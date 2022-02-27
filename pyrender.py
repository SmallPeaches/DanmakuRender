import argparse
from cgitb import handler
import os
import sys
import time
import logging

from downloader.Downloader import Downloader
from downloader.Render import PythonRender
from downloader.getrealurl import split_url
from tools.utils import onair, url_available

if __name__ == '__main__':    
    parser = argparse.ArgumentParser(description='Render')
    parser.add_argument('-v','--version',action='store_true')
    parser.add_argument('-u','--url',type=str,default='')
    parser.add_argument('-o','--output',type=str,default='./save')
    parser.add_argument('-s','--split',type=int,default=0)
    parser.add_argument('-n','--name',type=str)
    parser.add_argument('--ffmpeg',type=str,default='tools/ffmpeg.exe')
    parser.add_argument('--timeout',type=int,default=20)

    parser.add_argument('--gpu',type=str,default='nvidia')
    parser.add_argument('--hwaccel',type=int,default=True)
    parser.add_argument('--vdecoder',type=str,default='dxva2')

    parser.add_argument('--vencoder',type=str)
    parser.add_argument('--vbitrate',type=str,default='15M')
    parser.add_argument('--aencoder',type=str,default='aac')
    parser.add_argument('--abitrate',type=str,default='320K')
    parser.add_argument('--fps',type=float,default=60)
    parser.add_argument('--resolution',type=str,default='1920x1080')

    parser.add_argument('--copy',action='store_true')
    parser.add_argument('--nproc',type=int,default=2)
    parser.add_argument('--dmrate',type=float,default=0.5)
    parser.add_argument('--startpixel',type=int,default=20)
    parser.add_argument('--margin',type=int,default=12)
    parser.add_argument('--font',type=str,default='msyhbd.ttc')
    parser.add_argument('--fontsize',type=int,default=30)
    parser.add_argument('--overflow_op',type=str,default='ignore',choices=['ignore','override'])
    parser.add_argument('--dmduration',type=float,default=15)
    parser.add_argument('--opacity',type=float,default=0.8)
    parser.add_argument('--resolution_fixed',type=int,default=True)

    parser.add_argument('--debug',action='store_true')
    parser.add_argument('--discardcorrupt',type=int,default=True)
    parser.add_argument('--use_wallclock_as_timestamps',action='store_true')
    parser.add_argument('--reconnect',action='store_true')
    parser.add_argument('--disable_lowbitrate_interrupt',action='store_true')
    parser.add_argument('--disable_lowspeed_interrupt',action='store_true')
    parser.add_argument('--flowtype',type=str,default='flv',choices=['flv','m3u8'])

    args = parser.parse_args()

    if args.gpu.lower() == 'nvidia':
        args.vdecoder = 'nvdec' 
        args.vencoder = 'h264_nvenc' if not args.vencoder else args.vencoder
    elif args.gpu.lower() == 'amd':
        args.vdecoder = 'dxva2' 
        args.vencoder = 'h264_amf' if not args.vencoder else args.vencoder
    elif args.gpu.lower() == 'none':
        args.vencoder = 'libx264' if not args.vencoder else args.vencoder

    if args.hwaccel:
        args.hwaccel_args = ['-hwaccel',args.vdecoder]
    else:
        args.hwaccel_args = []

    if not args.name:
        p,r = split_url(args.url)
        args.name = p+r
    
    logger = logging.getLogger('main')
    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter('[%(asctime)s][%(levelname)s]: %(message)s',datefmt='%H:%M:%S')

    os.makedirs('./logs',exist_ok=True)
    args.logname = f'./logs/{args.name}-{time.strftime("%Y%m%d-%H%M%S",time.localtime())}.log'
    filehandler = logging.FileHandler(args.logname,encoding='utf-8',mode='a')
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
    
    if args.version:
        logger.info("DanmakuRender-2 2022.2.26")
        exit(0)

    while not url_available(args.url):
        logger.error("URL不可用")
        args.url = input("请输入合法的URL: ")

    if args.ffmpeg != 'ffmpeg' and not os.path.exists(args.ffmpeg):
        logger.error("FFmpeg路径设置错误.")
        exit(0)

    if not onair(args.url):
        logger.info('直播结束,正在等待...')
        time.sleep(60)
        while not onair(args.url):
            time.sleep(60)
    
    while True:
        if args.copy or args.dmrate == 0:
            rec = Downloader(url=args.url,
                            name=args.name,
                            save=args.output,
                            ffmpeg=args.ffmpeg,
                            timeout=args.timeout)
            logger.info('正在启动录制（不包括弹幕）.')
        else:
            rec = PythonRender(url=args.url,
                            name=args.name,
                            save=args.output,
                            ffmpeg=args.ffmpeg,
                            timeout=args.timeout)            
            logger.info('正在启动录制.')


        logger.debug('DanmakuRender args:')
        logger.debug(args)

        try:
            rval = rec.start(args)
        except KeyboardInterrupt:
            rec.stop()
            logger.info('录制终止')
            exit(0)

        if onair(args.url):
            logger.error('录制异常终止, 请查询日志文件了解更多信息.')
            logger.info('正在重试...')
            time.sleep(5)
        else:
            logger.info('直播结束,正在等待...')
            time.sleep(60)
            while not onair(args.url):
                time.sleep(60)


    