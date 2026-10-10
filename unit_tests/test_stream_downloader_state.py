"""``DMR.Downloader.stream_downloader`` 状态登记的模块级测试（P1）。

覆盖录制侧的写入点：

- 开播时登记**场次**（含主播/房间元信息，供 `.part` 转正与恢复使用）
- 每个分段封闭后登记**产物**（视频 + 弹幕字幕文件）
- 下播/主动停止时标记场次结束，使对账能在全部产物终态后回收该场次

用例不联网：``LiveAPI`` 被替换为替身；``StreamDownloadTask`` 通过 ``__new__``
构造，绕过会在构造期请求网络的 ``__init__``。
"""
from __future__ import annotations

import os
import tempfile
import unittest
from types import SimpleNamespace

from DMR.state import ArtifactKind, ArtifactState, StateRepository
from unit_tests.support import DMRTestCase

MB = 1024 * 1024


class _FakeLiveAPI:
    """``LiveAPI`` 替身：房间信息可配置，不发起任何请求。"""

    def __init__(self, room_info=None):
        self._room_info = room_info or {'title': '测试标题'}
        self.calls = []

    def GetRoomInfo(self):
        self.calls.append('GetRoomInfo')
        return self._room_info


class _TaskTestCase(DMRTestCase):
    """共享：内存状态库 + 绕过构造函数的 StreamDownloadTask。"""

    def setUp(self) -> None:
        super().setUp()
        self.repo = StateRepository(":memory:").open()
        self.addCleanup(self.repo.close)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmpdir = self._tmp.name

    def make_task(self, *, state_repo="auto", taskname="mytask", sess_id="sess-1",
                  streamer=None, room_info=None, output_name=None,
                  advanced_video_args=None):
        from DMR.Downloader.stream_downloader import StreamDownloadTask

        task = StreamDownloadTask.__new__(StreamDownloadTask)
        task.taskname = taskname
        task.url = 'https://live.bilibili.com/123'
        task.plat, task.rid = 'bilibili', '123'
        task.output_dir = self.tmpdir
        task.output_format = 'flv'
        task.output_name = output_name or '{STREAMER.NAME}-{CTIME.YEAR}年{CTIME.MONTH:02d}月'
        task.send_queue = None
        task.logger = __import__('logging').getLogger('test')
        task.kwargs = {}
        task.debug = False
        task.state_repo = self.repo if state_repo == "auto" else state_repo
        task.advanced_video_args = advanced_video_args or {}
        task.danmaku = True
        task.video = True
        task.engine = 'ffmpeg'
        task.stream_option = {}
        task.room_info = room_info or {'title': '测试标题'}
        task.streamer_info = streamer if streamer is not None else SimpleNamespace(
            name='测试主播', uid='999')
        task.liveapi = _FakeLiveAPI(room_info)
        task.sess_id = sess_id
        task.segment_id = 1
        # segment_callback 会用 segment_start_time 计算时长，必须是个 datetime
        task.segment_start_time = __import__('datetime').datetime.now()
        task.width, task.height = 1920, 1080
        task.stoped = False
        return task

    def write(self, name, size_mb=10.0):
        path = os.path.join(self.tmpdir, name)
        with open(path, 'wb') as handle:
            handle.write(b'\0' * int(size_mb * MB))
        return path

    @staticmethod
    def make_video_info(path, *, segment_id=1, duration=600.0, size=10 * MB,
                        dm_file_id=None, resolution=(1920, 1080)):
        return SimpleNamespace(
            path=path, segment_id=segment_id, duration=duration, size=size,
            dm_file_id=dm_file_id, resolution=resolution,
        )


