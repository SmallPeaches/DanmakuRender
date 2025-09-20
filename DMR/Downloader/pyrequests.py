import re
import logging
import subprocess
import sys
import os
import glob
import requests
import m3u8
import time

from collections import deque
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime
from os.path import splitext, split, join, exists

from DMR.utils import *


class PyRequestsFlvDownloader:
    default_header = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'User-Agent': 'Mozilla/5.0 (Linux; Android 5.0; SM-G900P Build/LRX21T) AppleWebKit/537.36 '
                            '(KHTML, like Gecko) Chrome/75.0.3770.100 Mobile Safari/537.36 '
        }

    def __init__(self, 
                 stream_url:str, 
                 output_dir:str,
                 output_format:str,
                 segment:int,
                 url:str,
                 taskname:str,
                 debug=False,
                 header:dict=None,
                 advanced_video_args:dict=None,
                 segment_callback=None,
                 **kwargs):
        
        self.stream_url = stream_url
        self.header = header if header else self.default_header
        self.output_dir = output_dir
        self.output_format = output_format
        self.segment = segment
        self.debug = debug
        self.taskname = taskname
        self.url = url
        self.segment_callback = segment_callback
        self.advanced_video_args = advanced_video_args if advanced_video_args else {}
        self.kwargs = kwargs

        if '.flv' not in self.stream_url:
            self.logger.warning(f'pyrequests仅支持flv流!')

        self.stoped = False
        self.logger = logging.getLogger(__name__)
        self.session = requests.Session()
        self.session.headers.update(self.header)

    def _download_part(self, stream_iter:requests.Response):
        start_t = datetime.now()
        self.video_file = join(self.output_dir, f'[正在录制]{self.taskname}-{start_t.strftime("%Y%m%d-%H%M%S")}.{self.output_format}')
        if exists(self.video_file):
            cnt = len(glob.glob(splitext(self.video_file)[0] + '*'))
            self.video_file = splitext(self.video_file)[0] + f'({cnt})' + splitext(self.video_file)[1]

        with open(self.video_file, 'wb') as file_obj:
            for idx, chunk in enumerate(stream_iter):
                if not chunk:
                    raise RuntimeError(f'{self.taskname} stream end.')

                file_obj.write(chunk)
                if idx % 10 == 0:
                    file_obj.flush()

                now_t = datetime.now()
                duration = (now_t - start_t).total_seconds()
                if (self.segment and duration > self.segment) \
                    or self.stoped:
                    file_obj.flush()
                    break

        return self.video_file

    def start(self):
        self.logger.debug(f'{self.taskname} PyRequestsFlv: {self.stream_url}')

        stream = self.session.get(self.stream_url, headers=self.header, stream=True)
        if stream.status_code != 200:
            raise RuntimeError(f'Error downloading stream: {stream.status_code}')
        stream_iter = stream.iter_content(chunk_size=512*1024)
        
        while not self.stoped:
            try:
                self._download_part(stream_iter)
            except Exception as e:
                self.logger.debug(f'{self.taskname} Error downloading stream: {e}')
                raise e
            finally:
                if self.video_file and exists(self.video_file):
                    new_file = rename_safe(self.video_file, self.video_file.replace('[正在录制]', ''))
                    if not new_file:
                        self.logger.error(f'{self.taskname} 重命名文件 {self.video_file} 失败!')
                        new_file = self.video_file
                    self.logger.debug(f'{self.taskname} 录制完成: {new_file}')
                    self.segment_callback(new_file)
    
    def stop(self):
        self.stoped = True
        self.logger.debug('PyRequestsFlv downloader stoped.')


