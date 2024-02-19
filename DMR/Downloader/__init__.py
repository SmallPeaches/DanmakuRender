import logging
import os
import queue
import threading

from DMR.utils import *

class Downloader():
    def __init__(self,
                 pipe:Tuple[queue.Queue, queue.Queue],
                 **kwargs,
                 ) -> None:
        self.send_queue, self.recv_queue = pipe
        self.logger = logging.getLogger('DMR.Downloader')
        self.kwargs = kwargs
        self.stoped = True

        self._piperecvprocess = None
        self.download_tasks = {}
    
    def _pipeSend(self, event, msg, target='engine', dtype=None, data=None, **kwargs):
        if self.send_queue:
            msg = PipeMessage(
                source='downloader',
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
                if message.target == 'downloader':
                    if message.event == 'stoptask':
                        self.stoptask(message.data)
                    elif message.event == 'newtask':
                        self.newtask(message)
                    elif message.event == 'exit':
                        break
            except Exception as e:
                self.logger.error(f'Message:{message} raise an error.')
                self.logger.exception(e)
        
    def stoptask(self, taskname:str):
        if taskname in self.download_tasks:
            self.download_tasks[taskname].stop()
            del self.download_tasks[taskname]
            self._pipeSend(event='info', msg=f'下载任务 {taskname} 已停止。', dtype='str', data=taskname)
        else:
            raise ValueError(f'下载任务 {taskname} 不存在。')
        
    def newtask(self, message:PipeMessage):
        taskname = message.data['taskname']
        dltype = message.data['dltype']
        config = message.data['config']
        if taskname in self.download_tasks:
            raise ValueError(f'下载任务 {taskname} 已存在。')
        
        if dltype == 'live':
            from .stream_downloader import StreamDownloadTask
            downloader_task = StreamDownloadTask
        elif dltype == 'videos':
            from .video_downloader import VideoDownloadTask
            downloader_task = VideoDownloadTask
        
        self.download_tasks[taskname] = downloader_task(taskname=taskname, send_queue=self.send_queue, **config)
        self.download_tasks[taskname].start()
        self._pipeSend(event='info', msg=f'下载任务 {taskname} 已启动。', dtype='str', data=taskname)
        
    def start(self):
        self.stoped = False
        self._piperecvprocess = threading.Thread(target=self._pipeRecvMonitor, daemon=True)
        self._piperecvprocess.start()

    def stop(self):
        self.stoped = True
        self.recv_queue.put(PipeMessage(source='downloader', target='downloader', event='exit'))
        for taskname in list(self.download_tasks.keys()):
            self.stoptask(taskname)
        self.logger.info('Downloader stoped.')
        self._pipeSend(event='info', msg='下载器已停止.')
