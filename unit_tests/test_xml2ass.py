"""XML 弹幕转换器（``DMR/utils/xml2ass.py``）与渲染器 XML 兼容的模块级测试。

设计要点：

- **不依赖真实 dmconvert**：用例用 ``sys.modules`` 注入替身，因此没有安装该
  可选依赖时也能跑（CI / 干净环境）。
- 重点锁定**参数顺序**：上游 ``convert_xml_to_ass`` 是 14 个位置参数，顺序写错
  不会报错、只会产出错误的弹幕，因此必须逐位断言。
- 渲染器侧锁定：``.ass`` 原样透传、``.xml`` 走转换、临时文件渲染后被清理、
  转换失败时不留下临时文件。
"""
from __future__ import annotations

import os
import sys
import tempfile
import types
import unittest
from unittest import mock

from unit_tests.support import DMRTestCase

FIELDS = ['font_name', 'font_size', 'sc_font_size', 'resolution_x', 'resolution_y',
          'displayarea', 'roll_time', 'fix_time', 'opacity', 'bold', 'outline', 'shadow']


class _FakeDmconvert(types.ModuleType):
    """``dmconvert`` 替身：记录调用参数并写一个可被检测的输出文件。"""

    def __init__(self, write_output=True):
        super().__init__('dmconvert')
        self.calls = []
        self.write_output = write_output

    def convert_xml_to_ass(self, *args):
        self.calls.append(args)
        if self.write_output:
            ass_file = args[-1]
            with open(ass_file, 'w', encoding='utf-8') as handle:
                handle.write('[Script Info]\nTitle: fake\n')


class TestXml2AssArgs(DMRTestCase):
    def test_defaults_match_config(self):
        from DMR.utils.xml2ass import DEFAULT_DMCONVERT_ARGS, Xml2AssArgs

        args = Xml2AssArgs.from_dict(DEFAULT_DMCONVERT_ARGS)
        self.assertEqual(args.font_name, 'Microsoft YaHei')
        self.assertEqual(args.font_size, 36)
        # 默认值必须与 default.yml 的弹幕录制参数保持一致
        self.assertEqual(args.displayarea, 0.4)      # dmrate
        self.assertEqual(args.roll_time, 16.0)       # dmduration
        self.assertEqual(args.opacity, 0.8)          # opacity
        self.assertEqual(args.outline, 1.0)          # outlinesize

    def test_config_section_is_present_and_merged(self):
        """default.yml 里必须真的有这一段，否则用户改配置不生效。"""
        from DMR.Config import Config

        config = Config('configs/global.yml')
        section = config.global_config['render_args']['dmrender'].get('dmconvert')
        self.assertIsInstance(section, dict, 'default.yml 缺少 render_args.dmrender.dmconvert')
        for key in FIELDS:
            self.assertIn(key, section, f'dmconvert 段缺少配置项 {key}')

    def test_from_dict_ignores_unknown_keys(self):
        """未知键必须被忽略 —— 否则上游改签名或用户写错键会直接 TypeError。"""
        from DMR.utils.xml2ass import Xml2AssArgs

        args = Xml2AssArgs.from_dict({'font_size': 40, 'not_a_real_option': 1,
                                      'another_bogus': 'x'})
        self.assertEqual(args.font_size, 40)
        self.assertEqual(args.sc_font_size, 36)

    def test_from_dict_none_uses_defaults(self):
        from DMR.utils.xml2ass import Xml2AssArgs

        self.assertEqual(Xml2AssArgs.from_dict(None), Xml2AssArgs())

    def test_as_call_args_order_matches_upstream(self):
        """逐位断言位置参数顺序（上游签名见 DanmakuConvert/convert.py）。"""
        from DMR.utils.xml2ass import Xml2AssArgs

        args = Xml2AssArgs(
            font_name='F', font_size=11, sc_font_size=22, resolution_x=1920,
            resolution_y=1080, displayarea=0.5, roll_time=12.0, fix_time=5.0,
            opacity=0.9, bold=1, outline=2.0, shadow=0.5)
        call = args.as_call_args('in.xml', 'out.ass')
        self.assertEqual(call, ('F', 11, 22, 1920, 1080, 0.5, 12.0, 5.0,
                                0.9, 1, 2.0, 0.5, 'in.xml', 'out.ass'))

    def test_missing_resolution_is_rejected_with_actionable_message(self):
        from DMR.utils.xml2ass import Xml2AssArgs

        with self.assertRaises(ValueError) as ctx:
            Xml2AssArgs(font_size=36).as_call_args('in.xml', 'out.ass')
        self.assertIn('resolution_x', str(ctx.exception))


