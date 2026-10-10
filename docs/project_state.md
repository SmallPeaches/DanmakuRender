# 项目当前状态 — DanmakuRender-5

> **面向开发者。** 本文件是**当前状态快照**，会随代码演进被改写；
> 历史细节与踩坑记录以 [维护记录](maintainer-log.md) 为准。
>
> 相关文档：[更新说明](CHANGELOG.md) ·
> [维护记录](maintainer-log.md) ·
> [待办清单](TODO.md) ·
> [测试说明](../unit_tests/README.md) ·
> [返回 README](../README.md)
>
> 生成方式：实际阅读源码 + 只读运行验证，未修改任何代码。
> 对应仓库状态：分支 `v5`，HEAD `2eb6080`（与 `origin/v5` 一致），工作区有未提交改动。

---

## 1. 项目是什么

**DanmakuRender-5**：Python 直播录制工具，录制纯净直播流 + 弹幕，支持本地预览、自动渲染弹幕到视频、多任务并发录制、自动上传 B 站/YouTube。

- 入口：`main.py`（常驻录制）、`dryrun.py`（测试用，180 秒后自动停任务）、`render_only.py`（对已有文件离线渲染/转码）
- 版本号：`main.py` 中 `VERSION = '2026.05.01'`
- 运行环境：Python 3.11.0（本机），依赖见 `requirements.txt`，已全部安装

---

## 2. 目录与模块职责

```
DMR/                        核心代码
├── __init__.py             DanmakuRender 主类：装配引擎、加载插件与任务、配置热更新、.temp 清理
├── engine.py               DMREngine：插件/任务注册与 PipeMessage 路由（所有跨模块通信的中枢）
├── Config/
│   ├── __init__.py         Config：default.yml + global.yml 合并、任务配置加载、文件哈希变更检测
│   └── default.yml         配置基准（470 行），含全部可配置项与注释
├── Task/
│   ├── baseevents.py       事件基类
│   ├── liveevents.py       直播任务状态机：livestart → livesegment → render → upload → clean
│   └── replaytask.py       任务包装，进程内收发消息
├── Downloader/
│   ├── __init__.py         Downloader 插件：按 dltype 分发 live/videos/virtual 三类任务
│   ├── stream_downloader.py 直播录制主流程（含 danmaku/video 双线程、分段、重连、最小文件过滤）
│   ├── sync_stream_downloader.py  边录边传（streamlink + biliwebapi）
│   ├── ffmpeg.py / streamgears.py / streamlink.py / pyrequests.py   四种拉流引擎
│   ├── video_downloader.py / ytdlp.py / yutto.py    视频搬运下载
│   ├── virtual_downloader.py  监控文件夹当直播处理（虚拟录制）
│   ├── streamlink_sync.py   同步流下载实现
│   └── Danmaku/
│       ├── danmaku.py      DanmakuDownloader：驱动 DanmakuClient、过滤、分段、写 ASS
│       └── asswriter.py    ASS 字幕写出与弹幕排布
├── LiveAPI/
│   ├── __init__.py         LiveAPI 包装类（GetStreamURL/GetRoomInfo/Onair…）
│   ├── BaseAPI.py          平台 API 抽象基类；get_stream_url 默认从 get_stream_urls 随机取
│   ├── bilibili.py / douyu.py / huya.py / douyin.py / cc.py / twitch.py / defaultapi.py
│   ├── bilivideo.py / bilivideo_utils.py   B站视频（WBI 签名）相关
│   ├── abogus.py           抖音 a_bogus 签名
│   ├── huya_wup/           虎牙 WUP 协议（wup.py + packet/ + wup_struct/）
│   ├── tars/               虎牙 TARS RPC 客户端
│   └── danmaku/            弹幕 WebSocket 实现
│       ├── __init__.py     DanmakuClient：site_class（类方法）/ site_class_v3（实例方法，可带配置）
│       ├── DMAPI.py        弹幕 API 抽象基类（要求 heartbeat / get_ws_info / decode_msg）
│       ├── bilibili.py / douyu.py / huya.py / cc.py / twitch.py / youtube.py
│       └── douyin/         抖音弹幕（protobuf + 参数签名）
├── Render/
│   ├── __init__.py         Render 插件：ThreadPoolExecutor、失败任务持久化到 .temp/failed_renders.json
│   ├── baserender.py       渲染基类
│   ├── dmrender.py         弹幕渲染主要实现
│   ├── transcode.py        转码
│   └── ffmpeg.py           ffmpeg 调用封装
├── Uploader/
│   ├── __init__.py         Uploader 插件：上传组复用、重试、失败持久化 .temp/failed_uploads.json
│   ├── biliuprs.py         调用 biliup-rs 子进程
│   ├── biliwebapi.py       B站 Web API 上传（自实现）
│   ├── youtubev3.py        YouTube Data API v3
│   └── subprocess_uploader.py  自定义命令上传
├── Cleaner/
│   ├── __init__.py         Cleaner 插件：copy/move/delete/custom，支持 delay
│   ├── copy.py / move.py / delete.py
├── WebService/
│   ├── __init__.py         WebService 插件（默认未启用）
│   └── webapi.py           Flask 应用：/login、/api/put_message、/tasks、/config 增删改、失败重试
└── utils/
    ├── __init__.py         汇总导出
    ├── dataclass.py        PipeMessage / StreamerInfo / StreamInfo / FileInfo / VideoInfo
    ├── utils.py            通用函数（replace_keywords、split_url、merge_dict、cookiestr2dict…）
    ├── ffmpeg.py / ffprobe.py   工具封装（时长、分辨率探测）
    ├── danmaku.py          弹幕数据类（SimpleDanmaku / GiftDanmaku / EntryDanmaku / SuperChatDanmaku）
    ├── runcmd.py           子进程调用
    ├── logintools.py       登录信息读写
    └── toolsmgr.py         ffmpeg/biliup 工具自动查找与下载

configs/                    录制配置（DMR-**.yml 才会被当作任务加载）
tools/                      check_env.py（依赖检查/自动安装）、check_update
docs/                       installation.md、usage.md
.login_info/                登录凭据（bili-xiaohao.json、.bili_watch_cookies.json、cookies.json…）
```

