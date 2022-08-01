from os import makedirs
from tools.check_env import *
check_pypi()

import argparse
import requests
from datetime import datetime, timedelta
from downloader.Render import Render
from downloader.DanmakuWriter import DanmakuWriter
from tools.utils import *

BANNED_WORDS = ['\{','赞']

def get_danmu_from_remote(args):
    _,dm_fname = os.path.split(args.video)
    dm_fname = dm_fname.replace('.mp4','.ass')
    w,h = [int(x) for x in args.resolution.split('x')]

    video_info = get_video_info(args.ffmpeg,args.video)
    if not (video_info.get('width') or video_info.get('height')):
        print(f'无法获取视频大小，使用默认值{args.resolution}.')
        video_info['width'],video_info['height'] = [int(i) for i in args.resolution.split('x')]
    if not video_info.get('duration'):
        print(f'无法获取视频长度，使用默认值{args.video_duration}.')
        video_info['duration'] = args.video_duration

    if args.resolution_fixed:
        args.dmduration_fixed = video_info['width']/1920*(args.dmduration)
        args.fontsize_fixed = int(video_info['height']/1080*(args.fontsize))
        args.margin_fixed = int(video_info['height']/1080*(args.margin))
    else:
        args.dmduration_fixed = float(args.dmduration)
        args.fontsize_fixed = int(args.fontsize)
        args.margin_fixed = int(args.margin)
    
    dmw = DanmakuWriter(save_name=dm_fname,
                        save_dir=args.dm_dir,
                        split=0,
                        width=w,
                        height=h,
                        margin=args.margin_fixed,
                        dmrate=args.dmrate,
                        font=args.font,
                        fontsize=args.fontsize_fixed,
                        overflow_op=args.overflow_op,
                        dmduration=args.dmduration_fixed,
                        opacity=args.opacity)
    
    start_time = datetime(*[int(x) for x in re.split('[\s:,.：，]',args.start_time)])
    end_time = start_time + timedelta(seconds=video_info['duration'])
    start_time_str = start_time.strftime('%Y.%m.%d.%H.%M.%S')
    end_time_str = end_time.strftime('%Y.%m.%d.%H.%M.%S')

    url_parms = f'api/dmlist?s={args.name}&t={start_time_str},{end_time_str}'
    remote_url = args.remote_addr + url_parms

    try:
        resp = requests.get(remote_url)
        danmu = json.loads(resp.text)['danmu']
    except:
        print('服务器错误！')
        exit(0)

    dmcnt = 0
    for dm in danmu:
        if danmu_available(dm):
            dm['time'] = dm['time'] - start_time.timestamp()
            dmw.add(dm=dm)
            dmcnt += 1
    print(f'{dmcnt}条弹幕被加载.')
    dmw.stop()

    return os.path.join(args.dm_dir,dm_fname)

def start_render(args,dmfile):
    render = Render(args)
    if not args.output:
        args.output = args.video.replace('.mp4','(带弹幕版).mp4')
    proc = render.render(args.video,dmfile,args.output,to_stdout=True)
    return proc


if __name__ == '__main__':    
    parser = argparse.ArgumentParser(description='Render_online')
    parser.add_argument('info',nargs='+')
    parser.add_argument('-v','--video',type=str)
    parser.add_argument('-o','--output',type=str)
    parser.add_argument('--dm_dir',type=str,default='./danmu_tmp')
    parser.add_argument('-V','--version',action='store_true')
    parser.add_argument('--ffmpeg',type=str,default='tools/ffmpeg.exe')

    parser.add_argument('--remote_addr',type=str,default='http://106.55.39.79:5000/')
    parser.add_argument('-n','--name',type=str)
    parser.add_argument('-t','--start_time',type=str)
    parser.add_argument('--video_duration',type=float,default=7200)

    parser.add_argument('--gpu',type=str,default='nvidia')
    parser.add_argument('--hwaccel_args',type=str)
    parser.add_argument('--vencoder',type=str)
    parser.add_argument('--vencoder_args',type=str)
    parser.add_argument('--aencoder',type=str,default='aac')
    parser.add_argument('--aencoder_args',type=str,default='-b:a,320K')
    
    parser.add_argument('--resolution',type=str,default='1920x1080')
    parser.add_argument('--fps',type=float,default=60)

    parser.add_argument('--dmrate',type=float,default=0.4)
    parser.add_argument('--margin',type=int,default=6)
    parser.add_argument('--font',type=str,default='Microsoft YaHei')
    parser.add_argument('--fontsize',type=int,default=36)
    parser.add_argument('--overflow_op',type=str,default='override',choices=['ignore','override'])
    parser.add_argument('--dmduration',type=float,default=16)
    parser.add_argument('--opacity',type=float,default=0.8)
    parser.add_argument('--resolution_fixed',type=int,default=True)

    args = parser.parse_args()

    if len(args.info)>0:
        args.video = args.info[0]
    if len(args.info)>1:
        args.name = args.info[1]
    if len(args.info)>2:
        args.start_time = args.info[2]
    
    print(args)
    if not(args.video and args.name and args.start_time):
        print('参数错误.')
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

    makedirs(args.dm_dir,exist_ok=True)
    dmfile = get_danmu_from_remote(args)
    proc = start_render(args,dmfile)
    proc.wait()
    print(f'带弹幕视频{args.output}渲染完成')
