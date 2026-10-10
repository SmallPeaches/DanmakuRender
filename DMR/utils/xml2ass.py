"""XML 弹幕（B站录制格式）→ ASS 弹幕转换器。

对 `DanmakuConvert <https://github.com/timerring/DanmakuConvert>`_（PyPI 包名
``dmconvert``）的封装，用于处理 **外部来源的 XML 弹幕**：

- 本程序自己录制的弹幕是直接写 ASS 的（``DMR/Downloader/Danmaku/asswriter.py``），
  不经过这里；
- 但 B站录播 / 第三方工具产出的弹幕常是 ``.xml``，需要先转成 ``.ass`` 才能交给
  ffmpeg 的 ``subtitles`` 滤镜渲染 —— 这正是本模块的用途。

参数与配置文件一致
------------------

所有参数默认值都对应 ``DMR/Config/default.yml`` 中
``render_args.dmrender.dmconvert`` 段，见 :data:`DEFAULT_DMCONVERT_ARGS`。
调用方（渲染器）通常把该段配置整体传进来，因此**改配置文件即可生效**。

关于 ``fontsize``
----------------
``dmconvert`` 的 ``fontsize`` 是**绝对像素值**，而 ``dmrender`` 在处理 ASS 时按
1080P 基准自适应缩放（``AssWriter.auto_fontsize``）。本模块不做缩放，需要其他
分辨率下的等效字号时请自行换算。

依赖说明
--------
``dmconvert`` 是**可选依赖**：只有真的要转换 XML 时才需要它。未安装时
:func:`xml_to_ass` 会抛出带安装提示的 :class:`RuntimeError`，不会影响 ASS 录制
与渲染等既有功能。
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from os.path import abspath, exists, join, splitext

__all__ = [
    'DEFAULT_DMCONVERT_ARGS',
    'Xml2AssArgs',
    'DEFAULT_XML_SUFFIX',
    'DEFAULT_ASS_SUFFIX',
    'DANMAKU_SUFFIXES',
    'default_ass_path',
    'find_danmaku_file',
    'is_danmaku_xml',
    'xml_to_ass',
]

logger = logging.getLogger(__name__)

#: 支持的弹幕文件后缀（不含点）。ASS 为渲染器原生格式，XML 需要先转换。
DEFAULT_XML_SUFFIX = 'xml'
DEFAULT_ASS_SUFFIX = 'ass'

#: 查找弹幕文件时按此顺序尝试：``.ass`` 是渲染器原生格式，优先使用；
#: ``.xml`` 是外部来源（B站录播、录播姬等）的格式，渲染时自动转换。
DANMAKU_SUFFIXES = (f'.{DEFAULT_ASS_SUFFIX}', f'.{DEFAULT_XML_SUFFIX}')

#: ``render_args.dmrender.dmconvert`` 的默认值，与 ``DMR/Config/default.yml`` 保持一致。
#: 键名即 ``dmconvert.convert_xml_to_ass`` 的位置参数名，便于直接展开调用。
DEFAULT_DMCONVERT_ARGS = {
    # 弹幕字体名，对应 default.yml 的 dm_font
    'font_name': 'Microsoft YaHei',
    # 弹幕字体大小（绝对像素），对应 default.yml 的 dm_fontsize
    'font_size': 36,
    # SuperChat / 礼物弹幕的字体大小（绝对像素）
    'sc_font_size': 36,
    # 分辨率；为 ~ 时由渲染器从视频探测（推荐），也可显式指定 1920x1080
    'resolution_x': None,
    'resolution_y': None,
    # 弹幕显示区域占屏幕高度的比例（0.00-1.00），对应 default.yml 的 dmrate
    'displayarea': 0.4,
    # 滚动弹幕显示时长（秒），对应 default.yml 的 dmduration
    'roll_time': 16.0,
    # 固定弹幕（顶部/底部）显示时长（秒）
    'fix_time': 5.0,
    # 不透明度（0.0-1.0），对应 default.yml 的 dm_opacity
    'opacity': 0.8,
    # 是否加粗，0 或 1
    'bold': 0,
    # 描边宽度，对应 default.yml 的 dm_outlinesize
    'outline': 1.0,
    # 阴影宽度
    'shadow': 0.0,
}

#: ``convert_xml_to_ass`` 的参数顺序（上游为位置参数，这里显式固定顺序）。
_FIELD_ORDER = (
    'font_name', 'font_size', 'sc_font_size', 'resolution_x', 'resolution_y',
    'displayarea', 'roll_time', 'fix_time', 'opacity', 'bold', 'outline', 'shadow',
)


@dataclass
class Xml2AssArgs:
    """一次 XML→ASS 转换的参数。

    默认值来自 :data:`DEFAULT_DMCONVERT_ARGS`。未显式给出的分辨率（``None``）
    必须由调用方探测视频后填入，否则转换会失败并给出明确原因。
    """
    font_name: str = 'Microsoft YaHei'
    font_size: int = 36
    sc_font_size: int = 36
    resolution_x: int = None
    resolution_y: int = None
    displayarea: float = 0.4
    roll_time: float = 16.0
    fix_time: float = 5.0
    opacity: float = 0.8
    bold: int = 0
    outline: float = 1.0
    shadow: float = 0.0

    @classmethod
    def from_dict(cls, args: dict = None) -> 'Xml2AssArgs':
        """从配置字典构造；**未知键会被忽略**（配置可以带注释以外的额外键）。

        仅接受 dataclass 已声明的字段，避免上游库改签名或用户写错键时
        ``TypeError`` 直接把渲染打断。
        """
        known = set(_FIELD_ORDER)
        values = {k: v for k, v in (args or {}).items() if k in known}
        return cls(**values)

    def as_call_args(self, xml_file: str, ass_file: str) -> tuple:
        """按上游库的位置参数顺序拼出调用元组。"""
        missing = [k for k in ('resolution_x', 'resolution_y') if not getattr(self, k)]
        if missing:
            raise ValueError(
                f'XML 弹幕转换缺少分辨率 {missing}：'
                f'请由调用方探测视频分辨率后填入，或在配置的 '
                f'render_args.dmrender.dmconvert 中显式指定 resolution_x/resolution_y。'
            )
        values = [getattr(self, name) for name in _FIELD_ORDER]
        return tuple(values) + (xml_file, ass_file)


def is_danmaku_xml(path: str) -> bool:
    """判断路径是否为需要转换的 XML 弹幕文件。"""
    return bool(path) and splitext(str(path))[1].lower() == f'.{DEFAULT_XML_SUFFIX}'


def find_danmaku_file(video_path: str, suffixes: tuple = DANMAKU_SUFFIXES) -> str:
    """为视频查找同名弹幕文件，按 ``suffixes`` 顺序取第一个存在的。

    默认优先 ``.ass``（渲染器原生格式），其次 ``.xml``（需转换，见 :func:`xml_to_ass`）。
    找不到时返回 ``None``。

    录制侧（``virtual_downloader``）与离线渲染（``render_only``）共用此函数，
    保证两处对"弹幕文件在哪"的判断一致。
    """
    if not video_path:
        return None
    base = splitext(str(video_path))[0]
    for suffix in suffixes:
        candidate = base + suffix
        if exists(candidate):
            return candidate
    return None


def default_ass_path(xml_file: str) -> str:
    """由 XML 路径推出同目录同名的 ``.ass`` 路径。

    注意：这里的 ``.ass`` 是**转换产物**。调用方必须承担"改名/删除"的责任 ——
    本模块只给出约定路径，不做清理，以免误删用户自己放在旁边的 ASS 文件。
    """
    return splitext(str(xml_file))[0] + f'.{DEFAULT_ASS_SUFFIX}'


def _import_convert():
    """延迟导入 ``dmconvert``，未安装时给出可操作的提示。"""
    try:
        from dmconvert import convert_xml_to_ass
        return convert_xml_to_ass
    except ImportError as e:
        raise RuntimeError(
            f'XML 弹幕转换需要 dmconvert 库（当前未安装或导入失败：{e}）。'
            f'请执行 `pip install dmconvert` 后重试，'
            f'或提供已转换好的 .ass 弹幕文件。'
        ) from e


def xml_to_ass(xml_file: str, ass_file: str = None, args=None,
               skip_if_exists: bool = False) -> str:
    """把 XML 弹幕转换为 ASS 弹幕。

    :param xml_file: 输入 XML 路径。必须存在。
    :param ass_file: 输出 ASS 路径；省略则用 :func:`default_ass_path`。
    :param args: 转换参数，可以是 :class:`Xml2AssArgs`、配置字典或 ``None``
        （用 :data:`DEFAULT_DMCONVERT_ARGS`）。
    :param skip_if_exists: 输出已存在时是否直接复用（默认 False，即重新转换）。
        渲染器复用同一路径重渲时应设为 True，避免重复转换。
    :returns: 输出 ASS 的绝对路径。
    :raises FileNotFoundError: XML 不存在。
    :raises RuntimeError: ``dmconvert`` 未安装，或上游转换失败。
    :raises ValueError: 缺少分辨率等必要参数。
    """
    xml_file = abspath(str(xml_file))
    if not exists(xml_file):
        raise FileNotFoundError(f'XML 弹幕文件不存在: {xml_file}')

    ass_file = abspath(str(ass_file)) if ass_file else default_ass_path(xml_file)

    if isinstance(args, Xml2AssArgs):
        conv_args = args
    elif isinstance(args, dict) or args is None:
        conv_args = Xml2AssArgs.from_dict(args)
    else:
        raise TypeError(f'不支持的转换参数类型: {type(args).__name__}')

    if skip_if_exists and exists(ass_file):
        logger.debug(f'复用已有弹幕文件: {ass_file}')
        return ass_file

    call_args = conv_args.as_call_args(xml_file, ass_file)
    convert_xml_to_ass = _import_convert()

    out_dir = os.path.dirname(ass_file)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    logger.debug(f'转换 XML 弹幕: {xml_file} -> {ass_file}')
    try:
        convert_xml_to_ass(*call_args)
    except Exception as e:
        # 上游只保证成功时不抛；这里补上输入输出路径，便于定位是哪个分段失败
        raise RuntimeError(f'转换 XML 弹幕失败 {xml_file} -> {ass_file}: {e}') from e

    if not exists(ass_file):
        raise RuntimeError(f'转换 XML 弹幕后未生成输出文件: {ass_file}')

    logger.debug(f'转换弹幕完成: {ass_file}')
    return ass_file
