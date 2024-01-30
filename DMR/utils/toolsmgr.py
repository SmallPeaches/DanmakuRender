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


__all__ = ('check_ffmpeg','check_biliup','ToolsList')

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
            os.makedirs('.temp', exist_ok=True)
            with open('.temp/biliuprs.zip', 'wb') as f:
                f.write(content)
            
            # 检测文件完整性
            try:
                f = zipfile.ZipFile('.temp/biliuprs.zip', 'r')
            except Exception as e:
                print("Biliup 安装过程出错，请检查网络连接或参考教程自行下载！")
                exit(0)

            # 解压
            for file in f.namelist():
                f.extract(file, '.temp')
            f.close()

            file_dir = [f for f in os.listdir('.temp') if 'biliupR-' in f]
            file_dir = sorted(file_dir)[-1]

            # 文件归位
            shutil.move(f'.temp/{file_dir}/biliup.exe', './tools/biliup.exe')

            # 删除下载文件
            shutil.rmtree(f'.temp/{file_dir}')
            os.remove('.temp/biliuprs.zip')

            print("Biliup 安装完成.")
        ToolsList.set('biliup', "tools/biliup.exe")
        return True
    
    else:
        if not os.path.exists("tools/biliup"):
            print("biliup未正确安装，请参考教程安装biliup！")
            exit(0)
        ToolsList.set('biliup', "tools/biliup")
        return True
    return 

class ToolsList(dict):
    _tools = {}

    @classmethod
    def get(cls, name:str, auto_install=True):
        if not cls._tools.get(name) and auto_install:
            if name == 'biliup':
                check_biliup()
            elif name == 'ffmpeg' or name == 'ffprobe':
                check_ffmpeg()

        return cls._tools.get(name)
    
    @classmethod
    def set(cls, name:str, path:str):
        cls._tools[name] = path