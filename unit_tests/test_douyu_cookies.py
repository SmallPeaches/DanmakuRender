"""斗鱼取流 cookies 支持：解析归一化 + 只让取流请求带 cookies + 登录态走 JSEngine 取流分支。

对应改动：``DMR/LiveAPI/douyu.py``（用户要求：斗鱼取流时带上 cookies，拿到原画 + expire=0；
**开播判断/房间信息不带 cookies** —— 因此 cookies 不写入 session，只在取流请求上显式携带）。
全部用例**不联网**（用假 session 记录请求），也不需要真实直播间。
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest

from unit_tests.support import DMRTestCase  # noqa: F401  (完成 sys.path / 日志静音设置)

from DMR.LiveAPI.douyu import (
    DOUYU_DEFAULT_COOKIES,
    DOUYU_PLAY_DOMAIN,
    DOUYU_WEB_DOMAIN,
    douyu,
    load_cookies,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
        self.text = json.dumps(payload)
        self.status_code = 200

    def json(self):
        return self.payload

    def raise_for_status(self):
        return None


class FakeSession:
    """记录请求的假 session：cookies 用真实的 RequestsCookieJar 以便断言。"""

    def __init__(self, payload):
        import requests

        self.cookies = requests.cookies.RequestsCookieJar()
        self.payload = payload
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return FakeResponse(self.payload)

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return FakeResponse(self.payload)

    def close(self):
        return None

    def request_cookies(self, index=-1):
        """某次请求实际会带上的 cookies：session 里的 + 该请求显式传入的（后者优先）。"""
        _, _, kwargs = self.calls[index]
        sent = {c.name: c.value for c in self.cookies}
        sent.update(kwargs.get("cookies") or {})
        return sent


PLAY_INFO = {
    "error": 0,
    "data": {
        "rtmp_url": "https://hw3a.douyucdn2.cn/live",
        "rtmp_live": "1667826raGmpqNhi.flv?expire=0&did=abc",
        "rtmp_cdn": "hw-h5",
        "cdnsWithName": [{"cdn": "hw-h5"}],
    },
}


def make_api(cookies_value=DOUYU_DEFAULT_COOKIES, use_login=False, payload=None):
    """构造一个绕过 __init__（不联网）的 douyu 实例。"""
    api = douyu.__new__(douyu)
    api.rid = "1667826"
    api.plugin_msg = "douyu-1667826"
    api.fake_headers = {}
    api.stream_headers = {}
    api.sess = FakeSession(payload or PLAY_INFO)
    api._douyu__js_runable = True
    api._douyu__use_login_cookies = use_login
    api._douyu__watch_cookies = {}
    api._douyu__req_query = {
        "cdn": "hw-h5", "rate": "0", "ver": "Douyu_new", "iar": "0", "ive": "0",
        "rid": api.rid, "hevc": "0", "fa": "0", "sov": "0",
    }
    api._cookies_value = cookies_value
    return api


class TestLoadCookies(unittest.TestCase):
    """cookies 归一化：str / json / 文件 / dict 四种输入。"""

    def test_dict_passthrough(self):
        self.assertEqual(load_cookies({"dy_did": "1", "acf_uid": 2}), {"dy_did": "1", "acf_uid": "2"})

    def test_cookie_string(self):
        self.assertEqual(
            load_cookies("dy_did=abc; acf_did=def"),
            {"dy_did": "abc", "acf_did": "def"},
        )

    def test_cookie_string_tolerates_trailing_semicolon_and_spaces(self):
        self.assertEqual(
            load_cookies("  dy_did=abc;acf_uid=42;;  "),
            {"dy_did": "abc", "acf_uid": "42"},
        )

    def test_cookie_string_value_may_contain_equal_sign(self):
        self.assertEqual(load_cookies("dy_auth=a=b=c"), {"dy_auth": "a=b=c"})

    def test_duplicate_key_last_wins(self):
        self.assertEqual(load_cookies("dy_did=old; dy_did=new"), {"dy_did": "new"})

    def test_json_string(self):
        self.assertEqual(load_cookies('{"acf_uid": "1", "dy_did": "2"}'), {"acf_uid": "1", "dy_did": "2"})

    def test_biliup_style_json(self):
        text = json.dumps({"cookie_info": {"cookies": [{"name": "acf_uid", "value": "9"}]}})
        self.assertEqual(load_cookies(text), {"acf_uid": "9"})

    def test_json_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "cookies.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"acf_uid": "7"}, f)
            self.assertEqual(load_cookies(path), {"acf_uid": "7"})

    def test_plain_text_cookie_file(self):
        """真实文件格式：浏览器导出的 cookies 文本（不是 json）。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "douyu_watch_cookies.json")
            with open(path, "w", encoding="utf-8") as f:
                f.write("dy_did=5096; acf_did=1234; acf_uid=42;\n")
            self.assertEqual(load_cookies(path), {"dy_did": "5096", "acf_did": "1234", "acf_uid": "42"})

    def test_empty_and_blank(self):
        self.assertEqual(load_cookies(""), {})
        self.assertEqual(load_cookies("   "), {})

    def test_missing_file_like_value_is_not_treated_as_cookies(self):
        """路径写错时不应把路径本身当成一条 cookie。"""
        self.assertEqual(load_cookies(".login_info/not_exists.json"), {})

    def test_unsupported_type_raises(self):
        with self.assertRaises(TypeError):
            load_cookies(["dy_did=1"])

    def test_invalid_json_raises(self):
        with self.assertRaises(json.JSONDecodeError):
            load_cookies('{"acf_uid": ')


