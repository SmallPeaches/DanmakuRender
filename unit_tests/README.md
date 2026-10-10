# 测试说明（P0 基座）

本轮建立了**模块级测试**骨架，取代此前"只能跑全流程"的验证方式。

## 运行

仓库根目录，**零额外依赖**（只用标准库 `unittest`，本机未安装 pytest）：

```powershell
python -B -m unittest discover -s unit_tests -t . -v
```

若将来安装了 pytest，同一批用例可直接收集：

```powershell
python -m pytest unit_tests -v
```

> `-B` 用于避免本仓库 `__pycache__` 的写入权限问题（见 `TODO.md` B6）。

## 为什么目录叫 `unit_tests/` 而不是 `tests/`

⚠️ **不要改回 `tests/`**：根 `.gitignore` 第 5 行是 `/test**`，它会同时匹配到
`tests/` 目录（已用 `git check-ignore` 实测确认），导致：

- 整个测试目录对 git 不可见；
- `git clean -fdx` 会把这些测试文件**直接删除**。

git 无法用 `!` 例外把"已被排除目录里的文件"重新包含进来（实测 `!/tests/` 无效），
而放行它需要把 `/test**` 改成 `/test*` 再加 `!/tests/`，那会削弱 `/.`* 对仓库根的
忽略保护。因此选择 `unit_tests/` 这个不与该规则冲突的名字 —— **无需修改
`.gitignore`**。

## 目录结构

```
unit_tests/
├── __init__.py           使它成为包，支持 `from unit_tests.support import ...`
├── README.md             本文件
├── support.py            共享基座：路径设置、日志静音、fakes、DMRTestCase
├── test_liveevents.py    DMR/Task/liveevents.py 的状态机逻辑            (18)
├── test_events.py        ReplayTask 事件路由 + 事件表注册                (10)
├── test_engine.py        DMREngine 启动路径与目标分发                    (8)
├── test_repository.py    DMR/state/repository.py 状态仓储（P1）          (32)
├── test_state_reconciler.py  DMR/state/reconciler.py 启动对账（P1）      (32)
├── test_state_init.py    DanmakuRender 与状态库的接线（P1）              (9)
├── test_state_migration.py   产物 JSON 载荷与 v1→v2 迁移（P1）           (16)
├── test_liveevents_state.py  liveevents 与状态库的双写（P1）             (22)
├── test_stream_downloader_state.py  下载器场次/产物/中断登记（P1）        (10)
├── test_biliwebapi_video.py / test_biliuprs_video.py / test_uploader_group.py
│                         上传组稿件归属（P1）                 (11/10/15)
├── test_downloader_memory.py 下载引擎的内存上界与行为等价（F1）          (23)
├── test_xml2ass.py       XML→ASS 弹幕转换与渲染器 XML 兼容（F7）        (28)
├── test_virtual_downloader_danmaku.py  虚拟录制/离线渲染的弹幕查找（F7） (16)
├── test_runcmd_capture.py 输出捕获与 bufsize 清理（F2）                   (12)
├── test_ffmpeg_hls_window.py  HLS 行记录与 15 秒存活判定（F8）            (13)
├── test_douyu_cookies.py 斗鱼取流 cookies（解析/仅取流携带/登录态取流分支）(23)
├── test_biliwebapi_cookies.py 上传前重新读取 B 站 cookies（每次上传刷新）  (9)
└── _mem_flood_child.py   子进程辅助脚本（非测试用例，仅供上面那个文件调用）
```

测试文件命名跟随被测模块：`DMR/state/reconciler.py` → `test_state_reconciler.py`。

合计 **432 个用例**，约 33 秒跑完。

## 设计约定

