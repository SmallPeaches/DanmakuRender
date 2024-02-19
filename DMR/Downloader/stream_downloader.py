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


class StreamDownloadTask():
    def __init__(self, 
                 url, 
                 output_dir, 
                 send_queue:queue.Queue, 
                 segment:int, 
                 output_name=None, 
                 taskname=None, 
                 danmaku=True, 
                 video=True, 
                 stop_wait_time=0, 
                 output_format='flv', 
                 stream_option=None, 
                 advanced_video_args:dict=None,
                 advanced_dm_args:dict=None,
                 engine='ffmpeg', 
                 debug=False, 
                 **kwargs
        ) -> None:
        self.taskname = taskname
        self.url = url
        self.plat, self.rid = split_url(url)
        self.liveapi = LiveAPI(url)
        self.output_dir = output_dir
        self.output_format = output_format
        self.output_name = output_name
        self.send_queue = send_queue
        self.logger = logging.getLogger(__name__)
        self.kwargs = kwargs
        self.debug = debug
        self.segment = segment
        self.danmaku = danmaku
        self.video = video
        self.stream_option = stream_option
        self.stop_wait_time = stop_wait_time
        self.engine = engine
        self.advanced_video_args = advanced_video_args if advanced_video_args else {}
        self.advanced_dm_args = advanced_dm_args if advanced_dm_args else {}

        if self.engine == 'ffmpeg':
            from .ffmpeg import FFmpegDownloader
            self.download_class = FFmpegDownloader
        elif self.engine == 'streamgears':
            from .streamgears import StreamgearsDownloader
            self.download_class = StreamgearsDownloader
        elif self.engine == 'streamlink':
            from .streamlink import StreamlinkDownloader
            self.download_class = StreamlinkDownloader
        else: 
            raise NotImplementedError(f'No Downloader Named {self.engine}.')

        os.makedirs(self.output_dir,exist_ok=True)
    
    def _pipeSend(self, event, msg, target=None, dtype=None, data=None, **kwargs):
        if self.send_queue:
            target = target if target else f'replay/{self.taskname}'
            msg = PipeMessage(
                source='downloader',
                target=target,
                event=event,
                msg=msg,
                dtype=dtype,
                data=data,
                **kwargs,
            )
            self.send_queue.put(msg)

    def stable_callback(self, time_error):
        if hasattr(self, 'dmw'):
            self.dmw.time_fix(time_error)

    def segment_callback(self, filename:str):
        if self.room_info is None or not exists(filename):
            self.logger.debug(f'No video file {filename}')
            return 
        
        video_info = VideoInfo(
            file_id=uuid(),
            dtype='src_video',
            path=filename,
            group_id=self.sess_id,
            segment_id=0,
            size=os.path.getsize(filename),
            ctime=self.segment_start_time,
            duration=datetime.now().timestamp()-self.segment_start_time.timestamp(),
            resolution=(self.width, self.height),
            title=self.room_info['title'],
            streamer=self.streamer_info,
            taskname=self.taskname,
        )

        newfile = join(self.output_dir, replace_keywords(self.output_name, video_info, replace_invalid=True)+'.'+self.output_format)
        _file = rename_safe(filename, newfile)
        if _file:
            newfile = _file
        else:
            newfile = filename
            self.logger.error(f'视频 {newfile} 分段失败，将使用默认名称 {filename}.')
            
        if self.danmaku:
            newdmfile = splitext(newfile)[0]+'.'+self.kwargs.get('dm_format', 'ass')
            self.dmw.split(newdmfile)
        else:
            newdmfile = None
        
        video_info.path = newfile
        video_info.dm_file_id = newdmfile
        self._pipeSend(event='livesegment', msg=f'视频分段 {newfile} 录制完成.', target=f'replay/{self.taskname}', dtype='VideoInfo', data=video_info)

        new_room_info = self.liveapi.GetRoomInfo()
        if new_room_info:
            self.room_info = new_room_info
        self.segment_start_time = datetime.now()

    def start_once(self):
        self.stoped = False
        
        # init segment info
        self.room_info = self.streamer_info = None
        while not self.streamer_info:
            self.streamer_info = self.liveapi.GetStreamerInfo()
        while not self.room_info:
            self.room_info = self.liveapi.GetRoomInfo()
        self.segment_start_time = datetime.now()
        os.makedirs(self.output_dir,exist_ok=True)
        
        stream_url = self.liveapi.GetStreamURL(**self.stream_option)
        stream_request_header = self.liveapi.GetStreamHeader()
        width, height = FFprobe.get_resolution(stream_url, stream_request_header)
        # 斗鱼的直播地址只能用一次，所以要重新获取
        if self.plat == 'douyu':
            stream_url = self.liveapi.GetStreamURL(**self.stream_option)

        if not (width and height):
            default_resolution = self.advanced_video_args.get('default_resolution', (1920, 1080))
            self.logger.warn(f'无法获取视频大小，使用默认值 {default_resolution}.')
            width, height = default_resolution
        
        self.width,self.height = width, height

        self.downloader = None
        self.dmw = None

        def danmaku_thread():
            description = f'{self.taskname}的录播弹幕文件, {self.url}, Powered by DanmakuRender: https://github.com/SmallPeaches/DanmakuRender.'
            danmu_output = join(self.output_dir, f'[正在录制]{self.taskname}-{time.strftime("%Y%m%d-%H%M%S",time.localtime())}-Part%03d.ass')
            self.dmw = DanmakuDownloader(self.url,
                                     danmu_output,
                                     self.segment,
                                     description=description,
                                     width=self.width,
                                     height=self.height,
                                     advanced_dm_args=self.advanced_dm_args,
                                     **self.kwargs)
            self.dmw.start(self_segment=not self.video)
        
        def video_thread():
            self.downloader = self.download_class(
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

        self.executor = ThreadPoolExecutor(max_workers=2)
        futures = []
        if self.danmaku:
            futures.append(self.executor.submit(danmaku_thread))
        if self.video:
            futures.append(self.executor.submit(video_thread))
        
        while not self.stoped:
            try:
                for future in as_completed(futures, timeout=60):
                    return future.result()
            except TimeoutError:
                if self.liveapi.Onair() == False:
                    self.logger.debug('LIVE END.')
                    return

    def start_helper(self):
        self.loop = True
        stop_waited = 0  # 已经等待的时间（下播但是还没停止）
        stop_wait_time = self.stop_wait_time*60    # 设定的等待时间
        live_end = False
        restart_cnt = 0     # 出错重启次数
        start_check_interval = self.advanced_video_args.get('start_check_interval', 60)  # 开播检测时间
        stop_check_interval = self.advanced_video_args.get('stop_check_interval', 30)   # 下播检测间隔
        self.sess_id = uuid(8)

        if not self.liveapi.Onair():
            self._pipeSend('liveend', '直播已结束', )
            live_end = True
            time.sleep(start_check_interval)

        while self.loop:
            if not self.liveapi.Onair():
                restart_cnt = 0
                if live_end:
                    time.sleep(start_check_interval)
                    stop_waited += start_check_interval
                else:
                    time.sleep(stop_check_interval)
                    stop_waited += stop_check_interval
                
                if stop_waited > stop_wait_time and not live_end:
                    live_end = True
                    self._pipeSend('liveend', '直播已结束', data=self.sess_id)
                    self.sess_id = uuid(8)          # 每场直播结束后重新分配session id
                continue

            try:
                stop_waited = 0
                live_end = False
                self._pipeSend('livestart', '直播开始', dtype='str', data=self.sess_id)
                self.start_once()
                if self.liveapi.Onair():
                    raise RuntimeError(f'{self.taskname} 录制异常退出.')
            except KeyboardInterrupt:
                self.stop()
                exit(0)
            except Exception as e:
                if self.liveapi.Onair():
                    self.logger.exception(e)
                    self.stop_once()
                    self._pipeSend('liveerror', f'录制过程出错:{e}', dtype='Exception', data=e)
                    time.sleep(min(restart_cnt*10,60))
                    restart_cnt += 1
                    continue
                else:
                    self.logger.debug(e)
            
            self.logger.debug(f'{self.taskname} stop once.')
            self.stop_once()

    def start(self):
        thread = threading.Thread(target=self.start_helper,daemon=True)
        thread.start()
        return thread
    
    def stop(self):
        self.loop = False
        self.stop_once()
        self._pipeSend('livestop', '录制终止', dtype='str', data=self.sess_id if hasattr(self, 'sess_id') else None)

    def stop_once(self):
        self.stoped = True
        if self.danmaku and hasattr(self, 'dmw'):
            try:
                self.dmw.stop()
            except Exception as e:
                self.logger.exception(e)
        if self.video and hasattr(self, 'downloader'):
            try:
                self.downloader.stop()
            except Exception as e:
                self.logger.exception(e)
        try:
            if hasattr(self, 'executor'):
                self.executor.shutdown(wait=False)
        except Exception as e:
            self.logger.exception(e)