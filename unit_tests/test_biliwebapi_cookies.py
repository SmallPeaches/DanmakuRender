"""``DMR.Uploader.biliwebapi`` 的 cookies 刷新（每次上传前重新读文件）。

背景：``Uploader`` 的上传器池会**长期复用**同一个 ``BiliWebApi`` 实例（默认空闲
300 秒过期、最长 7 天）。实例在构造时把 cookies 读进内存，期间用户在别处重新登录
或 ``biliup renew`` 刷新了 cookies 文件后，实例里的旧 cookies 会让上传失败。

因此要求：**每次上传（``upload()``）前都重新从 cookies 文件读一次**，
并且刷新失败不能把上传本身弄挂（保留现有 cookies 继续尝试）。

用例不联网：用临时文件当 cookies 文件，请求方法全部替换为替身。
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from types import SimpleNamespace

from unit_tests.support import DMRTestCase

import requests


def cookie_file(cookies: dict, *, with_token=True) -> dict:
    """按 biliup 的 cookies 文件结构（``cookie_info.cookies``）生成内容。"""
    data = {
        "cookie_info": {
            "cookies": [{"name": k, "value": v} for k, v in cookies.items()],
        },
        "sso": ["https://www.bilibili.com"],
    }
    if with_token:
        data["token_info"] = {"access_token": "at", "refresh_token": "rt", "mid": 1}
    return data


class _BiliWebApiTestCase(DMRTestCase):
    """共享：绕过 ``__init__``（它会登录并联网）的实例，带真实 requests.Session。"""

    def setUp(self):
        super().setUp()
        from DMR.Uploader.biliwebapi import BiliWebApi

        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)

        self.api = BiliWebApi.__new__(BiliWebApi)
        self.api.limit = 1
        self.api.sort_videos = False
        self.api.videos = None
        self.api.stoped = False
        self.api._auto_os = {"os": "upos", "query": "", "probe_url": ""}
        self.api._session = requests.Session()
        self.api.cookies_path = os.path.join(self.tmpdir.name, "account.json")
        self.api._BiliWebApi__bili_jct = "initial-jct"

    def write_cookies(self, cookies: dict, *, with_token=True):
        with open(self.api.cookies_path, "w", encoding="utf-8") as f:
            json.dump(cookie_file(cookies, with_token=with_token), f)


class TestRefreshCookies(_BiliWebApiTestCase):
    def test_refresh_reads_new_cookies_from_file(self):
        self.write_cookies({"SESSDATA": "s1", "bili_jct": "jct-1"})

        self.assertTrue(self.api.refresh_cookies())
        self.assertEqual(self.api.cookies["bili_jct"], "jct-1")
        self.assertEqual(self.api._BiliWebApi__bili_jct, "jct-1")
        self.assertEqual(self.api._session.cookies.get("SESSDATA"), "s1")
        self.assertEqual(self.api.access_token, "at")

    def test_refresh_picks_up_externally_renewed_cookies(self):
        self.write_cookies({"SESSDATA": "old", "bili_jct": "jct-old"})
        self.assertTrue(self.api.refresh_cookies())

        # 模拟外部（biliup renew / 重新登录）刷新了同一个文件
        self.write_cookies({"SESSDATA": "new", "bili_jct": "jct-new"})
        self.assertTrue(self.api.refresh_cookies())

        self.assertEqual(self.api.cookies["SESSDATA"], "new")
        self.assertEqual(self.api._BiliWebApi__bili_jct, "jct-new")
        self.assertEqual(self.api._session.cookies.get("SESSDATA"), "new")

    def test_missing_file_keeps_current_cookies(self):
        self.api.cookies = {"bili_jct": "keep"}
        self.write_cookies({})
        os.remove(self.api.cookies_path)

        self.assertFalse(self.api.refresh_cookies())
        self.assertEqual(self.api.cookies, {"bili_jct": "keep"})
        self.assertEqual(self.api._BiliWebApi__bili_jct, "initial-jct")

    def test_broken_json_keeps_current_cookies(self):
        self.api.cookies = {"bili_jct": "keep"}
        with open(self.api.cookies_path, "w", encoding="utf-8") as f:
            f.write('{"cookie_info": {"cookies": [')  # 写到一半的坏文件

        self.assertFalse(self.api.refresh_cookies())
        self.assertEqual(self.api.cookies, {"bili_jct": "keep"})

    def test_cookies_without_bili_jct_are_rejected(self):
        self.api.cookies = {"bili_jct": "keep"}
        self.write_cookies({"SESSDATA": "s1"})  # 没有 bili_jct

        self.assertFalse(self.api.refresh_cookies())
        self.assertEqual(self.api.cookies, {"bili_jct": "keep"})
        self.assertEqual(self.api._BiliWebApi__bili_jct, "initial-jct")

    def test_missing_token_info_is_tolerated(self):
        self.write_cookies({"bili_jct": "jct-1"}, with_token=False)

        self.assertTrue(self.api.refresh_cookies())
        self.assertEqual(self.api._BiliWebApi__bili_jct, "jct-1")
        self.assertIsNone(self.api.access_token)

    def test_without_cookies_path_refresh_is_noop(self):
        del self.api.cookies_path
        self.api.cookies = {"bili_jct": "keep"}

        self.assertFalse(self.api.refresh_cookies())
        self.assertEqual(self.api.cookies, {"bili_jct": "keep"})


class TestUploadRefreshesCookies(_BiliWebApiTestCase):
    """``upload()`` 必须以文件中的最新 cookies 发起上传。"""

    def _prepare_upload(self):
        seen = []

        def fake_videoinfo_to_videos(video_info, config):
            return SimpleNamespace(bvid=None, title="t", videos=[])

        def fake_upload_file(filepath, lines="AUTO", videos=None, submit_api=None):
            seen.append(self.api._BiliWebApi__bili_jct)
            videos.bvid = "BV_NEW"
            return True, "ok"

        self.api.videoinfo_to_videos = fake_videoinfo_to_videos
        self.api.upload_file = fake_upload_file
        return seen

    def test_each_upload_reloads_cookies(self):
        seen = self._prepare_upload()
        file = SimpleNamespace(path="seg1.flv")

        self.write_cookies({"bili_jct": "jct-1"})
        self.api.upload(files=[file])
        # 两次上传之间文件被外部更新
        self.write_cookies({"bili_jct": "jct-2"})
        self.api.videos = None  # 让第二次上传仍走"新建稿件"分支
        self.api.upload(files=[file])

        self.assertEqual(seen, ["jct-1", "jct-2"])

    def test_upload_survives_unreadable_cookies_file(self):
        seen = self._prepare_upload()
        self.write_cookies({"bili_jct": "jct-old"})
        self.assertTrue(self.api.refresh_cookies())
        os.remove(self.api.cookies_path)  # 上传前文件被删/不可读

        status, info = self.api.upload(files=[SimpleNamespace(path="seg1.flv")])

        self.assertTrue(status)
        self.assertEqual(seen, ["jct-old"])  # 沿用现有 cookies，上传没有被中断


if __name__ == "__main__":
    unittest.main()
