# 维护记录（已完成工作明细）

> **面向开发者与后续维护会话。**
> 相关文档：[更新说明](CHANGELOG.md) ·
> [项目当前状态](project_state.md) ·
> [待办清单](TODO.md) ·
> [测试说明](../unit_tests/README.md) ·
> [返回 README](../README.md)
>
> 本文件记录**已完成**工作的技术细节：根因、实现要点、验证证据、踩过的坑与取舍。
> 目的是让后续维护者不必重新推导一遍。

---

## 1. 状态持久化与启动对账（P1）

### 1.1 新增模块 `DMR/state/`

单一功能模块（未新建顶层目录）：

| 文件 | 职责 |
|---|---|
| `__init__.py` | 对外唯一入口 |
| `enums.py` | `ArtifactKind` / `ArtifactState` / `UploadGroupState` + 取值容错 |
| `schema.py` | DDL、模式版本（**v2**）、迁移框架 |
| `repository.py` | `StateRepository`：会话/产物/上传组读写，`RLock` 线程安全 |
| `payload.py` | 产物可变字段的 JSON 载荷编解码 |
| `keys.py` | 产物标识格式单一出处 |
| `reconciler.py` | 启动对账：磁盘对齐、中断处置、过期回收、收集待恢复 |
| `resume.py` | 由产物 + 场次记录重建 `VideoInfo` |

存储：`logs/dmr_state.db`（SQLite + WAL，5 张表：`schema_version`/`sessions`/
`artifacts`/`upload_groups`/`meta`）。

### 1.2 产物存储：「键列 + JSON 载荷」（模式 v2）

**动机**：产物字段会持续扩展（分辨率、编码信息、自定义元数据…）。每个字段建一列
意味着每次扩展都要改表 + 写迁移。

**判据**：会变或未来可能新增、且**不需要**进 SQL 的 `WHERE`/`ORDER BY` 的字段放 JSON。

| 列上（可查询/需约束） | `data` JSON（易变/会扩展） |
|---|---|
| `artifact_id`、`session_id`、`segment_idx`、`kind`、`state`、`updated_at` | `path`、`part_path`、`danmaku_path`、`size`、`duration`、`resolution`、`origin`、`attempts`、`last_error`、`video_info` |

反例：`state` 必须能 `WHERE state NOT IN (...)`，所以留列并建索引。

**迁移 v1 → v2**（`MIGRATIONS[2]`）：`ADD COLUMN data` → `json_object()` 搬迁九个老列
→ 逐个 `DROP COLUMN`。空库路径改为**直接按当前版本建表**，使新库与升级后的老库结构一致。

**容错**（坏数据不能让程序起不来）：

| 情况 | 处理 |
|---|---|
| `data` 为 NULL/空 | 空载荷，全字段走默认值 |
| 非法 JSON / 非对象 | 记 warning，按空载荷处理 |
| 载荷含本版本不认识的键 | **读取时过滤**（否则 `ArtifactRecord(**kwargs)` 抛 `TypeError`）；写入时剔除 |
| 载荷缺键 | 由 dataclass 默认值补齐 |
| `resolution` 字符串 | 读回时还原为 `(w, h)` 元组 |

### 1.3 产物语义（易搞反，已核实）

- `src_video_pre` = 转码**前**的原始录制流
- `src_video` = 转码**结果**，**替代**前者；不转码时它就是原始录制流
- `dm_video` = 渲染后的弹幕版
- `w_srcfile` = "清理弹幕版时连带清理源文件"；`w_srcpre` = "被替代的原始流可清理"
- **弹幕 `.ass` 不是独立产物**：它单独存在没有意义，记录在 `artifacts.danmaku_path` 附属字段

### 1.4 启动对账的分组

| 组 | 内容 |
|---|---|
| 第 0 步 | 净化运行中状态：`RECORDING`→`INTERRUPTED`，`RENDERING`/`UPLOADING`→`RECORDED` |
| A 组 | 磁盘校验：文件是否存在、中断产物处置、缺失标记 |
| C 组 | 上传组封存 |
| D 组 | 回收：`stale_after` 过期抛弃；**已结束且全部产物终态的场次 → 删除**（级联删产物） |

