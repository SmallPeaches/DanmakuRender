import logging
import random
import subprocess
import re
import glob

from datetime import datetime
from os.path import splitext, split, join, exists
import tempfile
import time

from DMR.utils import *
from DMR.LiveAPI import Onair


class StreamlinkDownloader():
    def __init__(self,  
                 output_dir:str,
                 segment:int,
                 url:str,
                 taskname:str,
                 output_format:str,
                 debug=False,
                 segment_callback=None,
                 **kwargs):
        
        self.output_dir = output_dir
        self.output_format = output_format
        self.segment = segment
        self.debug = debug
        self.taskname = taskname
        self.url = url
        self.segment_callback = segment_callback
        self.kwargs = kwargs

        self.advanced_video_args = kwargs.get('advanced_video_args', {})
        self.logger = logging.getLogger(__name__)
        self.stoped = False
    
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
                    logfile.seek(0)
                    stdout = logfile.read().decode('utf8', errors='ignore')
                    if re.findall(r'http://\d+\.\d+\.\d+\.\d+:'+str(port), stdout):
                        streamlink_ok = True
                        break
                except Exception as e:
                    pass
                time.sleep(1)
            if not streamlink_ok:
                logfile.seek(0)
                log = logfile.read().decode('utf8', errors='ignore')
                raise RuntimeError(f'{self.taskname} Streamlink启动失败: {log}')
            
            self.ffmpeg_proc = subprocess.Popen(ffmpeg_args, stdin=subprocess.PIPE, stdout=logfile, stderr=subprocess.STDOUT)
            self.lastfile = None
            while not self.stoped:
                if self.streamlink_proc.poll() is not None or self.ffmpeg_proc.poll() is not None:
                    self.logger.debug(f'{self.taskname} Streamlink return {self.streamlink_proc.returncode}, ffmpeg return {self.ffmpeg_proc.returncode}')
                    break

                files = sorted(glob.glob(join(self.output_dir, f'*{self.uuid}*')))
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
                logfile.seek(0)
                log = logfile.read().decode('utf8', errors='ignore')
                raise RuntimeError(f'{self.taskname} Streamlink 异常退出 {log[-1000:]}.')

    def start(self):
        # 生成一个uuid，用于标记这次录制的文件
        self.uuid = uuid(8)
        return self.start_helper()
    
    def stop(self):
        self.stoped = True
        try:
            self.streamlink_proc.kill()
            self.ffmpeg_proc.kill()
        except Exception as e:
            self.logger.debug(e)
        finally:
            out, _ = self.streamlink_proc.communicate(timeout=0.1)
            if out: 
                self.logger.debug(f'{self.taskname} streamlink: {out}')
            out, _ = self.ffmpeg_proc.communicate(timeout=0.1)
            if out: 
                self.logger.debug(f'{self.taskname} streamlink: {out}')

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