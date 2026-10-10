"""``DMR.state.reconciler`` 启动对账的模块级测试（P1）。

用例在临时目录里造出"磁盘事实"，并注入假的时长探测器，
从而不需要真实媒体文件、ffprobe、网络或子进程。
"""
from __future__ import annotations

import os
import tempfile
import unittest

from DMR.state import (
    ArtifactKind,
    ArtifactState,
    InterruptedFileAction,
    RecoveryConfig,
    RecoveryManager,
    StateRepository,
)
from unit_tests.support import DMRTestCase

MB = 1024 * 1024


class _FakeProbe:
    """假时长探测器：记录调用并返回预设时长。"""

    def __init__(self, duration: float | None = 600.0) -> None:
        self.duration = duration
        self.calls: list[str] = []

    def __call__(self, path: str):
        self.calls.append(path)
        if self.duration is None:
            raise RuntimeError("probe failed")
        return self.duration


class _RecoveryTestCase(DMRTestCase):
    """共享：内存状态库 + 临时目录 + 注入的探测器。"""

    def setUp(self) -> None:
        super().setUp()
        self.repo = StateRepository(":memory:").open()
        self.addCleanup(self.repo.close)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmpdir = self._tmp.name
        self.probe = _FakeProbe()
        # ⚠️ 必须锚定真实时间：状态库用 ``time.time()`` 写 ``updated_at``，
        # 若这里写死一个未来的常数，所有产物都会被算成"已过期"。
        self.now = int(__import__("time").time())

    # --- 辅助 ---

    def path(self, name: str) -> str:
        return os.path.join(self.tmpdir, name)

    def write(self, name: str, size_mb: float = 10.0) -> str:
        """造一个指定大小的文件，返回路径。"""
        target = self.path(name)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as handle:
            handle.write(b"\0" * int(size_mb * MB))
        return target

    def make_session(self, session_id: str = "sess-1", **kwargs):
        return self.repo.create_session(session_id, "testtask", **kwargs)

    def make_artifact(self, state, *, artifact_id="a1", session_id="sess-1",
                      segment_idx=1, kind=ArtifactKind.SOURCE,
                      path=None, part_path=None, size=None, duration=None,
                      updated_at=None):
        artifact = self.repo.upsert_artifact(
            artifact_id, session_id, segment_idx, kind, state,
            path=path, part_path=part_path, size=size, duration=duration,
        )
        if updated_at is not None:
            self.repo.conn.execute(
                "UPDATE artifacts SET updated_at=? WHERE artifact_id=?",
                (updated_at, artifact_id),
            )
            self.repo.conn.commit()
        return artifact

    #: 用例里用的小文件阈值：这些用例构造的是 10MB 文件并讨论"够不够大"，
    #: 因此显式声明阈值，不依赖 ``min_valid_size_mb`` 的默认值（默认 30MB）——
    #: 否则调整默认值会连带改变这些用例的语义。
    SMALL_THRESHOLD_MB = 1.0

    def manager(self, **kwargs) -> RecoveryManager:
        kwargs.setdefault("min_valid_size_mb", self.SMALL_THRESHOLD_MB)
        config = RecoveryConfig(**kwargs)
        return RecoveryManager(self.repo, config, probe=self.probe,
                               now=lambda: self.now)


class TestStep0Sanitize(_RecoveryTestCase):
    """第 0 步：运行中状态一律不可信。"""

    def test_recording_becomes_interrupted(self):
        self.make_session()
        self.make_artifact(ArtifactState.RECORDING, part_path=self.write("a.part"))

        report = self.manager(on_interrupted_file=InterruptedFileAction.ASK).reconcile()

        self.assertEqual(len(report.unstable), 1)
        self.assertEqual(report.unstable[0].from_state, ArtifactState.RECORDING)
        self.assertEqual(report.unstable[0].to_state, ArtifactState.INTERRUPTED)

    def test_rendering_becomes_recorded(self):
        self.make_session()
        final = self.write("a.flv")
        self.make_artifact(ArtifactState.RENDERING, path=final)

        self.manager().reconcile()

        self.assertEqual(self.repo.get_artifact("a1").state, ArtifactState.RECORDED)

    def test_uploading_becomes_recorded(self):
        """B站语义：单个文件传一半必须从 0 重传，所以回到 recorded。"""
        self.make_session()
        final = self.write("a.flv")
        self.make_artifact(ArtifactState.UPLOADING, path=final)

        self.manager().reconcile()

        self.assertEqual(self.repo.get_artifact("a1").state, ArtifactState.RECORDED)

    def test_reconcile_is_idempotent(self):
        """对账重复运行不应产生额外变化（第 0 步保证）。"""
        self.make_session()
        final = self.write("a.flv")
        self.make_artifact(ArtifactState.UPLOADING, path=final)

        manager = self.manager()
        first = manager.reconcile()
        second = manager.reconcile()

        self.assertEqual(len(first.unstable), 1)
        self.assertEqual(len(second.unstable), 0, "第二次不应再有运行中状态可净化")
        self.assertEqual(self.repo.get_artifact("a1").state, ArtifactState.RECORDED)


