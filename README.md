# DanmakuRender-5 —— 一个录制带弹幕直播的小工具（版本5）
结合网络上的代码写的一个能录制带弹幕直播流的小工具，主要用来录制包含弹幕的视频流。     
- 可以录制纯净直播流和弹幕，并且支持在本地预览带弹幕直播流。
- 可以自动渲染弹幕到视频中，并且渲染速度快。
- 支持同时录制多个直播。    
- 支持录播自动上传至B站。     

此版本为全新设计的版本5，包含以下新功能：     
- 支持动态载入配置文件。
- 支持更加复杂的录制、上传、渲染和清理逻辑。
- 支持搬运直播回放或者视频。
- 支持使用webhook与其他录制软件协同。

旧版本可以在分支v1-v4找到。     


## 使用说明
**如果你是纯萌新建议看我B站的专栏安装：https://www.bilibili.com/read/cv26348023**         

### 安装与使用文档      
[**安装文档**](docs/installation.md)       
[**使用文档**](docs/usage.md)     

[**服务器录播示例**](https://github.com/SmallPeaches/DanmakuRender/discussions/368)

### 可选参数
程序运行时可以指定以下参数
- `--config` 指定全局配置文件，默认`configs/global.yml`
- `--version` 查看版本号
- `--skip_update` 跳过版本检查

## 文档索引

### 面向使用者
- [安装文档](docs/installation.md) —— 环境准备与安装步骤
- [使用文档](docs/usage.md) —— 配置项与各项功能的使用说明
- [更新说明](docs/CHANGELOG.md) —— 每个版本改了什么、升级注意事项

### 面向开发者
- [项目当前状态](docs/project_state.md) —— 核实过的架构事实、产物语义、关键决策
- [维护记录](docs/maintainer-log.md) —— 已完成工作的技术明细（根因、实现、踩坑与教训）
- [待办清单](docs/TODO.md) —— **仅记录未完成事项**与已确认的缺陷
- [测试说明](unit_tests/README.md) —— 模块级测试的组织与运行方式

### 测试
本仓库自带模块级测试，运行方式：

```bash
python -B -m unittest discover -s unit_tests -t .
```

> `-B` 用于避免本仓库 `__pycache__` 的写入权限问题（见 `TODO.md` B6）。

需要按**当前配置**做一次完整流程冒烟（180 秒后自动停止任务）：

```bash
python dryrun.py
```

## 更多
感谢 THMonster/danmaku, wbt5/real-url, ForgQi/biliup, ForgQi/stream-gears 的工作。     
出现问题欢迎大家提issue讨论。       

**本程序仅供研究学习使用！**
