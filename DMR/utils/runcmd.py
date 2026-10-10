import subprocess
import time
import os
import tempfile

__all__ = ['runcmd', 'run_and_capture_output']

class runcmd():
    @staticmethod
    def runcmd(cmd:list, wait=True, timeout=None, **kwargs):
        shell = isinstance(cmd, str)
        if not shell:
            _cmd = [str(x) for x in cmd]
        p = subprocess.Popen(_cmd, shell=shell, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kwargs)
        if wait:
            p.wait(timeout=timeout)
        return p


def _output_tempfile(filename=None, dir=None):
    """优先用仓库约定的 ``.temp`` 目录，不可用时退回系统临时目录。"""
    candidates = []
    if dir:
        candidates.append(dir)
    else:
        candidates.extend(['.temp', None])
    for candidate in candidates:
        try:
            if candidate:
                os.makedirs(candidate, exist_ok=True)
            return tempfile.TemporaryFile(dir=candidate, prefix=filename or 'runcmd_')
        except OSError:
            continue
    return tempfile.TemporaryFile()


def run_and_capture_output(cmd:list, timeout:float=None, wait:bool=True,
                           decode:bool=True, filename:str=None, **kwargs) -> tuple:
    """执行子进程并返回 ``(合并输出, 退出码)``，不占内存也不死锁。

    为什么不用 ``stdout=subprocess.PIPE`` + ``proc.wait()``：

    1. 子进程写入量超过操作系统管道缓冲（Windows 约 64KB）时会**死锁** —— 子进程
       阻塞在写管道，父进程阻塞在 ``wait()``，而那段输出要等到 ``wait()`` 返回后才
       被读取。登录类命令（``biliup login``/``renew``）的输出正好可能超过这个量。
    2. ``bufsize=10**8`` 解决不了上面的问题（刷新仍发生在 ``wait()`` 之后），却会
       让每个子进程额外预留上百 MB 的缓冲内存。

    改成把输出重定向到**临时文件**后，子进程写文件不会被阻塞，``communicate()``
    负责收尾与回收，最后从文件读回字符串。

    :returns: ``(output, returncode)``。超时时进程被强杀，退出码为平台相关的
        非 0 值（Windows 上为 1），调用方的 ``returncode != 0`` 判定仍然成立。
    :param wait: 是否等待子进程结束（``False`` 时返回 ``('', None)``）。
    :param decode: 是否把输出解码为 ``str``。原调用方都会 ``.decode()``，
        保持 True 以避免下游对 bytes 调用 ``.lower()`` 这类隐蔽错误。
    """
    if not wait:
        subprocess.Popen([str(x) for x in cmd], **kwargs)
        return '', None

    with _output_tempfile(filename=filename) as logfile:
        proc = subprocess.Popen(
            [str(x) for x in cmd],
            stdin=kwargs.pop('stdin', subprocess.DEVNULL),
            stdout=logfile,
            stderr=subprocess.STDOUT,
            **kwargs
        )
        try:
            proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
        logfile.seek(0)
        out = logfile.read()
    return (out.decode('utf-8', errors='ignore') if decode else out), proc.returncode