**D4 的推论**：`cleaned` / `uploaded` 都是**终态**，不阻止场次回收。所以"`cleaned` 记录
要不要删"的答案是**已经在自动删**——条件是①场次已结束 ②没有非终态产物。
若场次一直 `ended_at=None`（下播检测没走到），记录才会长期保留。

---

## 2. 恢复重驱动：重启后继续处理未完成的产物

**服务器实测现象**：重启后日志显示"已恢复为 recorded"，但文件**既没改名也没上传**。

**根因是两个独立缺口**：

1. `reconcile()` **只对账、不重跑** —— 它把状态修正到"与磁盘一致"，但不把产物送回处理链；
2. 文件仍是 `[正在录制]...Part000-...` **中间名** —— 分段式引擎只在"下一个分段开始时"
   才由 `segment_callback` 改名，进程在那之前退出就永远停在中间名上。

**隐性前提**：**重建不出 `VideoInfo`**。输出文件名与标题依赖录制当时的元信息
（主播/标题/时间），而库里原本只有路径/大小/时长。

**实现**：

- 产物载荷新增 `video_info`（存整个 `VideoInfo`）。它是 `cpdict`（dict 子类）可直接
  JSON 化，但 `datetime`(`ctime`) 与 `tuple`(`resolution`) 必须显式转换 ——
  **`ctime` 若读回 str，`{CTIME.YEAR}` 这类文件名模板会直接抛异常**。
- `rebuild_video_info()`：首选载荷；缺失或损坏时用**产物字段 + 场次记录**回退重建。
  `streamer` 必须还原为 `StreamerInfo` 而非 dict，否则下游属性访问失败。
- `RecoveryManager.collect_resumable()`：挑出 `RECORDED` + `RENDERED`，累加 `attempts`。
- `LiveEvents.resume_recovered()`：按**原场次**还原成 `state_dict` 分段（状态 `ready`）、
  补做中间名改名，然后交给**既有的** `_check_for_upload` 走同一条链路。

**为什么复用 `_check_for_upload` 而不另写流程**：两条路径（正常录制 vs 恢复）各写一份
渲染/上传/清理逻辑，行为迟早漂移。恢复只负责"把产物还原成正常状态"。

**安全性**：终态永不重跑；`INTERRUPTED` 不自动重跑；只处理当前加载的任务；
改名失败沿用原名继续上传（能上传比名字漂亮重要）；单条失败不连坐。

**已知取舍**：`uploading` 在重启时会被净化回 `recorded`（无法确定远端是否真的收下），
因此**崩溃前已完成的投稿可能被重新上传一次**。跨重启的精确去重做不到。

---

## 3. 恢复判定：不依赖 ffprobe（最终方案）

用户判断：时长探测失败说明**文件坏了、不用恢复**；且判定**不应依赖 ffprobe**。

**规则**（`is_recovered_file_usable`）：

1. 文件名以 `[正在录制]` 开头 —— 分段式引擎写出中间名，说明确实开始录了；已改名的同样正常
2. 文件大小 ≥ `recovery.min_valid_size_mb`（默认 **30MB**）—— 读一次 `stat` 即可

**上传长度门槛同步改**（`liveevents._passes_length_gate`，实时与非实时共用）：
时长已知按 `min_length`；时长**未知或为 0** 时改用文件大小判断 ——
否则恢复出的产物永远传不上去。`0` 与 `None` 同等看待（对已封闭文件，"时长 0 秒"
只意味着元信息没写上）。

**演进过程（保留教训）**：

| 轮次 | 做法 | 问题 |
|---|---|---|
| 第 1 轮 | 用 ffprobe 探测补齐时长 | 探测失败既不等于文件损坏，也让恢复依赖 ffprobe |
| 第 2 轮 | 探测不出就判"文件损坏"并 `skipped` | 仍依赖 ffprobe；没装 ffprobe 的机器上产物全被判死 |
| 最终 | 文件名标记 + 文件大小 | 确定的信号，无需解析容器 |