class TestCookieScope(DMRTestCase):
    """cookies 只在取流请求上携带：不写入 session，开播判断/房间信息保持匿名。"""

    def _urls(self, api):
        # 屏蔽真实取流请求，只验证 cookies 的处理方式与返回值
        api.get_web_play_info = lambda *a, **kw: PLAY_INFO["data"]
        return api.get_stream_urls(douyu_watch_cookies=api._cookies_value)

    def test_cookie_file_is_not_written_into_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "c.json")
            with open(path, "w", encoding="utf-8") as f:
                f.write("dy_did=abc; acf_uid=42")
            api = make_api(cookies_value=path)
            urls = self._urls(api)

            # cookies 只保存在实例上，session 里不能残留（否则会污染 betard 请求）
            self.assertEqual(dict(api.sess.cookies), {})
            self.assertEqual(api._douyu__watch_cookies, {"dy_did": "abc", "acf_uid": "42"})
            self.assertTrue(api._douyu__use_login_cookies)
            self.assertEqual(urls[0]["stream_url"], PLAY_INFO["data"]["rtmp_url"] + "/" + PLAY_INFO["data"]["rtmp_live"])

    def test_cookie_string_is_accepted(self):
        api = make_api(cookies_value="dy_did=abc; acf_uid=42")
        self._urls(api)
        self.assertEqual(api._douyu__watch_cookies, {"dy_did": "abc", "acf_uid": "42"})
        self.assertEqual(dict(api.sess.cookies), {})
        self.assertTrue(api._douyu__use_login_cookies)

    def test_none_string_disables_cookies(self):
        api = make_api(cookies_value="None")
        self._urls(api)
        self.assertEqual(api._douyu__watch_cookies, {})
        self.assertFalse(api._douyu__use_login_cookies)

    def test_default_path_when_not_configured(self):
        api = make_api(cookies_value=None)
        api.get_web_play_info = lambda *a, **kw: PLAY_INFO["data"]
        api.get_stream_urls()  # 不传参数 → 使用默认路径
        # 本机若存在该文件则会带上 cookies；不存在则保持无登录模式
        expected = load_cookies(DOUYU_DEFAULT_COOKIES)
        self.assertEqual(api._douyu__watch_cookies, expected)
        self.assertEqual(api._douyu__use_login_cookies, bool(expected))

    def test_cookies_never_leak_into_onair_or_room_info(self):
        """取流前后调用 onair()/get_info()，发出的 betard 请求都必须不带 cookies。"""
        api = make_api(cookies_value="dy_did=abc; acf_uid=42")
        api.get_web_play_info = lambda *a, **kw: PLAY_INFO["data"]

        api.sess.payload = {"room": {"videoLoop": 0, "show_status": 1, "isVip": 0,
                                     "room_name": "t", "nickname": "u"}}
        api.onair()
        api.get_info()
        before = [api.sess.request_cookies(i) for i in range(len(api.sess.calls))]

        api.get_stream_urls(douyu_watch_cookies=api._cookies_value)  # 中间取一次流

        api.onair()
        api.get_info()
        after = [api.sess.request_cookies(i) for i in range(len(before), len(api.sess.calls))]

        self.assertEqual(before, [{}, {}], "取流之前的 betard 请求不应带 cookies")
        self.assertEqual(after, [{}, {}], "取流之后的 betard 请求同样不应带 cookies")
        self.assertEqual(dict(api.sess.cookies), {}, "session 里不应残留登录 cookies")

    def test_missing_custom_file_falls_back_to_anonymous(self):
        api = make_api(cookies_value=".login_info/definitely_not_exists.json")
        self._urls(api)
        self.assertEqual(api._douyu__watch_cookies, {})
        self.assertFalse(api._douyu__use_login_cookies)

    def test_get_stream_urls_raises_when_play_info_unavailable(self):
        api = make_api()

        def boom(*a, **kw):
            raise RuntimeError("boom")

        api.get_web_play_info = boom
        with self.assertRaises(RuntimeError):
            api.get_stream_urls(douyu_watch_cookies="None")


