"""``DanmakuRender`` 与状态库/对账接线的集成测试（P1）。

覆盖：
- 默认状态库路径为 ``logs/dmr_state.db``
- 首次启动创建状态库、产出对账报告、并把报告的 taskname 写入库
- 二次启动能读回状态（持久化生效）
- **任务集与状态库不一致时拒绝启动**（防止误删历史状态）
"""
from __future__ import annotations

import os
import tempfile
import unittest

from unit_tests.support import DMRTestCase


class _WiringTestCase(DMRTestCase):
    """共享：临时目录里放一份全局配置 + 一个任务配置。"""

    def setUp(self) -> None:
        super().setUp()
        # ignore_cleanup_errors：Windows 下 sqlite 的 .db 句柄可能比清理时机活得久，
        # 删不掉临时目录不应让测试失败（被测行为与此无关）
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.tmpdir = self._tmp.name

    def make_config(self, taskname: str = "test", *, config_path: str | None = None,
                    subdir: str = ""):
        """写一份可用于 ``Config`` 的全局配置 + 任务配置，返回全局配置路径。"""
        from DMR.Config import Config

        config_dir = os.path.join(self.tmpdir, subdir or "configs")
        os.makedirs(config_dir, exist_ok=True)

        task_file = os.path.join(config_dir, f"DMR-{taskname}.yml")
        with open(task_file, "w", encoding="utf-8") as handle:
            handle.write(
                "common_event_args:\n"
                "  auto_render: 0\n"
                "  auto_upload: 0\n"
                "  auto_clean: False\n"
                "  auto_transcode: False\n"
                "download_args:\n"
                "  dltype: live\n"
                "  url: https://live.bilibili.com/1\n"
            )

        global_file = os.path.join(config_dir, "global.yml")
        with open(global_file, "w", encoding="utf-8") as handle:
            handle.write(
                "dmr_engine_args:\n"
                f"  config_path: {config_path or config_dir}\n"
                "  enabled_plugins: ['downloader']\n"
                f"state:\n  db_path: {os.path.join(self.tmpdir, 'dmr_state.db')}\n"
            )
        return Config(global_file)

    def make_dmr(self, config):
        from DMR import DanmakuRender

        dmr = DanmakuRender(config)
        self.addCleanup(dmr.stop)
        return dmr


class TestStateWiring(_WiringTestCase):

    def test_default_db_path_is_logs(self):
        """未配置 state.db_path 时使用约定的 logs/dmr_state.db。"""
        from DMR import DanmakuRender

        config = self.make_config()
        config.global_config.pop("state", None)

        dmr = DanmakuRender.__new__(DanmakuRender)
        dmr.config = config

        self.assertEqual(dmr._resolve_state_db_path(),
                         os.path.join("logs", "dmr_state.db"))

    def test_state_db_path_can_be_configured(self):
        config = self.make_config()
        dmr = self.make_dmr(config)
        self.assertTrue(dmr.state_db_path.endswith("dmr_state.db"))
        self.assertTrue(os.path.isabs(dmr.state_db_path))

    def test_first_start_creates_db_and_report(self):
        config = self.make_config()
        dmr = self.make_dmr(config)

        self.assertIsNotNone(dmr.state_repo, "状态库应已打开")
        self.assertIsNotNone(dmr.recovery_report, "应产出对账报告")
        self.assertEqual(dmr.recovery_report.errors, [])
        self.assertTrue(os.path.exists(dmr.state_db_path), "状态库文件应已创建")
        from DMR.state import SCHEMA_VERSION
        self.assertEqual(dmr.state_repo.schema_version, SCHEMA_VERSION)

    def test_recovery_populates_state_used_by_consistency_check(self):
        """对账后库里能查到任务 —— 这是任务集校验的依据。"""
        config = self.make_config()
        dmr = self.make_dmr(config)

        # 手工写入一条会话，模拟"上一轮运行留下的状态"
        dmr.state_repo.create_session("sess-x", "test", streamer_name="主播")

        self.assertIn("test", {s.taskname for s in dmr.state_repo.list_sessions()})

    def test_state_survives_reopen(self):
        """第二次启动应能读回上一轮写入的状态（持久化生效）。"""
        config = self.make_config()
        first = self.make_dmr(config)
        first.state_repo.create_session("sess-1", "test", streamer_name="主播")
        first.stop()

        second = self.make_dmr(self.make_config())
        self.assertIsNotNone(second.state_repo.get_session("sess-1"))


