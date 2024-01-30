import os
import platform
import signal
import sys
import subprocess
import logging
import tempfile

from .baserender import BaseRender
from os.path import exists
from DMR.utils import *

class RawFFmpegRender(BaseRender):
    def __init__(self,
                 debug=False,
                 **kwargs
                 ):
        self.debug = debug
        self.logger = logging.getLogger(__name__)

    def call_ffmpeg(self, cmds, **kwargs):
        ffmpeg_args = [str(x) for x in cmds]
        self.logger.debug(f'ffmpeg render args: {ffmpeg_args}')

        with tempfile.TemporaryFile() as logfile:
            if self.debug:
                self.render_proc = subprocess.Popen(
                    ffmpeg_args, stdin=sys.stdin, stdout=sys.stdout, stderr=subprocess.STDOUT, bufsize=10**8)
            else:
                self.render_proc = subprocess.Popen(
                    ffmpeg_args, stdin=subprocess.PIPE, stdout=logfile, stderr=subprocess.STDOUT, bufsize=10**8)

            self.render_proc.wait()
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
            
    def render_one(self, cmds, **kwargs):
        start_time = datetime.now()
        status, info = self.call_ffmpeg(cmds, **kwargs)
        if status:
            output_info:VideoInfo = video.copy()
            output_info.path = output
            output_info.file_id = uuid()
            output_info.size = os.path.getsize(output)
            output_info.ctime = start_time
            output_info.src_video_id = video.file_id
            return status, output_info
        else:
            return status, info
            
    def stop(self):
        try:
            out, _ = self.render_proc.communicate(b'q', timeout=5)
            self.logger.debug(out)
        except subprocess.TimeoutExpired:
            self.render_proc.kill()
        except Exception as e:
            self.logger.debug(e)
