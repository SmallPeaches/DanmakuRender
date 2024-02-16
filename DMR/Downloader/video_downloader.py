import logging
import os
import queue
import threading
import time

from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from os.path import join,exists,splitext
from datetime import datetime
from DMR.LiveAPI import *
from DMR.utils import *


class VideoDownloadTask():
    def __init__(self, 
                 url, 
                 output_dir, 
                 output_name=None, 
                 engine=None, 
                 send_queue:queue.Queue=None, 
                 taskname=None, 
                 debug=False, 
                 **kwargs,
        ) -> None:
        self.taskname = taskname
        self.url = url
        self.output_dir = output_dir
        self.output_name = output_name
        self.send_queue = send_queue
        self.debug = debug
        self.engine = engine
        self.kwargs = kwargs

        self.logger = logging.getLogger(__name__)
        self.platfrom = get_platform(self.url)
        self.downloader = None
        if self.engine is None:
            if self.platfrom == 'bilibili':
                self.engine = 'yutto'
            elif self.platfrom == 'youtube':
                self.engine = 'yt-dlp'
    
    def _pipeSend(self, event, msg, target=None, dtype=None, data=None, **kwargs):
        if self.send_queue:
            target = target if target else f'replay/{self.taskname}'
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
    
    def _segment_callback(self, file_info:VideoInfo):
        filepath = file_info.path
        self._pipeSend(event='livesegment', msg=f'视频 {filepath} 录制完成.', target=f'replay/{self.taskname}', dtype='VideoInfo', data=file_info)
        self._pipeSend(event='liveend', msg=f'视频 {filepath} 录制完成.', target=f'replay/{self.taskname}', dtype='str', data=file_info.group_id)

    def start_helper(self):
        if self.engine == 'yutto':
            from .yutto import YuttoDownloader
            self.downloader = YuttoDownloader(
                url=self.url,
                output_dir=self.output_dir,
                output_name=self.output_name,
                segment_callback=self._segment_callback,
                **self.kwargs,
            )
        elif self.engine == 'yt-dlp':
            from .ytdlp import YtdlpDownloader
            self.downloader = YtdlpDownloader(
                url=self.url,
                output_dir=self.output_dir,
                output_name=self.output_name,
                segment_callback=self._segment_callback,
                **self.kwargs,
            )
        
        status = self.downloader.start()
        if status == 'finished':
            self._pipeSend(event='info', msg=f'下载任务 {self.taskname} 已经完成.', dtype='str', data=self.taskname)

    def start(self):
        t = threading.Thread(target=self.start_helper, daemon=True)
        t.start()
        return t