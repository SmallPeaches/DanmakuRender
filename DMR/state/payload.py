"""产物（Artifact）可变字段的 JSON 载荷序列化。

设计动机（用户要求）
--------------------
产物会持续扩展（新增分辨率、编码信息、弹幕最终路径、自定义元数据…）。若每个字段
都建一列，每次扩展都要改表 + 写迁移，成本高且容易出错。

因此把**身份与查询键**留在列上，把**易变的载荷**收进一个 JSON 列 ``data``：

===========================  ==========================  ============================
列（结构化，需要查询/约束）    含义                        ``data``（JSON 载荷）
===========================  ==========================  ============================
``artifact_id``             主键                        ``path`` 产物文件
``session_id``              外键 + 级联 + 按场次查询      ``part_path`` 待收尾的文件
``segment_idx`` + ``kind``  同一分段的唯一约束            ``danmaku_path`` 弹幕附属文件
``state``                   对账要按状态过滤（有索引）      ``size`` / ``duration``
``updated_at``              过期判定 / 内存回收            ``resolution`` / ``origin``
                                                       ``attempts`` / ``last_error``
===========================  ==========================  ============================

**加入 ``data`` 的判据**：该字段会变、或未来可能新增，且**不需要**在 SQL 里过滤/排序。
反例：``state`` 必须能 ``WHERE state NOT IN (...)``，所以留在列上。

扩展新字段时**无需改表**：在新的 Python 版本里给它一个默认值并列入
:data:`MUTABLE_PAYLOAD_FIELDS`，旧的 ``data`` 里没有该键也能正常读回。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Mapping

logger = logging.getLogger(__name__)

__all__ = [
    "MUTABLE_PAYLOAD_FIELDS",
    "encode_payload",
    "decode_payload",
    "encode_video_info",
    "decode_video_info",
]

#: 存入 ``artifacts.data``（JSON）的字段名。
#: 与 :class:`~DMR.state.repository.ArtifactRecord` 的字段名一一对应 ——
#: 读写两端共用这一处定义，避免两边漂移。
MUTABLE_PAYLOAD_FIELDS: tuple[str, ...] = (
    "path",
    "part_path",
    "danmaku_path",
    "size",
    "duration",
    "resolution",
    "origin",
    "attempts",
    "last_error",
    # 录制当时的完整 VideoInfo（含主播 / 标题 / 时间）。用于重启后**重建**产物
    # 并重新驱动渲染与上传 —— 缺了它就无法还原输出文件名与视频标题。
    "video_info",
)

#: 载荷内需要按 ``(宽, 高)`` 元组还原的字段（JSON 里存 "1920x1080" 字符串）
_TUPLE_FIELDS = ("resolution",)


def encode_payload(record: Any) -> str:
    """把记录的易变字段编码成 JSON 字符串。

    写入当前字段的全集（``None`` 也保留），便于人工排查时直接看到全部字段；
    非 JSON 原生的值（``datetime`` / ``tuple``，以及嵌套的 ``VideoInfo``）
    在这里统一转换，保证写入端与读取端的表示一致。
    """
    payload: dict[str, Any] = {}
    for field_name in MUTABLE_PAYLOAD_FIELDS:
        value = getattr(record, field_name, None)
        if field_name == "video_info":
            # 嵌套结构：交给专用编码器（内部会做 datetime/tuple 归一化）
            value = encode_video_info(value)
        elif field_name in _TUPLE_FIELDS:
            value = _resolution_to_text(value)
        payload[field_name] = value
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def decode_payload(raw: Any) -> dict[str, Any]:
    """把 ``data`` 列解回字段字典。

    容错原则（与状态枚举一致）：坏数据不应让程序无法启动。

    - ``NULL`` / 空字符串 → 全默认；
    - 非法 JSON → 记 warning 并当作空载荷；
    - 非 dict → 同上；
    - 位置参数缺失的键 → 由调用方的默认值兜住；
    - ``resolution`` 字符串 → ``(w, h)`` 元组。
    """
    if raw is None or raw == "":
        return {}
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="replace")
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("产物 data 列不是合法 JSON，按空载荷处理：%r", raw)
        return {}
    if not isinstance(parsed, Mapping):
        logger.warning("产物 data 列不是对象，按空载荷处理：%r", raw)
        return {}

    result = dict(parsed)
    if "resolution" in result:
        result["resolution"] = _text_to_resolution(result["resolution"])
    if "video_info" in result:
        result["video_info"] = decode_video_info(result["video_info"])
    return result


# --------------------------------------------------------------------------- 视频信息
#
# ``VideoInfo`` 是 ``cpdict``（dict 子类），本身就带全部字段，因此可以直接 JSON 化。
# 但其中两类值不是 JSON 原生类型，必须显式转换，否则要么写入失败、要么读回来后
# 类型不对（``ctime`` 变成 str，会让 ``{CTIME.YEAR}`` 这类文件名模板抛异常）：
#
#   - ``datetime``（``ctime``）→ ISO 字符串；反序列化时还原为 ``datetime``
#   - ``tuple``（``resolution``）→ 列表；反序列化时还原为 tuple

#: 反序列化时需要还原为 ``datetime`` 的键
_DATETIME_FIELDS = ("ctime",)


def _json_default(value: Any) -> Any:
    """``json.dumps`` 的兜底：把 datetime 转 ISO 字符串，其余转字符串。"""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def encode_video_info(video_info: Any) -> dict[str, Any] | None:
    """把 ``VideoInfo`` 编码成可 JSON 化的 dict。

    过一遍 ``json.dumps/loads`` 是为了得到一个**纯 JSON 类型**的 dict：这样读取端
    拿到的结构与"从库里读回"完全一致，避免"新建时是 datetime、恢复后是 str"这种
    只在恢复路径上出现的不一致。

    接受的对象形式：``Mapping``（``VideoInfo`` 就是 dict 子类）、``str``（已是 JSON）
    以及带 ``__dict__`` 的普通对象（例如自定义下载器传进来的命名空间对象）。
    """
    if video_info is None:
        return None
    if isinstance(video_info, str):
        # 已经是 JSON 字符串（例如从旧载荷读回）
        return decode_video_info(video_info)
    if isinstance(video_info, Mapping):
        raw = dict(video_info)
    elif hasattr(video_info, "__dict__"):
        # 非 Mapping 的对象（如 SimpleNamespace / 自定义信息类）
        raw = {k: v for k, v in vars(video_info).items()
               if not k.startswith("_")}
    else:
        logger.warning("VideoInfo 形式无法识别，将不保存：%r", type(video_info))
        return None
    try:
        encoded = json.dumps(raw, ensure_ascii=False, default=_json_default)
        return json.loads(encoded)
    except (TypeError, ValueError) as exc:
        logger.warning("VideoInfo 无法序列化，将不保存：%r", exc)
        return None


def decode_video_info(raw: Any) -> dict[str, Any] | None:
    """把载荷里的 ``video_info`` 解成可构造 ``VideoInfo`` 的 dict。

    容错与 :func:`decode_payload` 一致：坏数据返回 ``None``，不抛异常。
    """
    if raw is None or raw == "":
        return None
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="replace")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            logger.warning("video_info 不是合法 JSON，已忽略：%r", raw)
            return None
    if not isinstance(raw, Mapping):
        logger.warning("video_info 不是对象，已忽略：%r", raw)
        return None

    result = dict(raw)
    for field_name in _DATETIME_FIELDS:
        if field_name in result:
            result[field_name] = _text_to_datetime(result[field_name])
    if "resolution" in result:
        result["resolution"] = _text_to_resolution(result["resolution"])
    return result


def _text_to_datetime(value: Any) -> datetime | None:
    """把 ISO 字符串还原为 ``datetime``；已是 datetime 则原样返回。"""
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        logger.warning("video_info.ctime 不是合法时间，已忽略：%r", value)
        return None


def _resolution_to_text(value: Any) -> str | None:
    """``(1920, 1080)`` → ``"1920x1080"``；已是字符串则原样返回。"""
    if not value:
        return None
    if isinstance(value, str):
        return value
    try:
        width, height = value
        return f"{int(width)}x{int(height)}"
    except Exception:
        return None


def _text_to_resolution(value: Any) -> tuple[int, int] | None:
    """``"1920x1080"`` → ``(1920, 1080)``。"""
    if not value:
        return None
    if isinstance(value, (tuple, list)) and len(value) == 2:
        try:
            return int(value[0]), int(value[1])
        except (TypeError, ValueError):
            return None
    try:
        width, height = str(value).lower().split("x", 1)
        return int(width), int(height)
    except Exception:
        return None
