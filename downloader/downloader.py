import logging
import os
import subprocess
import threading
import time
import asyncio
import json
import sys
import tempfile
from datetime import datetime
from .GetStreamURL import GetStreamURL
from .danmaku import DanmakuClient

class downloader():
    header = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'User-Agent': 'Mozilla/5.0 (Linux; Android 5.0; SM-G900P Build/LRX21T) AppleWebKit/537.36 '
                            '(KHTML, like Gecko) Chrome/75.0.3770.100 Mobile Safari/537.36 '
        }
    def __init__(self,url:str,name:str,save:str='./save',ffmpeg:str='ffmpeg.exe',replay_timeout:int=20):
        self.danmu = []
        self.duration = 0
        self.dmcnt = 0
        self._name = name
        self._url = url
        self._save = os.path.abspath(save)
        self._cacheKB = 1024
        self._ffmpeg = ffmpeg
        self._stop = False
        self._ffmpeg_base_args = [self._ffmpeg,'-y','-headers',''.join('%s: %s\r\n' % x for x in self.header.items()),
                                  '-rw_timeout', str(replay_timeout*1e6)]
    
    def _dl_video(self,splitSec:int=0,fname:str=None):
        self._ffmpegoutfile = tempfile.NamedTemporaryFile()
        stream_url = GetStreamURL.get_url(self._url)
        fname = fname + '-part%03d.mp4'
        save = os.path.join(self._save,fname)
        if not splitSec:
            ffmpeg_args = [*self._ffmpeg_base_args,'-i', stream_url,'-c','copy','-movflags','frag_keyframe',save.replace(f'-part%03d','')]
        else:
            ffmpeg_args = [*self._ffmpeg_base_args,'-i', stream_url,'-c','copy',
                           '-f','segment','-segment_time',str(splitSec),'-movflags','frag_keyframe',save]

        proc = subprocess.Popen(ffmpeg_args, stdin=subprocess.PIPE, stdout=self._ffmpegoutfile, stderr=self._ffmpegoutfile)
        # proc = subprocess.Popen(ffmpeg_args, stdin=subprocess.PIPE, stdout=sys.stdout, stderr=sys.stderr)
        return proc
    
    def _dl_damuku(self,splitSec:int=0,fname=None):
        starttime = datetime.now().timestamp()
        fname = fname
        async def danmu_monitor():
            q = asyncio.Queue()
            dmc = DanmakuClient(self._url, q)
            asyncio.create_task(dmc.start())
            while not self._stop:
                await asyncio.sleep(0.1)
                num = q.qsize()
                for _ in range(num):
                    dm = q.get_nowait()
                    if dm.get('name',0):
                        dm['time'] = '+%.2f'%(dm['time'].timestamp()-starttime)
                        self.danmu.append(dm)
                        self.dmcnt+=1

            await dmc.stop()

        def dm_writer(splitSec:int=0,fname:str=''):
            monitor = threading.Thread(target=asyncio.run,args=(danmu_monitor(),),daemon=True)
            monitor.start()
            part = 0
            savetime = 5
            if splitSec:
                fname = fname + f'-part{part:03d}.json'
            else:
                fname = fname + '.json'

            while not self._stop:
                time.sleep(0.5)
                if splitSec and int(self.duration/splitSec)!=part:
                    with open(os.path.join(self._save,fname),'w',encoding='utf-8') as f:
                        json.dump(self.danmu,f,indent=4, separators=(',', ': '),ensure_ascii=False)
                    self.danmu = []
                    part+=1
                    fname = fname.replace('part%03d'%(part-1),'part%03d'%part)
                    global starttime
                    starttime = datetime.now().timestamp()
                elif int(self.duration)%savetime == 0:
                    with open(os.path.join(self._save,fname),'w',encoding='utf-8') as f:
                        json.dump(self.danmu,f,indent=4, separators=(',', ': '),ensure_ascii=False)
            
            with open(os.path.join(self._save,fname),'w',encoding='utf-8') as f:
                json.dump(self.danmu,f,indent=4, separators=(',', ': '),ensure_ascii=False)
            self.danmu = []
                
        t = threading.Thread(target=dm_writer,args=(splitSec,fname),daemon=True)
        t.start()
        return t
        
    def download(self,splitSec:int=0,fname=None,rectype='all'):
        if not os.path.exists(self._save):
            os.makedirs(self._save)
        if not fname:
            fname = f'{self._name}-{time.strftime("%Y%m%d-%H%M%S",time.localtime())}'

        if rectype == 'video':
            self.video_proc = self._dl_video(splitSec,fname)
        elif rectype == 'danmu':
            self.danmu_thread = self._dl_damuku(splitSec,fname)
        else:
            self.video_proc = self._dl_video(splitSec,fname)
            self.danmu_thread = self._dl_damuku(splitSec,fname)
        
        starttime = datetime.now().timestamp()
        ffmpegout = ''

        while not self._stop:
            if rectype in ['video','all']:
                try:
                    self._ffmpegoutfile.seek(0)
                    out = self._ffmpegoutfile.readlines()
                    if out:
                        ffmpegout = out
                    if 'video:' in ffmpegout[-1].decode('utf-8'):
                        self.stop()
                        return ffmpegout[-1]
                    elif 'frame=' in ffmpegout[-1].decode('utf-8'):
                        print(f'\r正在录制:{self._name}, 录制时间:{int(self.duration)}秒, 弹幕数量:{self.dmcnt}.',end='',file=sys.stdout)
                except:
                    pass
            else:
                print(f'\r正在录制:{self._name}, 录制时间:{int(self.duration)}秒, 弹幕数量:{self.dmcnt}.',end='',file=sys.stdout)
            time.sleep(0.5)
            self.duration = datetime.now().timestamp()-starttime

    def stop(self):
        self._stop = True
        try:
            self.video_proc.communicate(b'q')
            self._ffmpegoutfile.close()
            self.video_proc.wait()
        except:
            pass
        try:
            self.danmu_thread.join()
        except:
            pass

        
        


        
