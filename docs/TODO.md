# 待办清单 — DanmakuRender-5

> **本文件只记录"尚未完成"的事项。** 相关文档：
> [更新说明](CHANGELOG.md) ·
> [维护记录（技术明细）](maintainer-log.md) ·
> [项目当前状态](project_state.md) ·
> [测试说明](../unit_tests/README.md) ·
> [返回 README](../README.md)
>
> 所有条目均为**已核实的代码事实**（附文件与行号），不是猜测。
> 用户已明确：**不修改** `configs/global.yml`，也暂不处理 §1 的未提交 WIP。

**当前进行中：无。**

---

## 1. 未提交改动（工作区 WIP）遗留的问题

这批改动位于 `DMR/LiveAPI/danmaku/bilibili.py`、`DMR/LiveAPI/douyu.py`，
属他人/既有进行中的工作。其中 **A4、A5 已修复**（见 CHANGELOG），其余待处理。

### A1. B站弹幕：`uid` 解析后未使用 — 功能未生效
- **位置**：`DMR/LiveAPI/danmaku/bilibili.py:30-38`（解析）、`:60-68`（构造 WS 注册包）
- **现象**：`uid = cookies.get('DedeUserID', 0)` 被赋值后，payload 里仍是 `"uid": 0` 硬编码，后续无任何使用。
- **根因**：payload 字面量未替换为变量。
- **建议**：把 payload 的 `uid` 改为解析出的值（`DedeUserID` 是 str，需转 int）；`bili_dm_cookies` 为空时保持 `0`，确保匿名路径行为不变。
- **验收**：`bili_dm_cookies=None` 与传文件两种情况下分别断言 payload 中 `uid` 的值。

### A2. B站弹幕：改写类级共享 `headers`
- **位置**：`DMR/LiveAPI/danmaku/bilibili.py:37`、`:50-55`、`:12-19`
- **现象**：`Bilibili.headers['cookie'] = ...` 直接改类属性；未传 cookie 时 `buvid3/buvid4` 可能残留上一次的值。
- **根因**：`headers` 是类级可变字典，被当作实例状态使用。
- **建议**：按实例构造 headers 副本（需相应把该类从 `site_class` 迁到 `site_class_v3`，或至少构造局部 headers 并在请求时显式传入），避免跨任务污染。
- **风险**：`DanmakuClient` 通过 `getattr(self.__site_api, 'headers', {})` 取 headers，改动需同步确认。
- **验收**：两个不同账号的实例 headers 互不影响；不带 cookie 时不出现 `buvid3`。

### A3. `bili_dm_cookies` 无法通过配置文件配置
- **位置**：`DMR/Config/default.yml`（`dm_stream_option`）、`configs/global.yml:143-148`
- **现象**：`dm_stream_option` 只有 `douyin_dm_cookies`，没有 `bili_dm_cookies`；只能像 `test_danmu.py` 那样硬编码传参。
- **根因**：`default.yml` 是配置基准，键不在此定义就无法被用户配置覆盖。
- **建议**：在 `default.yml` 的 `dm_stream_option` 增加 `bili_dm_cookies: ~` 及注释；同步 `docs/usage.md` 对应段落。
- **验收**：`Config(...)` 打印的 `dm_stream_option` 中含该键，且能在 `configs/global.yml` 中覆盖生效。

### A6. `huya_mobile_api` 参数不可配置
- **位置**：`DMR/LiveAPI/douyu.py:307-308`、`docs/usage.md:351`
- **现象**：代码仍接收并透传，但配置基准与用户配置都没有该键（已被删除）。
- **建议**：确认是否还需要该开关：需要则补回 `default.yml`，不需要则移除参数与文档描述。
- **优先级**：低。

---

## 2. 既有观察（与 WIP 无关）

