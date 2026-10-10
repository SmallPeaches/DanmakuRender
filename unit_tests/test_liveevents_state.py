"""``LiveEvents`` 状态镜像到状态库的测试（P1 最后一项）。

P1 的目标是让进程重启后仍知道"哪些分段还没渲染/上传/清理"。``state_dict`` 仍是
运行时真相，这里验证的是它被**镜像**到状态库的结果。

用例不联网、不起线程：``LiveEvents`` 由 ``make_live_events`` 通过 ``__new__`` 构造，
状态库用内存库；需要文件时在临时目录造。
"""
from __future__ import annotations

import os
import tempfile
import unittest
from types import SimpleNamespace

from DMR.state import (
    ArtifactKind,
    ArtifactState,
    StateRepository,
    make_artifact_key,
)
from unit_tests.support import DMRTestCase


class _SyncTestCase(DMRTestCase):
    """共享：内存状态库 + 已注入状态库的 LiveEvents。"""

    def setUp(self) -> None:
        super().setUp()
        self.repo = StateRepository(":memory:").open()
        self.addCleanup(self.repo.close)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmpdir = self._tmp.name

    def make_events(self, *, with_repo: bool = True, **kwargs):
        events = self.make_live_events(**kwargs)
        if with_repo:
            events.state_repo = self.repo
        return events

    def path(self, name: str) -> str:
        return os.path.join(self.tmpdir, name)

    def artifact(self, group_id, kind, segment_idx):
        return self.repo.get_artifact(make_artifact_key(group_id, kind, segment_idx))

    @staticmethod
    def make_video(path, *, segment_id=1, group_id="g1", duration=600.0,
                   dm_file_id=None, upload_group_id=None):
        info = SimpleNamespace(
            path=path, segment_id=segment_id, group_id=group_id, duration=duration,
            dm_file_id=dm_file_id, size=1024, resolution=(1920, 1080),
            title="标题", streamer=None, ctime=None,
        )
        if upload_group_id is not None:
            info.upload_group_id = upload_group_id
        return info


class TestSessionEnsure(_SyncTestCase):
    """场次按需补建（渲染/上传可能先于录制登记发生）。"""

    def test_session_is_created_on_demand(self):
        events = self.make_events()

        self.assertTrue(events._ensure_session("g1"))

        session = self.repo.get_session("g1")
        self.assertIsNotNone(session)
        self.assertEqual(session.taskname, events.name)

    def test_existing_session_is_not_overwritten(self):
        """录制侧已登记的元信息（主播名等）必须保留。"""
        self.repo.create_session("g1", "othertask", streamer_name="主播甲")
        events = self.make_events()

        events._ensure_session("g1")

        session = self.repo.get_session("g1")
        self.assertEqual(session.taskname, "othertask")
        self.assertEqual(session.streamer_name, "主播甲")

    def test_empty_group_id_is_rejected(self):
        events = self.make_events()
        self.assertFalse(events._ensure_session(""))

    def test_without_repo_returns_false(self):
        events = self.make_events(with_repo=False)
        self.assertFalse(events._ensure_session("g1"))


