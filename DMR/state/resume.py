"""从状态库记录**重建** ``VideoInfo``，供重启后重新驱动处理链。

要解决的问题
------------
``reconcile()`` 能把状态修正到"与磁盘一致"，但产物要重新走渲染/上传，就需要一个
真正的 ``VideoInfo``：上传器要用它取标题、文件大小、时长、分组；``LiveEvents``
要用它算输出文件名（``{STREAMER.NAME}``、``{CTIME.*}``、``{TITLE}`` 等模板）。

状态库里原本只有路径/大小/时长，**重建不出**文件名与标题。因此录制约定期把整个
``VideoInfo`` 存进产物载荷（``artifacts.data.video_info``），本模块负责把它还原。

两条还原路径
------------
1. **首选**：载荷里有 ``video_info`` → 直接还原来录制当时的元信息（最准确，
   标题与时间是录制当时的真实值）。
2. **回退**：载荷里没有（例如升级前录的分段）→ 用产物自身字段 + 场次记录拼一个
   可用的 ``VideoInfo``。主播名/房间/标题/平台取自 ``sessions`` 表，
   时间取场次开始时间。``face_url`` / ``cover_url`` 等未持久化的字段会缺失 ——
   仅影响引用它们的文件名模板。
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Mapping

from .payload import decode_video_info
from .repository import ArtifactRecord, SessionRecord

logger = logging.getLogger(__name__)

__all__ = [
    "rebuild_video_info",
    "is_recovered_file_usable",
    "looks_like_inprogress_file",
]

#: 分段式引擎写"正在录制"文件时统一加的前缀（见各 Downloader 的 raw_name）
INPROGRESS_MARKER = "[正在录制]"


def looks_like_inprogress_file(path: str | None) -> bool:
    """文件名是否以 ``[正在录制]`` 开头（分段式引擎的中间名标记）。"""
    if not path:
        return False
    return os.path.basename(path).startswith(INPROGRESS_MARKER)


def is_recovered_file_usable(path: str | None, size=None,
                             *, min_size_mb: float = 30.0) -> bool:
    """判断一个待恢复的产物是否"看起来正常"。

    **刻意不依赖 ffprobe**：服务器上探测失败既可能是文件损坏，也可能是环境里
    没有 ffprobe；据此判定会把好文件也一并放弃。改用两个便宜且确定的信号：

    1. **文件名以 ``[正在录制]`` 开头** —— 分段式引擎写出中间名就说明它确实开始
       录制了（这正是"录制中途被杀"留下的文件）；已改名的文件同样正常。
    2. **文件大小达到阈值**（默认 30MB）—— 大小是"录到实质内容"的直接证据，
       不需要解析容器。

    两者都满足即视为正常，可以继续渲染/上传。大小取不到（文件不存在等）时返回
    ``False``：无法证明可用就不处理，交由 ``on_interrupted_file`` 那条路径。

    :param size: 已知文件大小（字节）。为 ``None`` 时按 ``path`` 现取。
    """
    if not path:
        return False
    try:
        if size is None:
            if not os.path.exists(path):
                return False
            size = os.path.getsize(path)
    except OSError:
        return False
    if size is None:
        return False
    threshold = float(min_size_mb or 0) * 1024 * 1024
    return size >= threshold


def _fill_missing_media_info(video, artifact: ArtifactRecord, path: str) -> None:
    """补齐重建出的 ``VideoInfo`` 上缺失的 ``size``。

    只补 ``size``（读一次 ``stat`` 就够）—— **不再探测时长**：时长只用于上传的
    ``min_length`` 门槛，而恢复路径改用"文件名标记 + 文件大小"判定（见
    :func:`is_recovered_file_usable`），因此没有理由为此依赖 ffprobe。
    """
    if video is None:
        return
    if getattr(video, "size", None) is None and artifact.size is not None:
        video.size = artifact.size
    if getattr(video, "size", None) is None and path:
        try:
            video.size = os.path.getsize(path)
        except OSError:
            pass


def _sanitize_text_fields(kwargs: dict) -> dict:
    """把载荷里的文本字段归一化，避免 ``None`` 被格式化进文件名。

    起因：``{TITLE}`` 之类的模板遇到值为 ``None`` 的键会把它格式化成字符串
    ``"None"``（``dict_wapper`` 用 ``format_map``，找到键就返回其值），于是
    文件名变成 ``korooonx-None.mkv``。这里把"存在的键但值为 None"统一换成空串，
    让模板缺值就是缺值；``streamer`` 等非文本字段保持原样。
    """
    result = dict(kwargs)
    for field in ("title", "taskname", "dtype", "group_id", "dm_file_id"):
        if field in result and result[field] is None:
            result[field] = ""
    return result


def rebuild_video_info(artifact: ArtifactRecord,
                       session: SessionRecord | None,
                       *, path: str | None = None) -> object | None:
    """由产物与场次记录重建 ``VideoInfo``。

    ``VideoInfo`` 在函数内**延迟导入**：``DMR/__init__.py`` 会导入 ``DMR.state``，
    若本模块在顶层导入 ``DMR.utils`` 就会形成循环。延迟到调用时（那时包已加载完）
    即可安全拿到类型，同时避免依赖 ``DMR/__init__.py`` 里的导入顺序。

    :param path: 文件路径的**兜底值**。产物载荷可能损坏（或来自未写入载荷的旧版本），
        此时 ``artifact.path`` 也会一起丢失；调用方若已从别处拿到路径（例如对账
        报告里的 ``ResumableAction.path``），传进来即可继续重建。
        ``artifact.path`` 与它都存在时，以 ``artifact.path`` 为准。
    :returns: 重建出的 ``VideoInfo``；无法重建（连路径都没有）时返回 ``None``。
    """
    from DMR.utils import StreamerInfo, VideoInfo

    # 产物表是当前真相；载荷损坏时回退到调用方给出的路径
    path = artifact.path or path
    if not path:
        return None

    # --- 首选：载荷里的 video_info（录制当时写入，最准确）
    stored = decode_video_info(artifact.video_info)
    if stored:
        kwargs = _sanitize_text_fields(stored)
        # 产物表里的路径是"当前"真相（文件可能已被移动/改名），以它为准
        kwargs["path"] = path
        kwargs.setdefault("dtype", str(artifact.kind))
        kwargs.setdefault("group_id", artifact.session_id)
        kwargs.setdefault("segment_id", artifact.segment_idx)
        kwargs.setdefault("taskname", getattr(session, "taskname", None))
        # 标题缺失时用场次记录兜底 —— 否则文件名模板里的 {TITLE} 会留下空段
        if not kwargs.get("title") and session is not None:
            kwargs["title"] = getattr(session, "title", None)
        if not kwargs.get("taskname") and session is not None:
            kwargs["taskname"] = getattr(session, "taskname", None)
        # ``streamer`` 存进 JSON 后是普通 dict，但下游（文件名模板、上传器）按
        # 属性访问 ``video.streamer.name``。必须还原成 ``StreamerInfo``，
        # 否则重建出的对象一用就 AttributeError。
        streamer = kwargs.get("streamer")
        if isinstance(streamer, Mapping):
            kwargs["streamer"] = StreamerInfo(**dict(streamer))
        elif not streamer and session is not None:
            kwargs["streamer"] = _streamer_from_session(session, StreamerInfo)
        try:
            video = VideoInfo(**kwargs)
        except (TypeError, AttributeError, ValueError) as exc:
            # 载荷结构不符（例如旧版本写入的格式）→ 退回用场次信息拼
            logger.warning("产物 %s 的 video_info 无法还原（%s），改用场次信息重建。",
                           artifact.artifact_id, exc)
        else:
            _fill_missing_media_info(video, artifact, path)
            return video

    # --- 回退：用产物字段 + 场次记录拼装
    video = _rebuild_from_session(artifact, session, VideoInfo, StreamerInfo, path)
    _fill_missing_media_info(video, artifact, path)
    return video


def _fill_missing_media_info(video, artifact: ArtifactRecord, path: str) -> None:
    """重建后补齐缺失的 ``size``（两条重建路径共用）。

    先用产物表里已记录的值，仍缺失才读一次文件 ``stat`` —— 读库比读盘便宜。
    **不补时长**：恢复判定与上传长度门槛都用"文件名标记 + 文件大小"（见
    :func:`is_recovered_file_usable`），没有理由为此依赖 ffprobe。
    """
    if getattr(video, "size", None) is None and artifact.size is not None:
        video.size = artifact.size
    if getattr(video, "duration", None) is None and artifact.duration is not None:
        # 库里已有真实时长就用它（例如正常录制登记的产物），不做探测
        video.duration = artifact.duration
    if getattr(video, "size", None) is None and path:
        try:
            video.size = os.path.getsize(path)
        except OSError:
            pass


def _rebuild_from_session(artifact: ArtifactRecord, session: SessionRecord | None,
                          video_cls, streamer_cls, path: str):
    """载荷不可用时的回退重建。

    ``face_url`` / ``cover_url`` 等未持久化的字段会缺失 —— 仅影响引用它们的
    文件名模板，不影响上传与渲染。
    """
    return video_cls(
        path=path,
        dtype=str(artifact.kind),
        size=artifact.size,
        # 时间用场次开始时间：它最接近该分段的录制时间，且对文件名模板有意义
        ctime=(datetime.fromtimestamp(session.started_at)
               if session is not None and session.started_at else None),
        duration=artifact.duration,
        resolution=artifact.resolution,
        title=getattr(session, "title", None),
        streamer=(_streamer_from_session(session, streamer_cls)
                  if session is not None else None),
        group_id=artifact.session_id,
        segment_id=artifact.segment_idx,
        taskname=getattr(session, "taskname", None),
        dm_file_id=artifact.danmaku_path,
    )


def _streamer_from_session(session: SessionRecord, streamer_cls):
    """由场次记录重建 ``StreamerInfo``。"""
    return streamer_cls(
        name=session.streamer_name or session.taskname,
        uid=session.streamer_uid,
        platform=session.platform,
        room_id=session.room_id,
        url=session.room_url,
    )