### B1. `dmr_engine_args` 键名不一致 ★**已修复**
- **位置**：`DMR/Config/default.yml` 曾定义 `dynamic_config_path`，而 `DMR/Config/__init__.py:52` 读取的是 `config_path`
- **原现状**：`configs/global.yml` 设了正确的 `config_path`，且代码有 `.get(..., ['./configs'])` 兜底，因此**不触发故障**；但按 `default.yml` 写配置的人改了 `dynamic_config_path` 不会生效。
- **修法**：`default.yml` 改为 `config_path: ./configs`，删除失效的 `dynamic_config_path`，并补注释说明键名以代码为准。

### B2. `clean_args` 存在两套互不兼容的结构
- **位置**：`DMR/Config/default.yml` 以 `move/copy/delete/custom` 为键（旧的"方法名"结构）；`DMR/Config/__init__.py:107-114` 与 `docs/usage.md` 用 `文件类型 → {method: ...}`（新的"文件类型分组"结构）
- **现状**：任务配置校验读的是新结构；实际生效的是 `configs/global.yml` 的 `clean_args`。
- **建议**：确认 `default.yml` 的旧结构是否已被废弃；若废弃应改为新结构以免误导用户。
- **优先级**：低（文档/默认值不一致）。

### B3. B站弹幕连续创建两个 `aiohttp.ClientSession`
- **位置**：`DMR/LiveAPI/danmaku/bilibili.py:25`、`:48`
- **现象**：第一个仅用于 `room_init`，随后弃置未关闭。
- **建议**：合并为一个 session。
- **优先级**：轻微（资源浪费）。

### B4. `WebService.stop()` 为死代码
- **位置**：`DMR/WebService/__init__.py:30-32`，`stop()` 首行即 `return`。
- **建议**：实现真正的停止逻辑，或删除不可达语句。
- **优先级**：低。

### B5. `DMREngine.start()` 非幂等，循环解包必然失败（潜伏缺陷）★真实缺陷
- **位置**：`DMR/engine.py:69-73`（插件循环）、`:75-80`（任务循环）
- **现象**：`for name, plugin in self.plugin_dict.values():` 每次迭代产出**单个 dict**（含 `class/config/send_queue/status` 四个键），解包成 2 个名字必然抛 `ValueError: too many values to unpack (expected 2)`。下一行 `self.plugin_dict['name']['status'] = 1` 同样是笔误（写死字符串 `'name'`，应为循环变量）。
- **为什么现在不爆炸**：`DMR/__init__.py` 先调用 `engine.start()`，此刻两个 dict 还是空的，循环不执行；插件与任务随后由 `add_plugin()` / `add_task()` 各自 `start()`。
- **已实测**：按 `main.py` 真实顺序调用 `dmr.start()` → 正常；在已注册插件后再调一次 `engine.start()` → 立即 `ValueError`。
- **影响**：任何"重复调用 `engine.start()`"的场景（WebUI 重启引擎、异常恢复、以后重构为"先 add 后 start"）都会直接崩溃。
- **建议**：改为 `.items()`，并把 `self.xxx_dict['name']['status']` 改为 `self.xxx_dict[name]['status']`。**注意**：`add_plugin` 已在 `stoped == False` 时自己 start 过，`status` 判断可避免重复启动——需连带确认，不能盲改。
- **优先级**：低（当前不触发），但属真实缺陷；改前需先明确启动顺序契约。

### B6. `__pycache__` 中 `.pyc` 无法写入（环境）
- **现象**：`python -m compileall` 报 `PermissionError: ... .pyc.NNNN`（目录 ACL 无当前用户写权限）。
- **影响**：仅影响字节码缓存，不影响运行。
- **规避**：`python -B` 或设 `PYTHONDONTWRITEBYTECODE=1`。

---

## 3. Task 层（`DMR/Task/`）逻辑问题

### B7.3 事件系统：死代码 + 语义与 `source` 强耦合
- **位置**：`DMR/Task/replaytask.py:20-23`、`:30-71`；`DMR/Task/liveevents.py:14-29`
- **实测**：
  - `add_event` 两次注册同一事件，handler 数仍是 **1**：`replaytask.py:21-22` 先 `append`，紧接着第 23 行**无条件覆盖** `self._event_dict[event] = [trigger]`，append 结果被丢弃（死分支）。
  - 若 `event_dict` 的值是 `list`，会得到**嵌套 list**，回放时 `func(msg)` 直接 `TypeError`。**今天不炸**仅因为 `liveevents.event_dict` 每个值都是单个 bound method。
