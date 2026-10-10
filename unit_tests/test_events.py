"""``ReplayTask`` 事件路由与 ``LiveEvents`` 事件表注册的测试（P0）。

``ReplayTask`` 会把消息转成 ``source + '/' + event`` 形式的事件键去查表
（``replaytask.py:35``）。这层字符串耦合是当前架构的主要脆弱点之一，这里把它的
**现有可工作行为**与**已知缺陷**分别固定下来。
"""
from __future__ import annotations

import queue
import unittest

from unit_tests.support import DMRTestCase, drain_queue


class TestReplayTaskRouting(DMRTestCase):
    """验证经由后台线程的真实事件路由。"""

    def _make_task(self, name: str = "mytask", config: dict | None = None):
        from DMR.Task import ReplayTask

        config = config or {
            "common_event_args": {
                "auto_render": False, "auto_upload": False,
                "auto_clean": False, "auto_transcode": False,
            },
            "download_args": {"dltype": "live"},
            "upload_args": {},
            "clean_args": {},
            "render_args": {},
        }
        send_queue: queue.Queue = queue.Queue()
        recv_queue: queue.Queue = queue.Queue()
        task = ReplayTask(name, config, (send_queue, recv_queue))
        task.start()
        self.addCleanup(task.stop)
        return task, send_queue, recv_queue

    def test_engine_ready_message_produces_downloader_newtask(self):
        """``engine.start()`` 发出的 ready 消息应触发下载器建任务。

        这是整条链路能跑起来的前提：``LiveEvents.onReady`` → ``downloader/newtask``。
        """
        from DMR.utils import PipeMessage

        task, send_queue, recv_queue = self._make_task("mytask")

        recv_queue.put(PipeMessage(source="engine", target="replay/mytask",
                                   event="ready"))
        messages = drain_queue(send_queue)

        self.assertEqual(len(messages), 1, "ready 应恰好产生一条下行消息")
        msg = messages[0]
        self.assertEqual(msg.target, "downloader")
        self.assertEqual(msg.event, "newtask")
        self.assertEqual(msg.data["taskname"], "mytask")
        self.assertEqual(msg.data["dltype"], "live")
        # source 会被加上 replay/ 前缀，以便引擎路由回该任务
        self.assertEqual(msg.source, "replay/mytask")

    def test_downloader_livestart_is_handled_by_default_event(self):
        """``downloader/livestart`` 注册的是 ``defaultEvent``（只记日志，不回消息）。"""
        from DMR.utils import PipeMessage

        task, send_queue, recv_queue = self._make_task("mytask")

        recv_queue.put(PipeMessage(source="downloader", target="replay/mytask",
                                   event="livestart", msg="直播开始"))
        messages = drain_queue(send_queue, timeout=0.3)

        self.assertEqual(messages, [], "defaultEvent 不产生下行消息")

    def test_unregistered_event_falls_back_without_crashing(self):
        """未注册事件应静默降级到 default，不能抛异常打断处理循环。"""
        from DMR.utils import PipeMessage

        task, send_queue, recv_queue = self._make_task("mytask")

        recv_queue.put(PipeMessage(source="nobody", target="replay/mytask",
                                   event="something-weird"))
        recv_queue.put(PipeMessage(source="engine", target="replay/mytask",
                                   event="ready"))
        messages = drain_queue(send_queue)

        # 关键：奇怪事件没有打断循环，后续 ready 仍被正常处理
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].event, "newtask")

    def test_message_for_other_task_is_ignored(self):
        from DMR.utils import PipeMessage

        task, send_queue, recv_queue = self._make_task("mytask")

        recv_queue.put(PipeMessage(source="engine", target="replay/othertask",
                                   event="ready"))
        recv_queue.put(PipeMessage(source="engine", target="replay/mytask",
                                   event="ready"))
        messages = drain_queue(send_queue)

        self.assertEqual(len(messages), 1, "发给他人的消息不应被本任务处理")

    def test_exit_event_stops_task(self):
        from DMR.utils import PipeMessage

        task, send_queue, recv_queue = self._make_task("mytask")

        recv_queue.put(PipeMessage(source="engine", target="replay/mytask",
                                   event="exit"))
        messages = drain_queue(send_queue)

        self.assertTrue(task.stoped, "exit 事件应停止任务")
        self.assertTrue(any(m.target == "downloader" and m.event == "stoptask"
                            for m in messages),
                        "exit 应通知下载器停止任务")