class TestSyncArtifact(_SyncTestCase):
    """产物状态镜像。"""

    def test_creates_artifact_when_missing(self):
        events = self.make_events()

        events._sync_artifact("g1", "src_video", 1, path="seg1.flv",
                              state=ArtifactState.RECORDED)

        artifact = self.artifact("g1", ArtifactKind.SOURCE, 1)
        self.assertIsNotNone(artifact)
        self.assertEqual(artifact.state, ArtifactState.RECORDED)
        self.assertEqual(artifact.path, "seg1.flv")

    def test_updates_state_without_touching_path(self):
        """只改状态时不得丢掉已记录的路径（载荷合并语义）。"""
        events = self.make_events()
        events._sync_artifact("g1", "src_video", 1, path="seg1.flv",
                              state=ArtifactState.RECORDED)

        events._sync_artifact("g1", "src_video", 1,
                              state=ArtifactState.UPLOADED)

        artifact = self.artifact("g1", ArtifactKind.SOURCE, 1)
        self.assertEqual(artifact.state, ArtifactState.UPLOADED)
        self.assertEqual(artifact.path, "seg1.flv")

    def test_none_state_does_not_write(self):
        """``state=None`` 且内存状态为 None 时不写入 —— 不能把 RECORDED 覆盖成"未处理"。"""
        events = self.make_events()
        events._sync_artifact("g1", "src_video", 1, path="seg1.flv",
                              state=ArtifactState.RECORDED)
        events.state_dict["g1"] = [self.blank_state()]   # 三个槽位状态均为 None

        events._sync_artifact("g1", "src_video", 1)

        self.assertEqual(self.artifact("g1", ArtifactKind.SOURCE, 1).state,
                         ArtifactState.RECORDED, "不得被 None 覆盖")

    def test_state_derived_from_memory(self):
        """未显式给出状态时，应能从内存状态推导。"""
        events = self.make_events()
        state = self.blank_state()
        state["src_video"].update({"status": "uploading",
                                   "file": self.make_video(self.path("seg1.flv"))})
        events.state_dict["g1"] = [state]

        events._sync_artifact("g1", "src_video", 1)

        artifact = self.artifact("g1", ArtifactKind.SOURCE, 1)
        self.assertEqual(artifact.state, ArtifactState.UPLOADING)
        self.assertEqual(artifact.path, self.path("seg1.flv"))

    def test_danmaku_attachment_is_recorded(self):
        events = self.make_events()
        video = self.make_video(self.path("seg1.flv"), dm_file_id="seg1.ass")

        events._sync_artifact("g1", "src_video", 1, path=video,
                              state=ArtifactState.RECORDED)

        artifact = self.artifact("g1", ArtifactKind.SOURCE, 1)
        self.assertEqual(artifact.path, self.path("seg1.flv"))
        self.assertEqual(artifact.danmaku_path, "seg1.ass")

    def test_unknown_vtype_is_ignored(self):
        events = self.make_events()
        events._sync_artifact("g1", "not_a_slot", 1, state=ArtifactState.RECORDED)
        self.assertEqual(self.repo.list_artifacts(), [])

    def test_without_repo_is_a_noop(self):
        events = self.make_events(with_repo=False)
        events._sync_artifact("g1", "src_video", 1, state=ArtifactState.RECORDED)

    def test_repository_error_does_not_propagate(self):
        """同步失败绝不能影响录制/上传主流程。"""
        events = self.make_events()

        class Broken:
            def create_session(self, *a, **kw):
                raise RuntimeError('db locked')

        events.state_repo = Broken()
        events._sync_artifact("g1", "src_video", 1, state=ArtifactState.RECORDED)

    def test_all_three_slots_map_to_distinct_kinds(self):
        events = self.make_events()
        for vtype, kind in (("src_video", ArtifactKind.SOURCE),
                            ("src_video_pre", ArtifactKind.SOURCE_PRE),
                            ("dm_video", ArtifactKind.DANMAKU_VIDEO)):
            events._sync_artifact("g1", vtype, 1, path=f"{vtype}.mp4",
                                  state=ArtifactState.RECORDED)

        kinds = {a.kind for a in self.repo.list_artifacts()}
        self.assertEqual(kinds, {ArtifactKind.SOURCE, ArtifactKind.SOURCE_PRE,
                                 ArtifactKind.DANMAKU_VIDEO})


