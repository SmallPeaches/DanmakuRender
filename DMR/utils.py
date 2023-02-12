import subprocess
import json
import warnings

from .LiveAPI import GetStreamerInfo, split_url, AVAILABLE_DANMU, AVAILABLE_LIVE

class FFprobe():
    ffprobe = 'ffprobe'
    header = {
                'Content-Type': 'application/x-www-form-urlencoded',
                'User-Agent': 'Mozilla/5.0 (Linux; Android 5.0; SM-G900P Build/LRX21T) AppleWebKit/537.36 '
                                '(KHTML, like Gecko) Chrome/75.0.3770.100 Mobile Safari/537.36 '
            }

    @classmethod
    def setffprobe(cls,ffprobe):
        cls.ffprobe = ffprobe
    
    @classmethod
    def run_ffprobe(cls,fpath):
        out = subprocess.check_output([
            cls.ffprobe,
            '-i', fpath,
            '-print_format','json',
            '-show_format','-show_streams',
            '-v','quiet'
            ])
        out = out.decode('utf8')
        res = json.loads(out)
        return res
        
    @classmethod
    def get_duration(cls,fpath):
        res = cls.run_ffprobe(fpath)
        try:
            duration = float(res['format']['duration'])
            return duration
        except:
            return None

    @classmethod
    def get_resolution(cls,url,header=None) -> tuple:
        if header is None:
            header = cls.header
        out = subprocess.check_output([
            cls.ffprobe,
            '-headers', ''.join('%s: %s\r\n' % x for x in header.items()),
            '-i', url,
            '-select_streams', 'v:0', 
            '-print_format','json',
            '-show_format','-show_streams',
            '-v','quiet'
            ])
        out = out.decode('utf8')
        res = json.loads(out)
        try:
            resolution = res['streams'][0]['width'],res['streams'][0]['height']
            return resolution
        except:
            return 0,0

class Config():
    def __init__(self, default_conf:dict, replay_conf:dict) -> None:
        self.default_conf = default_conf.copy()
        self.replay_conf = replay_conf.copy()

        self.default_conf['downloader']['ffmpeg'] = self.default_conf.get('ffmpeg')
        self.default_conf['render']['ffmpeg'] = self.default_conf.get('ffmpeg')
        FFprobe.setffprobe(self.default_conf.get('ffprobe'))
        
        self.config = default_conf.copy()
        self.config['upload'] = {}

        if self.replay_conf.get('replay'):
            self.config['replay'] = {}
            replay = self.replay_conf['replay']
            if isinstance(replay,list):
                for rep in replay:
                    rep_conf = self.default_conf['downloader'].copy()
                    rep_conf.update(rep)
                    plat, _ = split_url(rep['url'])
                    if plat not in AVAILABLE_LIVE:
                        raise ValueError(f'不支持的平台: {plat}.')
                    if plat not in AVAILABLE_DANMU:
                        warnings.warn(f'平台 {plat} 不支持录制弹幕，程序将只录制直播流.')
                        rep_conf['danmaku'] = False
                    name = GetStreamerInfo(rep['url'])[1]
                    self.config['replay'][name] = rep_conf
            elif isinstance(replay,dict):
                for name, rep in replay.items():
                    rep_conf = self.default_conf['downloader'].copy()
                    rep_conf.update(rep)
                    plat, _ = split_url(rep['url'])
                    if plat not in AVAILABLE_LIVE:
                        raise ValueError(f'不支持的平台: {plat}.')
                    if plat not in AVAILABLE_DANMU:
                        warnings.warn(f'平台 {plat} 不支持录制弹幕，程序将只录制直播流.')
                        rep_conf['danmaku'] = False
                    self.config['replay'][name] = rep_conf
        
        if self.replay_conf.get('upload'):
            upload = self.replay_conf['upload']
            for upd in upload.keys():
                if not upload[upd].get('target'):
                    upload[upd]['target'] = 'bilibili'
                target = upload[upd]['target']
                upload_conf = self.default_conf['uploader'][target].copy()
                upload_conf.update(upload[upd])
                self.config['upload'][upd] = upload_conf

        default_upds = set()
        for name, rep_conf in self.config['replay'].items():
            for dtype, upds in rep_conf.get('upload',{}).items():
                if isinstance(upds,str):
                    upds = upds.split(',')
                    rep_conf['upload'][dtype] = upds
                for upd in upds:
                    if self.config.get('upload') and self.config['upload'].get(upd):
                        continue
                    elif self.default_conf['uploader'].get(upd):
                        default_upds.add(upd)
                    else:
                        raise ValueError(f'不存在上传器 {upd}.')
                    
        for upd in default_upds:
            upload_conf = self.default_conf['uploader'][upd].copy()
            self.config['upload'][upd] = upload_conf

    @property
    def render_config(self) -> dict:
        return self.config.get('render')

    @property
    def uploader_config(self) -> dict:
        return self.config.get('upload')

    @property
    def replay_config(self) -> dict:
        return self.config.get('replay')

    def get_replay_config(self,name) -> dict:
        return self.replay_config.get(name)