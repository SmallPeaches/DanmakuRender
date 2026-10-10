"""恢复重驱动：重启后把"已录制/已渲染但未完成"的产物送回处理链。

对应服务器上观察到的现象：状态库里有 ``recorded`` 的产物，但重启后既没被改名
也没被上传 —— 原因是 ``reconcile()`` 只对账、不重新驱动。

本文件覆盖三层：
1. 载荷编解码（``video_info`` 的 datetime / tuple / 嵌套 streamer 往返）
2. 重建（``rebuild_video_info`` 的首选路径与回退路径）
3. 选择与注入（``collect_resumable`` 的选取范围；``resume_recovered`` 的注入与派发）
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime

from DMR.state import (
    ArtifactKind,
    ArtifactState,
    RecoveryConfig,
    RecoveryManager,
    RecoveryReport,
    StateRepository,
    decode_video_info,
    encode_video_info,
    make_artifact_key,
    rebuild_video_info,
)
from unit_tests.support import DMRTestCase

MB = 1024 * 1024


class _StateCase(DMRTestCase):
    """共享：内存状态库 + 一个场次。"""

    def setUp(self) -> None:
        super().setUp()
        self.repo = StateRepository(":memory:").open()
        self.addCleanup(self.repo.close)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmpdir = self._tmp.name

    def path(self, name: str) -> str:
        return os.path.join(self.tmpdir, name)

    #: 测试用文件大小：要高于 recovery.min_valid_size_mb 默认值（30MB），
    #: 这样"大小达标"这一条才成立（判定规则见 is_recovered_file_usable）
    FILE_MB = 40.0

    def write(self, name: str, size_mb: float = None) -> str:
        p = self.path(name)
        with open(p, "wb") as f:
            f.write(b"\0" * int((self.FILE_MB if size_mb is None else size_mb) * MB))
        return p

    def make_session(self, session_id="sess-1", taskname="mytask", **kw):
        defaults = dict(platform="twitch", room_id="123",
                        room_url="https://twitch.tv/123",
                        streamer_name="Korooon", streamer_uid="999",
                        title="直播标题")
        defaults.update(kw)
        return self.repo.create_session(session_id, taskname, **defaults)

    def make_artifact(self, state=ArtifactState.RECORDED, *, segment_idx=1,
                      kind=ArtifactKind.SOURCE, session_id="sess-1",
                      path=None, video_info=None, **kw):
        path = path if path is not None else self.write(f"seg{segment_idx}.mkv")
        # 允许用例覆盖 duration/size（例如模拟"时长未知"的旧产物）
        kw.setdefault("size", int(self.FILE_MB * MB))
        kw.setdefault("duration", 600.0)
        return self.repo.upsert_artifact(
            make_artifact_key(session_id, kind, segment_idx),
            session_id, segment_idx, kind, state,
            path=path, resolution=(1920, 1080), video_info=video_info, **kw,
        )


class TestVideoInfoPayload(DMRTestCase):
    """``video_info`` 的载荷编解码。"""

    def test_round_trip_keeps_types(self):
        """datetime 与 tuple 必须还原为原类型。

        类型错了会在文件名模板上炸掉（``{CTIME.YEAR}`` 需要 datetime，
        分辨率元组被当成字符串会让下游解析失败）。
        """
        info = encode_video_info({
            "path": "a.mkv", "title": "t", "duration": 600.0, "size": 100,
            "resolution": (1920, 1080),
            "ctime": datetime(2026, 10, 5, 16, 50, 16),
            "streamer": {"name": "S", "platform": "twitch"},
            "group_id": "g1", "segment_id": 1, "taskname": "mytask",
        })
        # 编码结果必须是纯 JSON 类型（否则写库时会失败）
        json.dumps(info)
        decoded = decode_video_info(info)

        self.assertIsInstance(decoded["ctime"], datetime)
        self.assertEqual(decoded["ctime"], datetime(2026, 10, 5, 16, 50, 16))
        self.assertEqual(decoded["resolution"], (1920, 1080))
        self.assertEqual(decoded["streamer"]["name"], "S")

    def test_videoinfo_object_is_accepted(self):
        """``VideoInfo`` 是 dict 子类，应能直接编码。"""
        from DMR.utils import StreamerInfo, VideoInfo

        info = encode_video_info(VideoInfo(
            path="a.mkv", dtype="src_video", size=1, duration=2.0,
            resolution=(1280, 720), title="t",
            streamer=StreamerInfo(name="S"), group_id="g1", segment_id=1,
            ctime=datetime(2026, 1, 2, 3, 4, 5),
        ))

        self.assertEqual(info["path"], "a.mkv")
        self.assertEqual(info["resolution"], [1280, 720])

    def test_plain_object_is_accepted(self):
        """普通对象（自定义下载器可能传命名空间对象）也应能编码。"""
        from types import SimpleNamespace

        info = encode_video_info(SimpleNamespace(path="a.mkv", segment_id=3))

        self.assertEqual(info["path"], "a.mkv")
        self.assertEqual(info["segment_id"], 3)

    def test_none_and_garbage_are_tolerated(self):
        self.assertIsNone(encode_video_info(None))
        self.assertIsNone(decode_video_info(None))
        self.assertIsNone(decode_video_info(""))
        self.assertIsNone(decode_video_info("{not json"))
        self.assertIsNone(decode_video_info("[1,2,3]"))
        self.assertIsNone(encode_video_info(12345))

    def test_bad_ctime_degrades_to_none(self):
        decoded = decode_video_info({"path": "a.mkv", "ctime": "not-a-time"})
        self.assertIsNone(decoded["ctime"])

    def test_unsupported_value_falls_back_to_string(self):
        """不可序列化的值不应让整条记录写不进去。"""
        info = encode_video_info({"path": "a.mkv", "weird": object()})
        self.assertIsNotNone(info)
        self.assertEqual(info["path"], "a.mkv")


class TestRebuildVideoInfo(_StateCase):
    """``rebuild_video_info``：首选载荷、回退场次。"""

    def test_preferred_path_uses_stored_info(self):
        """载荷里的标题与时间是录制当时的真实值，优先使用。"""
        self.make_session()
        artifact = self.make_artifact(video_info={
            "path": "old.mkv", "title": "当时的标题", "duration": 600.0,
            "size": 100, "resolution": [1920, 1080],
            "ctime": "2026-10-05T16:50:16",
            "streamer": {"name": "Korooon", "platform": "twitch"},
            "group_id": "sess-1", "segment_id": 1, "taskname": "mytask",
        })

        video = rebuild_video_info(artifact, self.repo.get_session("sess-1"))

        self.assertEqual(video.title, "当时的标题")
        self.assertEqual(video.ctime, datetime(2026, 10, 5, 16, 50, 16))
        self.assertEqual(video.streamer.name, "Korooon", "streamer 应是对象而非 dict")
        self.assertEqual(video.segment_id, 1)

    def test_artifact_path_wins_over_stored_path(self):
        """产物表里的路径是当前真相（文件可能已被改名/搬迁）。"""
        self.make_session()
        artifact = self.make_artifact(video_info={"path": "stale.mkv",
                                                  "title": "t"})

        video = rebuild_video_info(artifact, self.repo.get_session("sess-1"))

        self.assertEqual(video.path, artifact.path)

    def test_fallback_uses_session_when_payload_missing(self):
        """升级前录的分段没有载荷 → 用场次记录补出主播/标题/时间。"""
        self.make_session()
        artifact = self.make_artifact()

        video = rebuild_video_info(artifact, self.repo.get_session("sess-1"))

        self.assertEqual(video.title, "直播标题")
        self.assertEqual(video.streamer.name, "Korooon")
        self.assertEqual(video.streamer.platform, "twitch")
        self.assertEqual(video.streamer.room_id, "123")
        self.assertIsInstance(video.ctime, datetime)
        self.assertEqual(video.duration, 600.0)
        self.assertEqual(video.group_id, "sess-1")
        self.assertEqual(video.segment_id, 1)

    def test_filename_template_works_on_both_paths(self):
        """两条路径重建出的对象都必须能套用文件名模板（这是最实际的检验）。"""
        from DMR.utils import replace_keywords

        template = ("{STREAMER.NAME}-{CTIME.YEAR}年{CTIME.MONTH:02d}月"
                    "{CTIME.DAY:02d}日{CTIME.HOUR:02d}点{CTIME.MINUTE:02d}分-{TITLE}")
        self.make_session()
        with_payload = self.make_artifact(
            segment_idx=1,
            video_info={"path": "a.mkv", "title": "标题甲",
                        "ctime": "2026-10-05T16:50:16",
                        "streamer": {"name": "Korooon"}, "duration": 600.0},
        )
        without_payload = self.make_artifact(segment_idx=2)
        session = self.repo.get_session("sess-1")

        for artifact, expect in ((with_payload, "标题甲"), (without_payload, "直播标题")):
            video = rebuild_video_info(artifact, session)
            name = replace_keywords(template, video, replace_invalid=True)
            self.assertIn("Korooon", name)
            self.assertIn(expect, name)

    def test_missing_path_returns_none(self):
        self.make_session()
        artifact = self.make_artifact()
        artifact.path = None

        self.assertIsNone(rebuild_video_info(artifact, None))

    def test_broken_payload_falls_back(self):
        """载荷结构不符时应退回场次重建，而不是抛异常。"""
        self.make_session()
        artifact = self.make_artifact(video_info={"unexpected": 1, "title": "x"})

        video = rebuild_video_info(artifact, self.repo.get_session("sess-1"))

        self.assertEqual(video.path, artifact.path)

    def test_none_title_does_not_leak_into_filename(self):
        """标题为 ``None`` 时**不能**在文件名里变成字符串 "None"。

        ``replace_keywords`` 用 ``format_map``：模板里的键在 dict 中存在就取其值，
        因此 ``{'title': None}`` 会渲染成 "None"。而恢复流程很容易遇到"载荷里
        标题是 null"（旧产物或未写入元信息）。
        """
        from DMR.utils import replace_keywords

        self.make_session()
        artifact = self.make_artifact(
            segment_idx=1,
            video_info={"path": "a.mkv", "title": None, "duration": 600.0},
        )

        video = rebuild_video_info(artifact, self.repo.get_session("sess-1"))
        name = replace_keywords("{STREAMER.NAME}-{TITLE}", video,
                                replace_invalid=True)

        self.assertNotIn("None", name)
        self.assertEqual(name, "Korooon-直播标题", "应回落到场次记录里的标题")

    def test_title_fallback_uses_session(self):
        """载荷没给标题时用场次记录的标题。"""
        self.make_session()
        artifact = self.make_artifact(video_info={"path": "a.mkv", "duration": 600.0})

        video = rebuild_video_info(artifact, self.repo.get_session("sess-1"))

        self.assertEqual(video.title, "直播标题")


class TestCollectResumable(_StateCase):
    """``collect_resumable``：只挑没收尾的产物。"""

    def manager(self):
        return RecoveryManager(self.repo, RecoveryConfig(),
                               probe=lambda p: 600.0,
                               now=lambda: int(__import__("time").time()))

    def collect(self, **kw):
        report = RecoveryReport()
        self.manager().collect_resumable(report, **kw)
        return report

    def test_recorded_and_rendered_are_collected(self):
        self.make_session()
        self.make_artifact(ArtifactState.RECORDED, segment_idx=1)
        self.make_artifact(ArtifactState.RENDERED, segment_idx=2,
                           kind=ArtifactKind.DANMAKU_VIDEO)

        report = self.collect()

        reasons = {a.artifact_id: a.reason for a in report.resumable}
        self.assertEqual(len(report.resumable), 2)
        self.assertEqual(reasons["sess-1:src_video:1"], "unprocessed")
        self.assertEqual(reasons["sess-1:dm_video:2"], "rendered")

    def test_terminal_states_are_never_collected(self):
        """已上传/已清理绝不重跑 —— 否则会重复投稿。"""
        self.make_session()
        for idx, state in enumerate((ArtifactState.UPLOADED, ArtifactState.CLEANED,
                                     ArtifactState.SKIPPED, ArtifactState.MISSING), 1):
            self.make_artifact(state, segment_idx=idx)

        report = self.collect()

        self.assertEqual(report.resumable, [])

    def test_interrupted_is_not_collected(self):
        """校验未通过的中断产物不在自动重跑范围内（可能不完整）。"""
        self.make_session()
        self.make_artifact(ArtifactState.INTERRUPTED)

        self.assertEqual(self.collect().resumable, [])

    def test_taskname_filter(self):
        self.make_session("sess-1", "taskA")
        self.make_session("sess-2", "taskB")
        self.make_artifact(ArtifactState.RECORDED, session_id="sess-1")
        self.make_artifact(ArtifactState.RECORDED, session_id="sess-2")

        report = self.collect(tasknames={"taskA"})

        self.assertEqual([a.taskname for a in report.resumable], ["taskA"])

    def test_artifact_without_path_is_skipped(self):
        self.make_session()
        artifact = self.make_artifact(ArtifactState.RECORDED)
        self.repo.conn.execute("UPDATE artifacts SET data=json_remove(data, '$.path')"
                               " WHERE artifact_id=?", (artifact.artifact_id,))
        self.repo.conn.commit()

        self.assertEqual(self.collect().resumable, [])

    def test_orphan_artifact_is_reported_not_silently_dropped(self):
        """场次已被回收时应如实记错，而不是静默丢掉这个产物。"""
        self.make_session()
        artifact = self.make_artifact(ArtifactState.RECORDED)
        self.repo.conn.execute("PRAGMA foreign_keys=OFF")
        self.repo.conn.execute("DELETE FROM sessions WHERE session_id='sess-1'")
        self.repo.conn.commit()

        report = self.collect()

        self.assertEqual(report.resumable, [])
        self.assertTrue(any(artifact.artifact_id in e for e in report.errors))

    def test_reconcile_summary_mentions_resumable(self):
        report = RecoveryReport()
        self.assertIn("待恢复 0 项", report.summary())


class TestResumeRecovered(_StateCase):
    """``LiveEvents.resume_recovered``：注入内存状态并重新派发。"""

    def make_events(self, **kwargs):
        events = self.make_live_events(**kwargs)
        events.state_repo = self.repo
        return events

    def actions(self, *artifacts):
        from DMR.state import ResumableAction

        result = []
        for a in artifacts:
            session = self.repo.get_session(a.session_id)
            result.append(ResumableAction(
                artifact_id=a.artifact_id, taskname=session.taskname,
                session_id=a.session_id, segment_idx=a.segment_idx,
                kind=str(a.kind), state=str(a.state), path=a.path,
                reason="unprocessed",
            ))
        return result

    def test_artifact_is_injected_as_ready(self):
        """注入的分段状态必须是 ready，否则 _check_for_upload 会跳过它。"""
        self.make_session()
        artifact = self.make_artifact(ArtifactState.RECORDED)
        events = self.make_events()

        events.resume_recovered(self.actions(artifact))

        state = events.state_dict["sess-1"][0]
        self.assertEqual(state["src_video"]["status"], "ready")
        self.assertEqual(state["src_video"]["file"].path, artifact.path)

    def test_without_upload_config_no_messages(self):
        """未开启 auto_upload 时只注入状态，不派发消息。"""
        self.make_session()
        artifact = self.make_artifact(ArtifactState.RECORDED)
        events = self.make_events()

        messages = events.resume_recovered(self.actions(artifact))

        self.assertEqual(messages, [])

    def test_upload_is_redispatched(self):
        self.make_session()
        artifact = self.make_artifact(ArtifactState.RECORDED)
        events = self.make_events(
            common_event_args={"auto_render": False, "auto_upload": True,
                               "auto_clean": False, "auto_transcode": False},
            upload_args={"src_video": [{
                "engine": "biliwebapi", "target": "bilibili",
                "account": "main", "realtime": True, "min_length": 120,
            }]},
        )

        messages = events.resume_recovered(self.actions(artifact))

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].target, "uploader")
        self.assertEqual(self.repo.get_artifact(artifact.artifact_id).state,
                         ArtifactState.UPLOADING)

    def test_segment_index_is_respected(self):
        """第 N 个分段必须落到下标 N-1，且中间空位要补齐。"""
        self.make_session()
        first = self.make_artifact(ArtifactState.RECORDED, segment_idx=1)
        third = self.make_artifact(ArtifactState.RECORDED, segment_idx=3)
        events = self.make_events()

        events.resume_recovered(self.actions(first, third))

        group = events.state_dict["sess-1"]
        self.assertEqual(len(group), 3)
        self.assertEqual(group[0]["src_video"]["status"], "ready")
        self.assertIsNone(group[1]["src_video"]["status"], "空位应保持未处理")
        self.assertEqual(group[2]["src_video"]["file"].path, third.path)

    def test_ended_session_is_marked_ended(self):
        """已下播的场次要标记结束，非实时（整组）上传才会被触发。"""
        self.make_session()
        self.repo.end_session("sess-1")
        artifact = self.make_artifact(ArtifactState.RECORDED)
        events = self.make_events(
            common_event_args={"auto_render": False, "auto_upload": True,
                               "auto_clean": False, "auto_transcode": False},
            upload_args={"src_video": [{
                "engine": "biliwebapi", "target": "bilibili",
                "account": "main", "realtime": False, "min_length": 120,
            }]},
        )

        messages = events.resume_recovered(self.actions(artifact))

        self.assertIn("sess-1", events.ended_dict)
        self.assertEqual(len(messages), 1, "非实时上传应被触发")

    def test_live_session_is_not_marked_ended(self):
        self.make_session()
        artifact = self.make_artifact(ArtifactState.RECORDED)
        events = self.make_events()

        events.resume_recovered(self.actions(artifact))

        self.assertNotIn("sess-1", events.ended_dict)

    def test_without_repo_is_a_noop(self):
        events = self.make_events()
        events.state_repo = None

        self.assertEqual(events.resume_recovered([]), [])

    def test_missing_artifact_is_skipped(self):
        """产物在对账后被删掉时不应抛异常。"""
        self.make_session()
        artifact = self.make_artifact(ArtifactState.RECORDED)
        actions = self.actions(artifact)
        self.repo.delete_artifact(artifact.artifact_id)
        events = self.make_events()

        messages = events.resume_recovered(actions)

        self.assertEqual(messages, [])
        self.assertEqual(events.state_dict, {})

    def test_corrupt_payload_still_recovers(self):
        """载荷损坏时仍应恢复：路径以产物表/对账报告为准，其余用场次信息补齐。

        这一类产物最需要被恢复（正因为上次异常退出才留下损坏载荷），
        所以不能因为载荷坏了就放弃它 —— 判定用"文件名标记 + 文件大小"，
        不需要解析视频内容，载荷坏掉不影响判定。
        """
        self.make_session()
        good = self.make_artifact(ArtifactState.RECORDED, segment_idx=1)
        bad = self.make_artifact(ArtifactState.RECORDED, segment_idx=2)
        self.repo.conn.execute(
            "UPDATE artifacts SET data='not-json' WHERE artifact_id=?",
            (bad.artifact_id,))
        self.repo.conn.commit()
        events = self.make_events()

        events.resume_recovered(self.actions(good, bad))

        group = events.state_dict["sess-1"]
        self.assertEqual(group[0]["src_video"]["status"], "ready")
        self.assertEqual(group[1]["src_video"]["status"], "ready",
                         "载荷损坏不应导致该产物被放弃")
        self.assertEqual(group[1]["src_video"]["file"].path, bad.path)
        self.assertEqual(group[1]["src_video"]["file"].title, "直播标题",
                         "缺失的元信息应由场次记录补齐")

    def test_single_failure_does_not_affect_others(self):
        """单条产物重建失败不影响其它产物（隔离性）。"""
        self.make_session()
        good = self.make_artifact(ArtifactState.RECORDED, segment_idx=1)
        # 不存在的产物：resume 时应被跳过而不是中断整批
        from DMR.state import ResumableAction
        ghost = ResumableAction(
            artifact_id="sess-1:src_video:9", taskname="mytask",
            session_id="sess-1", segment_idx=9, kind="src_video",
            state="recorded", path=self.path("ghost.mkv"), reason="unprocessed",
        )
        events = self.make_events()

        events.resume_recovered([ghost] + self.actions(good))

        group = events.state_dict["sess-1"]
        self.assertEqual(group[0]["src_video"]["status"], "ready")
        self.assertEqual(len(group), 1, "不存在的产物不应占位")


#: 分段式引擎写出的中间名（[正在录制] 前缀 + Part + uuid）
_INTERMEDIATE = "[正在录制]mytask-{name}-0-20261005165016-Part000-deadbeef.mkv"

_TEMPLATE = ("{STREAMER.NAME}-{CTIME.YEAR}年{CTIME.MONTH:02d}月{CTIME.DAY:02d}日"
             "{CTIME.HOUR:02d}点{CTIME.MINUTE:02d}分-{TITLE}")


class TestIntermediateRename(_StateCase):
    """恢复时应把 ``[正在录制]`` 中间名改成最终文件名。

    分段式引擎只在"下一个分段开始"时才改名，进程若在那之前退出，文件就永远停在
    中间名上 —— 服务器上观察到的正是这一情形。
    """

    def make_events(self, output_dir, **kwargs):
        download_args = {"dltype": "live", "output_dir": output_dir,
                         "output_name": _TEMPLATE, "output_format": "mkv",
                         "max_fn_length": 80}
        events = self.make_live_events(download_args=download_args, **kwargs)
        events.state_repo = self.repo
        return events

    def seed(self, *, name="seg", marker=True, payload=True, **extra):
        """造一个带中间名文件的产物，返回 (artifact, 原路径)。"""
        self.make_session()
        filename = (_INTERMEDIATE.format(name=name) if marker
                    else f"{name}.mkv")
        path = self.write(filename)
        info = None
        if payload:
            info = {"path": path, "title": "直播标题", "duration": 600.0,
                    # 大小要高于 min_valid_size_mb（默认 30MB），否则会因"太小"被跳过
                    "size": int(self.FILE_MB * MB), "resolution": [1920, 1080],
                    "ctime": "2026-10-05T16:50:16",
                    "streamer": {"name": "Korooon", "platform": "twitch"},
                    "group_id": "sess-1", "segment_id": 1, "taskname": "mytask"}
        artifact = self.make_artifact(ArtifactState.RECORDED, path=path,
                                      video_info=info, **extra)
        return artifact, path

    def actions(self, *artifacts):
        from DMR.state import ResumableAction

        return [ResumableAction(
            artifact_id=a.artifact_id, taskname="mytask",
            session_id=a.session_id, segment_idx=a.segment_idx,
            kind=str(a.kind), state=str(a.state), path=a.path,
            reason="unprocessed") for a in artifacts]

    def test_intermediate_name_is_promoted(self):
        artifact, old = self.seed()
        events = self.make_events(self.tmpdir)

        events.resume_recovered(self.actions(artifact))

        video = events.state_dict["sess-1"][0]["src_video"]["file"]
        self.assertNotIn("[正在录制]", os.path.basename(video.path))
        self.assertIn("Korooon", os.path.basename(video.path))
        self.assertIn("直播标题", os.path.basename(video.path))
        self.assertIn("2026年10月05日16点50分", os.path.basename(video.path),
                      "时间应取自录制当时（ctime），而不是恢复时刻")
        self.assertTrue(os.path.exists(video.path), "改名后文件必须还在")
        self.assertFalse(os.path.exists(old), "旧名不应残留")

    def test_new_path_is_persisted(self):
        """新路径要回写状态库，否则下次重启又按旧路径找不到文件。"""
        artifact, old = self.seed()
        events = self.make_events(self.tmpdir)

        events.resume_recovered(self.actions(artifact))

        stored = self.repo.get_artifact(artifact.artifact_id)
        self.assertNotIn("[正在录制]", stored.path)
        self.assertTrue(os.path.exists(stored.path))
        self.assertIsNone(stored.part_path, "改名后不应再标记为中间文件")

    def test_final_name_is_left_alone(self):
        """名字已是最终的（文件下载类引擎）不应被改名。"""
        artifact, path = self.seed(name="already-final", marker=False)
        events = self.make_events(self.tmpdir)

        events.resume_recovered(self.actions(artifact))

        video = events.state_dict["sess-1"][0]["src_video"]["file"]
        self.assertEqual(video.path, path)

    def test_target_collision_gets_unique_name(self):
        """目标名已被占用时，``rename_safe`` 会派一个不冲突的名字，文件不丢。"""
        artifact, old = self.seed()
        events = self.make_events(self.tmpdir)
        target = events._compute_output_path(self._rebuilt(artifact))
        with open(target, "wb") as handle:
            handle.write(b"occupied")

        events.resume_recovered(self.actions(artifact))

        video = events.state_dict["sess-1"][0]["src_video"]["file"]
        self.assertNotEqual(video.path, target, "不应覆盖已存在的文件")
        self.assertNotIn("[正在录制]", os.path.basename(video.path))
        self.assertTrue(os.path.exists(video.path))
        self.assertTrue(os.path.exists(target), "已存在的文件必须保留")
        self.assertFalse(os.path.exists(old), "原文件应已改名，不留残file")

    def _rebuilt(self, artifact):
        from unit_tests.support import DMRTestCase

        return rebuild_video_info(artifact, self.repo.get_session("sess-1"))

    def test_missing_template_keeps_name_but_strips_marker(self):
        """没配 ``output_name`` 时用兜底命名：只去掉中间名标记。"""
        artifact, old = self.seed()
        events = self.make_events(self.tmpdir)
        events.config["download_args"].pop("output_name")

        events.resume_recovered(self.actions(artifact))

        video = events.state_dict["sess-1"][0]["src_video"]["file"]
        self.assertNotIn("[正在录制]", os.path.basename(video.path))
        self.assertTrue(os.path.exists(video.path))

    def test_rename_failure_does_not_block_upload(self):
        """即使改名抛异常，也必须继续上传（不能因命名问题丢产物）。"""
        artifact, old = self.seed()
        events = self.make_events(
            self.tmpdir,
            common_event_args={"auto_render": False, "auto_upload": True,
                               "auto_clean": False, "auto_transcode": False},
            upload_args={"src_video": [{
                "engine": "biliwebapi", "target": "bilibili",
                "account": "main", "realtime": True, "min_length": 120,
            }]},
        )
        events._compute_output_path = lambda video: (_ for _ in ()).throw(
            RuntimeError("boom"))

        messages = events.resume_recovered(self.actions(artifact))

        self.assertEqual(len(messages), 1, "改名失败仍应派发上传")
        self.assertEqual(messages[0].data["files"][0].path, old)

    def test_file_download_dir_defaults_to_video_dir(self):
        """未配 ``output_dir`` 时，最终文件应落在原文件所在目录。"""
        artifact, old = self.seed()
        events = self.make_events(None)
        events.config["download_args"]["output_dir"] = None

        events.resume_recovered(self.actions(artifact))

        video = events.state_dict["sess-1"][0]["src_video"]["file"]
        self.assertEqual(os.path.dirname(video.path), os.path.dirname(old))


class TestUsableFileRule(DMRTestCase):
    """恢复判定：``[正在录制]`` 标记 + 文件大小达标，**不依赖 ffprobe**。"""

    def setUp(self) -> None:
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.tmpdir = self._tmp.name

    def write(self, name, size_mb):
        p = os.path.join(self.tmpdir, name)
        with open(p, "wb") as f:
            f.write(b"\0" * int(size_mb * MB))
        return p

    def test_inprogress_marker_is_recognized(self):
        from DMR.state import looks_like_inprogress_file

        self.assertTrue(looks_like_inprogress_file("[正在录制]a-Part000-x.mkv"))
        self.assertFalse(looks_like_inprogress_file("a-2026.mkv"))
        self.assertFalse(looks_like_inprogress_file(None))
        self.assertFalse(looks_like_inprogress_file(""), "空路径不应被当成中间名")
        # 标记在目录名里、文件名是最终名时不算中间名
        self.assertFalse(looks_like_inprogress_file(
            os.path.join("[正在录制]dir", "a.mkv")))

    def test_size_above_threshold_is_usable(self):
        from DMR.state import is_recovered_file_usable

        path = self.write("[正在录制]a-Part000-x.mkv", 40)

        self.assertTrue(is_recovered_file_usable(path, min_size_mb=30))

    def test_size_below_threshold_is_not_usable(self):
        from DMR.state import is_recovered_file_usable

        path = self.write("[正在录制]a-Part000-x.mkv", 5)

        self.assertFalse(is_recovered_file_usable(path, min_size_mb=30))

    def test_final_name_is_usable_when_big_enough(self):
        """已改名的文件同样正常（不要求必须有中间名标记）。"""
        from DMR.state import is_recovered_file_usable

        path = self.write("a-2026.mkv", 40)

        self.assertTrue(is_recovered_file_usable(path, min_size_mb=30))

    def test_missing_file_is_not_usable(self):
        from DMR.state import is_recovered_file_usable

        self.assertFalse(is_recovered_file_usable(
            os.path.join(self.tmpdir, "ghost.mkv"), min_size_mb=30))
        self.assertFalse(is_recovered_file_usable(None, min_size_mb=30))

    def test_explicit_size_skips_stat(self):
        """已知大小时直接用，不去读文件（文件不存在也能判定）。"""
        from DMR.state import is_recovered_file_usable

        self.assertTrue(is_recovered_file_usable(
            os.path.join(self.tmpdir, "ghost.mkv"), 40 * MB, min_size_mb=30))
        self.assertFalse(is_recovered_file_usable(
            os.path.join(self.tmpdir, "ghost.mkv"), 1 * MB, min_size_mb=30))

    def test_threshold_is_configurable(self):
        from DMR.state import is_recovered_file_usable

        path = self.write("a.mkv", 40)

        self.assertTrue(is_recovered_file_usable(path, min_size_mb=10))
        self.assertFalse(is_recovered_file_usable(path, min_size_mb=100))


class TestUnusableFile(_StateCase):
    """不满足恢复条件的产物（太小/不存在）不恢复，且不无限重试。"""

    def make_events(self, **kwargs):
        events = self.make_live_events(**kwargs)
        events.state_repo = self.repo
        return events

    def seed(self, size_mb=1.0, name="[正在录制]a-Part000-x.mkv", **kw):
        """造一个小文件产物（低于 30MB 阈值）→ 不满足恢复条件。"""
        self.make_session()
        path = self.write(name, size_mb=size_mb)
        return self.make_artifact(ArtifactState.RECORDED, path=path,
                                  size=int(size_mb * MB), **kw)

    def actions(self, artifact):
        from DMR.state import ResumableAction

        return [ResumableAction(
            artifact_id=artifact.artifact_id, taskname="mytask",
            session_id=artifact.session_id, segment_idx=artifact.segment_idx,
            kind=str(artifact.kind), state=str(artifact.state),
            path=artifact.path, reason="unprocessed")]

    def upload_events(self, **recovery):
        events = self.make_events(
            common_event_args={"auto_render": False, "auto_upload": True,
                               "auto_clean": False, "auto_transcode": False},
            upload_args={"src_video": [{
                "engine": "biliwebapi", "target": "bilibili",
                "account": "main", "realtime": True, "min_length": 120,
            }]},
        )
        if recovery:
            events.config["recovery"] = recovery
        return events

    def test_too_small_is_not_uploaded(self):
        artifact = self.seed()

        messages = self.upload_events().resume_recovered(self.actions(artifact))

        self.assertEqual(messages, [], "过小的文件不应被上传")

    def test_too_small_is_marked_skipped(self):
        artifact = self.seed()
        events = self.make_events()

        events.resume_recovered(self.actions(artifact))

        stored = self.repo.get_artifact(artifact.artifact_id)
        self.assertEqual(stored.state, ArtifactState.SKIPPED)
        self.assertIn("阈值", stored.last_error or "")
        self.assertTrue(os.path.exists(artifact.path), "skip 不删除文件")

    def test_skipped_is_not_collected_again(self):
        """标记后不再被 collect_resumable 选中（否则每次重启都白试）。"""
        artifact = self.seed()
        events = self.make_events()
        events.resume_recovered(self.actions(artifact))

        report = RecoveryReport()
        RecoveryManager(self.repo, RecoveryConfig(),
                        probe=lambda p: 600.0,
                        now=lambda: int(__import__("time").time())
                        ).collect_resumable(report)

        self.assertEqual(report.resumable, [])

    def test_big_enough_file_is_uploaded_without_duration(self):
        """**核心回归**：时长未知但大小达标 → 视为正常并上传（不依赖 ffprobe）。"""
        self.make_session()
        path = self.write("[正在录制]korooonx-Part000-abc.mkv", size_mb=40)
        artifact = self.make_artifact(ArtifactState.RECORDED, path=path,
                                      duration=None, size=int(40 * MB))

        messages = self.upload_events().resume_recovered(self.actions(artifact))

        self.assertEqual(len(messages), 1, "大小达标的产物必须能上传")
        self.assertEqual(self.repo.get_artifact(artifact.artifact_id).state,
                         ArtifactState.UPLOADING)

    def test_discard_removes_file(self):
        artifact = self.seed()

        self.upload_events(on_unusable_file="discard").resume_recovered(
            self.actions(artifact))

        self.assertEqual(self.repo.get_artifact(artifact.artifact_id).state,
                         ArtifactState.SKIPPED)
        self.assertFalse(os.path.exists(artifact.path), "discard 应删除文件")

    def test_ask_keeps_state_for_manual_decision(self):
        artifact = self.seed()

        self.upload_events(on_unusable_file="ask").resume_recovered(
            self.actions(artifact))

        self.assertEqual(self.repo.get_artifact(artifact.artifact_id).state,
                         ArtifactState.RECORDED, "ask 应保持原状态")
        self.assertTrue(os.path.exists(artifact.path))

    def test_invalid_config_value_falls_back_to_skip(self):
        artifact = self.seed()

        self.upload_events(on_unusable_file="bogus").resume_recovered(
            self.actions(artifact))

        self.assertEqual(self.repo.get_artifact(artifact.artifact_id).state,
                         ArtifactState.SKIPPED)

    def test_custom_threshold_is_respected(self):
        artifact = self.seed(size_mb=10)

        messages = self.upload_events(min_valid_size_mb=5).resume_recovered(
            self.actions(artifact))

        self.assertEqual(len(messages), 1, "调低阈值后 10MB 应判定为可用")

    def test_recovery_and_upload_gate_share_one_threshold(self):
        """``recovery.min_valid_size_mb`` 同时约束"恢复判定"与"上传长度门槛"。

        两者都在回答"这个录到一半的文件是否已录到实质内容"，因此必须是同一项 ——
        早期版本曾拆成两个配置名（``min_valid_size_mb`` / ``resume_min_size_mb``），
        属于重复配置；如果它们不一致，会出现"恢复接受了、上传又拒绝"的矛盾。
        """
        from DMR.state import RecoveryConfig

        config = RecoveryConfig.from_mapping({"min_valid_size_mb": 7})
        events = self.make_events()
        events.config["recovery"] = {"min_valid_size_mb": 7}

        # 上传门槛读到的阈值
        self.assertEqual(events._min_valid_size_mb(), 7.0)
        self.assertEqual(config.min_valid_size_mb, 7.0)

        # 6MB 文件：两处都应判为不达标
        video = self.make_video_info(path=self.write("a.mkv", size_mb=6))
        video.duration = None
        video.size = 6 * MB
        self.assertFalse(events._passes_length_gate(video, 120, {}))
        from DMR.state import is_recovered_file_usable
        self.assertFalse(is_recovered_file_usable(video.path, video.size,
                                                  min_size_mb=7))

        # 8MB 文件：两处都应判为达标
        video2 = self.make_video_info(path=self.write("b.mkv", size_mb=8))
        video2.duration = None
        video2.size = 8 * MB
        self.assertTrue(events._passes_length_gate(video2, 120, {}))
        self.assertTrue(is_recovered_file_usable(video2.path, video2.size,
                                                 min_size_mb=7))


class TestLengthGate(_StateCase):
    """``_passes_length_gate``：时长优先、未知时用大小（实时/非实时共用）。"""

    def make_events(self, recovery=None):
        events = self.make_live_events()
        events.state_repo = self.repo
        if recovery is not None:
            events.config["recovery"] = recovery
        return events

    def video(self, *, duration=None, size=None, exists=True, mb=40):
        path = self.write("a.mkv", size_mb=mb) if exists else self.path("ghost.mkv")
        v = self.make_video_info(path=path)
        v.duration = duration
        v.size = size
        return v

    def test_known_duration_below_min_is_rejected(self):
        events = self.make_events()

        self.assertFalse(events._passes_length_gate(self.video(duration=10), 120, {}))

    def test_known_duration_above_min_is_accepted(self):
        events = self.make_events()

        self.assertTrue(events._passes_length_gate(self.video(duration=600), 120, {}))

    def test_unknown_duration_falls_back_to_size(self):
        events = self.make_events()

        self.assertTrue(events._passes_length_gate(self.video(duration=None), 120, {}))

    def test_unknown_duration_and_small_size_is_rejected(self):
        events = self.make_events()

        self.assertFalse(events._passes_length_gate(
            self.video(duration=None, mb=5), 120, {}))

    def test_unknown_duration_missing_file_is_rejected(self):
        events = self.make_events()

        self.assertFalse(events._passes_length_gate(
            self.video(duration=None, exists=False), 120, {}))

    def test_size_is_read_from_disk_when_absent(self):
        """``size`` 为空时应读一次文件大小并回填（避免重复读盘）。"""
        events = self.make_events()
        video = self.video(duration=None, size=None)

        self.assertTrue(events._passes_length_gate(video, 120, {}))
        self.assertIsNotNone(video.size)

    def test_zero_duration_uses_size(self):
        """时长为 0 属于"元信息没写上"，按未知处理而非"时长 0 秒"。"""
        events = self.make_events()

        self.assertTrue(events._passes_length_gate(self.video(duration=0, mb=40),
                                                   120, {}))

    def test_does_not_raise_on_unknown_duration(self):
        """回归服务器报错：时长未知不得抛 TypeError。"""
        events = self.make_events()

        try:
            events._passes_length_gate(self.video(duration=None), 120, {})
        except TypeError as exc:  # pragma: no cover - 失败时给出明确信息
            self.fail(f"时长未知不应抛 TypeError：{exc}")


if __name__ == "__main__":
    unittest.main()