class TestUploadFlowSync(_SyncTestCase):
    """上传流程：上传组登记 + 产物标为 UPLOADING/UPLOADED。"""

    def _events_with_upload(self, *, realtime=True):
        return self.make_events(
            common_event_args={"auto_render": False, "auto_upload": True,
                               "auto_clean": False, "auto_transcode": False},
            upload_args={"src_video": [{
                "engine": "biliwebapi", "target": "bilibili",
                "account": "main", "realtime": realtime, "min_length": 120,
            }]},
        )

    def test_realtime_upload_registers_group_and_marks_uploading(self):
        events = self._events_with_upload()
        state = self.blank_state()
        state["src_video"].update({
            "status": "ready",
            "file": self.make_video(self.path("seg1.flv"), segment_id=1),
        })
        events.state_dict["g1"] = [state]

        messages = events._check_for_upload("g1")

        self.assertEqual(len(messages), 1)
        group_key = messages[0].data["upload_group"]
        group = self.repo.get_upload_group(group_key)
        self.assertIsNotNone(group, "上传组应被登记，供上传器回写 bvid")
        self.assertEqual(group.target, "bilibili")
        self.assertEqual(group.account, "main")
        self.assertEqual(self.artifact("g1", ArtifactKind.SOURCE, 1).state,
                         ArtifactState.UPLOADING)

    def test_group_key_matches_message(self):
        """状态库里的上传组键必须与消息里的键完全一致。

        否则上传器回写的 bvid 会落到另一个键上，"同组进同一稿件"失效。
        """
        events = self._events_with_upload()
        state = self.blank_state()
        state["src_video"].update({
            "status": "ready",
            "file": self.make_video(self.path("seg1.flv"), upload_group_id="23333"),
        })
        events.state_dict["g1"] = [state]

        messages = events._check_for_upload("g1")
        group_key = messages[0].data["upload_group"]

        self.assertTrue(group_key.startswith("23333_"))
        self.assertIsNotNone(self.repo.get_upload_group(group_key))

    def test_non_realtime_marks_all_segments_uploading(self):
        events = self._events_with_upload(realtime=False)
        states = []
        for idx in (1, 2):
            state = self.blank_state()
            state["src_video"].update({
                "status": "ready",
                "file": self.make_video(self.path(f"seg{idx}.flv"),
                                        segment_id=idx),
            })
            states.append(state)
        events.state_dict["g1"] = states
        events.ended_dict["g1"] = 1

        messages = events._check_for_upload("g1")

        self.assertEqual(len(messages), 1)
        for idx in (1, 2):
            self.assertEqual(self.artifact("g1", ArtifactKind.SOURCE, idx).state,
                             ArtifactState.UPLOADING)

    def test_upload_end_marks_uploaded(self):
        events = self._events_with_upload()
        state = self.blank_state()
        state["src_video"].update({
            "status": "ready",
            "file": self.make_video(self.path("seg1.flv")),
        })
        events.state_dict["g1"] = [state]
        messages = events._check_for_upload("g1")
        request_id = messages[0].request_id

        from DMR.utils import PipeMessage
        events.onUploadEnd(PipeMessage(source='uploader', target='replay/testtask',
                                       event='end', request_id=request_id,
                                       data={}))

        self.assertEqual(self.artifact("g1", ArtifactKind.SOURCE, 1).state,
                         ArtifactState.UPLOADED)

    def test_upload_end_waits_for_all_requests(self):
        """同一产物有多个上传目标时，只有全部结束才算已上传。"""
        events = self.make_events(
            common_event_args={"auto_render": False, "auto_upload": True,
                               "auto_clean": False, "auto_transcode": False},
            upload_args={"src_video": [
                {"engine": "biliwebapi", "target": "bilibili", "account": "a",
                 "realtime": True, "min_length": 0},
                {"engine": "biliwebapi", "target": "bilibili", "account": "b",
                 "realtime": True, "min_length": 0},
            ]},
        )
        state = self.blank_state()
        state["src_video"].update({
            "status": "ready",
            "file": self.make_video(self.path("seg1.flv")),
        })
        events.state_dict["g1"] = [state]
        messages = events._check_for_upload("g1")
        self.assertEqual(len(messages), 2)

        from DMR.utils import PipeMessage
        events.onUploadEnd(PipeMessage(source='uploader', target='replay/testtask',
                                       event='end',
                                       request_id=messages[0].request_id, data={}))
        self.assertEqual(self.artifact("g1", ArtifactKind.SOURCE, 1).state,
                         ArtifactState.UPLOADING, "还有一个请求未结束")

        events.onUploadEnd(PipeMessage(source='uploader', target='replay/testtask',
                                       event='end',
                                       request_id=messages[1].request_id, data={}))
        self.assertEqual(self.artifact("g1", ArtifactKind.SOURCE, 1).state,
                         ArtifactState.UPLOADED)


