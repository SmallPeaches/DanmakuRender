"""``DMR/utils/runcmd.py`` 的输出捕获与 ``bufsize`` 清理的回归测试（F2）。

背景（实测数据见 ``TODO.md`` F1/F2）：

- ``bufsize=10**8`` 会让 Python 为**每个子进程**预留约 190 MB 缓冲；
- 当 ``stdout`` 是文件对象或 ``sys.stdout`` 时，Python 根本不会分配该缓冲 ——
  这个参数纯属无效（4 处，已直接删除）；
- 当 ``stdout=subprocess.PIPE`` 且随后才 ``wait()`` + ``read()`` 时，子进程输出超过
  操作系统管道缓冲（Windows 约 64KB）会**死锁**，而 ``bufsize`` 解决不了它
  （刷新发生在 ``wait()`` 之后）—— 4 处改成临时文件 + ``communicate()``。
"""
from __future__ import annotations

import inspect
import os
import subprocess
import sys
import tempfile
import time
import unittest

from unit_tests.support import DMRTestCase

#: 这4个模块原先用 PIPE + bufsize=10**8，现已改走共用捕获函数
PIPE_CAPTURE_MODULES = [
    'DMR/utils/logintools.py',
    'DMR/Uploader/biliuprs.py',
]
#: 这4个模块的 stdout 不是管道，bufsize 本来就是无效参数
FILE_REDIRECT_MODULES = [
    'DMR/Render/ffmpeg.py',
    'DMR/Downloader/streamgears.py',
]
ALL_TOUCHED = PIPE_CAPTURE_MODULES + FILE_REDIRECT_MODULES
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestNoHugeBufsizeLeft(DMRTestCase):
    """全仓库不应再出现 ``bufsize=10**8``（注释与字符串里提到不算）。"""

    @staticmethod
    def _code_text(path: str) -> str:
        """只保留真正的代码 token，剔除注释与字符串字面量。

        用 ``tokenize`` 而不是"按 # 切"：本次的说明文字同时出现在行注释与
        docstring 里，简单切分会把两者混淆，导致用例要么误报、要么漏报。
        """
        import io
        import tokenize

        pieces = []
        with open(path, 'rb') as handle:
            for tok in tokenize.tokenize(handle.readline):
                if tok.type in (tokenize.COMMENT, tokenize.STRING,
                                tokenize.NL, tokenize.NEWLINE, tokenize.INDENT,
                                tokenize.DEDENT, tokenize.ENCODING):
                    continue
                pieces.append(tok.string)
        return ' '.join(pieces)

    def _iter_py(self):
        for root, _dirs, files in os.walk(_REPO_ROOT):
            if '__pycache__' in root or os.sep + '.git' in root:
                continue
            for name in files:
                if name.endswith('.py'):
                    yield os.path.join(root, name)

    def test_no_code_contains_huge_bufsize(self):
        offenders = []
        for path in self._iter_py():
            rel = os.path.relpath(path, _REPO_ROOT)
            if rel.startswith('unit_tests' + os.sep):
                continue          # 测试自身会在字符串里引用该模式
            if 'bufsize=10**8' in self._code_text(path):
                offenders.append(rel)
        self.assertEqual(offenders, [], f'仍有未清理的巨额 bufsize: {offenders}')

    def test_touched_modules_do_not_pass_bufsize_kwarg(self):
        """被改的 4 个模块不应再把它作为**参数**传给 Popen。"""
        offenders = [rel for rel in ALL_TOUCHED
                     if 'bufsize' in self._code_text(os.path.join(_REPO_ROOT, rel))]
        self.assertEqual(offenders, [], f'这些模块仍在代码里用 bufsize: {offenders}')

    def test_pipe_capture_modules_use_shared_helper(self):
        """原先 PIPE+read 的两处必须改用共用捕获函数（否则死锁风险还在）。"""
        for rel in PIPE_CAPTURE_MODULES:
            with open(os.path.join(_REPO_ROOT, rel), encoding='utf-8') as handle:
                src = handle.read()
            self.assertIn('run_and_capture_output', src, f'{rel} 应使用共用捕获函数')