class TestGroupADiskCheck(_RecoveryTestCase):
    """A 组：校验非终态产物的磁盘事实。"""

    def test_a1_part_valid_kept_when_ask(self):
        self.make_session()
        part = self.write("a.flv.part")
        self.make_artifact(ArtifactState.RECORDING, part_path=part)

        report = self.manager(on_interrupted_file=InterruptedFileAction.ASK).reconcile()

        artifact = self.repo.get_artifact("a1")
        self.assertEqual(artifact.state, ArtifactState.INTERRUPTED)
        self.assertTrue(os.path.exists(part), "ask 策略下不应动文件")
        self.assertEqual(report.needs_attention, 1)

    def test_a1_part_valid_promoted_when_keep(self):
        self.make_session()
        part = self.write("a.flv.part", size_mb=10)
        self.make_artifact(ArtifactState.RECORDING, part_path=part)

        report = self.manager(on_interrupted_file=InterruptedFileAction.KEEP).reconcile()

        artifact = self.repo.get_artifact("a1")
        self.assertEqual(artifact.state, ArtifactState.RECORDED)
        self.assertEqual(artifact.path, self.path("a.flv"))
        self.assertIsNone(artifact.part_path, "转正后不应再指向 .part")
        self.assertFalse(os.path.exists(part), ".part 应已被改名")
        self.assertTrue(os.path.exists(self.path("a.flv")))
        self.assertEqual(artifact.size, 10 * MB)
        self.assertAlmostEqual(artifact.duration, 600.0)
        self.assertEqual([a.reason for a in report.interrupted], ["promoted"])

    def test_a1_part_valid_discarded_when_discard(self):
        self.make_session()
        part = self.write("a.flv.part")
        self.make_artifact(ArtifactState.RECORDING, part_path=part)

        report = self.manager(
            on_interrupted_file=InterruptedFileAction.DISCARD
        ).reconcile()

        self.assertEqual(self.repo.get_artifact("a1").state, ArtifactState.SKIPPED)
        self.assertFalse(os.path.exists(part), "discard 策略应删除 .part")
        self.assertEqual([a.reason for a in report.interrupted], ["discarded"])

    def test_a2_part_too_small_always_discarded(self):
        """校验失败时即便策略是 keep 也不能转正。"""
        self.make_session()
        part = self.write("a.flv.part", size_mb=0.1)   # 低于 min_valid_size_mb
        self.make_artifact(ArtifactState.RECORDING, part_path=part)

        self.manager(on_interrupted_file=InterruptedFileAction.KEEP).reconcile()

        artifact = self.repo.get_artifact("a1")
        self.assertEqual(artifact.state, ArtifactState.INTERRUPTED)
        self.assertIn("校验未通过", artifact.last_error)
        self.assertGreaterEqual(artifact.attempts, 1)

    def test_a2_part_unprobeable_is_invalid(self):
        """时长探测失败视为校验不通过。"""
        self.make_session()
        part = self.write("a.flv.part")
        self.make_artifact(ArtifactState.RECORDING, part_path=part)
        self.probe.duration = None

        self.manager(on_interrupted_file=InterruptedFileAction.KEEP).reconcile()

        self.assertEqual(self.repo.get_artifact("a1").state,
                         ArtifactState.INTERRUPTED)

    def test_a2_part_too_short_always_discarded(self):
        self.make_session()
        part = self.write("a.flv.part")
        self.make_artifact(ArtifactState.RECORDING, part_path=part)
        self.probe.duration = 5.0                      # 低于 min_valid_duration

        self.manager(on_interrupted_file=InterruptedFileAction.KEEP).reconcile()

        self.assertEqual(self.repo.get_artifact("a1").state,
                         ArtifactState.INTERRUPTED)

    def test_a3_nothing_on_disk_becomes_missing(self):
        self.make_session()
        self.make_artifact(ArtifactState.RECORDING,
                           part_path=self.path("gone.flv.part"))

        report = self.manager().reconcile()

        self.assertEqual(self.repo.get_artifact("a1").state, ArtifactState.MISSING)
        self.assertEqual(len(report.missing), 1)

    def test_a4_final_file_present_is_restored_to_recorded(self):
        """rename 成功但状态没落库的情况。"""
        self.make_session()
        final = self.write("a.flv")
        self.make_artifact(ArtifactState.RECORDING, path=final,
                           part_path=self.path("a.flv.part"))

        report = self.manager().reconcile()

        self.assertEqual(self.repo.get_artifact("a1").state, ArtifactState.RECORDED)
        self.assertEqual([a.reason for a in report.interrupted], ["promoted"])

    def test_a5_stable_state_with_existing_file_is_untouched(self):
        self.make_session()
        final = self.write("a.flv")
        before = self.make_artifact(ArtifactState.RECORDED, path=final)

        report = self.manager().reconcile()

        artifact = self.repo.get_artifact("a1")
        self.assertEqual(artifact.state, ArtifactState.RECORDED)
        self.assertEqual(artifact.updated_at, before.updated_at,
                         "未发生变化的产物不应被刷新")
        self.assertEqual(report.missing, [])

    def test_a6_missing_file_becomes_missing(self):
        self.make_session()
        self.make_artifact(ArtifactState.RECORDED, path=self.path("gone.flv"))

        report = self.manager().reconcile()

        artifact = self.repo.get_artifact("a1")
        self.assertEqual(artifact.state, ArtifactState.MISSING)
        self.assertEqual(len(report.missing), 1)

    def test_terminal_artifact_is_not_downgraded_to_missing(self):
        """已经上传成功的产物，本地文件被删不应被判为 lost。

        A 组只遍历非终态产物；``UPLOADED`` 属终态，其本地文件缺失是正常情况
        （上传完成后的清理动作）。
        """
        self.make_session()
        self.make_artifact(ArtifactState.UPLOADED, path=self.path("gone.flv"))

        report = self.manager().reconcile()

        self.assertEqual(self.repo.get_artifact("a1").state, ArtifactState.UPLOADED)
        self.assertEqual(report.missing, [], "终态产物不应进入 lost 统计")

    def test_planned_without_file_is_left_alone(self):
        """尚未产生的产物属正常，不应被判为 lost。"""
        self.make_session()
        self.make_artifact(ArtifactState.PLANNED, kind=ArtifactKind.DANMAKU_VIDEO)

        report = self.manager().reconcile()

        self.assertEqual(self.repo.get_artifact("a1").state, ArtifactState.PLANNED)
        self.assertEqual(report.missing, [])


