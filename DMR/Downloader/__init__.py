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
    def __init__(self, url, output_dir, pipe, segment:int, output_name=None, taskname=None, danmaku=True, video=True, end_cnt=0, vid_format='flv', flow_cdn=None, engine='ffmpeg', debug=False, **kwargs) -> None:
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
        self.output_name = join(output_dir, output_name+f'.{vid_format}')

        # init stream info
        self.sinfo = ()
        while not self.sinfo:
            self.sinfo = self.liveapi.GetStreamerInfo()
        self.taskname = self.sinfo[1]
        os.makedirs(self.output_dir,exist_ok=True)
    
    def pipeSend(self,msg,type='info',**kwargs):
        if self.sender:
            self.sender.put(PipeMessage('downloader',msg=msg,type=type,group=self.taskname,**kwargs))
        else:
            print(PipeMessage('downloader',msg=msg,type=type,group=self.taskname,**kwargs))

    def check_segment(self):
        nextfile = self._output_fn.replace(r'%03d','%03d'%(self._seg_part+1))
        if exists(nextfile) or self.stoped:
            thisfile = self._output_fn.replace(r'%03d','%03d'%self._seg_part)
            if self.sinfo is None:
                return 
            duration = FFprobe.get_duration(thisfile)
            if duration < 0:
                duration = self.segment
            t0 = datetime.now() - timedelta(seconds=duration)
            video_info = {
                'url': self.url,
                'taskname': self.taskname,
                'streamer': self.sinfo[1],
                'title': self.sinfo[0],
                'time': t0,
                'has_danmu': '',
                'duration': duration
            }
            try:
                newfile = replace_keywords(self.output_name, video_info)
                os.rename(thisfile, newfile)
                if self.danmaku:
                    newdmfile = newfile.replace(f'.{self.vid_format}','.ass')
                    self.dmw.split(newdmfile)
            except Exception as e:
                logging.error(f'视频 {thisfile} 分段失败.')
                logging.exception(e)
                if self.danmaku:
                    self.dmw.split()
                newfile = thisfile

            self.pipeSend(newfile,'split',video_info=video_info)
            self._seg_part += 1

            # 更新 start time
            self.segment_start_time += timedelta(seconds=duration)
            # 更新 stream info
            self.sinfo = ()
            while not self.sinfo:
                self.sinfo = self.liveapi.GetStreamerInfo()

    def segment_helper(self, output:str):
        self._output_fn = output + f'.{self.vid_format}'
        self._seg_part = 0
        while not self.stoped:
            try:
                self.check_segment()
            except Exception as e:
                logging.exception(e)
            time.sleep(5)

    def start_once(self):
        os.makedirs(self.output_dir,exist_ok=True)
        
        stream_url = self.liveapi.GetStreamURL(flow_cdn=self.flow_cdn)
        stream_request_header = self.liveapi.GetStreamHeader()

        if not self.liveapi.IsStable():
            stream_url_2 = self.liveapi.GetStreamURL(flow_cdn=self.flow_cdn)
            stream_request_header_2 = self.liveapi.GetStreamHeader()

        width, height = FFprobe.get_resolution(stream_url_2,stream_request_header_2)
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

        # init start time
        self.segment_start_time = datetime.now()

        if self.danmaku:
            description = f'{filename}的弹幕文件, {self.url}, powered by DanmakuRender: https://github.com/SmallPeaches/DanmakuRender.'
            self.dmw = DanmakuWriter(self.url,output,self.segment,description,self.width,self.height,**self.kwargs)
            self.dmw.start(self_segment=not self.video)
        
        if self.video:
            self.downloader.start_helper()
        else:
            while self.loop:
                if not self.liveapi.Onair():
                    break
                time.sleep(60)

    def start_helper(self):
        self.loop = True
        end_cnt = 0
        restart_cnt = 0
        if not self.liveapi.Onair():
            self.pipeSend('end')
            time.sleep(60)

        while self.loop:
            if not self.liveapi.Onair():
                time.sleep(60)
                restart_cnt = 0
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
                    time.sleep(min(restart_cnt*10,30))
                    restart_cnt += 1
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
        if self.danmaku:
            try:
                self.dmw.stop()
            except Exception as e:
                logging.exception(e)
        if self.video:
            try:
                self.downloader.stop()
            except Exception as e:
                logging.exception(e)
        try:
            self.check_segment()
        except Exception as e:
            logging.exception(e)
        