- **语义耦合**：分发键是 `msg.source + '/' + msg.event`，而 `liveevents` 的键写作 `'downloader/livestart'`、`'render/end'`。这意味着**事件名必须与发送方的 `source` 字符串完全一致**——改任一侧都会静默降级到 `default`（只打一行日志）。实际已存在不一致：`'render/error'`、`'uploader/error'`、`'cleaner/error'` 三个键**不可达**，因为对方实际发的是 `event='error'`，只有 `xxx/end` 能命中。
- **返回值处理重复**：`ret_msgs` 的处理逻辑在 `replaytask.py:39-48` 与 `:54-63` 完全重复两遍。
- **建议**：事件名集中为常量/枚举，显式声明 `(source, event) -> handler`；抽出 `_dispatch(funcs, msg)`；删掉 `add_event` 的覆盖分支或明确其"替换"语义。

### B7.4 清理链路缺少完成回调
- **位置**：`DMR/Task/liveevents.py`（`onCleanEnd` 只在 `baseevents.py:55` 有空实现）、`:26-27` 把 `cleaner/end`/`cleaner/error` 指向 `defaultEvent`
- **现象**：`Cleaner` 完成后会发 `end`/`error` 消息，但 `LiveEvents` 未注册处理，回复被丢弃；清理的 `request_id` 也从未加入任何 `wait` 列表，因此**无法得知清理是否成功**。
- **附**：`_check_for_clean` 只被 `onUploadEnd` 调用，所以 `auto_clean=True` + `auto_upload=False` 时清理**完全不会执行**，而 `_free_state_memory` 仍以 `'cleaned'` 为 `final_status`。

### B7.5 状态机为隐式、分散、无类型
- **位置**：`liveevents.py` 全篇，核心结构 `state_dict[group_id][idx][vtype]['status'|'file'|'wait']`
- **现象**：状态是裸字符串 `None / 'ready' / 'rendering' / 'uploading' / 'uploaded' / 'cleaned'`，写入点分散；完成判定靠 `_free_state_memory` 反向扫描"是否都等于 `final_status`"。
- **后果**：没有集中的状态转移表；`final_status` 由 `auto_upload`/`auto_clean` 两个开关推导，组合语义不直观。
- **注**：`state_dict` 与 `ended_dict` 的键语义不同——前者是录制会话 `sess_id`，后者复用同一键名但当"结束时间戳"用。`ended_dict` 若被写入非数值（如 `True`），`time.time() - True` 不会报错而是得到巨大值，使 72 小时超时分支**立即误删整组状态**。生产路径写入的是 `time.time()`，当前安全，但类型约束缺失。

### B7.6 基类事件与注册表不对齐
- **位置**：`baseevents.py` 定义了 21 个 `onXxx` 钩子，`liveevents.py` 只注册 13 个键
- **现象**：`onCleanEnd`、`onRenderStart`、`onUploadStart`、`onLiveError` 等既未被调用也未被注册，属纯死代码；基类形同文档，且与实际协议不一致。

### B7.7 任务装配与配置校验
- **位置**：`liveevents.py`（`self.config['download_args']['dltype']`、`['render_args']['transcode']`、`['upload_args']`、`['clean_args']`）
- **现象**：这些键只在 `Config.add_task_config` 里按 `common_event_args` 的开关才装载。若任务写了 `auto_clean: True` 但没有 `clean_args` 段，事件处理时 `KeyError`；错误信息不会指出是配置缺项。
- **建议**：装配阶段做一次性 schema 校验并给出明确报错，而不是等到事件回调里才炸。

