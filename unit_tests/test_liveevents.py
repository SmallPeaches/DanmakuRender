"""``DMR.Task.liveevents`` 状态机逻辑的模块级测试（P0）。

这些用例**不需要网络、磁盘、子进程或真实录制**：只构造内部状态、调用被测方法、
断言返回值与状态变化。这是当前仓库最缺的一环（此前只能跑全流程）。

标记约定
--------
``@unittest.expectedFailure`` 用于**当前代码的已知缺陷**：用例断言的是"正确行为"，
所以在缺陷存在期间失败（计入 expected failures，套件整体仍 OK）；缺陷被修复后会
变成 "unexpected success" 并使套件变红 —— 这正是提醒我们去掉标记、正式锁定修复
的信号。缺陷编号对应 ``TODO.md`` 的 B7 节。
"""
from __future__ import annotations

import unittest

from unit_tests.support import DMRTestCase


class TestUploadEmptyCandidates(DMRTestCase):
    """TODO.md B7.1 —— ``_check_for_upload`` 空候选列表导致 IndexError。

    复现条件（已实测）：``auto_upload=True``、上传配置 ``realtime: False``、
    ``min_length`` 高于所有分段时长、组已结束。``liveevents.py:213-214`` 在
    ``up_videos`` 为空时仍取 ``up_videos[0]``。
    """

    def _events_with_short_segments(self, realtime: bool, min_length: int):
        events = self.make_live_events(
            common_event_args={
                "auto_render": False, "auto_upload": True,
                "auto_clean": False, "auto_transcode": False,
            },
            upload_args={"src_video": [{
                "engine": "biliwebapi", "realtime": realtime,
                "min_length": min_length,
            }]},
        )
        # 一个已完成、但时长低于 min_length 的分段
        state = self.blank_state()
        state["src_video"].update(
            {"status": "ready", "file": self.make_video_info(duration=30, segment_id=1)}
        )
        events.state_dict["g1"] = [state]
        events.ended_dict["g1"] = self.clock.now()
        return events

    def _check_no_candidates(self, realtime: bool):
        events = self._events_with_short_segments(realtime=realtime, min_length=120)

        # 期望：不抛异常，返回列表，且不把状态改成 uploading
        messages = events._check_for_upload("g1")

        self.assertIsInstance(messages, list)
        self.assertEqual(messages, [])
        self.assertEqual(events.state_dict["g1"][0]["src_video"]["status"], "ready")

    def test_non_realtime_no_candidates_no_raise(self):
        """非实时分支：所有分段都短于 ``min_length`` 时应安静跳过。

        B7.1 已修复：原先在取 ``up_videos[0]`` 前未判空，会抛 ``IndexError``
        并中断整个事件处理循环。
        """
        self._check_no_candidates(realtime=False)

    def test_realtime_no_candidates_is_safe(self):
        """实时分支实测**安全**：``liveevents.py:168-170`` 用 ``continue`` 跳过了
        时长不足的分段，不会走到 ``up_videos[0]``。

        保留此用例是为了固定"实时分支不受 B7.1 影响"这一事实 —— 修复 B7.1 时
        不应改变实时分支的行为。
        """
        self._check_no_candidates(realtime=True)


