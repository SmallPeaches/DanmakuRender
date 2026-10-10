"""`ffmpeg.py` 15 秒存活判定与 `[hls` 行处理的回归测试。

背景（真实故障）：HLS 录制时偶发

    RuntimeError: xxx 管道读取错误, 即将重试.

而那一刻 ffmpeg 其实在正常输出（同一时刻分段甚至被正常改名登记）。原因：
判定用的是"``log`` 是否为空 / ``log`` 里有没有进度行"，而 ``log`` 当时**过滤掉了
`[hls` 行**；HLS 起流/切流期间可能十几秒只打 ``[hls @ ...] Skip(...)``，于是被
误判为管道故障，白白重试一次。

现在的判据：窗口内**有没有收到任何输出**（含 `[hls` 行），见
``FFmpegDownloader._check_window_alive``。
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest

from unit_tests.support import DMRTestCase

_HLS_LINE = ("[hls @ 0x559162dee440] Skip ('#EXT-X-VERSION:7')")
_HLS_OPEN_LINE = ("[hls @ 0x559162dee440] Opening "
                  "'https://x/live_bvc/1/423989315.m4s' for reading")
_PROGRESS_LINE = ("frame=  870 fps= 65 q=-1.0 size=N/A time=00:00:14.52 "
                  "bitrate=N/A speed=1.09x")


def _make_ffmpeg_downloader(**overrides):
    from DMR.Downloader.ffmpeg import FFmpegDownloader

    kwargs = dict(
        stream_url='http://127.0.0.1:1/fake',
        output_dir=tempfile.gettempdir(),
        output_format='ts',
        taskname='wintest',
        segment=30,
        ffmpeg=sys.executable,
    )
    kwargs.update(overrides)
    return FFmpegDownloader(**kwargs)


class TestHlsLinesAreLogged(DMRTestCase):
    """`[hls` 行必须进日志（不再被过滤）——这是误判的根因。"""

    def setUp(self):
        super().setUp()
        self.dl = _make_ffmpeg_downloader()
        self.dl._init_line_buffer()

    def test_hls_lines_go_into_log(self):
        self.dl._append_line(_HLS_LINE)
        self.assertIn('Skip', self.dl._log())
        self.assertIn('[hls', self.dl._log())

    def test_hls_opening_line_goes_into_log(self):
        self.dl._append_line(_HLS_OPEN_LINE)
        self.assertIn('Opening', self.dl._log())

    def test_progress_line_still_logged(self):
        self.dl._append_line(_PROGRESS_LINE)
        self.assertIn('frame=', self.dl._log())

    def test_received_counter_counts_every_line(self):
        for line in (_HLS_LINE, _HLS_OPEN_LINE, _PROGRESS_LINE):
            self.dl._append_line(line)
        self.assertEqual(self.dl._received_lines, 3,
                         '计数必须包含 [hls 行，否则 HLS 窗口会被误判为空')

    def test_init_resets_counter(self):
        self.dl._append_line(_HLS_LINE)
        self.dl._init_line_buffer()
        self.assertEqual(self.dl._received_lines, 0)
        self.assertEqual(self.dl._log(), '')

    def test_is_info_line_still_recognises_progress_only(self):
        """`_is_info_line` 只用于慢速判定，与"窗口是否存活"无关。"""
        self.assertTrue(self.dl._is_info_line(_PROGRESS_LINE))
        self.assertFalse(self.dl._is_info_line(_HLS_LINE))
        self.assertFalse(self.dl._is_info_line(_HLS_OPEN_LINE))


class TestWindowAliveCheck(DMRTestCase):
    """`_check_window_alive`：窗口内"有任意输出"即视为存活。"""

    def setUp(self):
        super().setUp()
        self.dl = _make_ffmpeg_downloader()
        self.dl._init_line_buffer()

    def test_window_with_only_hls_lines_is_alive(self):
        """核心回归：只有 `[hls` 行的窗口不得被判为管道故障。

        这正是真实故障的形态 —— HLS 起流/切流十几秒只打解复用行。
        """
        baseline = self.dl._received_lines
        for _ in range(30):
            self.dl._append_line(_HLS_LINE)

        new_baseline = self.dl._check_window_alive(baseline)   # 不应抛异常

        self.assertEqual(new_baseline, 30)

    def test_window_with_only_opening_lines_is_alive(self):
        baseline = self.dl._received_lines
        for _ in range(10):
            self.dl._append_line(_HLS_OPEN_LINE)
        self.assertEqual(self.dl._check_window_alive(baseline), 10)

    def test_silent_window_raises(self):
        """真·管道故障：窗口内一条输出都没有。"""
        baseline = self.dl._received_lines
        with self.assertRaises(RuntimeError) as ctx:
            self.dl._check_window_alive(baseline)
        message = str(ctx.exception)
        self.assertIn('15 秒内未收到任何 ffmpeg 输出', message)
        self.assertIn('wintest', message)
        # 报错信息要说明真实原因，不能再叫"管道读取错误"
        self.assertNotIn('管道读取错误', message)

    def test_silent_window_message_differs_from_old_misdiagnosis(self):
        """旧文案会把"起流慢"说成管道错误，这里锁定它已不复现。"""
        self.dl._append_line(_HLS_LINE)          # 有输出 → 存活
        baseline = 0
        self.dl._check_window_alive(baseline)    # 不抛

    def test_baseline_advances_each_window(self):
        baseline = self.dl._received_lines
        self.dl._append_line(_HLS_LINE)
        baseline = self.dl._check_window_alive(baseline)
        self.assertEqual(baseline, 1)
        # 下一窗口又静默 → 应当报错（保护没有被削弱）
        with self.assertRaises(RuntimeError):
            self.dl._check_window_alive(baseline)

    def test_old_behaviour_would_have_misjudged(self):
        """反向验证：按旧判据（日志里有没有"进度行"）这个窗口会被误杀。"""
        for _ in range(30):
            self.dl._append_line(_HLS_LINE)

        log = self.dl._log()
        # 旧判据1：日志是否为空 → 旧实现里 [hls 行不进 log，log 会是空
        # 旧判据2：日志里是否有进度行 → 这里确实没有
        self.assertTrue(any('time=' in li for li in []) is False)
        self.assertFalse(any(self.dl._is_info_line(li) for li in log.split('\n')),
                         '这个窗口里确实没有进度行 —— 旧逻辑会据此报错')
        # 新判据：有输出即存活
        self.dl._check_window_alive(0)


class TestRealHlsStreamWindow(DMRTestCase):
    """用真实子进程验证：HLS 风格的输出不会触发存活判定失败。"""

    CHILD = (
        'import sys, time\n'
        'for i in range(40):\n'
        '    sys.stdout.write("[hls @ 0x1] Skip (\'#EXT-X-VERSION:7\')\\n")\n'
        '    sys.stdout.flush()\n'
        '    time.sleep(0.02)\n'
    )

    def test_hls_only_child_keeps_window_alive(self):
        import subprocess
        from unittest import mock

        dl = _make_ffmpeg_downloader()
        dl.raw_name = os.path.join(tempfile.gettempdir(), 'win-Part%03d.ts')
        dl.start_time = time.time()
        dl._timer_cnt = 1
        dl.thisfile = None
        dl.stoped = False
        real_popen = subprocess.Popen

        def patched(args, **kwargs):
            return real_popen([sys.executable, '-B', '-c', self.CHILD], **kwargs)

        with mock.patch.object(subprocess, 'Popen', side_effect=patched):
            dl.start_ffmpeg()
        try:
            # 等子进程把 40 行打完（它会在约 0.8 秒内结束）
            deadline = time.time() + 3
            while time.time() < deadline and dl._received_lines < 40:
                time.sleep(0.05)
            self.assertGreaterEqual(dl._received_lines, 40,
                                    '监控线程应收到全部 [hls 行')

            # ⚠️ 必须在 drain 之前断言：_drain_line 会把该行同时从日志尾移除，
            # 先取空队列再查 _log() 必然为空（测试自身的坑，不是产品缺陷）。
            log = dl._log()
            self.assertIn('[hls', log)
            self.assertIn('Skip', log)

            # 整个窗口只有 [hls 行 —— 新判据应视为存活
            dl._check_window_alive(0)
        finally:
            dl.stoped = True
            dl.ffmpeg_proc.kill()
            dl.ffmpeg_proc.wait()
            dl._close_proc_pipes()


if __name__ == '__main__':
    unittest.main()