---

## 3. 架构与关键数据流

### 3.1 引擎与消息

`DMREngine` 持有 `plugin_dict`（downloader/render/uploader/cleaner/webservice）与 `task_dict`（每个录制任务一个 `ReplayTask`）。所有组件不直接互相调用，统一通过 `PipeMessage(source, target, event, request_id, dtype, data)` 投递到 `recv_queue`，由 `DMREngine._pipeRecvMonitor` 路由：

- `target == 'engine'` → 引擎自己处理（`addtask` / `deltask` / `info`）
- `target == 'replay/<taskname>'` → 投递给对应任务的 `send_queue`
- `target in {'render','uploader','cleaner','downloader'}` → 投递给对应插件

### 3.2 配置合并（**改配置项必须看这里**）

```
DMR/Config/default.yml   (基准，必须在这里定义键才能被用户配置覆盖)
        │  merge_dict(default, user_global)
        ▼
configs/global.yml       (用户全局覆盖)
        │  Config.add_task_config()：按 dltype 取 download_args.<dltype> 深拷贝，
        │  再用任务文件 configs/DMR-*.yml 的 download_args 覆盖
        ▼
ReplayTask.config  →  liveevents.onReady() 把 config['download_args'] 发给 downloader
```

任务配置只对 `common_event_args` 中 `auto_render` / `auto_upload` / `auto_clean` 为真的部分装载 `render_args` / `upload_args` / `clean_args`。

### 3.3 直播录制数据流

```
StreamDownloadTask.start_helper()         并发循环，检测开播/下播、自动重连
  └─ start_once()
       ├─ liveapi.GetStreamURL(**stream_option)   ← config.download_args.live.stream_option
       ├─ danmaku_thread(): DanmakuDownloader(... **kwargs)
       │       └─ DanmakuClient(url, q, **dm_stream_option)   ← config.download_args.live.dm_stream_option
       │            └─ 平台 get_ws_info(url, **kwargs) → 弹幕 WS
       ├─ video_thread(): {FFmpeg|Streamgears|Streamlink|PyRequests}Downloader
       └─ segment_callback() → 分段落盘、按 min_video_size/min_video_duration 过滤、
                               发 `livesegment` 消息给 LiveEvents
```

`LiveEvents.onLiveSegment()` 依据 `auto_transcode` / `auto_render` / `auto_upload` 生成后续 `render` / `uploader` 消息，并用 `state_dict[group_id]` 跟踪每个分段的生命周期（待渲染 → 待上传 → 已上传 → 已清理）。

### 3.4 弹幕客户端两种形态（**加平台参数时的关键约束**）

- `site_class`：`DanmakuClient` 直接用类对象，`get_ws_info(url, **kwargs)` 上的 **类方法/静态方法**；`headers` 通过 `getattr(self.__site_api, 'headers', {})` 取。
- `site_class_v3`：`DanmakuClient` 会 **实例化** `site_class_v3.get(platform)(**kwargs)`，因此平台类可以在 `__init__` 里接收来自 `dm_stream_option` 的配置（抖音 `Douyin.__init__(douyin_dm_cookies)` 即此模式）。

bilibili/douyu/huya/cc/twitch 弹幕目前都在 `site_class`（类方法）里，因此它们的 `get_ws_info` 只能靠 `**kwargs` 拿参数。

### 3.5 产物（src_video / dm_video）语义 —— **已核实，易误解，务必按此理解**

程序对内使用三个"产物槽位"，其真实关系是**替代（alternatives）而非串联（chain）**：

```
原始录制流  = src_video_pre        ← 录制直接产出，未转码
     ├─ (transcode) ─→ src_video   ← 转码结果，**替代**原始流；对外"原视频"就是它
     └─ (dmrender)  ─→ dm_video    ← 弹幕版，由原始流 + .ass 渲染
```

| 槽位 | 语义 | 代码依据 |
|---|---|---|
| `src_video_pre` | **转码前的原始录制流** | `stream_downloader.py:51` 状态初始化时预置；`liveevents.py:87` 在 `auto_transcode` 分支里被标记为转码输入 |
| `src_video` | **转码后的结果，替代原始流**；不转码时它就是原始录制流 | `liveevents.py:92` 在不转码时直接把录制产物放进 `src_video`；`:248-249` 转码完成后 `onRenderEnd` 把输出写进 `src_video` |
| `dm_video` | 弹幕版 | `liveevents.py:120` 起渲染任务 |

**由此推出两条容易搞错的行为**：

1. `clean_args.*.w_srcpre`（`liveevents.py:276-278`）的含义是"**被替代品可清理**"——即 `src_video` 已产出后，`src_video_pre` 才可以删除。它**不是**"链上的下一环"。
2. `clean_args.*.w_srcfile`（`liveevents.py:272-274`）只对 `dm_video` 生效：清理弹幕版时顺带清理 `src_video`。**前提是不上传原视频**，否则原视频上传会失败（`docs/usage.md:799` 也有此警告）。

⚠️ 这两个 `w_*` 开关目前**行为与文档描述一致**，但只在 `info['status'] == 'uploaded'` 时才会被检查（`liveevents.py:264`），而 `_check_for_clean` 只被 `onUploadEnd` 调用——因此 `auto_clean=True` 且 `auto_upload=False` 时清理**完全不执行**（见 [维护记录](maintainer-log.md) 第 8 节与 [`TODO.md`](TODO.md) B7.4）。

### 3.6 上传"续传"与"同组"语义 —— **已核实，两者是不同机制，勿混淆**

