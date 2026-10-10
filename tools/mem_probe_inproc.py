"""进程内内存诊断：不打断录制，随时打印内存快照与增长来源。

为什么要"进程内"
----------------
从外面 ``top``/``ps`` 只能看到总数，看不到**是谁占的** —— Python 对象、
C 扩展缓冲、线程栈、子进程都混在一起。而且有两个容易误判的点：

- ``gc.get_objects()`` **看不到 ``str``/``bytes``**（它们不被 GC 追踪），
  所以"整文件读入"这类问题用它是查不出来的；必须用 ``tracemalloc``。
- 大块内存**释放后一般会还给 OS**（实测 5×100MB 释放后 RSS 全额回落），
  因此"历史上分配过 190MB 缓冲"并不会永久抬高 RSS ——
  真正要看的是 ``tracemalloc`` 的**峰值**与**两次快照之间的增长**。

接入方式（不需要改录制逻辑）
----------------------------
1. 环境变量（推荐）::

       DMR_MEM_PROBE=1 python main.py            # 每 30 分钟打印一次
       DMR_MEM_PROBE=1 DMR_MEM_PROBE_INTERVAL=600 python main.py

   运行中随时手动触发::

       kill -USR1 <pid>      # 打印内存快照（含最大分配点与自上次以来的增长）
       kill -USR2 <pid>      # 先打印，再尝试 malloc_trim 回收堆空洞

2. 代码里显式安装::

       from tools.mem_probe_inproc import install
       install(interval=1800)
"""
from __future__ import annotations

import ctypes
import ctypes.util
import gc
import logging
import os
import signal
import sys
import threading
import time
from collections import Counter

__all__ = ['snapshot', 'memory_report', 'top_allocations', 'install', 'try_malloc_trim',
           'status', 'selftest']

logger = logging.getLogger(__name__)

_installed = False
_baseline = None          # 上一次快照，用于算增长
_tracer_started = False
_installed_at = None


def _banner(text: str) -> None:
    """把关键提示写到 stderr。

    只走 stderr 不走 logger：这是"日志没配好/看不到输出"时的兜底通道，
    同时写两处会导致重复打印。
    """
    try:
        sys.stderr.write(text + '\n')
        sys.stderr.flush()
    except Exception:
        pass


def _mib(nbytes) -> str:
    return f'{nbytes / 1024 / 1024:.1f}MB'


def _self_rss() -> int:
    try:
        import psutil
        return psutil.Process().memory_info().rss
    except Exception:
        return 0


def _ensure_tracer(depth: int = 10) -> bool:
    """启动 tracemalloc（带回溯），未启动时返回 False。"""
    global _tracer_started
    try:
        import tracemalloc
        if not tracemalloc.is_tracing():
            tracemalloc.start(depth)
        _tracer_started = True
        return True
    except Exception as e:
        logger.debug(f'tracemalloc 启动失败: {e}')
        return False


def try_malloc_trim() -> int:
    """把 glibc 堆里"已释放但未归还"的内存还给系统，返回归还字节数。

    仅 Linux/glibc 有效。注意：这**不是**主要优化手段 —— 实测大块释放后
    本来就会归还；只有碎片化留下的小空洞才需要它。
    """
    if not sys.platform.startswith('linux'):
        return 0
    before = _self_rss()
    try:
        gc.collect()
        libc = ctypes.CDLL(ctypes.util.find_library('c') or 'libc.so.6')
        libc.malloc_trim(0)
    except Exception as e:
        logger.debug(f'malloc_trim 失败: {e}')
        return 0
    return max(0, before - _self_rss())


def top_allocations(limit: int = 12, min_kb: int = 512) -> list:
    """当前占用最大的分配点（``tracemalloc`` 统计，带文件:行号）。

    这一项能直接指出"内存被哪一行代码占着"，例如
    ``find_danmaku_file`` 无关，而 ``streamgears.py:93`` 的
    ``logfile.read().decode(...)`` 就会以一个大块出现在这里。
    """
    if not _ensure_tracer():
        return []
    import tracemalloc
    snap = tracemalloc.take_snapshot()
    out = []
    for stat in snap.statistics('lineno'):
        if stat.size < min_kb * 1024:
            break
        frame = stat.traceback[0]
        out.append((os.path.basename(frame.filename), frame.lineno,
                    stat.size, stat.count))
        if len(out) >= limit:
            break
    return out


