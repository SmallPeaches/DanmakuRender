# DanmakuRender-2 —— 一个直播录制和弹幕渲染的小工具（版本2）
结合网络上的代码写的一个能录制带弹幕直播流的小工具，主要用来录制包含弹幕的视频流。     
之前的版本是使用AE完成渲染，这个版本可以直接使用Python在录制的时候生成弹幕，然后直接生成视频。     

使用AE渲染的旧版本可以在old分支找到。   

## 使用说明
### 前置要求
- Python 3.7+
- Python库 aiohttp,requests,pillow,execjs
- FFmpeg
- 附带满足条件的

### 安装
- 下载源代码
- 将ffmpeg.exe移动到`tools`文件夹下

### 简单使用
运行`pyrender.py`，按要求输入URL，如果出现正在录制xxx的提示说明录制开始。   
录制的视频会存放在`save`文件夹中。

### 详细说明
程序运行时可以附带以下参数
#### 录制参数
- `-u` 指定录制链接
- `-n` 指定录制的名称，默认为replay
- `-o` 指定输出文件夹，默认为此目录下的save文件夹
- `-s` 指定视频分块长度（单位：秒），默认为0（不分块），设置为0表示不分块
- `--ffmpeg` 指定`ffmpeg.exe`可执行文件所在路径
- `--record` 指定录制类型为以下三种：danmu（只录制弹幕），video（只录制视频），all（都录制），默认为all  
- `--timeout` 指定网络中断超时等待时间  
- 

#### 实例
- `python main.py -u https://www.huya.com/712416` 录制虎牙712416直播间，如果主播未开播则抛出错误
- `python main.py -u https://www.huya.com/712416 -m` 录制虎牙712416直播间，如果主播下播则一直等待直到开播然后录制
- `python main.py -u https://www.huya.com/712416 -s 0` 录制虎牙712416直播间，录播不分块
- `python main.py -u https://www.huya.com/712416 -s 0 --record danmu` 录制虎牙712416直播间，只录制弹幕，不分块
- `python render.py -f danmu.json` 渲染此文件夹下的danmu.json文件
- `python render.py -f danmu.json -o script.jsx` 渲染弹幕文件为AE脚本script.jsx文件，之后再手动运行

## 更多
如果有bug很正常，因为程序没有经过严格测试，只是一个简单的demo  
感谢 THMonster/danmaku, wbt5/real-url, ForgQi/biliup