class TestInterruptedFileShapes(_RecoveryTestCase):
    """两种"中断"形态的语义区分（真机 dryrun 暴露过这里的问题）。

    所有下载引擎都**直接写最终文件名**，因此 ``part_path`` 通常**等于** ``path``：

    - **形态 A**（``part == path``）：文件就在正式路径上且有效 → 意味着"其实已经
      录完，只是状态没落库"，可以**无条件**恢复为 ``RECORDED``，与策略无关。
    - **形态 B**（独立的 ``.part``）：即使能被解析，仍只是"可能没写完"的中间产物
      → 必须尊重 ``ask`` / ``keep`` / ``discard``。

    早期实现要求"``.part`` 不存在且正式路径存在"才恢复，导致最常见的形态 A 永远
    走不到恢复分支（``keep`` 形同虚设）。
    """

    def _make(self, *, same_file: bool, size_mb: float = 10.0):
        self.make_session()
        final_path = self.path("seg.flv")
        if same_file:
            final = self.write("seg.flv", size_mb=size_mb)
            return self.make_artifact(ArtifactState.RECORDING, path=final,
                                      part_path=final), final, None
        part = self.write("seg.flv.part", size_mb=size_mb)
        return self.make_artifact(ArtifactState.RECORDING, path=final_path,
                                  part_path=part), final_path, part

    def test_same_file_is_recovered_regardless_of_policy(self):
        for policy in InterruptedFileAction:
            with self.subTest(policy=policy.value):
                self.setUp()
                artifact, final, _ = self._make(same_file=True)

                report = self.manager(on_interrupted_file=policy).reconcile()

                loaded = self.repo.get_artifact("a1")
                self.assertEqual(loaded.state, ArtifactState.RECORDED)
                self.assertEqual(loaded.path, final)
                self.assertIsNone(loaded.part_path)
                self.assertEqual([a.reason for a in report.interrupted],
                                 ["promoted"])

    def test_distinct_part_respects_ask(self):
        artifact, _, part = self._make(same_file=False)

        report = self.manager(on_interrupted_file=InterruptedFileAction.ASK).reconcile()

        self.assertEqual(self.repo.get_artifact("a1").state,
                         ArtifactState.INTERRUPTED)
        self.assertTrue(os.path.exists(part), "ask 不应动文件")
        self.assertEqual([a.reason for a in report.interrupted],
                         ["needs_attention"])

    def test_distinct_part_promoted_with_keep(self):
        artifact, final, part = self._make(same_file=False)

        report = self.manager(on_interrupted_file=InterruptedFileAction.KEEP).reconcile()

        loaded = self.repo.get_artifact("a1")
        self.assertEqual(loaded.state, ArtifactState.RECORDED)
        self.assertEqual(loaded.path, final, "应转正到正式路径")
        self.assertFalse(os.path.exists(part))
        self.assertTrue(os.path.exists(final))
        self.assertEqual([a.reason for a in report.interrupted], ["promoted"])

    def test_distinct_part_removed_with_discard(self):
        artifact, final, part = self._make(same_file=False)

        report = self.manager(
            on_interrupted_file=InterruptedFileAction.DISCARD
        ).reconcile()

        self.assertEqual(self.repo.get_artifact("a1").state, ArtifactState.SKIPPED)
        self.assertFalse(os.path.exists(part))
        self.assertFalse(os.path.exists(final))
        self.assertEqual([a.reason for a in report.interrupted], ["discarded"])

    def test_invalid_part_is_never_promoted(self):
        """``keep`` 也不能转正校验不通过的文件。"""
        self.make_session()
        part = self.write("seg.flv.part", size_mb=0.01)   # 低于 min_valid_size_mb
        self.make_artifact(ArtifactState.RECORDING,
                           path=self.path("seg.flv"), part_path=part)

        report = self.manager(on_interrupted_file=InterruptedFileAction.KEEP).reconcile()

        self.assertEqual(self.repo.get_artifact("a1").state,
                         ArtifactState.INTERRUPTED)
        self.assertEqual([a.reason for a in report.interrupted],
                         ["needs_attention"])

    def test_promote_failure_keeps_needs_attention(self):
        """改名失败（目标被占用等）时应如实报告需要人工处理。"""
        self.make_session()
        part = self.write("seg.flv.part")
        # 目标路径是个目录 → os.replace 会失败
        final = self.path("seg.flv")
        os.makedirs(final)
        self.make_artifact(ArtifactState.RECORDING, path=final, part_path=part)

        report = self.manager(on_interrupted_file=InterruptedFileAction.KEEP).reconcile()

        self.assertEqual([a.reason for a in report.interrupted],
                         ["needs_attention"])
        self.assertTrue(os.path.exists(part), "改名失败时不应丢掉原文件")


