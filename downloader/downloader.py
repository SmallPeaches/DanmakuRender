import logging
import os
import subprocess
import threading
import time
import asyncio
import json
import sys
import tempfile
import csv
from datetime import datetime
from .GetStreamURL import GetStreamURL
from .danmaku import DanmakuClient

class downloader():
    header = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'User-Agent': 'Mozilla/5.0 (Linux; Android 5.0; SM-G900P Build/LRX21T) AppleWebKit/537.36 '
                            '(KHTML, like Gecko) Chrome/75.0.3770.100 Mobile Safari/537.36 '
        }
    def __init__(self,url:str,name:str,save:str='./save',ffmpeg:str='ffmpeg.exe',timeout:int=20):
        self.danmu = []
        self.dmcnt = 0
        self._name = name
        self._url = url
        self._save = os.path.abspath(save)
        self._ffmpeg = ffmpeg
        self._timeout = timeout
        self._stop = False
        self._ffmpeg_base_args = [self._ffmpeg,'-y','-headers',''.join('%s: %s\r\n' % x for x in self.header.items()),
                                  '-rw_timeout', str(self._timeout*1e6),'-fflags', '+discardcorrupt']
    
    @property
    def duration(self):
        return self._endTime - self._startTime if self._endTime else datetime.now().timestamp() - self._startTime

    def _dl_video(self):
        self._ffmpegoutfile = tempfile.NamedTemporaryFile()
        stream_url = GetStreamURL.get_url(self._url)
        fname = self._basename + '-part%03d.mp4'
        save = os.path.join(self._save,fname)
        if not self._split:
            ffmpeg_args = [*self._ffmpeg_base_args,'-i', stream_url,'-c','copy','-movflags','frag_keyframe',save.replace(f'-part%03d','')]
        else:
            ffmpeg_args = [*self._ffmpeg_base_args,'-i', stream_url,'-c','copy',
                           '-f','segment','-segment_time',str(self._split),'-movflags','frag_keyframe',save]

        proc = subprocess.Popen(ffmpeg_args, stdin=subprocess.PIPE, stdout=self._ffmpegoutfile, stderr=self._ffmpegoutfile)
        # proc = subprocess.Popen(ffmpeg_args, stdin=subprocess.PIPE, stdout=sys.stdout, stderr=sys.stderr)
        return proc
    
    def _dl_damuku(self):
        starttime = datetime.now().timestamp()
        lock = threading.Lock()

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
                        with lock:
                            self.danmu.append(dm)
                        self.dmcnt+=1

            await dmc.stop()

        def dm_writer_json():
            part = 0
            savetime = 5
            fname = self._basename + f'-part{part:03d}.json' if self._split else self._basename + '.json'

            while not self._stop:
                time.sleep(0.5)
                if self._split and int(self.duration/self._split)!=part:
                    with open(os.path.join(self._save,fname),'w',encoding='utf-8') as f, lock:
                        json.dump(self.danmu,f,indent=4, separators=(',', ': '),ensure_ascii=False)
                        self.danmu = []
                    part+=1
                    fname = fname.replace('part%03d'%(part-1),'part%03d'%part)
                    global starttime
                    starttime = datetime.now().timestamp()
                elif int(self.duration)%savetime == 0:
                    with open(os.path.join(self._save,fname),'w',encoding='utf-8') as f:
                        json.dump(self.danmu,f,indent=4, separators=(',', ': '),ensure_ascii=False)
            
            with open(os.path.join(self._save,fname),'w',encoding='utf-8') as f, lock:
                json.dump(self.danmu,f,indent=4, separators=(',', ': '),ensure_ascii=False)
                self.danmu = []
        
        def dm_writer_csv(encoding='utf-8'):
            part = 0
            savetime = 3
            fname = self._basename + f'-part{part:03d}.csv' if self._split else self._basename + '.csv'

            with open(os.path.join(self._save,fname),'a+',encoding=encoding) as f:
                #if mode:
                    #f.write("\xef\xbb\xbf")
                f.write('time,name,content,color\n')

            while not self._stop:
                time.sleep(0.5)
                if int(self.duration)%savetime == 0:
                    with open(os.path.join(self._save,fname),'a+',encoding=encoding,newline='') as f, lock:
                        writer = csv.writer(f)
                        for dm in self.danmu:
                            writer.writerow([dm['time'],dm['name'],dm['content'],dm['color']])
                        self.danmu = []
                
                if self._split and int(self.duration/self._split)!=part:
                    part+=1
                    fname = fname.replace('part%03d'%(part-1),'part%03d'%part)
                    global starttime
                    starttime = datetime.now().timestamp()
            
            with open(os.path.join(self._save,fname),'a+',encoding=encoding,newline='') as f, lock:
                writer = csv.writer(f)
                for dm in self.danmu:
                    writer.writerow([dm['time'],dm['name'],dm['content'],dm['color']])
                self.danmu = []
        
        monitor = threading.Thread(target=asyncio.run,args=(danmu_monitor(),),daemon=True)
        monitor.start()

        if self._dmFileType == 'json':
            writer = threading.Thread(target=dm_writer_json,daemon=True)
        elif self._dmFileType == 'csv':
            writer = threading.Thread(target=dm_writer_csv,args=('utf-8',),daemon=True)
        elif self._dmFileType == 'excel':
            writer = threading.Thread(target=dm_writer_csv,args=('utf-8-sig',),daemon=True)
        writer.start()
        
        return writer
        
    def download(self,split:int=0,fname:str=None,rectype:str='all',dmFileType:str='json'):
        if not os.path.exists(self._save):
            os.makedirs(self._save)
        
        self._basename = fname if fname else f'{self._name}-{time.strftime("%Y%m%d-%H%M%S",time.localtime())}'
        self._split = split
        self._dmFileType = dmFileType
        self.dmcnt = 0
        self._startTime = datetime.now().timestamp()
        self._endTime = 0

        if rectype == 'video':
            self.video_proc = self._dl_video()
        elif rectype == 'danmu':
            self.danmu_thread = self._dl_damuku()
        else:
            self.video_proc = self._dl_video()
            self.danmu_thread = self._dl_damuku()
        
        ffmpegout = 'none'

        while not self._stop:
            if rectype in ['video','all']:
                self._ffmpegoutfile.seek(0)
                out = self._ffmpegoutfile.readlines()
                if out:
                    ffmpegout = out[-1].decode('utf-8')
                if 'video:' in ffmpegout:
                    self.stop()
                    return ffmpegout
                elif 'frame=' in ffmpegout:
                    print(f'\r正在录制:{self._name}, 录制时间:{int(self.duration)}秒, 弹幕数量:{self.dmcnt}.',end='',file=sys.stdout)
            else:
                print(f'\r正在录制:{self._name}, 录制时间:{int(self.duration)}秒, 弹幕数量:{self.dmcnt}.',end='',file=sys.stdout)
            
            time.sleep(0.5)

    def stop(self):
        self._stop = True
        self._endTime = datetime.now().timestamp()
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

        
        


        
