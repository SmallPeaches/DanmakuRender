import subprocess
import json
import warnings
import re

from tools import ToolsList
from tools.check_env import *
from .LiveAPI import GetStreamerInfo, split_url, AVAILABLE_DANMU, AVAILABLE_LIVE

__all__ = [
    'replace_keywords',
    'replace_invalid_chars',
    'sec2hms',
    'hms2sec',
    'RGB2BGR',
    'BGR2RGB',
    'FFprobe',
]

def replace_keywords(string:str, kw_info:dict=None, replace_invalid:bool=False):
    if not kw_info:
        return string
    for k, v in kw_info.items():
        if k == 'time':
            for kw in ['year','month','day','hour','minute','second']:
                if kw != 'year':
                    string = string.replace('{'+f'{kw}'.upper()+'}', str(getattr(v,kw)).zfill(2))
                else:
                    string = string.replace('{'+f'{kw}'.upper()+'}', str(getattr(v,kw)))
        if replace_invalid:
            string = string.replace('{'+f'{k}'.upper()+'}', replace_invalid_chars(v))
        else:
            string = string.replace('{'+f'{k}'.upper()+'}', str(v))
    return string

def replace_invalid_chars(string:str) -> str:
    return re.sub(r"[\\/:*?\"<>|]", "", str(string))

def sec2hms(sec:float):
    sec = float(sec)
    t_m,t_s = divmod(sec ,60)   
    t_h,t_m = divmod(t_m,60)
    return t_h, t_m, t_s

def hms2sec(hrs:float,mins:float,secs:float):
    return float(hrs)*3600 + float(mins)*60 + float(secs)

def BGR2RGB(color):
    return color[4:6] + color[2:4] + color[0:2]

def RGB2BGR(color):
    return BGR2RGB(color)

class FFprobe():
    header = {
                'Content-Type': 'application/x-www-form-urlencoded',
                'User-Agent': 'Mozilla/5.0 (Linux; Android 5.0; SM-G900P Build/LRX21T) AppleWebKit/537.36 '
                                '(KHTML, like Gecko) Chrome/75.0.3770.100 Mobile Safari/537.36 '
            }

    @classmethod
    def ffprobe(cls) -> str:
        return ToolsList.get('ffprobe')
    
    @classmethod
    def run_ffprobe(cls,fpath):
        out = subprocess.check_output([
            cls.ffprobe(),
            '-i', fpath,
            '-print_format','json',
            '-show_format','-show_streams',
            '-v','quiet'
            ])
        out = out.decode('utf8')
        res = json.loads(out)
        return res
        
    @classmethod
    def get_duration(cls,fpath) -> float:
        try:
            res = cls.run_ffprobe(fpath)
            try:
                st = float(res['format']['start_time'])
            except:
                st = 0
            duration = float(res['format']['duration'])-st
            return duration
        except:
            return -1

    @classmethod
    def run_ffprobe_livestream(cls, url, header=None):
        if header is None:
            header = cls.header
        out = subprocess.check_output([
            cls.ffprobe(),
            '-headers', ''.join('%s: %s\r\n' % x for x in header.items()),
            '-i', url,
            '-select_streams', 'v:0', 
            '-print_format','json',
            '-show_format','-show_streams',
            '-v','quiet'
            ])
        out = out.decode('utf8')
        res = json.loads(out)
        return res

    @classmethod
    def get_livestream_info(cls,url,header=None) -> dict:
        res = cls.run_ffprobe_livestream(url,header)
        return res['streams'][0]
        
    @classmethod
    def get_resolution(cls,url,header=None) -> tuple:
        res = cls.run_ffprobe_livestream(url,header)
        try:
            resolution = res['streams'][0]['width'],res['streams'][0]['height']
            return resolution
        except:
            return 0,0