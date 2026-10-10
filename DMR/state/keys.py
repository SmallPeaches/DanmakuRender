"""产物标识（``artifact_id``）的格式与解析。

为什么需要单独一个模块
----------------------
``artifact_id`` 会被**两个模块**用到：

- ``DMR/Downloader/stream_downloader.py``（录制时登记"这个分段"）
- ``DMR/Task/liveevents.py``（渲染/上传/清理时更新"同一个分段"）

若两边各自拼字符串，任何一处改动都会让状态静默对不上（表现为"任务明明上传了，
状态库里却查不到"这类难查的问题）。因此格式集中在这里，双方只调用函数。

格式
----
``<session_id>:<kind>:<segment_idx>``

- ``session_id``：一场直播（下载器里的 ``sess_id``，Task 层里的 ``group_id``）
- ``kind``：:class:`~DMR.state.enums.ArtifactKind` 的取值，如 ``src_video``
- ``segment_idx``：分片序号（从 1 开始）

``segment_idx`` 为 ``None`` 时省略该段（用于"整场只有一个产物"的场景，
例如渲染结果），得到 ``<session_id>:<kind>``。
"""
from __future__ import annotations

from .enums import ArtifactKind

__all__ = ["make_artifact_key", "parse_artifact_key"]

_SEPARATOR = ":"


def make_artifact_key(session_id: str, kind: ArtifactKind | str,
                      segment_idx: int | None = None) -> str:
    """拼出产物标识。

    ``session_id`` 本身含有 ``:`` 时无法可靠解析，因此显式拒绝（宁可早失败，
    也不要生成一个之后解析不回来的键）。
    """
    if not session_id:
        raise ValueError("session_id 不能为空。")
    if _SEPARATOR in str(session_id):
        raise ValueError(f"session_id 不能包含 {_SEPARATOR!r}：{session_id!r}")
    kind_value = str(ArtifactKind(kind))
    if segment_idx is None:
        return f"{session_id}{_SEPARATOR}{kind_value}"
    return f"{session_id}{_SEPARATOR}{kind_value}{_SEPARATOR}{int(segment_idx)}"


def parse_artifact_key(key: str) -> tuple[str, ArtifactKind, int | None]:
    """把产物标识解析回 ``(session_id, kind, segment_idx)``。

    解析失败抛 ``ValueError``（调用方应传入自己拼过的键，失败即为编程错误）。
    """
    parts = str(key).split(_SEPARATOR)
    if len(parts) == 2:
        session_id, kind_value = parts
        segment_idx = None
    elif len(parts) == 3:
        session_id, kind_value, raw_idx = parts
        try:
            segment_idx = int(raw_idx)
        except ValueError as exc:
            raise ValueError(f"产物标识的分片序号非法：{key!r}") from exc
    else:
        raise ValueError(f"产物标识格式非法：{key!r}")
    try:
        kind = ArtifactKind(kind_value)
    except ValueError as exc:
        raise ValueError(f"产物标识的 kind 非法：{key!r}") from exc
    return session_id, kind, segment_idx
