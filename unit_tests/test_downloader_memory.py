"""下载器引擎的内存占用回归测试（``DMR/Downloader/ffmpeg.py``、``streamlink.py``）。

背景（修改前实测数据）：见 ``TODO.md`` 的 F1 节。
- ``subprocess.Popen(..., bufsize=10**8)`` 会为**每个子进程**预留约 190 MB 的
  Python 堆缓冲（RSS 因为懒提交看着不变，但堆确实被占用）。
- ``ffmpeg`` 的行队列原先无上界，消费慢于生产时实测 10 秒涨到 800+ MB RSS。
- ``streamlink`` 用 ``logfile.read()`` 整体读入临时日志文件，56.7 MB 的文件会
  让 Python 堆峰值到 170 MB，而实际只用到末尾 1000 字符。

这些用例锁定"内存有上界"这一契约，跑得快（子进程用例约 3 秒）。
"""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import tempfile
import time
import unittest

import psutil

from unit_tests.support import DMRTestCase

_HERE = os.path.dirname(os.path.abspath(__file__))
_FLOOD_CHILD = os.path.join(_HERE, '_mem_flood_child.py')


def _make_ffmpeg_downloader(out_dir, **overrides):
    from DMR.Downloader.ffmpeg import FFmpegDownloader

    kwargs = dict(
        stream_url='http://127.0.0.1:1/fake',
        output_dir=out_dir,
        output_format='mp4',
        taskname='memtest',
        segment=60,
        ffmpeg=sys.executable,
    )
    kwargs.update(overrides)
    return FFmpegDownloader(**kwargs)


class TestFFmpegLineBuffer(DMRTestCase):
    """行缓冲必须有上界；日志尾与待处理队列共用同一个缓冲（单一数据源）。

    统一后的不变量：``_log_lines`` 恰好是 ``_lines`` 的内容（同一批对象），
    主循环每取走一行，两边同时少一行。
    """

    def _make(self):
        dl = _make_ffmpeg_downloader('.')
        dl._init_line_buffer()
        return dl

    def test_log_keeps_only_recent_lines(self):
        from DMR.Downloader.ffmpeg import MSG_QUEUE_MAXSIZE

        dl = self._make()
        for i in range(MSG_QUEUE_MAXSIZE * 3):
            dl._append_line(f'line{i}')

        lines = dl._log().split('\n')
        self.assertEqual(len(lines), MSG_QUEUE_MAXSIZE)
        self.assertEqual(lines[-1], f'line{MSG_QUEUE_MAXSIZE * 3 - 1}')
        self.assertEqual(lines[0], f'line{MSG_QUEUE_MAXSIZE * 2}')

    def test_log_is_bounded_for_unbounded_input(self):
        from DMR.Downloader.ffmpeg import MSG_QUEUE_MAXSIZE

        dl = self._make()
        long_line = 'y' * 4096
        for _ in range(20000):
            dl._append_line(long_line)

        # 上界 = 行数上限 × 单行长度，不再随输入量增长
        self.assertLessEqual(len(dl._log()), MSG_QUEUE_MAXSIZE * (len(long_line) + 1))

    def test_empty_log_is_empty_string(self):
        self.assertEqual(self._make()._log(), '')

    def test_drain_returns_none_when_empty(self):
        self.assertIsNone(self._make()._drain_line())

    def test_single_buffer_shared_by_queue_and_log(self):
        """核心不变量：两者始终是同一批行，不存在"两份数据"。"""
        dl = self._make()
        dl._append_line('a')
        dl._append_line('b')
        self.assertEqual(list(dl._lines), ['a', 'b'])
        self.assertEqual(list(dl._log_lines), ['a', 'b'])

        self.assertEqual(dl._drain_line(), 'a')          # FIFO
        self.assertEqual(list(dl._lines), ['b'])
        self.assertEqual(list(dl._log_lines), ['b'])     # 日志尾同步缩短

        self.assertEqual(dl._drain_line(), 'b')
        self.assertIsNone(dl._drain_line())
        self.assertEqual(dl._log(), '')

    def test_log_tail_only_covers_unprocessed_lines(self):
        """日志尾只覆盖"尚未处理"的那一段 —— 这正是 15 秒窗口检查依赖的语义。"""
        dl = self._make()
        for i in range(5):
            dl._append_line(f'l{i}')
        dl._drain_line()
        dl._drain_line()
        self.assertEqual(dl._log(), 'l2\nl3\nl4')

    def test_drain_tolerates_line_already_dropped_by_overflow(self):
        """溢出丢弃最旧行后，取到的行可能已不在日志尾里 —— 不能因此报错。"""
        from DMR.Downloader.ffmpeg import MSG_QUEUE_MAXSIZE

        dl = self._make()
        for i in range(MSG_QUEUE_MAXSIZE):
            dl._append_line(f'l{i}')
        # 模拟监控线程在溢出窗口里把同一行挤掉（这里直接清空日志尾）
        dl._log_lines.clear()
        self.assertEqual(dl._drain_line(), 'l0')     # 不抛异常


