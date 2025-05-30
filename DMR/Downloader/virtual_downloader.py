import glob
import logging
import os
import queue
import re
import threading
import time
import shutil

from os.path import *
from DMR.utils import *


class VirtualDownloaderTask:
    def __init__(
        self,
        taskname: str,
        send_queue:queue.Queue,
        input_dir: str,
        output_dir: str=None,
        video_pattern: str=None,
        info_pattern: dict=None,
        segment_wait_time: int=1,
        stop_wait_time: int=5,
        start_time: datetime=None,
        advanced_video_args: dict=None,
        extra_info: dict=None,
        **kwargs,
    ):
        self.taskname = taskname
        self.send_queue = send_queue
        self.input_dir = input_dir
        self.output_dir = output_dir
        self.video_pattern = video_pattern or r'.*\.(mp4|mkv|avi|flv|mov|ts)$'
        self.info_pattern = info_pattern or {}
        self.extra_info = extra_info or {}
        self.segment_wait_time = segment_wait_time*60
        self.stop_wait_time = stop_wait_time*60
        self.start_time = datetime.strptime(start_time, '%Y-%m-%d %H:%M:%S').timestamp() if start_time else None
        self.advanced_video_args = advanced_video_args if advanced_video_args else {}

        self.stoped = True
        self.logger = logging.getLogger(__name__)

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

    def find_files(self):
        videofiles = []
        for file in os.listdir(self.input_dir):
            if isfile(join(self.input_dir, file)):
                videofiles.append(file)

        videofiles = sorted(videofiles)
        for file in videofiles:
            file_path = join(self.input_dir, file)
            ctime = getctime(file_path)
            mtime = getmtime(file_path)
            # Check if the file is a video file
            if not re.match(self.video_pattern, file):
                continue
            # 过老的视频
            if ctime < self.start_time:
                continue
            # 还在录制的视频
            if mtime > time.time() - self.segment_wait_time:
                continue

            width, height = FFprobe.get_resolution(file_path)
            if not (width and height):
                default_resolution = self.advanced_video_args.get('default_resolution', (1920, 1080))
                self.logger.warning(f'无法获取视频大小，使用默认值 {default_resolution}.')
                width, height = default_resolution

            video_info = VideoInfo(
                file_id=uuid(),
                dtype='src_video',
                path=file_path,
                group_id=self.sess_id,
                segment_id=len(self.sess_videos) + 1,
                size=getsize(file_path),
                ctime=ctime,
                duration=mtime-ctime,
                resolution=(width, height),
                title=splitext(file)[0],
                streamer=StreamerInfo(
                    name=self.taskname,
                ),
                taskname=self.taskname,
            )

            if name_pattern := self.info_pattern.get('name'):
                name_match = re.search(name_pattern, file)
                if name_match:
                    video_info.streamer.name = name_match.group(1)
            if title_pattern := self.info_pattern.get('title'):
                title_match = re.search(title_pattern, file)
                if title_match:
                    video_info.title = title_match.group(1)
            if self.info_pattern.get('danmaku'):
                dm_file = splitext(file_path)[0] + '.ass'
                if exists(dm_file):
                    video_info.dm_file_id = dm_file
            try:
                time_str_pattern = self.info_pattern.get('time_str')
                time_format = self.info_pattern.get('time_format')
                if time_str_pattern and time_format:
                    time_match = re.search(time_str_pattern, file)
                    video_info.ctime = datetime.strptime(time_match.group(1), time_format)
            except Exception as e:
                self.logger.error(f"Error parsing time string: {e}")
            
            min_video_size = self.advanced_video_args.get('min_video_size')
            min_video_duration = self.advanced_video_args.get('min_video_duration')
            if (min_video_size and video_info.size < min_video_size *1024*1024) \
                or (min_video_duration and video_info.duration < min_video_duration):
                self.logger.info(f'视频 {video_info.path} 过小, 设置 {min_video_size}MB {min_video_duration}s,'
                                f'实际 {video_info.size/1024/1024:.2f}MB {video_info.duration}s')
                continue

            if self.output_dir:
                output_file = join(self.output_dir, file)
                if not exists(self.output_dir):
                    os.makedirs(self.output_dir, exist_ok=True)
                if exists(output_file):
                    cnt = len(glob.glob(splitext(output_file)[0] + '*'))
                    output_file = splitext(output_file)[0] + f'({cnt})' + splitext(output_file)[1]
                shutil.copy2(file_path, output_file)
                video_info.path = output_file

            self._pipeSend(event='livesegment', msg=f'视频分段 {video_info.path} 录制完成.', target=f'replay/{self.taskname}', dtype='VideoInfo', data=video_info)
            self.sess_videos.append(video_info)

    def fake_onair(self):
        max_mtime = 0
        for file in os.listdir(self.input_dir):
            file_path = join(self.input_dir, file)
            ctime = getctime(file_path)
            mtime = getmtime(file_path)
            # Check if the file is a video file
            if not (isfile(file_path) and re.match(self.video_pattern, file)):
                continue
            # 过老的视频
            if ctime < self.start_time:
                continue
            max_mtime = max(max_mtime, mtime)

        if max_mtime and max_mtime > time.time() - self.stop_wait_time:
            return True
        else:
            return False
        
    def start_helper(self):
        self.onair = False
        self.start_time = self.start_time or time.time()
        self.sess_id = uuid(8)
        self.sess_videos = []

        while not self.stoped:
            try:
                if self.fake_onair() and not self.onair:
                    self.onair = True
                    self._pipeSend('livestart', '直播开始', dtype='str', data=self.sess_id)
                elif not self.fake_onair() and self.onair:
                    self.onair = False
                    self.start_time = time.time()
                    self.sess_id = uuid(8)
                    self.sess_videos = []
                    self._pipeSend('liveend', '直播结束', dtype='str', data=self.sess_id)
                
                if self.onair:
                    self.find_files()

            except Exception as e:
                self.logger.error(f"Error in VirtualDownloader {self.taskname}: {e}")
                self.logger.exception(e)

            time.sleep(30)
    
    def start(self):
        self.stoped = False
        self.thread = threading.Thread(target=self.start_helper, daemon=True)
        self.thread.start()

    def stop(self):
        self.stoped = True
        self._pipeSend('livestop', '录制终止', dtype='str', data=self.sess_id if hasattr(self, 'sess_id') else None)
        self.logger.info(f"VirtualDownloader {self.taskname} stopped.")
