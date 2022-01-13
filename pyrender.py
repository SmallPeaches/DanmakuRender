import argparse
import os
import time
from tools.utils import *
from downloader.Render import PythonRender

if __name__ == '__main__':    
    parser = argparse.ArgumentParser(description='Render')
    parser.add_argument('-v','--version',action='store_true')
    parser.add_argument('-u','--url',type=str,default='')
    parser.add_argument('-o','--output',type=str,default='./save')
    parser.add_argument('-s','--split',type=int,default=0)
    parser.add_argument('-n','--name',type=str,default='replay')
    parser.add_argument('--ffmpeg',type=str,default='tools/ffmpeg.exe')
    parser.add_argument('--timeout',type=int,default=20)

    parser.add_argument('--gpu',type=str,default='nvidia')
    parser.add_argument('--hwaccel',type=str)

    parser.add_argument('--vencoder',type=str)
    parser.add_argument('--vbitrate',type=str,default='15M')
    parser.add_argument('--aencoder',type=str,default='aac')
    parser.add_argument('--abitrate',type=str,default='320K')

    parser.add_argument('--nproc',type=int,default=2)
    parser.add_argument('--dmrate',type=float,default=0.5)
    parser.add_argument('--startpixel',type=int,default=20)
    parser.add_argument('--margin',type=int,default=12)
    parser.add_argument('--font',type=str,default='msyhbd.ttc')
    parser.add_argument('--fontsize',type=int,default=30)
    parser.add_argument('--overflow_op',type=str,default='ignore',choices=['ignore','override'])
    parser.add_argument('--dmduration',type=str,default='+15')
    parser.add_argument('--opacity',type=float,default=0.8)

    parser.add_argument('--debug',action='store_true')

    args = parser.parse_args()

    if args.gpu.lower() == 'nvidia':
        args.hwaccel = 'nvdec' if not args.hwaccel else args.hwaccel
        args.vencoder = 'h264_nvenc' if not args.vencoder else args.vencoder
    elif args.gpu.lower() == 'amd':
        args.hwaccel = 'dxva2' if not args.hwaccel else args.hwaccel
        args.vencoder = 'h264_amf' if not args.vencoder else args.vencoder
    else:
        args.vencoder = 'libx264' if not args.vencoder else args.vencoder

    if args.hwaccel:
        args.hwaccel_args = ['-hwaccel',args.hwaccel]
    else:
        args.hwaccel_args = []

    if args.version:
        print("DanmakuRender-2 2022.1.13")
        exit(0)

    while not url_available(args.url):
        print("URL不可用")
        args.url = input("请输入合法的URL: ")

    if args.ffmpeg != 'ffmpeg' and not os.path.exists(args.ffmpeg):
        print("FFmpeg路径设置错误.")
        exit(0)

    if not onair(args.url):
        print('直播结束,正在等待...')
        time.sleep(60)
        while not onair(args.url):
            time.sleep(60)
    
    while True:
        rec = PythonRender(url=args.url,
                           name=args.name,
                           save=args.output,
                           ffmpeg=args.ffmpeg,
                           timeout=args.timeout)

        rval = rec.start(args)

        if onair(args.url):
            print('\n录制异常终止:')
            if isinstance(rval,list):
                for l in rval:
                    print(l,end='')
            else:
                print(rval)
            print('正在重试...')
            time.sleep(5)
        else:
            print('直播结束,正在等待...')
            time.sleep(60)


    