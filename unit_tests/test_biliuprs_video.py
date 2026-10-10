"""``DMR.Uploader.biliuprs`` 稿件复用的模块级测试（P1）。

``biliuprs`` 本身早已支持追加到既有稿件：``call_biliuprs(bvid=...)`` 会拼出
``biliup append --vid <bvid>``，而 ``upload()`` 成功后把 bvid 记在
``self.task_info['bvid']``。缺的只是**从状态库恢复**与**回写**。

这些用例通过替换 ``upload_once`` 与伪造 ``base_args`` 来避免真正调用外部
``biliup`` 可执行文件（不联网、不起子进程）。
"""
from __future__ import annotations

import unittest

from unit_tests.support import DMRTestCase


class _BiliuprsTestCase(DMRTestCase):
    """共享：绕过会调用 biliup 可执行文件的构造函数。"""

    def make_uploader(self, *, resume_bvid=None, task_upload_lock=True,
                      fail_bvids=()):
        from DMR.Uploader.biliuprs import biliuprs

        up = biliuprs.__new__(biliuprs)          # 绕过 __init__（它会跑 biliup login）
        up.debug = False
        up.biliup = 'biliup'
        up.account = 'test'
        up.cookies = '.login_info/test.json'
        up.base_args = ['biliup', '-u', up.cookies]
        up.task_upload_lock = task_upload_lock
        up.task_info = {'bvid': resume_bvid} if resume_bvid else {}
        up._upload_lock = __import__('threading').Lock()
        up._upload_procs = {}
        up.stoped = False
        up.logger = __import__('logging').getLogger('test')

        self.upload_calls: list[tuple] = []
        self.islogin_called = 0

        def fake_upload_once(video, bvid=None, **config):
            self.upload_calls.append((tuple(video), bvid))
            if bvid in fail_bvids:
                return False, 'append failed'
            # 新建稿件成功时返回一个新 bvid；追加成功时沿用原 bvid
            return True, (bvid or 'BV_NEW')

        up.upload_once = fake_upload_once
        return up

    @staticmethod
    def make_files(*paths):
        from types import SimpleNamespace

        return [SimpleNamespace(path=p) for p in (paths or ('seg1.flv',))]


class TestResumeWithBvid(_BiliuprsTestCase):

    def test_get_remote_bvid_returns_task_info_bvid(self):
        up = self.make_uploader(resume_bvid='BV_OLD')
        self.assertEqual(up.get_remote_bvid(), 'BV_OLD')

    def test_get_remote_bvid_none_before_first_upload(self):
        up = self.make_uploader()
        self.assertIsNone(up.get_remote_bvid())

    def test_first_upload_creates_new_video(self):
        """没有既有 bvid 时首次上传应新建稿件，并记下返回的 bvid。"""
        up = self.make_uploader()

        status, bvid = up.upload(files=self.make_files())

        self.assertTrue(status)
        self.assertEqual(bvid, 'BV_NEW')
        self.assertEqual(self.upload_calls, [(('seg1.flv',), None)])
        self.assertEqual(up.get_remote_bvid(), 'BV_NEW')

    def test_resumed_upload_appends_to_existing_video(self):
        """恢复的 bvid 应使上传走 append 分支（带上 bvid）。"""
        up = self.make_uploader(resume_bvid='BV_OLD')

        status, bvid = up.upload(files=self.make_files())

        self.assertTrue(status)
        self.assertEqual(self.upload_calls, [(('seg1.flv',), 'BV_OLD')],
                         "首个分段就应追加到既有稿件")
        self.assertEqual(up.get_remote_bvid(), 'BV_OLD')

    def test_subsequent_segments_reuse_bvid(self):
        """续传过程中后续分段仍进同一稿件。"""
        up = self.make_uploader(resume_bvid='BV_OLD')

        up.upload(files=self.make_files('a.flv'))
        up.upload(files=self.make_files('b.flv'))
        up.upload(files=self.make_files('c.flv'))

        self.assertEqual([c[1] for c in self.upload_calls],
                         ['BV_OLD', 'BV_OLD', 'BV_OLD'])
        self.assertEqual(up.get_remote_bvid(), 'BV_OLD')

    def test_new_video_then_reuse_within_process(self):
        """本次新建的稿件，其 bvid 也会被后续分段复用。"""
        up = self.make_uploader()

        up.upload(files=self.make_files('a.flv'))
        up.upload(files=self.make_files('b.flv'))

        self.assertEqual([c[1] for c in self.upload_calls], [None, 'BV_NEW'])


class TestDeletedVideoFallback(_BiliuprsTestCase):
    """状态库里的 bvid 可能指向已被删除的稿件，此时应退化为新建。"""

    def test_append_failure_falls_back_to_new_video(self):
        up = self.make_uploader(resume_bvid='BV_GONE', fail_bvids={'BV_GONE'})

        status, bvid = up.upload(files=self.make_files())

        self.assertTrue(status)
        self.assertEqual(self.upload_calls,
                         [(('seg1.flv',), 'BV_GONE'), (('seg1.flv',), None)],
                         "应先尝试追加，失败后新建")
        self.assertEqual(bvid, 'BV_NEW')
        self.assertEqual(up.get_remote_bvid(), 'BV_NEW',
                         "回退后应记录新稿件，避免后续继续追加到已删稿件")

    def test_no_fallback_when_creating_new_video_fails(self):
        """没有既有 bvid 时失败不应触发额外重试。"""
        up = self.make_uploader(fail_bvids={None})

        status, _ = up.upload(files=self.make_files())

        self.assertFalse(status)
        self.assertEqual(len(self.upload_calls), 1)


class TestParallelBranch(_BiliuprsTestCase):
    """``task_upload_lock=False`` 时的并行分支同样要复用 bvid。"""

    def test_parallel_first_upload_creates_then_reuses(self):
        up = self.make_uploader(task_upload_lock=False)

        up.upload(files=self.make_files('a.flv'))
        up.upload(files=self.make_files('b.flv'))

        self.assertEqual([c[1] for c in self.upload_calls], [None, 'BV_NEW'])

    def test_parallel_resumed_upload_appends(self):
        up = self.make_uploader(task_upload_lock=False, resume_bvid='BV_OLD')

        up.upload(files=self.make_files())

        self.assertEqual(self.upload_calls, [(('seg1.flv',), 'BV_OLD')])


if __name__ == "__main__":
    unittest.main()
