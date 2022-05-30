from datetime import datetime
import logging
import os
import queue
import re
import subprocess
import sys
import multiprocessing
import asyncio
import threading
import time
from os.path import join
from downloader.DanmakuWriter import DanmakuWriter
from downloader.Render import Render
from downloader.getrealurl import get_stream_url
from downloader.danmaku import DanmakuClient
from tools.utils import onair

class Downloader():
    header = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'User-Agent': 'Mozilla/5.0 (Linux; Android 5.0; SM-G900P Build/LRX21T) AppleWebKit/537.36 '
                            '(KHTML, like Gecko) Chrome/75.0.3770.100 Mobile Safari/537.36 '
        }
    def __init__(self, url:str, name:str, ffmpeg:str = 'tools/ffmpeg.exe', video_dir:str='./save', dm_dir:str=None, render_dir='/save-dm'):
        self.taskname = name
        self.url = url
        self.ffmpeg = ffmpeg

        self.video_dir = video_dir
        if dm_dir is None:
            self.dm_dir = self.video_dir
        else:
            self.dm_dir = dm_dir
        self.render_dir = render_dir
        
        self.stoped = False
        self.logger = logging.getLogger('main')
    
    @property
    def duration(self):
        return datetime.now().timestamp() - self._startTime

    def _get_stream_info(self,url):
        ffmpeg_args = [self.ffmpeg, '-headers', ''.join('%s: %s\r\n' % x for x in self.header.items()),'-i', url]
        proc = subprocess.Popen(ffmpeg_args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        # proc = subprocess.Popen(ffmpeg_args, stdout=sys.stdout, stderr=subprocess.STDOUT)
        info = {}
        lines = [l.decode('utf-8') for l in proc.stdout.readlines()]

        for line in lines:
            if ' displayWidth ' in line:
                info['width'] = int(line.split(':')[-1])
            elif ' displayHeight ' in line:
                info['height'] = int(line.split(':')[-1])
            elif ' fps ' in line:
                info['fps'] = float(line.split(':')[-1])
            if len(info) == 3:
                break
        
        if len(info) < 3:
            for line in lines:
                if 'Video:' in line:
                    metadata = line.split(',')
                    for x in metadata:
                        if 'fps' in x:
                            info['fps'] = float([i for i in x.split(' ') if len(i)>0][0])
                        elif 'x' in x:
                            wh = [i for i in x.split(' ') if len(i)>0][0]
                            if len(wh.split('x')) == 2:
                                info['width'] = int(wh.split('x')[0])
                                info['height'] = int(wh.split('x')[1])
                        if len(info) == 3:
                            break
        return info
    
    def _set_ffmpeg(self,stream_url,args):
        ffmpeg_stream_args = args.ffmpeg_stream_args.split(',')
        ffmpeg_args =   [
                        self.ffmpeg, '-y',
                        '-headers', ''.join('%s: %s\r\n' % x for x in self.header.items()),
                        *ffmpeg_stream_args,
                        '-thread_queue_size', '16',
                        '-i', stream_url,
                        '-c','copy'
                        ]
        
        self.format_videoname = f'{self.taskname}-{time.strftime("%Y%m%d-%H%M%S",time.localtime())}-Part%03d.mp4'
        if args.split > 0:
            ffmpeg_args += ['-f','segment','-segment_time',str(args.split),'-reset_timestamps','1','-movflags','frag_keyframe',join(self.video_dir,self.format_videoname)]
        else:
            fname = self.format_videoname.replace(f'%03d','000')
            ffmpeg_args += ['-movflags','frag_keyframe',join(self.video_dir,fname)]

        
        self.logger.debug('Downloader FFmpeg args:')
        self.logger.debug(ffmpeg_args)

        if args.debug:
            proc = subprocess.Popen(ffmpeg_args, stdin=subprocess.PIPE, stdout=sys.stdout, stderr=subprocess.STDOUT,bufsize=10**8)
        else:
            proc = subprocess.Popen(ffmpeg_args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,bufsize=10**8)
        
        return proc

    def _dm_filter(self,dm):
        if not dm.get('name',0):
            return 
        if '\{' in dm.get('content',''):
            return 
        return dm

    def _set_danmaku(self,args):
        self.dmw = DanmakuWriter(self.format_videoname.replace('.mp4','.ass'),
                                self.dm_dir,args.split,self.width,self.height,args.margin_fixed,args.dmrate,
                                args.font,args.fontsize_fixed,args.overflow_op,args.dmduration_fixed,args.opacity)
        async def danmu_monitor():
            q = asyncio.Queue()
            self.dmc = DanmakuClient(self.url, q)
            task = asyncio.create_task(self.dmc.start())
            latest = self.duration

            while not self.stoped:
                try:
                    dm = q.get_nowait()
                    dm['time'] = self.duration
                    latest = self.duration
                    dm = self._dm_filter(dm)
                    if dm:
                        # print(dm)
                        self.dmw.add(dm)
                    continue
                except asyncio.QueueEmpty:
                    pass
                        
                if not args.disable_danmaku_reconnect and self.duration-latest > 300:
                    self.logger.error('弹幕流中断,正在重连.')
                    task.cancel()
                    self.dmc = DanmakuClient(self.url, q)
                    task = asyncio.create_task(self.dmc.start())
                
                await asyncio.sleep(0.1)

            self.dmw.stop()
    
        monitor = threading.Thread(target=asyncio.run,args=(danmu_monitor(),),daemon=True)
        monitor.start()
        return monitor

    def _set_render(self,args):
        self.render = Render(args,self.ffmpeg)
        def start():
            self.render.auto_render(self.format_videoname[0:-13],self.video_dir,self.dm_dir,self.render_dir)

        monitor = threading.Thread(target=start,daemon=True)
        monitor.start()
        return monitor

    def start_helper(self,args,onprint=True):
        self.args = args 

        stream_url = get_stream_url(self.url,args.flowtype)
        stream_info = self._get_stream_info(stream_url)

        if not (stream_info.get('width') or stream_info.get('height')):
            self.logger.warn(f'无法获取视频大小，使用默认值{args.resolution}.')
            stream_info['width'],stream_info['height'] = [int(i) for i in args.resolution.split('x')]

        self.width,self.height = stream_info['width'],stream_info['height']

        if args.resolution_fixed:
            args.dmduration_fixed = self.width/1920*(args.dmduration)
            args.fontsize_fixed = int(self.height/1080*(args.fontsize))
            args.margin_fixed = int(self.height/1080*(args.margin))
        else:
            args.dmduration_fixed = float(args.dmduration)
            args.fontsize_fixed = int(args.fontsize)
            args.margin_fixed = int(args.margin)

        self.stoped = False
        self._startTime = datetime.now().timestamp()
        
        self._ffmpeg_proc = self._set_ffmpeg(stream_url,args)
        self._dm_proc = self._set_danmaku(args)
        if not args.disable_auto_render:
            os.makedirs(self.render_dir,exist_ok=True)
            self._render_proc = self._set_render(args)

        self.logger.debug('DanmakuRender args:')
        self.logger.debug(self.args)

        log = ''
        ffmpeg_low_speed = 0
        m3u8_drop_cnt = 0
        timer_cnt = 1
        
        while not self.stoped:
            if self._ffmpeg_proc.stdout is None:
                time.sleep(0.5)
            else:
                out = b''
                while 1:
                    char = self._ffmpeg_proc.stdout.read(1)
                    if self._ffmpeg_proc.stdout.closed:
                        break
                    if char in [b'\n',b'\r']:
                        break
                    else:
                        out += char
                line = out.decode('utf-8')
                log += line+'\n'
                if onprint and 'frame=' in line:
                    print(f'\r正在录制{self.taskname}: {line}',end='')
                    
                segs = line.split('\'')
                if len(segs) > 2 and '.mp4' in segs[1] and '%' not in segs[1]:
                    self.logger.info(f"正在录制分片{segs[1]}.")
                    
                if self._ffmpeg_proc.poll() is not None:
                    self.logger.debug('FFmpeg exit.')
                    self.stop()
                    return log

            if self.duration > timer_cnt*60 and not self.args.debug:   
                self.logger.debug(f'FFmpeg output:{log}')

                if not args.disable_lowspeed_interrupt:
                    l = line.find('speed=')
                    r = line.find('x',l)
                    if l>0 and r>0:
                        speed = float(line[l:r][6:])
                        if speed < 0.9:
                            ffmpeg_low_speed += 1
                            self.logger.warn(f'直播流下载速度过慢, 请保证网络带宽充足.')
                            if ffmpeg_low_speed >= 2:
                                self.logger.error('下载速度过慢, 即将重试.')
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
                        if m3u8_drop_cnt >= 2:
                            self.logger.error('直播流读取错误, 即将重试.')
                            self.stop()
                            return
                else:
                    if 'dropping it' in log:
                        self.logger.error('直播流读取错误, 即将重试, 如果此问题多次出现请反馈.')
                        self.stop()

                if not onair(self.url):
                    self.logger.debug('Live end.')
                    self.stop()

                log = ''
                timer_cnt += 1
        
        return 
    
    def start(self,args,onprint=True):
        try:
            rval = self.start_helper(args,onprint=onprint)
            return rval
        except KeyboardInterrupt:
            self.stop()
            self.logger.info(f'{self.taskname}录制结束.')
            exit(0)

    def stop(self):
        self.stoped = True
        print('')
        try:
            self.dmw.stop()
        except Exception as e:
            self.logger.debug(e)
        try:
            self.render.stop()
        except Exception as e:
            self.logger.debug(e)
        try:
            self._ffmpeg_proc.stdin.flush()
        except Exception as e:
            self.logger.debug(e)
        try:
            out,_ = self._ffmpeg_proc.communicate(b'q',2.0)
            out = out.decode('utf-8')
            self.logger.debug(out)
        except Exception as e:
            self._ffmpeg_proc.kill()
            self.logger.debug(e)
        time.sleep(0.5)