class TestUploadPicksQualifiedSegments(DMRTestCase):
    """``_check_for_upload`` 的**正常路径**必须被锁定，防止修 B7.1 时改坏。"""

    def test_non_realtime_uploads_only_qualified_segments(self):
        events = self.make_live_events(
            common_event_args={
                "auto_render": False, "auto_upload": True,
                "auto_clean": False, "auto_transcode": False,
            },
            upload_args={"src_video": [{
                "engine": "biliwebapi", "realtime": False, "min_length": 120,
            }]},
        )
        long_state = self.blank_state()
        long_state["src_video"].update(
            {"status": "ready", "file": self.make_video_info(duration=600, segment_id=1)}
        )
        short_state = self.blank_state()
        short_state["src_video"].update(
            {"status": "ready", "file": self.make_video_info(duration=30, segment_id=2)}
        )
        events.state_dict["g1"] = [long_state, short_state]
        events.ended_dict["g1"] = self.clock.now()

        messages = events._check_for_upload("g1")

        self.assertEqual(len(messages), 1, "只应上传满足 min_length 的那一段")
        self.assertEqual(messages[0].target, "uploader")
        self.assertEqual(messages[0].event, "newtask")
        self.assertEqual(messages[0].data["files"][0].duration, 600)
        self.assertTrue(messages[0].data["stateless"], "非实时上传应为 stateless=True")

    def test_realtime_uploads_each_ready_segment(self):
        events = self.make_live_events(
            common_event_args={
                "auto_render": False, "auto_upload": True,
                "auto_clean": False, "auto_transcode": False,
            },
            upload_args={"src_video": [{
                "engine": "biliwebapi", "realtime": True, "min_length": 120,
            }]},
        )
        for idx, duration in enumerate((600, 700), start=1):
            state = self.blank_state()
            state["src_video"].update({
                "status": "ready",
                "file": self.make_video_info(duration=duration, segment_id=idx),
            })
            events.state_dict.setdefault("g1", []).append(state)

        messages = events._check_for_upload("g1")

        self.assertEqual(len(messages), 2, "实时上传应逐段上传")
        self.assertFalse(messages[0].data["stateless"], "实时上传应为 stateless=False")
        statuses = [s["src_video"]["status"] for s in events.state_dict["g1"]]
        self.assertEqual(statuses, ["uploading", "uploading"])

    def test_skips_segment_shorter_than_min_length_in_realtime(self):
        """实时模式：过短分段被跳过，**不应**被标记为 uploading。"""
        events = self.make_live_events(
            common_event_args={
                "auto_render": False, "auto_upload": True,
                "auto_clean": False, "auto_transcode": False,
            },
            upload_args={"src_video": [{
                "engine": "biliwebapi", "realtime": True, "min_length": 120,
            }]},
        )
        state = self.blank_state()
        state["src_video"].update(
            {"status": "ready", "file": self.make_video_info(duration=30, segment_id=1)}
        )
        events.state_dict["g1"] = [state]

        messages = events._check_for_upload("g1")

        self.assertEqual(messages, [])
        self.assertEqual(events.state_dict["g1"][0]["src_video"]["status"], "ready")

    def test_unknown_group_returns_empty(self):
        events = self.make_live_events()
        self.assertEqual(events._check_for_upload("does-not-exist"), [])


class TestStaleGroupResultsAreDropped(DMRTestCase):
    """任务重启后，旧任务的管道结果到达时不得崩溃（生产事故回归）。

    生产实测的调用栈::

        liveevents.py, in onRenderEnd
            video_states = self.state_dict[video.group_id]
        KeyError: '61c1fc64'

    **场景**：配置更新时任务是"删任务 + 5 秒后重建任务"。``onExit`` 会清空
    ``state_dict``，但**旧实例派发出去的渲染/转码/上传任务仍在管道里**；它们完成后
    把结果发回**任务名**，此时由**新实例**处理，而新实例的 ``state_dict`` 是空的。
    因此"结果到达时分组已不存在"是**预期现象**，应当丢弃并告警，而不是抛异常
    ——异常会打断 ``ReplayTask._pipeRecvMonitor`` 的消息处理循环。
    """

    def _events_with_upload(self):
        return self.make_live_events(
            common_event_args={"auto_render": True, "auto_upload": True,
                               "auto_clean": True, "auto_transcode": False},
            upload_args={"src_video": [{
                "engine": "biliwebapi", "target": "bilibili",
                "account": "main", "realtime": True, "min_length": 120,
            }]},
        )

    def _render_end_message(self, group_id="61c1fc64"):
        from DMR.utils import PipeMessage

        return PipeMessage(
            source="render", target="replay/task", event="end",
            request_id="ccdd8024c25511f1a71ac3aff6dcf76c",
            msg="渲染完成",
            data={"output": self.make_video_info(group_id=group_id)},
        )

    def test_on_render_end_with_missing_group_does_not_raise(self):
        events = self._events_with_upload()          # state_dict 为空（等价于刚重启）

        with self.assertLogs("testtask", level="WARNING") as captured:
            ret = events.onRenderEnd(self._render_end_message())

        self.assertEqual(ret, [])
        self.assertTrue(any("已不存在" in line for line in captured.output),
                        "必须告警说明结果被丢弃，否则难以定位")

    def test_on_upload_end_with_missing_group_does_not_raise(self):
        from DMR.utils import PipeMessage

        events = self._events_with_upload()

        ret = events.onUploadEnd(PipeMessage(
            source="uploader", target="replay/task", event="end",
            request_id="req-1", msg="上传完成", data={}))

        self.assertEqual(ret, [])

    def test_check_for_upload_on_missing_group_returns_empty(self):
        events = self._events_with_upload()
        self.assertEqual(events._check_for_upload("61c1fc64"), [])

    def test_free_state_memory_tolerates_group_absent_from_state_dict(self):
        """``ended_dict`` 里有、``state_dict`` 里没有的组不应抛 KeyError。

        ``resume_recovered`` 会直接写 ``ended_dict``；若该组随后被释放，
        两个字典就会不同步。
        """
        import time

        events = self.make_live_events()
        events.ended_dict["61c1fc64"] = time.time()

        events._free_state_memory()

        self.assertNotIn("61c1fc64", events.ended_dict)

    def test_check_for_clean_with_empty_state_is_safe(self):
        events = self.make_live_events(clean_args={
            "src_video": [{"method": "delete", "delay": 0}]})

        self.assertEqual(events._check_for_clean(), [])


