import json
import logging
import subprocess
import sys
import os
import glob

from datetime import datetime
from os.path import splitext, split, join, exists
import tempfile
import time
from DMR.utils import *
from DMR.LiveAPI import Onair


class StreamgearsDownloader():
    default_header = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'User-Agent': 'Mozilla/5.0 (Linux; Android 5.0; SM-G900P Build/LRX21T) AppleWebKit/537.36 '
                            '(KHTML, like Gecko) Chrome/75.0.3770.100 Mobile Safari/537.36 '
        }
    def __init__(self,  
                 stream_url:str, 
                 output_dir:str,
                 segment:int,
                 url:str,
                 taskname:str,
                 debug=False,
                 header:dict=None,
                 segment_callback=None,
                 inprogress_callback=None,
                 **kwargs):
        
        self.stream_url = stream_url
        self.header = header if header else self.default_header
        self.output_dir = output_dir
        self.segment = segment
        self.debug = debug
        self.taskname = taskname
        self.url = url
        # 上报"正在写入"的文件，使录制中途被强杀后残file能被对账发现
        self.inprogress_callback = inprogress_callback
        self.segment_callback = segment_callback
        self.kwargs = kwargs

        self.logger = logging.getLogger(__name__)
        self.stoped = False
    
    def start_helper(self):
        raw_name = join(self.output_dir, f'[正在录制]{self.taskname}-%Y%m%d%H%M%S-{self.uuid}')
        stream_url, header = self.stream_url, self.header

        streamgears_args = [
            sys.executable, 
            'DMR/Downloader/streamgears_wrapper.py',
            '-i', stream_url,
            '-o', raw_name, 
            '-s', self.segment,
            '--header', json.dumps(header),
        ]

        streamgears_args = [str(x) for x in streamgears_args]
        self.logger.debug(f'Stream-gears downloader args: {streamgears_args}')

        # stdout 是 sys.stdout 或临时文件，都不是管道：Python 不会为其分配 bufsize
        # 指定的缓冲，原来的 bufsize=10**8 是无效参数（现已移除）。
        if self.debug:
            self.streamgears_proc = subprocess.Popen(streamgears_args, stdin=subprocess.PIPE, stdout=sys.stdout, stderr=subprocess.STDOUT)
            self.streamgears_proc.wait()
            return

        with tempfile.TemporaryFile(dir='.temp') as logfile:
        # with open('.temp/test.log', 'wb') as logfile:
            self.streamgears_proc = subprocess.Popen(streamgears_args, stdin=subprocess.PIPE, stdout=logfile, stderr=subprocess.STDOUT)
            while not self.stoped:
                if self.streamgears_proc.poll() is not None:
                    break

                files = sorted(glob.glob(join(self.output_dir, f'*{self.uuid}*')))
                # 列表最后一个文件是正在写入、尚未封闭的分段，上报它使中途被杀的
                # 残file有记录（仅在变化时上报，避免重复写库）
                if files and files[-1] != getattr(self, '_last_reported', None) \
                        and self.inprogress_callback:
                    self._last_reported = files[-1]
                    self.inprogress_callback(files[-1])
                # 最后一个文件不算在内
                for p in range(len(files)-1):
                    self.segment_callback(files[p])
                time.sleep(10)
            
            if not self.stoped and Onair(self.url):
                logfile.seek(0)
                log = logfile.read().decode('utf8', errors='ignore')
                raise RuntimeError(f'{self.taskname} Stream-gears 异常退出 {log[-1000:]}.')

    def start(self):
        # 生成一个uuid，用于标记这次录制的文件
        self.uuid = uuid(16)
        return self.start_helper()
    
    def stop(self):
        self.stoped = True
        try:
            self.streamgears_proc.kill()
            out, _ = self.streamgears_proc.communicate(timeout=0.1)
            if out: 
                self.logger.debug(f'{self.taskname} streamgears: {out}')
        except Exception as e:
            self.logger.debug(e)

        files = sorted(glob.glob(join(self.output_dir, f'*{self.uuid}*')))
        for p in range(len(files)):
            self.segment_callback(files[p])
        
        self.logger.debug('Stream-gears downloader stoped.')
