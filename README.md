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
在内存充足的情况下，每渲染一千条弹幕大约需要五分钟，占用内存8G。如果内存不足渲染速度会大幅下降，建议每次渲染数量不超过1000条。  
**注意：如果在运行脚本之前AE未打开，则渲染完成并保存后AE会自动关闭，尽量保证在AE未打开任何项目时渲染弹幕**  

### 详细说明
#### 录制选项
运行`main.py`时可以附带以下参数：
- `-u` 指定录制链接
- `-n` 指定录制的名称，默认为replay
- `-o` 指定输出文件夹，默认为此目录下的save文件夹
- `-s` 指定视频分块长度（单位：秒），默认为3600（一个小时一个文件），设置为0表示不分块
- `-m` 监视此直播间。如果使用此参数则程序会一直监视直播间，并在开播时自动录制，直到用户主动关闭。如果不使用此参数则程序会在直播结束时结束。默认无此参数
- `--ffmpeg` 指定`ffmpeg.exe`可执行文件所在路径
- `--record` 指定录制类型为以下三种：danmu（只录制弹幕），video（只录制视频），all（都录制），默认为all  

#### 渲染选项
运行`render.py`时可以附带以下参数：
- `-f` 指定弹幕文件路径
- `-o` 指定保存脚本的位置，如果为空则表示直接运行脚本而不保存，默认为空。**但是建议先保存脚本再运行，这样会提高效率**
- `-a` 指定AE的主程序AfterFX.exe所在路径，默认为auto，由程序自己搜索
- `--nosave` 指示AE不主动保存项目，也就是只渲染到AE的窗口，**如果AE此时存在项目，则会在当前项目新建一个合成并渲染，并不会创建新项目**     

关于录制和渲染的详细配置可以修改`config.json`文件。  
附带参数运行会覆盖在`config.json`文件里的设置。 

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