class TestRegisterSession(_TaskTestCase):
    """``_register_session``：把主播/房间元信息落库。"""

    def test_session_is_registered_with_metadata(self):
        task = self.make_task()

        task._register_session()

        session = self.repo.get_session('sess-1')
        self.assertIsNotNone(session)
        self.assertEqual(session.taskname, 'mytask')
        self.assertEqual(session.platform, 'bilibili')
        self.assertEqual(session.room_id, '123')
        self.assertEqual(session.room_url, 'https://live.bilibili.com/123')
        self.assertEqual(session.streamer_name, '测试主播')
        self.assertEqual(session.streamer_uid, '999')
        self.assertEqual(session.title, '测试标题')
        self.assertFalse(session.is_ended)

    def test_missing_streamer_info_is_tolerated(self):
        """拿不到主播信息时仍应登记场次，只是元信息为空。"""
        task = self.make_task(streamer=None, room_info={})
        task.streamer_info = None

        task._register_session()

        session = self.repo.get_session('sess-1')
        self.assertIsNotNone(session)
        self.assertIsNone(session.streamer_name)

    def test_without_state_repo_is_a_noop(self):
        task = self.make_task(state_repo=None)

        task._register_session()

        self.assertEqual(self.repo.list_sessions(), [])

    def test_repository_error_does_not_propagate(self):
        """状态登记失败不得影响录制。"""
        task = self.make_task()

        class Broken:
            def create_session(self, *a, **kw):
                raise RuntimeError('db locked')

        task.state_repo = Broken()

        task._register_session()   # 不应抛异常


class TestRecordSegment(_TaskTestCase):
    """``_record_segment``：登记已完成的分段。"""

    def test_video_artifact_is_registered(self):
        task = self.make_task()
        task._register_session()
        path = self.write('seg1.flv')

        task._record_segment(self.make_video_info(path, segment_id=1))

        artifact = self.repo.get_artifact('sess-1:src_video:1')
        self.assertIsNotNone(artifact)
        self.assertEqual(artifact.kind, ArtifactKind.SOURCE)
        self.assertEqual(artifact.state, ArtifactState.RECORDED)
        self.assertEqual(artifact.path, path)
        self.assertEqual(artifact.size, 10 * MB)
        self.assertEqual(artifact.duration, 600.0)
        self.assertEqual(artifact.resolution, (1920, 1080))

    def test_danmaku_file_is_recorded_as_attachment(self):
        """``.ass`` 是视频的**附属物**，应记在视频产物行上，而不是独立产物。

        理由：单独的弹幕文件没有意义（无法独立上传/清理）；且此刻它的最终文件名
        还没确定 —— `.ass` 是在下一个分段开始时才由 ``dmw.split()`` 改名。
        """
        task = self.make_task()
        task._register_session()
        path = self.write('seg1.flv')
        ass = self.write('seg1.ass', size_mb=0.01)

        task._record_segment(self.make_video_info(path, dm_file_id=ass))

        artifact = self.repo.get_artifact('sess-1:src_video:1')
        self.assertEqual(artifact.danmaku_path, ass, "弹幕文件应作为附属字段记录")
        # 不应产生独立的弹幕产物行
        self.assertEqual(len(self.repo.list_artifacts(session_id='sess-1')), 1)

    def test_no_danmaku_attachment_when_absent(self):
        task = self.make_task()
        task._register_session()

        task._record_segment(self.make_video_info(self.write('seg1.flv')))

        self.assertIsNone(self.repo.get_artifact('sess-1:src_video:1').danmaku_path)

    def test_attached_danmaku_survives_reconcile(self):
        """弹幕作为附属物不应被对账当作"缺失的产物"处理。"""
        from DMR.state import RecoveryConfig, RecoveryManager

        task = self.make_task()
        task._register_session()
        ass = self.write('seg1.ass', size_mb=0.01)
        task._record_segment(
            self.make_video_info(self.write('seg1.flv'), dm_file_id=ass))

        report = RecoveryManager(self.repo, RecoveryConfig(),
                                 now=lambda: int(__import__('time').time())).reconcile()

        self.assertEqual(report.missing, [])
        self.assertEqual(self.repo.get_artifact('sess-1:src_video:1').danmaku_path, ass)

    def test_rerecording_same_segment_is_idempotent(self):
        """同一分段重复登记应更新而非产生重复行。"""
        task = self.make_task()
        task._register_session()
        path = self.write('seg1.flv')

        task._record_segment(self.make_video_info(path, size=1 * MB))
        task._record_segment(self.make_video_info(path, size=2 * MB))

        artifacts = self.repo.list_artifacts(session_id='sess-1')
        self.assertEqual(len(artifacts), 1)
        self.assertEqual(artifacts[0].size, 2 * MB)

    def test_session_updated_at_is_refreshed(self):
        """登记分段应刷新场次活跃时间，避免被过期回收误判。"""
        task = self.make_task()
        task._register_session()
        self.repo.conn.execute(
            "UPDATE sessions SET updated_at=updated_at-10000 WHERE session_id='sess-1'")
        self.repo.conn.commit()
        stale = self.repo.get_session('sess-1').updated_at

        task._record_segment(self.make_video_info(self.write('seg1.flv')))

        self.assertGreater(self.repo.get_session('sess-1').updated_at, stale)

    def test_without_state_repo_is_a_noop(self):
        task = self.make_task(state_repo=None)

        task._record_segment(self.make_video_info(self.write('seg1.flv')))

        self.assertEqual(self.repo.list_artifacts(), [])

    def test_repository_error_does_not_propagate(self):
        task = self.make_task()

        class Broken:
            def upsert_artifact(self, *a, **kw):
                raise RuntimeError('disk full')

        task.state_repo = Broken()

        task._record_segment(self.make_video_info(self.write('seg1.flv')))