class TestLoginUsesJsSignedEndpoint(DMRTestCase):
    """登录态的取流请求必须走 JSEngine 签名 + www 的 getH5Play（POST）。"""

    def _prepare(self, use_login):
        api = make_api(use_login=use_login)
        api._douyu__calls = []
        api.aget_sign = lambda rid: api._douyu__calls.append(("sign", rid)) or {"auth": "A", "tt": "1", "did": "D"}

        import DMR.LiveAPI.douyu as douyu_module

        def fake_sign(**kwargs):
            api._douyu__calls.append(("v1sign", kwargs))
            return {"key": {"enc_data": "E"}, "ts": 1, "auth": "A"}

        # 用 staticmethod 包装保存/还原：直接赋函数会让 DouyuUtils.sign 变成实例方法
        self._orig_sign = douyu_module.DouyuUtils.__dict__["sign"]
        douyu_module.DouyuUtils.sign = staticmethod(fake_sign)
        self.addCleanup(setattr, douyu_module.DouyuUtils, "sign", self._orig_sign)
        return api

    def test_login_uses_www_getH5Play_post(self):
        api = self._prepare(use_login=True)
        api._douyu__watch_cookies = {"dy_did": "abc", "acf_uid": "42"}
        api.get_web_play_info(api.rid, dict(api._douyu__req_query))

        method, url, kwargs = api.sess.calls[-1]
        self.assertEqual(method, "POST")
        self.assertIn(f"https://{DOUYU_WEB_DOMAIN}/lapi/live/getH5Play/{api.rid}", url)
        self.assertNotIn("getH5PlayV1", url)
        # 签名参数通过请求体提交（服务端据此下发原画 + expire=0）
        self.assertEqual(kwargs["data"]["auth"], "A")
        # 登录 cookies 挂在这条取流请求上
        self.assertEqual(kwargs["cookies"], {"dy_did": "abc", "acf_uid": "42"})
        self.assertEqual(api.sess.request_cookies(-1), {"dy_did": "abc", "acf_uid": "42"})
        self.assertEqual(api._douyu__calls[0][0], "sign")

    def test_anonymous_keeps_v1_endpoint(self):
        api = self._prepare(use_login=False)
        api.get_web_play_info(api.rid, dict(api._douyu__req_query))

        method, url, kwargs = api.sess.calls[-1]
        self.assertEqual(method, "POST")
        self.assertIn("getH5PlayV1", url)
        self.assertIsNone(kwargs.get("cookies"))  # 匿名路径不显式带 cookies
        self.assertEqual(api._douyu__calls[0][0], "v1sign")

    def test_vip_room_without_cookies_keeps_playweb(self):
        from DMR.LiveAPI.douyu import DouyuUtils

        api = self._prepare(use_login=False)
        DouyuUtils.VipRoom.add(api.rid)
        try:
            api.get_web_play_info(api.rid, dict(api._douyu__req_query))
        finally:
            DouyuUtils.VipRoom.discard(api.rid)

        method, url, _ = api.sess.calls[-1]
        self.assertEqual(method, "GET")
        self.assertIn(f"https://{DOUYU_PLAY_DOMAIN}/lapi/live/getH5Play/{api.rid}", url)


if __name__ == "__main__":
    unittest.main()