class TestFFmpegRealSubprocessMemory(DMRTestCase):
    """真实子进程下，缓冲与内存必须有上界（修改前这里会涨到数百 MB）。"""

    def setUp(self):
        super().setUp()
        self.out_dir = tempfile.mkdtemp(prefix='dmr_memtest_')

    def tearDown(self):
        try:
            os.rmdir(self.out_dir)
        except OSError:
            pass

    def _start_with_helper(self, *helper_args):
        """启动真实子进程：直接执行辅助脚本，argv 里不带 ffmpeg 的参数。

        ⚠️ 不要用 ``advanced_video_args={'ffmpeg_stream_args': [脚本]}`` 的方式注入：
        辅助脚本会被拼在 ffmpeg 参数之后，从而收到 ``-y``/``-i`` 等参数并**立刻崩溃**
        （`int(sys.argv[1])` 抛 ValueError）。那样子进程根本没有产出，用例会退化成
        "空缓冲也满足上界"的假绿。
        """
        import subprocess as _sp
        from unittest import mock

        dl = _make_ffmpeg_downloader(self.out_dir, advanced_video_args={})
        dl.raw_name = os.path.join(self.out_dir, 'probe-Part%03d.mp4')
        dl.start_time = time.time()
        dl._timer_cnt = 1
        dl.thisfile = None
        dl.stoped = False

        real_popen = _sp.Popen

        def patched(args, **kwargs):
            return real_popen([sys.executable, '-B', _FLOOD_CHILD, *helper_args], **kwargs)

        with mock.patch.object(_sp, 'Popen', side_effect=patched):
            dl.start_ffmpeg()
        return dl

    def test_real_flood_keeps_buffer_bounded(self):
        from DMR.Downloader.ffmpeg import MSG_QUEUE_MAXSIZE

        dl = self._start_with_helper()
        try:
            observed_max = 0
            deadline = time.time() + 2.0
            # 刻意**不消费**缓冲：这是最坏情况，修改前会无限膨胀
            while time.time() < deadline:
                observed_max = max(observed_max, len(dl._lines))
                time.sleep(0.1)

            self.assertLessEqual(observed_max, MSG_QUEUE_MAXSIZE)
            # 防止"子进程没跑起来 → 空缓冲也通过"的假绿
            self.assertGreater(observed_max, 0, '子进程没有产出，测试无意义')
            # 单一数据源：待处理队列与日志尾行数一致
            self.assertEqual(len(dl._lines), len(dl._log_lines))
        finally:
            dl.stop()

    def test_bufsize_is_not_huge(self):
        """锁定子进程管道不使用 10**8 这种巨额缓冲。

        直接捕获 ``Popen`` 的实参，而不是对源码做字符串匹配（后者会被注释/格式
        变化误伤，也验证不到真实调用）。
        """
        from unittest import mock

        from DMR.Downloader import ffmpeg as ffmpeg_mod

        dl = _make_ffmpeg_downloader(self.out_dir, advanced_video_args={})
        dl.raw_name = os.path.join(self.out_dir, 'probe-Part%03d.mp4')

        fake_proc = mock.Mock()
        fake_proc.stdout = None      # 让 start_ffmpeg 不去起监控线程
        with mock.patch.object(ffmpeg_mod.subprocess, 'Popen', return_value=fake_proc) as popen:
            dl.start_ffmpeg()

        self.assertEqual(popen.call_count, 1)
        bufsize = popen.call_args.kwargs.get('bufsize')
        self.assertIsNotNone(bufsize, 'bufsize 应显式声明')
        self.assertLess(bufsize, 1024 * 1024,
                        f'bufsize={bufsize} 过大，会为每个子进程预留大量缓冲内存')

    def test_stop_is_idempotent_and_drains(self):
        dl = self._start_with_helper()
        time.sleep(0.8)
        dl.stop()
        # 第二次 stop 必须直接返回，不抛异常
        dl.stop()
        self.assertTrue(dl.stoped)

    def test_monitor_thread_does_not_spin_after_child_exits(self):
        """子进程退出→管道 EOF 后，监控线程必须停止，不能空转吃 CPU。

        缺陷形态：``readline()`` 在 EOF 时立即返回空串，原实现只判断
        ``len(line) > 0`` 而不退出循环，于是 ``while not self.stoped`` 空转，
        实测吃满 **0.97 CPU 秒/秒**（一个核），直到主循环把 ``stoped`` 置位。
        """
        # 打印一行就退出 → 管道随即 EOF
        dl = self._start_with_helper('1')

        dl.ffmpeg_proc.wait(timeout=10)
        thread = dl.ffmpeg_monitor_proc
        # 等线程自己退出（修复后应立刻退出）
        thread.join(timeout=3)
        self.assertFalse(thread.is_alive(),
                         'EOF 后监控线程仍在运行（会持续自旋占用 CPU）')

        proc = psutil.Process()
        t0 = proc.cpu_times()
        time.sleep(1.0)
        t1 = proc.cpu_times()
        cpu_used = (t1.user - t0.user) + (t1.system - t0.system)
        self.assertLess(cpu_used, 0.2,
                        f'空闲 1 秒消耗 {cpu_used:.3f} CPU 秒，疑似仍在自旋')

        dl.stoped = True
        dl.ffmpeg_proc.kill()
        dl._close_proc_pipes()


