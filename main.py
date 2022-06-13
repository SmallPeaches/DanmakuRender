from tools.check_env import check_pypi
check_pypi()

import argparse
from copy import deepcopy
import multiprocessing
import os
import sys
import threading
import time
import logging

from downloader.Render import Render
from downloader.Downloader import Downloader
from downloader.getrealurl import split_url
from tools.utils import onair, url_available
from tools.check_env import check_ffmpeg

def replay_one(args,onprint=False):
    p,r = split_url(args.url)
    args.name = p+r
    
    logger = logging.getLogger('main')
    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter('[%(asctime)s][%(levelname)s]: %(message)s',datefmt='%H:%M:%S')

    os.makedirs('./logs',exist_ok=True)
    logname = f'./logs/{args.name}-{time.strftime("%Y%m%d-%H%M%S",time.localtime())}.log'
    filehandler = logging.FileHandler(logname,encoding='utf-8',mode='a')
    filehandler.setLevel(logging.DEBUG)
    filehandler.setFormatter(formatter)
    
    console = logging.StreamHandler(sys.stdout)
    if args.debug:
        console.setLevel(logging.DEBUG)
    else:
        console.setLevel(logging.INFO)
    console.setFormatter(formatter)

    logger.addHandler(filehandler)
    logger.addHandler(console)

    while not url_available(args.url):
        logger.error("URL不可用")
        exit(0)

    if not onair(args.url):
        logger.info('直播结束,正在等待...')
        time.sleep(60)
        while not onair(args.url):
            time.sleep(60)
    
    while True:
        rec = Downloader(url=args.url,
                        name=args.name,
                        ffmpeg=args.ffmpeg,
                        video_dir=args.video_dir,
                        dm_dir=args.dm_dir,
                        render_dir=args.render_dir
                        )

        logger.info(f'正在录制{args.name}.')
        logger.debug('DanmakuRender args:')
        logger.debug(args)

        try:
            rval = rec.start(args,onprint=onprint)
        except KeyboardInterrupt:
            rec.stop()
            logger.info(f'{args.name}录制终止.')
            exit(0)

        if onair(args.url):
            logger.error(f'{args.name}录制异常终止, 请查询日志文件了解更多信息.')
            logger.info('正在重试...')
            time.sleep(5)
        else:
            logger.info(f'{args.name}直播结束,正在等待...')
            time.sleep(60)
            while not onair(args.url):
                time.sleep(60)

def set_auto_render(args,autoexit=False):
    os.makedirs(args.render_dir,exist_ok=True)

    logger = logging.getLogger('render')
    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter('[%(asctime)s][%(levelname)s]: %(message)s',datefmt='%H:%M:%S')

    os.makedirs('./logs',exist_ok=True)
    logname = f'./logs/Render-{time.strftime("%Y%m%d-%H%M%S",time.localtime())}.log'
    filehandler = logging.FileHandler(logname,encoding='utf-8',mode='a')
    filehandler.setLevel(logging.DEBUG)
    filehandler.setFormatter(formatter)
    
    console = logging.StreamHandler(sys.stdout)
    if args.debug:
        console.setLevel(logging.DEBUG)
    else:
        console.setLevel(logging.INFO)
    console.setFormatter(formatter)

    logger.addHandler(filehandler)
    logger.addHandler(console)

    render = Render(args,args.ffmpeg)

    def start():
        logger.info('启动自动渲染.')
        render.auto_render('.mp4',args.video_dir,args.dm_dir,args.render_dir,autoexit=autoexit)

    monitor = threading.Thread(target=start,daemon=True)
    monitor.start()
    return render,monitor

if __name__ == '__main__':    
    parser = argparse.ArgumentParser(description='Render')
    parser.add_argument('-v','--version',action='store_true')
    parser.add_argument('-u','--url',type=str,default='')
    parser.add_argument('-s','--split',type=int,default=3600)
    parser.add_argument('--ffmpeg',type=str,default='tools/ffmpeg.exe')
    parser.add_argument('--timeout',type=int,default=20)
    parser.add_argument('--video_dir',type=str,default='./直播回放')
    parser.add_argument('--dm_dir',type=str)
    parser.add_argument('--render_dir',type=str,default='./直播回放（带弹幕）')

    parser.add_argument('--render_only',action='store_true')
    parser.add_argument('--disable_auto_render',action='store_true')
    parser.add_argument('--gpu',type=str,default='nvidia')
    parser.add_argument('--hwaccel_args',type=str)
    parser.add_argument('--vencoder',type=str)
    parser.add_argument('--vencoder_args',type=str)
    parser.add_argument('--aencoder',type=str,default='aac')
    parser.add_argument('--aencoder_args',type=str,default='-b:a,320K')
    
    parser.add_argument('--resolution',type=str,default='1920x1080')

    parser.add_argument('--dmrate',type=float,default=0.4)
    parser.add_argument('--margin',type=int,default=6)
    parser.add_argument('--font',type=str,default='Microsoft YaHei')
    parser.add_argument('--fontsize',type=int,default=36)
    parser.add_argument('--overflow_op',type=str,default='override',choices=['ignore','override'])
    parser.add_argument('--dmduration',type=float,default=16)
    parser.add_argument('--opacity',type=float,default=0.8)
    parser.add_argument('--resolution_fixed',type=int,default=True)

    parser.add_argument('--debug',action='store_true')
    parser.add_argument('--ffmpeg_stream_args',type=str,default='-fflags,+discardcorrupt,-reconnect,1,-rw_timeout,10000000')
    parser.add_argument('--disable_danmaku_reconnect',action='store_true')
    parser.add_argument('--disable_lowspeed_interrupt',action='store_true')
    parser.add_argument('--flowtype',type=str,default='flv',choices=['flv','m3u8'])

    args = parser.parse_args()

    if args.version:
        print('DanmakuRender-3 2022.5.29.')
        exit(0)
    
    check_ffmpeg(args)

    if (not args.vencoder) and (not args.hwaccel_args):
        if args.gpu.lower() == 'nvidia':
            args.hwaccel_args = '-hwaccel,cuda,-noautorotate'
            args.vencoder = 'h264_nvenc'
            args.vencoder_args = '-cq,27'
        elif args.gpu.lower() == 'amd':
            args.vencoder = 'h264_amf'
            args.vencoder_args = '-cq,27'
        elif args.gpu.lower() == 'none':
            args.vencoder = 'libx264'
            args.vencoder_args = '-crf,25'
    
    if args.dm_dir is None:
        args.dm_dir = args.video_dir
    
    if args.render_only:
        _,monitor = set_auto_render(args,autoexit=True)
        monitor.join()
        exit(0)

    os.makedirs(args.video_dir,exist_ok=True)
    os.makedirs(args.dm_dir,exist_ok=True)

    urls = args.url.split(',')
    procs = []
    render = None
    if not args.disable_auto_render:
        render,_ = set_auto_render(args)
    
    for url in urls:
        args_copy = deepcopy(args)
        args_copy.url = url
        if len(urls) == 1:
            proc = multiprocessing.Process(target=replay_one,args=(args_copy,True),daemon=True)
        else:
            proc = multiprocessing.Process(target=replay_one,args=(args_copy,False),daemon=True)
        proc.start()
        procs.append(proc)
    
    try:
        for proc in procs:
            proc.join()
    except KeyboardInterrupt:
        for proc in procs:
            proc.kill()
        if render:
            render.stop()
            
    


    
