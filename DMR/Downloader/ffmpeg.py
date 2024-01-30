from datetime import datetime
import subprocess
import sys
import threading
import time
import queue
import logging
from os.path import *

from DMR.utils import *

class FFmpegDownloader():
    default_header = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'User-Agent': 'Mozilla/5.0 (Linux; Android 5.0; SM-G900P Build/LRX21T) AppleWebKit/537.36 '
                            '(KHTML, like Gecko) Chrome/75.0.3770.100 Mobile Safari/537.36 '
        }
    
    def __init__(self, 
                 stream_url:str, 
                 output_dir:str,
                 output_format:str,
                 taskname:str='',
                 segment:int=None,
                 header:dict=None,
                 ffmpeg:str=None,
                 segment_callback=None,
                 stable_callback=None,
                 advanced_video_args:dict=None,
                 debug=False,
                 **kwargs):
        
        self.stream_url = stream_url
        self.output_dir = output_dir
        self.output_format = output_format
        self.header = header if header else self.default_header
        self.segment = segment
        self.debug = debug
        self.taskname = taskname
        self.segment_callback = segment_callback
        self.stable_callback = stable_callback
        self.advanced_video_args = advanced_video_args if advanced_video_args else {}
        self.kwargs = kwargs
        self.ffmpeg = ffmpeg if ffmpeg else ToolsList.get('ffmpeg')
        self.logger = logging.getLogger(__name__)
        
        self.ffmpeg_proc = None
        self.stoped = False
    
    @property
    def duration(self):
        return datetime.now().timestamp() - self.start_time
        
    def start_ffmpeg(self):
        ffmpeg_stream_args = self.advanced_video_args.get('ffmpeg_stream_args', 
                                                          [ '-rw_timeout','10000000',
                                                            '-analyzeduration','15000000',
                                                            '-probesize','50000000',
                                                            '-thread_queue_size', '16'])
        ffmpeg_args = [
            self.ffmpeg, '-y',
            '-headers', ''.join('%s: %s\r\n' % x for x in self.header.items()),
            *ffmpeg_stream_args,
            '-i', self.stream_url,
            '-c', 'copy'
        ]

        ffmpeg_output_args = self.advanced_video_args.get('ffmpeg_output_args', 
                                                          [ '-movflags','faststart+frag_keyframe+empty_moov'])
        if self.segment:
            ffmpeg_args += ['-f','segment',
                            '-segment_time',str(self.segment),
                            '-reset_timestamps','1',
                            *ffmpeg_output_args,
                            self.raw_name]
        else:
            ffmpeg_args += [*ffmpeg_output_args,
                            self.raw_name]

        
        self.logger.debug('FFmpegDownloader args:')
        self.logger.debug(ffmpeg_args)

        if self.debug:
            self.ffmpeg_proc = subprocess.Popen(ffmpeg_args, stdin=subprocess.PIPE, stdout=sys.stdout, stderr=subprocess.STDOUT,bufsize=10**8, universal_newlines=True, encoding='utf-8', errors='ignore')
        else:
            self.ffmpeg_proc = subprocess.Popen(ffmpeg_args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,bufsize=10**8, universal_newlines=True, encoding='utf-8', errors='ignore')
        
        self.msg_queue = None
        def ffmpeg_monitor():
            while not self.stoped:
                if self.ffmpeg_proc.stdout.readable():
                    line = self.ffmpeg_proc.stdout.readline().strip()
                    if len(line) > 0:
                        self.msg_queue.put(line)
        
        if self.ffmpeg_proc.stdout is not None:
            self.msg_queue = queue.Queue()
            self.ffmpeg_monitor_proc = threading.Thread(target=ffmpeg_monitor, daemon=True)
            self.ffmpeg_monitor_proc.start()

        return self.msg_queue
    
    def start_helper(self):
        self.stoped = False
        self.raw_name = join(self.output_dir, f'[正在录制]{self.taskname}-{time.strftime("%Y%m%d-%H%M%S",time.localtime())}-Part%03d.{self.output_format}')
        self.start_time = datetime.now().timestamp()
        self._timer_cnt = 1
        self.thisfile = None

        log = ''
        ffmpeg_low_speed = 0

        self.start_ffmpeg()

        def is_info_line(line:str):
            return bool(line.startswith('frame=') or line.startswith('size=') or 'time=' in line)
        
        self.download_stable = False # stable ffmpeg speed < 2
        while not self.stoped:
            if self.ffmpeg_proc.poll() is not None:
                self.logger.debug('FFmpeg exit.')
                self.logger.debug(log)
                raise RuntimeError(f'FFmpeg 退出.')
            
            if self.debug:
                time.sleep(1)
                continue
            
            line = ''
            try:
                line = self.msg_queue.get_nowait()
                if not line.startswith('[hls'):
                    log += line + '\n'
            except queue.Empty:
                time.sleep(1)
            
            if is_info_line(line):
                if not self.advanced_video_args.get('disable_lowspeed_interrupt'):
                    l = line.find('speed=')
                    r = line.find('x', l)
                    if l > 0 and r > 0:
                        speed = float(line[l:r][6:])
                        if speed < 0.8:
                            ffmpeg_low_speed += 1
                            if ffmpeg_low_speed % 5 == 3:
                                self.logger.warn(f'{self.taskname} 直播流下载速度过慢, 请保证网络带宽充足.')
                            if ffmpeg_low_speed >= 15:
                                self.logger.debug(log)
                                raise RuntimeError(f'{self.taskname} 下载速度过慢, 即将重试.')
                        else:
                            ffmpeg_low_speed = 0

                        if not self.download_stable:
                            if speed and speed < 2:
                                l = line.find('time=')
                                r = line.find('bitrate') - 1
                                if l > 0 and r > 0:
                                    downloaded_duration = line[l+5:r]
                                try:
                                    h, m, s = int(downloaded_duration.split(':')[0]), int(downloaded_duration.split(':')[0]), float(downloaded_duration.split(':')[2])
                                    downloaded_duration_ms = h * 3600 + m * 60 + s
                                    time_error = downloaded_duration_ms - datetime.now().timestamp() + self.start_time + (speed - 1)
                                    self.stable_callback(time_error)
                                    self.download_stable = True
                                except Exception as e:
                                    self.logger.debug(e)
                                    self.download_stable = False
            
            if 'Opening' in line:
                fname = line.split('\'')[1]
                if not fname.startswith('http'):
                    if self.thisfile:
                        self.segment_callback(self.thisfile)
                    self.thisfile = fname

            if 'dropping it' in line or 'Invalid NAL unit size' in line:
                self.logger.debug(log)
                raise RuntimeError(f'{self.taskname} 直播流读取错误, 即将重试, 如果此问题多次出现请反馈.')

            if self.start_time is not None and self.duration > self._timer_cnt*15:
                if len(log) == 0:
                    raise RuntimeError(f'{self.taskname} 管道读取错误, 即将重试.')
                
                ok = False
                output_log = False
                for li in log.split('\n'):
                    if li and is_info_line(li):
                        ok = True
                    if li and not is_info_line(li):
                        output_log = True
                
                if output_log:
                    self.logger.debug(f'{self.taskname} FFmpeg output:\n{log}')
                
                if not ok:
                    raise RuntimeError(f'{self.taskname} 直播流读取错误, 即将重试.')

                log = ''
                self._timer_cnt += 1

    def start(self):
        return self.start_helper()

    def stop(self):
        if self.stoped:
            return
        self.stoped = True
        log = ''
        try:
            while self.msg_queue.qsize() > 0:
                msg = self.msg_queue.get_nowait()
                log += msg+'\n'
        except Exception as e:
            self.logger.debug(e)
        if log:
            self.logger.debug(f'{self.taskname} ffmpeg: {log}')
            
        try:
            out, _ = self.ffmpeg_proc.communicate('q',timeout=3)
            if out:
                self.logger.debug(f'ffmpeg out: {out}.')
        except Exception as e:
            self.ffmpeg_proc.kill()
            self.logger.debug(e)
        
        if self.thisfile:
            time.sleep(1)
            self.segment_callback(self.thisfile)
        self.logger.debug('ffmpeg downloader stoped.')
