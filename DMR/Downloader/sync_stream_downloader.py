import logging
import os
import queue
import threading
import time

from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from os.path import join,exists,splitext
from datetime import datetime
from DMR.Downloader.Danmaku import DanmakuDownloader
from DMR.LiveAPI import *
from DMR.utils import *
from .stream_downloader import StreamDownloadTask


class SyncStreamDownloadTask(StreamDownloadTask):
    def __post_init__(self):
        self.danmaku = False

    def start_once(self):
        self.stoped = False
        
        # init segment info
        self.room_info = retry_safe(self.liveapi.GetRoomInfo)
        self.streamer_info = retry_safe(self.liveapi.GetStreamerInfo)
        if not(self.room_info and self.streamer_info):
            raise RuntimeError(f'{self.taskname}: 获取主播信息出现错误.')
        
        self.segment_start_time = datetime.now()
        os.makedirs(self.output_dir,exist_ok=True)
        
        stream_url = self.liveapi.GetStreamURL(**self.stream_option)
        stream_request_header = self.liveapi.GetStreamHeader()
        # width, height = FFprobe.get_resolution(stream_url, stream_request_header)
        # 斗鱼和虎牙的直播地址只能用一次，所以要重新获取
        # if self.plat == 'douyu' or self.plat == 'huya':
        #     stream_url = self.liveapi.GetStreamURL(**self.stream_option)

        this_engine = self.engine
        if this_engine == 'auto':
            # B站规则：带有bluray的hls流使用pyrequests，普通的hls流使用ffmpeg，flv流使用streamgears
            if self.plat == 'bilibili':
                if re.search(r'live_\d+_[a-zA-Z_]{0,10}\d+_[a-zA-Z]{1,10}', stream_url)\
                    and '.m3u8' in stream_url:
                    this_engine = 'pyrequests'
                elif '.m3u8' in stream_url:
                    this_engine = 'ffmpeg'
                else:
                    this_engine = 'streamgears'
            # # 虎牙必须使用ffmpeg (https://github.com/SmallPeaches/DanmakuRender/issues/386)
            # elif self.plat == 'huya':
            #     this_engine = 'ffmpeg'
            # 其他原生支持的平台hls流使用ffmpeg，flv流使用streamgears
            elif self.plat in ['huya', 'douyu', 'douyin', 'cc']:
                if '.m3u8' in stream_url:
                    this_engine = 'ffmpeg'
                else:
                    this_engine = 'streamgears'
            # streamlink支持的平台使用streamlink
            else:
                this_engine = 'streamlink'

        # 目前只支持streamlink的同步下载
        this_engine = 'streamlink_sync'

        if this_engine == 'ffmpeg_sync':
            from .ffmpeg import FFmpegDownloader
            downloader_class = FFmpegDownloader
        elif this_engine == 'streamlink_sync':
            from .streamlink_sync import StreamlinkSyncDownloader
            downloader_class = StreamlinkSyncDownloader
        elif this_engine == 'pyrequests_sync':
            from .pyrequests import PyRequestsDownloader
            downloader_class = PyRequestsDownloader
        else: 
            raise NotImplementedError(f'No Downloader Named {this_engine}.')

        self.width, self.height = 0, 0

        self.downloader = None
        self.dmw = None
        
        def video_thread():
            self.downloader = downloader_class(
                stream_url=stream_url,
                header=stream_request_header,
                output_dir=self.output_dir,
                output_format=self.output_format,
                segment=self.segment,
                url=self.url,
                taskname=self.taskname,
                advanced_video_args=self.advanced_video_args,
                segment_callback=self.segment_callback,
                stable_callback=self.stable_callback,
                debug=self.debug,
                **self.kwargs
            )
            self.downloader.start()

        self.executor = ThreadPoolExecutor(max_workers=1)
        future = self.executor.submit(video_thread)
        
        while not self.stoped:
            try:
                return future.result(timeout=60)
            except TimeoutError:
                if self.liveapi.Onair() == False:
                    self.logger.debug('LIVE END.')
                    return
    
    def segment_callback(self, stream_queue):
        if self.room_info is None:
            self.logger.warning('房间信息获取失败，无法录制.')
            return

        video_info = VideoInfo(
            file_id=uuid(),
            dtype='src_video',
            path='',
            group_id=self.sess_id,
            segment_id=self.segment_id,
            size=0,
            ctime=datetime.now(),
            duration=28800,                  # 用于绕过上传时长检测
            resolution=(self.width, self.height),
            title=self.room_info['title'],
            streamer=self.streamer_info,
            taskname=self.taskname,
            stream_queue=stream_queue,
        )
        
        max_fn_length = self.advanced_video_args.get('max_fn_length', 80)
        filename = replace_keywords(self.output_name, video_info)[:max_fn_length]
        video_info.path = filename

        if self.advanced_video_args.get('group_id'):
            group_id = str(self.advanced_video_args['group_id'])
            group_id = replace_keywords(group_id, video_info)
            video_info.upload_group_id = group_id

        self._pipeSend(event='livesegment', msg=f'同步下载P{self.segment_id}: {video_info.title}开始.', target=f'replay/{self.taskname}', dtype='VideoInfo', data=video_info)
        new_room_info = retry_safe(self.liveapi.GetRoomInfo)
        if new_room_info:
            self.room_info = new_room_info
        # self.segment_start_time = datetime.now()
        self.segment_id += 1
