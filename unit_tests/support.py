"""P0 测试基座：共享路径设置与最小测试替身（fakes）。

设计约束（对应 TODO.md B8 P0）：
1. **零新增依赖**：只用标准库 ``unittest``（本机未安装 pytest）。将来装上 pytest 也能
   直接收集这些用例，因为它们就是标准 ``unittest.TestCase``。
2. **不需要网络 / 磁盘 / 子进程**：这些替身让核心逻辑可在毫秒级被单独验证。
3. 测试通过 ``python -m unittest discover -s unit_tests -t .`` 运行；此处显式把仓库
   根目录加入 ``sys.path``，使测试不依赖调用时的当前目录。
"""
from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta
from typing import Iterable

# --- 让 unit_tests/ 下的用例可以 import DMR（不依赖调用目录） -----------------
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _silence_library_logging() -> None:
    """静音被测代码的日志，避免污染测试输出。

    被测模块普遍用 ``logging.getLogger(__name__)`` 直接打日志（如
    ``DMREngine`` 的 "Unknown target"、下载器的 "Task missing not exists"）。
    这些是**预期行为**，不是测试失败。

    实现方式：给根 logger 装一个 ``NullHandler`` 并关闭向上传播，而不是用
    ``logging.disable()``（后者会连带禁掉测试自身想看的日志）。
    """
    import logging

    root = logging.getLogger()
    if not any(isinstance(h, logging.NullHandler) for h in root.handlers):
        root.addHandler(logging.NullHandler())
    root.propagate = False


# 在任何用例构造 logger 之前生效。放在模块级而非 setUpModule，是因为
# support.py 不是 test 模块，unittest discover 不会调用它的 setUpModule。
_silence_library_logging()


class FakeClock:
    """可手动推进的时钟，默认从**真实当前时间**起算。

    为什么需要：``LiveEvents._free_state_memory`` 的 72 小时超时逻辑、
    ``ended_dict`` 的时间戳判定，都依赖真实时间。没有可注入的时钟就只能靠
    "读代码"判断，这正是之前只能靠人肉审查发现 bug 的原因。

    ⚠️ 起始值必须锚定 ``time.time()`` 而不是写死一个大常数：被测代码目前直接调用
    ``time.time()``（尚未注入时钟），若起始值跑到未来，"N 小时前"的时间戳会大于
    真实 now，超时判定永远不成立 —— 这类**测试基建自身的错误**比被测代码的 bug
    更难发现，所以这里显式锚定真实时间。
    """

    def __init__(self, start: float | None = None) -> None:
        import time as _time

        self._now = float(_time.time() if start is None else start)

    def now(self) -> float:
        return self._now

    def advance(self, seconds: float) -> float:
        self._now += float(seconds)
        return self._now


class FakeEventBus:
    """最小事件总线替身：记录被发布的事件，供断言使用。

    目前生产代码还没有总线（那是 P3/P4 的内容）；先提供替身，使新写的测试
    可以按"事件"而非"内部 dict"来断言，避免继续耦合到 ``state_dict`` 结构。
    """

    def __init__(self) -> None:
        self.published: list[object] = []

    def publish(self, event: object) -> None:
        self.published.append(event)

    def of_type(self, event_type: type) -> list[object]:
        return [e for e in self.published if isinstance(e, event_type)]


class InMemoryArtifactRepo:
    """内存产物仓储替身（后续 P1 会替换为 SQLite 实现）。

    只实现当前测试需要的语义：按 group 收集产物、按键查询、清空。
    """

    def __init__(self) -> None:
        self._items: dict[str, object] = {}

    def add(self, key: str, artifact: object) -> None:
        self._items[key] = artifact

    def get(self, key: str) -> object | None:
        return self._items.get(key)

    def all(self) -> list[object]:
        return list(self._items.values())

    def keys(self) -> Iterable[str]:
        return tuple(self._items.keys())

    def __len__(self) -> int:
        return len(self._items)


