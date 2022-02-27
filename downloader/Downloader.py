from datetime import datetime
import logging
import queue
import subprocess
import sys
import threading
import multiprocessing
import asyncio
import time
from os.path import join
from downloader.getrealurl import get_stream_url
from downloader.danmaku import DanmakuClient
from tools.utils import onair
from .BaseRender import *


class Downloader():
    header = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'User-Agent': 'Mozilla/5.0 (Linux; Android 5.0; SM-G900P Build/LRX21T) AppleWebKit/537.36 '
                            '(KHTML, like Gecko) Chrome/75.0.3770.100 Mobile Safari/537.36 '
        }
    def __init__(self, url: str, name: str, save: str = './save', ffmpeg: str = 'tools/ffmpeg.exe', timeout: int = 30):
        self.danmu = []
        self.dmcnt = 0
        self._name = name
        self._url = url
        self._save = os.path.abspath(save)
        self._ffmpeg = ffmpeg
        self._timeout = timeout
        self._stop = False
        self.interrupt = multiprocessing.Queue()
        self.logger = logging.getLogger('main')
    
    @property
    def duration(self):
        return self._endTime - self._startTime if self._endTime else datetime.now().timestamp() - self._startTime

    def _set_ffmpeg(self,stream_url,args):
        ffmpeg_stream_args = []
        if args.discardcorrupt:
            ffmpeg_stream_args += ['-fflags', '+discardcorrupt']
        if args.use_wallclock_as_timestamps:
            ffmpeg_stream_args += ['-use_wallclock_as_timestamps','1']
        if args.reconnect:
            ffmpeg_stream_args += [
                        '-reconnect', '1',
                        '-reconnect_streamed', '1',
                        '-reconnect_delay_max', '20'
                        ]
        
        ffmpeg_args =   [
                        self._ffmpeg, '-y',
                        '-headers', ''.join('%s: %s\r\n' % x for x in self.header.items()),
                        *ffmpeg_stream_args,
                        '-thread_queue_size', '32',
                        '-i', stream_url,

                        '-c','copy'
                        ]
        
        if args.split > 0:
            fname = f'{self._name}-{time.strftime("%Y%m%d-%H%M%S",time.localtime())}-Part%03d.mp4'
            ffmpeg_args += ['-f','segment','-segment_time',str(args.split),'-movflags','frag_keyframe',join(self._save,fname)]
        else:
            fname = f'{self._name}-{time.strftime("%Y%m%d-%H%M%S",time.localtime())}.mp4'
            ffmpeg_args += ['-movflags','frag_keyframe',join(self._save,fname)]

        
        self.logger.debug('FFmpeg args:')
        self.logger.debug(ffmpeg_args)

        if args.debug:
            proc = subprocess.Popen(ffmpeg_args, stdin=subprocess.PIPE, stdout=sys.stdout, stderr=subprocess.STDOUT,bufsize=10**8)
        else:
            proc = subprocess.Popen(ffmpeg_args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,bufsize=10**8)
        
        return proc

    def start_helper(self,args):
        self.args = args
        if not os.path.exists(self._save):
            os.makedirs(self._save)

        stream_url = get_stream_url(self._url,args.flowtype)

        self._stop = False
        self._startTime = datetime.now().timestamp()
        self._endTime = 0
        
        self._ffmpeg_proc = self._set_ffmpeg(stream_url,args)

        self.logger.debug('DanmakuRender args:')
        self.logger.debug(self.args)

        ffmpeg_low_speed = 0
        m3u8_drop_cnt = 0
        timer_cnt = 1
        
        while not self._stop:
            if self._ffmpeg_proc.stdout is None:
                time.sleep(0.5)
            else:
                out = self._ffmpeg_proc.stdout.readline(200).decode('utf-8')
                log += out
                line = out.strip('\n')
                line_split = line.split('\r')
                if len(line_split) > 1:
                    info = line_split[1]
                    if 'frame=' in info:
                        print(f'\r正在录制{self._name}: {info}',end='')
                    
                    if self._ffmpeg_proc.poll() is not None:
                        self.logger.debug('FFmpeg exit.')
                        self.stop()
                        return log

            if self.duration > timer_cnt*60 and not self.args.debug:   
                self.logger.debug(f'FFmpeg output:{log}')

                if not args.disable_lowspeed_interrupt:
                    l = info.find('speed=')
                    r = info.find('x',l)
                    if l>0 and r>0:
                        speed = float(info[l:r][6:])
                        if speed < 0.9:
                            ffmpeg_low_speed += 1
                            self.logger.warn(f'直播流编码速度过慢, 请保证有足够的资源用于实时编码.')
                            if ffmpeg_low_speed >= 3:
                                self.logger.error('编码速度过慢, 即将重试.')
                                self.stop()
                                return 
                        else:
                            ffmpeg_low_speed = 0

                if '.m3u8' in stream_url:
                    if 'Opening' in log:
                        m3u8_drop_cnt = 0
                    else:
                        self.logger.warn(f'直播流读取错误, 请检查录制情况.')
                        m3u8_drop_cnt += 1
                        if m3u8_drop_cnt >= 3:
                            self.logger.error('直播流读取错误, 即将重试.')
                            self.stop()
                            return
                else:
                    if 'dropping it' in log:
                        self.logger.error('直播流读取错误, 即将重试, 如果此问题多次出现请反馈.')
                        self.stop()

                if not onair(self._url):
                    self.logger.debug('Live end.')
                    self.stop()

                log = ''
                timer_cnt += 1
        
        return 
    
    def start(self,args):
        try:
            rval = self.start_helper(args)
            return rval
        except KeyboardInterrupt:
            self.stop()
            self.logger.info('录制结束.')
            exit(0)

    def stop(self):
        self._stop = True
        try:
            self._ffmpeg_proc.stdin.flush()
        except Exception as e:
            self.logger.debug(e)
        try:
            out,_ = self._ffmpeg_proc.communicate(b'q')
            out = out.decode('utf-8')
            self.logger.debug(out)
        except Exception as e:
            self.logger.debug(e)