| 平台 | 单个文件传了一半 | 代码依据 |
|---|---|---|
| **B站 `biliwebapi`** | ❌ **从 0 重新开始**（每次新建 `upload_id`） | `biliwebapi.py:400` `?uploads` 每次新申请；`upos_stream` 内无 resume 分支 |
| **B站 `biliuprs`** | ❌ 整个视频重传 | `docs/usage.md:722`、`default.yml:302` 注释明确"重试会整个视频重传" |
| **YouTube** | ✅ 字节级断点续传 | 仅 YouTube 有 `retry_resume`（`docs/usage.md:724-726`） |

> 已实测确认：`retry_resume` **只存在于 `upload_args.youtube`**，`bilibili` 与 `custom` 均无此键。

**"可以继续"的正确含义 = 同一 `upload_group` 要归入同一稿件**（例如 `src_video` 的第 5/6/7 段应是同一稿件的 P5/P6/P7，而非三个独立稿件）。

承载这一归属的状态**全在内存，从未落盘**：

| 状态 | 位置 | 丢失后果 |
|---|---|---|
| 远程稿件标识 `bvid` | `biliwebapi.py:68` `self.videos`（`submit()` 靠 `videos.bvid is not None` 决定 `edit` 还是新建，`:657`） | 重启后新建稿件，同一场直播被拆成多个稿件 |
| 上传器实例与过期 | `Uploader/__init__.py:210-214` `_uploader_pool[upload_group]`（默认 `expire` 7 天） | 重启后组内后续分段无法追加到原稿件 |
| 分段状态 | `liveevents.py` `state_dict`（内存） | 重启即丢，无法知道哪些分段已上传 |

**能力已具备、只缺持久化**：`get_remote_data(bvid)`（`biliwebapi.py:616`）+ `submit(edit=True)`（`:657,684-685`）已支持"追加到既有稿件"，但 `bvid` 没有持久化。

---

## 4. 当前 Git 与配置状态

### 4.1 Git

- 分支：`v5`（`remotes/origin/HEAD → origin/v4`）
- HEAD：`2eb6080 feat: 录制斗鱼时移流的功能(#545)`
- 未提交改动（**属于他人/既有进行中工作，未处理**）：

| 文件 | 改动摘要 |
|---|---|
| `DMR/LiveAPI/danmaku/bilibili.py` | `get_ws_info` 增加 `bili_dm_cookies` 参数，读 cookie 文件、拼 `cookie` 头、取 `uid` |
| `DMR/LiveAPI/douyu.py` | `get_stream_urls` 增加 `douyu_watch_cookies` 参数，读 cookie 文件到局部变量 |
| `configs/global.yml` | 大量个人化参数（bili_watch_cookies 指向 `bili-xiaohao.json`、重启间隔、最小文件大小、streamlink 代理、渲染编码器、上传引擎改 `biliwebapi`、account 改 `bili-xiaohao` 等） |
| `AGENT.md` | 未跟踪文件（项目工作规则） |

### 4.2 配置文件分工

- `configs/global.yml`：用户全局配置，**已高度个人化**，不要随意按 default.yml 重整。
- `configs/DMR-*.yml`：会被当作录制任务加载。当前会加载的是 `configs/DMR-test.yml`（任务名 `test`，twitch `xzylas`，`danmaku: 0`）。
- `configs/-DMR-*.yml`、`configs/example-*.yml`：文件名不匹配 `DMR-**.yml`，**不会被加载**（仅作模板）。
- `.login_info/` 中实际存在：`bili-xiaohao.json`（含 `SESSDATA/bili_jct/DedeUserID/...`，**无 buvid3/buvid4**）、`.bili_watch_cookies.json`、`cookies.json`、`client.json`、`google-oauth2.json`。

---

## 5. 已验证的事实（本次会话运行过）

| 验证项 | 方法 | 结果 |
|---|---|---|
| 工作区可写 | 建目录/写文件/删除 | ✅ 通过 |
| 全模块可导入 | `python -B -c` 导入 DMR 全部插件与 LiveAPI | ✅ 通过（`imports OK`） |
| 配置可加载 | `Config('configs/global.yml')` | ✅ 通过，任务列表 `['test']` |
| 配置键实际值 | 打印 `dm_stream_option` / `stream_option` | `dm_stream_option = {'douyin_dm_cookies': None}`；`stream_option = {'stream_cdn': None, 'stream_type': None, 'bili_watch_cookies': '.login_info/bili-xiaohao.json'}` |
| 方法签名 | `inspect.signature` | `Bilibili.get_ws_info(url, bili_dm_cookies=None, **kwargs)`；`douyu.get_stream_urls(self, stream_cdn=None, douyu_watch_cookies=None, **kwargs)` |
| YAML 重复键 | 逐行扫描 `configs/global.yml` 的 `custom` 段 | ❌ **存在重复键**：`upload_args.custom` 中 `realtime` 出现两次（`:498 realtime: 1`、`:505 realtime: True`）。PyYAML 静默保留后者，因此解析结果为 `{'engine': 'subprocess', 'realtime': True, 'retry': 5, 'timeout': 0, 'min_length': 60, 'command': None}` —— 重复判断必须看原始文本，解析后的结果看不出来 |
| cookie 文件结构 | 解析 `.login_info/bili-xiaohao.json` | `cookie_info.cookies` 列表；无 `buvid3/buvid4`；`DedeUserID` 为 str |
| **启动路径可用** | 按 `main.py` 真实顺序调用 `DanmakuRender(config).start()` | ✅ 通过：4 个插件（downloader/render/uploader/cleaner）与任务 `test` 全部装配成功 |
| `DMREngine.start()` 幂等性 | 在已注册插件/任务后再次调用 `engine.start()` | ❌ 抛 `ValueError: too many values to unpack (expected 2)`（`DMR/engine.py:69`） |
| Task 事件路由 | 注入 `PipeMessage(source='engine', target='replay/mytask', event='ready')` | ✅ 通过：产出 `target='downloader', event='newtask'` 消息，证明 `onReady` → 下载器链路正常 |
| `ReplayTask.add_event` | 同一事件连续注册两个 handler | ❌ handler 数仍为 1（`replaytask.py:21-23` 的 append 被无条件覆盖） |
| `LiveEvents._check_for_upload` | 非实时上传 + 所有分段短于 `min_length` | ❌ 抛 `IndexError: list index out of range`（`liveevents.py:214`） |
| `LiveEvents._check_for_clean` | 清理规则不匹配时是否改状态 | ❌ 仍被置为 `'cleaned'`（`liveevents.py:294` 缩进层级错误） |
| `LiveEvents._free_state_memory` | 组内含未完成分段（`uploading`/`ready`） | ✅ 正确保留不释放（需 `ended_dict` 存时间戳；若存 `True` 会走 72 小时超时分支误删） |
| `retry_resume` 归属 | `Config('configs/global.yml')` 检查三个上传目标的键集合 | ✅ 仅 `upload_args.youtube` 有 `retry_resume`；`bilibili` / `custom` 均无 → **字节级续传只有 YouTube 支持** |
| 产物语义 | 读 `liveevents.py:51-53,87,92,248,272-278` + `stream_downloader.py:51` | ✅ `src_video_pre`=转码前原始流；`src_video`=转码后**替代**它；`w_srcpre`="被替代品可清理" |
| 上传同组归属 | 读 `biliwebapi.py:68,210,616,657` + `Uploader/__init__.py:210-214` | ⚠️ `bvid` 与 `_uploader_pool` **仅在内存**，重启即丢；但 `get_remote_data`+`submit(edit=True)` 能力已具备 |