class TestGroupDReclaim(_RecoveryTestCase):
    """D 组：回收与内存上限。"""

    def test_d3_stale_non_terminal_is_dropped(self):
        """超过 stale_after 无进展的非终态产物应被抛弃。

        用 ``path=None`` 的产物，使 A 组不会碰它（没有文件可校验），
        从而直接检验 D3 的过期判定。
        """
        self.make_session()
        self.make_artifact(ArtifactState.PLANNED,
                           updated_at=self.now - (8 * 24 * 3600))

        report = self.manager(stale_after=7 * 24 * 3600).reconcile()

        self.assertEqual(self.repo.get_artifact("a1").state, ArtifactState.SKIPPED)
        self.assertEqual(len(report.stale), 1)

    def test_d3_fresh_non_terminal_is_kept(self):
        """单独调用 D 组，避免 A 组刷新 updated_at 而掩盖过期判定。"""
        from DMR.state import RecoveryReport

        self.make_session()
        final = self.write("a.flv")
        self.make_artifact(ArtifactState.RECORDED, path=final,
                           updated_at=self.now - 3600)

        report = RecoveryReport()
        self.manager(stale_after=7 * 24 * 3600)._group_d_reclaim(report)

        self.assertEqual(self.repo.get_artifact("a1").state, ArtifactState.RECORDED)
        self.assertEqual(report.stale, [])

    def test_d4_ended_session_with_all_terminal_is_deleted(self):
        self.make_session()
        self.make_artifact(ArtifactState.CLEANED)
        self.repo.end_session("sess-1")

        report = self.manager().reconcile()

        self.assertIsNone(self.repo.get_session("sess-1"))
        self.assertEqual(len(report.sessions_cleaned), 1)

    def test_d4_ongoing_session_is_kept(self):
        self.make_session()
        self.make_artifact(ArtifactState.UPLOADED)

        report = self.manager().reconcile()

        self.assertIsNotNone(self.repo.get_session("sess-1"))
        self.assertEqual(report.sessions_cleaned, [])

    def test_d4_ended_session_with_pending_artifact_is_kept(self):
        """还有未完成产物时不能清理场次。"""
        self.make_session()
        final = self.write("a.flv")
        self.make_artifact(ArtifactState.RECORDED, path=final)
        self.repo.end_session("sess-1")

        report = self.manager().reconcile()

        self.assertIsNotNone(self.repo.get_session("sess-1"))
        self.assertEqual(report.sessions_cleaned, [])


