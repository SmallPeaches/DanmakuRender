from datetime import datetime
import queue
import subprocess
import threading
import multiprocessing
import asyncio
import time
import sys
import warnings
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
    
    @property
    def duration(self):
        return self._endTime - self._startTime if self._endTime else datetime.now().timestamp() - self._startTime
      

    def _get_danmaku(self):
        def boardcast_danmaku(dm):
            for sender in self._sender:
                sender.put(dm)
        
        def dmfilter(dm):
            s = dm['content']
            if '\{' in s:
                return
            elif '/{' in s:
                return 
            return dm
        
        self.args.starttime = self._startTime
        monitor = multiprocessing.Process(target=_danmu_subproc,args=(self.args,dmfilter,boardcast_danmaku,self.interrupt))
        monitor.run()
        """
        async def danmu_monitor():
            q = asyncio.Queue()
            dmc = DanmakuClient(self._url, q)
            
            async def dmc_task():
                try:
                    await dmc.start()
                except Exception as e:
                    self.stop()
                    print(e)
            asyncio.create_task(dmc_task())

            while not self._stop:
                await asyncio.sleep(0.1)
                num = q.qsize()
                for _ in range(num):
                    dm = q.get_nowait()
                    if dm.get('name',0):
                        dm['time'] = self.duration + 1.0
                        dm = self._dmfilter(dm)
                        if dm:
                            self._boardcast_danmaku(dm)
                            self.dmcnt+=1

            await dmc.stop()
        
        monitor = threading.Thread(target=asyncio.run,args=(danmu_monitor(),),daemon=True)
        monitor.start()
        """
        
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
            fid = 1
            thisfid = 1
            _,framebytes = self._recver[0].get()
            while not self._stop:
                try:
                    pid = fid%nproc
                    thisfid,newframebytes = self._recver[pid].get_nowait()
                    while thisfid < fid: 
                        thisfid,newframebytes = self._recver[pid].get_nowait()
                    fout.write(newframebytes)
                    framebytes = newframebytes
                except queue.Empty:
                    self._sender[pid].put({'msg_type':'fid','fid':fid+nproc})
                    fout.write(framebytes)
                
                fid += 1
                # print('fid: %d \r'%fid,end='')
                MAX_DELAY = 0.25
                delay = fid/self.fps - self.duration
                if delay > MAX_DELAY:
                    time.sleep(MAX_DELAY)

        monitor = threading.Thread(target=frame_monitor,daemon=True)
        monitor.start()

        procs = []
        for i in range(nproc):
            proc = multiprocessing.Process(target=_render_subproc,args=(i,nproc,self.args,self._sender[i],self._recver[i]))
            proc.start()
            procs.append(proc)
        
        return procs

    def _set_ffmpeg(self,stream_url,args):
        ffmpeg_args =   [
                        self._ffmpeg, '-y',
                        '-headers', ''.join('%s: %s\r\n' % x for x in self.header.items()),
                        '-fflags', '+discardcorrupt',
                        '-analyzeduration', '5',
                        *args.hwaccel_args,
                        '-reconnect_streamed', '1', 
                        '-reconnect_delay_max', '20', 
                        '-rw_timeout', '%d000000'%self._timeout,
                        '-thread_queue_size', '16',
                        '-i', stream_url,

                        '-thread_queue_size', '32',
                        '-f', 'rawvideo',
                        '-s', '%dx%d'%(self.width,int(self.height*args.dmrate)), 
                        '-pix_fmt', 'rgba',
                        '-r', str(self.fps),
                        '-i', '-',
                        
                        '-filter_complex','overlay=0:0',
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

        if args.debug:
            proc = subprocess.Popen(ffmpeg_args, stdin=subprocess.PIPE, stdout=sys.stdout, stderr=subprocess.STDOUT, bufsize=10**8)
        else:
            proc = subprocess.Popen(ffmpeg_args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,bufsize=10**8)
        
        return proc

    def start_helper(self,args):
        self.args = args
        if not os.path.exists(self._save):
            os.makedirs(self._save)

        stream_url = get_stream_url(self._url)
        info = self._get_stream_info(stream_url)

        if not info.get('fps'):
            warnings.warn('无法获取流帧率，使用默认值60.')
            info['fps'] = 60
        if not (info.get('width') or info.get('height')):
            warnings.warn('无法获取视频大小，使用默认值1920x1080.')
            info['width'],info['height'] = 1920,1080
        self.fps,self.width,self.height = info['fps'],info['width'],info['height']
        args.fps,args.width,args.height = info['fps'],info['width'],info['height']

        if args.dmduration[0] == '+':
            args.dmduration = int(args.dmduration[1:])
            args.dmduration = self.width/1920*(args.dmduration)
        else:
            args.dmduration = int(args.dmduration)

        self._stop = False
        self._startTime = datetime.now().timestamp()
        self._endTime = 0
        
        self._ffmpeg_proc = self._set_ffmpeg(stream_url,args)
        self._render_procs = self._set_render(self._ffmpeg_proc.stdin,args.nproc)
        self._danmu_proc = self._get_danmaku()

        self.log = ''
        
        while not self._stop:
            try:
                info = self.interrupt.get_nowait()
                if info['msg_type'] == 'stop':
                    self.stop()
                    print(info['stop'])
            except queue.Empty:
                pass

            if self._ffmpeg_proc.stdout is None:
                time.sleep(0.5)
            else:
                out = self._ffmpeg_proc.stdout.readline(200).decode('utf-8')
                self.log += out
                line = out.strip('\n')
                info = line.split('\r')
                if len(info) > 1:
                    info = line.split('\r')[1]
                    if 'frame=' in info:
                        print(f'\r正在录制{self._name}: {info}',end='')

            if int(self.duration)%60 == 0:
                if not onair(self._url):
                    self.stop()
            
        return self.log
    
    def start(self,args):
        try:
            return self.start_helper(args)
        except KeyboardInterrupt:
            self.stop()
            print('录制结束.')
            exit(0)

    def stop(self):
        self._stop = True
        try:
            self._ffmpeg_proc.stdin.flush()
        except:
            pass
        try:
            self._ffmpeg_proc.communicate(b'q')
        except:
            pass
        try:
            self._danmu_proc.kill()
        except:
            pass
        try:
            for proc in self._render_procs:
                proc.kill()
        except:
            pass
        return True

##------------------------------
def _danmu_subproc(args,dmfilter,boardcast,send:multiprocessing.Queue=None,recv:multiprocessing.Queue=None):
    async def danmu_monitor():
        q = asyncio.Queue()
        dmc = DanmakuClient(args.url, q)
        
        async def dmc_task():
            try:
                await dmc.start()
            except Exception as e:
                if send:
                    send.put({'msg_type':'stop','stop':e})
        asyncio.create_task(dmc_task())

        while 1:
            dm = await q.get()
            if dm.get('name',0):
                dm['time'] = datetime.now().timestamp()-args.starttime + 1.0
                dm = dmfilter(dm)
                if dm:
                    boardcast(dm)
    
    monitor = threading.Thread(target=asyncio.run,args=(danmu_monitor(),),daemon=True)
    monitor.start()
    
    return monitor

def _render_subproc(pid:int,nproc:int,args,recv:multiprocessing.Queue,send:multiprocessing.Queue):
    global fid
    fid = pid
    lock = multiprocessing.Lock()

    render =   DmScreen(width=args.width,
                        height=int(args.height*args.dmrate),
                        dmstartpixel=args.startpixel,
                        fps=args.fps,
                        margin=args.margin,
                        dmrate=1,
                        font=args.font,
                        fontsize=args.fontsize,
                        overflow_op=args.overflow_op,
                        dmduration=args.dmduration,
                        opacity=args.opacity)

    def recv_monitor():
        while True:
            info = recv.get()
            if info.get('msg_type',0) == 'danmaku':
                with lock:
                    render.add(info)
            elif info.get('msg_type',0) == 'fid':
                global fid
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