import platform
import warnings
import sys
import subprocess

__all__ = ('check_pypi', 'check_update')

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
            print('')
    except Exception as e:
        print(f'检查更新失败, {e}')