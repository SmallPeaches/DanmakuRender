import math
import os, json, subprocess
import shutil
import logging
import glob
import tempfile
import threading

from datetime import datetime
from os.path import exists, join, splitext, split, isdir, isfile
from DMR.utils import *


class YtdlpDownloader:
    def __init__(
            self, 
            url:str,
            output_dir:str, 
            output_name:str=None,
            quality:int=None,
            segment_callback=None,
            start_time:str=None,
            end_time:str=None,
            check_interval:int=600,
            subprocess_timeout:int=3600,
            extra_args:list=None,
            debug=False, 
            **kwargs,
        ) -> None:
        self.url = url
        self.output_dir = output_dir
        self.output_name = output_name
        self.quality = quality
        self.start_time = datetime.strptime(start_time, '%Y-%m-%d %H:%M:%S') if start_time else None
        self.end_time = datetime.strptime(end_time, '%Y-%m-%d %H:%M:%S') if end_time else None
        self.extra_args = extra_args
        self.segment_callback = segment_callback
        self.check_interval = check_interval
        self.subprocess_timeout = subprocess_timeout or None
        self.debug = debug

        self.ytdl_proc = None
        self.logger = logging.getLogger(__name__)

    @staticmethod
    def _get_subtitle(path:str):
        for ext in ['.ass', '.xml', '.protobuf', '.srt']:
            dmfile = splitext(path)[0]+ext
            if exists(dmfile):
                return dmfile

    def download_once(
            self, 
            url, 
            output_dir:str, 
            output_name:str=None,
            quality:str=None,
            start_time:datetime=None,
            end_time:datetime=None,
            info_only:bool=False,
            extra_args:list=None,
            **kwargs,
        ):
        cmd = ['yt-dlp', '--ignore-config', '--color', 'never', '--force-overwrites']
        cmd += ['-o', join(output_dir, output_name)]
        
        if quality: cmd += ['--format', quality]
        if start_time: cmd += ['--dateafter', start_time.strftime('%Y%m%d')]
        if end_time: cmd += ['--datebefore', end_time.strftime('%Y%m%d')]
        if info_only: cmd += ['--dump-json']

        cmd += extra_args if extra_args is not None else []
        cmd += [url]
        cmd = [str(c) for c in cmd]

        if self.debug and not info_only:
            self.ytdl_proc = subprocess.Popen(cmd, stderr=subprocess.STDOUT)
            self.ytdl_proc.wait()
            return self.ytdl_proc.returncode == 0

        with tempfile.TemporaryFile() as tmpfile:
            self.ytdl_proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=tmpfile, stderr=subprocess.STDOUT)
            try:
                self.ytdl_proc.wait(self.subprocess_timeout)
            except subprocess.TimeoutExpired:
                self.logger.error(f'下载 {self.url} 超时')
                self.ytdl_proc.kill()
                return False

            tmpfile.seek(0)
            info = tmpfile.read().decode('utf8', errors='ignore')

            if info_only:
                info = [json.loads(i) for i in info.split('\n') if i.strip() != '']
                return info

            if self.ytdl_proc.returncode != 0 and not self.stoped:
                self.logger.error(f'下载 {self.url} 时出现错误: {info}')
                return False
            
            return True
    
    def download_directly(self):
        self.start_time = self.start_time or datetime.now()
        downloaded_today = []

        while not self.stoped:
            try:
                stime = datetime.now()
                if datetime.now().day != self.start_time.day:
                    downloaded_today = []
                
                os.makedirs(self.output_dir, exist_ok=True)
                output_name = self.output_name or '%(title)s.%(ext)s'
                info = self.download_once(
                    url=self.url, 
                    output_dir=self.output_dir, 
                    output_name=output_name,
                    quality=self.quality,
                    start_time=self.start_time,
                    end_time=self.end_time,
                    info_only=True,
                    extra_args=self.extra_args,
                )
                
                need_download_videos = [i for i in info if i['id'] not in downloaded_today]

                for yt_video in need_download_videos:
                    status = self.download_once(
                        url=yt_video['original_url'], 
                        output_dir=self.output_dir, 
                        output_name=output_name, 
                        quality=self.quality,
                        extra_args=self.extra_args,
                    )
                    if not status:  continue
                    video_info = VideoInfo(
                        file_id=uuid(),
                        path=yt_video['filename'],
                        dtype='src_video',
                        size=os.path.getsize(yt_video['filename']),
                        ctime=datetime.strptime(yt_video['upload_date'], '%Y%m%d'),
                        duration=yt_video['duration'],
                        resolution=(yt_video['width'], yt_video['height']),
                        title=yt_video['title'],
                        streamer=StreamerInfo(
                            name=yt_video['uploader'],
                            uid=yt_video['uploader_id'],
                            platform='youtube',
                            url=yt_video['uploader_url'],
                        ),
                        group_id=uuid(8),
                        segment_id=0,
                        dm_file_id=self._get_subtitle(yt_video['filename']),
                        desc=yt_video['description'],
                        tag=yt_video['tags'],
                        cover_url=yt_video['thumbnail'],
                    )
                    self.segment_callback(video_info)
                    downloaded_today.append(yt_video['id'])
                
                self.start_time = stime
            except Exception as e:
                self.logger.error(f'下载 {self.url} 时出现错误: {e}')
            
            if self.end_time and datetime.now() > self.end_time:
                self.stoped = True
                return 'finished'

            time.sleep(self.check_interval)

    def start(self):
        self.stoped = False
        return self.download_directly()
    
    def stop(self):
        self.stoped = True
        if self.ytdl_proc:
            self.ytdl_proc.kill()
        self.logger.info(f'下载 {self.url} 已停止。')
    