### ⚠️ 踩坑：哨兵值当返回值

`FFprobe.get_duration` 失败时返回 **`-1`**（不是异常、也不是 `None`）。
若把它当真实时长写进 `VideoInfo`，下游与 `min_length` 比较后判定"太短"，
**产物静默不上传**。凡是"用哨兵值表示失败"的接口，容错时必须显式排除。

### ⚠️ 踩坑：`title=None` 会被渲染成字符串 `"None"`

`replace_keywords` 用 `format_map`：模板里的键在 dict 中**存在**就取其值，
因此 `{'title': None}` 会渲染出 `korooonx-None.mkv`。恢复流程很容易遇到
"载荷里标题是 null"，所以重建时要把空文本字段归一化，并回落场次记录的标题。

---

## 4. 消息路由不再依赖 `replay/` 前缀（生产事故根因）

**现象**：B站稿件**已上传成功**，但状态库里大量产物停在 `recorded`/`uploading`，
`cleaned` 很少，清理不触发。

**根因**：上传器把消息来源原样当作回包目标：

```python
Uploader/__init__.py:167   'source': msg.source          # 来源
Uploader/__init__.py:307   target=task['source']          # 回包时原样当 target
```

而引擎**旧实现只认 `replay/` 前缀**：

```python
elif target.startswith('replay/'):   # 裸任务名落到 else
else:
    self.logger.error(f'Unknown target {target}.')   # 消息丢弃，只留一行日志
```

于是：上传成功 → 回包 `Unknown target` → `LiveEvents.onUploadEnd` **从不执行**
→ 状态不进入 `uploaded` → `_check_for_clean` 只处理 `uploaded` → **清理永不派发**。

**两份日志坐实版本差异**：

| 日志 | liveevents 发出的 source | 结果 |
|---|---|---|
| `.log.2026-10-05`（旧） | `'source': 'twitchpros-yrvz72-0'` | `Unknown target twitchpros-yrvz72-0.` |
| `(3).log`（新） | `'source': 'replay/dds-0'` | 正常路由，清理完整执行 |

状态库时间线吻合：18:47 那批全卡 `uploading`；升级后 19:49–20:02 立刻出现 `cleaned`。

**`replay/` 前缀到底有没有用**（已核实：**没有**）

- 真正解析它的**只有** `engine.pipeSend` 一处；
- `replaytask.py` 判断前缀后**又用裸 `msg.event` 查表**，前缀没参与事件查找；
- `replaytask.py:35` 拼出的 `replay/<task>/<event>` 与 `event_dict` 的键**对不上**；
- 赋给 `msg.source` 的前缀**全代码库无人解析**（只作为 return address 被原样回传）。

结论：它只是命名空间仪式；而"同一件事三种写法 + 无统一自检"正是事故成因。

**修法**：`engine._resolve_target()` 按确定顺序解析 ——
`engine` → `replay/<name>`（**按前缀剥离**，不再 `split('/')[1]`）→ 插件名
（**保留标识优先于同名任务**）→ **裸任务名** → unknown（error 日志带 `source`/`event`）。

---

## 5. 上传组稿件归属

重启后同一上传组复用状态库中的 `remote_id`（bvid），新分段追加到既有稿件。
`biliwebapi` 与 `biliuprs` 均已支持（`resume_bvid` / `get_remote_bvid`）。

**测试抓到的真 bug**：`biliwebapi` 刷新远端数据失败时被误判为"稿件不存在"，
网络抖动即丢失稿件归属（会把一场直播裂成两个稿件）。修法：三态
（成功 / 不存在 / **保持既有**）+ `_KEEP_EXISTING` 哨兵。

**注意**：B站两个引擎都是**整文件重传**（每次新 `upload_id`）；只有 YouTube 支持
字节级续传（`retry_resume` 仅存在于 `upload_args.youtube`）。"继续"的真实含义是
**复用既有稿件 id**，不是断点续传字节。

