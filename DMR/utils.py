import subprocess
import json
import warnings
import re

from .LiveAPI import GetStreamerInfo, split_url, AVAILABLE_DANMU, AVAILABLE_LIVE

def replace_keywords(string:str, kw_info:dict=None):
    if not kw_info:
        return string
    for k, v in kw_info.items():
        if k == 'time':
            for kw in ['year','month','day','hour','minute','second']:
                if kw != 'year':
                    string = string.replace('{'+f'{kw}'.upper()+'}', str(getattr(v,kw)).zfill(2))
                else:
                    string = string.replace('{'+f'{kw}'.upper()+'}', str(getattr(v,kw)))
        elif k == 'title':
            string = string.replace('{'+f'{k}'.upper()+'}', re.sub(r"[\\/:*?\"<>|]", "", str(v)))
        string = string.replace('{'+f'{k}'.upper()+'}', str(v))
    return string

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
    def run_ffprobe_livestream(cls, url, header=None):
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

class Config():
    def __init__(self, default_conf:dict, replay_conf:dict) -> None:
        self.default_conf = default_conf.copy()
        self.replay_conf = replay_conf.copy()

        self.default_conf['downloader']['ffmpeg'] = self.default_conf.get('ffmpeg')
        self.default_conf['render']['ffmpeg'] = self.default_conf.get('ffmpeg')
        FFprobe.setffprobe(self.default_conf.get('ffprobe'))
        
        self.config = default_conf.copy()
        self.config['upload'] = {}

        # check downloader output name validation
        self.downloader_output_name = self.default_conf['downloader']['output_name']
        self.downloader_output_name_check = re.sub(r"[\\/:*?\"<>|]", "", str(self.downloader_output_name))
        if self.downloader_output_name_check != self.downloader_output_name:
            raise ValueError(f'自定义录制文件名称不合法: {self.downloader_output_name}')

        if self.replay_conf.get('render'):
            self.config['render'].update(self.replay_conf.get('render'))

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
            self.config['upload'][upd]['target'] = upd

        # check bilibili config
        for upd, upd_conf in self.config['upload'].items():
            if upd_conf['target'] == 'bilibili':
                if upd_conf['title'] is None:
                    raise ValueError('上传参数 title 不能为空，请检查 default.yml 中 uploader 的 title 参数.')
                elif upd_conf['desc'] is None:
                    raise ValueError('上传参数 desc 不能为空，请检查 default.yml 中 uploader 的 desc 参数.')
                elif upd_conf['tid'] is None:
                    raise ValueError('上传参数 tid 不能为空，请检查 default.yml 中 uploader 的 tid 参数.')
                elif upd_conf['tag'] is None:
                    raise ValueError('上传参数 tag 不能为空，请检查 default.yml 中 uploader 的 tag 参数.')
                elif upd_conf['dtime'] is None:
                    raise ValueError('上传参数 dtime 不能为空，请检查 default.yml 中 uploader 的 dtime 参数.')
                elif int(upd_conf['dtime']) < 0 or int(upd_conf['dtime']) > 0 and int(upd_conf['dtime']) < 14400 or int(upd_conf['dtime']) > 1296000:
                    raise ValueError('上传参数 dtime 的值必须 ≥14400(4小时) 且 ≤1296000(15天), 请重新设置 dtime 参数.')

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