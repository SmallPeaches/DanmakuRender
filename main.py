import argparse
import os
import time

from downloader import downloader
from tools.utils import *

replay = None
def replay_once(args):
    global replay
    replay = downloader(args.url,args.name,args.output,args.ffmpeg)
    replay.download(args.split,rectype=args.record)

if __name__ == '__main__':
    config_path = 'config.json'
    config = read_json(config_path)
    
    parser = argparse.ArgumentParser(description='Replay')
    parser.add_argument('-u','--url',type=str,default=config['url'],help='live url')
    parser.add_argument('-n','--name',type=str,default=config['taskname'],help='task name')
    parser.add_argument('-o','--output',type=str,default=config['output'],help='output directory')
    parser.add_argument('-s','--split',type=int,default=config['split'],help='split time (seconds)')
    parser.add_argument('--ffmpeg',type=str,default=config['ffmpeg'],help='ffmpeg.exe path')
    parser.add_argument('--record',type=str,default=config['recordtype'],choices=['all','danmu','video'])
    parser.add_argument('-m','--monitor',action='store_true')

    args = parser.parse_args()
    if args.ffmpeg != 'ffmpeg' and not os.path.exists(args.ffmpeg):
        print("FFmpeg路径设置错误.")
        exit(0)

    if (not args.url) or (not url_available(args.url)):
        url = input('请输入URL: ')
        while not url_available(url):
            print('无法解析URL：'+url)
            url = input('请输入URL: ')
        args.url = url
        
    if not args.monitor:
        print('Start.')
        rval = replay_once(args)
        print('录制异常终止.')
        print(rval)
    else:
        while True:
            if onair(args.url):
                print('\rStart.')
                rval = replay_once(args)
                if rval:
                    print('录制异常终止.')
                    print(rval)
                else:
                    print('直播结束.')
                time.sleep(5)
            else:
                print('\r未开播，正在等待...',end='')
                time.sleep(30)


    