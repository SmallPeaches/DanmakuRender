"""``DMR.Uploader`` 稿件归属持久化的模块级测试（P1）。

验证"同一 upload_group 重启后仍进同一稿件"这条链路的上半段：

- 新建上传器实例时，从状态库取回该组的 ``remote_id``（bvid）并注入引擎；
- 引擎自报的 bvid 会被回写到状态库；
- 状态库不可用/未打开时不得影响上传本身。

真实上传引擎需要登录与网络，因此这些用例通过可注入的 ``uploader_factory`` 替换。
"""
from __future__ import annotations

import queue
import unittest

from DMR.state import StateRepository
from unit_tests.support import DMRTestCase


class _StubUploader:
    """上传引擎替身：只记录收到的参数，并能自报一个 bvid。"""

    def __init__(self, bvid=None):
        self.args = {}
        self.bvid = bvid
        self.upload_calls = []

    def upload(self, files=None, stream_queue=None, **kwargs):
        self.upload_calls.append((files, stream_queue, kwargs))
        return True, 'uploaded'

    def get_remote_bvid(self):
        return self.bvid

    def stop(self):
        pass


class _UploaderTestCase(DMRTestCase):
    """共享：内存状态库 + 可注入工厂。"""

    def setUp(self) -> None:
        super().setUp()
        self.repo = StateRepository(":memory:").open()
        self.addCleanup(self.repo.close)
        self.created: list = []

    def make_uploader(self, *, state_repo="auto"):
        """构造被测 Uploader；``state_repo=None`` 表示不带状态库。"""
        from DMR.Uploader import Uploader

        repo = self.repo if state_repo == "auto" else state_repo

        def factory(engine, args):
            stub = _StubUploader(bvid=args.get('_stub_bvid'))
            stub.args = dict(args)
            self.created.append(stub)
            return stub

        send_queue: queue.Queue = queue.Queue()
        recv_queue: queue.Queue = queue.Queue()
        return Uploader((send_queue, recv_queue), nuploaders=1,
                        state_repo=repo, uploader_factory=factory)

    @staticmethod
    def make_task(upload_group='g1', engine='biliwebapi', taskname='mytask',
                  args=None):
        from types import SimpleNamespace

        return {
            'upload_group': upload_group,
            'engine': engine,
            'taskname': taskname,
            'args': args if args is not None else {
                'engine': engine, 'account': 'main', 'retry': 0,
            },
            'files': [SimpleNamespace(path='seg1.flv', title='t')],
            'stream_queue': None,
        }


class TestResumeInjection(_UploaderTestCase):
    """新建实例时应把库中记录的 bvid 注入给引擎。"""

    def test_remote_id_is_injected(self):
        self.repo.get_or_create_upload_group('g1', taskname='mytask',
                                            target='biliwebapi')
        self.repo.set_upload_group_remote('g1', 'BV_OLD')
        uploader = self.make_uploader()

        target = uploader._get_or_create_uploader(self.make_task('g1'))

        self.assertEqual(target.args.get('resume_bvid'), 'BV_OLD',
                         "应把既有 bvid 注入引擎以复用稿件")

    def test_no_remote_id_means_no_resume(self):
        self.repo.get_or_create_upload_group('g1', taskname='mytask',
                                            target='biliwebapi')
        uploader = self.make_uploader()

        target = uploader._get_or_create_uploader(self.make_task('g1'))

        self.assertNotIn('resume_bvid', target.args)

    def test_unknown_group_means_no_resume(self):
        """库里没有这个组时不应注入，也不应报错。"""
        uploader = self.make_uploader()

        target = uploader._get_or_create_uploader(self.make_task('never-seen'))

        self.assertNotIn('resume_bvid', target.args)

    def test_engine_without_resume_support_is_skipped(self):
        """不支持续传的引擎不应收到 resume_bvid 参数（否则会 TypeError）。

        ``youtubev3`` / ``subprocess`` 没有"追加到既有稿件"的概念。
        """
        self.repo.get_or_create_upload_group('g1', taskname='mytask',
                                            target='youtubev3')
        self.repo.set_upload_group_remote('g1', 'BV_OLD')
        uploader = self.make_uploader()

        target = uploader._get_or_create_uploader(
            self.make_task('g1', engine='youtubev3'))

        self.assertNotIn('resume_bvid', target.args)

    def test_biliuprs_also_receives_resume_bvid(self):
        """``biliuprs`` 同样支持追加（biliup append --vid），应收到 resume_bvid。"""
        self.repo.get_or_create_upload_group('g1', taskname='mytask',
                                            target='biliuprs')
        self.repo.set_upload_group_remote('g1', 'BV_OLD')
        uploader = self.make_uploader()

        target = uploader._get_or_create_uploader(
            self.make_task('g1', engine='biliuprs'))

        self.assertEqual(target.args.get('resume_bvid'), 'BV_OLD')

    def test_without_state_repo_nothing_is_injected(self):
        """没有状态库时（初始化失败降级）应静默跳过，不影响上传。"""
        uploader = self.make_uploader(state_repo=None)

        target = uploader._get_or_create_uploader(self.make_task('g1'))

        self.assertNotIn('resume_bvid', target.args)

    def test_pool_reuses_instance_within_process(self):
        """同一进程内应复用实例，不重复注入/登录。"""
        self.repo.get_or_create_upload_group('g1', taskname='mytask',
                                            target='biliwebapi')
        uploader = self.make_uploader()

        first = uploader._get_or_create_uploader(self.make_task('g1'))
        second = uploader._get_or_create_uploader(self.make_task('g1'))

        self.assertIs(first, second)
        self.assertEqual(len(self.created), 1)


