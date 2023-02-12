from datetime import datetime
import logging
import signal
import subprocess
import sys
import os
import asyncio
import threading
import time
import multiprocessing
import queue
import glob

from DMR.message import PipeMessage
from .ffmpegrender import FFmpegRender
from DMR.LiveAPI import *
from os.path import join,exists
from DMR.utils import *

def isvideo(path:str) -> bool:
    ext = path.split('.')[-1]
    if ext in ['mp4','flv']:
        return True
    else:
        return False

class Render():
    def __init__(self, output_dir, pipe, format, engine='ffmpeg', debug=False, **kwargs) -> None:
        self.output_dir = output_dir
        self.sender = pipe
        self.format = format
        self.kwargs = kwargs
        self.debug = debug
        self.rendering = False
        self.wait_queue = queue.Queue()
        self.render = FFmpegRender(self.output_dir, debug=self.debug, **kwargs)

    def pipeSend(self,msg,type='info',**kwargs):
        if self.sender:
            self.sender.put(PipeMessage('render',msg=msg,type=type,**kwargs))
        else:
            print(PipeMessage('render',msg=msg,type=type,**kwargs))

    def start(self):
        self.stoped = False
        thread = threading.Thread(target=self.render_queue,daemon=True)
        thread.start()
        return thread

    def add(self, video, group=None, video_info=None, **kwargs):
        if video == 'end':
            self.wait_queue.put({
                'msg_type': 'end',
                'group': group
            })
            return 
        
        danmaku = os.path.splitext(video)[0] + '.ass'
        filename = os.path.splitext(os.path.basename(video))[0] + f'（带弹幕版）.{self.format}'
        if self.output_dir:
            output_dir = self.output_dir
        else:
            output_dir = os.path.dirname(video)+'（带弹幕版）'
        os.makedirs(output_dir,exist_ok=True)
        output = join(output_dir,filename)
        if self.rendering:
            logging.warn('弹幕渲染速度慢于录制速度，可能导致队列阻塞.')
        self.wait_queue.put({
            'msg_type':'render',
            'video':video,
            'danmaku':danmaku,
            'output':output,
            'group':group,
            'video_info':video_info,
            'kwargs': kwargs,
        })
        
    def render_queue(self):
        while not self.stoped:
            task = self.wait_queue.get()
            if task.get('msg_type') == 'end':
                self.pipeSend(task.get('group'),'end')
            self.rendering = True
            logging.info(f'正在渲染: {task["video"]}')
            try:
                info = self.render.render_one(**task)
                if task.get('video_info'):
                    task['video_info'] = task['video_info'].copy()
                    task['video_info']['has_danmu'] = '（带弹幕版）'
                self.pipeSend(task['output'],desc=info,**task)
            except KeyboardInterrupt:
                self.stop()
            except Exception as e:
                logging.exception(e)
                self.pipeSend(task['output'],'error',desc=e)
            self.rendering = False

    def render_only(self, input_dir):
        files = glob.glob(input_dir+'/*')
        videos = [f for f in files if isvideo(f)]
        for vid in videos:
            filename = os.path.splitext(os.path.basename(vid))[0] + f'（带弹幕版）.{self.format}'
            if self.output_dir:
                output_dir = self.output_dir
            else:
                output_dir = os.path.dirname(vid)+'（带弹幕版）'
            os.makedirs(output_dir,exist_ok=True)
            output = join(output_dir,filename)
            if exists(output) and FFprobe.get_duration(output) - FFprobe.get_duration(vid) < 30:
                logging.info(f'视频 {vid} 已经存在带弹幕视频 {output}，跳过渲染.')
                continue
            danmu = os.path.splitext(vid)[0] + '.ass'
            if not exists(danmu):
                logging.info(f'视频 {vid} 不存在匹配的弹幕文件，跳过渲染.')
                continue

            logging.info(f'正在渲染: {vid}')
            self.render.render_one(**{
                'video':vid,
                'danmaku':danmu,
                'output':output
            })

    def stop(self):
        self.stoped = True
        if self.rendering:
            logging.warn('渲染被提前终止，带弹幕的视频可能不完整.')
            try:
                self.render.stop()
            except Exception as e:
                logging.debug(e)
            self.rendering = False
        
