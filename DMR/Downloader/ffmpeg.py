from datetime import datetime
from collections import deque
import subprocess
import sys
import threading
import time
import queue
import logging
from os.path import *

from DMR.utils import *

# 监控线程与主循环共用的行缓冲容量：既限制"待处理行"的积压，也限制"日志尾"的行数。
# 主循环每次只取一行，若子进程输出速率高于消费速率，无界缓冲会持续膨胀
# （实测可到数百 MB）。缓冲只用于判断近期状态，溢出时丢弃最旧的行。
MSG_QUEUE_MAXSIZE = 4096

class FFmpegDownloader():
    default_header = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'User-Agent': 'Mozilla/5.0 (Linux; Android 5.0; SM-G900P Build/LRX21T) AppleWebKit/537.36 '
                            '(KHTML, like Gecko) Chrome/75.0.3770.100 Mobile Safari/537.36 '
        }
    
    def __init__(self, 
                 stream_url:str, 
                 output_dir:str,
                 output_format:str,
                 taskname:str='',
                 segment:int=None,
                 header:dict=None,
                 ffmpeg:str=None,
                 segment_callback=None,
                 stable_callback=None,
                 inprogress_callback=None,
                 advanced_video_args:dict=None,
                 debug=False,
                 **kwargs):
        
        self.stream_url = stream_url
        self.output_dir = output_dir
        self.output_format = output_format
        self.header = header if header else self.default_header
        self.segment = segment
        self.debug = debug
        self.taskname = taskname
        self.segment_callback = segment_callback
        self.stable_callback = stable_callback
        # 上报"正在写入"的文件，使录制中途被强杀后残file能被对账发现
        self.inprogress_callback = inprogress_callback
        self.advanced_video_args = advanced_video_args if advanced_video_args else {}
        self.kwargs = kwargs
        self.ffmpeg = ffmpeg if ffmpeg else ToolsList.get('ffmpeg')
        self.logger = logging.getLogger(__name__)
        
        self.ffmpeg_proc = None
        self._init_line_buffer()
        self.stoped = False
    
    @property
    def duration(self):
        return datetime.now().timestamp() - self.start_time

    def _init_line_buffer(self):
        """监控线程与主循环共用的行缓冲（单一数据源）。

        ``_lines``：待主循环处理的行（FIFO，主循环每次取一行）。
        ``_log_lines``：同样的行，用于超时/出错时报出最近日志。
        两者都是 ``deque(maxlen=MSG_QUEUE_MAXSIZE)``，因此行数与内存都有硬上界；
        主循环每处理完一行就从 ``_log_lines`` 里删掉它，使日志尾始终只覆盖
        "尚未处理完"的那一段。
        """
        self._lines = deque(maxlen=MSG_QUEUE_MAXSIZE)
        self._log_lines = deque(maxlen=MSG_QUEUE_MAXSIZE)
        # 监控线程累计读到的行数（含 [hls 行）。主循环用它判定"窗口内是否有输出"，
        # 这比"看日志是否为空/是否含 info 行"可靠：只要 ffmpeg 还在吐东西，
        # 无论吐的是进度行还是 HLS 解复用行，都不应该被判定为管道故障。
        self._received_lines = 0

    def _append_line(self, line:str):
        """由监控线程调用：入待处理队列，同时记为日志尾。

        注意：**不过滤 `[hls` 行**。这类行（``[hls @ ...] Skip(...)`` /
        ``Opening '...m4s'``）同样证明 ffmpeg 正在正常输出，早期把它们排除在
        ``log`` 之外会导致 HLS 起流/切流的那十几秒里 ``log`` 为空，从而被误判成
        "管道读取错误"并白白重试一次。
        """
        self._lines.append(line)
        self._log_lines.append(line)
        # 单调递增的累计计数：主循环用它判断"这个 15 秒窗口内到底有没有收到输出"。
        self._received_lines += 1

    def _drain_line(self):
        """由主循环调用：取出一行并把它从日志尾移除；缓冲为空返回 ``None``。"""
        try:
            line = self._lines.popleft()
        except IndexError:
            return None
        try:
            self._log_lines.remove(line)
        except ValueError:      # 溢出时该行可能已被丢弃
            pass
        return line

    def _log(self):
        """最近尚未处理完的行，作为报错上下文。"""
        return '\n'.join(self._log_lines)

    def _close_proc_pipes(self):
        """kill 之后主动关闭管道：communicate 未能正常收尾时管道会一直挂着。"""
        for stream in (getattr(self.ffmpeg_proc, 'stdout', None), getattr(self.ffmpeg_proc, 'stdin', None)):
            try:
                if stream is not None:
                    stream.close()
            except Exception:
                pass

    def start_ffmpeg(self):
        ffmpeg_stream_args = self.advanced_video_args.get('ffmpeg_stream_args', 
                                                          [ '-rw_timeout','10000000',
                                                            '-analyzeduration','15000000',
                                                            '-probesize','50000000',
                                                            '-thread_queue_size', '16'])
        ffmpeg_args = [
            self.ffmpeg, '-y',
            '-headers', ''.join('%s: %s\r\n' % x for x in self.header.items()),
            *ffmpeg_stream_args,
            '-i', self.stream_url,
            '-c', 'copy'
        ]

        ffmpeg_output_args = self.advanced_video_args.get('ffmpeg_output_args', 
                                                          [ '-movflags','faststart+frag_keyframe+empty_moov'])
        if self.segment:
            ffmpeg_args += ['-f','segment',
                            '-segment_time',str(self.segment),
                            '-reset_timestamps','1',
                            *ffmpeg_output_args,
                            self.raw_name]
        else:
            ffmpeg_args += [*ffmpeg_output_args,
                            self.raw_name]

        
        self.logger.debug('FFmpegDownloader args:')
        self.logger.debug(ffmpeg_args)

        # 每次启动都重置，避免复用同一个实例时残留上一次的缓冲
        self._init_line_buffer()

        if self.debug:
            self.ffmpeg_proc = subprocess.Popen(ffmpeg_args, stdin=subprocess.PIPE, stdout=sys.stdout, stderr=subprocess.STDOUT, bufsize=1, universal_newlines=True, encoding='utf-8', errors='ignore')
        else:
            # bufsize 用行缓冲：下方是按行 readline() 消费的，行缓冲既够用又不会像
            # bufsize=10**8 那样为每个子进程预留上百 MB 的缓冲区内存。
            self.ffmpeg_proc = subprocess.Popen(ffmpeg_args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1, universal_newlines=True, encoding='utf-8', errors='ignore')

        def ffmpeg_monitor():
            while not self.stoped:
                if self.ffmpeg_proc.stdout is None:
                    break
                line = self.ffmpeg_proc.stdout.readline().strip()
                # 空行意味着管道已 EOF（子进程退出）：必须退出循环。
                # 否则 readline() 会一直立刻返回空串，线程空转吃满一个 CPU 核。
                if len(line) == 0:
                    break
                self._append_line(line)

        if self.ffmpeg_proc.stdout is not None:
            self.ffmpeg_monitor_proc = threading.Thread(target=ffmpeg_monitor, daemon=True)
            self.ffmpeg_monitor_proc.start()

        return self._lines
    
    @staticmethod
    def _is_info_line(line:str) -> bool:
        """是否为 ffmpeg 的进度行（用于慢速判定）。"""
        return bool(line.startswith('frame=') or line.startswith('size=') or 'time=' in line)

    def _handle_line(self, line:str, ffmpeg_low_speed:int) -> int:
        """处理一行 ffmpeg 输出。

        :returns: 更新后的 ``ffmpeg_low_speed``
        """
        if self._is_info_line(line):
            if not self.advanced_video_args.get('disable_lowspeed_interrupt'):
                l = line.find('speed=')
                r = line.find('x', l)
                if l > 0 and r > 0:
                    speed = float(line[l:r][6:])
                    if speed < 0.8:
                        ffmpeg_low_speed += 1
                        if ffmpeg_low_speed % 5 == 3:
                            self.logger.warn(f'{self.taskname} 直播流下载速度过慢, 请保证网络带宽充足.')
                        if ffmpeg_low_speed >= 15:
                            self.logger.debug(self._log())
                            raise RuntimeError(f'{self.taskname} 下载速度过慢, 即将重试.')
                    else:
                        ffmpeg_low_speed = 0

                    if not self.download_stable:
                        if speed and speed < 2:
                            l = line.find('time=')
                            r = line.find('bitrate') - 1
                            if l > 0 and r > 0:
                                downloaded_duration = line[l+5:r]
                            try:
                                h, m, s = int(downloaded_duration.split(':')[0]), int(downloaded_duration.split(':')[0]), float(downloaded_duration.split(':')[2])
                                downloaded_duration_ms = h * 3600 + m * 60 + s
                                time_error = downloaded_duration_ms - datetime.now().timestamp() + self.start_time + (speed - 1)
                                self.stable_callback(time_error)
                                self.download_stable = True
                            except Exception as e:
                                self.logger.debug(e)
                                self.download_stable = False

        if 'Opening' in line:
            fname = line.split('\'')[1]
            if not fname.startswith('http'):
                if self.thisfile:
                    self.segment_callback(self.thisfile)
                self.thisfile = fname
                # 新分段开始写入 —— 立即上报，使中途被杀时该文件有记录
                if self.inprogress_callback:
                    self.inprogress_callback(fname)

        if 'dropping it' in line or 'Invalid NAL unit size' in line:
            self.logger.debug(self._log())
            raise RuntimeError(f'{self.taskname} 直播流读取错误, 即将重试, 如果此问题多次出现请反馈.')

        return ffmpeg_low_speed

    def _check_window_alive(self, window_baseline:int) -> int:
        """结束一个 15 秒窗口时判断"这段时间到底有没有收到 ffmpeg 输出"。

        :param window_baseline: 本窗口开始时 ``_received_lines`` 的值。
        :returns: 下一个窗口的基线。
        :raises RuntimeError: 整个窗口一条输出都没有 —— 这才可能是管道/子进程故障。

        关键：判据是"**有没有任何**输出"，不是"日志是否为空"、也不是"日志里有没有
        进度行"。HLS 流在起流与切流期间可能十几秒只打 ``[hls @ ...] Skip(...)`` 与
        ``Opening '...m4s'`` 这类解复用行；若把它们排除在日志之外，就会误判成
        "管道读取错误"并白白重试一次。
        """
        if self._received_lines == window_baseline:
            raise RuntimeError(
                f'{self.taskname} 15 秒内未收到任何 ffmpeg 输出, 即将重试.')
        return self._received_lines

    def start_helper(self):
        self.stoped = False
        self.raw_name = join(self.output_dir, f'[正在录制]{self.taskname}-{time.strftime("%Y%m%d-%H%M%S",time.localtime())}-Part%03d.{self.output_format}')
        self.start_time = datetime.now().timestamp()
        self._timer_cnt = 1
        self.thisfile = None

        ffmpeg_low_speed = 0

        self.start_ffmpeg()

        self.download_stable = False # stable ffmpeg speed < 2
        # 当前 15 秒窗口开始时的累计行数；用于判断窗口结束时"是否有任何输出"
        window_baseline = self._received_lines
        while not self.stoped:
            if self.ffmpeg_proc.poll() is not None:
                self.logger.debug('FFmpeg exit.')
                self.logger.debug(self._log())
                raise RuntimeError(f'FFmpeg 退出.')
            
            if self.debug:
                time.sleep(1)
                continue
            
            line = self._drain_line()
            if line is None:
                line = ''
                time.sleep(1)
            
            ffmpeg_low_speed = self._handle_line(line, ffmpeg_low_speed)

            if self.start_time is not None and self.duration > self._timer_cnt*15:
                # 15 秒窗口内一条输出都没有才会重试；只要有输出（哪怕只是
                # [hls @ ...] 这类解复用行）就放行 —— 详见 _check_window_alive。
                window_baseline = self._check_window_alive(window_baseline)
                self._timer_cnt += 1

    def start(self):
        return self.start_helper()

    def stop(self):
        if self.stoped:
            return
        self.stoped = True
        if self.ffmpeg_proc is None:
            self.logger.debug('ffmpeg downloader stoped.')
            return
        # 把尚未处理的输出一起打进日志（缓冲有上界，不会无限增长）
        if self._log_lines:
            self.logger.debug(f'{self.taskname} ffmpeg: ' + self._log())
            
        try:
            out, _ = self.ffmpeg_proc.communicate('q',timeout=3)
            if out:
                self.logger.debug(f'ffmpeg out: {out[-MSG_QUEUE_MAXSIZE*128:]}.')
        except Exception as e:
            self.ffmpeg_proc.kill()
            self._close_proc_pipes()
            self.logger.debug(e)
        
        if self.thisfile:
            time.sleep(1)
            self.segment_callback(self.thisfile)
        self.logger.debug('ffmpeg downloader stoped.')