class TestRenderAndCleanSync(_SyncTestCase):
    """渲染与清理完成后的镜像。"""

    def test_render_end_marks_rendered(self):
        events = self.make_events()
        state = self.blank_state()
        state["dm_video"].update({"status": "rendering",
                                  "file": None, "wait": ["req-1"]})
        events.state_dict["g1"] = [state]
        events._sync_artifact("g1", "dm_video", 1, state=ArtifactState.RENDERING)

        from DMR.utils import PipeMessage
        output = self.make_video(self.path("dm.mp4"))
        events.onRenderEnd(PipeMessage(source='render', target='replay/testtask',
                                       event='end', request_id="req-1",
                                       data={'output': output}))

        artifact = self.artifact("g1", ArtifactKind.DANMAKU_VIDEO, 1)
        self.assertEqual(artifact.state, ArtifactState.RENDERED)
        self.assertEqual(artifact.path, self.path("dm.mp4"))

    def test_clean_marks_cleaned_when_rule_matches(self):
        events = self.make_events(
            common_event_args={"auto_render": False, "auto_upload": True,
                               "auto_clean": True, "auto_transcode": False},
            clean_args={"src_video": [{"method": "delete", "delay": 0}]},
        )
        state = self.blank_state()
        state["src_video"].update({
            "status": "uploaded",
            "file": self.make_video(self.path("seg1.flv")),
        })
        events.state_dict["g1"] = [state]

        events._check_for_clean()

        self.assertEqual(self.artifact("g1", ArtifactKind.SOURCE, 1).state,
                         ArtifactState.CLEANED)

    def test_no_matching_rule_leaves_state_uploaded(self):
        """没有命中清理规则时，状态库里也必须保持 uploaded（B7.2）。"""
        events = self.make_events(
            common_event_args={"auto_render": False, "auto_upload": True,
                               "auto_clean": True, "auto_transcode": False},
            clean_args={"dm_video": [{"method": "delete", "delay": 0}]},
        )
        state = self.blank_state()
        state["src_video"].update({
            "status": "uploaded",
            "file": self.make_video(self.path("seg1.flv")),
        })
        events.state_dict["g1"] = [state]
        events._sync_artifact("g1", "src_video", 1, state=ArtifactState.UPLOADED)

        events._check_for_clean()

        self.assertEqual(self.artifact("g1", ArtifactKind.SOURCE, 1).state,
                         ArtifactState.UPLOADED)


class TestLiveSegmentSync(_SyncTestCase):
    """``onLiveSegment`` 也应把分段登记为 RECORDED（覆盖不经下载器的路径）。"""

    def test_segment_is_registered_on_arrival(self):
        events = self.make_events()
        video = self.make_video(self.path("seg1.flv"))

        from DMR.utils import PipeMessage
        events.onLiveSegment(PipeMessage(source='downloader',
                                        target='replay/testtask',
                                        event='livesegment', msg='ok',
                                        dtype='VideoInfo', data=video))

        artifact = self.artifact("g1", ArtifactKind.SOURCE, 1)
        self.assertIsNotNone(artifact)
        self.assertEqual(artifact.state, ArtifactState.RECORDED)
        self.assertEqual(artifact.path, self.path("seg1.flv"))


if __name__ == "__main__":
    unittest.main()
