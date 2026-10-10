"""P1 全流程测试运行器：下载 → 渲染 → 上传 → 清理。

与 ``dryrun.py`` 的区别：``dryrun.py`` 刻意**禁止真实上传**（测试状态持久化用）。
本运行器用于**验证完整链路**，需要用户明确授权，因此独立成一个工具。

```powershell
# 默认：5 分钟分段、录 3 个分段
python -B tools/_p1_fullflow_runner.py

# 自定义
python -B tools/_p1_fullflow_runner.py --url https://live.bilibili.com/xxx \
    --segment 300 --segments 3 --duration 1020 --publish-delay 86400
```

设计要点
--------
1. **隔离配置**：以用户 ``global.yml`` 的**原始内容**为基底生成临时全局配置，
   ``config_path`` 指向只含本测试任务的目录，避免把用户其他任务一并录制。
2. **隔离状态库**：使用独立的 ``logs/dmr_state_fullflow.db``，不污染正式状态库。
3. **清理是 move 而非 delete**：把文件移到单独目录，既能验证清理链路，
   又不会真正删除数据。可用 ``--clean-method`` 覆盖。
4. **延迟发布**：默认 ``dtime`` 设为 24 小时，测试稿件不会立即公开。
5. 到点后发 ``stoptask`` 走**正常停止流程**，使 ``liveend`` → 上传 → 清理
   这条链路能真正跑完（而不是直接杀进程）。
"""
import argparse
import logging
import os
import sys
import time

import yaml

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO_ROOT)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
sys.path.append(os.path.join(REPO_ROOT, "tools"))

from DMR import DanmakuRender
from DMR.Config import Config
from DMR.utils import PipeMessage

TASK_NAME = "fullflow"
STATE_DB = "logs/dmr_state_fullflow.db"
LOG_FILE = "logs/p1-fullflow.log"


def _setup_logging(level: int = logging.DEBUG) -> None:
    os.makedirs("logs", exist_ok=True)
    logger = logging.getLogger("DMR")
    logger.setLevel(logging.DEBUG)
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter("[%(asctime)s][%(levelname)s]: %(message)s"))
    logger.addHandler(console)
    fh = logging.FileHandler(LOG_FILE, mode="w", encoding="utf-8")
    fh.setLevel(level)
    fh.setFormatter(logging.Formatter(
        "[%(asctime)s][%(module)s][%(levelname)s]: %(message)s"))
    logger.addHandler(fh)


def _build_task(args) -> dict:
    """构造测试任务的 download/render/upload/clean 参数。"""
    download_args = {
        "dltype": "live",
        "url": args.url,
        "output_dir": args.output_dir,
        "output_name": ("{STREAMER.NAME}-{CTIME.YEAR}年{CTIME.MONTH:02d}月"
                        "{CTIME.DAY:02d}日{CTIME.HOUR:02d}点{CTIME.MINUTE:02d}分-{TITLE}"),
        "segment": args.segment,
        "engine": args.engine,
        "danmaku": True,
        "video": True,
        "stop_wait_time": 2,
        "output_format": args.output_format,
        "stream_option": {"stream_cdn": args.stream_cdn, "stream_type": args.stream_type},
        "advanced_video_args": {
            "group_id": None,
            "restart_interval": [0, 5, 10],
            "max_fn_length": 80,
            "min_video_size": 1,
        },
        "dm_format": "ass",
        "dm_filter": {"dm_type": "danmaku", "keywords": None,
                      "username": None, "max_length": 0},
    }

    render_args = {
        "dmrender": {
            "output_dir": None,
            "output_name": None,
            "format": "mp4",
            "hwaccel_args": None,
            "vencoder": args.vencoder,
            "vencoder_args": args.vencoder_args,
            "aencoder": "aac",
            "aencoder_args": ["-b:a", "128K"],
            "output_resize": None,
        }
    }

    upload_args = {
        "src_video": {
            "target": "bilibili",
            "engine": args.upload_engine,
            "account": args.account,
            "cookies": None,
            "retry": 1,
            "realtime": True,
            # 小于分段时间，确保每个分段都会被上传（本次就是要验证上传链路）
            "min_length": args.min_length,
            "limit": 3,
            "copyright": 1,
            "source": "",
            "tid": 65,
            "cover": "",
            "title": ("[全流程测试/{STREAMER.NAME}] {TITLE} "
                      "{CTIME.YEAR}年{CTIME.MONTH:02d}月{CTIME.DAY:02d}日"),
            "desc": "DanmakuRender P1 全流程测试，可自行删除。",
            "dynamic": "{STREAMER.NAME} 的全流程测试",
            "tag": "直播回放",
            # 延迟发布：测试稿件不会立即公开
            "dtime": args.publish_delay,
            "dolby": 0,
            "no_reprint": 1,
            "open_elec": 0,
        }
    }

    clean_args = {
        "src_video": {
            "method": args.clean_method,
            "dest": args.clean_dest,
            # 立即清理（0 秒延迟），以便在测试窗口内验证清理链路
            "delay": args.clean_delay,
            "w_srcfile": False,
            "w_srcpre": True,
        }
    }

    return {
        "common_event_args": {
            "auto_render": 1,
            "auto_upload": 1,
            "auto_clean": 1,
            "auto_transcode": 0,
        },
        "download_args": download_args,
        "render_args": render_args,
        "upload_args": upload_args,
        "clean_args": clean_args,
    }


