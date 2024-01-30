from datetime import datetime
import logging
import os
import threading
import queue
from concurrent.futures import ThreadPoolExecutor
from os.path import join, exists

from DMR.LiveAPI import *
from DMR.utils import *

class Render():
    def __init__(self,
                 pipe:Tuple[queue.Queue, queue.Queue],
                 nrenders:int=1,
                 **kwargs,
                 ) -> None:
        
        self.nrenders = int(nrenders)
        self.send_queue, self.recv_queue = pipe
        self.logger = logging.getLogger(__name__)
        self.kwargs = kwargs
        self.stoped = True

        self._piperecvprocess = None
        self.render_tasks = {}
        self.render_executors = ThreadPoolExecutor(max_workers=self.nrenders)
        self._lock = threading.Lock()

    def _pipeSend(self, event, msg, target='engine', dtype=None, data=None, **kwargs):
        if self.send_queue:
            msg = PipeMessage(
                source='render',
                target=target,
                event=event,
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
                if message.target == 'render':
                   if message.event == 'newtask':
                       self.add_task(message)
            except Exception as e:
                self.logger.error(f'Message:{message} raise an error.')
                self.logger.exception(e)
    
    def start(self):
        self.stoped = False
        self._piperecvprocess = threading.Thread(target=self._pipeRecvMonitor, daemon=True)
        self._piperecvprocess.start()

    def add_task(self, msg:PipeMessage):
        with self._lock:
            config = msg.data
            source = msg.source
            request_id = msg.request_id
            task = {
                'uuid': uuid(),
                'source': source,
                'request_id': request_id,
                'mode': config.get('mode', 'dmrender'),
                'args': config.get('args', {}),
                'video': config.get('video'),
                'output': config.get('output'),
                'config': config,
            }
            self.render_tasks[task['uuid']] = task
            self.render_executors.submit(self._render_subprocess, task)

    def _gather(self, task, status, desc=''):
        with self._lock:
            self.render_tasks.pop(task['uuid'])
            if status == 'error':
                self._pipeSend(
                    event='error',
                    msg=f"渲染视频{task['output']}时出现错误: {desc}",
                    target=task['source'],
                    request_id=task['request_id'],
                    dtype=str(type(desc)),
                    data=desc,
                )
            else:
                self._pipeSend(
                    event='end',
                    msg=f"视频{task['output']}渲染完成",
                    target=task['source'],
                    request_id=task['request_id'],
                    dtype='dict',
                    data={
                        'config': task['config'],
                        'output': desc,
                    },
                )

    def _render_subprocess(self, task):
        try:
            render_args = task['args']
            mode:str = task['mode']
            video:VideoInfo = task.get('video')
            output:str = task.get('output')

            if mode == 'dmrender':
                from .dmrender import DmRender as TargetRender
            elif mode == 'transcode':
                from .transcode import Transcoder as TargetRender
            elif mode == 'rawffmpeg':
                raise NotImplementedError
                from .ffmpeg import RawFFmpegRender as TargetRender
            
            target_render = TargetRender(**render_args)
            self.logger.info(f'正在渲染: {video.path}')
            os.makedirs(os.path.dirname(output), exist_ok=True)

            status, info = target_render.render_one(video=video, output=output)
            if status:
                self._gather(task, 'info', desc=info)
            else:
                self._gather(task, 'error', desc=info)
        except KeyboardInterrupt:
            target_render.stop()
        except Exception as e:
            self.logger.exception(e)
            self._gather(task, 'error', desc=e)