class TestLiveEnd(_TaskTestCase):
    """``_on_live_end``：标记场次结束。"""

    def test_session_is_marked_ended(self):
        task = self.make_task()
        task._register_session()

        task._on_live_end()

        self.assertTrue(self.repo.get_session('sess-1').is_ended)

    def test_without_state_repo_is_a_noop(self):
        task = self.make_task(state_repo=None)
        task._on_live_end()   # 不应抛异常


class TestSegmentCallbackRegisters(_TaskTestCase):
    """端到端：走真实的 ``segment_callback`` 全流程，产物应落库且能通过对账。"""

    def _run_callback(self, task, filename, *, expect_danmaku=True):
        """执行 ``segment_callback``，把外部探测/改名替换为桩。"""
        from DMR.Downloader import stream_downloader as sd
        from DMR.utils import FFprobe

        class _FakeDmw:
            """弹幕写入器替身：分段时只记录目标文件名。"""

            def __init__(self):
                self.split_targets = []

            def split(self, filename=None):
                self.split_targets.append(filename)

        if task.danmaku and not hasattr(task, 'dmw'):
            task.dmw = _FakeDmw()

        original = (sd.rename_safe, FFprobe.get_duration)
        sd.rename_safe = lambda src, dst, retry=10: src
        FFprobe.get_duration = lambda path: 600.0
        try:
            task.segment_callback(filename)
        finally:
            sd.rename_safe, FFprobe.get_duration = original

    def test_completed_segment_is_registered(self):
        task = self.make_task(output_name='{STREAMER.NAME}-seg')
        task._register_session()
        rawname = self.write('[正在录制]mytask-Part001.flv')

        self._run_callback(task, rawname)

        artifact = self.repo.get_artifact('sess-1:src_video:1')
        self.assertIsNotNone(artifact, "分段完成后应登记产物")
        self.assertEqual(artifact.state, ArtifactState.RECORDED)
        self.assertTrue(os.path.exists(artifact.path))
        self.assertEqual(task.segment_id, 2, "segment_id 应递增")

    def test_registered_segment_survives_reconcile(self):
        """登记后重跑对账：文件存在则状态保持 RECORDED（不会被误判丢失）。"""
        from DMR.state import RecoveryConfig, RecoveryManager

        task = self.make_task(output_name='{STREAMER.NAME}-seg')
        task._register_session()
        rawname = self.write('[正在录制]mytask-Part001.flv')
        self._run_callback(task, rawname)

        report = RecoveryManager(self.repo, RecoveryConfig(),
                                 now=lambda: int(__import__('time').time())).reconcile()

        artifact = self.repo.get_artifact('sess-1:src_video:1')
        self.assertEqual(artifact.state, ArtifactState.RECORDED)
        self.assertEqual(report.missing, [], "文件存在时不应被判为丢失")

    def test_deleted_file_is_detected_by_reconcile(self):
        """产物文件被外部删除时，对账应把它标记为 MISSING。"""
        from DMR.state import RecoveryConfig, RecoveryManager

        task = self.make_task(output_name='{STREAMER.NAME}-seg')
        task._register_session()
        rawname = self.write('[正在录制]mytask-Part001.flv')
        self._run_callback(task, rawname)
        artifact = self.repo.get_artifact('sess-1:src_video:1')
        os.remove(artifact.path)

        report = RecoveryManager(self.repo, RecoveryConfig(),
                                 now=lambda: int(__import__('time').time())).reconcile()

        self.assertEqual(self.repo.get_artifact('sess-1:src_video:1').state,
                         ArtifactState.MISSING)
        self.assertEqual(len(report.missing), 1)

    def test_live_end_then_reconcile_cleans_up(self):
        """下播且产物全部终态后，对账应回收场次及其产物。"""
        from DMR.state import RecoveryConfig, RecoveryManager

        task = self.make_task(output_name='{STREAMER.NAME}-seg')
        task._register_session()
        self._run_callback(task, self.write('[正在录制]mytask-Part001.flv'))
        # 把所有产物推进到终态（视频已上传、弹幕文件已处理）
        for artifact in self.repo.list_artifacts(terminal=False):
            self.repo.set_artifact_state(artifact.artifact_id, ArtifactState.UPLOADED)
        task._on_live_end()

        report = RecoveryManager(self.repo, RecoveryConfig(),
                                 now=lambda: int(__import__('time').time())).reconcile()

        self.assertIsNone(self.repo.get_session('sess-1'), "场次应被回收")
        self.assertEqual(len(report.sessions_cleaned), 1)

    def test_live_end_with_pending_artifact_keeps_session(self):
        """仍有非终态产物时，下播也不应回收场次。"""
        from DMR.state import RecoveryConfig, RecoveryManager

        task = self.make_task(output_name='{STREAMER.NAME}-seg')
        task._register_session()
        self._run_callback(task, self.write('[正在录制]mytask-Part001.flv'))
        task._on_live_end()

        RecoveryManager(self.repo, RecoveryConfig(),
                        now=lambda: int(__import__('time').time())).reconcile()

        self.assertIsNotNone(self.repo.get_session('sess-1'),
                             "有未处理产物时场次必须保留")

    def test_completed_segment_and_inprogress_are_distinct(self):
        """端到端：分段 1 完成、分段 2 进行中 → 两条记录状态互不干扰。"""
        task = self.make_task(output_name='{STREAMER.NAME}-seg')
        task._register_session()
        self._run_callback(task, self.write('[正在录制]mytask-Part001.flv'))
        # 引擎随即开始写分段 2
        task.inprogress_callback(self.write('[正在录制]mytask-Part002.flv', size_mb=3))

        first = self.repo.get_artifact('sess-1:src_video:1')
        second = self.repo.get_artifact('sess-1:src_video:2')
        self.assertEqual(first.state, ArtifactState.RECORDED)
        self.assertIsNone(first.part_path, "已完成产物不应保留 part_path")
        self.assertEqual(second.state, ArtifactState.RECORDING)


