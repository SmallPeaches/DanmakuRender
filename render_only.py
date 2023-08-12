import argparse
from datetime import datetime
from glob import glob
import os
import sys
import logging
import logging.handlers
import yaml
from os.path import exists, join

sys.path.append('..')
sys.path.append('.')

from main import load_config
from DMR.utils import FFprobe
from DMR.Render import Render
from DMR.Config import Config, new_config

def isvideo(path:str) -> bool:
    ext = path.split('.')[-1].lower()
    if ext in ['mp4','flv','ts','mkv']:
        return True
    else:
        return False

def main():    
    parser = argparse.ArgumentParser()
    parser.add_argument('-c','--config',default='replay.yml')
    parser.add_argument('--default_config',default='configs/default.yml')
    parser.add_argument('--debug',action='store_true')
    parser.add_argument('--render_only',action='store_true')
    parser.add_argument('--input_dir',type=str)
    parser.add_argument('--output_dir',type=str)
    args = parser.parse_args()
    
    config = load_config(args.default_config, args.config)
    
    logging.getLogger().setLevel(logging.DEBUG)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO) 
    console_handler.setFormatter(logging.Formatter("[%(asctime)s][%(levelname)s]: %(message)s"))
    logging.getLogger().addHandler(console_handler)

    input_dir = args.input_dir if args.input_dir else config.config['downloader'].get('output_dir')
    inp = input(f"请输入视频文件夹路径 (回车使用默认路径 {input_dir}): \n")
    if inp: input_dir = inp

    print(f'即将对文件夹 {input_dir} 下的视频进行渲染')

    files = glob(input_dir+'/*')
    videos = sorted([f for f in files if isvideo(f)])
    tasks = []
    ignores = []

    for _, vname in enumerate(videos):
        danmu = os.path.splitext(vname)[0] + '.ass'
        fmt = config.render_config.get('format', 'mp4')
        filename = os.path.splitext(os.path.basename(vname))[0] + f"（带弹幕版）.{fmt}"
        if args.output_dir:
            output_dir = args.output_dir
        else:
            output_dir = os.path.dirname(vname)+'（带弹幕版）'
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

    render = Render(pipe=None, debug=True, **config.render_config)
    render.start()
    for idx in task_idx:
        render.add(**tasks[idx])
    render.wait()
    render.stop()

if __name__ == '__main__':
    try:
        main()
        input('渲染完成.')
    except Exception as e:
        logging.exception(e)
        input(f'渲染错误, {e}')