def snapshot() -> dict:
    """收集当前进程的内存快照（不打印）。"""
    gc.collect()
    data = {'rss': _self_rss(), 'threads': threading.active_count(),
            'time': time.time()}

    try:
        import psutil
        proc = psutil.Process()
        mi = proc.memory_info()
        data['vms'] = mi.vms
        try:
            data['uss'] = proc.memory_full_info().uss
        except Exception:
            data['uss'] = 0
        children, total = [], 0
        for ch in proc.children(recursive=True):
            try:
                cmi = ch.memory_info()
                total += cmi.rss
                children.append((ch.pid, ch.name(), cmi.rss))
            except Exception:
                continue
        data['children'], data['children_rss'] = children, total
    except Exception:
        data['vms'] = data['uss'] = data['children_rss'] = 0
        data['children'] = []

    if _ensure_tracer():
        import tracemalloc
        cur, peak = tracemalloc.get_traced_memory()
        data['py_cur'], data['py_peak'] = cur, peak
    else:
        data['py_cur'] = data['py_peak'] = 0

    return data


def memory_report(prefix: str = '[DMR-MEM]', reason: str = '',
                  with_allocations: bool = True) -> str:
    """打印一份可读的内存快照并返回文本。"""
    global _baseline
    d = snapshot()
    lines = [f'{prefix} === 内存快照 {time.strftime("%H:%M:%S")} {reason}'.rstrip()]
    lines.append(f'{prefix} RSS={_mib(d["rss"])} VMS={_mib(d.get("vms", 0))}'
                 + (f' USS={_mib(d["uss"])}' if d.get('uss') else '')
                 + f' 线程={d["threads"]}')

    if d['py_cur'] or d['py_peak']:
        lines.append(f'{prefix} Python堆 当前={_mib(d["py_cur"])} '
                     f'峰值={_mib(d["py_peak"])}')

    if _baseline is not None:
        dt = d['time'] - _baseline['time']
        drss = d['rss'] - _baseline['rss']
        dpy = d['py_cur'] - _baseline.get('py_cur', 0)
        lines.append(f'{prefix} 距上次 {dt/60:.1f} 分钟：'
                     f'RSS {drss/1024/1024:+.1f}MB  Python堆 {dpy/1024/1024:+.1f}MB'
                     + ('   ← 持续正增长，疑似泄漏' if dpy > 20 * 1024 * 1024 else ''))
    _baseline = d

    if d.get('children'):
        by_name = Counter(n for _, n, _ in d['children'])
        detail = ' '.join(f'{n}×{c}' for n, c in by_name.most_common(6))
        lines.append(f'{prefix} 子进程 {len(d["children"])} 个 合计RSS='
                     f'{_mib(d["children_rss"])}  ({detail})')
        for pid, name, rss in sorted(d['children'], key=lambda x: -x[2])[:4]:
            lines.append(f'{prefix}   pid={pid} {name} {_mib(rss)}')

    if with_allocations:
        allocs = top_allocations(limit=8)
        if allocs:
            lines.append(f'{prefix} 最大分配点（tracemalloc，可定位到代码行）：')
            for fname, lineno, size, cnt in allocs:
                lines.append(f'{prefix}   {_mib(size):>9} ×{cnt:<6} '
                             f'{fname}:{lineno}')

    text = '\n'.join(lines)
    for line in lines:
        logger.info(line)
    return text


def install(interval: int = 1800, prefix: str = '[DMR-MEM]') -> bool:
    """注册信号处理器与周期性趋势打印。

    ``SIGUSR1`` → 打印快照；``SIGUSR2`` → 打印快照并尝试 ``malloc_trim``。
    :param interval: 周期打印间隔（秒）；<=0 关闭周期打印。
    """
    global _installed, _installed_at
    if _installed:
        return True

    _ensure_tracer()
    registered = []
    pid = os.getpid()

    # 优先 SIGUSR1/SIGUSR2；没有（Windows）则退化为 SIGINT 之外的可用信号
    candidates = []
    for name in ('SIGUSR1', 'SIGUSR2'):
        sig = getattr(signal, name, None)
        if sig is not None:
            candidates.append((name, sig))

    if candidates:
        try:
            def _dump(_signum, _frame):
                memory_report(prefix, f'(信号 {_signum})')

            def _dump_and_trim(_signum, _frame):
                memory_report(prefix, f'(信号 {_signum} 前)')
                _banner(f'{prefix} malloc_trim 归还 {_mib(try_malloc_trim())}')

            # SIGUSR1 → 仅打印；SIGUSR2 → 打印 + 回收
            signal.signal(candidates[0][1], _dump)
            registered.append(candidates[0][0])
            if len(candidates) > 1:
                signal.signal(candidates[1][1], _dump_and_trim)
                registered.append(candidates[1][0])
        except (ValueError, OSError) as e:
            # ValueError: 不在主线程；OSError: 平台不支持
            _banner(f'{prefix} ⚠ 信号注册失败（{e}）—— kill -USR1 不会生效，'
                    f'请改用周期打印或直接调用 memory_report()')

    if interval and interval > 0:
        def _loop():
            while True:
                time.sleep(interval)
                try:
                    memory_report(prefix, '(周期)')
                except Exception as e:
                    logger.debug(f'内存快照失败: {e}')

        threading.Thread(target=_loop, daemon=True, name='dmr-mem-probe').start()

    _installed = True
    _installed_at = time.time()
    if registered:
        _banner(f'{prefix} 已启用（pid={pid}）：'
                f'kill -{registered[0].replace("SIG", "")} {pid} 打印快照'
                + (f'；kill -{registered[1].replace("SIG", "")} {pid} 打印并回收'
                   if len(registered) > 1 else '')
                + f'；周期={interval}s')
    else:
        _banner(f'{prefix} 已启用（pid={pid}）：本平台无 SIGUSR1/2，'
                f'只能靠周期打印（{interval}s）')
    return True


