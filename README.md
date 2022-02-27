# DanmakuRender-2 —— 一个录制带弹幕直播的小工具（版本2）
结合网络上的代码写的一个能录制带弹幕直播流的小工具，主要用来录制包含弹幕的视频流。     
之前的版本是使用AE完成渲染，这个版本可以直接使用Python在录制的时候生成弹幕，然后直接生成视频。     

使用AE渲染的旧版本可以在old分支找到。   

**2022.2.9版本更新：主要修复了直播流错误时无法正常重启的情况**     
2022.2.22更新：修复了弹幕闪烁的问题
2022.2.28更新：增加不录制弹幕的功能

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

### 详细说明
程序运行时可以附带以下参数
#### 录制参数
- `-u` 指定录制链接
- `-n` 指定录制的名称，默认为直播平台+房间号
- `-o` 指定输出文件夹，默认为此目录下的save文件夹
- `-s` 指定视频分块长度（单位：秒），默认为0（不分块），设置为0表示不分块
- `--ffmpeg` 指定`ffmpeg.exe`可执行文件所在路径，设置为ffmpeg则表示使用系统默认值 
- `--timeout` 指定网络中断超时等待时间，默认20秒 
- `--copy` 不录制弹幕，此时不会进行编码，只会复制原始视频流（省很多资源但是没有弹幕）
- `--gpu` 指定显卡类型，可以为AMD或者NVIDIA，设置为none表示不使用显卡辅助编码，**默认使用NVIDIA显卡**    

特别地，如果希望单独指定编码器参数，可以使用以下参数，参数将会覆盖GPU默认选择    

- `--hwaccel` 指定硬件解码器，NVIDIA显卡默认为NVDEC，AMD显卡默认为dxva2
- `--vencoder` 指定视频编码器，NVIDIA显卡默认为H264_NVENC，AMD显卡默认为H264_AMF，不使用硬件加速的话默认为libx264
- `--vbitrate` 指定视频码率，默认为15Mbps，注意码率应该设置为数值+单位，例如10M，10000K等
- `--aencoder` 指定音频编码器，默认为AAC
- `--abitrate` 指定音频码率，默认为320Kbps   

如果程序无法正常判断流的分辨率和帧率（例如部分主播使用了4K120Hz的超高清流）导致录制错误，可以使用以下参数强行指定     

- `--fps` 指定输出帧率
- `--resolution` 指定分辨率，分辨率应该使用x分割，例如1920x1080

#### 弹幕参数
- `--nproc` 指定弹幕渲染进程数，默认为2，如果录制超高清流应该调高
- `--dmrate` 指定弹幕占屏幕的最大比例（即屏幕上半部分有多少可以用来显示弹幕），默认为0.5
- `--startpixel` 指定第一行弹幕开始的高度，默认为20
- `--margin` 指定弹幕行距，默认12
- `--font` 指定弹幕字体，这里要求输入为字体文件的位置或者名称，默认为Windows系统里微软雅黑字体文件(C:\Windows\Fonts\msyhbd.ttc)
- `--fontsize` 指定弹幕字体大小，默认为30
- `--overflow_op` 指定过量弹幕的处理方法，可选ignore（忽略过量弹幕）或者override（强行叠加弹幕），默认ignore
- `--dmduration` 指定单条弹幕持续时间（秒），默认为15
- `--opacity` 指定弹幕不透明度，默认为0.8
- `--resolution_fixed` 使用自适应分辨率模式，也就是说弹幕大小会随分辨率变化而变化，前面设置的是1080P下的大小，默认true

#### 其他参数
- `--debug` 使用debug模式，将录制信息输出到控制台。**新版本不建议使用，错误信息会自动保存为日志文件**
- `--use_wallclock_as_timestamps` 强制使用系统时钟作为视频时钟，默认false
- `--discardcorrupt` 忽略错误的包，默认true
- `--reconnect` ffmpeg级的自动重连，默认false
- `--disable_lowbitrate_interrupt` 关闭低比特率自动重启功能，程序现在会在低比特率时自动重连（低比特率说明录制故障了）
- `--disable_lowspeed_interrupt` 关闭编码过慢自动重启功能（编码速度低说明录制故障或者是资源不足了）
- `--flowtype` 选择流类型，可选flv或者是m3u8，默认flv，此选项仅对B站流生效，在flv流故障或者录制超高清直播时应该设置为m3u8
- `-v` 查看版本号

## 更多
感谢 THMonster/danmaku, wbt5/real-url, ForgQi/biliup     
出现问题了可以把日志文件发给我，我会尽量帮忙修复