class TestEventRegistry(DMRTestCase):
    """``LiveEvents.event_dict`` 与 ``ReplayTask.add_event`` 的注册行为。"""

    def _registry(self):
        from DMR.Task import ReplayTask

        task = ReplayTask.__new__(ReplayTask)
        task._event_dict = {}
        return task

    def test_event_dict_has_no_duplicate_handlers(self):
        """``event_dict`` 的每个值都是单个可调用对象（当前实现如此）。

        这条事实是 ``add_event`` 的覆盖缺陷（B7.3）今天不爆的前提：若某天某个值
        变成 list，注册机制会静默产生嵌套 list，回放时 TypeError。
        """
        events = self.make_live_events()

        for key, handler in events.event_dict.items():
            self.assertFalse(
                isinstance(handler, (list, tuple, set)),
                f"事件 {key} 的值是容器，会触发 add_event 的嵌套缺陷（B7.3）",
            )
            self.assertTrue(callable(handler), f"事件 {key} 的值不可调用")

    def test_registered_event_names_use_expected_prefix_rule(self):
        """固定事件键的两种形态与其查找路径（``replaytask.py:35-36``）。

        查找有**两级**：

        1. ``source + '/' + event``（如 ``downloader/livesegment``）—— 需要前缀；
        2. 退化到纯 ``event``（如 ``ready``）—— 不需要前缀。

        因此注册表里同时存在两类键。把这条规则固定下来，避免误以为所有键都必须
        带前缀，也避免漏掉"来源与事件名必须精确拼写"这一脆弱点。
        """
        events = self.make_live_events()

        # 这些键靠第二级查找（纯 event）命中，属于有意设计
        unprefixed = {"default", "exit", "ready"}
        for key in events.event_dict:
            if key in unprefixed:
                continue
            self.assertIn(
                "/", key,
                f"事件键 {key!r} 缺少 source/ 前缀，将只能靠第二级查找命中",
            )

    def test_ready_is_reachable_via_second_level_lookup(self):
        """``ready`` 走第二级查找：键是纯 ``ready``，而消息来源是 ``engine``。

        这解释了为何 ``replaytask.py:36`` 需要 ``_event_dict.get(msg.event)``
        这一级退化查找；也是 ``TestReplayTaskRouting`` 里 ready 用例能通过的
        真正原因（而非前缀匹配）。
        """
        events = self.make_live_events()
        self.assertIn("ready", events.event_dict)
        self.assertNotIn("engine/ready", events.event_dict)

    @unittest.expectedFailure
    def test_add_event_accumulates_handlers(self):
        """同一事件注册两个 handler 时都应被保留（B7.3）。

        ``replaytask.py:21-23`` 先 ``append`` 又无条件覆盖，导致只留最后一个。
        """
        task = self._registry()

        def first(_msg):
            return None

        def second(_msg):
            return None

        task.add_event("render/end", first)
        task.add_event("render/end", second)

        self.assertEqual(len(task._event_dict["render/end"]), 2)

    @unittest.expectedFailure
    def test_add_event_with_list_value_does_not_nest(self):
        """``event_dict`` 值为 list 时不应产生嵌套结构（B7.3 的另一面）。

        ``replaytask.py:78-82`` 会先对 list 的每个元素 ``add_event``，再把整个
        list 也 ``add_event`` 一次，于是末元素变成 list-of-list，回放时
        ``func(msg)`` 直接 TypeError。当前不触发仅因为 ``liveevents.event_dict``
        的值都是单个 bound method。
        """
        task = self._registry()

        def first(_msg):
            return None

        def second(_msg):
            return None

        # 复刻 replaytask.start() 对 list 值的处理方式
        for func in (first, second):
            task.add_event("e", func)
        task.add_event("e", [first, second])

        for entry in task._event_dict["e"]:
            self.assertTrue(callable(entry),
                            f"handler 应为可调用对象，实际为 {type(entry).__name__}")


if __name__ == "__main__":
    unittest.main()
