"""状态持久化与启动对账（P1）。

本模块统一负责"把状态存下来并在重启后对齐"，包含两部分：

- **仓储**（:mod:`DMR.state.repository`）：会话 / 产物 / 上传组的 SQLite 读写。
- **对账**（:mod:`DMR.state.reconciler`）：启动时把状态库与磁盘事实对齐，
  处置"录到一半"的产物、回收过期状态。

用法::

    from DMR.state import RecoveryConfig, RecoveryManager, StateRepository

    repo = StateRepository("logs/dmr_state.db").open()
    repo.create_session("sess-1", "mytask", streamer_name="主播")

    report = RecoveryManager(repo, RecoveryConfig()).reconcile()
    print(report.summary())
"""
from .enums import (
    TERMINAL_ARTIFACT_STATES,
    UNSTABLE_ARTIFACT_STATES,
    ArtifactKind,
    ArtifactState,
    StateConsistencyError,
    UploadGroupState,
    coerce_artifact_state,
    coerce_upload_group_state,
)
from .keys import make_artifact_key, parse_artifact_key
from .payload import encode_video_info, decode_video_info
from .reconciler import (
    InterruptedAction,
    InterruptedFileAction,
    MissingAction,
    RecoveryConfig,
    RecoveryManager,
    RecoveryReport,
    ResumableAction,
    SessionCleanupAction,
    StaleAction,
    UnusableFileAction,
    UnstableAction,
)
from .repository import (
    ArtifactRecord,
    SessionRecord,
    StateRepository,
    UploadGroupRecord,
)
from .resume import (
    is_recovered_file_usable,
    looks_like_inprogress_file,
    rebuild_video_info,
)
from .schema import SCHEMA_VERSION

__all__ = [
    # 枚举与取值校验
    "ArtifactKind",
    "ArtifactState",
    "UploadGroupState",
    "TERMINAL_ARTIFACT_STATES",
    "UNSTABLE_ARTIFACT_STATES",
    "coerce_artifact_state",
    "coerce_upload_group_state",
    "StateConsistencyError",
    # 产物标识
    "make_artifact_key",
    "parse_artifact_key",
    # 视频信息载荷
    "encode_video_info",
    "decode_video_info",
    # 仓储
    "ArtifactRecord",
    "SessionRecord",
    "UploadGroupRecord",
    "StateRepository",
    "SCHEMA_VERSION",
    # 对账
    "RecoveryConfig",
    "RecoveryManager",
    "RecoveryReport",
    "InterruptedFileAction",
    "UnusableFileAction",
    "InterruptedAction",
    "UnstableAction",
    "MissingAction",
    "StaleAction",
    "SessionCleanupAction",
    "ResumableAction",
    # 恢复重建
    "rebuild_video_info",
    "is_recovered_file_usable",
    "looks_like_inprogress_file",
]
