import json
from datetime import datetime
import logging
import os
import threading
import queue
from concurrent.futures import ThreadPoolExecutor
from os.path import join, exists
from typing import Tuple

from DMR.utils import VideoInfo, DateTimeEncoder, DateTimeDecoder, uuid, PipeMessage


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
        self.failed_tasks = {}
        self.failed_tasks_file = '.temp/failed_renders.json'
        self.load_failed_tasks()

        self._render_class = {}
        self.render_executors = ThreadPoolExecutor(max_workers=self.nrenders)
        self._lock = threading.Lock()

    def load_failed_tasks(self):
        if exists(self.failed_tasks_file):
            try:
                with open(self.failed_tasks_file, 'r', encoding='utf-8') as f:
                    data = json.load(f, cls=DateTimeDecoder)
                    for uuid, task in data.items():
                        if task.get('video'):
                            task['video'] = VideoInfo(**task['video'])
                            # Update config as well
                            # if 'config' in task and 'video' in task['config']:
                            #     task['config']['video'] = task['video']
                        self.failed_tasks[uuid] = task
                self.logger.info(f'Loaded {len(self.failed_tasks)} failed render tasks.')
            except Exception as e:
                self.logger.error(f'Failed to load failed tasks: {e}')

    def save_failed_tasks(self):
        try:
            with open(self.failed_tasks_file, 'w', encoding='utf-8') as f:
                json.dump(self.failed_tasks, f, cls=DateTimeEncoder, ensure_ascii=False, indent=4)
        except Exception as e:
            self.logger.error(f'Failed to save failed tasks: {e}')

    def retry_task(self, uuid):
        with self._lock:
            if uuid in self.failed_tasks:
                task = self.failed_tasks.pop(uuid)
                self.save_failed_tasks()
                
                # Re-submit
                task['status'] = 'waiting'
                self.render_tasks[task['uuid']] = task
                self.render_executors.submit(self._render_subprocess, task)
                return True
            return False

    def delete_failed_task(self, uuid):
        with self._lock:
            if uuid in self.failed_tasks:
                self.failed_tasks.pop(uuid)
                self.save_failed_tasks()
                return True
            return False

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
                # 'config': config,
                'status': 'waiting',
            }
            self.render_tasks[task['uuid']] = task
            self.render_executors.submit(self._render_subprocess, task)

    def _gather(self, task, status, desc=''):
        with self._lock:
            self.render_tasks.pop(task['uuid'], None)
            if status == 'error':
                self.failed_tasks[task['uuid']] = task
                self.save_failed_tasks()

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
                        # 'config': task['config'],
                        'output': desc,
                    },
                )

    def _render_subprocess(self, task):
        task['status'] = 'rendering'
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

            self._render_class[task['uuid']] = target_render
            status, info = target_render.render_one(video=video, output=output)
            self._render_class.pop(task['uuid'])

            if status:
                self._gather(task, 'info', desc=info)
            else:
                self._gather(task, 'error', desc=info)
        except KeyboardInterrupt:
            target_render.stop()
        except Exception as e:
            self.logger.exception(e)
            self._gather(task, 'error', desc=e)

    def stop(self):
        self.stoped = True
        for uuid, render in self._render_class.items():
            render.stop()
        self.render_executors.shutdown(wait=False)
        
        with self._lock:
            for uuid, task in self.render_tasks.items():
                if uuid not in self.failed_tasks:
                    self.failed_tasks[uuid] = task
            self.save_failed_tasks()

        self.logger.info('Render stopped.')