| 约定 | 原因 |
|---|---|
| 不碰网络 / 磁盘 / 子进程 | 用例应在毫秒级跑完，可频繁执行 |
| 通过 `DMRTestCase.make_live_events()` 构造状态机 | 避免依赖 `__init__` 与线程 |
| 用 `FakeClock` 而非真实时间 | 72 小时超时等逻辑必须可控可测 |
| 状态库测试用 `:memory:` | 无需临时文件，互不干扰 |
| 对账测试注入假时长探测器 | 不需要真实媒体文件或 ffprobe |
| `drain_queue()` 带超时取队列 | 避免固定 `sleep` 造成不稳定 |

### 已知的例外：`test_downloader_memory.py`

⚠️ 这个文件**故意违反**"不碰子进程"的约定，因为它的验证对象就是**管道缓冲与队列
的内存上界**——用 fake 替身测不出这类问题（实测：`bufsize=10**8` 的 190 MB 只在
真实 `Popen` 后出现；队列膨胀只在真实子进程刷屏时出现）。为此：

- 用真实子进程，但进程数固定、总时长约 9 秒；
- 用假 ffmpeg（`_mem_flood_child.py`）而不是真 ffmpeg，**不需要网络与真实媒体文件**；
- 断言的是"**有上界**"这一契约（`qsize() <= 上限`），不是绝对内存数值 ——
  绝对数值会随机器与 Python 版本漂移，不适合做断言。

⚠️ **时钟必须锚定真实时间**：`DMR/state/repository.py` 用 `time.time()` 写
`updated_at`。若测试里把"当前时间"写死成一个未来的常数，所有产物都会被算成
"已过期"而误报失败。`test_state_reconciler.py` 与 `test_state_init.py` 都显式锚定
`time.time()`，改动时请勿退回常数。

## `@unittest.expectedFailure` 的含义

标记为 expected failure 的用例，断言的是**正确行为**，因此在缺陷存在期间失败。
- 套件整体（`OK (expected failures=N)`）仍然是绿的。
- **缺陷被修复后**，该用例会变成 `unexpected success`，unittest 报 FAILED —— 这是
  提醒我们回来去掉标记、正式锁定修复的信号。

## 已记录的缺陷（对应 `TODO.md`）

| 用例 | 缺陷 |
|---|---|
| `test_liveevents.TestUploadEmptyCandidates.test_non_realtime_no_candidates_no_raise` | B7.1 `_check_for_upload` 空候选列表 IndexError |
| `test_liveevents.TestCleanStatusAccounting.test_nonmatching_rule_must_not_mark_cleaned` | B7.2 无条件把状态改成 `cleaned` |
| `test_liveevents.TestCleanStatusAccounting.test_empty_clean_args_must_not_change_status` | B7.2 同上（`clean_args` 为空） |
| `test_events.TestEventRegistry.test_add_event_accumulates_handlers` | B7.3 `add_event` 覆盖导致 handler 丢失 |
| `test_events.TestEventRegistry.test_add_event_with_list_value_does_not_nest` | B7.3 list 值产生嵌套 handler |
| `test_engine.TestEngineStart.test_start_with_preloaded_plugin_is_not_idempotent` | B7.5 `engine.start()` 循环解包必然失败 |
| `test_engine.TestEngineStart.test_start_does_not_start_preloaded_plugins_twice` | B7.5 同上（且需避免重复启动） |
| `test_engine.TestEngineStart.test_start_with_preloaded_plugin_no_unpack_error` | B7.5 同上（等价记录） |

## 目录与命名约定

- 测试目录固定为 `unit_tests/`，**不要**改名为 `tests/`（原因见上）。
- 测试文件命名跟随被测模块：`DMR/state/reconciler.py` → `unit_tests/test_state_reconciler.py`。
- 新增功能时**不新建顶层目录**，并入已有功能模块；测试放入 `unit_tests/` 对应文件。

## 本轮刻意未做的事

- **没有修改任何生产代码**（P0 只加测试）。已确认缺陷的修复属于后续阶段。
- 没有引入 pytest / 断言库等依赖，以便在现有环境直接可跑。
- 尚未建立 `contract/`（每类插件实现的统一契约测试）与 `integration/`，
  它们依赖 P2/P3 的插件注册表与 Ports，见 `TODO.md` B8.3。