Task 层的完整问题清单见 [`TODO.md`](TODO.md) 的 B7 节。

未做（需授权）：任何真实拉流/弹幕/上传/渲染。

---

## 6. 已确认的问题与风险清单

### 6.1 未提交改动中的问题（**已核实为代码事实，非推测**）

| 编号 | 位置 | 问题 | 影响 |
|---|---|---|---|
| B1 | `DMR/LiveAPI/danmaku/bilibili.py:30-38, 60-68` | `uid` 从 cookie 解析出来后**从未被使用**，payload 中始终硬编码 `"uid": 0` | 该改动想实现的"登录态弹幕"实际未生效 |
| B2 | `DMR/LiveAPI/danmaku/bilibili.py:37, 50-55` | 直接改写类级共享可变对象 `Bilibili.headers`；且未传 cookie 时可能残留上一次写入的 `buvid3/buvid4` | 多任务/多账号互相污染；跨任务状态泄漏 |
| B3 | `DMR/Config/default.yml` + `configs/global.yml` | `dm_stream_option` 中**没有** `bili_dm_cookies` 键 | 无法通过配置文件使用，只能像 `test_danmu.py` 那样硬编码传参 |
| D1 | `DMR/LiveAPI/douyu.py:333-338` | 读出的 `watch_cookies` **从未注入** `self.sess` 或任何请求头，之后未再使用 | 死代码，功能未实现 |
| D2 | 同上 | `douyu_watch_cookies` 未进 `default.yml`，恒为 `None`；"文件不存在"的 warning 每次调用都会打印 | 配置不可达 + 日志噪音 |
| D3 | 同上 `:340-355` | 读 cookie 放在 `get_stream_urls` 内，每次调用重复读盘 | 轻微，可接受 |
| H1 | `DMR/LiveAPI/douyu.py:307-308` | 仍接收 `huya_mobile_api` 并透传给 `get_room_profile(use_api=...)`，但 `configs/global.yml` 已删除该键（`default.yml` 本就没有） | 参数不可配置，但默认值兜底，不崩溃 |

### 6.2 与未提交改动无关的既有观察（**均未修改**）

| 编号 | 位置 | 观察 | 判定 |
|---|---|---|---|
| C1 | `DMR/Config/default.yml` 曾定义 `dynamic_config_path`，而 `DMR/Config/__init__.py:52` 读取的是 `dmr_engine_args['config_path']` | 键名不一致 | ★**已修复**：`default.yml` 改为 `config_path: ./configs` 并删除失效键 |
| C2 | `DMR/Config/default.yml:431-467` 的 `clean_args` 以 `move/copy/delete/custom` 为键，而 `DMR/Config/__init__.py:107-114` 与 `docs/usage.md` 用的是 `文件类型 → {method: ...}` | 两套结构并存；实际生效的是 `global.yml` 里的 `clean_args`（文件类型分组） | 文档/默认值不一致，优先级低 |
| C3 | `DMR/LiveAPI/danmaku/bilibili.py:25,48` 连续创建两个 `aiohttp.ClientSession` | 第一个仅用于 room_init，随后被弃置 | 资源浪费，轻微 |
| C4 | `configs/global.yml` 中 `huya_mobile_api` 被删除，`docs/usage.md:351` 仍记录该键 | 文档与配置漂移；`DMR/LiveAPI/douyu.py:307-308` 仍接收该参数 | 文档问题，优先级低 |
| C5 | `configs/global.yml` `upload_args.custom` 曾出现 `realtime` 键重复（`realtime: 1` 与 `realtime: True`），YAML 静默取后者 | 脏配置隐患 | ★**已修复**：`global.yml` 现与 `default.yml` 一致，且在基准里补上了 `realtime: True`（自定义上传必须启用） |
| C6 | `DMR/WebService/__init__.py:30-32` 的 `stop()` 首行即 `return` | 后续 stop 逻辑为死代码 | 无害 |
| C7 | `DMR/engine.py:69-73, 75-80` | **潜伏缺陷（当前不触发）**：`for name, plugin in self.plugin_dict.values():` 每次迭代产出的是**单个 dict**（4 个键），解包成 2 个名字必然 `ValueError: too many values to unpack (expected 2)`；下一行 `self.plugin_dict['name']` 也是笔误（应为循环变量）。**之所以现在不爆炸**：`DMR/__init__.py:29` 是在 `plugin_dict`/`task_dict` **仍为空**时先调 `engine.start()`，插件随后由 `add_plugin` 自己 `start()`。已实测：按 main.py 顺序调用 `dmr.start()` 正常；但此时再调一次 `engine.start()` 立即抛 `ValueError`（非幂等）。 | 潜伏 bug + 死代码，优先级低但属真实缺陷 |
| C8 | `.pyc` 写入被拒绝（`DMR/**/__pycache__/*.pyc.NNNN` PermissionError） | 编译缓存无法更新，用 `python -B` 或 `PYTHONDONTWRITEBYTECODE=1` 规避 | 环境问题，不影响运行 |

