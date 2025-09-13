import logging
import queue
import subprocess
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, wait, ALL_COMPLETED

from DMR.utils import ToolsList


class StreamlinkSyncDownloader():
    def __init__(self,  
                 segment:int,
                 url:str,
                 taskname:str,
                 segment_callback=None,
                 **kwargs):

        self.segment = segment
        self.taskname = taskname
        self.url = url
        self.segment_callback = segment_callback
        self.kwargs = kwargs

        self.advanced_video_args = kwargs.get('advanced_video_args', {})
        self.logger = logging.getLogger(__name__)
        self.read_block_size = 256*1024
        self.pool = None
        self.futures = deque(maxlen=2)
        self.stoped = False
    
    def start_helper(self):
        self.logger.info(f'{self.taskname} 同步录制开始.')
        streamlink_extra_args = self.advanced_video_args.get('streamlink_extra_args') or []
        streamlink_extra_args = self.advanced_video_args.get('streamlink_extra_args') or []
        streamlink_quality = self.advanced_video_args.get('streamlink_quality') or 'best'
        streamlink_args = [
            "streamlink",
            *streamlink_extra_args,
            '-O',
            self.url,
            streamlink_quality,
        ]
        self.logger.debug(f'{self.taskname} streamlink args: {streamlink_args}')

        ffmpeg_args = [
            ToolsList.get('ffmpeg'),
            "-fflags", "+genpts",
            "-i", 'pipe:0',
            "-c:v", "copy",
            "-c:a", "copy",
            "-reset_timestamps", "1",
            "-avoid_negative_ts", "1",
            "-movflags", "+frag_keyframe+empty_moov",
            "-f", "flv",
            "-",
        ]
        self.logger.debug(f'{self.taskname} ffmpeg args: {ffmpeg_args}')
        wait_to_stop = False

        with subprocess.Popen(streamlink_args, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as streamlink_proc:
            with subprocess.Popen(ffmpeg_args, stdin=streamlink_proc.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as ffmpeg_proc:
                # 读取第一个数据
                data = ffmpeg_proc.stdout.read(self.read_block_size)
                if not data:  # 如果第一个数据为空
                    self.logger.error(f"{self.taskname}: ffmpeg启动失败")
                    streamlink_proc.kill()  # 终止 streamlink 进程
                    ffmpeg_proc.kill()  # 终止 ffmpeg 进程
                    # 打印错误输出
                    ffmpeg_err = ffmpeg_proc.stderr.read()
                    if ffmpeg_err:
                        self.logger.error(f"{self.taskname}: ffmpeg启动失败" + ffmpeg_err.decode("utf-8", errors="replace"))
                    streamlink_err = streamlink_proc.stderr.read()
                    if streamlink_err:
                        self.logger.error(f"{self.taskname}: streamlink启动失败" + ffmpeg_err.decode("utf-8", errors="replace"))
                    return False
                
                segment_start_time = time.time()
                video_queue = queue.SimpleQueue()
                self.segment_callback(video_queue)
                video_queue.put(data)  # 将第一个数据放入队列

                # 循环读取
                while not self.stoped:
                    data = ffmpeg_proc.stdout.read(self.read_block_size)
                    if not data:
                        self.logger.info(f"{self.taskname}: ffmpeg 进程结束")
                        ffmpeg_err = ffmpeg_proc.stderr.read()
                        if ffmpeg_err:
                            self.logger.debug(f"{self.taskname} ffmpeg: " + ffmpeg_err.decode("utf-8", errors="replace"))
                        streamlink_err = streamlink_proc.stderr.read()
                        if streamlink_err:
                            self.logger.debug(f"{self.taskname} streamlink: " + ffmpeg_err.decode("utf-8", errors="replace"))
                        break

                    if not wait_to_stop and time.time() - segment_start_time > self.segment - 10:
                        # 提前10秒准备下一个分片
                        future = self.pool.submit(self.start_helper)
                        self.futures.append(future)
                        wait_to_stop = True
                    elif wait_to_stop and time.time() - segment_start_time > self.segment:
                        self.logger.info(f"{self.taskname}: 分片录制完成")
                        break

                    if video_queue.qsize() * self.read_block_size > 10*1024*1024:
                        self.logger.error(f"{self.taskname}: 输出阻塞")
                        streamlink_proc.kill()
                        ffmpeg_proc.kill()
                        # 清空队列
                        try:
                            while video_queue.qsize() > 0:
                                video_queue.get_nowait()
                        except queue.Empty:
                            pass
                        break

                    video_queue.put(data)

                ffmpeg_proc.kill()
                streamlink_proc.kill()
                video_queue.put(None)
        return True

    def start(self):
        self.pool = ThreadPoolExecutor(max_workers=2)
        future = self.pool.submit(self.start_helper)
        self.futures.append(future)
        while not self.stoped and len(self.futures) > 0:
            future = self.futures.popleft()
            future.result()
    
    def stop(self):
        self.stoped = True
        self.logger.debug('Streamlink sync downloader stoped.')