### B7.8 消息流可观测性不足
- **位置**：`replaytask.py:50-51` 静默兜底
- **现象**：未注册事件只在 `default` 也存在时打一行 `info`，无法区分"预期外事件"与"正常心跳"。
- **注**：`engine.py` 侧已在本次改动中改为**告警并带上 `source`/`event`**（见 CHANGELOG），但 Task 侧仍是静默兜底。

---

## 4. 架构级重构（方向已对齐，尚未开工）

### B8.1 待解决的四个具体诉求
1. **支持复杂的处理逻辑**：录制后加后处理；对弹幕版/源视频能分别处理与上传（当前可做但**写死**）。
2. **易于扩展**：REST API 增删查任务；添加新平台（可能需取流 token）、自定义下载器/上传器。
3. **可以保存状态**：程序关闭后，未上传/未渲染的视频、录一半的视频不丢（用户也可选择从 0 开始）。
4. **可以分模块测试**。

### B8.2 关键事实（已核实）
- `src_video_pre` = 转码前的原始录制流；`src_video` = 转码**结果**，**替代**前者；`dm_video` = 渲染后的弹幕版。
- `w_srcfile` 意为"清理弹幕版时连带清理源文件"；`w_srcpre` 意为"被替代的原始流可清理"。
- 上传续传：B站两个引擎都是**整文件重传**（每次新 `upload_id`）；只有 YouTube 支持字节级续传（`retry_resume` 仅存在于 `upload_args.youtube`）。
- "继续"的真实含义是**持久化上传组的远端稿件 id**，使同组后续分段追加到同一稿件。

### B8.3 分阶段计划

| 阶段 | 内容 | 覆盖诉求 | 风险 | 状态 |
|---|---|---|---|---|
| **P0** | 测试基座 + 为已确认缺陷补回归测试 | 4 | 极低 | ✅ 已完成 |
| **P1** | SQLite 仓储 + 启动对账 + 恢复重驱动 + 上传组归属 | 3 | 低 | ✅ 已完成 |
| **P2** | 内置默认产物图替换 `liveevents.py` 硬编码槽位；可选 `artifacts:` 键用于**追加**产物与 `postprocess` | 1 | 中（默认行为须逐字节不变） | ⬜ |
| **P3** | `PluginRegistry` + `PluginManifest`（含 `options_schema`）+ 现有平台/引擎包装成插件 | 2 | 中 | ⬜ |
| **P4** | REST API v1 + `StatusProjection` + SSE；WebUI 切到新端点 | 2 | 中 | ⬜ |
| **P5** | 产物级 `postprocess` Action 链 + 自定义 `Stage` 示例 | 1 | 中 | ⬜ |
| **P6** | 恢复 UI：`GET /api/v1/recovery` + `resume`/`discard` | 3 | 低 | ⬜ |

### B8.4 预留配置形态（P2/P5 用，**当前不存在，勿照此写配置**）

```yaml
# 可选段；不写 = 使用内置默认产物图（等价于今天的行为）
artifacts:
  compressed:                    # 追加一个新产物
    from: src_video              # 依赖谁（替代或派生）
    stage: transcode
    options: {vencoder_args: [-crf, 28]}
    upload: [{target: custom, command: [...]}]
    clean:  [{method: delete, delay: 86400}]
  src_video:
    postprocess:                 # 产物级后处理
      - {action: command, cmd: [python, watermark.py, '{PATH}']}
      - {action: rclone, remote: 'mydrive:/rec'}
```

### B8.5 参考项目结论（已调研，供 P3/P4 决策）

| 项目 | 状态 | 可搬运的点 |
|---|---|---|
| streamlink | 活跃 | 解析/消费分离（`Plugin` → `Stream` → `StreamIO`）；`_plugins.json` 懒加载路由 + 优先级；侧载插件优先于内置 |
| yt-dlp | 活跃 | `PostProcessor` 链 `run(info) -> (files, info)`；`progress_hooks`；`ExtractorError(expected=)` 区分"用户问题/适配器 bug" |
| stream-rec | **已归档** | 双状态机（易失 `DownloadState` + 持久 `StreamerState`）；`Result<T, Error>` 错误代数；`sealed Action` 后处理 |
| DouyinLiveRecorder | 活跃 | **反例**：模块全局变量当状态、取消靠注释掉 INI 行、无管理 API、**无弹幕实现** |
| biliup | 活跃（已 Rust 重写） | 分层与 `events.rs` 事件契约 |