class TestInProgressDetection(_TaskTestCase):
    """进行中文件的登记：录制中途被强杀后，残file必须能被对账发现并按策略处置。

    信号由**引擎**提供（``inprogress_callback``）而不是扫目录：扫目录无法区分
    "刚封闭、尚未改名的分段"与"正在写入的下一个分段"。
    """

    def _reconcile(self):
        from DMR.state import RecoveryConfig, RecoveryManager

        return RecoveryManager(self.repo, RecoveryConfig(),
                               now=lambda: int(__import__('time').time())).reconcile()

    def test_inprogress_file_is_registered_as_recording(self):
        task = self.make_task(output_name='{STREAMER.NAME}-seg')
        task._register_session()
        writing = self.write('[正在录制]mytask-20260101-Part002.flv', size_mb=5)

        task.inprogress_callback(writing)

        artifact = self.repo.get_artifact('sess-1:src_video:1')
        self.assertIsNotNone(artifact, "进行中的文件必须被登记")
        self.assertEqual(artifact.state, ArtifactState.RECORDING)
        self.assertEqual(artifact.part_path, writing)

    def test_repeated_reports_get_increasing_indices(self):
        """引擎每次开始写新文件都应产生一条新记录，不覆盖上一条。

        序号与 ``segment_id`` 同源：真实流程中，引擎封闭分段 N 后会推进
        ``segment_id``，再开始写分段 N+1。
        """
        task = self.make_task()
        task._register_session()

        task.inprogress_callback(self.write('[正在录制]mytask-Part001.flv', size_mb=2))
        task.segment_id = 2          # 分段 1 已封闭，引擎开始写分段 2
        task.inprogress_callback(self.write('[正在录制]mytask-Part002.flv', size_mb=2))

        first = self.repo.get_artifact('sess-1:src_video:1')
        second = self.repo.get_artifact('sess-1:src_video:2')
        self.assertEqual(first.state, ArtifactState.RECORDING)
        self.assertEqual(second.state, ArtifactState.RECORDING)
        self.assertIn('Part001', first.part_path)
        self.assertIn('Part002', second.part_path)

    def test_inprogress_does_not_overwrite_completed_segment(self):
        """进行中记录绝不能覆盖已完成记录 —— 序号必须与 segment_id 同源。"""
        task = self.make_task(output_name='{STREAMER.NAME}-seg')
        task._register_session()
        # 分段 1 完成（segment_callback 内部会把 segment_id 推进到 2）
        first = self.repo.get_artifact('sess-1:src_video:1')

        class _Dmw:
            def split(self, filename=None):
                pass

        task.dmw = _Dmw()
        self._run_callback_standalone(task, self.write('[正在录制]mytask-Part001.flv'))
        # 引擎开始写分段 2
        task.inprogress_callback(self.write('[正在录制]mytask-Part002.flv', size_mb=2))

        self.assertEqual(self.repo.get_artifact('sess-1:src_video:1').state,
                         ArtifactState.RECORDED,
                         "已完成的第 1 段不应被进行中记录覆盖")
        self.assertEqual(self.repo.get_artifact('sess-1:src_video:2').state,
                         ArtifactState.RECORDING)

    @staticmethod
    def _run_callback_standalone(task, filename):
        """执行 ``segment_callback``，替换掉外部探测/改名。"""
        from DMR.Downloader import stream_downloader as sd
        from DMR.utils import FFprobe

        original = (sd.rename_safe, FFprobe.get_duration)
        sd.rename_safe = lambda src, dst, retry=10: src
        FFprobe.get_duration = lambda path: 600.0
        try:
            task.segment_callback(filename)
        finally:
            sd.rename_safe, FFprobe.get_duration = original

    def test_inprogress_file_is_interrupted_after_restart(self):
        """重启后：RECORDING → INTERRUPTED，且文件仍被识别为可处置。"""
        task = self.make_task(output_name='{STREAMER.NAME}-seg')
        task._register_session()
        writing = self.write('[正在录制]mytask-20260101-Part002.flv', size_mb=5)
        task.inprogress_callback(writing)

        report = self._reconcile()

        artifact = self.repo.get_artifact('sess-1:src_video:1')
        self.assertEqual(artifact.state, ArtifactState.INTERRUPTED)
        self.assertEqual(len(report.unstable), 1)
        self.assertEqual(report.needs_attention, 1, "ask 策略下应报告待处置")

    def test_interrupted_file_can_be_promoted_with_keep(self):
        """keep 策略：校验通过的中断文件应转为可用的 RECORDED 产物。"""
        from DMR.state import RecoveryConfig, RecoveryManager

        task = self.make_task(output_name='{STREAMER.NAME}-seg')
        task._register_session()
        writing = self.write('[正在录制]mytask-20260101-Part002.flv', size_mb=5)
        task.inprogress_callback(writing)

        report = RecoveryManager(
            self.repo,
            RecoveryConfig(on_interrupted_file='keep', min_valid_size_mb=1),
            probe=lambda path: 600.0,
            now=lambda: int(__import__('time').time()),
        ).reconcile()

        artifact = self.repo.get_artifact('sess-1:src_video:1')
        self.assertEqual(artifact.state, ArtifactState.RECORDED)
        self.assertTrue(os.path.exists(writing))
        self.assertEqual([a.reason for a in report.interrupted], ['promoted'])

    def test_interrupted_file_is_deleted_with_discard(self):
        """discard 策略：真正的 `.part` 文件应被删除（= 从 0 开始）。

        注意：这里刻意用**独立的 .part 路径**。若 ``part_path == path``（引擎直接写
        最终名），文件其实已在正式路径上，语义是"已录完但状态没落库"，会直接恢复为
        ``recorded`` 而**不受** discard 影响 —— 见
        ``test_state_reconciler.TestInterruptedFileShapes``。
        """
        from DMR.state import RecoveryConfig, RecoveryManager

        task = self.make_task(output_name='{STREAMER.NAME}-seg')
        task._register_session()
        part = self.write('writing.flv.part', size_mb=5)
        task.inprogress_callback(part)
        # 模拟引擎"还没改名到正式路径"的状态
        self.repo.set_artifact_path('sess-1:src_video:1',
                                    path=os.path.join(self.tmpdir, 'seg.flv'),
                                    part_path=part)

        RecoveryManager(
            self.repo,
            RecoveryConfig(on_interrupted_file='discard',
                           min_valid_size_mb=1),
            probe=lambda path: 600.0,
            now=lambda: int(__import__('time').time()),
        ).reconcile()

        self.assertEqual(self.repo.get_artifact('sess-1:src_video:1').state,
                         ArtifactState.SKIPPED)
        self.assertFalse(os.path.exists(part), "discard 应删除残file")

    def test_unrenamed_file_is_recovered_not_discarded(self):
        """引擎直接写最终名时，文件就是正式文件 → 直接恢复，不受 discard 影响。"""
        from DMR.state import RecoveryConfig, RecoveryManager

        task = self.make_task(output_name='{STREAMER.NAME}-seg')
        task._register_session()
        writing = self.write('writing.flv', size_mb=5)   # part_path == path
        task.inprogress_callback(writing)

        RecoveryManager(
            self.repo,
            RecoveryConfig(on_interrupted_file='discard',
                           min_valid_size_mb=1),
            probe=lambda path: 600.0,
            now=lambda: int(__import__('time').time()),
        ).reconcile()

        self.assertEqual(self.repo.get_artifact('sess-1:src_video:1').state,
                         ArtifactState.RECORDED, "已录完的文件不应被当作残file丢弃")
        self.assertTrue(os.path.exists(writing))

    def test_invalid_interrupted_file_is_never_promoted(self):
        """校验不通过时，即便策略是 keep 也不能转正。"""
        from DMR.state import RecoveryConfig, RecoveryManager

        task = self.make_task(output_name='{STREAMER.NAME}-seg')
        task._register_session()
        writing = self.write('[正在录制]mytask-20260101-Part002.flv', size_mb=0.01)
        task.inprogress_callback(writing)

        RecoveryManager(
            self.repo,
            RecoveryConfig(on_interrupted_file='keep', min_valid_size_mb=1),
            probe=lambda path: 600.0,
            now=lambda: int(__import__('time').time()),
        ).reconcile()

        artifact = self.repo.get_artifact('sess-1:src_video:1')
        self.assertEqual(artifact.state, ArtifactState.INTERRUPTED)
        self.assertIn("校验未通过", artifact.last_error)

    def test_without_state_repo_is_a_noop(self):
        task = self.make_task(state_repo=None)
        task.inprogress_callback(self.write('writing.flv', size_mb=2))   # 不应抛异常