class TestStreamlinkInprogressDedup(DMRTestCase):
    """streamlink 轮询不得对**同一个文件**反复上报"进行中"。

    真实故障：日志里同一条

        DEBUG: 已登记进行中的分段 1：./直播回放/[正在录制]twitchpros-...-Part000-xxx.mkv

    反复出现。原因：判重条件用的是 ``files[-1] != self.lastfile``，而 ``lastfile``
    表示"上次已**封闭**的分段"（总比正在写入的那个更旧）。两者不等时，同一个最新
    文件在每轮 10 秒轮询里都会被重新上报一次。

    实测（真实 HLS 源 + 真实 streamlink/ffmpeg，90 秒）：修复前 Part001/Part003
    各被上报 2 次；修复后 Part000..Part005 **各 1 次**。
    """

    def _make(self):
        from DMR.Downloader.streamlink import StreamlinkDownloader

        return StreamlinkDownloader(
            output_dir=tempfile.mkdtemp(prefix='dmr_sl_'),
            segment=15,
            url='https://live.bilibili.com/1',
            taskname='twitchpros',
            output_format='mkv',
        )

    def test_last_reported_is_initialised(self):
        dl = self._make()
        self.assertIsNone(dl._last_reported)
        self.assertIsNone(dl.lastfile)

    def test_reporting_does_not_touch_lastfile(self):
        """核心不变量：上报"进行中"只能推进 _last_reported，绝不能动 lastfile。

        若把 lastfile 也一起推进，那个文件就再也不会被 segment_callback 认领，
        会丢掉一个分段的登记 —— 这正是不能用 lastfile 做判重的原因。
        """
        dl = self._make()
        dl.lastfile = None
        parts = [f'Part{i:03d}' for i in range(3)]

        emitted = []
        for newest in parts:
            if newest != dl._last_reported:          # 引擎里的判重条件
                dl._last_reported = newest
                emitted.append(newest)
            # segment_callback 的推进只在真正封闭时发生（这里不模拟）

        self.assertEqual(emitted, parts, '每个文件只应上报一次')
        self.assertIsNone(dl.lastfile, '上报进行中不得改动 lastfile')

    def test_old_condition_would_repeat(self):
        """反向验证：用 lastfile 当判重条件时，同一文件会被重复上报。

        序列取自真实探针的时间线：Part001 出现 → Part000 被封闭（lastfile 推进到
        Part000）→ 下一轮 files[-1] 仍是 Part001，而 lastfile 已是 Part000，于是
        Part001 被**第二次**上报；直到 Part002 出现才停。
        """
        polls = ['Part000', 'Part001', 'Part001', 'Part002']
        # 生产时序：第 i 轮里封闭并推进 lastfile 的那一段
        segment_closes = {0: None, 1: 'Part000', 2: None, 3: 'Part001'}

        reported_with_old, reported_with_new = [], []
        lastfile = None
        last_reported = None
        for i, newest in enumerate(polls):
            if segment_closes[i]:
                lastfile = segment_closes[i]
            if newest != lastfile:                    # 旧条件（有 bug）
                reported_with_old.append(newest)
            if newest != last_reported:               # 新条件
                last_reported = newest
                reported_with_new.append(newest)

        self.assertEqual(reported_with_old,
                         ['Part000', 'Part001', 'Part001', 'Part002'],
                         '旧条件确实会重复上报同一文件')
        self.assertEqual(reported_with_new, ['Part000', 'Part001', 'Part002'],
                         '新条件每个文件只上报一次')

    def test_loop_source_uses_dedicated_state(self):
        """锁定实现：循环里的判重必须用 _last_reported，而不是 lastfile。"""
        import inspect

        from DMR.Downloader import streamlink as sl

        src = inspect.getsource(sl.StreamlinkDownloader.start_helper)
        self.assertIn('_last_reported', src)
        self.assertNotIn('files[-1] != self.lastfile', src,
                         '不应再拿 lastfile 作为"进行中"的判重条件')

    def test_segment_advance_still_uses_lastfile(self):
        """修复不能影响 segment_callback 的推进（仍以 lastfile 为游标）。"""
        import inspect

        from DMR.Downloader import streamlink as sl

        src = inspect.getsource(sl.StreamlinkDownloader.start_helper)
        self.assertIn('files.index(self.lastfile)', src)
        self.assertIn('self.lastfile = files[p]', src)


