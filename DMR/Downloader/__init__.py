from datetime import datetime, timedelta
import logging
import signal
import subprocess
import os
import asyncio
import threading
import time
import multiprocessing
from DMR.Downloader.danmakuio import DanmakuWriter
from DMR.message import PipeMessage
from .ffmpegio import FFmpegDownloader
from DMR.LiveAPI import *
from os.path import join,exists
from DMR.utils import *

class Downloader():
    def __init__(self, url, output_dir, pipe, segment:int, taskname=None, danmaku=True, flowtype='flv', engine='ffmpeg', debug=False, **kwargs) -> None:
        self.taskname = taskname
        self.url = url
        self.output_dir = output_dir
        self.sender = pipe
        self.kwargs = kwargs
        self.debug = debug
        self.flowtype = flowtype
        self.segment = segment
        self.danmaku = danmaku

        if not self.taskname:
            self.taskname = GetStreamerInfo(url)[1]
        os.makedirs(self.output_dir,exist_ok=True)
    
    def pipeSend(self,msg,type='info',**kwargs):
        if self.sender:
            self.sender.put(PipeMessage(self.taskname,msg=msg,type=type,**kwargs))
        else:
            print(PipeMessage(self.taskname,msg=msg,type=type,**kwargs))

    def segment_helper(self, output:str):
        output = output + f'.{self.flowtype}'
        part = 0
        duration = 0
        files = []
        while not self.stoped:
            nextfile = output.replace(r'%03d','%03d'%(part+1))
            if exists(nextfile):
                thisfile = output.replace(r'%03d','%03d'%part)
                sinfo = GetStreamerInfo(self.url)
                t0 = datetime.now() - timedelta(seconds=part*self.segment)
                video_info = {
                    'url': self.url,
                    'taskname': self.taskname,
                    'streamer': sinfo[1],
                    'title': sinfo[0],
                    'time': t0,
                    'group': self.group
                }
                self.pipeSend(thisfile,'split',video_info=video_info)
                files.append(thisfile)
                part += 1
            if duration-self.segment*part > 2*self.segment:
                break
            time.sleep(10)
            duration += 10

        nextfile = output.replace(r'%03d','%03d'%(len(files)))
        if exists(nextfile):
            sinfo = GetStreamerInfo(self.url)
            t0 = datetime.now() - timedelta(seconds=part*self.segment)
            video_info = {
                    'url': self.url,
                    'taskname': self.taskname,
                    'streamer': sinfo[1],
                    'title': sinfo[0],
                    'time': t0,
                    'group': self.group
                }
            self.pipeSend(nextfile,'split',video_info=video_info)
        else:
            thisfile = output.replace(r'%03d','%03d'%part)
            sinfo = GetStreamerInfo(self.url)
            t0 = datetime.now() - timedelta(seconds=part*self.segment)
            video_info = {
                    'url': self.url,
                    'taskname': self.taskname,
                    'streamer': sinfo[1],
                    'title': sinfo[0],
                    'time': t0,
                    'group': self.group
                }
            self.pipeSend(thisfile,'split',video_info=video_info)

    def start_once(self):
        os.makedirs(self.output_dir,exist_ok=True)
        
        stream_info = GetStreamURL(self.url)
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
            self.group = '-'.join(filename.split('-')[:-1])
        else:
            filename = f'{self.taskname}-{time.strftime("%Y%m%d-%H%M%S",time.localtime())}'
            output = join(self.output_dir,filename)
            self.group = filename
        
        self.downloader = FFmpegDownloader(
            stream_url=stream_url,
            header=stream_request_header,
            output=output,
            segment=self.segment,
            pipe=self.sender,
            flowtype=self.flowtype,
            url=self.url,
            taskname=self.taskname,
            debug=self.debug,
            **self.kwargs
        )

        if self.danmaku:
            description = f'{filename}的弹幕文件, {self.url}, powered by DanmakuRender.'
            self.dmw = DanmakuWriter(self.url,output,self.segment,description,self.width,self.height,**self.kwargs)
            self.dmw.start()
        
        self.downloader.start_helper()

    def start_helper(self):
        self.loop = True
        if not Onair(self.url):
            self.pipeSend('end')
            time.sleep(30)

        while self.loop:
            if not Onair(self.url):
                time.sleep(30)
                continue

            try:
                self.pipeSend('start')
                self.start_once()
            except KeyboardInterrupt:
                self.stop()
                exit(0)
            except Exception as e:
                if Onair(self.url):
                    logging.exception(e)
                    self.pipeSend('restart','error',desc=e)
                    time.sleep(30)
                else:
                    logging.debug(e)
            
            self.pipeSend('end')
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
        try:
            self.downloader.stop()
        except Exception as e:
            logging.exception(e)
        