**不记分 P 清单**：上传组只存 `remote_id`。用户可在 B站增删分 P，记成员清单只会失真。

---

## 6. cookies 过期导致上传失败

上传器实例会被**长期复用**（默认空闲 300 秒释放、最长 7 天）。实例构造时把 cookies
读进内存，期间用户重新登录或 `biliup renew` 刷新了 cookies 文件后，实例内旧 cookies
会让上传失败。

**修法**：`biliwebapi.refresh_cookies()`，**每次 `upload()` 前重新从文件读取**；
读取或解析失败时**保留当前 cookies 并继续尝试**，不让刷新本身中断上传。

---

## 7. 下载引擎内存优化

| 问题 | 实测（修复前） | 修法 |
|---|---|---|
| `Popen(..., bufsize=10**8)` 按该值分配管道缓冲，`stdout=PIPE` 时每个子进程一份 | `Popen` 后 Python 堆 **+190.74 MB**（`bufsize=-1`/`0`/`65536` 均约 0.1 MB）。**只测 RSS 会漏掉这个 bug** | 改为行缓冲 `bufsize=1`（代码本就按行 `readline()` 消费） |
| ffmpeg 监控线程 → 主循环的队列无上界，主循环每次只取 1 行 | 生产快消费慢时 10 秒积压 **1,522,823 行**、RSS **+804.7 MB** | 队列加上界（4096），满时丢弃**最旧**的行 |
| 用 `log += line` 累积整段 ffmpeg 输出 | 15 秒窗口内无行数上界 | 改为固定长度滚动尾缓冲 |
| `streamlink.py` 用 `logfile.read()` 整体读入临时日志 | 56.4 MB 日志 → 堆 **56.4 MB、峰值 170.2 MB**，实际只用到末尾 1000 字符 | 限定读取字节数与尾部读取。峰值降到 **0.13 MB** |

---

## 8. 其他修复

### `_check_for_upload` 空候选列表 `IndexError`
非实时分支在取 `up_videos[0]` 前未判空，全部分段短于 `min_length` 时抛异常并
**打断整个事件处理**（连带跳过 `_free_state_memory`）。改为判空跳过。

### `_check_for_clean` 无条件把状态改成 `cleaned`
赋值语句位于清理规则循环**之外**，只要产物是 `uploaded` 就被置为 `cleaned` ——
**即使没有任何规则命中**，导致"没清理的文件被当作已清理"而提前释放状态。
改为不匹配的规则提前跳过，只在真正派发清理消息时才更新状态。

### `DMREngine.stop()` 在未 `start()` 时崩溃
无条件使用 `self.recv_queue`，未启动时为 `None`。已加保护。

### 斗鱼登录态取流
- 新增 `douyu_watch_cookies`，支持 cookies 字符串 / cookies 字典的 json 文件 /
  浏览器导出的文本文件。
- **cookies 只用于取流请求**；开播判断与房间信息（betard）**始终匿名**。
- 带登录 cookies 时取流走 `JSEngine 签名 + www getH5Play（POST）` —— 实测这是唯一
  能拿到**原画 + 长期有效地址（`expire=0`）**的路径；免签名的 V1 接口带 cookies 会直接失败。
- 默认路径不存在时只记 `debug`；只有用户**显式配置却读不到**时才告警。

### XML 弹幕支持
`render_args.dmrender.dmconvert` 配置段，使**渲染器**与**虚拟录制**都能处理
B站录制格式的 `.xml` 弹幕（可选依赖 `dmconvert`）。本程序自行录制的 `.ass` 不走这里。

---

## 9. 测试基座

`unit_tests/`，标准库 `unittest`，**零新增依赖**。目录名不用 `tests/` 是因为
`.gitignore` 的 `/test**` 会忽略它。

```bash
python -B -m unittest discover -s unit_tests -t .
```

**约定**：`@unittest.expectedFailure` 用于**当前代码的已知缺陷** —— 用例断言的是
"正确行为"，修复后会变成"意外成功"从而提醒移除标记。当前 5 个
（B7.3 两例、B5 三例）。