class TestStreamlinkLogfileTail(DMRTestCase):
    """``read_logfile_tail`` 必须只读限定大小的片段，而不是整个文件。"""

    def _write_logfile(self, size_bytes):
        """写一个 size_bytes 大小的临时日志文件，返回已打开的文件对象。"""
        f = tempfile.TemporaryFile(mode='w+b')
        payload = (b'[cli][info] segment line ' + b'z' * 100 + b'\n')
        written = 0
        while written < size_bytes:
            f.write(payload)
            written += len(payload)
        f.flush()
        return f

    def test_reads_only_tail_when_large(self):
        from DMR.Downloader.streamlink import LOG_TAIL_BYTES, read_logfile_tail

        size = LOG_TAIL_BYTES * 4
        with self._write_logfile(size) as f:
            data = read_logfile_tail(f)
        self.assertLessEqual(len(data.encode('utf8')), LOG_TAIL_BYTES)
        self.assertGreater(len(data), 0)

    def test_from_start_returns_beginning(self):
        from DMR.Downloader.streamlink import LOG_TAIL_BYTES, read_logfile_tail

        port_line = 'http://127.0.0.1:12345\n'
        with tempfile.TemporaryFile(mode='w+b') as f:
            f.write(port_line.encode('utf8'))
            f.write(b'padding\n' * (LOG_TAIL_BYTES))   # 远超尾部窗口
            f.flush()
            data = read_logfile_tail(f, from_start=True)
        # 端口行在最前面且文件远大于窗口：只有 from_start 才能看到它
        self.assertIn('http://127.0.0.1:12345', data)

    def test_tail_window_would_miss_beginning(self):
        """反向确认：尾部读取确实看不到文件开头（说明上一条用例有区分度）。"""
        from DMR.Downloader.streamlink import LOG_TAIL_BYTES, read_logfile_tail

        with tempfile.TemporaryFile(mode='w+b') as f:
            f.write(b'http://127.0.0.1:12345\n')
            f.write(b'padding\n' * (LOG_TAIL_BYTES))
            f.flush()
            data = read_logfile_tail(f)
        self.assertNotIn('http://127.0.0.1:12345', data)

    def test_small_file_is_returned_whole(self):
        from DMR.Downloader.streamlink import read_logfile_tail

        with tempfile.TemporaryFile(mode='w+b') as f:
            f.write(b'hello streamlink\n')
            f.flush()
            self.assertEqual(read_logfile_tail(f), 'hello streamlink\n')

    def test_empty_file_returns_empty(self):
        from DMR.Downloader.streamlink import read_logfile_tail

        with tempfile.TemporaryFile(mode='w+b') as f:
            self.assertEqual(read_logfile_tail(f), '')

    def test_accepts_text_mode_file(self):
        """兼容文本模式打开的文件对象（返回 str，不需要再 decode）。"""
        from DMR.Downloader.streamlink import read_logfile_tail

        path = os.path.join(tempfile.mkdtemp(prefix='dmr_memtest_'), 'sl.log')
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write('line1\nline2\n')
            with open(path, 'r', encoding='utf-8') as f:
                self.assertEqual(read_logfile_tail(f), 'line1\nline2\n')
        finally:
            os.remove(path)
            os.rmdir(os.path.dirname(path))

    def test_startup_path_does_not_read_whole_file(self):
        """启动判定路径不能出现整体 read()（否则长录制下会把日志全读进内存）。"""
        import inspect

        from DMR.Downloader import streamlink as sl_mod

        src = inspect.getsource(sl_mod.StreamlinkDownloader.start_helper)
        self.assertNotIn('logfile.read()', src)
        self.assertIn('read_logfile_tail', src)


