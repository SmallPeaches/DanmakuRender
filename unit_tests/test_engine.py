"""``DMR.engine.DMREngine`` 启动路径的测试（P0）。

重点固定 ``engine.py:69/75`` 的循环解包问题（TODO.md B7.5）以及它今天为什么
**没有**导致程序无法启动。
"""
from __future__ import annotations

import queue
import threading
import unittest

from unit_tests.support import DMRTestCase


class _StubPlugin:
    """最小插件替身：只记录是否被启动过。"""

    def __init__(self) -> None:
        self.started = 0
        self.stopped = 0

    def start(self) -> None:
        self.started += 1

    def stop(self) -> None:
        self.stopped += 1


class TestEngineStart(DMRTestCase):

    def _make_engine(self):
        from DMR.engine import DMREngine

        engine = DMREngine()
        self.addCleanup(self._cleanup_engine, engine)
        return engine

    @staticmethod
    def _cleanup_engine(engine) -> None:
        """停掉引擎创建的守护线程，避免测试进程残留线程。"""
        engine.stoped = True
        if engine.recv_queue is not None:
            from DMR.utils import PipeMessage

            try:
                engine.recv_queue.put(
                    PipeMessage(source="test", target="engine", event="exit")
                )
            except Exception:
                pass

    def _register_plugin(self, engine, name: str = "render"):
        plugin = _StubPlugin()
        engine.plugin_dict[name] = {
            "class": plugin,
            "config": {},
            "send_queue": queue.Queue(),
            "status": 0,
        }
        return plugin

    def test_start_on_empty_engine_succeeds(self):
        """真实启动顺序：先 ``engine.start()``，此时字典还是空的。

        这正是 ``DMR/__init__.py:29`` 的调用方式，也是 ``engine.py:69`` 的缺陷
        今天不爆炸的原因。
        """
        engine = self._make_engine()

        engine.start()

        self.assertFalse(engine.stoped)
        self.assertIsNotNone(engine.recv_queue)

    @unittest.expectedFailure
    def test_start_with_preloaded_plugin_is_not_idempotent(self):
        """已注册插件后再调 ``start()`` 不应崩溃（B7.5）。

        ``engine.py:69`` 是 ``for name, plugin in self.plugin_dict.values()``，
        每次迭代产出的是单个 dict（4 个键），解包成 2 个名字必然
        ``ValueError: too many values to unpack``；下一行
        ``self.plugin_dict['name']`` 同样是笔误（写死字符串而非循环变量）。

        正确写法应为 ``.items()`` + ``self.plugin_dict[name]['status']``。
        """
        engine = self._make_engine()
        self._register_plugin(engine, "render")

        engine.start()  # 修复后此行应通过

    @unittest.expectedFailure
    def test_start_does_not_start_preloaded_plugins_twice(self):
        """修复 B7.5 时，不要重复启动已经 ``add_plugin`` 启动过的插件。

        ``add_plugin`` 在引擎非停止状态时已经调用过 ``plugin.start()``，并把
        ``status`` 置为 1；因此 ``start()`` 的循环必须尊重 ``status`` 判断。
        本用例在上游修复前会因解包异常而失败。
        """
        engine = self._make_engine()
        plugin = self._register_plugin(engine, "render")
        plugin.start()                          # 模拟 add_plugin 的行为
        engine.plugin_dict["render"]["status"] = 1

        engine.start()                          # 修复后此行应通过

        self.assertEqual(plugin.started, 1, "status=1 的插件不应被重复启动")

    @unittest.expectedFailure
    def test_start_with_preloaded_plugin_no_unpack_error(self):
        """与上例等价的缺陷记录（B7.5），断言"不应抛异常"。"""
        engine = self._make_engine()
        self._register_plugin(engine, "render")

        engine.start()


class TestEngineRouting(DMRTestCase):
    """``engine.pipeSend`` 的目标分发：未知目标只记日志，不抛异常。"""

    def test_unknown_target_does_not_raise(self):
        from DMR.engine import DMREngine
        from DMR.utils import PipeMessage

        engine = DMREngine()
        engine.recv_queue = queue.Queue()

        # 不应抛异常（当前实现只记录 error 日志）
        engine.pipeSend(PipeMessage(source="a", target="nobody", event="e"))

    def test_plugin_target_is_queued(self):
        from DMR.engine import DMREngine
        from DMR.utils import PipeMessage

        engine = DMREngine()
        engine.recv_queue = queue.Queue()
        send_queue: queue.Queue = queue.Queue()
        engine.plugin_dict["downloader"] = {
            "class": None, "config": {}, "send_queue": send_queue, "status": 0,
        }

        msg = PipeMessage(source="a", target="downloader", event="e")
        engine.pipeSend(msg)

        self.assertIs(send_queue.get_nowait(), msg)

    def test_replay_target_routes_to_task_queue(self):
        from DMR.engine import DMREngine
        from DMR.utils import PipeMessage

        engine = DMREngine()
        engine.recv_queue = queue.Queue()
        send_queue: queue.Queue = queue.Queue()
        engine.task_dict["t1"] = {
            "class": None, "config": {}, "send_queue": send_queue, "status": 0,
        }

        msg = PipeMessage(source="a", target="replay/t1", event="e")
        engine.pipeSend(msg)

        self.assertIs(send_queue.get_nowait(), msg)

    def test_replay_target_for_missing_task_does_not_raise(self):
        from DMR.engine import DMREngine
        from DMR.utils import PipeMessage

        engine = DMREngine()
        engine.recv_queue = queue.Queue()

        engine.pipeSend(PipeMessage(source="a", target="replay/missing", event="e"))