class TestIsDanmakuXml(DMRTestCase):
    def test_xml_detected_case_insensitively(self):
        from DMR.utils.xml2ass import is_danmaku_xml

        self.assertTrue(is_danmaku_xml('a.xml'))
        self.assertTrue(is_danmaku_xml('A.XML'))
        self.assertTrue(is_danmaku_xml(r'dir\sub\b.xml'))

    def test_ass_and_others_are_not_xml(self):
        from DMR.utils.xml2ass import is_danmaku_xml

        for path in ('a.ass', 'a.mp4', 'xml', '', None, 'a.xml.bak'):
            self.assertFalse(is_danmaku_xml(path), path)

    def test_default_ass_path(self):
        from DMR.utils.xml2ass import default_ass_path

        self.assertEqual(default_ass_path(os.path.join('d', 'a.xml')),
                         os.path.join('d', 'a.ass'))


class TestXmlToAss(DMRTestCase):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = self._tmp.name
        self.xml = os.path.join(self.dir, 'video.xml')
        with open(self.xml, 'w', encoding='utf-8') as handle:
            handle.write("<i><d p=\"0.0,1,25,16777215,0,0,0,0\">hi</d></i>")
        # XML 本身不含分辨率，转换必须由调用方提供；这里模拟渲染器探测的结果
        self.args = {'resolution_x': 1920, 'resolution_y': 1080}

    def _with_fake(self, fake):
        return mock.patch.dict(sys.modules, {'dmconvert': fake})

    def test_converts_and_returns_abs_path(self):
        from DMR.utils import xml_to_ass

        fake = _FakeDmconvert()
        with self._with_fake(fake):
            result = xml_to_ass(self.xml, args=self.args)

        self.assertTrue(os.path.isabs(result))
        self.assertTrue(result.endswith('.ass'))
        self.assertTrue(os.path.exists(result), '转换产物应存在')
        self.assertEqual(len(fake.calls), 1)

    def test_missing_resolution_is_rejected_clearly(self):
        """XML 不带分辨率信息：没给就必须明确报错，而不是让上游产出错位弹幕。"""
        from DMR.utils import xml_to_ass

        fake = _FakeDmconvert()
        with self._with_fake(fake):
            with self.assertRaises(ValueError) as ctx:
                xml_to_ass(self.xml)          # 未给分辨率
        self.assertIn('resolution', str(ctx.exception))
        self.assertEqual(fake.calls, [], '不应调用上游库')

    def test_passes_config_values_in_order(self):
        from DMR.utils import xml_to_ass

        fake = _FakeDmconvert()
        args = {'font_name': 'F', 'font_size': 40, 'resolution_x': 1280,
                'resolution_y': 720, 'displayarea': 0.6}
        with self._with_fake(fake):
            xml_to_ass(self.xml, args=args)

        call = fake.calls[0]
        self.assertEqual(call[0], 'F')
        self.assertEqual(call[1], 40)
        self.assertEqual(call[3], 1280)
        self.assertEqual(call[4], 720)
        self.assertEqual(call[5], 0.6)
        self.assertEqual(call[-2], os.path.abspath(self.xml))
        self.assertEqual(call[-1], os.path.abspath(os.path.splitext(self.xml)[0] + '.ass'))

    def test_supports_dict_args_from_config(self):
        """配置字典里带未知键也必须能用（用户可能照别的版本抄配置）。"""
        from DMR.utils import xml_to_ass

        fake = _FakeDmconvert()
        with self._with_fake(fake):
            result = xml_to_ass(self.xml, args={'resolution_x': 1, 'resolution_y': 1,
                                                'bogus_key': 9})
        self.assertTrue(os.path.exists(result))

    def test_explicit_output_path_is_used(self):
        from DMR.utils import xml_to_ass

        fake = _FakeDmconvert()
        out = os.path.join(self.dir, 'custom.ass')
        with self._with_fake(fake):
            result = xml_to_ass(self.xml, out, args=self.args)
        self.assertEqual(result, os.path.abspath(out))
        self.assertEqual(fake.calls[0][-1], os.path.abspath(out))

    def test_skip_if_exists_avoids_reconversion(self):
        from DMR.utils import xml_to_ass

        fake = _FakeDmconvert()
        out = os.path.join(self.dir, 'cached.ass')
        with open(out, 'w', encoding='utf-8') as handle:
            handle.write('existing')
        with self._with_fake(fake):
            result = xml_to_ass(self.xml, out, args=self.args, skip_if_exists=True)
        self.assertEqual(result, os.path.abspath(out))
        self.assertEqual(fake.calls, [], '已存在时不应重复调用上游库')

    def test_creates_missing_output_directory(self):
        from DMR.utils import xml_to_ass

        fake = _FakeDmconvert()
        out = os.path.join(self.dir, 'nested', 'deep', 'o.ass')
        with self._with_fake(fake):
            result = xml_to_ass(self.xml, out, args=self.args)
        self.assertTrue(os.path.exists(result))

    def test_missing_input_raises_file_not_found(self):
        from DMR.utils import xml_to_ass

        with self.assertRaises(FileNotFoundError):
            xml_to_ass(os.path.join(self.dir, 'nope.xml'), args=self.args)

    def test_upstream_failure_is_wrapped_with_paths(self):
        from DMR.utils import xml_to_ass

        class _Boom(_FakeDmconvert):
            def convert_xml_to_ass(self, *args):
                raise ValueError('bad xml')

        with self._with_fake(_Boom()):
            with self.assertRaises(RuntimeError) as ctx:
                xml_to_ass(self.xml, args=self.args)
        message = str(ctx.exception)
        self.assertIn('bad xml', message)
        self.assertIn(self.xml, message)

    def test_missing_output_file_is_detected(self):
        """上游"成功"但没写文件时必须报错，而不是让渲染拿到不存在的路径。"""
        from DMR.utils import xml_to_ass

        with self._with_fake(_FakeDmconvert(write_output=False)):
            with self.assertRaises(RuntimeError) as ctx:
                xml_to_ass(self.xml, args=self.args)
        self.assertIn('未生成输出文件', str(ctx.exception))

    def test_library_missing_raises_actionable_runtime_error(self):
        """未安装 dmconvert 时：只在真的要转换时报错，且提示安装方式。"""
        from DMR.utils import xml_to_ass

        with mock.patch.dict(sys.modules, {'dmconvert': None}):
            with self.assertRaises(RuntimeError) as ctx:
                xml_to_ass(self.xml, args=self.args)
        self.assertIn('dmconvert', str(ctx.exception))
        self.assertIn('pip install', str(ctx.exception))

    def test_bad_args_type_is_rejected(self):
        from DMR.utils import xml_to_ass

        with self.assertRaises(TypeError):
            xml_to_ass(self.xml, args=('not', 'a', 'dict'))


