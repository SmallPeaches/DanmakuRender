import asyncio
import logging
import os
import time
import threading
from datetime import datetime
from os.path import *

from DMR.LiveAPI.danmaku import DanmakuClient
from DMR.utils import sec2hms, hms2sec, BGR2RGB

def get_length(string:str,fontsize):
    length = 0
    for s in string:
        if len(s.encode('utf-8')) == 1:
            length += 0.5*fontsize
        else:
            length += fontsize
    return int(length)

class DanmakuWriter():
    def __init__(self,url,output,segment,description,width,height,margin,dst,dmrate,font,fontsize,overflow_op,dmduration,opacity,auto_fontsize,outlinecolor,outlinesize,dm_delay_fixed,dm_auto_restart,**kwargs) -> None:
        self.stoped = False

        self.url = url
        self.output = output
        self.segment = segment
        self.height = height
        self.width = width
        self.dmrate = dmrate
        if auto_fontsize:
            self.fontsize = int(width / 1920 * fontsize)
        else:
            self.fontsize = int(fontsize)
        self.font = font

        self.margin = margin
        self.dst = dst # Distance from screen top
        self.overflow_op = overflow_op
        self.dmduration = dmduration
        self.opacity = hex(255-int(opacity*255))[2:].zfill(2)
        self.outlinecolor = str(outlinecolor).zfill(6)
        self.outlinesize = outlinesize
        self.dm_delay_fixed = dm_delay_fixed
        self.dm_auto_restart = dm_auto_restart
        self.kwargs = kwargs

        self.lock = threading.Lock()
        self.ntrack = int(((height - dst) * dmrate - self.fontsize) / (self.fontsize + margin))
        self.trackinfo = [None for _ in range(self.ntrack)]

        self.meta_info = [
            '[Script Info]',
            f'Title: {description}',
            'ScriptType: v4.00+',
            'Collisions: Normal',
            f'PlayResX: {self.width}',
            f'PlayResY: {self.height}',
            'Timer: 100.0000',
            '',
            '[V4+ Styles]',
            'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding',
            # f'Style: Fix,Microsoft YaHei UI,25,&H66FFFFFF,&H66FFFFFF,&H66000000,&H66000000,1,0,0,0,100,100,0,0,1,2,0,2,20,20,2,0',
            f'Style: R2L,{self.font},{self.fontsize},&H{self.opacity}ffffff,,&H{self.opacity}{self.outlinecolor},,-1,0,0,0,100,100,0,0,1,{outlinesize},0,1,0,0,0,0',
            '',
            '[Events]',
            'Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text',
        ]
        self.part = 0
        
        import platform
        if platform.system()=='Windows':
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    def start(self, self_segment=False):
        self.starttime = datetime.now().timestamp()
        self.part_start_time = self.duration
        self.dm_file = self.output.replace(f'%03d','%03d'%self.part)
        with self.lock, open(self.dm_file,'w',encoding='utf-8') as f:
            for info in self.meta_info:
                f.write(info+'\n')

        def monitor():
            while not self.stoped:
                self.split()
                time.sleep(self.segment)
        
        if self_segment:
            self.monitor = threading.Thread(target=monitor,daemon=True)
            self.monitor.start()
        
        return self.start_dmc()
  
    @property
    def duration(self):
        return datetime.now().timestamp() - self.starttime
    
    def split(self, filename=None):
        self.part += 1
        self.part_start_time = self.duration
        if filename:
            try:
                with self.lock:
                    os.rename(self.dm_file, filename)
            except Exception as e:
                logging.error(e)
                logging.error(f'弹幕 {self.dm_file} 分段失败.')
        dm_file = self.output.replace(f'%03d','%03d'%self.part)
        logging.debug(f'New DMfile: {dm_file}')
        if not self.stoped:
            with self.lock, open(dm_file,'w',encoding='utf-8') as f:
                for info in self.meta_info:
                    f.write(info+'\n')
            self.dm_file = dm_file

    def dm_available(self,dm) -> bool:
        if not (dm.get('msg_type') == 'danmaku'):
            return 
        if not dm.get('name'):
            return 
        if '\{' in dm.get('content'):
            return 
        return True
    
    def start_dmc(self):
        async def danmu_monitor():
            q = asyncio.Queue()

            async def dmc_task():
                dmc = DanmakuClient(self.url, q)
                try:
                    await dmc.start()
                except asyncio.CancelledError:
                    await dmc.stop()
                    logging.debug('Cancel the future.')
                except Exception as e:
                    await dmc.stop()
                    logging.exception(e)
                
            task = asyncio.create_task(dmc_task())
            last_dm_time = datetime.now().timestamp()
            retry = 0

            while not self.stoped:
                try:
                    dm = q.get_nowait()
                    dm['time'] = self.duration - self.dm_delay_fixed
                    if self.dm_available(dm):
                        if self.add(dm):
                            last_dm_time = datetime.now().timestamp()
                    continue
                except asyncio.QueueEmpty:
                    pass
                        
                if task.done():
                    logging.error('弹幕下载线程异常退出，正在重试...')
                    task.cancel()
                    retry += 1
                    last_dm_time = datetime.now().timestamp()
                    await asyncio.sleep(min(5*retry,300))
                    task = asyncio.create_task(dmc_task())
                    continue

                if self.dm_auto_restart and datetime.now().timestamp()-last_dm_time>self.dm_auto_restart:
                    logging.error('获取弹幕超时，正在重试...')
                    task.cancel()
                    retry += 1
                    last_dm_time = datetime.now().timestamp()
                    await asyncio.sleep(min(5*retry,300))
                    task = asyncio.create_task(dmc_task())
                    continue
                
                await asyncio.sleep(0.1)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                logging.debug("DMC task cancelled.")

        new_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(new_loop)
        asyncio.get_event_loop().run_until_complete(danmu_monitor())

    def add(self,dm):
        tid = 0
        maxbias = -1e5
        
        def calc_bias(dm, tic):
            if not dm:
                return self.width
            dm_length = get_length(dm['content'], self.fontsize)
            bias = (tic - dm['time']) * (dm_length + self.width) / self.dmduration - dm_length 
            return bias
        
        for i,latest_dm in enumerate(self.trackinfo):
            bias = calc_bias(latest_dm, dm['time'])
            if bias > 0.2 * self.width:
                tid = i
                maxbias = bias
                break
            if bias > maxbias:
                maxbias = bias
                tid = i
        
        dm_length = get_length(dm['content'], self.fontsize)
        if maxbias < 0.05 * self.width and self.overflow_op == 'ignore':
            return False
        
        self.trackinfo[tid] = dm
        x0 = self.width + dm_length
        x1 = -dm_length
        y = self.fontsize + (self.fontsize + self.margin) * tid

        t0 = dm['time'] - self.part_start_time
        t1 = t0 + self.dmduration

        if t0 < 0:
            return False

        t0 = '%02d:%02d:%02.2f'%sec2hms(t0)
        t1 = '%02d:%02d:%02.2f'%sec2hms(t1)
        
        # set ass Dialogue
        dm_info = f'Dialogue: 0,{t0},{t1},R2L,,0,0,0,,'
        dm_info += '{\move(%d,%d,%d,%d)}'%(x0, y + self.dst, x1, y + self.dst)
        dm_info += '{\\1c&H%s&}'%(self.opacity + BGR2RGB(dm['color']))
        content = dm['content'].replace('\n',' ').replace('\r',' ')
        dm_info += content

        with self.lock, open(self.dm_file, 'a', encoding='utf-8') as f:
            f.write(dm_info + '\n')
        
        return True

    def stop(self):
        self.stoped = True
        logging.debug('danmaku writer stoped.')
        return True