class TestRunAndCaptureOutput(DMRTestCase):

    def _run(self, code, **kwargs):
        from DMR.utils import run_and_capture_output
        return run_and_capture_output([sys.executable, '-B', '-c', code], **kwargs)

    def test_captures_stdout_and_stderr(self):
        out, rc = self._run('import sys; print("OUT"); print("ERR", file=sys.stderr)')
        self.assertEqual(rc, 0)
        self.assertIn('OUT', out)
        self.assertIn('ERR', out)

    def test_detects_error_text_in_lowercase(self):
        """登录判定依赖 ``'error' in out.lower()``，必须能看到输出。"""
        out, _ = self._run('print("ERROR: invalid cookie")')
        self.assertIn('error', out.lower())

    def test_preserves_nonzero_returncode(self):
        _out, rc = self._run('import sys; sys.exit(3)')
        self.assertEqual(rc, 3)

    def test_handles_output_far_larger_than_pipe_buffer(self):
        """核心：2MB 输出必须能读完 —— 原 PIPE+wait 写法在此会死锁。

        Windows 管道缓冲约 64KB，这里写 20000 行（约 2MB）。
        """
        out, rc = self._run(
            'for i in range(20000): print("line %d %s" % (i, "x" * 100))',
            timeout=120)
        self.assertEqual(rc, 0)
        self.assertEqual(out.count('\n'), 20000)

    def test_timeout_kills_and_reports_failure(self):
        start = time.time()
        _out, rc = self._run('import time; time.sleep(30)', timeout=1)
        self.assertLess(time.time() - start, 15, '超时后应立即返回')
        self.assertNotEqual(rc, 0, '超时被强杀应体现为非 0 退出码')

    def test_does_not_leave_temp_files(self):
        from DMR.utils import run_and_capture_output
        import glob

        marker = 'dmr_runcmd_test_'
        patterns = [os.path.join(_REPO_ROOT, '.temp', marker + '*'),
                    os.path.join(tempfile.gettempdir(), marker + '*')]
        run_and_capture_output([sys.executable, '-B', '-c', 'print(1)'], filename=marker)
        for pattern in patterns:
            self.assertEqual(glob.glob(pattern), [], f'临时文件未清理: {pattern}')

    def test_wait_false_does_not_capture(self):
        from DMR.utils import run_and_capture_output

        # 用立即退出的命令：本用例只验证"不等待、不捕获"的返回约定，
        # 留一个 sleeping 子进程会产生 ResourceWarning 并拖慢用例。
        out, rc = run_and_capture_output(
            [sys.executable, '-B', '-c', 'pass'], wait=False)
        self.assertEqual(out, '')
        self.assertIsNone(rc)

    def test_empty_output(self):
        out, rc = self._run('pass')
        self.assertEqual(rc, 0)
        self.assertEqual(out, '')


class TestOldPatternWouldDeadlock(DMRTestCase):
    """反向验证：证明这4处确实有死锁风险，不是"顺手改改"。

    用子进程跑一段"旧写法"的代码（PIPE + wait + read，且输出 2MB），
    并加超时——旧写法应当超时，而新写法能读完。
    """

    OLD_CODE = (
        'import subprocess, sys\n'
        'p = subprocess.Popen([sys.executable, "-B", "-c",\n'
        '    "for i in range(20000): print(\'line %d %s\' % (i, \'x\'*100))"],\n'
        '    stdin=subprocess.PIPE, stdout=subprocess.PIPE,\n'
        '    stderr=subprocess.STDOUT, bufsize=10**8)\n'
        'p.wait()\n'                      # ← 死锁点：wait 在 read 之前
        'out = p.stdout.read()\n'
        'print("READ", len(out))\n'
    )

    def test_old_pattern_deadlocks_but_new_one_does_not(self):
        # 旧写法：wait() 在 read() 之前，2MB 输出会塞满管道 → 卡死到超时。
        # 输出重定向到 devnull，避免为"故意卡死的演示"再留下一层管道与孙进程。
        proc = subprocess.Popen([sys.executable, '-B', '-c', self.OLD_CODE],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            with self.assertRaises(subprocess.TimeoutExpired):
                proc.wait(timeout=5)
        finally:
            proc.kill()
            proc.wait()

        # 新写法：同样 2MB 输出，能完整读回
        from DMR.utils import run_and_capture_output
        out, rc = run_and_capture_output(
            [sys.executable, '-B', '-c',
             'for i in range(20000): print("line %d %s" % (i, "x" * 100))'],
            timeout=60)
        self.assertEqual(rc, 0)
        self.assertEqual(out.count('\n'), 20000)


if __name__ == '__main__':
    unittest.main()