class TestTaskSetConsistency(_WiringTestCase):
    """状态库是单一全局库，配置目录一换就会"任务消失"，必须拒绝启动。"""

    def test_missing_task_refuses_to_start(self):
        from DMR import DanmakuRender, StateConsistencyError

        config = self.make_config(taskname="test")
        first = self.make_dmr(config)
        first.state_repo.create_session("sess-1", "test")
        first.stop()

        # 换一个只有别的任务的配置目录，但复用同一个状态库
        other = self.make_config(taskname="other", subdir="configs2")
        with self.assertRaises(StateConsistencyError) as ctx:
            DanmakuRender(other)

        message = str(ctx.exception)
        self.assertIn("test", message, "错误信息应指出缺失的任务名")
        self.assertIn("dmr_state.db", message, "错误信息应给出处置指引")

    def test_refused_start_releases_state_db(self):
        """拒绝启动时不能留下打开的状态库连接（否则临时目录无法清理）。"""
        from DMR import DanmakuRender, StateConsistencyError

        config = self.make_config(taskname="test")
        first = self.make_dmr(config)
        first.state_repo.create_session("sess-1", "test")
        first.stop()

        other = self.make_config(taskname="other", subdir="configs3")
        with self.assertRaises(StateConsistencyError):
            DanmakuRender(other)

        # 连接已释放：可以用独占方式重新打开文件
        import sqlite3
        path = os.path.join(self.tmpdir, "dmr_state.db")
        conn = sqlite3.connect(path, timeout=1.0)
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM sessions")
                             .fetchone()[0], 1)
            conn.execute("BEGIN EXCLUSIVE")
            conn.rollback()
        finally:
            conn.close()

    def test_matching_task_set_starts_normally(self):
        config = self.make_config(taskname="test")
        first = self.make_dmr(config)
        first.state_repo.create_session("sess-1", "test")
        first.stop()

        second = self.make_dmr(self.make_config(taskname="test"))
        self.assertIsNotNone(second.state_repo)
        self.assertIsNotNone(second.state_repo.get_session("sess-1"))

    def test_missing_db_is_not_an_error(self):
        """全新环境（库不存在）不应出错。"""
        config = self.make_config()
        dmr = self.make_dmr(config)
        self.assertIsNotNone(dmr.state_repo)
        self.assertEqual(dmr.state_repo.list_sessions(), [])


class TestStateRepoInjection(_WiringTestCase):
    """``start()`` 应把状态库交给需要它的组件（下载器与上传器）。"""

    def test_downloader_module_reference_is_set_on_start(self):
        """下载器用模块级引用接收状态库（避免污染用户配置命名空间）。"""
        from DMR.Downloader import stream_downloader as sd
        from DMR import DanmakuRender

        original = sd._STATE_REPO
        self.addCleanup(lambda: setattr(sd, '_STATE_REPO', original))

        config = self.make_config()
        dmr = DanmakuRender(config)
        dmr.start()
        self.addCleanup(dmr.stop)

        self.assertIs(sd._STATE_REPO, dmr.state_repo)

    def test_uploader_plugin_receives_state_repo(self):
        from DMR import DanmakuRender

        config = self.make_config()
        # 启用上传器以便检查注入
        config.global_config['dmr_engine_args']['enabled_plugins'] = [
            'downloader', 'uploader']

        dmr = DanmakuRender(config)
        dmr.start()
        self.addCleanup(dmr.stop)

        uploader = dmr.engine.plugin_dict['uploader']['class']
        self.assertIs(uploader.state_repo, dmr.state_repo)

    def test_downloader_plugin_receives_state_repo(self):
        from DMR import DanmakuRender

        config = self.make_config()
        dmr = DanmakuRender(config)
        dmr.start()
        self.addCleanup(dmr.stop)

        downloader = dmr.engine.plugin_dict['downloader']['class']
        self.assertIs(downloader.state_repo, dmr.state_repo)

    def test_no_injection_when_state_db_unavailable(self):
        """状态库初始化失败时应照常启动（只是不持久化），不能因此崩溃。"""
        from DMR.Downloader import stream_downloader as sd
        from DMR import DanmakuRender

        original = sd._STATE_REPO
        self.addCleanup(lambda: setattr(sd, '_STATE_REPO', original))
        sd.set_state_repo(None)

        config = self.make_config()
        config.global_config['state'] = {'db_path': ':memory:'}
        dmr = DanmakuRender(config)
        dmr.start()
        self.addCleanup(dmr.stop)

        # 内存库能正常打开，因此应当注入成功
        self.assertIsNotNone(dmr.state_repo)