class TestStateRepoInjection(DMRTestCase):
    """模块级注入接口（供 ``DanmakuRender`` 使用）。"""

    def test_set_state_repo_affects_new_tasks(self):
        from DMR.Downloader import stream_downloader as sd

        original = sd._STATE_REPO
        self.addCleanup(lambda: setattr(sd, '_STATE_REPO', original))
        repo = StateRepository(":memory:").open()
        self.addCleanup(repo.close)

        sd.set_state_repo(repo)

        self.assertIs(sd._STATE_REPO, repo)

    def test_explicit_argument_overrides_module_reference(self):
        from DMR.Downloader import stream_downloader as sd

        original = sd._STATE_REPO
        self.addCleanup(lambda: setattr(sd, '_STATE_REPO', original))
        module_repo = StateRepository(":memory:").open()
        explicit_repo = StateRepository(":memory:").open()
        self.addCleanup(module_repo.close)
        self.addCleanup(explicit_repo.close)
        sd.set_state_repo(module_repo)

        task = StreamDownloadTaskStub(explicit_repo)

        self.assertIs(task.state_repo, explicit_repo)


class StreamDownloadTaskStub:
    """最小化地走 ``StreamDownloadTask.__init__`` 中的 state_repo 赋值逻辑。

    直接调用真实 ``__init__`` 会请求网络（``LiveAPI``），因此这里只验证
    "显式参数优先于模块级引用" 这条赋值规则，与真实构造函数中的写法一致。
    """

    def __init__(self, state_repo=None):
        from DMR.Downloader.stream_downloader import _STATE_REPO

        self.state_repo = state_repo if state_repo is not None else _STATE_REPO


