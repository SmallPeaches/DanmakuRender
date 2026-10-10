"""子进程辅助脚本：狂刷日志行 / 模拟 ffmpeg 分段落盘。

只被 ``test_downloader_memory.py`` 通过子进程调用，不属于生产代码。
用法:
  python -B unit_tests/_mem_flood_child.py [行数]        # 狂刷进度行
  python -B unit_tests/_mem_flood_child.py --segments    # 模拟分段 Opening
"""
import os
import sys
import time

LIMIT = 0
MODE = 'flood'
if '--segments' in sys.argv:
    MODE = 'segments'
    _rest = [a for a in sys.argv[1:] if a != '--segments']
    LIMIT = int(_rest[0]) if _rest else 3
elif len(sys.argv) > 1:
    LIMIT = int(sys.argv[1])

# 固定长行：模拟 ffmpeg -stats 的进度输出
PAD = 'x' * 512


def flood():
    i = 0
    while True:
        i += 1
        sys.stdout.write('frame=%d fps=60 time=00:00:%02d.%02d bitrate=8000kbits/s speed=1.0x %s\n'
                         % (i, i % 60, i % 100, PAD))
        sys.stdout.flush()
        if LIMIT and i >= LIMIT:
            break
        time.sleep(0.001)


def segments():
    """模拟 ffmpeg 的 -f segment：每 2 秒切换到下一个文件并打印 Opening 行。"""
    out = os.environ.get('PROBE_OUT', '.')
    for i in range(1, LIMIT + 1):
        path = os.path.join(out, f'seg-{i}.mp4').replace('\\', '/')
        sys.stdout.write(f"Opening '{path}' for writing\n")
        sys.stdout.flush()
        with open(path, 'wb') as f:
            f.write(b'\x00' * 128)
        time.sleep(2)
    # 保持存活，模拟录制仍在进行
    time.sleep(5)


if __name__ == '__main__':
    if MODE == 'segments':
        segments()
    else:
        flood()
