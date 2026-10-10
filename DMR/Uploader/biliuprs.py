import logging
import os
import queue
import re
import threading
import sys
import tempfile
import time
import subprocess

from DMR.utils import replace_keywords, ToolsList, VideoInfo, run_and_capture_output


class biliuprs():

    def __init__(self, 
                 cookies:str=None, 
                 account:str=None, 
                 task_upload_lock:bool=True,
                 debug=False, 
                 biliup:str=None, 
                 resume_bvid:str=None,
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
        # 状态持久化（P1）：bvid 决定后续分段是"追加到既有稿件"还是"新建稿件"。
        # 进程重启后由状态库注入，使同一 upload_group 仍进同一稿件。
        self.task_info = {'bvid': resume_bvid} if resume_bvid else {}
        self._upload_lock = threading.Lock()
        self._upload_procs = {}
        self.logger = logging.getLogger(__name__)
        self.stoped = False

        if resume_bvid:
            self.logger.info(f'已恢复既有稿件 {resume_bvid}，新分段将追加到该稿件。')

        if not self.islogin():
            self.login()

    def get_remote_bvid(self) -> str | None:
        """当前稿件标识，供上层回写到状态库。"""
        return self.task_info.get('bvid')

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

        # stdout 是文件对象（或 sys.stdout），不是管道：Python 不会为其分配
        # bufsize 指定的缓冲，原来的 bufsize=10**8 纯属无效参数（现已移除）。
        if self.debug:
            upload_proc = subprocess.Popen(upload_args, stdin=subprocess.PIPE, stdout=sys.stdout, stderr=subprocess.STDOUT)
        else:
            upload_proc = subprocess.Popen(upload_args, stdin=subprocess.PIPE, stdout=logfile, stderr=subprocess.STDOUT)
        
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
        
        return logfile, upload_args
    
    def islogin(self):
        renew_args = self.base_args + ['renew']
        # 临时文件收输出：PIPE + read() 在输出超过管道缓冲时会死锁，
        # 而 bufsize=10**8 解决不了死锁、只白白预留上百 MB 内存。
        out, _ = run_and_capture_output(renew_args, timeout=60)
        if 'error' in out.lower():
            return False
        else:
            return True

    def login(self):
        login_args = self.base_args + ['login']

        for _ in range(5):
            self.logger.info(f'正在登录名称为 {self.account} 的账户:')
            proc = subprocess.Popen(login_args)
            proc.wait(timeout=120)
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
                status, bvid = self._upload_once_with_fallback(video_files, **config)
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
                status, bvid = self._upload_once_with_fallback(video_files, **config)
                if status:
                    self.task_info['bvid'] = bvid

        return status, bvid

    def _upload_once_with_fallback(self, video_files, **config):
        """按既有 bvid 追加；失败时清空 bvid 再试一次，以应对"稿件已被删除"。

        为什么需要：状态库里的 bvid 可能对应一个已被用户删除的稿件。此时
        ``biliup append --vid <bvid>`` 会持续失败，而 :meth:`upload` 的重试逻辑会
        重复同一次注定失败的调用。这里退化为新建稿件，使上传能够继续。
        """
        bvid = self.task_info.get('bvid')
        status, result = self.upload_once(video=video_files, bvid=bvid, **config)
        if status or not bvid:
            return status, result

        self.logger.warning(
            f'追加到既有稿件 {bvid} 失败，可能是稿件已被删除，改以新建稿件重试。'
        )
        self.task_info.pop('bvid', None)
        return self.upload_once(video=video_files, bvid=None, **config)

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