class TestGroupCUploadGroups(_RecoveryTestCase):
    """C 组：sealed/过期的提示行为，不自动删 bvid。"""

    def test_sealed_group_is_reported_and_remote_id_kept(self):
        self.repo.get_or_create_upload_group("g1", taskname="t", target="bilibili")
        self.repo.set_upload_group_remote("g1", "BV_KEEP")
        self.repo.set_upload_group_state("g1", "sealed")

        report = self.manager().reconcile()

        self.assertEqual(report.sealed_groups, ["g1"])
        group = self.repo.get_upload_group("g1")
        self.assertEqual(group.remote_id, "BV_KEEP", "不得自动清除 bvid")

    def test_expired_group_keeps_remote_id(self):
        """过期只告警：月度合集的 bvid 不能被自动丢掉。"""
        self.repo.get_or_create_upload_group("g1", taskname="t", target="bilibili",
                                            expires_at=1)
        self.repo.set_upload_group_remote("g1", "BV_MONTHLY")

        self.manager().reconcile()

        self.assertEqual(self.repo.get_upload_group("g1").remote_id, "BV_MONTHLY")


class TestReconcileRobustness(_RecoveryTestCase):

    def test_report_summary_is_human_readable(self):
        self.make_session()
        report = self.manager().reconcile()
        self.assertIn("对账完成", report.summary())

    def test_last_reconcile_timestamp_recorded(self):
        self.manager().reconcile()
        self.assertEqual(self.repo.get_meta("last_reconcile_at"), str(self.now))

    def test_no_sessions_is_a_noop(self):
        report = self.manager().reconcile()
        self.assertEqual(report.unstable, [])
        self.assertEqual(report.errors, [])

    def test_probe_not_called_for_missing_files(self):
        """探测器不应在文件不存在时被调用（避免无谓的 ffprobe 子进程）。"""
        self.make_session()
        self.make_artifact(ArtifactState.RECORDED, path=self.path("nope.flv"))

        self.manager().reconcile()

        self.assertEqual(self.probe.calls, [])


class TestRecoveryConfig(DMRTestCase):

    def test_defaults(self):
        config = RecoveryConfig()
        self.assertEqual(config.on_interrupted_file, InterruptedFileAction.ASK)
        self.assertEqual(config.stale_after, 7 * 24 * 3600)
        self.assertIsNone(config.upload_group_expires)
        self.assertEqual(config.idle_release, 300)

    def test_from_mapping_reads_known_keys(self):
        config = RecoveryConfig.from_mapping({
            "on_interrupted_file": "keep",
            "stale_after": 3600,
            "min_valid_duration": 30,
        })
        self.assertEqual(config.on_interrupted_file, InterruptedFileAction.KEEP)
        self.assertEqual(config.stale_after, 3600)
        self.assertEqual(config.min_valid_duration, 30.0)

    def test_from_mapping_ignores_unknown_keys(self):
        """旧配置里残留的 adopt_orphans（功能已删除）不应导致启动失败。"""
        config = RecoveryConfig.from_mapping({
            "on_interrupted_file": "ask",
            "adopt_orphans": True,
            "adopt_without_metadata": True,
        })
        self.assertEqual(config.on_interrupted_file, InterruptedFileAction.ASK)

    def test_from_mapping_invalid_action_falls_back_to_ask(self):
        config = RecoveryConfig.from_mapping({"on_interrupted_file": "nonsense"})
        self.assertEqual(config.on_interrupted_file, InterruptedFileAction.ASK)

    def test_from_mapping_none_returns_defaults(self):
        self.assertEqual(RecoveryConfig.from_mapping(None), RecoveryConfig())


if __name__ == "__main__":
    unittest.main()