⚠️ 调研更正：stream-rec **没有** `Plugin`/`LivePlugin` 接口（真实接缝是 `Extractor`/`PlatformDownloader<T>`/`BaseDownloadEngine`/`Danmu`/`Upload`），且**已归档**。

### B8.6 明确不做（避免过度设计）

- 不引入 Celery/RabbitMQ/Redis：单机场景等于用 3 个进程替换 SQLite + 线程池。
- 不全面 asyncio 化：IO 是阻塞的（ffmpeg/streamlink/yt-dlp/子进程管道），且 `asyncio.Queue` 官方明确非线程安全。
- 不做完整 CQRS/事件溯源：只需一个 projection + 一张追加表。
- 不在有真实第三方插件前造完整 hookspec 插件 API。
- 不给录制会话套熔断器："直播结束"是正常输入。
- 不建通用凭据体系（用户已明确）。

---

## 5. 验证待办（需用户授权联网）

| 编号 | 内容 | 说明 |
|---|---|---|
| C2 | B站弹幕只读联网验证 | 仅取 WS token、不建流，验证 `uid` 与 headers 行为（**需授权联网**） |
| C3 | 斗鱼拉流只读联网验证 | 仅取流地址、不录制，验证 cookie 是否真正参与请求（**需授权联网**） |

> C1（模块级测试基座）与 C4（`dryrun.py` 端到端冒烟）已完成，见 CHANGELOG。

---

## 6. 环境与基础设施记录

- [x] 工作区根目录 Windows 文件权限修复（缺 `WRITE_OWNER`）—— 已用捆绑脚本修复并验证。
      - 备份与回滚：`D:\Code\_dsh-acl-recovery\acl-backup-5c77c8190ba74f19bda1b2ba0bcc9690.json` / `.ps1`
- [x] `DMR/**/__pycache__` 的 `.pyc` 写入被拒 —— 一律使用 `python -B` / `PYTHONDONTWRITEBYTECODE=1` 运行。
- [x] `DMR/state/` 下部分文件对**脚本写入**受限（`PermissionError`），需用编辑工具修改。
- [x] 删除/移动已存在目录可能被沙箱拦截，需要一次性完整权限批准。
- [x] 测试目录命名为 `unit_tests/`（非 `tests/`）：`.gitignore` 的 `/test**` 会忽略后者。
- [x] 目录职责约定：
      - `tools/` —— 仅"调用第三方软件的材料"，外加 `tools` 包本身
        （`check_env.py` 被 `main.py`/`dryrun.py`/`update.py` 引用；
        `mem_probe_inproc.py` 被 `main.py` 以 `DMR_MEM_PROBE=1` 可选启用）。
      - `unit_tests/` —— 全部测试与**测试运行器**。
      - `.dev/` —— 开发/诊断脚本（开发用，`/. **` 使其被 git 忽略）。
- [x] 文档已统一到 `docs/`：`CHANGELOG.md`、`TODO.md`、`project_state.md`、
      `maintainer-log.md`、`installation.md`、`usage.md`（全部小写命名）。

---

## 7. 文档事故记录（如实保留）

整理文档结构时，曾用脚本把 `TODO.md` 从 1214 行截断到 645 行，**误删了当时的
C/D/E/F 等章节**。该文件未被 git 跟踪且没有备份，无法完整还原。

- **错误**：对未被版本控制的重要文档执行"截断重写"，且未先备份。
- **教训**：整理文档结构应逐段编辑，或先复制副本；对未跟踪文件尤其不能做破坏性重写。
- **现状**：本次已按会话内实际执行结果重建（内容可靠），但**原始措辞可能已丢失**。
