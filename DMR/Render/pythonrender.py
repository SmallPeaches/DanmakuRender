import os
import queue
import signal
import re
import sys
import subprocess
import multiprocessing
import logging
import tempfile
import time

from .baserender import BaseRender
from .pythonrender_helper import *
from os.path import join, exists

class PythonRender(BaseRender):
    def __init__(self, hwaccel_args:list, vencoder:str, vencoder_args:list, aencoder:str, aencoder_args:list, output_resize:str, ffmpeg:str, nproc:int, bufsize, debug=False, **kwargs):
        self.rendering = False
        self.hwaccel_args = hwaccel_args if hwaccel_args is not None else []
        self.vencoder = vencoder
        self.vencoder_args = vencoder_args
        self.aencoder = aencoder
        self.aencoder_args = aencoder_args
        self.output_resize = output_resize
        self.ffmpeg = ffmpeg
        self.nproc = nproc
        self.bufsize = bufsize
        self.debug = debug

    def render_helper(self, video: str, danmaku: str, output: str, logfile):
        danmu_info = parser_ass(danmaku)
        w, h = danmu_info['width'], danmu_info['validheight']

        video_info = FFprobe.run_ffprobe(video)
        fps = video_info['streams'][0]['r_frame_rate']
        
        ffmpeg_args = [self.ffmpeg, '-y']
        ffmpeg_args += self.hwaccel_args

        if self.output_resize: 
            scale_args = ['-s', self.output_resize]
        else:
            scale_args = []
        
        ffmpeg_args =   [
            self.ffmpeg, '-y',
            *self.hwaccel_args,
            '-thread_queue_size', '16',
            '-i', video,

            '-thread_queue_size', '16',
            '-f', 'rawvideo',
            '-s', '%dx%d'%(w,h), 
            '-pix_fmt', 'rgba',
            '-r', fps,
            '-i', '-',
            
            '-filter_complex','[0:v][1:v]overlay=0:0[v]',
            '-map','[v]','-map','0:a',

            '-c:v',self.vencoder,
            *self.vencoder_args,
            '-c:a',self.aencoder,
            *self.aencoder_args,

            *scale_args, 
            output,
            ]
        ffmpeg_args = [str(x) for x in ffmpeg_args]
        logging.debug(f'pythonrender ffmpeg args: {ffmpeg_args}')

        proc = multiprocessing.Process(target=main_render_proc,args=(video_info, danmu_info, ffmpeg_args, self.nproc, self.bufsize, logfile, self.debug))
        proc.start()
        proc.join()

    def render_one(self, video: str, danmaku: str, output: str, **kwargs):
        if not exists(video):
            raise RuntimeError(f'不存在视频文件 {video}，跳过渲染.')
        if not exists(danmaku):
            raise RuntimeError(f'不存在弹幕文件 {danmaku}，跳过渲染.')

        os.makedirs('.temp',exist_ok=True)
        logfile = join('.temp','pythonrender.temp')
        self.render_helper(video, danmaku, output, logfile)
        with open(logfile, 'rb') as f:
            info = None
            log = ''
            f.seek(0)
            for line in f.readlines():
                line = line.decode('utf-8',errors='ignore').strip()
                log += line + '\n'
                if line.startswith('video:'):
                    info = line
        os.remove(logfile)
        if self.debug:
            return True
        if info:
            return info
        else:
            logging.debug(f'ffmpegrender output:{log}')
            raise RuntimeError(f'{output} 渲染错误:\n{log}')
        
    def stop(self):
        pass
        
def main_render_proc(video_info, danmu_info, ffmpeg_args, nproc, bufsize, logfile, debug=False):
    qs = [multiprocessing.Queue(int(60/nproc)) for i in range(nproc)]
    procs = []

    for i in range(nproc):
        proc = multiprocessing.Process(target=sub_render_proc,args=(i, nproc, video_info, danmu_info, qs[i]),daemon=True)
        proc.start()
        procs.append(proc)
    
    if logfile is None:
        logfile = tempfile.TemporaryFile()
    elif isinstance(logfile, str):
        logfile = open(logfile,'wb')

    if debug:
        ffmpeg_proc = subprocess.Popen(ffmpeg_args, stdin=subprocess.PIPE, stdout=sys.stdout, stderr=subprocess.STDOUT,bufsize=bufsize*10**6)
    else:
        ffmpeg_proc = subprocess.Popen(ffmpeg_args, stdin=subprocess.PIPE, stdout=logfile, stderr=subprocess.STDOUT, bufsize=bufsize*10**6)

    try:
        nframes = int(video_info['streams'][0]['nb_frames'])
        for fid in range(nframes):
            pid = fid%nproc
            q:multiprocessing.Queue = qs[pid]
            try:
                framebytes = q.get(timeout=10)
            except queue.Empty:
                raise RuntimeError('')
            try:
                ffmpeg_proc.stdin.write(framebytes)
            except Exception as e:
                raise e
    finally:
        ffmpeg_proc.stdin.close()
        ffmpeg_proc.wait()
        logfile.close()

def sub_render_proc(pid, nproc, video_info, danmu_info, q:multiprocessing.Queue):
    nframes = int(video_info['streams'][0]['nb_frames'])
    fps = eval(video_info['streams'][0]['r_frame_rate'])
    all_danmu = danmu_info['danmu']
    w, h = danmu_info['width'], danmu_info['validheight']

    p = 0
    now_danmu = []
    fid = pid

    while fid < nframes:
        tic = fid/fps
        while p < len(all_danmu) and all_danmu[p]['st'] < tic:
            dm = all_danmu[p]
            dtype = dm['type']
            if dtype == 'text':
                now_danmu.append(TextDanmaku(**dm))
            elif dtype == 'image':
                now_danmu.append(ImageDanmaku(**dm))
            p += 1
            
        while len(now_danmu)>0 and now_danmu[0].et < tic:
            now_danmu.pop(0)

        frame = Image.new(mode='RGBA', size=(w,h))
        for dm in now_danmu:
            dm: TextDanmaku | ImageDanmaku
            x0, y0 = dm.sp
            x1, y1 = dm.ep
            x = x0-(x0-x1)*(tic-dm.st)/(dm.et-dm.st)
            y = y0-(y0-y1)*(tic-dm.st)/(dm.et-dm.st) - dm.size[1]
            x, y = int(x), int(y)
            rgb, a = dm.image
            frame.paste(rgb,(x,y),a)

        q.put(frame.tobytes())
        fid += nproc
        

