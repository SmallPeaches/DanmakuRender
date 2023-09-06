from datetime import datetime
import json
import re
import platform
import warnings
from os import system
import os
import shutil
import sys
import zipfile
import subprocess

from tools import ToolsList

__all__ = ('check_pypi','check_ffmpeg','check_biliup','check_update')

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
        import stream_gears
        import google.protobuf 
        import websocket
        import brotli
        return True
    except ImportError:
        input('Python 包未正确安装，回车自动安装:')
        subprocess.Popen([sys.executable, '-m', 'pip', 'install', '-r', 'requirements.txt', '-i', 'https://pypi.tuna.tsinghua.edu.cn/simple']).wait()
        print('Python 包安装完成.')
        return 

def check_ffmpeg():
    if os.path.exists('tools/ffmpeg.exe') and os.path.exists('tools/ffprobe.exe'):
        ToolsList.set('ffmpeg', 'tools/ffmpeg.exe')
        ToolsList.set('ffprobe', 'tools/ffprobe.exe')
        return True
    
    try:
        proc = subprocess.Popen(['ffmpeg','-version'],stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        out = proc.stdout.readlines()[0].decode('utf-8')
        if 'ffmpeg version' in out:
            ToolsList.set('ffmpeg', 'ffmpeg')
        proc = subprocess.Popen(['ffprobe','-version'],stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        out = proc.stdout.readlines()[0].decode('utf-8')
        if 'ffprobe version' in out:
            ToolsList.set('ffprobe', 'ffprobe')
        return True
    except:
        pass
    
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

        # 检测 ffmpeg-release-essentials 完整性
        try:
            f = zipfile.ZipFile('./tools/ffmpeg-release-essentials.zip','r')
        except Exception as e:
            print("FFmpeg 安装过程出错，请检查网络连接.")
            exit(0)

        for file in f.namelist():
            f.extract(file,'./tools')
        f.close()
        ffmpeg_dir_list = [f for f in os.listdir('./tools') if 'essentials_build' in f]
        ffmpeg_version = sorted(ffmpeg_dir_list)[-1]
        shutil.move(f'./tools/{ffmpeg_version}/bin/ffmpeg.exe','./tools/ffmpeg.exe')
        shutil.move(f'./tools/{ffmpeg_version}/bin/ffplay.exe','./tools/ffplay.exe')
        shutil.move(f'./tools/{ffmpeg_version}/bin/ffprobe.exe','./tools/ffprobe.exe')

        # 清理下载文件
        shutil.rmtree(f'./tools/{ffmpeg_version}')
        os.remove("./tools/ffmpeg-release-essentials.zip")
        print('FFmpeg 安装完成.')
        ToolsList.set('ffmpeg', 'tools/ffmpeg.exe')
        ToolsList.set('ffprobe', 'tools/ffprobe.exe')
        return True
    else:
        print("FFmpeg 未正确安装，请参考安装文档.")
        exit(0)

def check_biliup():
    if sys.platform == 'win32':
        if not os.access("./tools/biliup.exe", os.F_OK):
            input("Biliup未正确安装, 回车自动安装:")

            import requests
            r = requests.get('https://github.com/biliup/biliup-rs/releases/download/v0.1.19/biliupR-v0.1.19-x86_64-windows.zip', stream=True)

            # 下载
            content = b''
            for i, chunk in enumerate(r.iter_content(1024*64)):
                print(f'\r已下载{i/16:.1f}MB.', end='')
                content += chunk
            print('')

            # 写入文件
            with open('./tools/biliupR-v0.1.15-x86_64-windows.zip', 'wb') as f:
                f.write(content)
            
            # 检测 biliupR-v0.1.15-x86_64-windows.zip 完整性
            try:
                f = zipfile.ZipFile('./tools/biliupR-v0.1.15-x86_64-windows.zip', 'r')
            except Exception as e:
                print("Biliup 安装过程出错，请检查网络连接.")
                exit(0)

            # 解压
            for file in f.namelist():
                f.extract(file, './tools')
            f.close()

            # 文件归位
            shutil.move(f'./tools/biliupR-v0.1.15-x86_64-windows/biliup.exe', './tools/biliup.exe')

            # 删除下载文件
            shutil.rmtree(f'./tools/biliupR-v0.1.15-x86_64-windows')
            os.remove("./tools/biliupR-v0.1.15-x86_64-windows.zip")

            print("Biliup 安装完成.")
        ToolsList.set('biliup', "tools/biliup.exe")
        return True
    
    elif sys.platform == 'linux':
        if not os.path.exists("tools/biliup"):
            print("biliup未正确安装，请参考教程安装biliup！")
            exit(0)
        ToolsList.set('biliup', "tools/biliup")
        return True

    return 

def check_update(version):
    try:
        import requests
        resp = requests.get('https://api.github.com/repos/SmallPeaches/DanmakuRender/releases/latest', timeout=5).json()
        lastest_version = resp["tag_name"]
        if compare_version(lastest_version, version) > 0:
            print('存在可用更新：')
            print(f"版本：{lastest_version}")
            print(f"发行时间：{resp['published_at']}")
            print(f"发行说明：{resp.get('name')}")
            print(f"{resp.get('body','')}\n")
            print("如果需要更新可以直接运行 update.py 或者前往 https://github.com/SmallPeaches/DanmakuRender 更新.")
    except Exception as e:
        print(f'检查更新失败, {e}')