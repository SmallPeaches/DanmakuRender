import logging
import os
import queue
import re
import threading
import sys
import tempfile
import time
import subprocess

from DMR.utils import replace_keywords, ToolsList

class biliuprs():
    def __init__(self, cookies:str=None, account:str=None, debug=False, biliup:str=None, **kwargs) -> None:
        self.biliup = biliup if biliup else ToolsList.get('biliup')
        if not (cookies or account):
            raise ValueError('cookies or account must be set.')
        if cookies is None:
            self.account = account
            self.cookies = f'.login_info/{account}.json'
        else:
            self.account = os.path.basename(cookies).split('.')[0]
            self.cookies = cookies
        os.makedirs(os.path.dirname(self.cookies), exist_ok=True)
        self.debug = debug
        self.base_args = [self.biliup, '-u', self.cookies]
        self.task_info = {}
        self._upload_lock = threading.Lock()
        self.logger = logging.getLogger(__name__)

        if not self.islogin():
            self.login()

    def call_biliuprs(self, 
        video, 
        bvid:str=None,
        copyright:int=1,
        cover:str='',
        desc:str='',
        dolby:int=0,
        dtime:int=0,
        dynamic:str='',
        interactive:int=0,
        line:str='kodo',
        limit:int=3,
        no_reprint:int=1,
        open_elec:int=1,
        source:str='',
        tag:str='',
        tid:int=65,
        title:str='',
        logfile=None,
        **kwargs
    ):
        if bvid:
            upload_args = self.base_args + ['append', '--vid', bvid]
        else:
            upload_args = self.base_args + ['upload']

        dtime = dtime + int(time.time()) if dtime else 0
        upload_args += [
            '--copyright', copyright,
            '--cover', cover,
            '--desc', desc,
            '--dolby', dolby,
            '--dtime', dtime,
            '--dynamic', dynamic,
            '--interactive', interactive,
            '--line', line,
            '--limit', limit,
            '--no-reprint', no_reprint,
            '--open-elec', open_elec,
            '--source', source,
            '--tag', tag,
            '--tid', tid,
            '--title', title,
        ]
        if isinstance(video, str):
            upload_args += [video]
        elif isinstance(video, list):
            upload_args += video

        upload_args = [str(x) for x in upload_args]
        self.logger.debug(f'biliuprs: {upload_args}')
        
        if not logfile:
            logfile = sys.stdout

        if self.debug:
            self.upload_proc = subprocess.Popen(upload_args, stdin=subprocess.PIPE, stdout=sys.stdout, stderr=subprocess.STDOUT, bufsize=10**8)
        else:
            self.upload_proc = subprocess.Popen(upload_args, stdin=subprocess.PIPE, stdout=logfile, stderr=subprocess.STDOUT, bufsize=10**8)
        
        self.upload_proc.wait()
        return logfile
    
    def islogin(self):
        renew_args = self.base_args + ['renew']
        proc = subprocess.Popen(renew_args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=10**8)
        out = proc.stdout.read()
        out = out.decode('utf-8')

        if 'error' in out.lower():
            return False
        else:
            return True

    def login(self):
        login_args = self.base_args + ['login']

        while not self.islogin():
            print(f'正在登录名称为 {self.account} 的账户:')
            proc = subprocess.Popen(login_args)
            proc.wait()
        
        print(f'将 {self.account} 的登录信息保存到 {self.cookies}.')

    def upload_once(self, video, bvid=None, **config):
        with tempfile.TemporaryFile() as logfile:
            self.upload_proc = self.call_biliuprs(video=video, bvid=bvid, logfile=logfile, **config)
            if self.debug:
                return True, ''
        
            out_bvid = None
            log = ''
            logfile.seek(0)
            for line in logfile.readlines():
                line = line.decode('utf-8', errors='ignore').strip()
                log += line+'\n'
                if '\"bvid\"' in line:
                    res = re.search(r'(BV[0-9A-Za-z]{10})', line)
                    if res:  out_bvid = res[0]
        
        if out_bvid:
            return True, out_bvid
        else:
            return False, log
        
    def upload_batch(self, video:list, video_info:list=None, config=None, **kwargs):
        video_info = video_info[0]
        config = config.copy()
        
        if config.get('title'):
            config['title'] = replace_keywords(config['title'], video_info)
        if config.get('desc'):
            config['desc'] = replace_keywords(config['desc'], video_info)
        if config.get('dynamic'):
            config['dynamic'] = replace_keywords(config['dynamic'], video_info)
        
        return self.upload_once(video, bvid=None, **config)

    def upload_one(self, video:str, video_info:str=None, config=None, **kwargs):
        config = config.copy()
        
        if config.get('title'):
            config['title'] = replace_keywords(config['title'], video_info)
        if config.get('desc'):
            config['desc'] = replace_keywords(config['desc'], video_info)
        if config.get('dynamic'):
            config['dynamic'] = replace_keywords(config['dynamic'], video_info)
        
        if self._upload_lock.locked():
            self.logger.warn('实时上传速度慢于录制速度，可能导致上传队列阻塞！')
        
        with self._upload_lock:
            status, info = self.upload_once(video=video, bvid=self.task_info.get('bvid'), **config)
            if status:
                self.task_info['bvid'] = info
            
        return status, info
    
    def upload(self, files:list, upload_group=None, **kwargs):
        config = kwargs.copy()
        
        if config.get('title'):
            config['title'] = replace_keywords(config['title'], files[0])
        if config.get('desc'):
            config['desc'] = replace_keywords(config['desc'], files[0])
        if config.get('dynamic'):
            config['dynamic'] = replace_keywords(config['dynamic'], files[0])
        
        if self._upload_lock.locked():
            self.logger.warn('上传速度慢于录制速度，可能导致上传队列阻塞！')
        
        with self._upload_lock:
            status, bvid = True, 'BV0000000000'
            # status, bvid = self.upload_once(video=files, bvid=self.task_info.get('bvid'), **config)
            if status:
                self.task_info['bvid'] = bvid
            
        return status, bvid
        
    def end_upload(self):
        self.task_info = {}
        self.logger.debug('realtime upload end.')

    def stop(self):
        try:
            if hasattr(self, 'upload_proc') and self.upload_proc.poll() is None:
                self.logger.warn('上传提前终止，可能需要重新上传.')
            self.upload_proc.kill()
            out, _ = self.upload_proc.communicate(timeout=2.0)
            out = out.decode('utf-8')
            self.logger.debug(out)
        except Exception as e:
            self.logger.debug(e)

        

