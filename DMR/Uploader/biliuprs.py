from datetime import datetime
import logging
import os
import queue
import signal
import sys
import json
import subprocess

class biliuprs():
    def __init__(self, biliup:str, cookies:str, name:str, debug=False, **kwargs) -> None:
        self.biliup = biliup
        self.name = name
        if cookies is None:
            self.cookies = f'./.temp/{name}.json'
        else:
            self.cookies = cookies
        self.debug = debug
        self.base_args = [self.biliup, '-u', self.cookies]
        self.wait_queue = queue.Queue()
        self.group2bvid = {}

        if not self.islogin():
            self.login()

    def upload_helper(self, 
        video:str, 
        bvid:str=None,
        copyright:int=1,
        cover:str='',
        desc:str='',
        dolby:int=0,
        hires:int=0,
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
        **kwargs
    ):
        if bvid:
            upload_args = self.base_args + ['append', '--vid', bvid]
        else:
            upload_args = self.base_args + ['upload']
        upload_args += [
            '--copyright', copyright,
            '--cover', cover,
            '--desc', desc,
            '--dolby', dolby,
            '--dtime', dtime,
            '--dynamic', dynamic,
            '--interactive', interactive,
            # '--line', line,
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
        logging.debug(f'biliuprs: {upload_args}')
        
        if self.debug:
            proc = subprocess.Popen(upload_args, stdin=subprocess.PIPE, stdout=sys.stdout, stderr=subprocess.STDOUT,bufsize=10**8)
        else:
            proc = subprocess.Popen(upload_args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,bufsize=10**8)
        return proc
    
    def islogin(self):
        renew_args = self.base_args + ['renew']
        proc = subprocess.Popen(renew_args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,bufsize=10**8)
        out = proc.stdout.read()
        out = out.decode('utf-8')

        if 'error' in out.lower():
            return False
        else:
            return True

    def login(self):
        login_args = self.base_args + ['login']

        while not self.islogin():
            print(f'正在登录名称为 {self.name} 的账户:')
            proc = subprocess.Popen(login_args)
            proc.wait()
        
        print(f'将 {self.name} 的登录信息保存到 {self.cookies}.')

    def replace_keywords(self, msg:str, info):
        if not info:
            return msg
        for k, v in info.items():
            if k == 'time':
                for kw in ['year','month','day','hour','minute','second']:
                    msg = msg.replace('{'+f'{kw}'.upper()+'}', str(getattr(v,kw)))
            msg = msg.replace('{'+f'{k}'.upper()+'}', str(v))
        return msg

    def upload_one(self, video, group=None, **kwargs):
        bvid = self.group2bvid.get(group) if group else None

        if kwargs.get('title'):
            kwargs['title'] = self.replace_keywords(kwargs['title'], kwargs.get('video_info'))
        if kwargs.get('desc'):
            kwargs['desc'] = self.replace_keywords(kwargs['desc'], kwargs.get('video_info'))
        if kwargs.get('dynamic'):
            kwargs['dynamic'] = self.replace_keywords(kwargs['dynamic'], kwargs.get('video_info'))

        logging.debug(f'Uploading {video}, {bvid}, {kwargs}')
        self.upload_proc = self.upload_helper(video, bvid, **kwargs)

        if self.upload_proc.stdout is None:
            return self.upload_proc.wait()

        for line in self.upload_proc.stdout.readlines():
            line = line.decode('utf-8')
            if line.startswith('Error'):
                raise RuntimeError(f'上传错误, {line}')
            try:
                str_info = line.split(': ')[1]
                info = json.loads(str_info)
                bvid = info['data']['bvid']
            except:
                logging.debug(line)
                continue

        if bvid:
            if group: 
                self.group2bvid[group] = bvid
            return True
        else:
            return False
        
    def upload_batch(self, batch):
        video_batch = [bat['video'] for bat in batch]
        kwargs = batch[0]['kwargs']
        video_info = batch[0]['video_info']
        
        if kwargs.get('title'):
            kwargs['title'] = self.replace_keywords(kwargs['title'], video_info)
        if kwargs.get('desc'):
            kwargs['desc'] = self.replace_keywords(kwargs['desc'], video_info)
        if kwargs.get('dynamic'):
            kwargs['dynamic'] = self.replace_keywords(kwargs['dynamic'], video_info)
        
        self.upload_proc = self.upload_helper(video=video_batch, bvid=None, **kwargs)

        if self.upload_proc.stdout is None:
            return self.upload_proc.wait()

        status = False
        for line in self.upload_proc.stdout.readlines():
            line = line.decode('utf-8')
            if '上传成功' in line:
                status = True
            
        return status

    def stop(self):
        try:
            if self.upload_proc.poll() is None:
                logging.warn('上传提前终止，可能需要重新上传.')
            self.upload_proc.send_signal(signal.SIGINT)
            out, _ = self.upload_proc.communicate(timeout=2.0)
            out = out.decode('utf-8')
            logging.debug(out)
        except Exception as e:
            logging.debug(e)

        