### 6.3 环境相关

- 本会话开始时工作区根目录缺少 `WRITE_OWNER`，导致 DSH 沙箱无法写入，已用捆绑脚本修复并验证；备份与回滚脚本位于 `D:\Code\_dsh-acl-recovery\`（`acl-backup-5c77c8190ba74f19bda1b2ba0bcc9690.json` / `.ps1`）。诊断报告：`acl-report-55c6893fedf94d8da6b050bad424433e.jsonl`。
- `logs/` 目录不存在（首次运行 `main.py`/`dryrun.py` 时自动创建）。
- `直播回放/` 目录不存在。

---

## 7. 可用验证手段（分层，按侵入度递增）

1. **静态**：`python -B -m compileall`、全模块 import、`inspect.signature` 检查。
2. **配置级**：`Config('configs/global.yml')` 打印合并结果，确认键被正确识别。
3. **单元级**：对纯函数（cookie 解析、`replace_keywords`、`split_url`、ASS 写出）构造输入断言输出。
4. **单模块联网（只读）**：`Bilibili.get_ws_info` 只取 token 不建流；`douyu.get_stream_urls` 只取 URL 不录制；`LiveAPI.Onair/GetRoomInfo`。
5. **集成**：`python dryrun.py`（180 秒后自动停任务），或指定单个 `DMR-*.yml` 任务短时录制。
6. **全流程**：`python main.py` —— **需事先获得用户批准**。

---

## 8. 架构级重构方向（已与用户对齐，**未开工**）

用户对当前架构提出的四个诉求与已确认的决策，完整内容见 [`TODO.md`](TODO.md) 的 **B8** 节。要点：

- **决策 1（产物配置）**：采用**可选追加**。`artifacts:` 为可选段，不写即使用内置默认产物图，行为等价于当前实现，**老配置零迁移**。
- **决策 2（状态持久化）**：**先只做三样** —— 非终态 artifact、`upload_group.remote_id`（`bvid`）、`upload_group` 成员清单。不改配置格式、不动录制主流程。
- **决策 3（取流凭据）**：**不建通用凭据体系**，作为插件普通选项（cookies）即可。

**阶段顺序**：P0 测试骨架 ✅ → **P1 持久化（存储/对账/启动接线已完成，写入点待接）** → P2 默认产物图 + 可选 `artifacts:` → P3 插件注册表 → P4 REST + SSE → P5 后处理 Action 链 → P6 恢复 UI。

### 8.0 状态持久化与启动对账（P1 进行中）

新增**单一模块** `DMR/state/`（不另建顶层目录，按功能模块组织）：

```
DMR/state/
├── __init__.py      对外唯一入口：枚举 + 仓储 + 对账
├── enums.py         ArtifactKind / ArtifactState / UploadGroupState + StateConsistencyError + 取值容错
├── schema.py        DDL 与模式版本（SCHEMA_VERSION=1，含迁移框架）
├── repository.py    StateRepository：会话 / 产物 / 上传组的 SQLite 读写
└── reconciler.py    RecoveryManager：启动对账（第 0 步 + A/C/D 组规则）
```

- **状态库**：`logs/dmr_state.db`（SQLite + WAL）。删除它等同于放弃所有未完成进度。
- **5 张表**：`schema_version` / `sessions` / `artifacts` / `upload_groups` / `meta`。**不记分P清单**，上传组只存 `remote_id`（bvid）。
- **`artifacts` 用「键列 + JSON 载荷」（模式 v2）**：列上只留 `artifact_id` / `session_id` / `segment_idx` / `kind` / `state` / `updated_at`，其余易变字段（`path` / `part_path` / `danmaku_path` / `size` / `duration` / `resolution` / `origin` / `attempts` / `last_error`）统一收进 `data` JSON 列。**以后扩展 Artifact 无需改表**；字段清单集中在 `DMR/state/payload.py`，读写两端共用。
- **对账**：启动时执行 第0步（净化 `RECORDING`/`RENDERING`/`UPLOADING`）→ A 组（校验磁盘事实）→ C 组（上传组提示）→ D 组（过期回收）。
- **新增保护**：状态库中出现但当前配置里没有的任务 → **拒绝启动**（`StateConsistencyError`）。防止换配置目录后旧任务状态被过期回收误删。
- **顺带修复的真实缺陷**：`DMREngine.stop()` 在未 `start()` 时因 `recv_queue is None` 崩溃。

**已完成接线（写入点 3/3 之一）**：上传组的稿件归属（bvid）—— **两个 B 站引擎都支持**
- `DMR/Uploader/biliwebapi.py`：构造函数新增 `resume_bvid`，按 bvid 载入既有稿件；新增 `get_remote_bvid()`；`upload()` 的 `is_new` 改为依据 `bvid` 是否存在判断。
- `DMR/Uploader/biliuprs.py`：构造函数新增 `resume_bvid`（写入 `task_info['bvid']`）；新增 `get_remote_bvid()` 与 `_upload_once_with_fallback()`（应对稿件已被删除）。**该引擎原本就有 `biliup append --vid <bvid>` 追加能力**，缺的只是持久化。
- `DMR/Uploader/__init__.py`：新增 `_get_or_create_uploader()` / `_persist_upload_group()` / `_lookup_group_remote_id()` / `_supports_resume()` / `_create_uploader()`；引擎选择集中为 `_UPLOADER_ENGINES` 表；`_RESUME_CAPABLE_ENGINES = {'biliwebapi', 'biliuprs'}`；上传成功后回写 bvid。
- `DMR/__init__.py`：向 uploader 插件注入 `state_repo`。

**已完成接线（写入点 3/3）**

1. **上传组稿件归属**（`Uploader` + `biliwebapi`/`biliuprs`）：重启后同一 upload_group 复用既有 bvid，新分段追加到同一稿件；两个 B 站引擎都支持。
2. **场次与产物登记**（`stream_downloader.py` + 四个下载引擎）：登记场次（含主播/房间元信息）与已完成分段；引擎上报"正在写入的文件"，使录制中途被强杀后残file可被对账按 `recovery.on_interrupted_file` 处置（`ask`/`keep`/`discard`）。
3. **渲染/上传/清理进度**（`liveevents.py`）：`state_dict` 仍是运行时真相，关键状态变化镜像到状态库 —— 重启后可知"哪些分段还没渲染/上传/清理"。

**顺带修复的两个已记录缺陷**：B7.1（`_check_for_upload` 空候选 `IndexError`）、B7.2（`_check_for_clean` 无条件标记 `cleaned`）。两者的 `expectedFailure` 用例已转为通过。

**弹幕文件是视频的附属物**：`.ass` 记录在 `artifacts.danmaku_path`，不是独立产物。文件名在**该分段自己的** `segment_callback` 里由 `dmw.split()` 改成与视频同名（配对正确，已实测），`dm_file_id` 取 `split()` 返回的**实际落盘路径** —— 改名失败时回退为 `[正在录制]` 原名，避免登记一个不存在的路径。

测试：`unit_tests/` 共 **437 个用例**，`Ran 437 tests ... OK (expected failures=5)`。
剩余 5 个 `expectedFailure` 对应尚未修复的 B7.3（`add_event` 覆盖 / list 值嵌套）与 B7.5（`engine.start()` 循环解包）。

### 8.0.5 消息路由不再依赖 `replay/` 前缀（生产事故根因，已修复）

**现象**：B站稿件已上传成功，但状态库里大量产物停在 `recorded` / `uploading`，清理不触发。

**根因**：上传器把消息来源原样当作回包目标（`Uploader/__init__.py:167` `'source': msg.source`，回包 `target=task['source']`），而引擎**旧实现只认 `replay/` 前缀**，裸任务名落进 `else` 分支被静默丢弃（只留一行 `Unknown target`）→ `onUploadEnd` 从不执行 → 状态不进入 `uploaded` → `_check_for_clean` 只处理 `uploaded` → **清理永不派发**。

旧日志 `'source': 'twitchpros-yrvz72-0'` + `Unknown target twitchpros-yrvz72-0.` 与状态库时间线（18:47 那批全卡 `uploading`、升级后 19:49 起出现 `cleaned`）完全吻合。

**`replay/` 前缀的实际作用**：核实后确认**没有作用** —— 只有 `engine.pipeSend` 解析它；`replaytask.py` 判断后仍用裸 `event` 查表；赋给 `source` 的前缀全库无人解析。它只是命名空间仪式，而"同一件事三种写法 + 无统一自检"正是事故成因。

**修法（选项 A）**：`engine.py` 新增 `_resolve_target()`，按 `engine` → `replay/<name>` → 插件名 → **裸任务名** → unknown 的顺序解析。要点：① **裸任务名即可路由**（消除对前缀约定的依赖）；② `replay/` 按前缀剥离而非 `split('/')[1]`，任务名含 `/` 不再被截断；③ 插件名作为保留标识**优先于同名任务**；④ `Unknown target` 日志带上 `source`/`event` 便于定位。

**回归测试 7 个**（`test_engine.py::TestBareTasknameRouting`），并做端到端复刻：uploader 以裸任务名回包时，产物状态 `uploading → uploaded`（修复前该消息被丢弃）。

### 8.0.3 恢复重驱动：重启后继续处理未完成的产物（已完成）

**问题**：服务器上重启后日志显示"已恢复为 recorded"，但文件**既没改名也没上传**。

**根因是两个独立缺口**：

1. `reconcile()` **只对账、不重跑** —— 它把状态修正到"与磁盘一致"，但不会把产物送回处理链，于是 `recorded` 永远停在那里。
2. 文件仍是 `[正在录制]...Part000-...` **中间名**：分段式引擎只在"下一个分段开始时"才改名，进程在那之前退出就永远停在中间名上。

另有一个隐性前提：**重建不出 `VideoInfo`** —— 输出文件名与标题依赖录制当时的元信息（主播/标题/时间），而库里原本只有路径/大小/时长。

**实现**：产物的 `data` 载荷新增 `video_info`（存整个 `VideoInfo`，`datetime`/`tuple` 显式转换，否则 `{CTIME.YEAR}` 这类模板会抛异常）；新增 `DMR/state/resume.py::rebuild_video_info()`（首选载荷；缺失或损坏时用产物字段 + 场次记录回退重建，`streamer` 还原为 `StreamerInfo` 而非 dict）；`RecoveryManager.collect_resumable()` 挑出 `RECORDED`/`RENDERED` 并累加 `attempts`；`LiveEvents.resume_recovered()` 把它们按**原场次**还原成 `state_dict` 分段、补做中间名改名，然后交给**既有的** `_check_for_upload` 走同一条渲染/上传/清理链路（不另写流程，避免行为漂移）；启动时由 `DMR/__init__.py::_resume_pending_artifacts()` 驱动，`recovery.resume` 可关闭（默认开）。

**安全性**：`UPLOADED`/`CLEANED` 等终态**永不**重跑（不会重复投稿）；`INTERRUPTED` 不自动重跑（可能不完整）；只处理当前加载的任务；改名失败沿用原名继续上传（能上传比名字漂亮重要）；单条失败不连坐。

**已知取舍**：`uploading` 在重启时会被净化回 `recorded`（无法确定远端是否真的收下），因此**崩溃前已完成的投稿可能被重新上传一次**。跨重启的精确去重做不到，属状态机固有取舍；同一次运行内不会重复派发。

**测试**：新增 43 个用例（`test_state_resume.py` 36 + `test_state_init.py::TestResumePendingArtifacts` 7）。真机数据验证：用日志里的真实文件名复现，成功改名为 `korooonx-2026年10月05日16点50分-直播标题.mkv`（时间取自 `ctime`，与原名时间戳一致）并派发上传。

**后续修复（已被 8.0.4 的最终方案取代）**：服务器实测恢复时曾抛 `TypeError: '<' not supported between instances of 'NoneType' and 'int'`（`duration` 为 `None` 时被直接拿去和 `min_length` 比较）。中间两轮修法是"用 ffprobe 探测补齐时长"，但探测失败既不等于文件损坏、也让恢复路径依赖 ffprobe —— 最终按用户要求改为 **8.0.4** 的"文件名标记 + 文件大小"规则，不再调用 ffprobe。

⚠️ 历史教训：`FFprobe.get_duration` 失败时返回 **`-1`** 而不是异常或 `None`；把哨兵值当真实时长会让产物被判"太短"而**静默不上传**。这类"哨兵值当返回值"的接口在容错时必须显式排除。

### 8.0.4 恢复判定不依赖 ffprobe（最终方案，已完成）

按用户判断：时长探测失败说明**文件坏了、不用恢复**；且判定**不应依赖 ffprobe**。

**规则**（`DMR/state/resume.py::is_recovered_file_usable`）：
1. 文件名以 `[正在录制]` 开头 —— 分段式引擎写出中间名，说明确实开始录了；已改名的文件同样正常
2. 文件大小 ≥ `recovery.min_valid_size_mb`（默认 **30MB**）—— 读一次 `stat` 即可，不解析容器

**上传长度门槛同步改**（`liveevents._passes_length_gate`，实时与非实时共用）：时长已知按 `min_length`；时长**未知或为 0** 时改用文件大小判断 —— 否则恢复出的产物永远传不上去。

**阈值只有一项**：`recovery.min_valid_size_mb`（默认 **30MB**）同时服务"启动对账校验中断产物"与"恢复时判定是否值得处理"—— 两者都在回答"是否已录到实质内容"，必须一致（早期曾误拆成两个配置名，属重复配置）。

**顺带修掉**：① `FFprobe.get_duration` 失败返回 `-1` 哨兵值被当成真实时长；② 时长未知直接比较导致 `TypeError` 中断整批恢复；③ 载荷 `title=None` 被渲染成字符串 `"None"` 写进文件名（现回落场次标题）。

由 `recovery.on_unusable_file`（`skip`/`discard`/`ask`，默认 `skip`）处置不满足条件的产物。

### 8.0.2 XML 弹幕支持：渲染器 + 虚拟录制（已完成）

新增 `DMR/utils/xml2ass.py`（封装可选依赖 `dmconvert`）与配置段 `render_args.dmrender.dmconvert`，让**渲染器**与**虚拟录制**都能直接吃 B站录制格式的 `.xml` 弹幕：

- 渲染器：`.ass` 原样透传；`.xml` 先转成临时 ASS 再渲染，结束后清理临时文件。
- 虚拟录制：弹幕查找从硬编码 `.ass` 改为 `find_danmaku_file()`（`.ass` 优先，其次 `.xml`），与 `render_only.py` 共用同一实现。

细节、接口契约与验证结果见 [`TODO.md`](TODO.md) 的 **F7** 节。要点：

- **`dmconvert` 是可选依赖**：未安装只影响"转换 XML"这一步（报错附安装提示），不影响 ASS 录制与渲染。
- **分辨率必须显式确定**：XML 不含分辨率，渲染器从视频探测，配置里也可指定；都没有则明确报错（不静默产出错位弹幕）。
- 按用户要求**没有**提供独立命令行工具。
- ⚠️ **未做真机验证**：本机无法联网安装 `dmconvert`，端到端验证用的是签名与上游一致的替身。

### 8.0.1 下载引擎内存优化（已完成）

`DMR/Downloader/ffmpeg.py`、`DMR/Downloader/streamlink.py` 的实测内存与 CPU 问题、修法与基线数据见 [`TODO.md`](TODO.md) 的 **F1–F5** 节。要点：

- `bufsize=10**8` 会为**每个子进程**预留约 190 MB 的 Python 堆缓冲；**RSS 因惰性提交看不出问题**，必须用 `tracemalloc` 之类的工具才能发现。已改为行缓冲。
- `ffmpeg.py` 的待处理行队列与日志尾**已合并为单一数据源**（两个 `deque(maxlen=MSG_QUEUE_MAXSIZE)`，监控线程写、主循环取）；streamlink 的临时日志文件不再整体读入。
- **监控线程在管道 EOF 后会空转吃满一个 CPU 核**（实测 0.97 CPU 秒/秒）——已修（读到空行即退出）。这是本次发现的**真实 CPU 缺陷**。
- CPU 基线：真实 `-stats` 速率（约 2 行/秒）下占用 **0.0%**；仅子进程疯狂刷屏的病态场景会吃满一核（每分钟约 4.5M 行时）。
- 仓库内另外 8 处同类 `bufsize=10**8`（`streamgears` / `Render/ffmpeg` / `biliuprs` / `logintools`）**已清理完毕**：其中 6 处 stdout 是文件/控制台，该参数被 Python 忽略（纯无效参数，直接删除）；2 处 stdout 是管道，改成"临时文件 + `communicate()`"，一并消除了**PIPE + wait + read 的输出死锁**（见 [维护记录](maintainer-log.md) 第 7 节，共用函数 `DMR/utils/runcmd.py::run_and_capture_output()`）。
- 新增回归测试：`unit_tests/test_downloader_memory.py`、`unit_tests/test_runcmd_capture.py`。

### 8.2 真机 dryrun 验收（P1，已完成）

用真实直播间（`https://live.bilibili.com/1773507572`，分段时间 120 秒）跑通一次录制，并读取真实状态库核对：