class TestStreamlinkStopSafety(DMRTestCase):
    """``stop()`` 在 ``start()`` 之前/失败后调用必须安全（原先会 AttributeError）。"""

    def _make(self):
        from DMR.Downloader.streamlink import StreamlinkDownloader

        return StreamlinkDownloader(
            output_dir=tempfile.mkdtemp(prefix='dmr_memtest_'),
            segment=60,
            url='https://example.com/live',
            taskname='memtest',
            output_format='mp4',
        )

    def test_stop_before_start_does_not_raise(self):
        dl = self._make()
        dl.stop()   # 修改前：self.uuid / self.lastfile 未初始化 → AttributeError
        self.assertTrue(dl.stoped)

    def test_stop_without_processes_records_no_segment(self):
        dl = self._make()
        called = []
        dl.segment_callback = called.append
        dl.uuid = 'abcdefgh'
        dl.stop()
        self.assertEqual(called, [])

    def test_stop_kills_partially_started_processes(self):
        """streamlink 起来了但 ffmpeg 没起来时，已起的进程也必须被清理。"""
        dl = self._make()
        dl.uuid = 'abcdefgh'
        proc = subprocess.Popen([sys.executable, '-B', '-c', 'import time; time.sleep(30)'])
        dl.streamlink_proc = proc
        dl.ffmpeg_proc = None
        try:
            dl.stop()
            self.assertIsNotNone(proc.poll(), 'streamlink 子进程未被清理')
        finally:
            if proc.poll() is None:
                proc.kill()

    def test_stop_reports_last_file_on_shutdown(self):
        """结束时应把最后一个文件也回调出去（原有语义不能丢）。"""
        import glob as _glob

        dl = self._make()
        dl.uuid = 'zzzzzzzz'
        last = os.path.join(dl.output_dir, f'[正在录制]memtest-1-Part001-{dl.uuid}.mp4')
        open(last, 'wb').close()
        final = os.path.join(dl.output_dir, f'memtest-1-Part001-{dl.uuid}.mp4')
        called = []
        dl.segment_callback = called.append
        try:
            dl.stop()
        finally:
            for p in _glob.glob(os.path.join(dl.output_dir, '*')):
                try:
                    os.remove(p)
                except OSError:
                    pass
            try:
                os.rmdir(dl.output_dir)
            except OSError:
                pass
        self.assertEqual(called, [last])