class TestBareTasknameRouting(DMRTestCase):
    """**裸任务名必须能路由到任务**（生产事故的回归）。

    事故经过：上传器回包时把消息来源原样当 target（``target=task['source']``），
    而来源是否带 ``replay/`` 前缀取决于 liveevents 怎么填。旧版本填的是裸任务名，
    于是 ``target.startswith('replay/')`` 为假 → 消息落进 else 分支被静默丢弃 →
    ``onUploadEnd`` 从不执行 → 产物永远停在 ``uploading``/``recorded``，
    清理也不再触发（B站上稿件已上传成功，状态库里却查不到）。

    修复方式：路由不再依赖前缀约定，命中已知任务名即直接投递。
    """

    def _engine_with_task(self, taskname="twitchpros-yrvz72-0"):
        from DMR.engine import DMREngine

        engine = DMREngine()
        engine.recv_queue = queue.Queue()
        send_queue: queue.Queue = queue.Queue()
        engine.task_dict[taskname] = {
            "class": None, "config": {}, "send_queue": send_queue, "status": 0,
        }
        return engine, taskname, send_queue

    def test_bare_taskname_routes_to_task(self):
        from DMR.utils import PipeMessage

        engine, taskname, send_queue = self._engine_with_task()

        msg = PipeMessage(source="uploader", target=taskname, event="end")
        engine.pipeSend(msg)

        self.assertIs(send_queue.get_nowait(), msg,
                      "裸任务名必须投递到该任务（上传完成通知依赖它）")

    def test_prefixed_form_still_works(self):
        """兼容既有写法：``replay/<taskname>`` 仍应可用。"""
        from DMR.utils import PipeMessage

        engine, taskname, send_queue = self._engine_with_task()

        msg = PipeMessage(source="a", target=f"replay/{taskname}", event="e")
        engine.pipeSend(msg)

        self.assertIs(send_queue.get_nowait(), msg)

    def test_taskname_containing_slash_is_not_truncated(self):
        """任务名本身含 ``/`` 时不能被截断。

        旧实现取 ``target.split('/')[1]``，对 ``replay/a/b`` 只会得到 ``a``。
        """
        from DMR.utils import PipeMessage

        engine, taskname, send_queue = self._engine_with_task("group/sub")

        engine.pipeSend(PipeMessage(source="a", target="replay/group/sub", event="e"))

        self.assertIs(send_queue.get_nowait().target, "replay/group/sub")

    def test_plugin_name_wins_over_same_named_task(self):
        """插件名是保留标识：名为 ``uploader`` 的任务不得截走发往上传器的消息。"""
        from DMR.utils import PipeMessage

        engine, _, _ = self._engine_with_task("uploader")
        plugin_queue: queue.Queue = queue.Queue()
        engine.plugin_dict["uploader"] = {
            "class": None, "config": {}, "send_queue": plugin_queue, "status": 0,
        }

        engine.pipeSend(PipeMessage(source="a", target="uploader", event="e"))

        self.assertEqual(plugin_queue.qsize(), 1, "应投递给上传器插件")
        self.assertEqual(engine.task_dict["uploader"]["send_queue"].qsize(), 0)

    def test_missing_task_logs_warning_with_context(self):
        """任务不存在时应告警并带上 source/event，便于定位发送方。"""
        from DMR.engine import DMREngine
        from DMR.utils import PipeMessage

        engine = DMREngine()
        engine.recv_queue = queue.Queue()

        with self.assertLogs("DMR.engine", level="WARNING") as captured:
            engine.pipeSend(PipeMessage(source="uploader", target="ghost",
                                        event="end"))

        output = "\n".join(captured.output)
        self.assertIn("ghost", output)
        self.assertIn("uploader", output, "应记录消息来源")
        self.assertIn("end", output, "应记录事件名")

    def test_unknown_target_reports_source_and_event(self):
        from DMR.engine import DMREngine
        from DMR.utils import PipeMessage

        engine = DMREngine()
        engine.recv_queue = queue.Queue()

        with self.assertLogs("DMR.engine", level="ERROR") as captured:
            engine.pipeSend(PipeMessage(source="render", target="nobody",
                                        event="newtask"))

        output = "\n".join(captured.output)
        self.assertIn("nobody", output)
        self.assertIn("render", output)
        self.assertIn("newtask", output)

    def test_resolve_target_kinds(self):
        from DMR.engine import DMREngine

        engine, _, _ = self._engine_with_task("t1")
        engine.plugin_dict["render"] = {
            "class": None, "config": {}, "send_queue": queue.Queue(), "status": 0,
        }

        self.assertEqual(engine._resolve_target("engine"), ("engine", "engine"))
        self.assertEqual(engine._resolve_target("t1"), ("task", "t1"))
        self.assertEqual(engine._resolve_target("replay/t1"), ("task", "t1"))
        self.assertEqual(engine._resolve_target("render"), ("plugin", "render"))
        self.assertEqual(engine._resolve_target("nobody"), ("unknown", "nobody"))


if __name__ == "__main__":
    unittest.main()
