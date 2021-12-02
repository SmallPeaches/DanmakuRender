# DanmakuRender —— 一个直播录制和弹幕渲染的小工具
结合网络上的代码写的一个直播录制和弹幕渲染的小工具，大概功能如下：      
- 录制直播流
- 录制直播弹幕
- 将弹幕渲染为AE项目
## 使用说明
### 前置要求
#### 录制
- Python 3.7+
- Python库 aiohttp,requests 
- FFmpeg
#### 弹幕渲染
- Windows平台
- Python 3.7+
- Adobe After Effects CC （建议使用Adobe After Effects CC2018及以上）
### 安装
- 下载源代码
- 将ffmpeg.exe移动到`tools`文件夹下 （如果不移动需要修改`config.json`里的ffmpeg路径）
### 简单使用
#### 录制
运行`main.py`，按要求输入URL，如果出现正在录制xxx的提示说明录制开始。   
录制的视频会存放在`save`文件夹中。
#### 渲染弹幕
运行`render.py`，按要求输入弹幕文件路径。  
此时将会直接打开AE程序，运行完成后AE会提示保存项目，选择保存路径即可。
**注意：AE在项目保存后可能会关闭，尽量保证在AE未启动或者AE未打开任何项目时渲染弹幕**