def status() -> str:
    """报告诊断是否已安装、注册了哪些信号 —— 用来判断 `kill -USR1` 该不该有输出。

    用法（在**录播进程内**执行，或作为排查第一步）::

        python -c "import sys; sys.path.insert(0,'.'); \\
                   from tools.mem_probe_inproc import status; print(status())"
    """
    lines = ['=== mem_probe 状态 ===']
    lines.append(f'  pid            : {os.getpid()}')
    lines.append(f'  已安装         : {_installed}'
                 + (f'（{time.time() - _installed_at:.0f} 秒前）' if _installed_at else ''))
    lines.append(f'  tracemalloc    : {_tracer_started}')
    got = []
    for name in ('SIGUSR1', 'SIGUSR2'):
        sig = getattr(signal, name, None)
        if sig is None:
            lines.append(f'  {name:<8}      : 本平台不存在')
            continue
        handler = signal.getsignal(sig)
        is_custom = callable(handler)
        lines.append(f'  {name:<8}      : '
                     + ('已注册自定义处理器 ✅' if is_custom else f'*** 未注册（{handler}）***'))
        got.append(name)
    if not got:
        lines.append('  本平台没有 SIGUSR1/SIGUSR2：Linux 上才有，'
                     '或者你连接的是 Windows。')
    elif not _installed:
        lines.append('  ⚠ 本进程**没有**调用过 install()：')
        lines.append('    - kill -USR1 不会有输出；')
        lines.append('    - 在 Linux 上 SIGUSR1 的**默认动作是终止进程**，')
        lines.append('      所以若进程仍存活，说明信号没送达（PID/命名空间问题）。')
        lines.append('    解决：重启时用 DMR_MEM_PROBE=1 启动，'
                     '或在代码里调用 install()。')
    return '\n'.join(lines)


def selftest() -> bool:
    """自检：自己给自己发一次 SIGUSR1，验证"信号 → 处理器 → 输出"整条链路。

    这是排查"kill 后没输出"最快的手段 —— 它区分了两种情况：

    - 自检能打印 → 链路正常，问题在**外部信号没送到**（PID 错、容器命名空间等）；
    - 自检不打印 → 处理器没注册或输出不可见。

    用法::

        python -c "import sys; sys.path.insert(0,'.'); \\
                   from tools.mem_probe_inproc import selftest; selftest()"
    """
    if not _installed:
        install(interval=0)
    sig = getattr(signal, 'SIGUSR1', None)
    if sig is None:
        _banner('本平台没有 SIGUSR1，无法做自检；改用直接调用验证：')
        memory_report(reason='(selftest 直接调用)')
        return True

    handler = signal.getsignal(sig)
    if not callable(handler):
        _banner(f'❌ SIGUSR1 未注册自定义处理器（当前={handler}）—— '
                f'install() 可能没执行或被覆盖。')
        return False

    _banner(f'自检：向自身 pid={os.getpid()} 发送 SIGUSR1，'
            f'下面应出现一条内存快照 …')
    os.kill(os.getpid(), sig)          # 只应在自检里这样用
    _banner('若上面**没有**出现快照，说明处理器未按预期执行。')
    return True


def _auto_install_from_env():
    if os.environ.get('DMR_MEM_PROBE', '').strip() in ('1', 'true', 'yes', 'on'):
        try:
            interval = int(os.environ.get('DMR_MEM_PROBE_INTERVAL', '1800'))
        except ValueError:
            interval = 1800
        install(interval=interval)


_auto_install_from_env()


if __name__ == '__main__':
    import argparse

    logging.basicConfig(level=logging.INFO, format='%(message)s')
    parser = argparse.ArgumentParser(description='进程内内存诊断')
    parser.add_argument('--status', action='store_true',
                        help='报告诊断是否已安装、注册了哪些信号')
    parser.add_argument('--selftest', action='store_true',
                        help='自检：给自己发一次 SIGUSR1，验证信号链路')
    parser.add_argument('--report', action='store_true', help='直接打印一次内存快照')
    parser.add_argument('--interval', type=int, default=0,
                        help='周期打印间隔（秒）；配合 --report 前先 install')
    args = parser.parse_args()

    if args.status:
        print(status())
    elif args.selftest:
        selftest()
    elif args.report:
        install(interval=args.interval)
        print(memory_report(with_allocations=True))
    else:
        install(interval=args.interval)
        print(status())
        print()
        print(memory_report())
