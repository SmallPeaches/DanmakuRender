from os import system
import os
import shutil
import sys
import zipfile
import subprocess


def check_pypi():
    try:
        import requests
        import aiohttp
        import PIL
        import execjs
        return True
    except ImportError:
        a = input('Python 包未正确安装，回车自动安装:')
        system("pip install -r requirements.txt")
        print('Python 包安装完成，请重启程序.')
        exit(0)

def check_ffmpeg(args):
    try:
        proc = subprocess.Popen(['ffmpeg','-version'],stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        out = proc.stdout.readlines()[0].decode('utf-8')
    except:
        out = ''
    if 'ffmpeg version' in out:
        args.ffmpeg = 'ffmpeg'
        return True
    elif os.path.exists(args.ffmpeg):
        return True
    else:
        if sys.platform == 'win32':
            input('FFmpeg 未正确安装，回车自动安装:')
            
            import requests
            print('正在下载FFmpeg (约78MB).')
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
            print('FFmpeg 安装完成，请重启程序.')
            exit(0)
        else:
            print("FFmpeg 未正确安装.")