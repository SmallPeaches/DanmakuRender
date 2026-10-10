"""``DMR.state`` 状态仓储的模块级测试（P1）。

全部用例使用内存库（``:memory:``），不碰磁盘、不联网，毫秒级完成。
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest

from DMR.state import (
    SCHEMA_VERSION,
    ArtifactKind,
    ArtifactState,
    StateRepository,
    UploadGroupState,
    coerce_artifact_state,
    coerce_upload_group_state,
)
from unit_tests.support import DMRTestCase


class _RepoTestCase(DMRTestCase):
    """共享：每个用例一个独立的内存库。"""

    def setUp(self) -> None:
        super().setUp()
        self.repo = StateRepository(":memory:").open()
        self.addCleanup(self.repo.close)

    def make_session(self, session_id="sess-1", **kwargs):
        kwargs.setdefault("streamer_name", "测试主播")
        kwargs.setdefault("title", "测试标题")
        kwargs.setdefault("platform", "bilibili")
        kwargs.setdefault("room_id", "123")
        return self.repo.create_session(session_id, "testtask", **kwargs)


class TestSchema(_RepoTestCase):

    def test_fresh_db_is_at_current_version(self):
        self.assertEqual(self.repo.schema_version, SCHEMA_VERSION)

    def test_reopening_keeps_version_and_data(self):
        """同一文件重复打开不应重建或丢数据。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "dmr_state.db")
            with StateRepository(path).open() as repo:
                repo.create_session("s1", "t", streamer_name="A")
            with StateRepository(path).open() as repo:
                self.assertEqual(repo.schema_version, SCHEMA_VERSION)
                self.assertIsNotNone(repo.get_session("s1"))

    def test_newer_schema_version_is_rejected(self):
        """比程序更新的库必须拒绝启动，而不是静默降级。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "dmr_state.db")
            StateRepository(path).open().close()
            conn = sqlite3.connect(path)
            try:
                conn.execute("INSERT INTO schema_version(version, applied_at)"
                             " VALUES(?, ?)", (SCHEMA_VERSION + 5, 0))
                conn.commit()
            finally:
                conn.close()

            repo = StateRepository(path)
            try:
                with self.assertRaises(RuntimeError):
                    repo.open()
            finally:
                # 即便 open() 抛错也要释放连接，否则 Windows 下无法清理临时目录
                repo.close()

    def test_wal_mode_enabled_for_file_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "dmr_state.db")
            with StateRepository(path).open() as repo:
                mode = repo.conn.execute("PRAGMA journal_mode").fetchone()[0]
            self.assertEqual(str(mode).lower(), "wal")


class TestSessions(_RepoTestCase):

    def test_create_and_read_back(self):
        session = self.make_session(
            platform="bilibili", room_id="1746", room_url="https://live.bilibili.com/1746",
            streamer_uid="999", group_id="23333",
        )
        loaded = self.repo.get_session("sess-1")

        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.session_id, session.session_id)
        self.assertEqual(loaded.taskname, "testtask")
        self.assertEqual(loaded.platform, "bilibili")
        self.assertEqual(loaded.room_id, "1746")
        self.assertEqual(loaded.streamer_name, "测试主播")
        self.assertEqual(loaded.streamer_uid, "999")
        self.assertEqual(loaded.title, "测试标题")
        self.assertEqual(loaded.group_id, "23333")
        self.assertFalse(loaded.is_ended)

    def test_create_is_idempotent(self):
        """重复登记同一 session_id 不应报错，也不应覆盖已有元信息。"""
        first = self.make_session(title="第一次的标题")
        again = self.repo.create_session("sess-1", "othertask", title="第二次的标题")

        self.assertEqual(again.title, "第一次的标题")
        self.assertEqual(again.taskname, first.taskname)
        self.assertEqual(len(self.repo.list_sessions()), 1)

    def test_end_session_marks_ended(self):
        self.make_session()
        self.repo.end_session("sess-1")
        loaded = self.repo.get_session("sess-1")
        self.assertTrue(loaded.is_ended)
        self.assertIsNotNone(loaded.ended_at)

    def test_touch_session_refreshes_updated_at(self):
        self.make_session()
        before = self.repo.get_session("sess-1").updated_at
        self.repo.conn.execute("UPDATE sessions SET updated_at=updated_at-1000"
                               " WHERE session_id='sess-1'")
        self.repo.conn.commit()

        self.repo.touch_session("sess-1")

        self.assertGreater(self.repo.get_session("sess-1").updated_at, before - 1000)

    def test_list_by_taskname_filters(self):
        self.repo.create_session("s1", "taskA")
        self.repo.create_session("s2", "taskB")
        self.assertEqual(len(self.repo.list_sessions("taskA")), 1)
        self.assertEqual(len(self.repo.list_sessions()), 2)


class TestArtifacts(_RepoTestCase):

    def test_round_trip_all_fields(self):
        self.make_session()
        self.repo.upsert_artifact(
            "a1", "sess-1", 1, ArtifactKind.SOURCE, ArtifactState.RECORDED,
            path="seg1.flv", part_path=None, size=1024, duration=600.5,
            resolution=(1920, 1080), origin="sess-1:1:src_video_pre",
        )

        artifact = self.repo.get_artifact("a1")

        self.assertEqual(artifact.kind, ArtifactKind.SOURCE)
        self.assertEqual(artifact.state, ArtifactState.RECORDED)
        self.assertEqual(artifact.path, "seg1.flv")
        self.assertEqual(artifact.size, 1024)
        self.assertAlmostEqual(artifact.duration, 600.5)
        self.assertEqual(artifact.resolution, (1920, 1080))
        self.assertEqual(artifact.origin, "sess-1:1:src_video_pre")
        self.assertEqual(artifact.segment_idx, 1)

    def test_upsert_preserves_path_when_not_given(self):
        """只改状态时不应把已记录的路径清空。"""
        self.make_session()
        self.repo.upsert_artifact("a1", "sess-1", 1, ArtifactKind.SOURCE,
                                  ArtifactState.RECORDING, part_path="seg1.part")

        self.repo.set_artifact_state("a1", ArtifactState.RECORDED)

        artifact = self.repo.get_artifact("a1")
        self.assertEqual(artifact.part_path, "seg1.part")
        self.assertEqual(artifact.state, ArtifactState.RECORDED)

    def test_set_artifact_path_records_final_file(self):
        self.make_session()
        self.repo.upsert_artifact("a1", "sess-1", 1, ArtifactKind.SOURCE,
                                  ArtifactState.RECORDING, part_path="seg1.part")

        self.repo.set_artifact_path("a1", path="seg1.flv", part_path=None,
                                    size=2048, duration=700, resolution=(1280, 720))

        artifact = self.repo.get_artifact("a1")
        self.assertEqual(artifact.path, "seg1.flv")
        self.assertIsNone(artifact.part_path)
        self.assertEqual(artifact.resolution, (1280, 720))

    def test_unique_constraint_per_session_segment_kind(self):
        """同一场次同一分段同一产物种类只能有一条记录。"""
        self.make_session()
        self.repo.upsert_artifact("a1", "sess-1", 1, ArtifactKind.SOURCE,
                                  ArtifactState.RECORDED)
        with self.assertRaises(sqlite3.IntegrityError):
            self.repo.conn.execute(
                "INSERT INTO artifacts(artifact_id, session_id, segment_idx, kind,"
                " state, updated_at) VALUES('a2','sess-1',1,'src_video','recorded',0)"
            )

    def test_cascade_delete_with_session(self):
        self.make_session()
        self.repo.upsert_artifact("a1", "sess-1", 1, ArtifactKind.SOURCE,
                                  ArtifactState.RECORDED)
        self.repo.delete_session("sess-1")
        self.assertIsNone(self.repo.get_artifact("a1"))

    def test_foreign_key_requires_existing_session(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.repo.upsert_artifact("a1", "no-such-session", 1,
                                      ArtifactKind.SOURCE, ArtifactState.RECORDED)

    def test_list_filters_by_state_and_terminality(self):
        self.make_session()
        self.repo.upsert_artifact("a1", "sess-1", 1, ArtifactKind.SOURCE,
                                  ArtifactState.RECORDED)
        self.repo.upsert_artifact("a2", "sess-1", 2, ArtifactKind.SOURCE,
                                  ArtifactState.UPLOADED)
        self.repo.upsert_artifact("a3", "sess-1", 3, ArtifactKind.SOURCE,
                                  ArtifactState.UPLOADING)

        self.assertEqual(len(self.repo.list_artifacts()), 3)
        self.assertEqual(len(self.repo.list_artifacts(terminal=True)), 1)
        non_terminal = {a.artifact_id for a in self.repo.list_artifacts(terminal=False)}
        self.assertEqual(non_terminal, {"a1", "a3"})
        only_uploading = self.repo.list_artifacts(states=[ArtifactState.UPLOADING])
        self.assertEqual([a.artifact_id for a in only_uploading], ["a3"])

    def test_terminal_flag_matches_enums(self):
        self.make_session()
        self.repo.upsert_artifact("a1", "sess-1", 1, ArtifactKind.SOURCE,
                                  ArtifactState.UPLOADED)
        self.repo.upsert_artifact("a2", "sess-1", 2, ArtifactKind.SOURCE,
                                  ArtifactState.CLEANED)
        self.repo.upsert_artifact("a3", "sess-1", 3, ArtifactKind.SOURCE,
                                  ArtifactState.MISSING)
        self.repo.upsert_artifact("a4", "sess-1", 4, ArtifactKind.SOURCE,
                                  ArtifactState.SKIPPED)
        self.repo.upsert_artifact("a5", "sess-1", 5, ArtifactKind.SOURCE,
                                  ArtifactState.RECORDED)

        for artifact_id in ("a1", "a2", "a3", "a4"):
            self.assertTrue(self.repo.get_artifact(artifact_id).is_terminal)
        self.assertFalse(self.repo.get_artifact("a5").is_terminal)

    def test_bump_attempts(self):
        self.make_session()
        self.repo.upsert_artifact("a1", "sess-1", 1, ArtifactKind.SOURCE,
                                  ArtifactState.RECORDED)

        self.repo.set_artifact_state("a1", ArtifactState.INTERRUPTED,
                                     last_error="part validation failed",
                                     bump_attempts=True)

        artifact = self.repo.get_artifact("a1")
        self.assertEqual(artifact.attempts, 1)
        self.assertEqual(artifact.last_error, "part validation failed")


class TestUploadGroups(_RepoTestCase):
    """上传组只记远端身份，不记分P清单。"""

    def test_create_then_store_remote_id(self):
        group = self.repo.get_or_create_upload_group(
            "g_23333_src_video_0", taskname="testtask", target="bilibili",
            account="main", engine="biliwebapi",
        )
        self.assertEqual(group.state, UploadGroupState.OPEN)
        self.assertIsNone(group.remote_id)

        self.repo.set_upload_group_remote("g_23333_src_video_0", "BV1xx411c7mD",
                                         remote_url="https://www.bilibili.com/video/BV1xx411c7mD")

        loaded = self.repo.get_upload_group("g_23333_src_video_0")
        self.assertEqual(loaded.remote_id, "BV1xx411c7mD")
        self.assertIn("BV1xx411c7mD", loaded.remote_url)

    def test_get_or_create_is_idempotent_and_keeps_remote_id(self):
        """重启后按 group_key 取回 bvid —— 这是"同组放到一起"的关键。"""
        self.repo.get_or_create_upload_group("g1", taskname="t", target="bilibili")
        self.repo.set_upload_group_remote("g1", "BV_REMOTE")

        again = self.repo.get_or_create_upload_group("g1", taskname="t",
                                                     target="bilibili")

        self.assertEqual(again.remote_id, "BV_REMOTE")

    def test_sealed_group_still_readable(self):
        self.repo.get_or_create_upload_group("g1", taskname="t", target="bilibili")
        self.repo.set_upload_group_state("g1", UploadGroupState.SEALED)
        self.assertEqual(self.repo.get_upload_group("g1").state,
                         UploadGroupState.SEALED)

    def test_touch_refreshes_idle_basis(self):
        """``updated_at`` 是空闲过期基准，入组新成员时必须刷新。"""
        self.repo.get_or_create_upload_group("g1", taskname="t", target="bilibili")
        self.repo.conn.execute("UPDATE upload_groups SET updated_at=updated_at-1000"
                               " WHERE group_key='g1'")
        self.repo.conn.commit()

        self.repo.touch_upload_group("g1")

        group = self.repo.get_upload_group("g1")
        self.assertLessEqual(abs(group.updated_at - int(__import__("time").time())), 2)

    def test_expires_at_null_means_never_expires(self):
        group = self.repo.get_or_create_upload_group("g1", taskname="t",
                                                     target="bilibili")
        self.assertIsNone(group.expires_at)
        self.assertFalse(group.is_expired)

    def test_expires_at_past_is_expired(self):
        self.repo.get_or_create_upload_group("g1", taskname="t", target="bilibili",
                                             expires_at=1)
        self.assertTrue(self.repo.get_upload_group("g1").is_expired)

    def test_list_by_taskname(self):
        self.repo.get_or_create_upload_group("g1", taskname="A", target="bilibili")
        self.repo.get_or_create_upload_group("g2", taskname="B", target="bilibili")
        self.assertEqual(len(self.repo.list_upload_groups("A")), 1)


class TestStateCoercion(DMRTestCase):
    """未知状态取值必须容错，不能让程序起不来。"""

    def test_unknown_artifact_state_becomes_interrupted(self):
        self.assertEqual(coerce_artifact_state("no-such-state"),
                         ArtifactState.INTERRUPTED)

    def test_known_artifact_state_passes_through(self):
        self.assertEqual(coerce_artifact_state("recorded"), ArtifactState.RECORDED)

    def test_unknown_upload_group_state_becomes_sealed(self):
        """保守处理：不认识的状态按"不再追加"对待，避免污染既有稿件。"""
        self.assertEqual(coerce_upload_group_state("weird"),
                         UploadGroupState.SEALED)

    def test_malformed_row_does_not_break_reads(self):
        """手工把状态改成垃圾值时，读取仍应成功并降级。"""
        repo = StateRepository(":memory:").open()
        self.addCleanup(repo.close)
        repo.create_session("s1", "t")
        repo.upsert_artifact("a1", "s1", 1, ArtifactKind.SOURCE,
                             ArtifactState.RECORDED)
        repo.conn.execute("UPDATE artifacts SET state='garbage' WHERE artifact_id='a1'")
        repo.conn.commit()

        artifact = repo.get_artifact("a1")

        self.assertEqual(artifact.state, ArtifactState.INTERRUPTED)

    def test_malformed_kind_falls_back_to_source(self):
        repo = StateRepository(":memory:").open()
        self.addCleanup(repo.close)
        repo.create_session("s1", "t")
        repo.upsert_artifact("a1", "s1", 1, ArtifactKind.SOURCE,
                             ArtifactState.RECORDED)
        repo.conn.execute("UPDATE artifacts SET kind='weird' WHERE artifact_id='a1'")
        repo.conn.commit()

        self.assertEqual(repo.get_artifact("a1").kind, ArtifactKind.SOURCE)


class TestMeta(_RepoTestCase):

    def test_set_and_get(self):
        self.repo.set_meta("last_reconcile", "12345")
        self.assertEqual(self.repo.get_meta("last_reconcile"), "12345")

    def test_missing_key_returns_default(self):
        self.assertIsNone(self.repo.get_meta("nope"))
        self.assertEqual(self.repo.get_meta("nope", "fallback"), "fallback")


if __name__ == "__main__":
    unittest.main()
