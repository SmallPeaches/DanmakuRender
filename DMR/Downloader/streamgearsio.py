import json
import time
import logging
import signal
import threading
import subprocess
import sys
from datetime import datetime
from os.path import splitext, split, join, exists

from DMR.utils import ToolsList
from DMR.LiveAPI import Onair

class StreamgearsDownloader():
    default_header = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'User-Agent': 'Mozilla/5.0 (Linux; Android 5.0; SM-G900P Build/LRX21T) AppleWebKit/537.36 '
                            '(KHTML, like Gecko) Chrome/75.0.3770.100 Mobile Safari/537.36 '
        }
    def __init__(self, 
                 stream_url:str, 
                 segment:int,
                 output:str,
                 url:str,
                 taskname:str,
                 debug=False,
                 header:dict=None,
                 callback=None,
                 **kwargs):
        self.stream_url = stream_url
        self.header = header if header else self.default_header
        self.output = output
        self.segment = segment
        self.debug = debug
        self.taskname = taskname
        self.url = url
        self.callback = callback
        self.kwargs = kwargs

        if isinstance(self.stream_url, str):
            self.stable = True
        else:
            self.stable = False
        self.stoped = False
    
    def extract_stream(self) -> tuple:
        if self.stable:
            stream_url = self.stream_url
            header = self.header
        else:
            stream_url = self.stream_url()
            header = self.header()
        return stream_url, header
    
    def start_helper(self):
        raw_name = join(split(self.output)[0], f'{self.taskname}-%Y%m%d%H%M%S')
        pythonpath = sys.executable
        stream_url, header = self.extract_stream()

        if '.m3u8' in stream_url:
            raise RuntimeError('HLS流不支持使用streamgears下载，请修改下载引擎为ffmpeg')

        streamgears_args = [
            pythonpath, 
            'DMR/Downloader/streamgears_wrapper.py',
            '-i', stream_url,
            '-o', raw_name, 
            '-s', self.segment,
            '--header', json.dumps(header),
        ]
        streamgears_args = [str(x) for x in streamgears_args]
        logging.debug(f'Stream-gears downloader args: {streamgears_args}')

        if self.debug:
            self.streamgears_proc = subprocess.Popen(streamgears_args, stdin=subprocess.PIPE, stdout=sys.stdout, stderr=subprocess.STDOUT)
        else:
            self.streamgears_proc = subprocess.Popen(streamgears_args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

        if self.debug:
            self.streamgears_proc.wait()
            return
        
        self.thisfile = None
        line = ''
        while not self.stoped:
            if not self.streamgears_proc.stdout.readable():
                break
            if self.streamgears_proc.poll() is not None:
                logging.debug('stream-gears exit.')
                break

            out = self.streamgears_proc.stdout.readline()
            line = out.decode('utf-8',errors='ignore').strip()
            if not line:
                continue

            if 'create flv file' in line:
                fname = line.split('create flv file ')[-1]
                if fname.endswith('.part'):
                    fname = fname[:-5]
                if self.thisfile and self.thisfile != fname:
                    time.sleep(5)
                    self.callback(self.thisfile)
                self.thisfile = fname
            logging.debug(f'{self.taskname} streamgears: {line}')


        if Onair(self.url):
            raise RuntimeError(f'{self.taskname} Stream-gears 异常退出 {line}.')

    def start(self):
        return self.start_helper()
    
    def stop(self):
        self.stoped = True
        try:
            self.streamgears_proc.kill()
        except Exception as e:
            logging.debug(e)
        finally:
            out, _ = self.streamgears_proc.communicate(timeout=0.1)
            if out: 
                logging.debug(f'{self.taskname} streamgears: {out}')

        if exists(self.thisfile+'.part'):
            self.callback(self.thisfile+'.part')
        else:
            self.callback(self.thisfile)
        logging.debug('Stream-gears downloader stoped.')