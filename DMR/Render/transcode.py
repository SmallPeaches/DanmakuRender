import copy
import os
import platform
import sys
import subprocess
import logging
import tempfile

from os.path import exists
from .ffmpeg import RawFFmpegRender
from .baserender import BaseRender
from DMR.utils import *


class Transcoder(BaseRender):
    def __init__(self,
                 hwaccel_args: list,
                 vencoder: str,
                 vencoder_args: list,
                 aencoder: str,
                 aencoder_args: list,
                 output_resize: str,
                 advanced_render_args: dict=None,
                 ffmpeg: str = None,
                 debug=False,
                 **kwargs
                 ):
        self.hwaccel_args = hwaccel_args if hwaccel_args is not None else []
        self.vencoder = vencoder
        self.vencoder_args = vencoder_args
        self.aencoder = aencoder
        self.aencoder_args = aencoder_args
        self.output_resize = output_resize
        self.advanced_render_args = advanced_render_args if isinstance(advanced_render_args, dict) else {}
        self.ffmpeg = ffmpeg if ffmpeg else ToolsList.get('ffmpeg')
        self.debug = debug

        self.logger = logging.getLogger(__name__)
        self.raw_ffmpeg = RawFFmpegRender(debug=self.debug)

    def render_helper(self, video: str, output: str):
        ffmpeg_args = [self.ffmpeg, '-y']
        ffmpeg_args += self.hwaccel_args

        if self.output_resize:
            if 'x' in str(self.output_resize):
                scale_args = ['-s', self.output_resize]
            else:
                w, h = FFprobe.get_resolution(video)
                if not (h and w):
                    self.logger.warn(f'获取视频 {video} 分辨率失败, 将使用默认分辨率 1920x1080.')
                    w, h = 1920, 1080
                scale = float(self.output_resize)
                w, h = int(w*scale), int(h*scale)
                scale_args = ['-s', f'{w}x{h}']
        else:
            scale_args = []
        
        ffmpeg_args += [
            '-fflags', '+discardcorrupt',
            '-i', video,
            '-c:v', self.vencoder,
            *self.vencoder_args,
            '-c:a', self.aencoder,
            *self.aencoder_args,
            *scale_args,
            output,
        ]

        return self.raw_ffmpeg.call_ffmpeg(ffmpeg_args)

    def render_one(self, video: VideoInfo, output: str, **kwargs):
        if not exists(video.path):
            raise RuntimeError(f'不存在视频文件 {video}，跳过渲染.')

        start_time = datetime.now()
        status, info = self.render_helper(video.path, output, **kwargs)
        if status:
            output_info:VideoInfo = copy.deepcopy(video)
            output_info.path = output
            output_info.file_id = uuid()
            output_info.size = os.path.getsize(output)
            output_info.ctime = start_time
            output_info.src_video_id = video.file_id
            return status, output_info
        else:
            return status, info

    def stop(self):
        self.logger.debug('ffmpeg render stop.')
        self.raw_ffmpeg.stop()