def _build_global_config(args) -> str:
    """以用户配置为基底生成测试用全局配置，返回其路径。"""
    with open(args.config, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    task_dir = os.path.join(args.workdir, "configs")
    os.makedirs(task_dir, exist_ok=True)
    task_path = os.path.join(task_dir, f"DMR-{TASK_NAME}.yml")
    with open(task_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(_build_task(args), f, allow_unicode=True, sort_keys=False)

    raw.setdefault("dmr_engine_args", {})
    raw["dmr_engine_args"]["config_path"] = task_dir
    raw["state"] = {"db_path": STATE_DB}
    raw["recovery"] = {"on_interrupted_file": "ask"}

    out_path = os.path.join(args.workdir, "fullflow-global.yml")
    with open(out_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(raw, f, allow_unicode=True, sort_keys=False)
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/global.yml",
                        help="用户的全局配置（作为基底，不会改动它）")
    parser.add_argument("--url", default="https://live.bilibili.com/1773507572")
    parser.add_argument("--segment", type=int, default=300, help="分段时间（秒）")
    parser.add_argument("--engine", default="ffmpeg",
                        choices=["auto", "ffmpeg", "streamgears", "streamlink", "pyrequests"],
                        help="录制引擎；auto 会按平台规则选择（B站flv通常落到streamgears）")
    parser.add_argument("--stream-type", default=None,
                        help="指定流类型，例如 hls / fmp4 / ts-avc / flv-avc；留空按默认规则")
    parser.add_argument("--stream-cdn", default=None, help="指定 CDN 关键字，例如 gotcha104")
    parser.add_argument("--output-format", default="flv",
                        help="录制文件容器（HLS 建议 ts 或 mp4）")
    parser.add_argument("--segments", type=int, default=3, help="期望录制的分段数")
    parser.add_argument("--duration", type=float, default=None,
                        help="总运行时长（秒）；默认为 segment*(segments+1)+120")
    parser.add_argument("--workdir", default=".fullflow")
    parser.add_argument("--output-dir", default="./全流程测试回放")
    parser.add_argument("--clean-method", default="move",
                        choices=["move", "copy", "delete", "custom"])
    parser.add_argument("--clean-dest", default="./全流程测试-已清理")
    parser.add_argument("--clean-delay", type=int, default=0)
    parser.add_argument("--publish-delay", type=int, default=86400,
                        help="延迟发布秒数；0 表示立即发布")
    parser.add_argument("--account", default="bili-xiaohao")
    parser.add_argument("--upload-engine", default="biliwebapi",
                        choices=["biliwebapi", "biliuprs"])
    parser.add_argument("--min-length", type=int, default=10)
    parser.add_argument("--vencoder", default="h264_nvenc",
                        help="渲染视频编码器；失败可改为 libx264")
    parser.add_argument("--vencoder-args", nargs="*",
                        default=["-b:v", "15M"])
    parser.add_argument("--no-stop", action="store_true",
                        help="不自动停止（手动 Ctrl+C）")
    args = parser.parse_args()

    duration = args.duration
    if duration is None:
        duration = args.segment * (args.segments + 1) + 120

    os.makedirs(args.workdir, exist_ok=True)
    _setup_logging()

    print("=" * 70)
    print(f"全流程测试：{args.url}")
    print(f"  分段时间      : {args.segment}s")
    print(f"  录制引擎      : {args.engine}")
    print(f"  流类型/CDN    : {args.stream_type or '默认'} / {args.stream_cdn or '默认'}")
    print(f"  输出容器      : {args.output_format}")
    print(f"  期望分段数    : {args.segments}")
    print(f"  预计运行时长  : {duration:.0f}s ({duration/60:.1f} 分钟)")
    print(f"  上传          : {args.upload_engine} -> {args.account}"
          f"（延迟发布 {args.publish_delay}s）")
    print(f"  清理          : {args.clean_method} -> {args.clean_dest}")
    print(f"  状态库        : {STATE_DB}")
    print(f"  日志          : {LOG_FILE}")
    print("=" * 70)

    config = Config(_build_global_config(args))
    print(f"已加载任务: {config.get_replaytasks()}")

    dmr = DanmakuRender(config)
    dmr.start()

    try:
        print(f"开始录制，{duration:.0f} 秒后停止任务以触发上传与清理 ...")
        time.sleep(duration)
        print("到时，正在停止任务（走正常停止流程，以便完成上传与清理）...")
        for taskname in list(dmr.engine.task_dict.keys()):
            dmr.engine.pipeSend(PipeMessage(
                source="fullflow", target="downloader",
                event="stoptask", dtype="str", data=taskname,
            ))
        # 给上传与清理留出时间
        print("等待上传与清理完成（300 秒）...")
        time.sleep(300)
    except KeyboardInterrupt:
        print("收到中断，正在停止 ...")
    finally:
        dmr.stop()
        print("测试运行结束。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
