import subprocess
import json
import warnings
import re

from .toolsmgr import ToolsList

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
            ],
            timeout=15,
        )
        out = out.decode('utf8')
        res = json.loads(out)
        return res

    @classmethod
    def get_livestream_info(cls,url,header=None) -> dict:
        res = cls.run_ffprobe_livestream(url,header)
        return res['streams'][0]
        
    @classmethod
    def get_resolution(cls, url:str, header=None) -> tuple:
        if url.startswith('http'):
            res = cls.run_ffprobe_livestream(url, header)
        else:
            res = cls.run_ffprobe(url)
        try:
            resolution = res['streams'][0]['width'],res['streams'][0]['height']
            return resolution
        except:
            return 0,0