class _FakeDmw:
    """``DanmakuDownloader`` 替身，复刻真实的弹幕文件命名协议。

    真实实现（``DMR/Downloader/Danmaku/danmaku.py``）的语义是：

    - ``dm_file`` 是"当前正在写入"的弹幕文件（``[正在录制]...Part%03d.ass``）；
    - ``split(final)`` 先把当前分段切到下一个 ``Part%03d``，再把**刚才那一段**的
      弹幕文件改名为 ``final``（该段视频的同名 ``.ass``）；
    - 返回**实际落盘**的路径：改名成功即 ``final``，失败则回退为未改名的原路径。

    ``rename_ok=False`` 用于模拟改名失败（例如目标名已存在 —— Windows 上
    ``os.rename`` 不覆盖，实测会抛 ``FileExistsError``）。
    """

    def __init__(self, tmpdir, name='mytask', rename_ok=True):
        self.tmpdir = tmpdir
        self.name = name
        self.rename_ok = rename_ok
        self.part = 1
        self.files = []          # 依次建立过的弹幕文件

    def current_file(self):
        """当前正在写入的弹幕文件（即"该段自己"那个）。"""
        return self.files[-1] if self.files else None

    def next_file(self):
        """已经为**下一段**新建的弹幕文件路径（``split()`` 的副作用产物）。"""
        return os.path.join(self.tmpdir, f'[正在录制]{self.name}-Part{self.part:03d}.ass')

    def _new_file(self):
        path = os.path.join(self.tmpdir, f'[正在录制]{self.name}-Part{self.part:03d}.ass')
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write(f'P{self.part} danmaku\n')
        self.files.append(path)
        return path

    def split(self, filename=None):
        old = self.current_file()
        self.part += 1
        self._new_file()                       # 先为下一段新建
        if not filename:
            return old
        if not self.rename_ok:
            return old                         # 改名失败 → 回退为原名
        os.rename(old, filename)               # 再把当前段改名
        self.files[self.files.index(old)] = filename
        return filename