class TestCleanStatusAccounting(DMRTestCase):
    """TODO.md B7.2 —— ``_check_for_clean`` 无条件把状态改成 ``cleaned``。

    ``liveevents.py:294`` 的赋值位于 ``for clean_file_types`` 循环之外，因此只要
    产物是 ``uploaded`` 就会被置为 ``cleaned``，**即使没有任何清理规则命中**。
    """

    def _events(self, clean_args):
        return self.make_live_events(
            common_event_args={
                "auto_render": False, "auto_upload": True,
                "auto_clean": True, "auto_transcode": False,
            },
            clean_args=clean_args,
        )

    def _uploaded_state(self):
        state = self.blank_state()
        state["src_video"].update(
            {"status": "uploaded", "file": self.make_video_info(duration=600)}
        )
        return state

    def test_matching_rule_emits_clean_message(self):
        """正常路径：规则命中 → 派发清理消息，并标记为 cleaned。"""
        events = self._events({"src_video": [{"method": "delete", "delay": 0}]})
        events.state_dict["g1"] = [self._uploaded_state()]

        messages = events._check_for_clean()

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].target, "cleaner")
        self.assertEqual(messages[0].event, "newtask")
        self.assertEqual(messages[0].data["method"], "delete")
        self.assertEqual(events.state_dict["g1"][0]["src_video"]["status"], "cleaned")

    def test_nonmatching_rule_must_not_mark_cleaned(self):
        """规则只针对 dm_video 时，src_video 不应被标记为 cleaned。

        B7.2 已修复：原先的赋值在 ``for clean_file_types`` 循环之外，会对**所有**
        已上传产物无条件置为 cleaned，导致"没清理的文件被当作已清理"。
        """
        events = self._events({"dm_video": [{"method": "delete", "delay": 0}]})
        events.state_dict["g1"] = [self._uploaded_state()]

        messages = events._check_for_clean()

        self.assertEqual(messages, [], "没有命中的规则，不应派发清理")
        self.assertEqual(
            events.state_dict["g1"][0]["src_video"]["status"], "uploaded"
        )

    def test_empty_clean_args_must_not_change_status(self):
        """``clean_args`` 为空时不得改变状态（B7.2 的另一面）。"""
        events = self._events({})
        events.state_dict["g1"] = [self._uploaded_state()]

        messages = events._check_for_clean()

        self.assertEqual(messages, [])
        self.assertEqual(
            events.state_dict["g1"][0]["src_video"]["status"], "uploaded"
        )

    def test_only_uploaded_artifacts_are_considered(self):
        """未上传完成的产物不应被清理。"""
        events = self._events({"src_video": [{"method": "delete", "delay": 0}]})
        state = self.blank_state()
        state["src_video"].update(
            {"status": "uploading", "file": self.make_video_info(duration=600)}
        )
        events.state_dict["g1"] = [state]

        messages = events._check_for_clean()

        self.assertEqual(messages, [])
        self.assertEqual(events.state_dict["g1"][0]["src_video"]["status"], "uploading")