| 验收项 | 结果 |
|---|---|
| 场次登记（含主播/标题元信息） | ✅ |
| 产物落库（路径 / 时长 / 大小） | ✅ 2 个分段 |
| 弹幕作为附属字段 | ✅ |
| 启动对账幂等（连续两次无变化） | ✅ |
| 中断文件三种策略（用真实 42MB 数据） | ✅ `ask`/`keep`/`discard` 行为正确 |
| 上传链路 | 本次刻意禁止真上传，全程无上传 |

真机暴露了 **2 个模块级测试没能发现的 bug**，均已修复（详见 [维护记录](maintainer-log.md) 第 10.3 节）：
1. `_register_session()` 在 `room_info` 赋值之前调用 → 场次登记失败 → 产物写入触发外键约束错误。
2. `_handle_interrupted` 要求"`.part` 不存在"才恢复，而引擎其实**直接写最终名** → `keep` 策略形同虚设。

⚠️ **dryrun 的上传闸门（当前状态）**：`dryrun.py` 按**当前配置**加载全部任务（这是它的本意），分段时间固定 30 秒、180 秒后自动停任务。为免测试片段被真实投稿，脚本把所有上传目标的 `min_length` 抬到测试分段无法满足的值（常量 `DRYRUN_MIN_LENGTH`）——**上传流程不会真正提交稿件**。