class PyRequestsHlsDownloader:
    default_header = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'User-Agent': 'Mozilla/5.0 (Linux; Android 5.0; SM-G900P Build/LRX21T) AppleWebKit/537.36 '
                            '(KHTML, like Gecko) Chrome/75.0.3770.100 Mobile Safari/537.36 '
        }

    def __init__(self,  
                 stream_url:str, 
                 output_dir:str,
                 output_format:str,
                 segment:int,
                 url:str,
                 taskname:str,
                 debug=False,
                 header:dict=None,
                 advanced_video_args:dict=None,
                 segment_callback=None,
                 stable_callback=None,
                 **kwargs):
        
        self.stream_url = stream_url
        self.header = header if header else self.default_header
        self.output_dir = output_dir
        self.output_format = output_format
        self.segment = segment
        self.debug = debug
        self.taskname = taskname
        self.url = url
        self.segment_callback = segment_callback
        self.stable_callback = stable_callback
        self.advanced_video_args = advanced_video_args if advanced_video_args else {}
        self.kwargs = kwargs

        self.stoped = False
        self.logger = logging.getLogger(__name__)
        self.session = requests.Session()
        self.session.headers.update(self.header)
        self.force_origin = self.advanced_video_args.get('bili_force_origin', True)

        if 'bilibili' not in self.url or '.m3u8' not in self.stream_url:
            self.logger.warning(f'pyrequests仅支持来自bilibili的hls流, 其他来源的hls流可能导致录制错误!')
            # raise ValueError(f'pyrequests仅支持bilibili的m3u8流!')

        self.downloaded_files = deque(maxlen=60)
        self.download_executor = ThreadPoolExecutor(max_workers=8)
        self.headfile = b''
        self.headfile_name = ''
        self.video_file = ''

    def _convert2origin(self, uri):
        keys = re.findall(r'live_\d+_[a-zA-Z_]{0,10}\d+_[a-zA-Z]{1,10}', uri)
        if not keys:
            return uri
        else:
            key = keys[0]
            new_key = '_'.join(key.split('_')[:-1])
            new_uri = uri.replace(key, new_key)
            return new_uri
        
    def _find_headfile(self, uri):
        headfile_name = re.findall(r'h\d+\.m4s', uri)[0]
        base_idx = int(headfile_name[1:-4])
        base_uri = uri.replace(headfile_name, 'h{idx}.m4s')
        sess = requests.Session()
        sess.headers.update(self.header)
        headfile = b''
        # B站的fmp4头以10位时间戳命名，往前扫描100s试出真实的头文件
        try:
            for bias in range(100):
                idx = base_idx - bias
                uri = base_uri.format(idx=idx)
                resp = sess.get(uri, timeout=3)
                if resp.status_code == 200:
                    # print(f'idx: {idx}')
                    headfile = resp.content
                    break
        except Exception as e:
            self.logger.debug(f'Error finding headfile: {e}')
        return headfile
    
    def _download_segment(self, uri, retry=5):
        while retry > 0:
            try:
                resp = self.session.get(uri, timeout=3)
                resp.raise_for_status()
                return resp.content
            except Exception as e:
                # self.logger.debug(f'Error downloading segment: {e}')
                retry -= 1
                time.sleep(1)

    def _init_headfile(self):
        m3u8_uri = self.m3u8_uri
        m3u8_obj = m3u8.load(m3u8_uri, headers=self.header, timeout=3)

        # 获取mp4文件头
        params_str = m3u8_uri.split('?')[1] if '?' in m3u8_uri else ''
        if m3u8_obj.segment_map:
            headfile_name = m3u8_obj.segment_map[0].uri
            headfile_uri = m3u8_obj.segment_map[0].absolute_uri + '?' + params_str
            if headfile_name != self.headfile_name:
                if self.force_origin:
                    t0 = time.time()
                    headfile_uri_origin = self._convert2origin(headfile_uri)
                    self.headfile = self._find_headfile(headfile_uri_origin)
                    if not self.headfile:
                        self.logger.warning(f'{self.taskname}: 未找到原画头文件: {headfile_name}, 即将回退到非原画模式')
                        self.headfile = self.session.get(headfile_uri).content
                        self.force_origin = False
                    t1 = time.time()
                    # 将获取头文件的时间传递给回调函数，让弹幕时间更准确
                    if self.stable_callback:
                        self.stable_callback(t0-t1)
                else:
                    self.headfile = self.session.get(headfile_uri).content
                self.headfile_name = headfile_name

    def download_part(self):
        now = datetime.now()
        self.video_file = join(self.output_dir, f'[正在录制]{self.taskname}-{now.strftime("%Y%m%d-%H%M%S")}.{self.output_format}')
        if exists(self.video_file):
            cnt = len(glob.glob(splitext(self.video_file)[0] + '*'))
            self.video_file = splitext(self.video_file)[0] + f'({cnt})' + splitext(self.video_file)[1]

        m3u8_uri = self.m3u8_uri
        params_str = m3u8_uri.split('?')[1] if '?' in m3u8_uri else ''
        
        m4s_duration = 0
        error_cnt = 0
        error = ''
        
        with open(self.video_file, 'wb') as video_file:
            video_file.write(self.headfile)
            while not self.stoped:
                t0 = time.time()
                try:
                    m3u8_obj = m3u8.load(m3u8_uri, headers=self.header, timeout=3)
                    if m3u8_obj.segment_map:
                        new_headfile = m3u8_obj.segment_map[0].uri
                        if self.headfile_name != new_headfile:
                            self.logger.debug(f'{self.taskname} 头文件更新: {self.headfile_name} -> {new_headfile}')
                            return
                    
                    this_segs = 0
                    for seg in m3u8_obj.segments:
                        seg_name = seg.uri
                        seg_uri = seg.absolute_uri + '?' + params_str
                        seg_duration = seg.duration
                        if seg_name in self.downloaded_files:
                            continue
                        if self.force_origin:
                            seg_uri = self._convert2origin(seg_uri)
                        
                        # 过多的下载任务会导致内存溢出
                        if len(self.future_to_segid) > 30:
                            raise RuntimeError('Too many segments downloading.')

                        future = self.download_executor.submit(self._download_segment, seg_uri)
                        self.future_to_segid[future] = self.segid
                        self.downloaded_files.append(seg_name)
                        self.segid += 1
                        this_segs += 1

                    done, _ = wait(self.future_to_segid, timeout=0.1, return_when=FIRST_COMPLETED)
                    finished_segid_to_future = {self.future_to_segid[fut]: fut for fut in done}

                    while self.next_segid in finished_segid_to_future:
                        future = finished_segid_to_future[self.next_segid]
                        result = future.result()
                        if not result:
                            error_cnt += 1
                            self.logger.debug(f'{self.taskname} Error downloading segment: {self.next_segid}')
                        else:
                            error_cnt = 0
                            video_file.write(result)
                            # self.logger.debug(f'{self.taskname} Downloaded segment: {self.next_segid}')
                        self.next_segid += 1
                        del self.future_to_segid[future]
                        m4s_duration += seg_duration
                    
                    if this_segs == 0:
                        raise RuntimeError('No new segments found.')
                except Exception as e:
                    error_cnt += 1
                    error = e

                video_file.flush()
                if self.segment and m4s_duration > self.segment:
                    self.logger.debug(f'{self.taskname} 分段录制完成: {m4s_duration}s')
                    break
                if error_cnt > 3:
                    # self.logger.debug(f'Error downloading segment: {error_cnt} times')
                    raise RuntimeError(f'Error downloading video: {error}')
                time.sleep(max(0, 3-time.time()+t0))

    def start(self):
        self.logger.debug(f'{self.taskname} PyrequestsHls: {self.stream_url}')
        if self.force_origin and self._convert2origin(self.stream_url) != self.stream_url:
            self.logger.warning(f'{self.taskname} 正工作在强制原画模式下，可能导致录制错误!')
            self.logger.debug(self._convert2origin(self.stream_url))
        
        self.stoped = False
        self.segid = 0
        self.next_segid = 0
        self.future_to_segid = {}

        # 处理playlist的情况
        m3u8_uri = self.stream_url
        for _ in range(3):
            m3u8_obj = m3u8.load(m3u8_uri, headers=self.header, timeout=3)
            if m3u8_obj.segments:
                break
            m3u8_uri = m3u8_obj.playlists[0].absolute_uri
        self.m3u8_uri = m3u8_uri

        while not self.stoped:
            try:
                self._init_headfile()
                self.download_part()
            except Exception as e:
                done, _ = wait(self.future_to_segid, timeout=1, return_when=FIRST_COMPLETED)
                finished_segid_to_future = {self.future_to_segid[fut]: fut for fut in done}
                if finished_segid_to_future:
                    with open(self.video_file, 'ab') as video_file:
                        while self.next_segid in finished_segid_to_future:
                            future = finished_segid_to_future[self.next_segid]
                            result = future.result()
                            if not result:
                                self.logger.debug(f'{self.taskname} Error downloading segment: {self.next_segid}')
                            else:
                                video_file.write(result)
                            self.next_segid += 1
                            del self.future_to_segid[future]
                raise e
            finally:
                if not self.stoped and self.video_file and exists(self.video_file):
                    new_file = rename_safe(self.video_file, self.video_file.replace('[正在录制]', ''))
                    if not new_file:
                        self.logger.error(f'{self.taskname} 重命名文件 {self.video_file} 失败!')
                        new_file = self.video_file
                    self.logger.debug(f'{self.taskname} 录制完成: {new_file}')
                    self.segment_callback(new_file)
    
    def stop(self):
        self.stoped = True
        self.download_executor.shutdown(wait=False)
        try:
            if self.video_file and exists(self.video_file):
                new_file = rename_safe(self.video_file, self.video_file.replace('[正在录制]', ''))
                if not new_file:
                    self.logger.error(f'{self.taskname} 重命名文件 {self.video_file} 失败!')
                    new_file = self.video_file
                self.logger.debug(f'{self.taskname} 录制完成: {new_file}')
                self.segment_callback(new_file)
        except Exception as e:
            self.logger.debug(e)
        self.logger.debug(f'{self.taskname}：Pyrequests downloader stoped.')


class PyRequestsDownloader:
    def __init__(self, stream_url:str, *args, **kwargs):
        self.logger = logging.getLogger(__name__)
        if '.m3u8' in stream_url or '.m3u' in stream_url:
            self.logger.debug(f'即将使用PyRequestsHlsDownloader下载流: {stream_url}')
            self.downloader = PyRequestsHlsDownloader(stream_url, *args, **kwargs)
        else:
            self.logger.debug(f'即将使用PyRequestsFlvDownloader下载流: {stream_url}')
            self.downloader = PyRequestsFlvDownloader(stream_url, *args, **kwargs)
    
    def start(self):
        self.downloader.start()
    
    def stop(self):
        self.downloader.stop()
