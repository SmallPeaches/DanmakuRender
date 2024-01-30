import json
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
                 **kwargs):
        
        self.stream_url = stream_url
        self.header = header if header else self.default_header
        self.output_dir = output_dir
        self.segment = segment
        self.debug = debug
        self.taskname = taskname
        self.url = url
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

        if self.debug:
            self.streamgears_proc = subprocess.Popen(streamgears_args, stdin=subprocess.PIPE, stdout=sys.stdout, stderr=subprocess.STDOUT, bufsize=10**8)
            self.streamgears_proc.wait()
            return

        # with tempfile.TemporaryFile() as logfile:
        with open('.temp/test.log', 'wb') as logfile:
            self.streamgears_proc = subprocess.Popen(streamgears_args, stdin=subprocess.PIPE, stdout=logfile, stderr=subprocess.STDOUT, bufsize=10**8)
            self.lastfile = None
            while not self.stoped:
                if self.streamgears_proc.poll() is not None:
                    break

                files = sorted(glob.glob(join(self.output_dir, f'*{self.uuid}*')))
                try:
                    pos = files.index(self.lastfile)
                except ValueError:
                    pos = -1
                # 最后一个文件是正在录制的不能认为是录制好的，这里要-2
                if pos < len(files)-2:
                    for p in range(pos+1, len(files)-1):
                        self.lastfile = files[p]
                        self.segment_callback(self.lastfile)
                time.sleep(10)
            
            if not self.stoped and Onair(self.url):
                logfile.seek(0)
                log = logfile.read().decode('utf8', errors='ignore')
                raise RuntimeError(f'{self.taskname} Stream-gears 异常退出 {log}.')

    def start(self):
        # 生成一个uuid，用于标记这次录制的文件
        self.uuid = uuid(16)
        return self.start_helper()
    
    def stop(self):
        self.stoped = True
        try:
            self.streamgears_proc.kill()
        except Exception as e:
            self.logger.debug(e)
        finally:
            out, _ = self.streamgears_proc.communicate(timeout=0.1)
            if out: 
                self.logger.debug(f'{self.taskname} streamgears: {out}')

        files = sorted(glob.glob(join(self.output_dir, f'*{self.uuid}*')))
        try:
            pos = files.index(self.lastfile)
        except ValueError:
            pos = -1
        # 结束时最后一个文件也要算在内
        if pos < len(files)-1:
            for p in range(pos+1, len(files)):
                self.lastfile = files[p]
                self.segment_callback(self.lastfile)
        
        self.logger.debug('Stream-gears downloader stoped.')