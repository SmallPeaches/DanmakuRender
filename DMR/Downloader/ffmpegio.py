from datetime import datetime
import logging
import signal
import subprocess
import sys
import threading
import time
import queue
from os.path import *

from DMR.LiveAPI import Onair
from DMR.utils import *
from tools import ToolsList

class FFmpegDownloader():
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
                 ffmpeg_stream_args:list=None,
                 ffmpeg:str=None,
                 debug=False,
                 header:dict=None,
                 segment_callback=None,
                 stable_callback=None,
                 advanced_video_args:dict=None,
                 **kwargs):
        self.stream_url = stream_url
        self.header = header if header else self.default_header
        self.segment = segment
        self.ffmpeg_stream_args = ffmpeg_stream_args
        self.debug = debug
        self.output = output
        self.taskname = taskname
        self.url = url
        self.segment_callback = segment_callback
        self.stable_callback = stable_callback
        self.advanced_video_args = advanced_video_args if advanced_video_args else {}
        self.kwargs = kwargs
        self.ffmpeg = ffmpeg if ffmpeg else ToolsList.get('ffmpeg')
        self.stream_type = 'm3u8' if isinstance(self.stream_url, str) and '.m3u8' in self.stream_url else 'flv'
        
        if isinstance(self.stream_url, str):
            self.stable = True
        else:
            self.stable = False
        self.stoped = False
    
    @property
    def duration(self):
        return datetime.now().timestamp() - self.start_time
    
    def extract_stream(self) -> tuple:
        if self.stable:
            stream_url = self.stream_url
            header = self.header
        else:
            stream_url = self.stream_url()
            header = self.header()
        return stream_url, header
        
    def start_ffmpeg(self):
        stream_url, header = self.extract_stream()

        ffmpeg_stream_args = self.advanced_video_args.get('ffmpeg_stream_args', 
                                                          [ '-rw_timeout','10000000',
                                                            '-analyzeduration','15000000',
                                                            '-probesize','50000000',
                                                            '-thread_queue_size', '16'])
        ffmpeg_args = [
            self.ffmpeg, '-y',
            '-headers', ''.join('%s: %s\r\n' % x for x in header.items()),
            *ffmpeg_stream_args,
            '-i', stream_url,
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

        
        logging.debug('FFmpegDownloader args:')
        logging.debug(ffmpeg_args)

        if self.debug:
            self.ffmpeg_proc = subprocess.Popen(ffmpeg_args, stdin=subprocess.PIPE, stdout=sys.stdout, stderr=subprocess.STDOUT,bufsize=10**8, universal_newlines=True, encoding='utf-8')
        else:
            self.ffmpeg_proc = subprocess.Popen(ffmpeg_args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,bufsize=10**8, universal_newlines=True, encoding='utf-8')
        
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
    
    @staticmethod
    def get_livestream_info(stream_url, header):
        stream_info = FFprobe.get_livestream_info(stream_url, header)
        IGNORE_KEYS = ['start_pts', 'start_time', 'bit_rate']
        for k in IGNORE_KEYS:
            stream_info.pop(k, 0)
        CALC_FRAME_KEYS = ['r_frame_rate', 'avg_frame_rate']
        for k in CALC_FRAME_KEYS:
            try:
                stream_info[k] = round(float(stream_info[k].split('/')[0]) / float(stream_info[k].split('/')[1]))
            except:
                stream_info[k] = 0
        return stream_info
    
    def start_helper(self):
        self.stoped = False
        self.raw_name = join(split(self.output)[0], f'[正在录制]{self.taskname}-{time.strftime("%Y%m%d-%H%M%S",time.localtime())}-Part%03d{splitext(self.output)[1]}')
        self.start_time = datetime.now().timestamp()
        self._timer_cnt = 1
        self.thisfile = None

        stream_url, header = self.extract_stream()
        if self.advanced_video_args.get('check_stream_changes'):
            latest_stream_info = self.get_livestream_info(stream_url, header)
        log = ''
        ffmpeg_low_speed = 0

        self.start_ffmpeg()

        def is_info_line(line:str):
            return bool(line.startswith('frame=') or line.startswith('size=') or 'time=' in line)
        
        self.download_stable = False # stable ffmpeg speed < 2
        while not self.stoped:
            if self.ffmpeg_proc.poll() is not None:
                logging.debug('FFmpeg exit.')
                logging.debug(log)
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
                                logging.warn(f'{self.taskname} 直播流下载速度过慢, 请保证网络带宽充足.')
                            if ffmpeg_low_speed >= 15:
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
                                    logging.debug(e)
                                    self.download_stable = False
            
            if 'Opening' in line:
                fname = line.split('\'')[1]
                if not fname.startswith('http'):
                    if self.thisfile:
                        self.segment_callback(self.thisfile)
                    self.thisfile = fname

            if 'dropping it' in line or 'Invalid NAL unit size' in line:
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
                    logging.debug(f'{self.taskname} FFmpeg output:\n{log}')
                
                if not ok:
                    raise RuntimeError(f'{self.taskname} 直播流读取错误, 即将重试.')

                if self._timer_cnt%3 == 0:
                    if self.advanced_video_args.get('check_stream_changes'):
                        try:
                            new_info = self.get_livestream_info(stream_url, header)
                        except Exception as e:
                            logging.debug(f'Check stream info error: {e}.')
                            new_info = latest_stream_info
                        if latest_stream_info and new_info != latest_stream_info:
                            logging.debug(f'latest_stream_info: {latest_stream_info}')
                            logging.debug(f'new_info: {new_info}')
                            raise RuntimeError('推流信息变化，即将重试...')

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
            logging.debug(e)
        if log:
            logging.debug(f'{self.taskname} ffmpeg: {log}')
            
        try:
            out, _ = self.ffmpeg_proc.communicate('q',timeout=3)
            if out:
                logging.debug(f'ffmpeg out: {out}.')
        except Exception as e:
            self.ffmpeg_proc.kill()
            logging.debug(e)
        
        if self.thisfile:
            time.sleep(1)
            self.segment_callback(self.thisfile)
        logging.debug('ffmpeg downloader stoped.')
