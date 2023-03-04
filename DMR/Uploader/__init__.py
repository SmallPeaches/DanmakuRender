import logging
import threading
import queue
import importlib
import warnings

from DMR.message import PipeMessage
from DMR.utils import FFprobe

class Uploader():
    def __init__(self, name, pipe, uploader_config, debug=False):
        self.uploader_config = uploader_config
        self.debug = debug
        self.name = name
        self.sender = pipe
        self.uploading = False

        pkg = importlib.import_module(f"DMR.Uploader.{uploader_config['engine']}")
        self.uploader = getattr(pkg,uploader_config['engine'])(debug=self.debug, name=name, **uploader_config)
        self.wait_queue = queue.Queue()
        self.video_buffer = {}

    def pipeSend(self,msg,type='info',**kwargs):
        if self.sender:
            self.sender.put(PipeMessage('uploader',msg=msg,type=type,**kwargs))
        else:
            print(PipeMessage('uploader',msg=msg,type=type,**kwargs))

    def upload_queue(self):
        while not self.stoped:
            task = self.wait_queue.get()
            self.uploading = True
            logging.info(f'正在上传: {task[0]["group"]}')
            logging.debug(f'uploading: {task}')
            try:
                status = self.uploader.upload_batch(task)
                if status == True:
                    self.pipeSend(task[0]['group'], status)
            except KeyboardInterrupt:
                self.stop()
            except Exception as e:
                logging.exception(e)
                self.pipeSend(task[0]['group'],'error',desc=e)
            self.uploading = False

    def start(self):
        self.stoped = False
        thread = threading.Thread(target=self.upload_queue,daemon=True)
        thread.start()
        return thread

    def add(self, video, group=None, video_info=None, **kwargs):
        if video == 'end':
            task = self.video_buffer.pop(group,0)
            if task:
                self.wait_queue.put(task)
            if self.uploading:
                logging.warn('视频上传速度慢于录制速度，可能导致队列阻塞.')
        else:
            if not self.video_buffer.get(group):
                self.video_buffer[group] = []

            min_length = kwargs.get('min_length')
            if FFprobe.get_duration(video) > min_length:
                task = {
                    'video': video,
                    'group': group,
                    'video_info': video_info,
                    'kwargs': kwargs
                }
                self.video_buffer[group].append(task)

    def stop(self):
        self.stoped = True
        if self.uploading:
            warnings.warn('上传被终止，可能导致部分文件未能上传完成.')
        try:
            self.uploader.stop()
        except Exception as e:
            logging.debug(e)
