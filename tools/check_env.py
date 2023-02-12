from datetime import datetime
import json
import platform
import warnings
import requests
from os import system
import os
import shutil
import sys
import zipfile
import subprocess

def compare_version(ver1, ver2):
    list1 = str(ver1).split(".")
    list2 = str(ver2).split(".")
    for i in range(len(list1)) if len(list1) < len(list2) else range(len(list2)):
        if int(list1[i]) == int(list2[i]):
            pass
        elif int(list1[i]) < int(list2[i]):
            return -1
        else:
            return 1
    if len(list1) == len(list2):
        return 0
    elif len(list1) < len(list2):
        return -1
    else:
        return 1

def check_pypi():
    if compare_version(platform.python_version(),'3.10.0') >= 0:
        warnings.warn('程序正运行在Python 3.10及以上版本, 此版本有可能导致斗鱼弹幕录制错误, 如果出现此情况可以切换到Python 3.9版本.')
    
    try:
        import requests
        import aiohttp
        import execjs
        import lxml
        import yaml
        return True
    except ImportError:
        input('Python 包未正确安装，回车自动安装:')
        system("python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple")
        print('Python 包安装完成.')
        return 

def check_ffmpeg():
    try:
        proc = subprocess.Popen(['ffmpeg','-version'],stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        out = proc.stdout.readlines()[0].decode('utf-8')
    except:
        out = ''
    if 'ffmpeg version' in out:
        return 'ffmpeg', 'ffprobe'
    elif os.path.exists('tools/ffmpeg.exe') and os.path.exists('tools/ffprobe.exe'):
        return 'tools/ffmpeg.exe', 'tools/ffprobe.exe'
    else:
        if sys.platform == 'win32':
            input('FFmpeg 未正确安装，回车自动安装:')
            
            import requests
            print('正在下载FFmpeg (约80MB, 若下载速度过慢可以参考教程自行下载).')
            r = requests.get('https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip',stream=True)
            content = b''
            for i,chunk in enumerate(r.iter_content(1024*64)):
                print(f'\r已下载{i/16:.1f}MB.',end='')
                content += chunk
            print('')
            with open('./tools/ffmpeg-release-essentials.zip','wb') as f:
                f.write(content)
            
            f = zipfile.ZipFile('./tools/ffmpeg-release-essentials.zip','r')
            for file in f.namelist():
                f.extract(file,'./tools')
            f.close()
            ffmpeg_dir_list = [f for f in os.listdir('./tools') if 'essentials_build' in f]
            ffmpeg_version = sorted(ffmpeg_dir_list)[-1]
            shutil.move(f'./tools/{ffmpeg_version}/bin/ffmpeg.exe','./tools/ffmpeg.exe')
            shutil.move(f'./tools/{ffmpeg_version}/bin/ffplay.exe','./tools/ffplay.exe')
            shutil.move(f'./tools/{ffmpeg_version}/bin/ffprobe.exe','./tools/ffprobe.exe')
            shutil.rmtree(f'./tools/{ffmpeg_version}')
            print('FFmpeg 安装完成.')
            return 'tools/ffmpeg.exe', 'tools/ffprobe.exe'
        else:
            print("FFmpeg 未正确安装.")
            exit(0)

def _update_from_github():
    pass

def check_update():
    if not os.path.exists('tools/VERSION.INFO'):
        resp = requests.get('https://api.github.com/repos/SmallPeaches/DanmakuRender',timeout=5).json()
        update_time = resp['pushed_at']
        info = {
            'last_update':update_time
        }
        _update_from_github()
        with open('tools/VERSION.INFO','w') as f:
            json.dump(info,f,ensure_ascii=False)
    else:
        with open('tools/VERSION.INFO','r') as f:
            info = json.load(f)
        update_time = info['last_update']
        resp = requests.get('https://api.github.com/repos/SmallPeaches/DanmakuRender',timeout=5).json()
        if update_time < resp['pushed_at']:
            _update_from_github()