class TestResumePendingArtifacts(_WiringTestCase):
    """``_resume_pending_artifacts``：把没做完的产物重新送回处理链。

    这是对"服务器上重启后正在录制的文件既没改名也没上传"的直接回归 ——
    ``reconcile()`` 只对账不重跑，这一步才是让它继续处理的关键接线。
    """

    def make_config_with_upload(self, taskname: str = "test"):
        """带真实上传参数的任务配置（不开启渲染，避免依赖渲染插件）。"""
        from DMR.Config import Config

        config_dir = os.path.join(self.tmpdir, "configs")
        os.makedirs(config_dir, exist_ok=True)
        with open(os.path.join(config_dir, f"DMR-{taskname}.yml"), "w",
                  encoding="utf-8") as handle:
            handle.write(
                "common_event_args:\n"
                "  auto_render: 0\n  auto_upload: 1\n"
                "  auto_clean: 0\n  auto_transcode: 0\n"
                "download_args:\n  dltype: live\n  url: https://live.bilibili.com/1\n"
                "upload_args:\n"
                "  src_video:\n"
                "    target: bilibili\n"
                "    engine: biliwebapi\n"
                "    account: tester\n"
                "    realtime: 1\n"
                "    min_length: 10\n"
            )
        global_file = os.path.join(config_dir, "global.yml")
        with open(global_file, "w", encoding="utf-8") as handle:
            handle.write(
                "dmr_engine_args:\n"
                f"  config_path: {config_dir}\n"
                "  enabled_plugins: ['downloader', 'uploader']\n"
                f"state:\n  db_path: {os.path.join(self.tmpdir, 'dmr_state.db')}\n"
            )
        return Config(global_file)

    def seed_artifact(self, taskname="test", *, state="recorded", size_mb=40,
                      **extra):
        """往状态库里塞一个"上次没做完"的产物，返回 (artifact, 文件路径)。

        ``size_mb`` 默认 40MB：需高于 ``recovery.min_valid_size_mb``（默认 30MB），
        否则会被判为"太小、不恢复"（判定规则见 ``is_recovered_file_usable``）。
        """
        from DMR.state import ArtifactKind, make_artifact_key

        repo = self.dmr.state_repo
        session_id = "sess-resume"
        if repo.get_session(session_id) is None:
            repo.create_session(session_id, taskname, streamer_name="主播",
                                streamer_uid="1", platform="bilibili",
                                room_id="1", room_url="https://live.bilibili.com/1",
                                title="标题")
        path = os.path.join(self.tmpdir, "seg1.flv")
        with open(path, "wb") as handle:
            handle.write(b"\0" * int(size_mb * 1024 * 1024))
        key = make_artifact_key(session_id, ArtifactKind.SOURCE, 1)
        repo.upsert_artifact(
            key, session_id, 1, ArtifactKind.SOURCE, state,
            path=path, size=int(size_mb * 1024 * 1024), duration=600.0,
            video_info={"path": path, "title": "标题", "duration": 600.0,
                        "size": int(size_mb * 1024 * 1024),
                        "streamer": {"name": "主播"}, "segment_id": 1,
                        "group_id": session_id},
            **extra,
        )
        return repo.get_artifact(key), path

    def _prepare(self):
        """构造 dmr（不启动插件线程），并把状态库初始化好以便塞数据。"""
        from DMR import DanmakuRender

        config = self.make_config_with_upload()
        dmr = DanmakuRender.__new__(DanmakuRender)
        dmr.logger = __import__("logging").getLogger("DMR")
        dmr.config = config
        dmr.kwargs = {}
        dmr.stoped = True
        dmr.state_repo = None
        dmr.recovery_report = None
        dmr.recovery_manager = None
        dmr.engine_args = config.get_config("dmr_engine_args")
        dmr.state_db_path = dmr._resolve_state_db_path()
        dmr.engine = self._make_fake_engine()
        dmr._init_state()
        self.dmr = dmr
        self.addCleanup(dmr.stop)
        # 显式关掉状态库：Windows 下 TemporaryDirectory 删除被 sqlite 占用的
        # .db 文件会抛 NotADirectoryError（清理顺序不确定时尤其明显）
        self.addCleanup(self._close_state_repo, dmr)
        return dmr

    @staticmethod
    def _close_state_repo(dmr):
        repo, dmr.state_repo = dmr.state_repo, None
        if repo is not None:
            try:
                repo.close()
            except Exception:
                pass

    @staticmethod
    def _make_fake_engine():
        """只记录 pipeSend 的假引擎（避免起真实线程与插件）。"""
        import logging

        class FakeEngine:
            def __init__(self):
                self.logger = logging.getLogger("fake-engine")
                self.sent = []
                self.task_dict = {}
                self.stoped = True

            def pipeSend(self, message):
                self.sent.append(message)

            def stop(self):
                self.stoped = True

        return FakeEngine()

    def _attach_task(self, dmr, taskname="test"):
        """把一个真实的 LiveEvents 挂到假引擎的 task_dict 上。"""
        from DMR.Task.liveevents import LiveEvents

        replay_config = dmr.config.get_replay_config(taskname)
        events = LiveEvents(taskname, {**replay_config,
                                       "state_repo": dmr.state_repo})
        task_entry = {"class": type("T", (), {"event_class": events})()}
        dmr.engine.task_dict[taskname] = task_entry
        return events

    def test_recorded_artifact_is_redispatched_to_uploader(self):
        dmr = self._prepare()
        artifact, _ = self.seed_artifact()
        events = self._attach_task(dmr)

        dmr._resume_pending_artifacts()

        self.assertEqual(len(dmr.engine.sent), 1, "应派发一个上传任务")
        message = dmr.engine.sent[0]
        self.assertEqual(message.target, "uploader")
        self.assertEqual(message.data["files"][0].path, artifact.path)
        self.assertEqual(len(dmr.recovery_report.resumable), 1)
        # 注入的内存状态必须进入"上传中"，否则会重复派发
        self.assertEqual(events.state_dict["sess-resume"][0]["src_video"]["status"],
                         "uploading")
        self.assertEqual(
            dmr.state_repo.get_artifact(artifact.artifact_id).state.value,
            "uploading")

    def test_uploaded_artifact_is_not_redispatched(self):
        """已上传的产物绝不重跑 —— 否则会重复投稿。"""
        dmr = self._prepare()
        self.seed_artifact(state="uploaded")
        self._attach_task(dmr)

        dmr._resume_pending_artifacts()

        self.assertEqual(dmr.engine.sent, [])
        self.assertEqual(dmr.recovery_report.resumable, [])

    def test_resume_can_be_disabled_by_config(self):
        dmr = self._prepare()
        self.seed_artifact()
        self._attach_task(dmr)
        dmr.config.global_config["recovery"] = {"resume": False}

        dmr._resume_pending_artifacts()

        self.assertEqual(dmr.engine.sent, [])

    def test_artifact_of_unloaded_task_is_skipped(self):
        """产物属于未加载的任务时应跳过，而不是让启动失败。"""
        dmr = self._prepare()
        self.seed_artifact(taskname="ghost-task")

        dmr._resume_pending_artifacts()

        self.assertEqual(dmr.engine.sent, [])

    def test_resume_does_not_double_dispatch(self):
        """同一次运行内重复恢复不应把同一产物派发两次。

        第一次派发已把状态写成 ``uploading``，第二次收集时它不再是
        ``recorded``/``rendered``，因此不会被选中。

        注意**跨重启**的去重做不到：``uploading`` 会由启动对账净化回
        ``recorded``（因为不知道远端是否真的收下了），所以崩溃前已完成的投稿
        在重启后可能被重新上传一次。这是状态机固有的取舍，已在文档中说明。
        """
        dmr = self._prepare()
        self.seed_artifact()
        self._attach_task(dmr)

        dmr._resume_pending_artifacts()
        first_batch = len(dmr.engine.sent)
        dmr._resume_pending_artifacts()

        self.assertEqual(first_batch, 1)
        self.assertEqual(len(dmr.engine.sent), 1,
                         "同一个产物不应在同一次运行中被派发两次")

    def test_resume_increments_attempts_for_visibility(self):
        """重新派发应累加 ``attempts``，便于排查"反复重试同一个产物"。"""
        dmr = self._prepare()
        artifact, _ = self.seed_artifact()
        self._attach_task(dmr)

        dmr._resume_pending_artifacts()

        self.assertEqual(dmr.state_repo.get_artifact(artifact.artifact_id).attempts,
                         1)

    def test_no_state_repo_is_a_noop(self):
        dmr = self._prepare()
        dmr.state_repo = None

        dmr._resume_pending_artifacts()   # 不应抛异常


if __name__ == "__main__":
    unittest.main()
