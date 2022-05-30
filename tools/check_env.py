from os import system
import os
import shutil
import zipfile


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

def check_ffmpeg(path):
    if not os.path.exists(path):
        a = input('FFmpeg 未正确安装，回车自动安装:')
        
        import requests
        print('正在下载FFmpeg (约78MB).')
        r = requests.get('https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip',stream=True)
        content = b''
        for i,chunk in enumerate(r.iter_content(1024)):
            print(f'\r已下载{i/1024:.2f}MB.',end='')
            content += chunk
        print('')
        with open('./tools/ffmpeg-release-essentials.zip','wb') as f:
            f.write(content)
        
        f = zipfile.ZipFile('./tools/ffmpeg-release-essentials.zip','r')
        for file in f.namelist():
            f.extract(file,'./tools')
        f.close()
        shutil.move('./tools/ffmpeg-5.0.1-essentials_build/bin/ffmpeg.exe','./tools/ffmpeg.exe')
        shutil.move('./tools/ffmpeg-5.0.1-essentials_build/bin/ffplay.exe','./tools/ffplay.exe')
        shutil.move('./tools/ffmpeg-5.0.1-essentials_build/bin/ffprobe.exe','./tools/ffprobe.exe')
        shutil.rmtree('./tools/ffmpeg-5.0.1-essentials_build')
        print('FFmpeg 安装完成，请重启程序.')
        exit(0)
    else:
        return True