class RecordingSubprocessRunner:
    """子进程替身：记录被调用的命令，不真的执行。

    用途：验证"渲染/上传会拼出什么命令"这类逻辑，而不必依赖本机安装 ffmpeg。
    """

    def __init__(self, returncode: int = 0, stdout: bytes = b"") -> None:
        self.calls: list[list[str]] = []
        self.returncode = returncode
        self.stdout = stdout

    def run(self, cmd: list[str], **kwargs) -> "RecordingSubprocessRunner":
        self.calls.append(list(cmd))
        return self

    def wait(self) -> int:
        return self.returncode


class DMRTestCase(unittest.TestCase):
    """所有 DMR 用例的基类：统一提供时钟与常用构造工具。"""

    def setUp(self) -> None:
        self.clock = FakeClock()

    # --- 便于构造领域对象的小工具（避免每个用例重复样板） ---

    @staticmethod
    def make_video_info(duration=600.0, segment_id=1, group_id="g1", dtype="src_video",
                        path=None):
        """构造一个领域 ``VideoInfo``。

        注意：``VideoInfo`` 是 ``cpdict`` 子类，构造参数会被同时设为属性与字典项。
        """
        from DMR.utils import VideoInfo

        return VideoInfo(
            path=path or f"seg{segment_id}.mp4",
            file_id=f"f{segment_id}",
            dtype=dtype,
            duration=duration,
            group_id=group_id,
            segment_id=segment_id,
        )

    @staticmethod
    def blank_state():
        """复刻 ``LiveEvents.onLiveSegment`` 初始化出来的三产物槽位。"""
        return {
            "src_video": {"status": None, "file": None, "wait": []},
            "src_video_pre": {"status": None, "file": None, "wait": []},
            "dm_video": {"status": None, "file": None, "wait": []},
        }

    @staticmethod
    def make_live_events(common_event_args=None, upload_args=None, clean_args=None,
                         download_args=None, render_args=None):
        """构造一个**不启动线程**的 ``LiveEvents`` 实例，用于单测状态机逻辑。

        走 ``__new__`` 而非 ``__init__``：``LiveEvents.__init__`` 需要 name/config，
        且会建立 state_dict/ended_dict，本函数直接给出等价的最小内部状态。
        """
        import logging

        from DMR.Task.liveevents import LiveEvents

        events = LiveEvents.__new__(LiveEvents)
        events.name = "testtask"
        events.logger = logging.getLogger("testtask")
        events.state_dict = {}
        events.ended_dict = {}
        # 与 LiveEvents.__init__ 保持一致：这些属性由 __init__ 建立，
        # 而本函数用 __new__ 绕过 __init__（避免依赖线程与真实配置）
        events.state_repo = None
        events._sessions_ensured = set()
        events.config = {
            "common_event_args": common_event_args or {
                "auto_render": False, "auto_upload": False,
                "auto_clean": False, "auto_transcode": False,
            },
            "upload_args": upload_args if upload_args is not None else {},
            "clean_args": clean_args if clean_args is not None else {},
            "download_args": download_args or {"dltype": "live"},
            "render_args": render_args or {},
            # 状态持久化默认关闭；需要验证同步行为的用例自行注入内存状态库
            "state_repo": None,
        }
        return events

    def assertWithin(self, value, low, high):  # pragma: no cover - 便捷断言
        self.assertGreaterEqual(value, low)
        self.assertLessEqual(value, high)


def drain_queue(q, timeout: float = 1.0, max_items: int = 100) -> list:
    """把队列里当前可取的项全部取出（最多 ``max_items`` 个）。

    用于验证经由 ``ReplayTask`` 后台线程转发的消息。使用 ``get(timeout=...)``
    配合空队列判断，避免依赖固定 sleep 造成的不稳定。
    """
    import queue as _queue

    items = []
    while len(items) < max_items:
        try:
            items.append(q.get(timeout=timeout))
        except _queue.Empty:
            break
    return items


__all__ = [
    "FakeClock",
    "FakeEventBus",
    "InMemoryArtifactRepo",
    "RecordingSubprocessRunner",
    "DMRTestCase",
    "drain_queue",
    "timedelta",
    "datetime",
]
