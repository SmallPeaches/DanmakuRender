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
                    self.logger.debug(f'Uploader {upload_group} expired and removed.')

    def add_task(self, msg:PipeMessage):
        with self._lock:
            config = msg.data
            file = config.get('files')[0]
            stream_queue = None
            if hasattr(file, 'stream_queue') and file.stream_queue is not None:
                stream_queue = file.stream_queue
            task = {
                'uuid': uuid(),
                'source': msg.source,
                'request_id': msg.request_id,
                'upload_group': config.get('upload_group'),
                'engine': config.get('engine', 'biliuprs'),
                'args': config.get('args', {}),
                'files': config.get('files'),
                'stream_queue': stream_queue,
                'config': config,
            }
            self.upload_tasks[task['uuid']] = task
            if stream_queue:
                threading.Thread(target=self._upload_subprocess, args=(task,), daemon=True).start()
            else:
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
            upload_group:str = task['upload_group']

            with self._lock:
                if upload_group in self._uploader_pool:
                    target_uploader = self._uploader_pool[upload_group]['class']
                    self._uploader_pool[upload_group]['ctime'] = time.time()
                else:
                    engine:str = task['engine']
                    if engine == 'biliuprs':
                        from .biliuprs import biliuprs as TargetUploader
                    elif engine == 'subprocess':
                        from .subprocess_uploader import SubprocessUploader as TargetUploader
                    elif engine == 'youtubev3':
                        from .youtubev3 import youtubev3 as TargetUploader
                    elif engine == 'biliwebapi':
                        from .biliwebapi import BiliWebApi as TargetUploader
                    else:
                        raise ValueError(f'Unknown engine: {engine}')
                    
                    target_uploader = TargetUploader(**upload_args)
                    self._uploader_pool[upload_group] = {
                        'class': target_uploader,
                        'ctime': time.time(),
                        'expire': task.get('expire', 7*24*3600)
                    }

            files = task['files']
            stream_queue = task.get('stream_queue', None)
            retry = upload_args.get('retry', 0)
            if stream_queue:
                retry = 0       # 流式上传无法重试
            status = info = None
            while retry >= 0:
                try:
                    if stream_queue:
                        self.logger.info(f"正在同步上传 {files[0].title} 至 {upload_args.get('account')}")
                    else:
                        self.logger.info(f"正在上传 {[f.path for f in files]} 至 {upload_args.get('account')}")
                    # logging.debug(task)
                    status, info = target_uploader.upload(files=files, stream_queue=stream_queue, **upload_args)
                except KeyboardInterrupt:
                    target_uploader.stop()
                    self.stop()
                    return
                except Exception as e:
                    status, info = False, e
                    self.logger.exception(e)
                
                retry -= 1
                if status or self.stoped:
                    break
                elif retry < 0:
                    self.logger.warning(f'上传 {[f.path for f in files]} 时出现错误，跳过上传.')
                    break
                else:
                    self.logger.warning(f'上传 {[f.path for f in files]} 时出现错误，即将重传.')
                    self.logger.debug(info)
                    time.sleep(60)
            
            if status:
                self._gather(task, 'info', desc=info)
            else:
                self._gather(task, 'error', desc=info)

            self._free_uploader_pool()
        
        except Exception as e:
            self.logger.exception(e)
            self._gather(task, 'error', desc=e)

    def stop(self):
        self.stoped = True
        self.upload_executors.shutdown(wait=False)
        for upload_group in self._uploader_pool:
            self._uploader_pool[upload_group]['class'].stop()
        self.logger.info('Uploader stopped.')
