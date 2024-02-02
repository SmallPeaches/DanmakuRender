import argparse
from datetime import datetime
from glob import glob
import optparse
import sys
import logging
import logging.handlers
import yaml
from os.path import exists, join

sys.path.append('..')
sys.path.append('.')

from DMR.utils import PipeMessage
from DMR import Config
from DMR.utils import FFprobe, isvideo, VideoInfo
from DMR.Render import Render

def main():    
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default='configs')
    parser.add_argument('--global_config',default='configs/global.yml')
    parser.add_argument('--mode', default='dmrender')
    parser.add_argument('--input_dir',type=str)
    parser.add_argument('--output_dir',type=str)
    args = parser.parse_args()

    config = Config(args.global_config, args.config)
    
    logging.getLogger().setLevel(logging.DEBUG)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO) 
    console_handler.setFormatter(logging.Formatter("[%(asctime)s][%(levelname)s]: %(message)s"))
    logging.getLogger().addHandler(console_handler)

    input_dir = args.input_dir if args.input_dir else config.global_config.get('downloader_args', {}).get('output_dir', '直播回放')
    inp = input(f"请输入视频文件夹路径 (回车使用默认路径 {input_dir}): \n")
    if inp: input_dir = inp

    print(f'即将对文件夹 {input_dir} 下的视频进行渲染')

    files = glob(input_dir+'/*')
    videos = sorted([f for f in files if isvideo(f)])
    tasks = []
    ignores = []

    render_args = config.global_config.get('render_args', {}).get(args.mode, '')
    render_kernel_args = config.global_config.get('render_kernel_args', {})
    assert render_args, f'请在 global.yml 中配置 {args.mode} 的参数'

    for _, vname in enumerate(videos):
        danmu = os.path.splitext(vname)[0] + '.ass'
        fmt = render_args.get('format', 'mp4')
        filename = os.path.splitext(os.path.basename(vname))[0] + f"（弹幕版）.{fmt}"
        if args.output_dir:
            output_dir = args.output_dir
        else:
            output_dir = os.path.dirname(vname)+'（弹幕版）'
        os.makedirs(output_dir,exist_ok=True)
        output = join(output_dir,filename)

        if exists(output) and FFprobe.get_duration(output) - FFprobe.get_duration(vname) < 30:
            ignores.append({
                'video': vname,
                'msg': f'视频 {vname} 已经存在带弹幕视频 {output}，跳过渲染.',
                })
            continue

        if not exists(danmu):
            ignores.append({
                'video': vname,
                'msg': f'视频 {vname} 不存在匹配的弹幕文件，跳过渲染.',
                })
            continue
        
        tasks.append({
            'video':vname,
            'danmaku':danmu,
            'output':output
        })

    print('以下视频将被忽略：')
    for i, item in enumerate(ignores):
        print(f"[{i}] {item['video']}: {item['msg']}")
    print('')
    print('以下视频将被渲染：')
    for i, item in enumerate(tasks):
        print(f"[{i}] {item['video']} -> {item['output']}")
    print('')

    print('如果视频被错误分类，请清理文件夹后重试')
    print('如果想选择特定的视频，请输入视频编号，例如：0 2 5')
    print('或者直接回车开始全部渲染：')
    inp = input()
    task_idx = range(len(tasks))
    if inp:
        task_idx = [int(x) for x in inp.split(' ')]

    if args.mode == 'dmrender':
        from DMR.Render.dmrender import DmRender as TargetRender
    elif args.mode == 'transcode':
        from DMR.Render.transcode import Transcoder as TargetRender
    elif args.mode == 'rawffmpeg':
        raise NotImplementedError
        from .ffmpeg import RawFFmpegRender as TargetRender
    
    for idx in task_idx:
        task = tasks[idx]
        video = VideoInfo(
            path=task['video'],
            dm_file_id=task['danmaku'],
        )
        logging.info(f'正在渲染: {video.path}')
        os.makedirs(os.path.dirname(output), exist_ok=True)

        target_render = TargetRender(debug=True, **render_args)
        status, info = target_render.render_one(video=video, output=output)

        if status:
            logging.info(f'渲染完成: {video.path} -> {output}')
        else:
            logging.error(f'渲染失败: {video.path} -> {output}, {info}')

if __name__ == '__main__':
    try:
        main()
        input('渲染完成.')
    except Exception as e:
        logging.exception(e)
        input(f'渲染错误, {e}')