import os
import platform
import signal
import sys
import subprocess
import logging
import tempfile

from tools import ToolsList

from .baserender import BaseRender
from os.path import exists
from DMR.utils import *


class FFmpegRender(BaseRender):
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
        self.rendering = False
        self.hwaccel_args = hwaccel_args if hwaccel_args is not None else []
        self.vencoder = vencoder
        self.vencoder_args = vencoder_args
        self.aencoder = aencoder
        self.aencoder_args = aencoder_args
        self.output_resize = output_resize
        self.advanced_render_args = advanced_render_args if isinstance(advanced_render_args, dict) else {}
        self.ffmpeg = ffmpeg if ffmpeg else ToolsList.get('ffmpeg')
        self.debug = debug

    def render_helper(self, video: str, danmaku: str, output: str, to_stdout: bool = False, logfile=None):
        ffmpeg_args = [self.ffmpeg, '-y']
        ffmpeg_args += self.hwaccel_args

        # solve bili dash
        gop = self.advanced_render_args.get('gop', 5)
        if gop:
            try:
                fps = eval(FFprobe.run_ffprobe(video)['streams'][0]['avg_frame_rate'])
                gop = int(gop)
                dash_args = [
                    '-keyint_min', int(fps * gop),
                    '-g', int(fps * gop)
                ]
            except Exception as e:
                logging.warn(f'GOP 设置失败：{e}')
                dash_args = []
        else:
            dash_args = []

        if self.output_resize:
            if 'x' in str(self.output_resize):
                scale_args = ['-s', self.output_resize]
            else:
                w, h = FFprobe.get_resolution(video)
                if not (h and w):
                    logging.warn(f'获取视频 {video} 分辨率失败, 将使用默认分辨率 1920x1080.')
                    w, h = 1920, 1080
                scale = float(self.output_resize)
                w, h = int(w*scale), int(h*scale)
                scale_args = ['-s', f'{w}x{h}']
        else:
            scale_args = []

        if platform.system().lower() == 'windows':
            danmaku = danmaku.replace("\\", "/").replace(":/", "\\:/")
        
        # 自定义video filter
        if self.advanced_render_args.get('filter_complex'):
            filter_name = '-filter_complex'
            filter_str = self.advanced_render_args.get('filter_complex')
            filter_str = replace_keywords(filter_str, {'DANMAKU': danmaku})
        else:
            filter_name = '-vf'
            filter_str = 'subtitles=filename=\'%s\'' % danmaku
            fps = self.advanced_render_args.get('fps')
            if fps:
                filter_str += ',fps=fps=%i' % int(fps)
        
        ffmpeg_args += [
            '-fflags', '+discardcorrupt',
            '-i', video,
            *dash_args,
            filter_name, filter_str,

            '-c:v', self.vencoder,
            *self.vencoder_args,
            '-c:a', self.aencoder,
            *self.aencoder_args,
            *scale_args,
            output,
        ]

        ffmpeg_args = [str(x) for x in ffmpeg_args]
        logging.debug(f'ffmpeg render args: {ffmpeg_args}')

        if not logfile:
            logfile = tempfile.TemporaryFile()

        if to_stdout or self.debug:
            self.render_proc = subprocess.Popen(
                ffmpeg_args, stdin=sys.stdin, stdout=sys.stdout, stderr=subprocess.STDOUT, bufsize=10**8)
        else:
            self.render_proc = subprocess.Popen(
                ffmpeg_args, stdin=subprocess.PIPE, stdout=logfile, stderr=subprocess.STDOUT, bufsize=10**8)

        self.render_proc.wait()
        return logfile

    def render_one(self, video: str, danmaku: str, output: str, **kwargs):
        if not exists(video):
            raise RuntimeError(f'不存在视频文件 {video}，跳过渲染.')
        if not exists(danmaku):
            raise RuntimeError(f'不存在弹幕文件 {danmaku}，跳过渲染.')

        with tempfile.TemporaryFile() as logfile:
            self.render_helper(video, danmaku, output,
                               to_stdout=self.debug, logfile=logfile)
            if self.debug:
                return True, ''

            info = None
            log = ''
            logfile.seek(0)
            for line in logfile.readlines():
                line = line.decode('utf-8', errors='ignore').strip()
                log += line + '\n'
                if 'video:' in line:
                    info = line
            if info:
                return True, info
            else:
                return False, log

    def stop(self):
        logging.debug('ffmpeg render stop.')
        try:
            out, _ = self.render_proc.communicate(b'q', timeout=5)
            logging.debug(out)
        except subprocess.TimeoutExpired:
            self.render_proc.kill()
        except Exception as e:
            logging.debug(e)
