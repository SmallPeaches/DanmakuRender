from datetime import datetime, timedelta
import logging
import os
import threading
import time
from functools import partial
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from os.path import join,exists,splitext

from DMR.Downloader.danmakuio import DanmakuWriter
from DMR.message import PipeMessage
from DMR.LiveAPI import *
from DMR.utils import *

class Downloader():
    def __init__(self, 
                 url, 
                 output_dir, 
                 pipe, 
                 segment:int, 
                 output_name=None, 
                 taskname=None, 
                 danmaku=True, 
                 video=True, 
                 end_cnt=0, 
                 vid_format='flv', 
                 flow_cdn=None, 
                 advanced_video_args:dict=None,
                 advanced_dm_args:dict=None,
                 engine='ffmpeg', 
                 debug=False, 
                 **kwargs
        ) -> None:
        self.taskname = taskname
        self.url = url
        self.plat, self.rid = split_url(url)
        self.liveapi = LiveAPI(self.plat, self.rid)
        self.output_dir = output_dir
        self.sender = pipe
        self.kwargs = kwargs
        self.debug = debug
        self.vid_format = vid_format
        self.segment = segment
        self.danmaku = danmaku
        self.video = video
        self.flow_cdn = flow_cdn
        self.end_cnt = end_cnt
        self.advanced_video_args = advanced_video_args if advanced_video_args else {}
        self.advanced_dm_args = advanced_dm_args if advanced_dm_args else {}
        self.output_name = join(output_dir, output_name+f'.{vid_format}')

        self.engine = engine
        if self.engine == 'ffmpeg':
            from .ffmpegio import FFmpegDownloader
            self.download_class = FFmpegDownloader
        elif self.engine == 'streamgears':
            from .streamgearsio import StreamgearsDownloader
            self.download_class = StreamgearsDownloader
        else: 
            raise NotImplementedError(f'No Downloader Named {self.engine}.')

        os.makedirs(self.output_dir,exist_ok=True)
    
    def pipeSend(self,msg,type='info',**kwargs):
        if self.sender:
            self.sender.put(PipeMessage('downloader',msg=msg,type=type,group=self.taskname,**kwargs))
        else:
            print(PipeMessage('downloader',msg=msg,type=type,group=self.taskname,**kwargs))

    def stable_callback(self, time_error):
        if hasattr(self, 'dmw'):
            self.dmw.time_fix(time_error)

    def segment_callback(self, filename:str):
        if self.segment_info is None or not exists(filename):
            logging.debug(f'No video file {filename}')
            return 
        t0 = self.segment_start_time
        video_duration = datetime.now().timestamp() - t0.timestamp()
        video_info = {
            'url': self.url,
            'taskname': self.taskname,
            'streamer': self.segment_info[1],
            'title': self.segment_info[0],
            'time': t0,
            'has_danmu': '',
            'duration': video_duration,
        }
        try:
            newfile = replace_keywords(self.output_name, video_info, replace_invalid=True)
            os.rename(filename, newfile)
            if self.danmaku:
                newdmfile = splitext(newfile)[0]+'.ass'
                self.dmw.split(newdmfile)
        except Exception as e:
            logging.error(e)
            logging.error(f'视频 {newfile} 分段失败，将使用默认名称 {filename}.')
            newfile = filename
            if self.danmaku:
                newdmfile = splitext(newfile)[0]+'.ass'
                self.dmw.split(newdmfile)
        self.pipeSend(newfile,'split',video_info=video_info)
        new_segment_info = self.liveapi.GetStreamerInfo()
        if new_segment_info:
            self.segment_info = new_segment_info
        self.segment_start_time = datetime.now()

    def start_once(self):
        self.stoped = False
        
        # init stream info
        self.segment_info = None
        while not self.segment_info:
            self.segment_info = self.liveapi.GetStreamerInfo()
        self.segment_start_time = datetime.now()
        os.makedirs(self.output_dir,exist_ok=True)
        
        if self.liveapi.IsStable():
            stream_url = self.liveapi.GetStreamURL(flow_cdn=self.flow_cdn, **self.advanced_video_args)
            stream_request_header = self.liveapi.GetStreamHeader()
            width, height = FFprobe.get_resolution(stream_url,stream_request_header)
        else:
            stream_url = partial(self.liveapi.GetStreamURL, flow_cdn=self.flow_cdn, **self.advanced_video_args)
            stream_request_header = self.liveapi.GetStreamHeader
            width, height = FFprobe.get_resolution(stream_url(),stream_request_header())

        if not (width and height):
            default_resolution = self.advanced_video_args.get('default_resolution', (1920, 1080))
            logging.warn(f'无法获取视频大小，使用默认值 {default_resolution}.')
            width, height = default_resolution
        
        self.width,self.height = width, height

        self.downloader = None
        self.dmw = None

        def danmaku_thread():
            description = f'{self.output_name}的弹幕文件, {self.url}, Powered by DanmakuRender: https://github.com/SmallPeaches/DanmakuRender.'
            danmu_output = join(self.output_dir, f'[正在录制]{self.taskname}-{time.strftime("%Y%m%d-%H%M%S",time.localtime())}-Part%03d.ass')
            self.dmw = DanmakuWriter(self.url,
                                     danmu_output,
                                     self.segment,
                                     description=description,
                                     width=self.width,
                                     height=self.height,
                                     advanced_dm_args=self.advanced_dm_args,
                                     **self.kwargs)
            self.dmw.start(self_segment=not self.video)
        
        def video_thread():
            self.downloader = self.download_class(
                stream_url=stream_url,
                header=stream_request_header,
                output=self.output_name,
                segment=self.segment,
                url=self.url,
                taskname=self.taskname,
                advanced_video_args=self.advanced_video_args,
                segment_callback=self.segment_callback,
                stable_callback=self.stable_callback,
                debug=self.debug,
                **self.kwargs
            )
            self.downloader.start()

        self.executor = ThreadPoolExecutor(max_workers=2)
        futures = []
        if self.danmaku:
            futures.append(self.executor.submit(danmaku_thread))
        if self.video:
            futures.append(self.executor.submit(video_thread))
        
        while not self.stoped:
            try:
                for future in as_completed(futures, timeout=60):
                    return future.result()
            except TimeoutError:
                if self.liveapi.Onair() == False:
                    logging.debug('LIVE END.')
                    return

    def start_helper(self):
        self.loop = True
        stop_waited = 0  # 已经等待的时间（下播但是还没停止）
        stop_wait_time = self.end_cnt*60    # 设定的等待时间
        live_end = False
        restart_cnt = 0     # 出错重启次数
        start_check_interval = self.advanced_video_args.get('start_check_interval', 60)  # 开播检测时间
        stop_check_interval = self.advanced_video_args.get('stop_check_interval', 30)   # 下播检测间隔

        if not self.liveapi.Onair():
            self.pipeSend('end')
            live_end = True
            time.sleep(start_check_interval)

        while self.loop:
            if not self.liveapi.Onair():
                restart_cnt = 0
                if live_end:
                    time.sleep(start_check_interval)
                    stop_waited += start_check_interval
                else:
                    time.sleep(stop_check_interval)
                    stop_waited += stop_check_interval
                
                if stop_waited > stop_wait_time and not live_end:
                    live_end = True
                    self.pipeSend('end')
                continue

            try:
                stop_waited = 0
                live_end = False
                self.pipeSend('start')
                self.start_once()
            except KeyboardInterrupt:
                self.stop()
                exit(0)
            except Exception as e:
                if self.liveapi.Onair():
                    logging.exception(e)
                    self.stop_once()
                    self.pipeSend('restart','error',desc=e)
                    time.sleep(min(restart_cnt*10,60))
                    restart_cnt += 1
                    continue
                else:
                    logging.debug(e)
            
            logging.debug(f'{self.taskname} stop once.')
            self.stop_once()

    def start(self):
        thread = threading.Thread(target=self.start_helper,daemon=True)
        thread.start()
        return thread
    
    def stop(self):
        self.loop = False
        self.stop_once()
        self.pipeSend('','exit')

    def stop_once(self):
        self.stoped = True
        if self.danmaku and hasattr(self, 'dmw'):
            try:
                self.dmw.stop()
            except Exception as e:
                logging.exception(e)
        if self.video and hasattr(self, 'downloader'):
            try:
                self.downloader.stop()
            except Exception as e:
                logging.exception(e)
        try:
            if hasattr(self, 'executor'):
                self.executor.shutdown(wait=False)
        except Exception as e:
            logging.exception(e)