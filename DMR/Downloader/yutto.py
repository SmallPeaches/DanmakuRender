import math
import os, json, subprocess
import shutil
import logging
import glob
import tempfile
import threading

from datetime import datetime
from os.path import exists, join, splitext, split, isdir, isfile
from DMR.utils import *
from DMR.LiveAPI.bilivideo import BiliVideoAPI


class YuttoDownloader():
    def __init__(
            self, 
            url:str,
            output_dir:str, 
            output_name:str=None,
            output_format:str=None,
            quality:int=None,
            cookies:str=None,
            account:str=None,
            segment_callback=None,
            start_time:str=None,
            end_time:str=None,
            danmaku:bool=True, 
            subtitle:bool=False, 
            check_interval:int=600,
            subprocess_timeout:int=3600,
            extra_args:list=None,
            debug=False, 
            **kwargs,
        ) -> None:
        self.url = url
        self.output_dir = output_dir
        self.output_name = output_name
        self.output_format = output_format
        self.quality = quality
        self.start_time = datetime.strptime(start_time, '%Y-%m-%d %H:%M:%S') if start_time else None
        self.end_time = datetime.strptime(end_time, '%Y-%m-%d %H:%M:%S') if end_time else None
        self.danmaku = danmaku
        self.subtitle = subtitle
        self.extra_args = extra_args
        self.segment_callback = segment_callback
        self.check_interval = check_interval
        self.subprocess_timeout = subprocess_timeout or None
        self.debug = debug

        self.logger = logging.getLogger(__name__)

        cookies_path = bili_login(cookies, account)
        self.logger.info(f'正在使用 {cookies_path} 的cookies登录B站下载视频。')
        with open(cookies_path, encoding='utf8') as f:
            cookies_dict = json.load(f)
        self.cookies = {it['name']:it['value'] for it in cookies_dict['cookie_info']['cookies']}
        self.stoped = False
        self.yutto_proc = None

    def download_once(
            self, 
            url, 
            output_dir:str, 
            output_name:str=None,
            quality:int=None,
            start_time:datetime=None,
            end_time:datetime=None,
            danmaku:bool=True, 
            subtitle:bool=False, 
            batch:bool=True,
            extra_args:list=None,
            **kwargs,
        ):
        cmd = ['yutto', '-w', '--no-color', '--no-progress', '-c', self.cookies['SESSDATA']]
        cmd += ['-d', output_dir]
        
        if batch: cmd += ['-b']
        if output_name: cmd += ['-tp', output_name]
        if not danmaku: cmd += ['--no-danmaku']
        if not subtitle: cmd += ['--no-subtitle']
        if quality: cmd += ['-q', quality]
        if start_time: cmd += ['--batch-filter-start-time', start_time.strftime('%Y-%m-%d %H:%M:%S')]
        if end_time: cmd += ['--batch-filter-end-time', end_time.strftime('%Y-%m-%d %H:%M:%S')]

        cmd += extra_args if extra_args is not None else []
        cmd += [url]
        cmd = [str(c) for c in cmd]

        if self.debug:
            self.yutto_proc = subprocess.Popen(cmd, stderr=subprocess.STDOUT)
            self.yutto_proc.wait()
            return self.yutto_proc.returncode == 0

        with tempfile.TemporaryFile() as tmpfile:
            self.yutto_proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=tmpfile, stderr=subprocess.STDOUT)
            try:
                self.yutto_proc.wait(self.subprocess_timeout)
            except subprocess.TimeoutExpired:
                self.yutto_proc.kill()
                self.logger.error(f'下载 {self.url} 超时')
                return False

            if self.yutto_proc.returncode != 0 and not self.stoped:
                tmpfile.seek(0)
                info = tmpfile.read().decode('utf8', errors='ignore')
                self.logger.error(f'下载 {self.url} 时出现错误: {info}')
                return False
            
            return True
        
    def download_user(self):
        self.start_time = self.start_time or datetime.now()
        vapi = BiliVideoAPI(cookies=self.cookies)
        user_id = re.search(r'space.bilibili.com/\d+', self.url)[0].split('/')[-1]

        while not self.stoped:
            try:
                stime = datetime.now()
                user_videos_info = vapi.fetch_user_videos(user_id)
                video_count = user_videos_info['page']['count']
                video_pages = math.ceil(video_count/30)
                valid_videos = []
                for page_id in range(1, video_pages+1):
                    this_videos = vapi.fetch_user_videos(user_id, page=page_id)['list']['vlist']
                    new_video = []
                    for video_info in this_videos:
                        ctime = datetime.fromtimestamp(video_info['created'])
                        if ctime < self.start_time:
                            continue
                        elif self.end_time and ctime > self.end_time:
                            continue
                        new_video.append(video_info['bvid'])
                    if len(new_video) == 0:
                        break
                    else:
                        valid_videos += new_video
                    
                for bvid in valid_videos:
                    video_info = vapi.fetch_video_info(bvid)
                    for pid, pinfo in enumerate(video_info['pages']):
                        segment_info = VideoInfo(
                            file_id=uuid(),
                            dtype='src_video',
                            path='',
                            group_id=video_info['title'],
                            segment_id=pid,
                            size=0,
                            duration=pinfo['duration'],
                            ctime=video_info['pubdate'],
                            title=pinfo['part'],
                            streamer=StreamerInfo(
                                name=video_info['owner']['name'], 
                                id=video_info['owner']['mid'], 
                                url=f"https://space.bilibili.com/{video_info['owner']['mid']}",
                                face_url=video_info['owner']['face'],
                            ),
                            desc=video_info['desc'],
                            url=f'https://www.bilibili.com/video/{bvid}?p={pid+1}',
                            cover_url=video_info['pic'],
                        )
                        outname_fmt = self.output_name or r'{GROUP_ID}/{TITLE}'
                        outname = replace_keywords(outname_fmt, segment_info, replace_invalid=True)
                        status = self.download_once(
                            url=f'https://www.bilibili.com/video/{bvid}?p={pid+1}', 
                            output_dir=self.output_dir, 
                            output_name=outname, 
                            quality=self.quality,
                            danmaku=self.danmaku, 
                            subtitle=self.subtitle, 
                            batch=False,
                            extra_args=self.extra_args,
                        )
                        realpath = self._get_video(join(self.output_dir, outname))
                        if not status or not realpath:
                            self.logger.error(f'下载 {self.url} 时出现错误，将跳过此次下载.')
                            continue
                        
                        segment_info.path = realpath
                        segment_info.size = os.path.getsize(realpath)

                        dmfile = self._get_danmaku(segment_info.path)
                        if dmfile:
                            segment_info.dm_file_id = dmfile
                        self.segment_callback(segment_info)
                self.start_time = stime
            except Exception as e:
                self.logger.error(f'下载 {self.url} 时出现错误: {e}')
            time.sleep(self.check_interval)

    @staticmethod
    def _get_danmaku(path:str):
        for ext in ['.ass', '.xml', '.protobuf']:
            dmfile = splitext(path)[0]+ext
            if exists(dmfile):
                return dmfile
            
    @staticmethod
    def _get_video(path:str):
        if isvideo(path): return path
        for ext in ['.mp4', '.mkv', '.ts', '.flv']:
            if isvideo(path+ext):
                return path+ext
    
    def download_directly(self):
        self.start_time = self.start_time or datetime.now()

        while not self.stoped:
            try:
                stime = datetime.now()
                temp_dir = f'.temp/yutto_{int(time.time())+86400}'
                os.makedirs(temp_dir, exist_ok=True)
                status = self.download_once(
                    url=self.url, 
                    output_dir=temp_dir, 
                    output_name=self.output_name,
                    quality=self.quality,
                    start_time=self.start_time,
                    end_time=self.end_time,
                    danmaku=self.danmaku, 
                    subtitle=self.subtitle, 
                    extra_args=self.extra_args,
                )
                if status:
                    os.makedirs(self.output_dir, exist_ok=True)
                    for fname in sorted(os.listdir(temp_dir)):
                        filepath = join(temp_dir, fname)
                        if isfile(filepath):
                            newfile = join(self.output_dir, fname)
                            shutil.move(filepath, newfile)
                            video_info = VideoInfo(
                                file_id=uuid(),
                                dtype='src_video',
                                path=newfile,
                                group_id=uuid(8),
                                size=os.path.getsize(newfile),
                                ctime=os.path.getctime(newfile),
                                title=splitext(fname)[0],
                            )
                            dmfile = self._get_danmaku(filepath)
                            if dmfile:
                                shutil.move(dmfile, join(self.output_dir, split(dmfile)[1]))
                                video_info.dm_file_id = join(self.output_dir, split(dmfile)[1])
                            self.segment_callback(video_info)
                        elif isdir(filepath):
                            new_dir = join(self.output_dir, fname)
                            shutil.move(filepath, new_dir)
                            for fn in sorted(os.listdir(filepath)):
                                fp = join(new_dir, fn)
                                if not isfile(fp): continue
                                video_info = VideoInfo(
                                    file_id=uuid(),
                                    dtype='src_video',
                                    path=fp,
                                    group_id=uuid(8),
                                    size=os.path.getsize(fp),
                                    ctime=os.path.getctime(fp),
                                    title=splitext(fname)[0],
                                )
                                dmfile = self._get_danmaku(fp)
                                if dmfile:
                                    video_info.dm_file_id = dmfile
                                self.segment_callback(video_info)
                    unused_files = glob.glob(join(temp_dir, '*'))
                    if len(unused_files) > 0:
                        self.logger.warn(f'下载 {self.url} 时存在无法被处理的文件: {unused_files}, 此文件将被删除.')
                    self.start_time = stime
            except Exception as e:
                self.logger.error(f'下载 {self.url} 时出现错误: {e}')
            finally:
                shutil.rmtree(temp_dir)
            
            if self.end_time and datetime.now() > self.end_time:
                self.stoped = True
                return 'finished'

            time.sleep(self.check_interval)

    def start(self):
        self.stoped = False
        if re.fullmatch(r'https://space.bilibili.com/\d+', self.url):
            # return self.download_directly()
            return self.download_user()
        else:
            return self.download_directly()
    
    def stop(self):
        self.stoped = True
        if self.yutto_proc:
            self.yutto_proc.terminate()
        self.logger.info(f'下载 {self.url} 已停止。')