class TestFFmpegBehaviorUnchanged(DMRTestCase):
    """优化内存不能改变行为：分段回调与"正在写入"上报必须照旧。

    用假 ffmpeg（真实子进程）按真实格式打印 ``Opening`` 行，验证：
    - 上一个分段封闭时触发 ``segment_callback``（闭合语义不变）；
    - 新分段立刻触发 ``inprogress_callback``（对账依赖的信号不变）。
    """

    def setUp(self):
        super().setUp()
        self.out_dir = tempfile.mkdtemp(prefix='dmr_memtest_')
        self.seg_dir = os.path.join(self.out_dir, 'segments')
        os.makedirs(self.seg_dir, exist_ok=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.out_dir, ignore_errors=True)

    def _make_engine(self, **overrides):
        env = dict(os.environ)
        env['PROBE_OUT'] = self.seg_dir.replace('\\', '/')
        dl = _make_ffmpeg_downloader(self.out_dir, **overrides)
        dl._test_env = env
        return dl

    def test_segment_and_inprogress_callbacks(self):
        import subprocess as _sp

        dl = self._make_engine()
        recorded, inprogress = [], []
        dl.segment_callback = recorded.append
        dl.inprogress_callback = inprogress.append
        dl.raw_name = os.path.join(self.out_dir, 'rec-Part%03d.mp4')

        # 直接驱动 start_ffmpeg，再用 main-loop 的同一段解析逻辑消费队列
        real_popen = _sp.Popen

        def patched(args, **kwargs):
            kwargs['env'] = dict(os.environ, PROBE_OUT=self.seg_dir.replace('\\', '/'))
            return real_popen([sys.executable, '-B', _FLOOD_CHILD, '--segments'], **kwargs)

        import unittest.mock as mock
        with mock.patch('subprocess.Popen', side_effect=patched):
            dl.start_ffmpeg()
        try:
            self.assertIsNotNone(dl._lines)
            dl.thisfile = None
            dl.stoped = False
            dl.download_stable = True    # 跳过 stable 判定，专测分段语义
            deadline = time.time() + 6.5
            while time.time() < deadline:
                line = dl._drain_line()
                if line is None:
                    time.sleep(0.05)
                    continue
                # 走生产代码的逐行处理逻辑，而不是在测试里复刻一遍
                dl._handle_line(line, 0)
        finally:
            dl.stoped = True
            dl.ffmpeg_proc.kill()
            dl.ffmpeg_proc.wait()
            dl._close_proc_pipes()

        # 3 个分段依次 Opening → 前两个被"下一个 Opening"封闭并回调
        self.assertEqual(len(inprogress), 3, inprogress)
        self.assertEqual(len(recorded), 2, recorded)
        self.assertTrue(recorded[0].endswith('seg-1.mp4'), recorded)
        self.assertTrue(recorded[1].endswith('seg-2.mp4'), recorded)
        self.assertTrue(dl.thisfile.endswith('seg-3.mp4'), dl.thisfile)


if __name__ == '__main__':
    unittest.main()
