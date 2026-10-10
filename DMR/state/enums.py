"""状态持久化的枚举定义与取值校验。

设计要点（对应 ``TODO.md`` B8 的 P1）：

- 状态区分 **稳定态** 与 **运行中态**。运行中态描述"此刻正在进行"，进程一旦异常
  退出就不可信，启动对账的第 0 步会把它们降级（见 :mod:`DMR.state.reconciler`）。
- 取值从 DB 读回时**宽松容错**：未知值记警告并归入 ``INTERRUPTED``，而不是抛异常。
  用户手工改过 DB、或旧版本写入了新状态时，丢一列状态不应导致程序无法启动。
"""
from __future__ import annotations

import logging
from enum import StrEnum

logger = logging.getLogger(__name__)

__all__ = [
    "ArtifactKind",
    "ArtifactState",
    "UploadGroupState",
    "TERMINAL_ARTIFACT_STATES",
    "UNSTABLE_ARTIFACT_STATES",
    "StateConsistencyError",
    "coerce_artifact_state",
    "coerce_upload_group_state",
]


class StateConsistencyError(RuntimeError):
    """状态库与当前任务集不一致。

    **必须终止启动**：状态库是单一全局库、以 ``taskname`` 区分任务，而任务配置存放
    在会被 ``.gitignore`` 忽略的 ``configs/*.yml`` 中。一旦用户换了一份配置目录，
    旧任务就会"消失"；若此时继续运行，后续的过期回收会把这些任务的**历史状态当作
    垃圾删掉**。所以这里报错退出，而不是降级为"无持久化继续运行"。
    """


class ArtifactKind(StrEnum):
    """产物种类。

    与今天 ``VideoInfo.dtype`` 的三槽位一一对应（``liveevents.py:51-53``）：

    - ``SOURCE_PRE`` = 转码前的原始录制流
    - ``SOURCE``     = 转码结果，**替代**原始流；不转码时它就是原始录制流
    - ``DANMAKU_VIDEO`` = 渲染后的弹幕版视频

    弹幕**字幕文件**（``.ass``）不是这里的产物：它单独存在没有意义，是视频的附属物，
    因此作为 ``artifacts.danmaku_path`` 一列，而不是独立的一行。

    语义详见 ``PROJECT_STATE.md`` §3.5。
    """

    SOURCE_PRE = "src_video_pre"
    SOURCE = "src_video"
    DANMAKU_VIDEO = "dm_video"


class ArtifactState(StrEnum):
    """产物状态。"""

    # --- 稳定态：进程重启后依然可信 ---
    PLANNED = "planned"
    RECORDED = "recorded"
    RENDERED = "rendered"
    UPLOADED = "uploaded"
    CLEANED = "cleaned"
    MISSING = "missing"
    SKIPPED = "skipped"

    # --- 运行中态：随进程死亡而失效，须由第 0 步净化 ---
    RECORDING = "recording"
    RENDERING = "rendering"
    UPLOADING = "uploading"

    # --- 需关注态 ---
    INTERRUPTED = "interrupted"


class UploadGroupState(StrEnum):
    """上传组状态。

    ``OPEN`` 允许新产物继续追加到同一稿件（复用 ``remote_id``）；
    ``SEALED`` 表示不再追加，剩余产物按新组处理。
    """

    OPEN = "open"
    SEALED = "sealed"


#: 到达这些状态后，该产物不再需要保留在内存里（D 组 D1 的判据）
TERMINAL_ARTIFACT_STATES: frozenset[ArtifactState] = frozenset({
    ArtifactState.UPLOADED,
    ArtifactState.CLEANED,
    ArtifactState.SKIPPED,
    ArtifactState.MISSING,
})

#: 这些状态描述"此刻正在进行"，重启后一律不可信（第 0 步的输入）
UNSTABLE_ARTIFACT_STATES: frozenset[ArtifactState] = frozenset({
    ArtifactState.RECORDING,
    ArtifactState.RENDERING,
    ArtifactState.UPLOADING,
})


def coerce_artifact_state(value: object, *, context: str = "") -> ArtifactState:
    """把 DB 读回的取值转成 ``ArtifactState``。

    未知值不抛异常 —— 记一条警告并归入 ``INTERRUPTED``（需关注态），
    让程序仍能启动并把问题暴露给用户。
    """
    if isinstance(value, ArtifactState):
        return value
    try:
        return ArtifactState(str(value))
    except ValueError:
        logger.warning(
            "未知的产物状态 %r%s，按 interrupted 处理。",
            value, f"（{context}）" if context else "",
        )
        return ArtifactState.INTERRUPTED


def coerce_upload_group_state(value: object, *, context: str = "") -> UploadGroupState:
    """把 DB 读回的取值转成 ``UploadGroupState``；未知值保守地按 ``SEALED``。"""
    if isinstance(value, UploadGroupState):
        return value
    try:
        return UploadGroupState(str(value))
    except ValueError:
        logger.warning(
            "未知的上传组状态 %r%s，按 sealed 处理（不再追加）。",
            value, f"（{context}）" if context else "",
        )
        return UploadGroupState.SEALED
