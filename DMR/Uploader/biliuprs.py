import logging
import os
import queue
import re
import threading
import sys
import tempfile
import time
import subprocess

from DMR.utils import replace_keywords, ToolsList, VideoInfo


class biliuprs():

    def __init__(self, 
                 cookies:str=None, 
                 account:str=None, 
                 task_upload_lock:bool=True,
                 debug=False, 
                 biliup:str=None, 
                 **kwargs,
    ) -> None:
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

        self.task_upload_lock = task_upload_lock
        self.debug = debug

        self.base_args = [self.biliup, '-u', self.cookies]
        self.task_info = {}
        self._upload_lock = threading.Lock()
        self._upload_procs = {}
        self.logger = logging.getLogger(__name__)
        self.stoped = False

        if not self.islogin():
            self.login()

    def __del__(self):
        self.stop()

    def call_biliuprs(self, 
        video, 
        bvid:str=None,
        copyright:int=1,
        cover:str='',
        desc:str='',
        dtime:int=0,
        dynamic:str='',
        line:str=None,
        limit:int=3,
        no_reprint:int=1,
        open_elec:int=1,
        source:str='',
        tag:str='',
        tid:int=65,
        title:str='',
        extra_args:list=None,
        timeout:int=None,
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
            '--dtime', dtime,
            '--dynamic', dynamic,
            '--limit', limit,
            '--no-reprint', no_reprint,
            '--open-elec', open_elec,
            '--source', source,
            '--tag', tag,
            '--tid', tid,
            '--title', title,
        ]
        if line:
            upload_args += ['--line', line]
        if extra_args:
            upload_args += extra_args

        if isinstance(video, str):
            upload_args += [video]
        elif isinstance(video, list):
            upload_args += video

        upload_args = [str(x) for x in upload_args]
        self.logger.debug(f'biliuprs: {upload_args}')
        
        if not logfile:
            logfile = sys.stdout

        if self.debug:
            upload_proc = subprocess.Popen(upload_args, stdin=subprocess.PIPE, stdout=sys.stdout, stderr=subprocess.STDOUT, bufsize=10**8)
        else:
            upload_proc = subprocess.Popen(upload_args, stdin=subprocess.PIPE, stdout=logfile, stderr=subprocess.STDOUT, bufsize=10**8)
        
        try:
            self._upload_procs[upload_proc.pid] = upload_proc
            if timeout: 
                upload_proc.wait(timeout=timeout)
            else:
                upload_proc.wait()
        except subprocess.TimeoutExpired:
            self.logger.warning(f'视频{video}上传超时，取消此次上传.')
        finally:
            upload_proc.kill()
            self._upload_procs.pop(upload_proc.pid)
        
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

        for _ in range(5):
            self.logger.info(f'正在登录名称为 {self.account} 的账户:')
            proc = subprocess.Popen(login_args)
            proc.wait()
            if self.islogin():
                self.logger.info(f'将 {self.account} 的登录信息保存到 {self.cookies}.')
                break
        
        self.logger.error(f'{self.account} 登录失败!.')

    def upload_once(self, video, bvid=None, **config):
        with tempfile.TemporaryFile(dir='.temp') as logfile:
            self.call_biliuprs(video=video, bvid=bvid, logfile=logfile, **config)
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

    def format_config(self, config, video_info=None, replace_invalid=False):
        config = config.copy()

        if config.get('title'):
            config['title'] = replace_keywords(config['title'], video_info, replace_invalid=replace_invalid)
            if len(config['title']) > 80:
                config['title'] = config['title'][:80]
                self.logger.warning(f'视频标题超过80字符，已自动截取为: {config["title"]}.')
        if config.get('desc'):
            config['desc'] = replace_keywords(config['desc'], video_info, replace_invalid=replace_invalid)
        if config.get('dynamic'):
            config['dynamic'] = replace_keywords(config['dynamic'], video_info, replace_invalid=replace_invalid)
        if config.get('tag'):
            if isinstance(config['tag'], list):
                config['tag'] = ','.join(config['tag'])
            config['tag'] = replace_keywords(config['tag'], video_info, replace_invalid=replace_invalid)
        if config.get('source'):
            config['source'] = replace_keywords(config['source'], video_info, replace_invalid=replace_invalid)
        if config.get('cover'):
            config['cover'] = replace_keywords(config['cover'], video_info, replace_invalid=replace_invalid)
            if config['cover'].startswith('http'):
                import requests
                try:
                    resp = requests.get(config['cover'], headers={'User-Agent': 'Mozilla/5.0'}, timeout=5.0)
                    resp.raise_for_status()
                    cover_filename = f'.temp/biliuprs_cover_{int(time.time())+86400}.png'
                    with open(cover_filename, 'wb') as f:
                        f.write(resp.content)
                    config['cover'] = cover_filename

                except Exception as e:
                    self.logger.error(f'视频 {config["title"]} 封面图片下载失败: {e}, 跳过设置.')
                    config['cover'] = ''
        return config

    def upload(self, files:list[VideoInfo], **kwargs):
        if not isinstance(files, list):
            files = [files]
        config = self.format_config(kwargs, files[0])

        if self._upload_lock.locked():
            self.logger.warning('上传速度慢于录制速度，可能导致上传队列阻塞！')
        
        video_files = [f.path for f in files]
        status, bvid = False, ''

        if self.task_upload_lock:       # 使用串行上传
            with self._upload_lock:
                status, bvid = self.upload_once(video=video_files, bvid=self.task_info.get('bvid'), **config)
                if status:
                    self.task_info['bvid'] = bvid

        else:                           # 完全并行上传
            if self.task_info.get('bvid') is None:      # 说明第一个任务还未上传，需要阻塞
                self._upload_lock.acquire()
                lock_released = False
                try:
                    if self.task_info.get('bvid'):      # 说明第一个任务已经上传完成
                        self._upload_lock.release()
                        lock_released = True
                    status, bvid = self.upload_once(video=video_files, bvid=None, **config)
                    if status:
                        self.task_info['bvid'] = bvid
                finally:
                    if not lock_released:
                        self._upload_lock.release()

            else:
                status, bvid = self.upload_once(video=video_files, bvid=self.task_info.get('bvid'), **config)
                if status:
                    self.task_info['bvid'] = bvid

        return status, bvid

    def end_upload(self):
        self.task_info = {}
        self.logger.debug('realtime upload end.')

    def stop(self):
        self.stoped = True
        try:
            if self._upload_procs:
                self.logger.warninging('上传提前终止，可能需要重新上传.')
            for _, proc in self._upload_procs.items():
                proc.kill()
                out, _ = proc.communicate(timeout=2.0)
                out = out.decode('utf-8')
                self.logger.debug(out)
        except Exception as e:
            self.logger.debug(e)
