import logging
import random
import subprocess
import re
import glob

from datetime import datetime
from os.path import splitext, split, join, exists, getsize
import tempfile
import time

from DMR.utils import *
from DMR.LiveAPI import Onair

# 这个临时文件同时承接 streamlink 与 ffmpeg 的输出，长时间录制会持续增长，
# 而实际只用得上"启动时是否打印了监听地址"与"异常退出时的最近错误"，
# 因此每次只读限定大小的一段。
LOG_TAIL_BYTES = 64 * 1024


def read_logfile_tail(logfile, maxbytes=LOG_TAIL_BYTES, from_start=False):
    """读取临时日志文件，最多 ``maxbytes`` 字节。

    :param from_start: 从文件开头读（启动阶段文件还很小，端口行在最前面，
        必须从头读才能看到）；否则只读**尾部** ``maxbytes``，用于异常退出时
        取最近的错误信息。
    """
    if from_start:
        offset = 0
    else:
        try:
            offset = max(0, getsize(logfile.name) - maxbytes)
        except OSError:
            offset = 0
    logfile.seek(offset)
    data = logfile.read(maxbytes)
    if isinstance(data, str):       # 文本模式打开时已经是 str
        return data
    return data.decode('utf8', errors='ignore')


class StreamlinkDownloader():
    def __init__(self,  
                 output_dir:str,
                 segment:int,
                 url:str,
                 taskname:str,
                 output_format:str,
                 debug=False,
                 segment_callback=None,
                 inprogress_callback=None,
                 **kwargs):
        
        self.output_dir = output_dir
        self.output_format = output_format
        self.segment = segment
        self.debug = debug
        self.taskname = taskname
        self.url = url
        self.segment_callback = segment_callback
        # 上报"正在写入"的文件，使录制中途被强杀后残file能被对账发现
        self.inprogress_callback = inprogress_callback
        self.kwargs = kwargs

        self.advanced_video_args = kwargs.get('advanced_video_args', {})
        self.logger = logging.getLogger(__name__)
        self.stoped = False
        # 这些属性原先只在 start()/start_helper() 里赋值，若 start 在起进程前就失败，
        # stop() 会抛 AttributeError 而漏掉子进程清理，这里先给出默认值。
        self.uuid = None
        self.streamlink_proc = None
        self.ffmpeg_proc = None
        self.lastfile = None
        # 上次上报为"进行中"的文件（与 lastfile 语义不同：那个是"上次已封闭的分段"）。
        # 循环开始时也会重置，放在这里是为了让"判重状态"在实例上可见、可测。
        self._last_reported = None
    
    def start_helper(self):
        raw_name = join(self.output_dir, f'[正在录制]{self.taskname}-{time.strftime("%Y%m%d%H%M%S",time.localtime())}-Part%03d-{self.uuid}.{self.output_format}')

        port = random.randint(10000, 65535)
        streamlink_extra_args = self.advanced_video_args.get('streamlink_extra_args') or []
        streamlink_quality = self.advanced_video_args.get('streamlink_quality') or 'best'
        streamlink_args = [
            "streamlink",
            "--player-external-http",  # 为外部程序提供流媒体数据
            "--player-external-http-port", str(port),  # 对外部输出流的端口
            *streamlink_extra_args,
            self.url,
            streamlink_quality,
        ]
        self.logger.debug(f'{self.taskname} streamlink args: {streamlink_args}')

        ffmpeg_args = [
            ToolsList.get('ffmpeg'),
            "-i", f"http://localhost:{port}",
            "-c", "copy",
        ]
        if self.segment:
            ffmpeg_args += ['-f','segment',
                            '-segment_time',str(self.segment),
                            '-reset_timestamps','1',
                            raw_name]
        else:
            ffmpeg_args += [raw_name]
        self.logger.debug(f'{self.taskname} ffmpeg args: {ffmpeg_args}')

        with tempfile.TemporaryFile(dir='.temp') as logfile:
            self.streamlink_proc = subprocess.Popen(streamlink_args, stdin=subprocess.PIPE, stdout=logfile, stderr=subprocess.STDOUT)
            # 等待streamlink流开始
            streamlink_ok = False
            for _ in range(60):
                try:
                    # 只读限定大小的片段并检查其中的端口行：这个文件是 streamlink 与
                    # ffmpeg 共用的输出，长时间录制会持续增长，整体 read() 会把整个
                    # 文件读进内存。启动阶段文件很小，从头读以确保不漏掉端口行。
                    stdout = read_logfile_tail(logfile, from_start=True)
                    if re.findall(r'http://\d+\.\d+\.\d+\.\d+:'+str(port), stdout):
                        streamlink_ok = True
                        break
                except Exception as e:
                    pass
                time.sleep(1)
            if not streamlink_ok:
                raise RuntimeError(f'{self.taskname} Streamlink启动失败: {read_logfile_tail(logfile)}')
            
            self.ffmpeg_proc = subprocess.Popen(ffmpeg_args, stdin=subprocess.PIPE, stdout=logfile, stderr=subprocess.STDOUT)
            self.lastfile = None
            # 单独记录"上次上报为进行中"的文件。
            # ⚠️ 不能拿 self.lastfile 当这个判据：它表示"上次已**封闭**并回调的分段"，
            #    总是比正在写入的那个更旧。两者不等时，同一个最新文件会在每轮轮询里
            #    被重复上报（实测 Part001/Part003 各被上报 2 次），下游就会反复打出
            #    "已登记进行中的分段 N：<同一文件>"并重复写状态库。
            self._last_reported = None
            while not self.stoped:
                if self.streamlink_proc.poll() is not None or self.ffmpeg_proc.poll() is not None:
                    self.logger.debug(f'{self.taskname} Streamlink return {self.streamlink_proc.returncode}, ffmpeg return {self.ffmpeg_proc.returncode}')
                    break

                files = sorted(glob.glob(join(self.output_dir, f'*{self.uuid}*')))
                # 列表最后一个文件是正在写入、尚未封闭的分段，上报它使中途被杀的
                # 残file有记录（仅在变化时上报，避免重复写库）
                if files and files[-1] != self._last_reported and self.inprogress_callback:
                    self._last_reported = files[-1]
                    self.inprogress_callback(files[-1])
                try:
                    pos = files.index(self.lastfile)
                except ValueError:
                    pos = -1
                # 最后一个文件是正在录制的不能认为是录制好的，这里要-2
                if pos < len(files)-2:
                    for p in range(pos+1, len(files)-1):
                        self.lastfile = files[p]
                        self.segment_callback(self.lastfile)
                time.sleep(10)
            
            if not self.stoped and Onair(self.url):
                raise RuntimeError(f'{self.taskname} Streamlink 异常退出 {read_logfile_tail(logfile)[-1000:]}.')

    def start(self):
        # 生成一个uuid，用于标记这次录制的文件
        self.uuid = uuid(8)
        return self.start_helper()
    
    def stop(self):
        self.stoped = True
        # 进程可能还没起来（start 在 Popen 之前就失败了），逐个判断，避免
        # 前一个进程的异常导致后面的进程得不到清理而残留。
        for name, proc in (('streamlink', self.streamlink_proc), ('ffmpeg', self.ffmpeg_proc)):
            if proc is None:
                continue
            try:
                proc.kill()
                out, _ = proc.communicate(timeout=0.1)
                if out:
                    self.logger.debug(f'{self.taskname} {name}: {out}')
            except Exception as e:
                self.logger.debug(e)

        if self.uuid is None:
            self.logger.debug('Streamlink downloader stoped.')
            return

        files = sorted(glob.glob(join(self.output_dir, f'*{self.uuid}*')))
        try:
            pos = files.index(self.lastfile)
        except ValueError:
            pos = -1
        # 结束时最后一个文件也要算在内
        if pos < len(files)-1:
            for p in range(pos+1, len(files)):
                self.lastfile = files[p]
                self.segment_callback(self.lastfile)
        
        self.logger.debug('Streamlink downloader stoped.')