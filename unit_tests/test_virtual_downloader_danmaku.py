"""虚拟录制（``DMR/Downloader/virtual_downloader.py``）与离线渲染的弹幕文件查找测试。

覆盖点：

- 虚拟录制按 ``视频同名.ass`` → ``视频同名.xml`` 的顺序查找弹幕（原先硬编码只找 .ass）；
- 找不到弹幕时 ``dm_file_id`` 保持为空；
- ``info_pattern.danmaku`` 关闭时不查找弹幕；
- 虚拟录制与 ``render_only`` 共用 ``DMR.utils.find_danmaku_file``，判定一致；
- XML 弹幕交由渲染器转换（虚拟录制自身不做转换，只把路径传下去）。

用例不联网、不跑 ffprobe（通过注入替身）：``find_files`` 里的 ``FFprobe.get_resolution``
被替换为固定值，避免依赖真实媒体文件。
"""
from __future__ import annotations

import os
import queue
import sys
import tempfile
import types
import unittest
from unittest import mock

from unit_tests.support import DMRTestCase

MB = 1024 * 1024


class _VirtualTaskTestCase(DMRTestCase):
    """共享：临时输入目录 + 绕过构造函数的 VirtualDownloaderTask。"""

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.input_dir = self._tmp.name

    def make_task(self, *, danmaku=True, output_dir=None, video_pattern=None,
                  advanced_video_args=None):
        from DMR.Downloader.virtual_downloader import VirtualDownloaderTask

        task = VirtualDownloaderTask.__new__(VirtualDownloaderTask)
        task.taskname = 'vtest'
        task.send_queue = queue.Queue()
        task.input_dir = self.input_dir
        task.output_dir = output_dir
        task.video_pattern = video_pattern or r'.*\.(mp4|mkv|avi|flv|mov|ts)$'
        task.info_pattern = {'danmaku': True} if danmaku else {}
        task.extra_info = {}
        # segment_wait_time 是"还在录制中"的判定阈值（生产默认 1 分钟，构造时 ×60）：
        # 用例里文件是刚写出来的，必须用负值才能通过"mtime > now - 阈值"这一关。
        # 这样既保留该过滤逻辑本身，又不必 sleep 一分钟。
        task.segment_wait_time = -1
        task.stop_wait_time = 0
        task.start_time = 0                     # 任何文件都"不够老"
        task.advanced_video_args = advanced_video_args or {}
        task.stoped = False
        task.logger = __import__('logging').getLogger('test')
        task.sess_id = 'sess-1'
        task.sess_videos = []
        return task

    def write(self, name, size_mb=1.0):
        path = os.path.join(self.input_dir, name)
        with open(path, 'wb') as handle:
            handle.write(b'\0' * int(size_mb * MB))
        return path

    def run_find(self, task):
        """执行 find_files，并把 ffprobe 探测替换为固定分辨率。"""
        from DMR.Downloader import virtual_downloader as vd
        from DMR.utils import FFprobe

        original = FFprobe.get_resolution
        FFprobe.get_resolution = classmethod(lambda cls, path: (1920, 1080))
        try:
            task.find_files()
        finally:
            FFprobe.get_resolution = original
        return list(task.sess_videos)

    def sent_videos(self, task):
        """取出发给 replay 的 livesegment 消息里的 VideoInfo。"""
        items = []
        while not task.send_queue.empty():
            msg = task.send_queue.get_nowait()
            if msg.event == 'livesegment':
                items.append(msg.data)
        return items