class TestPersistRemoteId(_UploaderTestCase):
    """上传成功后应把引擎自报的 bvid 回写到状态库。"""

    def test_new_bvid_is_written_back(self):
        uploader = self.make_uploader()
        task = self.make_task('g1')
        target = _StubUploader(bvid='BV_NEW')

        uploader._persist_upload_group(task, target)

        group = self.repo.get_upload_group('g1')
        self.assertIsNotNone(group, "应自动建立上传组记录")
        self.assertEqual(group.remote_id, 'BV_NEW')
        self.assertEqual(group.taskname, 'mytask')
        self.assertEqual(group.account, 'main')

    def test_unchanged_bvid_does_not_rewrite(self):
        self.repo.get_or_create_upload_group('g1', taskname='mytask',
                                            target='biliwebapi')
        self.repo.set_upload_group_remote('g1', 'BV_SAME')
        before = self.repo.get_upload_group('g1').updated_at
        self.repo.conn.execute(
            "UPDATE upload_groups SET updated_at=updated_at-1000 WHERE group_key='g1'")
        self.repo.conn.commit()
        baseline = self.repo.get_upload_group('g1').updated_at

        uploader = self.make_uploader()
        uploader._persist_upload_group(self.make_task('g1'), _StubUploader('BV_SAME'))

        self.assertEqual(self.repo.get_upload_group('g1').updated_at, baseline,
                         "bvid 未变化时不应产生写操作")
        self.assertNotEqual(baseline, before)

    def test_changed_bvid_is_written_back(self):
        self.repo.get_or_create_upload_group('g1', taskname='mytask',
                                            target='biliwebapi')
        self.repo.set_upload_group_remote('g1', 'BV_OLD')

        uploader = self.make_uploader()
        uploader._persist_upload_group(self.make_task('g1'), _StubUploader('BV_NEW'))

        self.assertEqual(self.repo.get_upload_group('g1').remote_id, 'BV_NEW')

    def test_engine_without_getter_is_ignored(self):
        """引擎没有该接口时（如 youtubev3）不应报错。"""
        uploader = self.make_uploader()

        class NoGetter:
            pass

        uploader._persist_upload_group(self.make_task('g1'), NoGetter())

        self.assertIsNone(self.repo.get_upload_group('g1'))

    def test_empty_bvid_is_ignored(self):
        uploader = self.make_uploader()

        uploader._persist_upload_group(self.make_task('g1'), _StubUploader(None))

        self.assertIsNone(self.repo.get_upload_group('g1'))

    def test_getter_error_does_not_propagate(self):
        """引擎取 bvid 抛异常时不应影响上传结果。"""
        uploader = self.make_uploader()

        class Exploding:
            def get_remote_bvid(self):
                raise RuntimeError('boom')

        uploader._persist_upload_group(self.make_task('g1'), Exploding())

        self.assertIsNone(self.repo.get_upload_group('g1'))

    def test_repo_error_does_not_propagate(self):
        """状态库写入失败不应让上传任务失败。"""
        uploader = self.make_uploader()

        class BrokenRepo:
            def get_upload_group(self, key):
                raise RuntimeError('db locked')

            def get_or_create_upload_group(self, *a, **kw):
                raise RuntimeError('db locked')

        uploader.state_repo = BrokenRepo()

        uploader._persist_upload_group(self.make_task('g1'), _StubUploader('BV_X'))


class TestEndToEndGroupReuse(_UploaderTestCase):
    """串联：首次上传记录 bvid → "重启"后新建实例复用它。"""

    def test_bvid_survives_recreation(self):
        # 第一次运行：上传成功，记录 bvid
        first = self.make_uploader()
        first._persist_upload_group(self.make_task('g1'), _StubUploader('BV_REMOTE'))

        # 模拟重启：全新的 Uploader 实例（内存池为空），共享同一个状态库
        second = self.make_uploader()
        target = second._get_or_create_uploader(self.make_task('g1'))

        self.assertEqual(target.args.get('resume_bvid'), 'BV_REMOTE',
                         "重启后同一上传组必须复用原稿件，而不是新建")


if __name__ == "__main__":
    unittest.main()
