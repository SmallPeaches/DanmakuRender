"""``dryrun.py`` 的便捷外壳：额外把日志落到一个**固定文件名**。

```powershell
python -B tools/_p1_dryrun_runner.py
```

``dryrun.py`` 自己已经配置了控制台与**按日期命名**的日志文件
（``logs/DMR-dryrun-YYYYMMDD.log``，同日多次运行会带 ``(1)``、``(2)`` 后缀）。
本外壳只多做一件事：把同一批日志再写一份到固定路径 ``logs/p1-dryrun.log``，
便于脚本/自动化按固定名字读取，不必去猜当天的文件名。

**它不做任何隔离**：``dryrun.py`` 按 ``--config``（默认 ``configs/global.yml``）
加载当前的全部任务配置，因此运行本外壳等同于运行 ``python dryrun.py``。
"""
import logging
import logging.handlers
import os
import runpy
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO_ROOT)
# dryrun.py 用 `from tools import check_pypi`，要求仓库根在 sys.path 上。
# 直接 `python dryrun.py` 时当前目录已在其中，但经 runpy 从 tools/ 启动时不在。
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
sys.path.append(os.path.join(REPO_ROOT, "tools"))

LOG_FILE = os.path.join("logs", "p1-dryrun.log")


def _setup_logging() -> None:
    os.makedirs("logs", exist_ok=True)
    logger = logging.getLogger("DMR")
    logger.setLevel(logging.DEBUG)

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter("[%(asctime)s][%(levelname)s]: %(message)s"))
    logger.addHandler(console)

    file_handler = logging.FileHandler(LOG_FILE, mode="w", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter("[%(asctime)s][%(module)s][%(levelname)s]: %(message)s")
    )
    logger.addHandler(file_handler)


if __name__ == "__main__":
    _setup_logging()
    print(f"日志将写入 {LOG_FILE}")
    print("正在启动 dryrun（180 秒后自动停止所有任务）...")
    # 以真实脚本执行，保证与手动运行 `python dryrun.py` 行为一致
    runpy.run_path("dryrun.py", run_name="__main__")
