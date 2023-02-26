from datetime import datetime, timedelta
import logging
import os
import threading
import time
from DMR.Downloader.danmakuio import DanmakuWriter
from DMR.message import PipeMessage
from .ffmpegio import FFmpegDownloader
from DMR.LiveAPI import *
from os.path import join,exists
from DMR.utils import *

class Downloader():
    def __init__(self, url, output_dir, pipe, segment:int, taskname=None, danmaku=True, video=True, end_cnt=0, vid_format='flv', flow_cdn=None, engine='ffmpeg', debug=False, **kwargs) -> None:
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

        if not self.taskname:
            self.taskname = self.liveapi.GetStreamerInfo()[1]
        os.makedirs(self.output_dir,exist_ok=True)
    
    def pipeSend(self,msg,type='info',**kwargs):
        if self.sender:
            self.sender.put(PipeMessage(self.taskname,msg=msg,type=type,**kwargs))
        else:
            print(PipeMessage(self.taskname,msg=msg,type=type,**kwargs))

    def check_segment(self):
        nextfile = self._output_fn.replace(r'%03d','%03d'%(self._seg_part+1))
        if exists(nextfile):
            thisfile = self._output_fn.replace(r'%03d','%03d'%self._seg_part)
            sinfo = self.liveapi.GetStreamerInfo()
            if sinfo is None:
                return 
            t0 = datetime.now() - timedelta(seconds=self._seg_part*self.segment)
            video_info = {
                'url': self.url,
                'taskname': self.taskname,
                'streamer': sinfo[1],
                'title': sinfo[0],
                'time': t0,
                'has_danmu': '',
            }
            self.pipeSend(thisfile,'split',video_info=video_info)
            self._seg_part += 1
        
        if self.stoped:
            thisfile = self._output_fn.replace(r'%03d','%03d'%self._seg_part)
            sinfo = self.liveapi.GetStreamerInfo()
            if sinfo is None:
                sinfo = (self.taskname, self.taskname)
            t0 = datetime.now() - timedelta(seconds=self._seg_part*self.segment)
            video_info = {
                    'url': self.url,
                    'taskname': self.taskname,
                    'streamer': sinfo[1],
                    'title': sinfo[0],
                    'time': t0
                }
            self.pipeSend(thisfile,'split',video_info=video_info)

    def segment_helper(self, output:str):
        self._output_fn = output + f'.{self.vid_format}'
        self._seg_part = 0
        while not self.stoped:
            try:
                self.check_segment()
            except Exception as e:
                logging.exception(e)
            time.sleep(10)

    def start_once(self):
        os.makedirs(self.output_dir,exist_ok=True)
        
        stream_info = self.liveapi.GetStreamURL(flow_cdn=self.flow_cdn)
        stream_url = stream_info.get('url')
        stream_request_header = stream_info.get('header')

        width, height = FFprobe.get_resolution(stream_url,stream_request_header)
        if not (width and height):
            logging.warn(f'无法获取视频大小，使用默认值{self.kwargs.get("resolution")}.')
            width, height = self.kwargs.get("resolution")
        self.width,self.height = width, height

        self._startTime = datetime.now().timestamp()
        self.stoped = False

        if self.segment:
            filename = f'{self.taskname}-{time.strftime("%Y%m%d-%H%M%S",time.localtime())}-Part%03d'
            output = join(self.output_dir,filename)
            self.segment_thread = threading.Thread(target=self.segment_helper,args=(output,),daemon=True)
            self.segment_thread.start()
        else:
            filename = f'{self.taskname}-{time.strftime("%Y%m%d-%H%M%S",time.localtime())}'
            output = join(self.output_dir,filename)
        
        self.downloader = FFmpegDownloader(
            stream_url=stream_url,
            header=stream_request_header,
            output=output,
            segment=self.segment,
            vid_format=self.vid_format,
            url=self.url,
            taskname=self.taskname,
            debug=self.debug,
            **self.kwargs
        )

        if self.danmaku:
            description = f'{filename}的弹幕文件, {self.url}, powered by DanmakuRender: https://github.com/SmallPeaches/DanmakuRender.'
            self.dmw = DanmakuWriter(self.url,output,self.segment,description,self.width,self.height,**self.kwargs)
            self.dmw.start()
        
        if self.video:
            self.downloader.start_helper()
        else:
            while 1:
                if not self.liveapi.Onair():
                    break
                time.sleep(60)

    def start_helper(self):
        self.loop = True
        end_cnt = 0
        if not self.liveapi.Onair():
            self.pipeSend('end')
            time.sleep(60)

        while self.loop:
            if not self.liveapi.Onair():
                time.sleep(60)
                end_cnt += 1
                if end_cnt > self.end_cnt:
                    self.pipeSend('end')
                continue

            try:
                end_cnt = 0
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
                    time.sleep(30)
                    continue
                else:
                    logging.debug(e)
            
            self.stop_once()

    def start(self):
        thread = threading.Thread(target=self.start_helper,daemon=True)
        thread.start()
        return thread
    
    def stop(self):
        self.loop = False
        self.stop_once()

    def stop_once(self):
        self.stoped = True
        try:
            self.check_segment()
        except Exception as e:
            logging.exception(e)
        if self.danmaku:
            try:
                self.dmw.stop()
            except Exception as e:
                logging.exception(e)
        try:
            self.downloader.stop()
        except Exception as e:
            logging.exception(e)
        