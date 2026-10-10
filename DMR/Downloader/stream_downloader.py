import logging
import os
import queue
import threading
import time
import re

from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from os.path import join,exists,splitext
from datetime import datetime
from DMR.Downloader.Danmaku import DanmakuDownloader
from DMR.LiveAPI import *
from DMR.state import ArtifactKind, encode_video_info, make_artifact_key
from DMR.utils import *


#: 状态库的进程级引用（P1）。
#:
#: 为什么不走配置：``Downloader``/``StreamDownloadTask`` 的配置来自
#: ``download_args``，属于**用户可写的任务配置**；把运行时对象塞进去会污染配置命名
#: 空间、也会让它被意外序列化。这里用模块级引用，由 ``DanmakuRender.start()``
#: 在启动时设置一次。下载器仍可通过 ``state_repo`` 参数显式覆盖（便于单测）。
_STATE_REPO = None


def set_state_repo(repo) -> None:
    """设置下载器使用的状态库（由 ``DanmakuRender`` 启动时调用）。"""
    global _STATE_REPO
    _STATE_REPO = repo


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
                 state_repo=None,
                 **kwargs
        ) -> None:
        self.taskname = taskname
        self.url = url
        self.plat, self.rid = split_url(url)
        self.liveapi = LiveAPI(url)
        self.output_dir = output_dir or './' + self.taskname
        self.output_format = output_format
        self.output_name = output_name
        self.send_queue = send_queue
        self.logger = logging.getLogger(__name__)
        self.kwargs = kwargs
        self.debug = debug
        # 状态持久化（P1）：登记录制场次与已完成的产物分段，
        # 使进程重启后仍能知道"录过哪些分段、它们在磁盘上的位置"。
        self.state_repo = state_repo if state_repo is not None else _STATE_REPO
        # 房间信息在 start_once() 里才取到，而 _register_session() 会读取这两个属性。
        # 必须先给出默认值，否则 start_helper() 里的登记会抛 AttributeError
        # （真机 dryrun 已复现：场次登记失败 → 后续产物写入触发外键约束错误）。
        self.room_info = None
        self.streamer_info = None
        self.segment = segment
        self.danmaku = danmaku
        self.video = video
        self.stream_option = stream_option
        self.stop_wait_time = stop_wait_time
        self.engine = engine or 'auto'
        self.advanced_video_args = advanced_video_args if advanced_video_args else {}
        self.advanced_dm_args = advanced_dm_args if advanced_dm_args else {}
        self.stoped = True

        # if self.engine not in ['ffmpeg', 'streamlink', 'streamgears', 'pyrequests', 'auto']:
        #     raise NotImplementedError(f'No Downloader Named {self.engine}.')

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
        if hasattr(self, 'dmw') and self.dmw:
            self.dmw.time_fix(time_error)

    # ------------------------------------------------------------------ 状态持久化
    #
    # 目标：进程重启后仍能知道"录过哪些分段、文件在哪、哪些需要收尾"。
    #
    # 覆盖范围说明（重要）：
    #   下载引擎（ffmpeg / streamgears / streamlink / pyrequests）**直接写最终文件**，
    #   不经过 .part 中间名。因此这里登记的是**已完成**的分段（segment_callback 触发
    #   时文件已封闭）。录制中途被强杀时，正在写入的那个文件不会被登记 —— 它没有
    #   DB 记录，因此（按"不收养"原则）不会进入后续的文件处理流程，需要人工处理。
    #   要覆盖这一情形需要让各引擎改写 .part 命名，属于独立改动。

    def _register_session(self) -> None:
        """登记本场直播；保存主播/房间元信息，供后续恢复与上传使用。"""
        if self.state_repo is None:
            return
        try:
            room_info = self.room_info or {}
            streamer = self.streamer_info
            self.state_repo.create_session(
                self.sess_id,
                self.taskname,
                group_id=self.kwargs.get('group_id'),
                platform=self.plat,
                room_id=self.rid,
                room_url=self.url,
                streamer_name=getattr(streamer, 'name', None) if streamer else None,
                streamer_uid=getattr(streamer, 'uid', None) if streamer else None,
                title=room_info.get('title'),
            )
            self.logger.debug(f'已登记录制场次 {self.sess_id}（{self.taskname}）。')
        except Exception as e:
            # 状态登记失败不应影响录制本身
            self.logger.warning(f'登记录制场次失败：{e}')

    def _record_segment(self, video_info:VideoInfo) -> None:
        """登记一个已完成的分段。

        弹幕文件（``.ass``）作为该分段视频的**附属字段**记录，而不是独立产物：
        它单独存在没有意义（无法独立上传/清理）。该字段的值由
        ``segment_callback`` 取 ``dmw.split()`` 返回的**实际落盘路径**给出。

        ``video_info`` 整个存进载荷：重启对账后需要**重建**这个产物并重新驱动
        渲染/上传，而输出文件名与视频标题都依赖录制当时的元信息（主播、标题、
        时间），只存路径重建不出来。
        """
        if self.state_repo is None:
            return
        try:
            self.state_repo.upsert_artifact(
                artifact_id=make_artifact_key(self.sess_id, ArtifactKind.SOURCE,
                                              video_info.segment_id),
                session_id=self.sess_id,
                segment_idx=video_info.segment_id,
                kind=ArtifactKind.SOURCE,
                state='recorded',
                path=video_info.path,
                danmaku_path=video_info.dm_file_id,
                size=video_info.size,
                duration=video_info.duration,
                resolution=video_info.resolution,
                video_info=encode_video_info(video_info),
            )
            self.state_repo.touch_session(self.sess_id)
            self.logger.debug(f'已登记分段 {video_info.segment_id}：{video_info.path}')
        except Exception as e:
            self.logger.warning(f'登记分段 {getattr(video_info, "path", None)} 失败：{e}')

    def inprogress_callback(self, filename:str) -> None:
        """下载引擎开始写入一个新文件时的回调（由引擎调用）。

        为什么需要引擎上报、而不是扫目录：引擎明确知道自己在写哪个文件；而**扫描
        目录无法区分"刚封闭、尚未改名的分段"与"正在写入的下一个分段"** —— 测试里
        刚完成的文件仍带 ``[正在录制]`` 前缀，会被误判为进行中（这是实现中真实踩到
        的坑）。因此这里由引擎给出精确信号。

        为什么这件事重要：所有引擎都**直接写最终文件名**、且只在文件封闭后才通过
        ``segment_callback`` 上报。若不登记"进行中"的文件，进程在录制中途被杀时，
        那个已经写了大半的文件就没有任何 DB 记录，会成为无人认领的残file。
        登记为 ``RECORDING`` 之后，重启对账会把它转为 ``INTERRUPTED`` 并按
        ``recovery.on_interrupted_file`` 处置（ask / keep / discard）。
        """
        if self.state_repo is None:
            return
        # 序号与 segment_id 保持一致（调用方在下一个分段开始时已推进 segment_id）。
        # 二者必须同源：否则"进行中"记录会覆盖已完成的同名记录（真实踩到的坑）。
        next_id = getattr(self, 'segment_id', None) or 1
        try:
            self.state_repo.upsert_artifact(
                artifact_id=make_artifact_key(self.sess_id, ArtifactKind.SOURCE,
                                              next_id),
                session_id=self.sess_id,
                segment_idx=next_id,
                kind=ArtifactKind.SOURCE,
                # 引擎直接写最终名，因此 path 与 part_path 相同；
                # 对账据此知道"文件在、但可能没写完"。
                state='recording',
                path=filename,
                part_path=filename,
            )
            self.logger.debug(f'已登记进行中的分段 {next_id}：{filename}')
        except OSError as e:
            self.logger.debug(f'登记进行中的录制文件失败：{e}')
        except (AttributeError, TypeError, KeyError, ValueError) as e:
            # 可预期的错误不应影响录制，但必须记 warning（不可静默）
            self.logger.warning(f'登记进行中的录制文件失败：{e}')
        # 不捕获 NameError / ImportError 等编程错误 —— 它们必须暴露出来。
        # （早期版本在"扫目录"实现里用了宽泛的 except，把 unbound name 这类
        #   NameError 吞掉，导致功能静默失效且难以定位。）

    def _on_live_end(self) -> None:
        """标记场次结束，使对账可以在产物全部终态后回收该场次。"""
        if self.state_repo is None:
            return
        try:
            self.state_repo.end_session(self.sess_id)
        except Exception as e:
            self.logger.warning(f'标记场次结束失败：{e}')

    def segment_callback(self, filename:str):
        if self.room_info is None or not exists(filename):
            self.logger.debug(f'No video file {filename}')
            return 

        duration = datetime.now().timestamp()-self.segment_start_time.timestamp()
        # 如果视频时长小于60秒，尝试使用ffprobe获取视频时长
        if duration < 60:
            duration = max(duration, FFprobe.get_duration(filename))
        
        video_info = VideoInfo(
            file_id=uuid(),
            dtype='src_video',
            path=filename,
            group_id=self.sess_id,
            segment_id=self.segment_id,
            size=os.path.getsize(filename),
            ctime=self.segment_start_time,
            duration=duration,
            resolution=(self.width, self.height),
            title=self.room_info['title'],
            streamer=self.streamer_info,
            taskname=self.taskname,
        )

        max_fn_length = self.advanced_video_args.get('max_fn_length', 80)
        raw_filename = replace_keywords(self.output_name, video_info, replace_invalid=True)[:max_fn_length]

        newfile = join(self.output_dir, raw_filename+'.'+self.output_format)
        _file = rename_safe(filename, newfile)
        if _file:
            newfile = _file
            self.logger.debug(f'Rename video file {filename} to {newfile}.')
        else:
            newfile = filename
            self.logger.error(f'视频 {newfile} 分段失败，将使用默认名称 {filename}.')
            
        if self.danmaku:
            newdmfile = splitext(newfile)[0]+'.'+self.kwargs.get('dm_format', 'ass')
            # ``dmw.split(newdmfile)`` 会把**当前这一段自己的**弹幕文件改名为 ``newdmfile``
            # （该段的起止与视频分段是同一段），随后才为**下一段**新建一个
            # ``[正在录制]...Part%03d.ass``。也就是说：被改名的不是"上一段"，登记的
            # 也不是"下一段" —— 分段序号与弹幕文件是**配对**的。
            # 依据：``DanmakuDownloader.split()``（先 open 新文件、再 rename ``old_dm_file``），
            # 且录直播时 ``self_segment=False``、不存在内部 monitor 线程，改名只发生在这里。
            #
            # 因此 ``dm_file_id`` 必须记**该段自己的**弹幕文件，而且要用 split 返回的
            # **实际落盘路径**：改名失败时（例如目标名已存在）弹幕会留在
            # ``[正在录制]`` 原名下，此时若仍记 ``newdmfile`` 就会指向其他段落的文件
            # 或一个不存在的路径，渲染（``dmrender`` 会回落到 ``video.dm_file_id``）
            # 与对账都会出错。
            dm_file = None
            try:
                dm_file = self.dmw.split(newdmfile)
            except Exception as e:
                self.logger.warning(f'弹幕分段失败，本轮不登记弹幕文件：{e}')
            newdmfile = dm_file or None
        else:
            newdmfile = None
        
        video_info.path = newfile
        video_info.dm_file_id = newdmfile
        if self.advanced_video_args.get('group_id'):
            group_id = str(self.advanced_video_args['group_id'])
            group_id = replace_keywords(group_id, video_info)
            video_info.upload_group_id = group_id

        min_video_size = self.advanced_video_args.get('min_video_size')
        min_video_duration = self.advanced_video_args.get('min_video_duration')
        if (min_video_size and video_info.size < min_video_size *1024*1024) \
            or (min_video_duration and video_info.duration < min_video_duration):
            self.logger.info(f'视频 {video_info.path} 过小, 设置 {min_video_size}MB {min_video_duration}s,'
                             f'实际 {video_info.size/1024/1024:.2f}MB {video_info.duration}s')
            if exists(video_info.path):
                os.remove(video_info.path)
            if video_info.dm_file_id and exists(video_info.dm_file_id):
                os.remove(video_info.dm_file_id)
            self.segment_start_time = datetime.now()
            return

        self._pipeSend(event='livesegment', msg=f'视频分段 {newfile} 录制完成.', target=f'replay/{self.taskname}', dtype='VideoInfo', data=video_info)
        # 登记到状态库：文件已封闭，可以安全记录
        self._record_segment(video_info)
        new_room_info = retry_safe(self.liveapi.GetRoomInfo)
        if new_room_info:
            self.room_info = new_room_info
        self.segment_start_time = datetime.now()
        self.segment_id += 1

    def start_once(self):
        self.stoped = False
        
        # init segment info
        self.room_info = retry_safe(self.liveapi.GetRoomInfo)
        self.streamer_info = retry_safe(self.liveapi.GetStreamerInfo)
        if not(self.room_info and self.streamer_info):
            raise RuntimeError(f'{self.taskname}: 获取主播信息出现错误.')
        
        # 登记录制场次（含主播/房间元信息）。必须放在这里而不是 start_helper()：
        # 房间信息此时才拿到，而登记需要写入这些元信息。
        # 幂等 —— 同一个 sess_id 在一次 start/stop 循环中只登记一次。
        if getattr(self, '_registered_sess_id', None) != self.sess_id:
            self._register_session()
            self._registered_sess_id = self.sess_id

        self.segment_start_time = datetime.now()
        os.makedirs(self.output_dir,exist_ok=True)
        
        stream_url = self.liveapi.GetStreamURL(**self.stream_option)
        stream_request_header = self.liveapi.GetStreamHeader()
        width, height = FFprobe.get_resolution(stream_url, stream_request_header)
        # 斗鱼和虎牙的直播地址只能用一次，所以要重新获取
        if self.plat == 'douyu' or self.plat == 'huya':
            stream_url = self.liveapi.GetStreamURL(**self.stream_option)

        this_engine = self.engine
        if this_engine == 'auto':
            # B站规则：带有bluray的hls流使用pyrequests，普通的hls流使用ffmpeg，flv流使用streamgears
            if self.plat == 'bilibili':
                if re.search(r'live_\d+_[a-zA-Z_]{0,10}\d+_[a-zA-Z]{1,10}', stream_url)\
                    and '.m3u8' in stream_url:
                    this_engine = 'ffmpeg'          # pyrequests强制原画可用率不高，改回ffmpeg
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

        if this_engine == 'ffmpeg':
            from .ffmpeg import FFmpegDownloader
            downloader_class = FFmpegDownloader
        elif this_engine == 'streamgears':
            from .streamgears import StreamgearsDownloader
            downloader_class = StreamgearsDownloader
        elif this_engine == 'streamlink':
            from .streamlink import StreamlinkDownloader
            downloader_class = StreamlinkDownloader
        elif this_engine == 'pyrequests':
            from .pyrequests import PyRequestsDownloader
            downloader_class = PyRequestsDownloader
        else: 
            raise NotImplementedError(f'No Downloader Named {this_engine}.')

        if not (width and height):
            default_resolution = self.advanced_video_args.get('default_resolution', (1920, 1080))
            self.logger.warning(f'无法获取视频大小，使用默认值 {default_resolution}.')
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
                inprogress_callback=self.inprogress_callback,
                debug=self.debug,
                **self.kwargs
            )
            self.downloader.start()

        self.executor = ThreadPoolExecutor(max_workers=int(self.danmaku) + int(self.video))
        futures = []
        if self.danmaku:
            futures.append(self.executor.submit(danmaku_thread))
        if self.video:
            futures.append(self.executor.submit(video_thread))
        
        while not self.stoped:
            try:
                for future in as_completed(futures, timeout=60):
                    try:
                        return future.result()
                    except TimeoutError as e:           # 捕获内部的超时，避免死循环
                        raise RuntimeError(f'{self.taskname} 录制异常退出: {e}') from e
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
        restart_interval = self.advanced_video_args.get('restart_interval', (0, 10, 60))  # 重启间隔时间
        if isinstance(restart_interval, (int, float)):
            restart_interval_min = restart_interval_step = restart_interval_max = restart_interval
        else:
            restart_interval_min, restart_interval_step, restart_interval_max = 0, 10, 60
        start_check_interval = self.advanced_video_args.get('start_check_interval', 60)  # 开播检测时间
        stop_check_interval = self.advanced_video_args.get('stop_check_interval', 30)   # 下播检测间隔
        
        self.sess_id = uuid(8)
        self.segment_id = 1
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
                    self._on_live_end()             # 标记场次结束，供对账回收
                    self.sess_id = uuid(8)          # 每场直播结束后重新分配session id
                    self.segment_id = 1
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
                    time.sleep(min(restart_interval_min + restart_interval_step * restart_cnt, restart_interval_max))
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
        # 主动停止也算场次结束，避免该场次在状态库里永久停留在"进行中"
        if hasattr(self, 'sess_id'):
            self._on_live_end()
        self._pipeSend('livestop', '录制终止', dtype='str', data=self.sess_id if hasattr(self, 'sess_id') else None)

    def stop_once(self):
        self.stoped = True
        if self.video and hasattr(self, 'downloader'):
            try:
                self.downloader.stop()
            except Exception as e:
                self.logger.exception(e)
        if self.danmaku and hasattr(self, 'dmw') and self.dmw:
            try:
                self.dmw.stop()
            except Exception as e:
                self.logger.exception(e)
        try:
            if hasattr(self, 'executor'):
                self.executor.shutdown(wait=False)
        except Exception as e:
            self.logger.exception(e)
