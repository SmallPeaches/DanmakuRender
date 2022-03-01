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


class PythonRender():
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
      

    def _get_danmaku(self):
        self.args.starttime = self._startTime
        monitor = multiprocessing.Process(target=_danmu_subproc,args=(self.args,_dmfilter,self._sender,self.interrupt))
        monitor.start()

        return monitor

    def _get_stream_info(self,url):
        ffmpeg_args = [self._ffmpeg, '-headers', ''.join('%s: %s\r\n' % x for x in self.header.items()),'-i', url]
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

    def _set_render(self,fout,nproc=2):
        QSIZE = int(self.fps/nproc)
        self._sender = [multiprocessing.Queue(QSIZE) for i in range(nproc)]
        self._recver = [multiprocessing.Queue(QSIZE) for i in range(nproc)]
       
        def frame_monitor():
            ndrop = 0
            ffmpeg_delay_cnt = 0
            fid = 1
            thisfid = 1
            _,framebytes = self._recver[0].get()
            empty_frame = framebytes
            while not self._stop:
                try:
                    pid = fid%nproc
                    thisfid,newframebytes = self._recver[pid].get_nowait()
                    while thisfid < fid: 
                        thisfid,newframebytes = self._recver[pid].get_nowait()
                    try:
                        fout.write(newframebytes)
                    except Exception as e:
                        self.logger.error(e)
                        self.stop()
                    framebytes = newframebytes
                except queue.Empty:
                    self._sender[pid].put({'msg_type':'fid','fid':fid+nproc})
                    try:
                        if fid - thisfid > self.fps*self.args.dmduration:
                            fout.write(empty_frame)
                        else:
                            fout.write(framebytes)
                    except Exception as e:
                        self.logger.error(e)
                        self.stop()

                    ndrop += 1
                    if ndrop and ndrop % 1000 == 0:
                        self.logger.warn(f'检测到弹幕渲染丢帧达到{ndrop}帧.')
                    elif ndrop and ndrop % 100 == 0:
                        self.logger.debug(f'检测到弹幕渲染丢帧达到{ndrop}帧.')
                except Exception as e:
                    self.logger.error(e)
                    self.stop()
                    
                fid += 1
                MAX_DELAY = 0.25
                delay = fid/self.fps - self.duration
                if delay > MAX_DELAY:
                    time.sleep(MAX_DELAY)
                elif delay < -MAX_DELAY:
                    ffmpeg_delay_cnt += 1
                    if ffmpeg_delay_cnt and ffmpeg_delay_cnt % 50 == 0:
                        self.logger.warn(f'视频编码队列阻塞达到{ffmpeg_delay_cnt}次, 请保证有足够的资源用于实时编码!')
                    fid += int(MAX_DELAY*self.fps)

        procs = []
        for i in range(nproc):
            proc = multiprocessing.Process(target=_render_subproc,args=(i,nproc,self.args,self._sender[i],self._recver[i]))
            proc.start()
            procs.append(proc)

        monitor = threading.Thread(target=frame_monitor,daemon=True)
        monitor.start()
        
        return procs

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
                        '-analyzeduration', '60',
                        *args.hwaccel_args,
                        # '-rw_timeout', '%d000000'%self._timeout,
                        '-thread_queue_size', '32',
                        '-i', stream_url,

                        '-thread_queue_size', '32',
                        '-f', 'rawvideo',
                        '-s', '%dx%d'%(self.width,int(self.height*args.dmrate)), 
                        '-pix_fmt', 'rgba',
                        '-r', str(self.fps),
                        '-i', '-',
                        
                        '-filter_complex','[0:v][1:v]overlay=0:0[v]',
                        '-map','[v]','-map','0:a',
                        '-c:v',args.vencoder,
                        '-c:a',args.aencoder,
                        '-b:v',args.vbitrate,
                        '-b:a',args.abitrate,
                        '-r', str(self.fps)
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
        stream_info = self._get_stream_info(stream_url)

        if not stream_info.get('fps') or stream_info.get('fps')<30:
            self.logger.warn(f'无法获取流帧率，使用默认值{args.fps}.')
            stream_info['fps'] = 60
        if not (stream_info.get('width') or stream_info.get('height')):
            self.logger.warn(f'无法获取视频大小，使用默认值{args.resolution}.')
            stream_info['width'],stream_info['height'] = [int(i) for i in args.resolution.split('x')]

        self.fps,self.width,self.height = stream_info['fps'],stream_info['width'],stream_info['height']
        args.fps,args.width,args.height = stream_info['fps'],stream_info['width'],stream_info['height']

        if args.resolution_fixed:
            args.dmduration_fixed = self.width/1920*(args.dmduration)
            args.fontsize_fixed = int(self.height/1080*(args.fontsize))
            args.margin_fixed = int(self.height/1080*(args.margin))
            args.startpixel_fixed = int(self.height/1080*(args.startpixel))
        else:
            args.dmduration_fixed = float(args.dmduration)
            args.fontsize_fixed = int(args.fontsize)
            args.margin_fixed = int(args.margin)
            args.startpixel_fixed = int(args.startpixel)

        self._stop = False
        self._startTime = datetime.now().timestamp()
        self._endTime = 0
        
        self._ffmpeg_proc = self._set_ffmpeg(stream_url,args)
        self._render_procs = self._set_render(self._ffmpeg_proc.stdin,args.nproc)
        self._danmu_proc = self._get_danmaku()

        self.logger.debug('DanmakuRender args:')
        self.logger.debug(self.args)

        log = ''
        try:
            if self.args.vbitrate[-1].lower() == 'm':
                vbitrate = float(self.args.vbitrate[:-1])*1e6
            elif self.args.vbitrate[-1].lower() == 'k':
                vbitrate = float(self.args.vbitrate[:-1])*1e3
            else:
                vbitrate = float(self.args.vbitrate)
        except:
            vbitrate = 15*1e6
        bitrate_avg = vbitrate
        bitrate_rts = 0
        ffmpeg_low_bitrate = 0
        ffmpeg_low_speed = 0
        m3u8_drop_cnt = 0
        timer_cnt = 1
        
        while not self._stop:
            try:
                for _ in range(self.interrupt.qsize()):
                    msg = self.interrupt.get_nowait()
                    if msg['msg_type'] == 'stop':
                        self.stop()
                        self.logger.debug('Subprocess Stop.')
                        self.logger.debug(msg['stop'])
                        break
                    elif msg['msg_type'] == 'danmaku':
                        self.logger.debug(f"Danmaku:{msg['danmaku']}.")
            except queue.Empty:
                pass

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

            if self.duration > timer_cnt*60:   
                self.logger.debug(f'FFmpeg output:{log}')

                if self.args.debug:
                    info = ''

                if not args.disable_lowbitrate_interrupt:
                    l = info.find('bitrate=')
                    r = info.find('kbits/s')
                    if l>0 and r>0:
                        bitrate = float(info[l:r][8:])*1e3
                        bitrate_realtime = (bitrate*self.duration - bitrate_avg*bitrate_rts)/(self.duration-bitrate_rts)
                        bitrate_avg = bitrate
                        self.logger.debug(f'bitrate_realtime:{bitrate_realtime}')

                        if bitrate_realtime < bitrate_avg*0.5:
                            ffmpeg_low_bitrate += 1
                            self.logger.warn(f'当前比特率过低, 设定为{vbitrate}bps, 实际为{bitrate_realtime}bps, 请检查录制情况.')
                            if ffmpeg_low_bitrate >= 5:
                                self.logger.error('比特率过低, 即将重试.')
                                self.stop()
                                return 
                        else:
                            ffmpeg_low_bitrate = 0

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
                
                if self.args.max_duration and self.duration > self.args.max_duration:
                    self.logger.info(f'超过单次最长录制时间{self.args.max_duration}秒, 即将重启录制.')
                    self.stop()
                    return

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
            out,_ = self._ffmpeg_proc.communicate(b'q',2.0)
            out = out.decode('utf-8')
            self.logger.debug(out)
        except Exception as e:
            self._ffmpeg_proc.kill()
            self.logger.debug(e)
        try:
            self._danmu_proc.kill()
        except Exception as e:
            self.logger.debug(e)
        try:
            for proc in self._render_procs:
                proc.kill()
        except Exception as e:
            self.logger.debug(e)
        return True