class TestVirtualDownloaderDanmaku(_VirtualTaskTestCase):

    def test_ass_is_used_when_present(self):
        self.write('seg1.mp4')
        ass = self.write('seg1.ass', size_mb=0.01)

        task = self.make_task()
        videos = self.run_find(task)

        self.assertEqual(len(videos), 1)
        self.assertEqual(videos[0].dm_file_id, ass)

    def test_xml_is_used_when_no_ass(self):
        """核心：只有 .xml 时也必须挂上（原先硬编码 .ass 会漏掉）。"""
        self.write('seg1.mp4')
        xml = self.write('seg1.xml', size_mb=0.01)

        task = self.make_task()
        videos = self.run_find(task)

        self.assertEqual(len(videos), 1)
        self.assertEqual(videos[0].dm_file_id, xml)

    def test_ass_wins_over_xml(self):
        self.write('seg1.mp4')
        ass = self.write('seg1.ass', size_mb=0.01)
        self.write('seg1.xml', size_mb=0.01)

        task = self.make_task()
        videos = self.run_find(task)

        self.assertEqual(videos[0].dm_file_id, ass)

    def test_no_danmaku_leaves_field_empty(self):
        self.write('seg1.mp4')

        task = self.make_task()
        videos = self.run_find(task)

        self.assertEqual(len(videos), 1)
        self.assertFalse(videos[0].dm_file_id)

    def test_danmaku_disabled_ignores_xml(self):
        self.write('seg1.mp4')
        self.write('seg1.xml', size_mb=0.01)

        task = self.make_task(danmaku=False)
        videos = self.run_find(task)

        self.assertFalse(videos[0].dm_file_id)

    def test_xml_is_reported_to_pipeline_unchanged(self):
        """虚拟录制只负责传路径，转换由渲染器完成 —— 传来的必须是 .xml 原件。"""
        from DMR.utils import is_danmaku_xml

        self.write('seg1.mp4')
        xml = self.write('seg1.xml', size_mb=0.01)

        task = self.make_task()
        self.run_find(task)
        sent = self.sent_videos(task)

        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0].dm_file_id, xml)
        self.assertTrue(is_danmaku_xml(sent[0].dm_file_id))
        self.assertTrue(os.path.exists(sent[0].dm_file_id))

    def test_multiple_videos_each_get_own_danmaku(self):
        self.write('seg1.mp4')
        self.write('seg2.mp4')
        ass = self.write('seg1.ass', size_mb=0.01)
        xml = self.write('seg2.xml', size_mb=0.01)

        task = self.make_task()
        videos = sorted(self.run_find(task), key=lambda v: v.path)

        self.assertEqual(len(videos), 2)
        self.assertEqual(videos[0].dm_file_id, ass)
        self.assertEqual(videos[1].dm_file_id, xml)

    def test_output_dir_copy_keeps_danmaku_reference(self):
        """配置了 output_dir 时会复制视频；弹幕引用仍指向输入目录的原件。"""
        out_dir = os.path.join(self.input_dir, 'out')
        self.write('seg1.mp4')
        xml = self.write('seg1.xml', size_mb=0.01)

        task = self.make_task(output_dir=out_dir)
        videos = self.run_find(task)

        self.assertTrue(videos[0].path.startswith(out_dir))
        # 弹幕不在 output_dir 里，仍用输入目录的路径（渲染器从视频探测分辨率，不受影响）
        self.assertEqual(videos[0].dm_file_id, xml)


class TestFindDanmakuFile(DMRTestCase):
    """共用的查找函数：虚拟录制与 render_only 必须行为一致。"""

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = self._tmp.name
        self.video = os.path.join(self.dir, 'v.mp4')
        with open(self.video, 'wb') as handle:
            handle.write(b'\0')

    def _touch(self, name):
        path = os.path.join(self.dir, name)
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write('')
        return path

    def test_prefers_ass(self):
        from DMR.utils import find_danmaku_file

        ass = self._touch('v.ass')
        self._touch('v.xml')
        self.assertEqual(find_danmaku_file(self.video), ass)

    def test_falls_back_to_xml(self):
        from DMR.utils import find_danmaku_file

        xml = self._touch('v.xml')
        self.assertEqual(find_danmaku_file(self.video), xml)

    def test_returns_none_when_absent(self):
        from DMR.utils import find_danmaku_file

        self.assertIsNone(find_danmaku_file(self.video))

    def test_returns_none_for_empty_input(self):
        from DMR.utils import find_danmaku_file

        self.assertIsNone(find_danmaku_file(''))
        self.assertIsNone(find_danmaku_file(None))

    def test_custom_suffix_order_is_respected(self):
        from DMR.utils import find_danmaku_file

        ass = self._touch('v.ass')
        xml = self._touch('v.xml')
        self.assertEqual(find_danmaku_file(self.video, suffixes=('.xml', '.ass')), xml)
        self.assertEqual(find_danmaku_file(self.video, suffixes=('.ass', '.xml')), ass)

    def test_ignores_unrelated_suffixes(self):
        """例如 .protobuf：渲染器不支持，不应被当成弹幕返回。"""
        from DMR.utils import find_danmaku_file

        self._touch('v.protobuf')
        self.assertIsNone(find_danmaku_file(self.video))

    def test_render_only_uses_shared_helper(self):
        """render_only 不应再自己实现一遍查找（避免两处漂移）。"""
        import inspect

        import render_only

        src = inspect.getsource(render_only)
        self.assertIn('find_danmaku_file', src)
        self.assertNotIn('def _find_danmaku', src)

    def test_virtual_downloader_uses_shared_helper(self):
        import inspect

        from DMR.Downloader import virtual_downloader as vd

        src = inspect.getsource(vd.VirtualDownloaderTask.find_files)
        self.assertIn('find_danmaku_file', src)
        # 不能再有硬编码的 .ass 查找
        self.assertNotIn("+ '.ass'", src)


if __name__ == '__main__':
    unittest.main()
