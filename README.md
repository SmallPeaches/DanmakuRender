# DanmakuRender-2 —— 一个录制带弹幕直播的小工具（版本2）
结合网络上的代码写的一个能录制带弹幕直播流的小工具，主要用来录制包含弹幕的视频流。     
之前的版本是使用AE完成渲染，这个版本可以直接使用Python在录制的时候生成弹幕，然后直接生成视频。     

使用AE渲染的旧版本可以在old分支找到。   

## 使用说明
### 前置要求
- Python 3.7+
- Python库 aiohttp,requests,pillow,execjs
- FFmpeg
- 满足条件的NVIDIA或者AMD显卡（也可以不用，但是录制会很占资源并且很卡）

### 安装
- 下载源代码
- 将ffmpeg.exe移动到`tools`文件夹下

### 简单实例
- `python pyrender.py -u https://www.huya.com/712416` 录制虎牙712416直播间，其他选项全部默认
- `python pyrender.py -u https://www.huya.com/712416 -s 3600` 录制虎牙712416直播间，并将文件分成一个小时一块
- `python pyrender.py -u https://www.huya.com/712416 --gpu amd` 录制虎牙712416直播间，使用AMD硬件编码器
- `python pyrender.py -u https://www.huya.com/712416 --fontsize 36` 录制虎牙712416直播间，指定弹幕大小为36
- `python pyrender.py -u https://www.huya.com/712416 --debug` 录制虎牙712416直播间，将录制的具体信息输出（用于debug）

### 详细说明
程序运行时可以附带以下参数
#### 录制参数
- `-u` 指定录制链接
- `-n` 指定录制的名称，默认为直播平台+房间号
- `-o` 指定输出文件夹，默认为此目录下的save文件夹
- `-s` 指定视频分块长度（单位：秒），默认为0（不分块），设置为0表示不分块
- `--ffmpeg` 指定`ffmpeg.exe`可执行文件所在路径，设置为ffmpeg则表示使用系统默认值 
- `--timeout` 指定网络中断超时等待时间，默认20秒 
- `--gpu` 指定显卡类型，可以为AMD或者NVIDIA，设置为none表示不使用显卡辅助编码，**默认使用NVIDIA显卡**    

特别地，如果希望单独指定编码器参数，可以使用以下参数，参数将会覆盖GPU默认选择    

- `--hwaccel` 指定硬件解码器，NVIDIA显卡默认为NVDEC，AMD显卡默认为dxva2
- `--vencoder` 指定视频编码器，NVIDIA显卡默认为H264_NVENC，AMD显卡默认为H264_AMF，不使用硬件加速的话默认为libx264
- `--vbitrate` 指定视频码率，默认为15Mbps
- `--aencoder` 指定音频编码器，默认为AAC
- `--abitrate` 指定音频码率，默认为320Kbps
#### 弹幕参数
- `--nproc` 指定弹幕渲染进程数，默认为2
- `--dmrate` 指定弹幕占屏幕的最大比例（即屏幕上半部分有多少可以用来显示弹幕），默认为0.5
- `--startpixel` 指定第一行弹幕开始的高度，默认为20
- `--margin` 指定弹幕行距，默认12
- `--font` 指定弹幕字体，这里要求输入为字体文件的位置或者名称，默认为Windows系统里微软雅黑字体文件(C:\Windows\Fonts\msyhbd.ttc)
- `--fontsize` 指定弹幕字体大小，默认为30
- `--overflow_op` 指定过量弹幕的处理方法，可选ignore（忽略过量弹幕）或者override（强行叠加弹幕），默认ignore
- `--dmduration` 指定单条弹幕持续时间，注意如果在数字前面加一个+号（例如+15）表示弹幕持续时间将会被规范化为1080P分辨率下的持续时间（也就是说使得弹幕移动速度在不同分辨率下保持一致），默认为+15
- `--opacity` 指定弹幕不透明度，默认为0.8
#### 其他参数
- `--debug` 使用debug模式，将录制信息输出到控制台
- `-v` 查看版本号

## 更多
感谢 THMonster/danmaku, wbt5/real-url, ForgQi/biliup