class TestDmRenderXmlCompat(DMRTestCase):
    """渲染器必须同时接受 .ass 与 .xml，且不留下临时文件。"""

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = self._tmp.name
        self.video = os.path.join(self.dir, 'v.mp4')
        with open(self.video, 'wb') as handle:
            handle.write(b'\0' * 1024)
        self.xml = os.path.join(self.dir, 'v.xml')
        with open(self.xml, 'w', encoding='utf-8') as handle:
            handle.write('<i></i>')
        self.ass = os.path.join(self.dir, 'v.ass')
        with open(self.ass, 'w', encoding='utf-8') as handle:
            handle.write('[Script Info]\n')

    def _make_render(self, **overrides):
        from DMR.Render.dmrender import DmRender

        kwargs = dict(hwaccel_args=[], vencoder='libx264', vencoder_args=[],
                      aencoder='aac', aencoder_args=[], output_resize=None,
                      advanced_render_args={'filter_complex': "subtitles=filename='{DANMAKU}'"},
                      dmconvert={'font_size': 30})
        kwargs.update(overrides)
        return DmRender(**kwargs)

    def _video_info(self, dm_file_id):
        from DMR.utils import VideoInfo
        return VideoInfo(path=self.video, dm_file_id=dm_file_id, file_id='f1',
                         dtype='src_video', group_id='g', segment_id=1)

    def test_ass_passes_through_untouched(self):
        render = self._make_render()
        prepared, temp = render._prepare_danmaku(self.video, self.ass)
        self.assertEqual(prepared, self.ass)
        self.assertIsNone(temp, '.ass 不应产生临时文件')
        self.assertTrue(os.path.exists(self.ass), '.ass 不应被改动')

    def test_xml_is_converted_and_reports_temp_file(self):
        from unit_tests.test_xml2ass import _FakeDmconvert

        render = self._make_render()
        fake = _FakeDmconvert()
        with mock.patch('DMR.utils.xml2ass._import_convert',
                        return_value=fake.convert_xml_to_ass), \
                mock.patch.object(render, '_video_resolution', return_value=(1280, 720)):
            prepared, temp = render._prepare_danmaku(self.video, self.xml)

        self.assertNotEqual(prepared, self.xml)
        self.assertTrue(prepared.endswith('.ass'))
        self.assertEqual(temp, prepared, '转换产物应由调用方清理')
        self.assertTrue(os.path.exists(prepared))
        # 探测到的视频分辨率必须传下去
        self.assertEqual(fake.calls[0][3], 1280)
        self.assertEqual(fake.calls[0][4], 720)
        render._remove_quietly(temp)

    def test_explicit_resolution_overrides_probe(self):
        from unit_tests.test_xml2ass import _FakeDmconvert

        render = self._make_render(dmconvert={'resolution_x': 640, 'resolution_y': 360})
        fake = _FakeDmconvert()
        with mock.patch('DMR.utils.xml2ass._import_convert',
                        return_value=fake.convert_xml_to_ass), \
                mock.patch.object(render, '_video_resolution', return_value=(1280, 720)):
            prepared, temp = render._prepare_danmaku(self.video, self.xml)
        self.assertEqual(fake.calls[0][3], 640)
        self.assertEqual(fake.calls[0][4], 360)
        render._remove_quietly(temp)

    def test_conversion_failure_leaves_no_temp_file(self):
        render = self._make_render()
        before = set(os.listdir(self.dir))
        with mock.patch('DMR.utils.xml2ass._import_convert',
                        side_effect=RuntimeError('Convert failed: boom')), \
                mock.patch.object(render, '_video_resolution', return_value=(1920, 1080)):
            with self.assertRaises(RuntimeError):
                render._prepare_danmaku(self.video, self.xml)
        self.assertEqual(set(os.listdir(self.dir)), before,
                         '转换失败时必须清掉临时文件')

    def test_render_one_cleans_temp_after_render(self):
        """端到端：render_one 渲染结束后临时 ASS 必须被删除。"""
        from unit_tests.test_xml2ass import _FakeDmconvert

        render = self._make_render()
        fake = _FakeDmconvert()
        captured = {}

        def fake_render_helper(video, danmaku, output, **kwargs):
            captured['danmaku'] = danmaku
            self.assertTrue(os.path.exists(danmaku), '渲染时弹幕文件必须存在')
            with open(output, 'wb') as handle:
                handle.write(b'\0' * 2048)
            return True, 'ok'

        with mock.patch('DMR.utils.xml2ass._import_convert',
                        return_value=fake.convert_xml_to_ass), \
                mock.patch.object(render, '_video_resolution', return_value=(1920, 1080)), \
                mock.patch.object(render, 'render_helper', side_effect=fake_render_helper):
            status, info = render.render_one(self._video_info(self.xml),
                                             os.path.join(self.dir, 'out.mp4'))

        self.assertTrue(status)
        self.assertFalse(os.path.exists(captured['danmaku']),
                         '渲染结束后临时弹幕文件应被清理')
        self.assertEqual(info.dm_file_id, None)

    def test_render_one_cleans_temp_even_when_render_fails(self):
        from unit_tests.test_xml2ass import _FakeDmconvert

        render = self._make_render()
        fake = _FakeDmconvert()
        captured = {}

        def failing_helper(video, danmaku, output, **kwargs):
            captured['danmaku'] = danmaku
            raise RuntimeError('ffmpeg boom')

        with mock.patch('DMR.utils.xml2ass._import_convert',
                        return_value=fake.convert_xml_to_ass), \
                mock.patch.object(render, '_video_resolution', return_value=(1920, 1080)), \
                mock.patch.object(render, 'render_helper', side_effect=failing_helper):
            with self.assertRaises(RuntimeError):
                render.render_one(self._video_info(self.xml),
                                  os.path.join(self.dir, 'out.mp4'))

        self.assertFalse(os.path.exists(captured['danmaku']),
                         '渲染失败也必须清理临时弹幕文件')

    def test_ass_only_render_still_works(self):
        render = self._make_render()
        captured = {}

        def fake_render_helper(video, danmaku, output, **kwargs):
            captured['danmaku'] = danmaku
            with open(output, 'wb') as handle:
                handle.write(b'\0' * 2048)
            return True, 'ok'

        with mock.patch.object(render, 'render_helper', side_effect=fake_render_helper):
            status, _ = render.render_one(self._video_info(self.ass),
                                          os.path.join(self.dir, 'out.mp4'))
        self.assertTrue(status)
        self.assertEqual(captured['danmaku'], self.ass)
        self.assertTrue(os.path.exists(self.ass), '原有 .ass 不能被删')


if __name__ == '__main__':
    unittest.main()
