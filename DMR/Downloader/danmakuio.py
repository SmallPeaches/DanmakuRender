import asyncio
import logging
import os
import re
import time
import threading
import platform
from datetime import datetime
from os.path import *

from DMR.LiveAPI.danmaku import DanmakuClient
from DMR.utils import sec2hms, hms2sec, BGR2RGB
from DMR.danmaku import SimpleDanmaku

class DanmakuWriter():
    def __init__(self,
                 url:str,
                 output:str,
                 segment:float,
                 dm_format:str,
                 dm_delay_fixed:int,
                 dm_auto_restart:bool,
                 dm_filter:str,
                 **kwargs) -> None:
        self.stoped = False

        self.url = url
        self.output = output
        self.segment = segment
        self.dm_format = dm_format
        self.dm_delay_fixed = dm_delay_fixed
        self.dm_auto_restart = dm_auto_restart
        self.dm_filter = dm_filter
        self.kwargs = kwargs

        self.part = 0

        if platform.system()=='Windows':
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        
        if dm_format == 'ass':
            from .asswriter import AssWriter
            self.dmwriter = AssWriter(**self.kwargs)
        else:
            raise NotImplementedError(f"unsupported danmaku format {dm_format}")

    def start(self, self_segment=False):
        self.starttime = datetime.now().timestamp()
        self.part_start_time = self.duration
        self.dm_file = self.output.replace(f'%03d','%03d'%self.part)
        self.dmwriter.open(self.dm_file)

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
        self.dmwriter.close()
        if filename:
            try:
                os.rename(self.dm_file, filename)
            except Exception as e:
                logging.error(e)
                logging.error(f'弹幕 {self.dm_file} 分段失败.')
        if not self.stoped:
            dm_file = self.output.replace(f'%03d','%03d'%self.part)
            logging.debug(f'New DMfile: {dm_file}')
            self.dmwriter.open(dm_file)
            self.dm_file = dm_file

    def dm_available(self,dm) -> bool:
        if not (dm.get('msg_type') == 'danmaku'):
            return False
        if not dm.get('name'):
            return False
        if self.dm_filter and re.search(self.dm_filter, dm.get('content','')):
            return False
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
                    dm['time'] = self.duration - self.part_start_time - self.dm_delay_fixed
                    if dm['time'] > 0 and self.dm_available(dm):
                        danmu = SimpleDanmaku(
                            time=dm['time'],
                            dtype='danmaku',
                            uname=dm['name'],
                            color=dm['color'],
                            content=dm['content']
                        )
                        if self.dmwriter.add(danmu):
                            last_dm_time = datetime.now().timestamp()
                    continue
                except asyncio.QueueEmpty:
                    pass
                
                if task.done():
                    logging.error('弹幕下载线程异常退出，正在重试...')
                    try:
                        logging.debug(task.result())
                    except:
                        logging.exception(task.exception())
                    task.cancel()
                    retry += 1
                    last_dm_time = datetime.now().timestamp()
                    await asyncio.sleep(min(15*retry,120))
                    task = asyncio.create_task(dmc_task())
                    continue

                if self.dm_auto_restart and datetime.now().timestamp()-last_dm_time>self.dm_auto_restart:
                    logging.error('获取弹幕超时，正在重试...')
                    task.cancel()
                    retry += 1
                    last_dm_time = datetime.now().timestamp()
                    await asyncio.sleep(min(15*retry,120))
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

    def stop(self):
        self.stoped = True
        logging.debug('danmaku writer stoped.')
        if self.duration < 10:
            try:
                os.remove(self.dm_file)
            except Exception as e:
                logging.debug(e)
        return True

