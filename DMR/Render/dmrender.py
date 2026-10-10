import copy
import logging
import os
import platform
import tempfile

from .baserender import BaseRender
from .ffmpeg import RawFFmpegRender
from os.path import exists, splitext
from DMR.utils import *

class DmRender(BaseRender):
    def __init__(self,
                 hwaccel_args: list,
                 vencoder: str,
                 vencoder_args: list,
                 aencoder: str,
                 aencoder_args: list,
                 output_resize: str,
                 advanced_render_args: dict=None,
                 dmconvert: dict=None,
                 ffmpeg: str = None,
                 debug=False,
                 **kwargs
                 ):
        self.hwaccel_args = hwaccel_args if hwaccel_args is not None else []
        self.vencoder = vencoder
        self.vencoder_args = vencoder_args
        self.aencoder = aencoder
        self.aencoder_args = aencoder_args
        self.output_resize = output_resize
        self.advanced_render_args = advanced_render_args if isinstance(advanced_render_args, dict) else {}
        # XML 弹幕转换参数（见 DMR/Config/default.yml 的 render_args.dmrender.dmconvert）
        self.dmconvert = dmconvert if isinstance(dmconvert, dict) else {}
        self.ffmpeg = ffmpeg if ffmpeg else ToolsList.get('ffmpeg')
        self.debug = debug

        self.logger = logging.getLogger(__name__)
        self.raw_ffmpeg = RawFFmpegRender(debug=self.debug)

    def _video_resolution(self, video: str) -> tuple:
        """探测视频分辨率，供 XML→ASS 转换使用（ASS 的坐标基准）。"""
        w, h = FFprobe.get_resolution(video)
        if not (w and h):
            self.logger.warning(f'获取视频 {video} 分辨率失败, XML 弹幕转换将使用默认分辨率 1920x1080.')
            w, h = 1920, 1080
        return w, h

    def _prepare_danmaku(self, video: str, danmaku: str) -> tuple:
        """把弹幕准备成 ffmpeg ``subtitles`` 滤镜能吃的格式。

        本程序自己录制的弹幕已经是 ``.ass``，直接返回；外部来源的 ``.xml``
        （B站录播最常见的格式）先转换成 ``.ass``。

        :returns: ``(可渲染的弹幕路径, 需要清理的临时文件路径或 None)``
        """
        if not is_danmaku_xml(danmaku):
            return danmaku, None

        resolution_x, resolution_y = self._video_resolution(video)
        # 配置项与上游库参数名一致（font_name/font_size/displayarea/...），
        # 只把分辨率换成探测到的真实值；未在配置里写的键用 xml2ass 的默认值。
        args = dict(self.dmconvert)
        args['resolution_x'] = args.get('resolution_x') or resolution_x
        args['resolution_y'] = args.get('resolution_y') or resolution_y

        # 写进临时文件而不是 XML 旁边：渲染可能对源目录只读，且避免污染用户文件。
        # 放在输出目录同级优先，便于与产物同盘；失败则退回系统临时目录。
        fd, ass_file = tempfile.mkstemp(
            prefix=f'.{os.path.basename(splitext(danmaku)[0])}.',
            suffix=f'.{DEFAULT_ASS_SUFFIX}',
            dir=self._temp_dir_for(video),
        )
        os.close(fd)          # 只要名字，交给 dmconvert 写入

        self.logger.info(f'检测到 XML 弹幕，正在转换为 ASS: {danmaku}')
        try:
            xml_to_ass(danmaku, ass_file, args=args)
        except Exception:
            self._remove_quietly(ass_file)
            raise
        return ass_file, ass_file

    def _temp_dir_for(self, video: str) -> str:
        """选一个可写的临时目录：优先与视频同目录（同盘、便于排查），否则系统临时目录。"""
        for candidate in (os.path.dirname(os.path.abspath(video)), None):
            try:
                if candidate is None:
                    return tempfile.gettempdir()
                if os.access(candidate, os.W_OK):
                    return candidate
            except OSError:
                continue
        return tempfile.gettempdir()

    def _remove_quietly(self, path: str) -> None:
        if not path:
            return
        try:
            os.remove(path)
        except OSError as e:
            self.logger.debug(f'清理临时弹幕文件 {path} 失败: {e}')

    def render_helper(self, video: str, danmaku: str, output: str, to_stdout: bool = False, logfile=None):
        ffmpeg_args = [self.ffmpeg, '-y']
        ffmpeg_args += self.hwaccel_args

        if self.output_resize:
            if 'x' in str(self.output_resize):
                scale_args = ['-s', self.output_resize]
            else:
                w, h = FFprobe.get_resolution(video)
                if not (h and w):
                    self.logger.warning(f'获取视频 {video} 分辨率失败, 将使用默认分辨率 1920x1080.')
                    w, h = 1920, 1080
                scale = float(self.output_resize)
                w, h = int(w*scale), int(h*scale)
                scale_args = ['-s', f'{w}x{h}']
        else:
            scale_args = ['-noautoscale']

        if platform.system().lower() == 'windows':
            danmaku = danmaku.replace("\\", "/").replace(":/", "\\:/")
        
        # 自定义video filter
        if self.advanced_render_args.get('filter_complex'):
            filter_name = '-filter_complex'
            filter_str = self.advanced_render_args.get('filter_complex')
            filter_str = replace_keywords(filter_str, {'danmaku': danmaku})
        else:
            filter_name = '-vf'
            filter_str = 'subtitles=filename=\'%s\'' % danmaku
        
        ffmpeg_args += [
            '-fflags', '+discardcorrupt+genpts',
            '-analyzeduration', '2147483647', '-probesize', '2147483647',
            '-i', video,
            filter_name, filter_str,

            '-c:v', self.vencoder,
            *self.vencoder_args,
            '-c:a', self.aencoder,
            *self.aencoder_args,
            *scale_args,
            output,
        ]

        return self.raw_ffmpeg.call_ffmpeg(ffmpeg_args)

    def render_one(self, video: VideoInfo, output: str, **kwargs):
        if not exists(video.path):
            raise RuntimeError(f'不存在视频文件 {video.path}，跳过渲染.')
        danmaku = kwargs.get('danmaku') or video.dm_file_id
        if not danmaku or not exists(danmaku):
            raise RuntimeError(f'不存在弹幕文件 {danmaku}，跳过渲染.')

        valid_output = safe_filename(output)
        if valid_output != output:
            self.logger.warning(f'输出文件名 {output} 不合法或已存在，已更改为 {valid_output}.')
            output = valid_output   

        # XML 弹幕先转成 ASS（本程序自录的 .ass 会原样返回，临时文件为 None）
        danmaku, temp_danmaku = self._prepare_danmaku(video.path, danmaku)
        start_time = datetime.now()
        try:
            status, info = self.render_helper(video.path, danmaku, output, **kwargs)
        finally:
            # 必须等 ffmpeg 渲染结束才能删：subtitles 滤镜是在渲染期间读这个文件的
            self._remove_quietly(temp_danmaku)
        if status:
            output_info:VideoInfo = copy.deepcopy(video)
            output_info.dtype = 'dm_video'
            output_info.path = output
            output_info.file_id = uuid()
            output_info.size = os.path.getsize(output)
            output_info.ctime = start_time
            output_info.dm_file_id = None
            output_info.src_video_id = video.file_id
            return status, output_info
        else:
            return status, info

    def stop(self):
        self.logger.debug('ffmpeg render stop.')
        self.raw_ffmpeg.stop()
