from datetime import datetime
import logging
import signal
import threading
import subprocess
import sys
from os.path import splitext, split, join, exists
import time

from DMR.utils import ToolsList
from DMR.LiveAPI import Onair

class BiliuprsDownloader():
    def __init__(self, 
                 stream_url:str, 
                 segment:int,
                 output:str,
                 url:str,
                 taskname:str,
                 biliup:str=None, 
                 debug=False,
                 header:dict=None,
                 callback=None,
                 **kwargs):
        self.output = output
        self.segment = segment
        self.debug = debug
        self.taskname = taskname
        self.url = url
        self.callback = callback
        self.kwargs = kwargs

        self.biliup = biliup if biliup else ToolsList.get('biliup')
        self.stoped = False
    
    def start_helper(self):
        raw_name = join(split(self.output)[0], f'{self.taskname}-%Y%m%d%H%M%S')
        biliup_args = [
            self.biliup, 
            'download',
            '-o', raw_name,
        ]
        if self.segment > 0:
            biliup_args += ['--split-time', str(self.segment)+'sec']
        biliup_args += [self.url]

        logging.debug(f'biliuprs downloader args: {biliup_args}')
        if self.debug:
            self.biliup_proc = subprocess.Popen(biliup_args, stdin=subprocess.PIPE, stdout=sys.stdout, stderr=subprocess.STDOUT)
        else:
            self.biliup_proc = subprocess.Popen(biliup_args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

        if self.debug:
            self.biliup_proc.wait()
            return
        
        self.thisfile = None
        while not self.stoped:
            if not self.biliup_proc.stdout.readable():
                break
            out = self.biliup_proc.stdout.readline()
            line = out.decode('utf-8',errors='ignore').strip()
            if not line:
                continue

            if 'create flv file' in line:
                fname = line.split('create flv file ')[-1]
                if fname.endswith('.part'):
                    fname = fname[:-5]
                if self.thisfile:
                    time.sleep(1)
                    self.callback(self.thisfile)
                self.thisfile = fname
                logging.debug(f'{self.taskname} biliup downloader: {line}')

        if Onair(self.url):
            raise RuntimeError('Biliuprs 异常退出.')

    def start(self):
        return self.start_helper()
    
    def stop(self):
        self.stoped = True
        try:
            if sys.platform == 'win32':
                SIGNAL_INT = signal.CTRL_C_EVENT
            else:
                SIGNAL_INT = signal.SIGINT
            self.biliup_proc.send_signal(SIGNAL_INT)
            self.biliup_proc.wait(5)
        except Exception as e:
            self.biliup_proc.kill()
            logging.debug(e)
        if exists(self.thisfile+'.part'):
            self.callback(self.thisfile+'.part')
        else:
            self.callback(self.thisfile)
        logging.debug('biliuprs downloader stoped.')