历史上它曾把 `min_length` 设为 `0`，导致测试片段被真实上传到 B 站账号（已确认 `BV1sUHL63EC6`）。需要连上传一起测时把该常量改为 `0`，并把 `dtime`（脚本已设为延迟 24 小时发布）考虑进去。

遗留物：`直播回放/`、`直播回放（弹幕版）/`（约 500MB）、`.dryrun/`、`logs/dmr_state_dryrun.db`、`logs/dmr_state.db`（第一次误用正式配置的运行留下的）。

### 8.3 全流程真机验证（P1，已完成）

用 `unit_tests/_p1_fullflow_runner.py` 在真实直播间跑通**下载 → 弹幕渲染 → 上传 → 清理**完整链路（分段时间 300 秒，真实上传到 B 站，清理用 `move` 到单独目录）。

**结果：四个阶段全部成功**

| 阶段 | 证据 |
|---|---|
| 下载 | 5 个分段，每段 297–299 秒，单段约 433–457MB |
| 渲染 | 5 个弹幕版 mp4 |
| 上传 | **5 段全部进同一稿件 `BV1wVHL6KEAT`**（`aid` 相同）—— 证明上传组归属生效，同场直播不会裂成多个稿件 |
| 清理 | 5 个 `src_video` 与 `.ass` 全部 move 到目标目录，原目录清空 |
| 状态库 | 10 条产物全部终态（`cleaned`×5 + `rendered`×5），**非终态 0 条**；场次 `ended=True` |

