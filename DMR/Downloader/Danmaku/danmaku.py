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
from DMR.utils import SimpleDanmaku, replace_keywords

__all__ = ['DanmakuDownloader']

class DanmakuDownloader():
    def __init__(self,
                 url:str,
                 output:str,
                 segment:float,
                 dm_format:str,
                 dm_filter:dict=None,
                 dm_template:dict=None,
                 dm_stream_option:dict={},
                 advanced_dm_args:dict={},
                 **kwargs) -> None:
        self.stoped = False

        self.logger = logging.getLogger(__name__)
        self.url = url
        self.output = output
        self.segment = segment
        self.dm_format = dm_format
        self.dm_stream_option = dm_stream_option
        self.advanced_dm_args = advanced_dm_args
        self.dm_template = dm_template if dm_template else {}
        self.dm_delay_fixed = self.advanced_dm_args.get('dm_delay_fixed', 6)
        self.dm_auto_restart = self.advanced_dm_args.get('dm_auto_restart', 300)
        self.dm_extra_inputs = self.advanced_dm_args.get('dm_extra_inputs', [])
        self.dm_file_min_time = self.advanced_dm_args.get('dm_file_min_time', 10)

        self.dm_filter = dm_filter.copy() if dm_filter else {}
        try:
            keywords_filter = dm_filter['keywords']
            if not keywords_filter:
                keywords_filter = []
            elif isinstance(keywords_filter, str):
                keywords_filter = [keywords_filter]
            elif isinstance(keywords_filter, list):
                pass
            else:
                raise ValueError('dm_filter.keywords must be a list or str.')
            keywords_filter = [re.compile(str(x)) for x in keywords_filter]
            self.dm_filter['keywords'] = keywords_filter
        except Exception as e:
            self.logger.warning(f'弹幕屏蔽词{keywords_filter}设置错误:{e}，此功能将不会生效.')
            self.dm_filter['keywords'] = []
        
        try:
            username_filter = dm_filter['username']
            if not username_filter:
                username_filter = []
            elif isinstance(username_filter, str):
                username_filter = [username_filter]
            elif isinstance(username_filter, list):
                pass
            else:
                raise ValueError('dm_filter.username must be a list or str.')
            username_filter = [re.compile(str(x)) for x in username_filter]
            self.dm_filter['username'] = username_filter
        except Exception as e:
            self.logger.warning(f'用户屏蔽{username_filter}设置错误:{e}，此功能将不会生效.')
            self.dm_filter['username'] = []
        
        self.kwargs = kwargs
        self.part = 0

        if platform.system() == 'Windows':
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        
        if dm_format == 'ass':
            from .asswriter import AssWriter
            self.dmwriter = AssWriter(dm_template=self.dm_template, **self.kwargs)
        else:
            raise NotImplementedError(f"unsupported danmaku format {dm_format}")

    def time_fix(self, time_error):
        self.part_start_time -= time_error

    def start(self, self_segment=False):
        self.start_time = datetime.now().timestamp()
        self.part_start_time = self.start_time
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
    
    def split(self, filename:str=None):
        self.part += 1
        self.part_start_time = datetime.now().timestamp()
        old_dm_file = self.dm_file
        if not self.stoped:
            new_dm_file = self.output.replace(f'%03d','%03d'%self.part)
            self.logger.debug(f'New DMfile: {new_dm_file}')
            self.dmwriter.open(new_dm_file)
            self.dm_file = new_dm_file
        if filename:
            try:
                os.rename(old_dm_file, filename)
            except Exception as e:
                self.logger.error(f'弹幕 {old_dm_file} 分段失败: {e}.')

    def dm_available(self, dm:SimpleDanmaku) -> bool:
        if dm.time < 0 \
                or not dm.text \
                or not dm.uname \
                or dm.dtype in ['other', 'others'] \
                or not dm.dtype:
            return False

        if self.dm_filter.get('dm_type', 'danmaku') != 'all':
            if dm.dtype not in self.dm_filter.get('dm_type', 'danmaku'):
                return False

        for keyword in self.dm_filter['keywords']:
            if keyword.search(dm.text):
                return False

        for username in self.dm_filter['username']:
            if username.fullmatch(dm.uname):
                return False
            
        if max_length := self.dm_filter.get('max_length'):
            if len(dm.text) > max_length:
                return False

        return True

    def start_dmc(self):
        async def danmu_monitor(url:str=None):
            if not url:
                url = self.url  
            q = asyncio.Queue()

            async def dmc_task():
                dmc = DanmakuClient(url, q, **self.dm_stream_option)
                try:
                    await dmc.start()
                except asyncio.CancelledError:
                    await dmc.stop()
                    self.logger.debug('Cancel the future.')
                except Exception as e:
                    await dmc.stop()
                    self.logger.exception(e)
                
            task = asyncio.create_task(dmc_task())
            last_dm_time = datetime.now().timestamp()
            retry = 0

            while not self.stoped:
                try:
                    dm = q.get_nowait()
                    if not isinstance(dm, SimpleDanmaku):
                        dm = SimpleDanmaku(
                            dtype=dm.get('msg_type', 'other'),
                            uname=dm.get('name', ''),
                            content=dm.get('content', ''),
                            timestamp=dm.get('timestamp', datetime.now().timestamp()),
                            color=dm.get('color', 'ffffff'),
                        )
                    # 将绝对时间转换为相对时间
                    dm.time = dm.timestamp - self.part_start_time - self.dm_delay_fixed
                    # 载入弹幕模板
                    if dm_templ := self.dm_template.get(dm.dtype):
                        dm.text = replace_keywords(dm_templ, dm)
                    if self.dm_available(dm):
                        retry = 0
                        if self.dmwriter.add(dm):
                            last_dm_time = datetime.now().timestamp()
                    continue
                except asyncio.QueueEmpty:
                    pass
                
                if task.done():
                    self.logger.error(f'{self.url} 弹幕下载线程异常退出，正在重试...')
                    try:
                        self.logger.debug(task.result())
                    except:
                        self.logger.exception(task.exception())
                    task.cancel()
                    retry += 1
                    last_dm_time = datetime.now().timestamp()
                    await asyncio.sleep(min(15*retry,60))
                    task = asyncio.create_task(dmc_task())
                    continue

                if self.dm_auto_restart and datetime.now().timestamp()-last_dm_time>self.dm_auto_restart:
                    self.logger.error(f'{self.url} 获取弹幕超时，正在重试...')
                    task.cancel()
                    last_dm_time = datetime.now().timestamp()
                    task = asyncio.create_task(dmc_task())
                    continue
                
                await asyncio.sleep(0.1)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                self.logger.debug("DMC task cancelled.")

        danmu_monitor_sets = []
        for url in [self.url] + self.dm_extra_inputs:
            danmu_monitor_sets.append(danmu_monitor(url))
        new_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(new_loop)
        asyncio.get_event_loop().run_until_complete(asyncio.gather(*danmu_monitor_sets))

    def stop(self):
        self.stoped = True
        self.logger.debug('danmaku writer stoped.')

        # 删除过短的弹幕文件
        if datetime.now().timestamp() - self.part_start_time < self.dm_file_min_time:
            try:
                os.remove(self.dm_file)
            except Exception as e:
                self.logger.debug(e)
        return True
