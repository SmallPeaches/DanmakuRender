import logging
import threading
import queue
import time
from concurrent.futures import ThreadPoolExecutor
from os.path import join, exists
from DMR.LiveAPI import *
from DMR.utils import *

class Uploader():
    def __init__(self,
                 pipe:Tuple[queue.Queue, queue.Queue],
                 nuploaders:int=1,
                 **kwargs,
                 ) -> None:
        
        self.nuploaders = int(nuploaders)
        self.send_queue, self.recv_queue = pipe
        self.logger = logging.getLogger(__name__)
        self.kwargs = kwargs

        self.stoped = True
        self._piperecvprocess = None
        self._uploader_pool = {}
        self.upload_tasks = {}
        self.upload_executors = ThreadPoolExecutor(max_workers=self.nuploaders)
        self._lock = threading.Lock()

    def _pipeSend(self, event, msg, target='engine', request_id=None, dtype=None, data=None, **kwargs):
        if self.send_queue:
            msg = PipeMessage(
                source='uploader',
                target=target,
                event=event,
                request_id=request_id,
                msg=msg,
                dtype=dtype,
                data=data,
                **kwargs,
            )
            self.send_queue.put(msg)

    def _pipeRecvMonitor(self):
        while self.stoped == False and self.recv_queue is not None:
            message:PipeMessage = self.recv_queue.get()
            try:
                if message.target == 'uploader':
                    if message.event == 'newtask':
                        self.add_task(message)
            except Exception as e:
                self.logger.error(f'Message:{message} raise an error.')
                self.logger.exception(e)

    def start(self):
        self.stoped = False
        self._piperecvprocess = threading.Thread(target=self._pipeRecvMonitor, daemon=True)
        self._piperecvprocess.start()

    def _free_uploader_pool(self):
        with self._lock:
            for upload_group in list(self._uploader_pool.keys()):
                expire = self._uploader_pool[upload_group]['expire']
                if expire > 0 and time.time() - self._uploader_pool[upload_group]['ctime'] > expire:
                    self._uploader_pool[upload_group]['class'].stop()
                    self._uploader_pool.pop(upload_group)

    def add_task(self, msg:PipeMessage):
        with self._lock:
            config = msg.data
            task = {
                'uuid': uuid(),
                'source': msg.source,
                'request_id': msg.request_id,
                'stateless': config.get('stateless', True),
                'upload_group': config.get('upload_group'),
                'engine': config.get('engine', 'biliuprs'),
                'args': config.get('args', {}),
                'files': config.get('files'),
                'config': config,
            }
            self.upload_tasks[task['uuid']] = task
            self.upload_executors.submit(self._upload_subprocess, task)

    def _gather(self, task, status, desc=''):
        with self._lock:
            self.upload_tasks.pop(task['uuid'])
            if status == 'error':
                self._pipeSend(
                    event='error',
                    msg=f"上传视频 {[f.path for f in task['files']]} 时出现错误:{desc}",
                    target=task['source'],
                    request_id=task['request_id'],
                    dtype=str(type(desc)),
                    data=desc,
                )
            else:
                self._pipeSend(
                    event='end',
                    msg=f"视频 {[f.path for f in task['files']]} 上传完成: {desc}",
                    target=task['source'],
                    request_id=task['request_id'],
                    dtype='dict',
                    data={
                        'config': task['config'],
                    },
                )

    def _upload_subprocess(self, task):
        try:
            upload_args = task['args']
            stateless = task['stateless']
            upload_group:str = task['upload_group']

            with self._lock:
                if not stateless and upload_group in self._uploader_pool:
                    target_uploader = self._uploader_pool[upload_group]['class']
                    self._uploader_pool[upload_group]['ctime'] = time.time()
                else:
                    engine:str = task['engine']
                    if engine == 'biliuprs':
                        from .biliuprs import biliuprs as TargetUploader
                    else:
                        raise ValueError(f'Unknown engine: {engine}')
                    
                    target_uploader = TargetUploader(**upload_args)
                    self._uploader_pool[upload_group] = {
                        'class': target_uploader,
                        'ctime': time.time(),
                        'expire': task.get('expire', 86400)
                    }

            files = task['files']
            retry = upload_args.get('retry', 0)
            status = info = None
            while retry >= 0:
                try:
                    self.logger.info(f"正在上传 {[f.path for f in files]} 至 {upload_args['account']}")
                    # logging.debug(task)
                    status, info = target_uploader.upload(files=files, **upload_args)
                except KeyboardInterrupt:
                    target_uploader.stop()
                    self.stop()
                    return
                except Exception as e:
                    status, info = False, e
                    self.logger.exception(e)
                
                if status:
                    break
                else:
                    self.logger.warn(f'上传 {[f.path for f in files]} 时出现错误，即将重传.')
                    self.logger.debug(info)
                    time.sleep(60)
                    retry -= 1
            
            if status:
                self._gather(task, 'info', desc=info)
            else:
                self._gather(task, 'error', desc=info)

            if stateless:
                with self._lock:
                    self._uploader_pool.pop(upload_group)
            else:
                self._free_uploader_pool()
        
        except Exception as e:
            self.logger.exception(e)
            self._gather(task, 'error', desc=e)

    def stop(self):
        pass
