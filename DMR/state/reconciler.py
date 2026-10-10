"""启动对账（P1）。

进程重启后，把 DB 里"进程被杀时留下的"状态与磁盘事实对齐，
必要时把未完成的产物转成可用产物，使"未上传/未渲染的视频"和"录一半的视频"不丢。

对账规则（完整说明见 ``TODO.md`` B8，此处按实现顺序列出）
----------------------------------------------------------

**第 0 步 · 净化运行中状态**
    ``RECORDING``/``RENDERING``/``UPLOADING`` 描述"此刻正在进行"，进程一旦退出即
    不可信。它们分别降级为 ``INTERRUPTED`` / ``RECORDED`` / ``RECORDED``。
    这一步让整个对账**幂等**。

**A 组 · 校验非终态产物的磁盘事实**
    A1 ``INTERRUPTED`` 且 ``.part`` 存在且校验通过 → 按策略处置
    A2 同上但校验失败                            → 强制抛弃
    A3 ``.part`` 与正式路径都不存在              → ``MISSING``
    A4 ``.part`` 不存在但正式路径存在且通过校验  → ``RECORDED``（rename 已发生）
    A5 其它稳定态且路径存在                      → 保持不变
    A6 路径不存在                                → ``MISSING``

**C 组 · 上传归属**
    C2 ``sealed`` 组只提示，不再追加
    C3 ``UPLOADED`` 跳过（幂等，由 ``list_artifacts`` 过滤实现）

**D 组 · 回收**
    D3 非终态且 ``updated_at`` 超过 ``stale_after`` → 抛弃
    D4 已结束且全部产物终态的场次                    → 删除（并级联删除产物）

注意：**不含"孤儿收养"**。按用户决定，DB 是唯一权威，磁盘上 DB 不认识的文件
不会被登记。
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from enum import StrEnum

from .enums import ArtifactState
from .repository import ArtifactRecord, SessionRecord, StateRepository

logger = logging.getLogger(__name__)

__all__ = [
    "InterruptedFileAction",
    "UnusableFileAction",
    "InterruptedAction",
    "UnstableAction",
    "MissingAction",
    "StaleAction",
    "SessionCleanupAction",
    "ResumableAction",
    "RecoveryConfig",
    "RecoveryReport",
    "RecoveryManager",
]


class InterruptedFileAction(StrEnum):
    """对"录到一半的产物"如何处置。"""

    ASK = "ask"          # 只标记 INTERRUPTED，等用户处置（默认）
    KEEP = "keep"        # 校验通过则转正为正常产物（可渲染/上传）
    DISCARD = "discard"  # 删除文件（= "从 0 开始"）


@dataclass(frozen=True)
class InterruptedAction:
    artifact_id: str
    path: str | None
    reason: str          # 'promoted' | 'needs_attention' | 'discarded'


@dataclass(frozen=True)
class UnstableAction:
    artifact_id: str
    from_state: ArtifactState
    to_state: ArtifactState


@dataclass(frozen=True)
class MissingAction:
    artifact_id: str
    path: str | None


@dataclass(frozen=True)
class StaleAction:
    artifact_id: str
    age_seconds: int


@dataclass(frozen=True)
class SessionCleanupAction:
    session_id: str
    taskname: str


#: 不满足恢复条件的产物（大小不足、文件已不存在）如何处置
class UnusableFileAction(StrEnum):
    """``recovery.on_unusable_file`` 的取值。"""

    #: 保持原状态，等用户决定（每次重启都会再试一遍并再次告警）
    ASK = "ask"
    #: 标记为 ``skipped``，不再重试（默认）—— 文件仍在磁盘上，不删除
    SKIP = "skip"
    #: 标记为 ``skipped`` 并**删除**文件
    DISCARD = "discard"


@dataclass(frozen=True)
class ResumableAction:
    """可恢复产物：重启后应被重新驱动处理的产物。

    ``reason`` 说明它为什么需要重新处理：

    - ``unprocessed``：录制完成但尚未渲染/上传（``RECORDED``）
    - ``rendered``   ：已渲染但尚未上传（``RENDERED``）
    """

    artifact_id: str
    taskname: str
    session_id: str
    segment_idx: int
    kind: str
    state: str
    path: str | None
    reason: str


@dataclass
class RecoveryReport:
    """对账结果。用于日志与（P4 之后的）REST ``GET /api/v1/recovery``。"""

    unstable: list[UnstableAction] = field(default_factory=list)
    interrupted: list[InterruptedAction] = field(default_factory=list)
    missing: list[MissingAction] = field(default_factory=list)
    stale: list[StaleAction] = field(default_factory=list)
    sessions_cleaned: list[SessionCleanupAction] = field(default_factory=list)
    sealed_groups: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    #: 对账后仍处于"已录制/已渲染但未上传"的产物 —— 应由恢复流程重新驱动。
    #: 由 :meth:`RecoveryManager.collect_resumable` 填充（不在 ``reconcile`` 里做，
    #: 因为"是否重跑"取决于配置与任务是否实际加载）。
    resumable: list[ResumableAction] = field(default_factory=list)

    @property
    def needs_attention(self) -> int:
        """需要用户处置的项数（``on_interrupted_file: ask`` 下的滞留项）。"""
        return sum(1 for item in self.interrupted if item.reason == "needs_attention")

    def summary(self) -> str:
        return (
            f"对账完成：状态净化 {len(self.unstable)} 项，"
            f"中断产物 {len(self.interrupted)} 项（待处置 {self.needs_attention}），"
            f"缺失 {len(self.missing)} 项，过期抛弃 {len(self.stale)} 项，"
            f"清理场次 {len(self.sessions_cleaned)} 个，"
            f"已封存上传组 {len(self.sealed_groups)} 个，"
            f"待恢复 {len(self.resumable)} 项，错误 {len(self.errors)} 条。"
        )


@dataclass(frozen=True)
class RecoveryConfig:
    """``configs/global.yml`` 的 ``recovery`` 段。"""

    on_interrupted_file: InterruptedFileAction = InterruptedFileAction.ASK
    min_valid_duration: float = 60.0
    #: 判定"正在录制文件是否可信"的**大小阈值**（MB，默认 30）。
    #:
    #: 用于两个必须一致的场合：
    #: 1. 启动对账时校验中断产物（``.part`` / 引擎直写最终名）够不够大；
    #: 2. 重启恢复时判定产物值不值得继续处理（``is_recovered_file_usable``）。
    #:
    #: 二者都在回答同一个问题——"这个录到一半的文件是否已录到实质内容"，
    #: 因此**共用这一项**（早期版本曾拆成两个名字，属于重复配置）。
    #: 判定**不依赖 ffprobe**：读一次 ``stat`` 即可，不需要解析容器。
    min_valid_size_mb: float = 30.0
    stale_after: int = 7 * 24 * 3600          # 7 天
    idle_release: int = 300                   # uploader 实例空闲释放
    upload_group_expires: int | None = None   # None = 永不过期
    #: 重启后是否自动继续处理"已录制 / 已渲染但未完成"的产物。
    #: 关闭时只对账不重跑，适合想先人工核对再上传的场景。
    resume: bool = True
    #: 不满足恢复条件的产物（大小不足、文件已不存在）如何处置。
    #: 默认 ``skip``：标记为 skipped 并停止重试，但**不删除文件**。
    on_unusable_file: UnusableFileAction = UnusableFileAction.SKIP

    def __post_init__(self) -> None:
        """统一把 ``on_interrupted_file`` 规整为枚举。

        不能只依赖 :meth:`from_mapping` 做转换：直接构造（包括单测与将来的
        程序化调用）传入字符串时，若保留为 ``str``，``_handle_interrupted`` 里的
        ``is`` 比较会静默落到 ``ask`` 分支 —— 即用户设置了 ``keep``/``discard``
        却完全不生效。因此校验放在 ``__post_init__``，任何构造路径都覆盖。
        """
        raw = self.on_interrupted_file
        if not isinstance(raw, InterruptedFileAction):
            try:
                object.__setattr__(self, "on_interrupted_file",
                                   InterruptedFileAction(raw))
            except ValueError:
                logger.warning(
                    "recovery.on_interrupted_file=%r 无效（可选 %s），改用 ask。",
                    raw, [a.value for a in InterruptedFileAction],
                )
                object.__setattr__(self, "on_interrupted_file",
                                   InterruptedFileAction.ASK)

        raw_unusable = self.on_unusable_file
        if not isinstance(raw_unusable, UnusableFileAction):
            try:
                object.__setattr__(self, "on_unusable_file",
                                   UnusableFileAction(raw_unusable))
            except ValueError:
                logger.warning(
                    "recovery.on_unusable_file=%r 无效（可选 %s），改用 skip。",
                    raw_unusable, [a.value for a in UnusableFileAction],
                )
                object.__setattr__(self, "on_unusable_file",
                                   UnusableFileAction.SKIP)

    @classmethod
    def from_mapping(cls, mapping: dict | None) -> "RecoveryConfig":
        """从配置字典构造；缺省项用默认值。"""
        if not mapping:
            return cls()
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        unknown = set(mapping) - known
        if unknown:
            logger.warning("recovery 配置中有未知项，已忽略：%s", sorted(unknown))
        values = {k: v for k, v in mapping.items() if k in known}
        # on_interrupted_file 的合法性由 __post_init__ 统一校验
        return cls(**values)


class RecoveryManager:
    """把状态库与磁盘对齐。

    用法::

        manager = RecoveryManager(repo, config)
        report = manager.reconcile()
        logger.info(report.summary())
    """

    def __init__(
        self,
        repo: StateRepository,
        config: RecoveryConfig | None = None,
        *,
        probe=None,
        now=None,
    ) -> None:
        self.repo = repo
        self.config = config or RecoveryConfig()
        self._probe = probe
        self._now = now or (lambda: int(time.time()))

    # ------------------------------------------------------------------ 入口

    def reconcile(self) -> RecoveryReport:
        report = RecoveryReport()
        try:
            self._step0_sanitize_unstable(report)
            self._group_a_check_disk(report)
            self._group_d_reclaim(report)
            self._note_sealed_groups(report)
        except Exception as exc:  # 对账失败不应阻止程序启动
            logger.exception("启动对账过程中出错，将使用现有状态继续。")
            report.errors.append(str(exc))
        self.repo.set_meta("last_reconcile_at", str(self._now()))
        return report

    # ------------------------------------------------- 收集"应重新驱动"的产物
    #
    # 为什么需要单独一步：``reconcile()`` 只把状态修正到"与磁盘一致"，**不会**把
    # 产物送回处理链。若只对账不重跑，重启后那些"已录完但没渲染/没上传"的分段就会
    # 永远停在那里 —— 这正是服务器上观察到的现象（文件在、状态是 recorded，
    # 但既没被上传也没被清理）。
    #
    # 因此这里挑出需要继续处理的产物，交由 Task 层重建 VideoInfo 并重新注入事件流。
    # 只包含 **RECORDED / RENDERED**：
    #   - 更早的状态（PLANNED）没有文件可用；
    #   - RENDERING / UPLOADING 已被第 0 步降级为 RECORDED，会自然出现在这里；
    #   - UPLOADED / CLEANED 等终态**绝不重跑**（否则会重复投稿）。

    #: 触发重新处理的产物状态 -> 原因
    RESUMABLE_STATES: dict[ArtifactState, str] = {
        ArtifactState.RECORDED: "unprocessed",
        ArtifactState.RENDERED: "rendered",
    }

    def collect_resumable(self, report: RecoveryReport,
                          *, tasknames: set[str] | None = None) -> None:
        """把需要继续处理的产物追加到 ``report.resumable``。

        :param tasknames: 只收集这些任务的产物；``None`` 表示全部。
            传入当前实际加载的任务，可避免为未加载的任务白建恢复对象。
        """
        sessions = {s.session_id: s for s in self.repo.list_sessions()}
        for artifact in self.repo.list_artifacts(
                states=list(self.RESUMABLE_STATES)):
            session = sessions.get(artifact.session_id)
            if session is None:
                # 场次已被回收，产物失去归属（正常不会发生：有非终态产物时
                # 场次不会被回收），如实记录而不是静默跳过。
                report.errors.append(
                    f"产物 {artifact.artifact_id} 的场次 "
                    f"{artifact.session_id} 不存在，无法恢复。"
                )
                continue
            if tasknames is not None and session.taskname not in tasknames:
                continue
            if not artifact.path:
                # 没有路径就无从处理；这类产物应已被对账判为 MISSING。
                continue
            report.resumable.append(ResumableAction(
                artifact_id=artifact.artifact_id,
                taskname=session.taskname,
                session_id=artifact.session_id,
                segment_idx=artifact.segment_idx,
                kind=str(artifact.kind),
                state=str(artifact.state),
                path=artifact.path,
                reason=self.RESUMABLE_STATES[artifact.state],
            ))
            # 累加重试次数（不改状态）：同一产物若反复出现，能从 attempts 看出来
            try:
                self.repo.bump_artifact_attempts(artifact.artifact_id)
            except Exception as exc:
                logger.warning("累加产物 %s 的重试次数失败：%s",
                               artifact.artifact_id, exc)
        if report.resumable:
            logger.info("发现 %d 个待恢复产物（已录制/已渲染但未完成处理）。",
                        len(report.resumable))

    # ------------------------------------------------- 第 0 步：净化运行中状态

    def _step0_sanitize_unstable(self, report: RecoveryReport) -> None:
        """运行中状态一律不可信：按 §第0步 降级。"""
        transitions = {
            ArtifactState.RECORDING: ArtifactState.INTERRUPTED,
            ArtifactState.RENDERING: ArtifactState.RECORDED,
            ArtifactState.UPLOADING: ArtifactState.RECORDED,
        }
        for artifact in self.repo.list_artifacts(states=list(transitions)):
            target = transitions[artifact.state]
            self.repo.set_artifact_state(
                artifact.artifact_id, target,
                last_error=None if target is ArtifactState.RECORDED
                else "进程退出时仍在运行",
            )
            report.unstable.append(
                UnstableAction(artifact.artifact_id, artifact.state, target)
            )
        if report.unstable:
            logger.info("已净化 %d 个运行中状态（进程上次未正常退出）。",
                        len(report.unstable))

    # ------------------------------------------------- A 组：校验磁盘事实

    def _group_a_check_disk(self, report: RecoveryReport) -> None:
        for artifact in self.repo.list_artifacts(terminal=False):
            state = artifact.state

            if state is ArtifactState.INTERRUPTED:
                self._handle_interrupted(artifact, report)
                continue

            # A5/A6：稳定态只看正式路径是否存在
            if state in (ArtifactState.PLANNED,):
                continue
            if self._exists(artifact.path):
                continue
            self.repo.set_artifact_state(
                artifact.artifact_id, ArtifactState.MISSING,
                last_error=f"文件不存在：{artifact.path}",
            )
            report.missing.append(MissingAction(artifact.artifact_id, artifact.path))
            logger.warning("产物 %s 的文件不存在，已标记为 lost：%s",
                           artifact.artifact_id, artifact.path)

    def _handle_interrupted(self, artifact: ArtifactRecord,
                            report: RecoveryReport) -> None:
        """A1–A4：处理录到一半的产物。

        关键情形：下载引擎**直接写最终文件名**，因此 ``part_path`` 通常**等于**
        ``path``（同一个文件），而不是一个独立的 ``.part``。早期实现要求
        "``.part`` 不存在且正式路径存在"才转正，导致这种最常见的情形永远走不到
        转正分支（``keep`` 策略形同虚设，实机验证时暴露）。
        """
        part = artifact.part_path
        has_part = self._exists(part)
        has_final = self._exists(artifact.path)
        # 引擎直接写最终名时 part 与 path 是同一个文件
        same_file = bool(part) and part == artifact.path

        # ① 正式文件已在且有效 → 恢复为可用的 RECORDED。
        #    这涵盖两种情形，二者都意味着"其实已经录完，只是状态没落库"：
        #      a) rename 已完成，但进程在写状态前退出；
        #      b) 引擎直接写最终名，part 与 path 是同一个文件。
        #    注意：只有**正式路径**上的文件才能这样直接恢复 —— 独立的 .part 即使
        #    能被解析，也仍然只是"可能没写完"的中间产物，必须按用户策略处置（见 ②）。
        if has_final and self._is_valid(artifact.path):
            self.repo.set_artifact_path(artifact.artifact_id,
                                        path=artifact.path, part_path=None)
            self.repo.set_artifact_state(artifact.artifact_id,
                                         ArtifactState.RECORDED)
            report.interrupted.append(
                InterruptedAction(artifact.artifact_id, artifact.path, "promoted")
            )
            logger.info("中断产物 %s 的正式文件有效，已恢复为 recorded：%s",
                        artifact.artifact_id, artifact.path)
            return

        # ② 存在描述"录到一半"的文件（path 无效或不存在，但 part 在）→ 按策略处置
        if has_part and not same_file:
            self._handle_part_file(artifact, part, report)
            return

        # ③ 两边都没有 → 真的丢了
        if not has_part and not has_final:
            self.repo.set_artifact_state(
                artifact.artifact_id, ArtifactState.MISSING,
                last_error="中断产物已不存在",
            )
            report.missing.append(MissingAction(artifact.artifact_id, artifact.path))
            return

        # ④ 兜底：文件在但校验未通过（损坏 / 过短）
        target = artifact.path if has_final else part
        self.repo.set_artifact_state(
            artifact.artifact_id, ArtifactState.INTERRUPTED,
            last_error="文件校验未通过（不可解析或过短）", bump_attempts=True,
        )
        action = self.config.on_interrupted_file
        if action is InterruptedFileAction.DISCARD:
            self._safe_remove(target)
            self.repo.set_artifact_state(artifact.artifact_id,
                                         ArtifactState.SKIPPED,
                                         last_error="文件校验未通过，已删除")
            report.interrupted.append(
                InterruptedAction(artifact.artifact_id, target, "discarded")
            )
        else:
            report.interrupted.append(
                InterruptedAction(artifact.artifact_id, target, "needs_attention")
            )
            logger.warning(
                "产物 %s 中断且文件校验未通过（%s），已标记为 interrupted。",
                artifact.artifact_id, target,
            )

    def _handle_part_file(self, artifact: ArtifactRecord, part: str,
                          report: RecoveryReport) -> None:
        """按 ``on_interrupted_file`` 策略处置"录到一半"的 ``.part`` 文件。

        - ``ask``    ：只标记 ``INTERRUPTED``，等用户决定（不动文件）
        - ``keep``   ：**校验通过**才转正为正式文件；不通过则仍需人工处理
        - ``discard``：删除文件（= 从 0 开始）
        """
        action = self.config.on_interrupted_file

        if action is InterruptedFileAction.DISCARD:
            self._safe_remove(part)
            self.repo.set_artifact_state(
                artifact.artifact_id, ArtifactState.SKIPPED,
                last_error="用户配置为丢弃中断产物",
            )
            report.interrupted.append(
                InterruptedAction(artifact.artifact_id, part, "discarded")
            )
            return

        if action is InterruptedFileAction.KEEP:
            if not self._is_valid(part):
                self.repo.set_artifact_state(
                    artifact.artifact_id, ArtifactState.INTERRUPTED,
                    last_error="part 校验未通过（不可解析或过短）",
                    bump_attempts=True,
                )
                report.interrupted.append(
                    InterruptedAction(artifact.artifact_id, part, "needs_attention")
                )
                logger.warning("中断产物 %s 的 part 校验未通过，未转正。",
                               artifact.artifact_id)
                return
            final_path = artifact.path or self._derive_final_path(part)
            if self._promote(part, final_path):
                size, duration = self._probe_size_duration(final_path)
                self.repo.set_artifact_path(
                    artifact.artifact_id, path=final_path, part_path=None,
                    size=size, duration=duration,
                )
                self.repo.set_artifact_state(artifact.artifact_id,
                                             ArtifactState.RECORDED)
                report.interrupted.append(
                    InterruptedAction(artifact.artifact_id, final_path, "promoted")
                )
                logger.info("中断产物 %s 已转正为 %s。",
                            artifact.artifact_id, final_path)
            else:
                report.interrupted.append(
                    InterruptedAction(artifact.artifact_id, part, "needs_attention")
                )
            return

        # ASK：只标记，不动文件
        self.repo.set_artifact_state(
            artifact.artifact_id, ArtifactState.INTERRUPTED,
            last_error="录到一半，等待处置",
        )
        report.interrupted.append(
            InterruptedAction(artifact.artifact_id, part, "needs_attention")
        )
        logger.warning(
            "产物 %s 中断（录到一半，已录 %s），可通过 "
            "recovery.on_interrupted_file 选择 keep 转正或 discard 删除。",
            artifact.artifact_id, part,
        )

    # ------------------------------------------------- D 组：回收

    def _group_d_reclaim(self, report: RecoveryReport) -> None:
        now = self._now()

        # D3：非终态且长期无进展 → 抛弃（正常一场直播不会超过 stale_after）
        stale_after = self.config.stale_after
        if stale_after and stale_after > 0:
            for artifact in self.repo.list_artifacts(terminal=False):
                age = now - artifact.updated_at
                if age <= stale_after:
                    continue
                self.repo.set_artifact_state(
                    artifact.artifact_id, ArtifactState.SKIPPED,
                    last_error=f"超过 {stale_after}s 无进展，已抛弃",
                )
                report.stale.append(StaleAction(artifact.artifact_id, age))
                logger.warning("产物 %s 已 %d 秒无进展，按过期抛弃。",
                               artifact.artifact_id, age)

        # D4：已结束且全部产物终态的场次 → 删除（级联删除产物）
        for session in self.repo.list_sessions():
            if not session.is_ended:
                continue
            remaining = self.repo.list_artifacts(session_id=session.session_id,
                                                 terminal=False)
            if remaining:
                continue
            self.repo.delete_session(session.session_id)
            report.sessions_cleaned.append(
                SessionCleanupAction(session.session_id, session.taskname)
            )

    # ------------------------------------------------- C 组（提示部分）

    def _note_sealed_groups(self, report: RecoveryReport) -> None:
        for group in self.repo.list_upload_groups():
            if group.state.value == "sealed":
                report.sealed_groups.append(group.group_key)
            elif group.is_expired:
                logger.warning(
                    "上传组 %s 已过期（expires_at=%s），其远端稿件 %s 仍会被复用；"
                    "如需停止追加，请将其置为 sealed。",
                    group.group_key, group.expires_at, group.remote_id,
                )

    # ------------------------------------------------- 小工具（可替换便于测试）

    @staticmethod
    def _exists(path: str | None) -> bool:
        return bool(path) and os.path.exists(path)

    def _is_valid(self, path: str | None) -> bool:
        """完整性校验：大小与时长都满足最低要求。"""
        if not self._exists(path):
            return False
        try:
            size = os.path.getsize(path)
        except OSError:
            return False
        if self.config.min_valid_size_mb and \
                size < self.config.min_valid_size_mb * 1024 * 1024:
            return False
        _, duration = self._probe_size_duration(path)
        if self.config.min_valid_duration and \
                (duration is None or duration < self.config.min_valid_duration):
            return False
        return True

    def _probe_size_duration(self, path: str | None):
        """返回 ``(size, duration)``；探测失败时时长为 ``None``。"""
        if not self._exists(path):
            return None, None
        try:
            size = os.path.getsize(path)
        except OSError:
            size = None
        if self._probe is None:
            from DMR.utils import FFprobe

            probe = FFprobe.get_duration
        else:
            probe = self._probe
        try:
            duration = float(probe(path))
        except Exception:
            logger.debug("无法探测 %s 的时长。", path, exc_info=True)
            duration = None
        return size, duration

    @staticmethod
    def _derive_final_path(part_path: str) -> str:
        """``xxx.flv.part`` → ``xxx.flv``；否则去掉 ``.part`` 后缀。"""
        if part_path.endswith(".part"):
            return part_path[: -len(".part")]
        root, ext = os.path.splitext(part_path)
        return root if ext == ".part" else part_path + ".promoted"

    @staticmethod
    def _promote(part_path: str, final_path: str) -> bool:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(final_path)) or ".",
                        exist_ok=True)
            os.replace(part_path, final_path)
            return True
        except OSError:
            logger.exception("把 %s 转正为 %s 失败。", part_path, final_path)
            return False

    @staticmethod
    def _safe_remove(path: str | None) -> None:
        if not path:
            return
        try:
            os.remove(path)
            logger.info("已删除中断产物文件 %s。", path)
        except OSError:
            logger.debug("删除 %s 失败。", path, exc_info=True)