**观察到的现象（非缺陷）**：实际录得 5 段而非 3 段（停止指令在 19:25 才发出，300 秒边界内又切出 2 段）；`dm_video` 的分段序号与 `src_video` 不对齐（渲染侧独立编号，按各自主键处理，不影响功能）；`biliuprs` 在无终端环境下因需扫码登录而失败（既有问题，由 `biliwebapi` 兜底）；`clean_args` 只配 `src_video`，故弹幕版 mp4 按配置保留。

### 8.1 模块级测试基座（P0 已完成）

仓库现在有可运行的模块级测试，不再只能跑全流程：

```powershell
python -B -m unittest discover -s unit_tests -t .
# → Ran 437 tests ... OK (expected failures=5)
```

- **零新增依赖**：只用标准库 `unittest`（本机未安装 pytest）。装了 pytest 后同一批用例也能直接收集。
- **不需要网络 / 磁盘 / 子进程**：全部用例合计约 4.4 秒。
- 测试替身：`FakeClock`、`FakeEventBus`、`InMemoryArtifactRepo`、`RecordingSubprocessRunner`、`drain_queue()`。
- 5 个 `expectedFailure` 精确对应尚未修复的已确认缺陷（B5 三例、B7.3 两例）；修复后会转为 `unexpected success` 报错，提醒去掉标记。
- 覆盖范围：`liveevents` 状态机（上传筛选、清理记账、产物语义、内存释放）、`ReplayTask` 事件路由与注册规则、`DMREngine` 启动路径与目标分发。
- ⚠️ **目录名必须是 `unit_tests/`，不能叫 `tests/`**：根 `.gitignore` 第 5 行 `/test**` 会匹配到 `tests/`，使测试对 git 不可见且会被 `git clean` 删除（已实测）。

细节见 [`unit_tests/README.md`](../unit_tests/README.md) 与 [维护记录](maintainer-log.md) 第 9 节。

**调研参考**：streamlink（解析/消费分离、懒加载路由、侧载优先）、yt-dlp（`PostProcessor` 链、`progress_hooks`、`expected=` 错误分类）、biliup（分层与事件契约）。stream-rec **已归档**，DouyinLiveRecorder 是**反例**（全局变量当状态、无管理 API、无弹幕实现）。

---

## 9. 工作约定（来自 `AGENT.md`，与用户本次指令一致）

1. 先读代码再改；优先最小必要修改，不做无关重构。
2. 修根因，不用异常捕获或硬编码掩盖问题。
3. 修改后必须运行相关测试或最小可运行案例；不删测试、不降低检查标准。
4. 不删除大量文件/数据；不 `git reset --hard` / force push；不动生产环境；不覆盖原始数据；不修改或暴露 API key / password；不执行明显高费用任务。
5. 保护用户已有的未提交修改。
6. 全流程录播任务需用户批准后再跑。