##------------------------------
def _dmfilter(dm):
    try:
        s = dm['content']
        if '\{' in s:
            return
        elif '/{' in s:
            return 
    except:
        return
    return dm

def _danmu_subproc(args,dmfilter,render_procs,interrupt:multiprocessing.Queue=None):
    starttime = datetime.now().timestamp()

    async def danmu_monitor():
        q = asyncio.Queue()
        dmc = DanmakuClient(args.url, q)
        
        async def dmc_task():
            try:
                await dmc.start()
            except Exception as e:
                if interrupt:
                    interrupt.put({'msg_type':'stop','stop':e})
        asyncio.create_task(dmc_task())

        while 1:
            dm = await q.get()
            if dm.get('name',0):
                dm['time'] = datetime.now().timestamp()-starttime + 1.0
                dm = dmfilter(dm)
                if dm:
                    interrupt.put({'msg_type':'danmaku','danmaku':dm})
                    for render_proc in render_procs:
                        render_proc.put(dm)
    
    monitor = threading.Thread(target=asyncio.run,args=(danmu_monitor(),),daemon=True)
    monitor.start()
    monitor.join()
    
    return monitor

def _render_subproc(pid:int,nproc:int,args,recv:multiprocessing.Queue,send:multiprocessing.Queue):
    global fid
    fid = pid
    lock = multiprocessing.Lock()

    render =   DmScreen(width=args.width,
                        height=int(args.height*args.dmrate),
                        dmstartpixel=args.startpixel_fixed,
                        fps=args.fps,
                        margin=args.margin_fixed,
                        dmrate=1,
                        font=args.font,
                        fontsize=args.fontsize_fixed,
                        overflow_op=args.overflow_op,
                        dmduration=args.dmduration_fixed,
                        opacity=args.opacity)

    def recv_monitor():
        global fid
        while True:
            info = recv.get()
            if info.get('msg_type',0) == 'danmaku':
                with lock:
                    render.add(info)

            elif info.get('msg_type',0) == 'fid':
                fid = max(info['fid'],fid)

    monitor = threading.Thread(target=recv_monitor,daemon=True)
    monitor.start()

    while True:
        while send.full():
            time.sleep(0.01)
        with lock:
            frame = render.render(fid)
        frame = (fid,frame.tobytes())
        send.put(frame)
        fid += nproc