**测试运行器**（均位于 `unit_tests/`）：

- `unit_tests/_p1_dryrun_runner.py`：`dryrun.py` 的外壳，额外把日志落到固定路径
  `logs/p1-dryrun.log`，便于脚本按固定名字读取。
- `unit_tests/_p1_fullflow_runner.py`：真实执行下载→渲染→上传→清理的验证运行器
  （**会上传**，需授权）。

**目录职责约定**（已整理）：

| 目录 | 放什么 |
|---|---|
| `tools/` | 仅"调用第三方软件的材料" + `tools` 包本身（`check_env.py` 的 `check_pypi`/`check_update` 被 `main.py`/`dryrun.py`/`update.py` 引用，`mem_probe_inproc.py` 被 `main.py` 以 `DMR_MEM_PROBE=1` 可选启用） |
| `unit_tests/` | 全部测试与测试运行器 |
| `.dev/` | 开发/诊断脚本（`mem_probe.py`、`check_douyu_stream.py`）；`/. **` 使其被 git 忽略 |

> `tools/` 在 `[INST]` 中被描述为"第三方工具"，但它在代码里同时是**Python 包**
> （`from tools import check_pypi`），因此不能只放二进制材料 —— 这一点已按实际依赖保留。

---

## 10. 事故与教训

### 10.1 dryrun 曾把测试片段真实上传到账号

早期 `dryrun.py` 把上传 `min_length` 设为 `0`，于是测试片段被**真实上传**到 B站账号
（已确认稿件 `BV1sUHL63EC6`）。

**当前做法**：保留"按当前配置加载全部任务"的原意（这是 dryrun 存在的意义），
但把 `min_length` 抬到测试分段无法满足的值（常量 `DRYRUN_MIN_LENGTH`）——
上传流程不会真正提交稿件。需要测上传链路时把该常量改为 `0`。

> 期间曾一度改成"生成隔离配置 + 隔离状态库"，但那会让 dryrun 不再验证**真实配置**，
> 与它的用途相悖，已还原。

### 10.2 文档被脚本截断

整理文档结构时曾用脚本把 `TODO.md` 从 1214 行截断到 645 行，**误删了若干章节**。
该文件当时未被 git 跟踪且没有备份，无法完整还原。

**教训**：整理文档结构应逐段编辑，或先复制副本；对未跟踪文件尤其不能做破坏性重写。
（该教训在后续文档重组中再次适用 —— `TODO.md` 现位于 `docs/`。）

### 10.3 真机验证发现的两个 bug（模块级测试没抓到）

| # | 问题 | 后果 |
|---|---|---|
| 1 | `_register_session()` 在 `room_info` 赋值**之前**调用 | `AttributeError` 被兜底日志吞掉 → 场次登记失败 → 产物写入触发**外键约束错误** |
| 2 | `_handle_interrupted` 要求"`.part` 不存在"才恢复 | 引擎**直接写最终名**（`part_path == path`）时永远走不到恢复分支 → `keep` 策略形同虚设 |

**教训**：模块级测试用假文件、假引擎，覆盖不到"真实引擎的文件命名时序"与
"属性初始化顺序"。真机跑一次的价值高于再写十个单测。

---

## 11. 验证记录

| 类型 | 方式 | 结论 |
|---|---|---|
| 状态持久化 | 真实直播间 dryrun（分段时间 120s） | 场次与产物落库、对账幂等、`ask`/`keep`/`discard` 三策略正确 |
| 全流程 | 真实执行下载→渲染→上传→清理（5 段 × 300s） | 四阶段全部成功；**5 段全部进同一稿件**；产物全部终态 |
| 恢复重驱动 | 用日志里的真实中间名文件复刻 | 成功改名并派发上传 |
| 恢复判定 | 复刻损坏文件场景（440MB / 10MB） | 大小达标正常派发；不足则标记 `skipped` 且不再重试 |
| 消息路由 | 复刻 uploader 裸任务名回包 | 产物状态 `uploading → uploaded`（修复前消息被丢弃） |
