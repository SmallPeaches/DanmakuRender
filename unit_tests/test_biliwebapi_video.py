"""``DMR.Uploader.biliwebapi`` 稿件复用逻辑的模块级测试（P1）。

状态持久化的核心目标之一是：**进程重启后，同一 upload_group 的新分段应追加到
原来的稿件（同一个 bvid），而不是新建一个稿件**。为此 ``BiliWebApi`` 需要：

- 构造时可通过 ``resume_bvid`` 载入既有稿件（由状态库提供）；
- 上传时区分"既有稿件"与"本次新建"，以便决定是否追加到合集；
- 能把当前 ``bvid`` 回吐给上层，用于写回状态库。

这些用例完全不联网：通过 ``object.__new__`` 绕过构造函数（它会登录并请求网络），
并替换掉所有会发起请求的方法。
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from unit_tests.support import DMRTestCase


def _make_videos(bvid=None, title="标题", videos=None):
    """构造一个足够像 ``Data`` 的替身（只用到 bvid/title/videos 三个字段）。"""
    return SimpleNamespace(bvid=bvid, title=title, videos=videos if videos is not None else [])


class _BiliWebApiTestCase(DMRTestCase):
    """共享：不触网、不初始化 cookies 的 BiliWebApi 实例。"""

    def make_api(self, videos=None, *, remote=None, remote_raises=None):
        from DMR.Uploader.biliwebapi import BiliWebApi

        api = BiliWebApi.__new__(BiliWebApi)      # 绕过需要登录的 __init__
        api.videos = videos
        api.sort_videos = False
        api._auto_os = {'os': 'upos', 'query': '', 'probe_url': ''}
        api._BiliWebApi__bili_jct = 'fake-jct'
        api.stoped = False
        api.logger = __import__("logging").getLogger("test")

        self.remote_calls = []
        self.upload_calls = []

        def fake_get_remote_data(bvid):
            self.remote_calls.append(bvid)
            if remote_raises is not None:
                raise remote_raises
            return remote

        def fake_videoinfo_to_videos(video_info, config):
            return _make_videos(bvid=None, title="新建稿件标题")

        def fake_upload_file(filepath, lines='AUTO', videos=None, submit_api=None):
            self.upload_calls.append(('file', filepath, getattr(videos, 'bvid', None)))
            # 模拟建稿成功：稿件获得 bvid
            if getattr(videos, 'bvid', None) is None:
                videos.bvid = 'BV_NEW'
            return True, 'ok'

        api.get_remote_data = fake_get_remote_data
        api.videoinfo_to_videos = fake_videoinfo_to_videos
        api.upload_file = fake_upload_file
        api.upload_stream = lambda **kw: (True, 'ok')
        return api

    @staticmethod
    def make_file(path="seg1.flv"):
        return SimpleNamespace(path=path)


class TestResumeRemote(_BiliWebApiTestCase):
    """``_resume_remote`` / ``resume_bvid`` 的行为。"""

    def test_resume_loads_existing_video(self):
        api = self.make_api(remote=_make_videos(bvid='BV_OLD', title='旧稿件'))

        self.assertTrue(api._resume_remote('BV_OLD'))
        self.assertEqual(api.videos.bvid, 'BV_OLD')
        self.assertEqual(self.remote_calls, ['BV_OLD'])

    def test_resume_missing_video_falls_back_to_new(self):
        """稿件已被删除时应回退为"新建"，而不是带着空 videos 继续。"""
        api = self.make_api(remote=None)

        self.assertFalse(api._resume_remote('BV_GONE'))
        self.assertIsNone(api.videos)

    def test_resume_error_is_not_fatal(self):
        """取稿件数据异常不应抛出，只回退为新建。"""
        api = self.make_api(remote_raises=RuntimeError('network down'))

        self.assertFalse(api._resume_remote('BV_ERR'))
        self.assertIsNone(api.videos)

    def test_get_remote_bvid(self):
        api = self.make_api(videos=_make_videos(bvid='BV_X'))
        self.assertEqual(api.get_remote_bvid(), 'BV_X')

    def test_get_remote_bvid_none_when_new(self):
        api = self.make_api(videos=None)
        self.assertIsNone(api.get_remote_bvid())


class TestUploadReusesExistingVideo(_BiliWebApiTestCase):
    """上传时对"既有稿件"与"新建稿件"的区分。"""

    def test_upload_with_resumed_video_does_not_create_new(self):
        """恢复的稿件：上传后仍指向原 bvid，且不触发建稿。"""
        api = self.make_api(videos=_make_videos(bvid='BV_OLD', title='旧稿件'),
                            remote=_make_videos(bvid='BV_OLD', title='旧稿件'))

        status, info = api.upload(files=[self.make_file()], stream_queue=None)

        self.assertTrue(status)
        self.assertEqual(api.videos.bvid, 'BV_OLD', "必须沿用原稿件")
        self.assertEqual([c[2] for c in self.upload_calls], ['BV_OLD'],
                         "上传应针对既有 bvid")

    def test_upload_refreshes_remote_data(self):
        """既有稿件应先刷新远端信息（拿最新分P列表），再上传。"""
        api = self.make_api(videos=_make_videos(bvid='BV_OLD'),
                            remote=_make_videos(bvid='BV_OLD', title='刷新后的标题'))

        api.upload(files=[self.make_file()], stream_queue=None)

        self.assertEqual(self.remote_calls, ['BV_OLD'])
        self.assertEqual(api.videos.title, '刷新后的标题')

    def test_upload_without_videos_creates_new(self):
        """全新上传：先建稿，成功后 videos 带上了新 bvid。"""
        api = self.make_api(videos=None)

        status, _ = api.upload(files=[self.make_file()], stream_queue=None)

        self.assertTrue(status)
        self.assertEqual(api.videos.bvid, 'BV_NEW')
        self.assertEqual(self.remote_calls, [], "全新上传无需查询远端稿件")

    def test_upload_falls_back_to_new_when_video_deleted(self):
        """既有稿件已不存在时：回退为新建，并把 is_new 视为真。

        这是改造前会出问题的地方 —— 旧代码用 ``get_remote_data(...) or self.videos``，
        稿件被删时会带着**旧 bvid** 继续上传，导致提交到一个不存在的稿件。
        """
        api = self.make_api(videos=_make_videos(bvid='BV_GONE', title='已删除'),
                            remote=None)

        status, _ = api.upload(files=[self.make_file()], stream_queue=None)

        self.assertTrue(status)
        self.assertEqual(api.videos.bvid, 'BV_NEW', "应回退为新建稿件")
        self.assertEqual(self.remote_calls, ['BV_GONE'])

    def test_upload_survives_refresh_error(self):
        """刷新远端失败（网络抖动）时不得丢掉稿件归属。"""
        api = self.make_api(videos=_make_videos(bvid='BV_OLD'),
                            remote_raises=RuntimeError('timeout'))

        status, _ = api.upload(files=[self.make_file()], stream_queue=None)

        self.assertTrue(status)
        self.assertEqual(api.videos.bvid, 'BV_OLD',
                         "网络异常时不应放弃既有稿件")

    def test_upload_multiple_files_all_go_to_same_bvid(self):
        """同一批次的多个分段都应进入同一个稿件（分P）。"""
        api = self.make_api(videos=_make_videos(bvid='BV_OLD'),
                            remote=_make_videos(bvid='BV_OLD'))

        api.upload(files=[self.make_file('a.flv'), self.make_file('b.flv')],
                   stream_queue=None)

        self.assertEqual([c[1] for c in self.upload_calls], ['a.flv', 'b.flv'])
        self.assertEqual({c[2] for c in self.upload_calls}, {'BV_OLD'})


if __name__ == "__main__":
    unittest.main()