class TestDanmakuPairingWithSegment(_TaskTestCase):
    """端到端：``segment_callback`` 登记的弹幕文件必须与**该段自己**配对。

    这组用例锁定一个曾经被注释误述为"错位、不修"的行为。实测（真实
    ``AssWriter`` + 真实 ``segment_callback``）证明分段与弹幕文件是配对的：

        video-P1.mp4 ↔ video-P1.ass（含第 1 段弹幕）
        video-P2.mp4 ↔ video-P2.ass（含第 2 段弹幕）

    因此这里的断言是"**该段自己的** .ass"，而不是"下一段新建的那个"。
    """

    def _patch_rename(self):
        """替换外部依赖：``rename_safe`` 用真实改名；``FFprobe`` 不真的探测。"""
        from DMR.Downloader import stream_downloader as sd
        from DMR.utils import FFprobe

        def real_rename(src, dst, retry=10):
            if not os.path.exists(src) or os.path.exists(dst):
                return None
            os.rename(src, dst)
            return dst

        original_rename, original_duration = sd.rename_safe, FFprobe.get_duration
        self.addCleanup(setattr, sd, 'rename_safe', original_rename)
        self.addCleanup(setattr, FFprobe, 'get_duration', original_duration)
        sd.rename_safe = real_rename
        FFprobe.get_duration = lambda path: 600.0

    def _make_task_with_dmw(self, rename_ok=True, advanced_video_args=None):
        task = self.make_task(output_name='rec-seg')
        if advanced_video_args:
            task.advanced_video_args = advanced_video_args
        task._register_session()
        # 先建好"第 1 段正在写入"的弹幕文件，再交给替身
        old_ass = os.path.join(self.tmpdir, '[正在录制]mytask-Part001.ass')
        with open(old_ass, 'w', encoding='utf-8') as handle:
            handle.write('P1 danmaku\n')
        task.dmw = _FakeDmw(self.tmpdir, rename_ok=rename_ok)
        task.dmw.files = [old_ass]
        self._patch_rename()
        return task, old_ass

    def test_danmaku_path_matches_its_own_segment(self):
        """正常路径：登记的 ``danmaku_path`` == 该段视频的同名 ``.ass``。"""
        task, _ = self._make_task_with_dmw()

        raw = self.write('[正在录制]mytask-Part001.flv')
        task.segment_callback(raw)

        artifact = self.repo.get_artifact('sess-1:src_video:1')
        self.assertIsNotNone(artifact)
        expected_ass = os.path.splitext(artifact.path)[0] + '.ass'

        self.assertTrue(os.path.exists(expected_ass), f'该段弹幕应存在: {expected_ass}')
        self.assertEqual(artifact.danmaku_path, expected_ass,
                         '登记的弹幕文件必须是该段自己的 .ass')
        # 反例保护：不能是"为下一段新建"的那个 Part002 文件
        self.assertNotIn('Part002', artifact.danmaku_path or '')

    def test_danmaku_path_falls_back_when_rename_fails(self):
        """改名失败：登记的必须是**真实存在**的回退路径，而不是一个不存在的名字。

        缺陷形态：``split()`` 改名失败只记日志，而 ``segment_callback`` 无条件把
        计算出来的 ``newdmfile`` 记为 ``dm_file_id`` → 该路径不存在（或指向别的
        分段的文件），渲染与对账都会出错，真弹幕文件留在 ``[正在录制]`` 名下变孤儿。
        """
        task, old_ass = self._make_task_with_dmw(rename_ok=False)

        raw = self.write('[正在录制]mytask-Part001.flv')
        task.segment_callback(raw)

        artifact = self.repo.get_artifact('sess-1:src_video:1')
        self.assertIsNotNone(artifact)

        computed = os.path.splitext(artifact.path)[0] + '.ass'
        self.assertFalse(os.path.exists(computed),
                         '本用例前提：改名失败，计算出来的名字不存在')
        self.assertEqual(artifact.danmaku_path, old_ass,
                         '改名失败时应回退登记真实存在的原文件')
        self.assertTrue(os.path.exists(artifact.danmaku_path),
                        '登记进状态库的弹幕路径必须真实存在')

    def test_too_small_segment_deletes_its_own_danmaku(self):
        """过小分段被丢弃时，删掉的必须是**该段自己**的弹幕文件。

        场景：改名失败（该段弹幕留在 ``Part001`` 原名下），同时替身已按真实
        ``split()`` 的行为为**下一段**建好了 ``Part002`` 文件。

        旧实现用计算出来的 ``newdmfile``（== ``rec-seg.ass``，一个碰巧存在的
        占位文件）去删，结果：误删占位文件、真弹幕留在 ``Part001`` 变孤儿。
        新实现删 ``Part001``（该段自己的），且**不碰** ``Part002``（下一段的）。
        """
        task, old_ass = self._make_task_with_dmw(
            rename_ok=False, advanced_video_args={'min_video_size': 100})

        raw = self.write('[正在录制]mytask-Part001.flv', size_mb=1.0)
        task.segment_callback(raw)

        # ⚠️ 必须在回调**之后**读 next_file()：part 计数是在 split() 内部推进的
        next_ass = task.dmw.next_file()      # Part002：下一段的文件
        self.assertEqual(next_ass, task.dmw.current_file())
        self.assertTrue(os.path.exists(next_ass),
                        '下一段的弹幕文件不得被本段误删')
        self.assertFalse(os.path.exists(old_ass),
                         '该段自己的弹幕文件应被删除')
        self.assertIsNone(self.repo.get_artifact('sess-1:src_video:1'),
                          '过小分段不应登记产物')


if __name__ == "__main__":
    unittest.main()