class TestArtifactSemantics(DMRTestCase):
    """锁定已核实的产物语义（``PROJECT_STATE.md`` §3.5）。

    关系是**替代**而非串联：``src_video_pre`` 是转码前的原始录制流，
    ``src_video`` 是转码结果并替代它；``dm_video`` 是独立分支。
    """

    def test_blank_state_has_exactly_three_slots(self):
        self.assertEqual(
            set(self.blank_state().keys()),
            {"src_video", "src_video_pre", "dm_video"},
        )

    def test_w_srcpre_cleans_replaced_original_when_cleaning_src_video(self):
        """清理 ``src_video`` 且 ``w_srcpre=True`` 时，被替代的原始流一并清理。"""
        events = self.make_live_events(
            common_event_args={
                "auto_render": False, "auto_upload": True,
                "auto_clean": True, "auto_transcode": True,
            },
            clean_args={"src_video": [
                {"method": "delete", "delay": 0, "w_srcpre": True},
            ]},
        )
        state = self.blank_state()
        state["src_video"].update(
            {"status": "uploaded", "file": self.make_video_info(duration=600)}
        )
        state["src_video_pre"].update(
            {"status": "cleaned",
             "file": self.make_video_info(duration=600, path="raw.flv")}
        )
        events.state_dict["g1"] = [state]

        messages = events._check_for_clean()

        self.assertEqual(len(messages), 1)
        files = messages[0].data["files"]
        self.assertEqual(len(files), 2, "应同时清理 src_video 与其被替代的原始流")
        self.assertIn("raw.flv", [str(f.path) for f in files])

    def test_w_srcpre_false_keeps_replaced_original(self):
        events = self.make_live_events(
            common_event_args={
                "auto_render": False, "auto_upload": True,
                "auto_clean": True, "auto_transcode": True,
            },
            clean_args={"src_video": [
                {"method": "delete", "delay": 0, "w_srcpre": False},
            ]},
        )
        state = self.blank_state()
        state["src_video"].update(
            {"status": "uploaded", "file": self.make_video_info(duration=600)}
        )
        state["src_video_pre"].update(
            {"status": "cleaned",
             "file": self.make_video_info(duration=600, path="raw.flv")}
        )
        events.state_dict["g1"] = [state]

        messages = events._check_for_clean()

        self.assertEqual(len(messages[0].data["files"]), 1)

    def test_w_srcfile_only_applies_to_dm_video(self):
        """``w_srcfile`` 只在清理 ``dm_video`` 时把 ``src_video`` 一并清理。"""
        events = self.make_live_events(
            common_event_args={
                "auto_render": False, "auto_upload": True,
                "auto_clean": True, "auto_transcode": False,
            },
            clean_args={"dm_video": [
                {"method": "delete", "delay": 0, "w_srcfile": True},
            ]},
        )
        state = self.blank_state()
        state["dm_video"].update(
            {"status": "uploaded",
             "file": self.make_video_info(duration=600, path="dm.mp4")}
        )
        state["src_video"].update(
            {"status": "uploaded",
             "file": self.make_video_info(duration=600, path="src.mp4")}
        )
        events.state_dict["g1"] = [state]

        messages = events._check_for_clean()

        self.assertEqual(len(messages), 1)
        paths = [str(f.path) for f in messages[0].data["files"]]
        self.assertIn("dm.mp4", paths)
        self.assertIn("src.mp4", paths, "w_srcfile=True 时应连带清理源视频")


class TestFreeStateMemory(DMRTestCase):
    """``_free_state_memory`` 的释放判定。

    ``ended_dict`` 存的是**时间戳**（``onLiveEnd`` 写入 ``time.time()``）。
    """

    def _events(self):
        return self.make_live_events(
            common_event_args={
                "auto_render": False, "auto_upload": True,
                "auto_clean": False, "auto_transcode": False,
            },
        )

    def test_group_with_pending_artifact_is_retained(self):
        events = self._events()
        uploading = self.blank_state()
        uploading["src_video"].update(
            {"status": "uploading", "file": self.make_video_info(duration=600),
             "wait": ["req1"]}
        )
        events.state_dict["g1"] = [uploading]
        events.ended_dict["g1"] = self.clock.now()

        events._free_state_memory()

        self.assertIn("g1", events.state_dict, "存在未完成产物时不应释放")
        self.assertIn("g1", events.ended_dict)

    def test_group_with_all_artifacts_uploaded_is_freed(self):
        events = self._events()
        state = self.blank_state()
        for slot in ("src_video", "src_video_pre", "dm_video"):
            state[slot]["status"] = "uploaded"
        events.state_dict["g1"] = [state]
        events.ended_dict["g1"] = self.clock.now()

        events._free_state_memory()

        self.assertNotIn("g1", events.state_dict)

    def test_group_older_than_72h_is_dropped(self):
        """超时分支：无论状态如何，超过 72 小时都会释放（防止内存无限增长）。"""
        events = self._events()
        stuck = self.blank_state()
        stuck["src_video"].update(
            {"status": "ready", "file": self.make_video_info(duration=30)}
        )
        events.state_dict["g1"] = [stuck]
        events.ended_dict["g1"] = self.clock.now() - 73 * 3600

        events._free_state_memory()

        self.assertNotIn("g1", events.state_dict)
        self.assertNotIn("g1", events.ended_dict)

    def test_ended_dict_non_numeric_value_drops_group(self):
        """记录一个**类型脆弱点**：``ended_dict`` 存非数值会立即命中超时分支。

        ``time.time() - True`` 不报错而是得到巨大值，导致整组被立即释放。
        生产路径写入的是 ``time.time()``（``liveevents.py:136``），因此当前安全；
        本用例把这个隐含契约固定下来，防止将来误写入布尔值。
        """
        events = self._events()
        state = self.blank_state()
        state["src_video"].update(
            {"status": "uploading", "file": self.make_video_info(duration=600),
             "wait": ["req1"]}
        )
        events.state_dict["g1"] = [state]
        events.ended_dict["g1"] = True  # 错误类型：并非时间戳

        events._free_state_memory()

        self.assertNotIn(
            "g1", events.state_dict,
            "非数值时间戳会因算术得到巨大差值而立即释放整组",
        )


if __name__ == "__main__":
    unittest.main()
