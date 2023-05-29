# DanmakuRender-4 —— 一个录制带弹幕直播的小工具（版本4）
结合网络上的代码写的一个能录制带弹幕直播流的小工具，主要用来录制包含弹幕的视频流。     
- 可以录制纯净直播流和弹幕，并且支持在本地预览带弹幕直播流。
- 可以自动渲染弹幕到视频中，并且渲染速度快。
- 支持同时录制多个直播。    
- 支持录播自动上传至B站。

旧版本可以在分支v1-v3找到。     

2023.4.30更新：添加新的streamgears下载引擎，修改部分代码逻辑     
2023.3.5更新：添加自动上传功能，修改默认分支为v4        
2023.1.6更新：更新版本4，优化逻辑       

### BUGS
- Python3.10及以上版本录制斗鱼弹幕失败？      
  请使用Python3.9版本录制。  
- 在主播意外断流恢复之后（例如PK结束和开始的时候）视频出现花屏？    
  修改下载引擎为streamgears，具体方法见下文示例.

## 使用说明
**如果你是纯萌新建议看我B站的专栏安装：https://www.bilibili.com/read/cv22343026**         
### 前置要求
- Python 3.7+
- Python库 aiohttp,requests,execjs,lxml,yaml
- FFmpeg
- 满足条件的NVIDIA或者AMD显卡（也可以不用，但是渲染弹幕会很卡）    

### 安装
- 下载源代码
- 下载ffmpeg，将ffmpeg.exe和ffprobe.exe移动到`tools`文件夹下    
- 下载biliup-rs可执行文件（https://github.com/biliup/biliup-rs/releases ），将其放到`tools`文件夹下或者修改配置文件。

### 使用方法
新版本使用yaml配置文件的方法来指定参数，配置文件一共有两个，分别为`default.yml`（默认配置文件）和`replay.yml`（录制配置文件），
一般情况下默认配置文件不需要修改，只需要修改录制配置文件，**程序第一次启动时会自动创建配置文件**。      
启动程序可以直接运行`python main.py`，不需要附带参数。    

录制配置文件内录制任务应该满足如下格式
```yaml
replay: # 一个数组，每个元素表示一个录制任务
  - url: <url>   # 第一个任务
    <录制参数>: <参数值>  # 可选  
    ...
  - url: <url>   # 第二个任务
    ...
  ...
```

录制配置文件示例如下：      
- 录制B站13308358直播间
```yaml
replay:
  - url: https://live.bilibili.com/13308358
```

- 录制B站13308358直播间，指定分段时间1800秒
```yaml
replay:
  - url: https://live.bilibili.com/13308358
    segment: 1800
```

- 录制多个直播间，并且指定不同的分段时间，
```yaml
replay:
  - url: https://live.bilibili.com/13308358
    segment: 1800
  - url: https://live.bilibili.com/23197314
    segment: 3600
    danmaku: false   # 指定此任务不需要录制弹幕                    
```

高阶用例：
- 使用不同的下载引擎
```yaml
replay:
  - url: https://live.bilibili.com/13308358
    engine: streamgears   # 使用streamgears作为下载引擎
    vid_format: flv       # 使用streamgears作为下载引擎时，录制格式只能是flv
```
注意：使用streamgears作为下载引擎时，录制格式只能是flv，使用其他格式可能会导致意外错误     

- 使用其他种类的编码器
```yaml
# replay.yml
render: 
  hwaccel_args: [-hwaccel,cuda,-noautorotate] # 硬件解码参数，不同平台设置不一样，一般情况下不是N卡都设置为空比较好
  vencoder: hevc_nvenc                        # 使用NVIDIA NVENC H.265编码器
  vencoder_args: ['b:v','15M']                # 特殊指定编码器参数，可用参数根据编码器不同而不同

replay:
  - url: https://live.bilibili.com/13308358
```
注意：可用编码器根据平台不同而不同，目前比较常用的编码器如下：

| 编码类型   | 编码器  |   注释 |
| :-------: | :-------: | :-------: |
| H.264 |   h264_nvenc   |  N卡使用 |
| H.264 |   h264_amf   |  A卡使用 |
| H.264 |   libx264   |  纯CPU编码使用 |
| H.264 |   h264_qsv   |  Intel集成显卡使用 |
| H.265(HEVC) |   hevc_nvenc   |  N卡使用 |
| H.265(HEVC) |   hevc_amf   |  A卡使用 |
| H.265(HEVC) |   libx265   |  纯CPU编码使用 |
| H.265(HEVC) |   hevc_qsv   |  Intel集成显卡使用 |

一般情况下不建议使用H.265编码器，因为编码慢很多，除非是自己本地存档需要节省磁盘空间。       

- 使用伪4K绕过B站码率限制
```yaml
# replay.yml
render: 
  output_resize: 3840x2160  # 设置渲染的带弹幕视频的分辨率，3840x2160正好是16:9的4K视频

replay:
  - url: https://live.bilibili.com/13308358
```
现在B站的普通1080P视频最高码率一般不超过2Mbps(AV1编码)，本地看视频不糊但是传B站就糊就是这个原因。
为了绕开这个限制，需要使用伪4K的功能，简单地说就是把视频缩放到4K，让B站以为是4K视频然后按4K分配码率，最后看的时候就会很清晰。
当然，你愿意的话甚至可以缩放到8K（7680x4320），不过渲染速度的话就不好说了，并且一般情况下4K已经能分到15M的码率了，8K分30M的码率没什么必要。

带自动上传功能的录制     
**注意此功能正在测试，可能遇到意料之外的问题，记得拿小号测试！**    
上传功能由biliup-rs支持，请先下载biliup.exe可执行文件到tools文件夹，biliup-rs项目地址：https://biliup.github.io/biliup-rs/index.html     
简单上传，只上传到b站的一个账号：    
```yaml
replay:
  - url: https://live.bilibili.com/13308358
    upload:                     # 指定此任务需要自动上传
      src_video: bilibili       # 指定上传源视频到B站
      dm_video: bilibili        # 指定上传弹幕视频到B站
```
在此任务中，视频会上传到B站的默认账号，弹幕视频和源视频将会分别上传，上传任务会在直播结束后进行。如果不想上传源视频就删掉src_video那一条。    
如果需要复杂的上传，则必须先在录制配置文件中创建一个上传器，然后对不同任务使用不同上传器上传：
```yaml
# replay.yml
upload:                         # 创建上传器
  bzhan-1:                      # 上传器名称，可以随便写但是不能重复
    title: '直播回放1号'         # 接下来的参数就是default.yml里面的自动上传参数
                                # 相当于可以单独设置上传的标题什么的
  bzhan-2:
    title: '直播回放2号'

replay:
  - url: https://live.bilibili.com/13308358
    upload:                     # 指定此任务需要自动上传
      src_video: bzhan-1        # 指定上传源视频到第一个上传器
      dm_video: bzhan-2         # 指定上传弹幕视频第二个上传器
``` 
多个上传器之间按照cookies来区分，默认保存cookies到`.temp/<上传器名称>.json`，如果想把多个上传器指定到一个账号则需要手动指定cookies到相同的路径。    
**特别提醒：cookies内包含了登录信息，不要将他分享给任何人！**

### 注意事项
- 程序的工作流程是：先录制一小时直播，然后在录制下一小时直播时启动对这一小时直播的渲染。录制完成后可以同时得到直播回放和带弹幕的直播回放（分为两个视频）
- 程序默认使用NVIDIA的硬件编码器渲染，如果用A卡的话需要修改参数。如果不渲染弹幕就不用管。
- 在关闭程序时，如果选择了自动渲染弹幕，则一定要等录制结束并且渲染完成再关闭（由于程序设定是先录制后渲染），否则带弹幕的录播会出问题。
- 如果因为配置比较差，渲染视频比较慢导致渲染比录制慢很多的，可以选择先不渲染弹幕，在录制结束后手动渲染。（这种情况比较少见，因为渲染的速度很快，我1060的显卡都可以同时录两个直播）
- 在录制的过程中弹幕保存为一个字幕文件，因此使用支持字幕的播放器在本地播放录播可以有弹幕的效果（**就算是没渲染弹幕也可以！**），拿VLC播放器为例，在播放录像时选择字幕-添加字幕文件，然后选择对应的ass文件就可以预览弹幕了。 
    

### 默认参数说明
#### 关键字替换说明
一些名称可以使用关键字替换，{xxx}这样的说明把这个东西在程序运行时动态换成指定的内容。例如：
`{STREAMER}-{YEAR}年{MONTH}月{DAY}日{HOUR}点{MINUTE}分` 在执行时大概会是这个样子：
`飞天狙想要努力变胖-2023年3月1日20点30分`。         
可用关键字：
{STREAMER}主播名称，{TITLE}标题，{HAS_DANMU}“带弹幕版”这几个字，{URL}直播间链接
{YEAR}年，{MONTH}月，{DAY}日，{HOUR}点，{MINUTE}分，{SECOND}秒       
**注意：具体参数以default.yml为准.**
```yaml
# FFprobe 可执行程序地址，为空自动搜索
ffprobe: ~
# FFmpeg 可执行程序地址，为空自动搜索
ffmpeg: ~
# biliup-rs可执行文件地址，为空自动搜索
biliup: ~

# 录制参数
downloader:
  # 录制输出文件夹，设置为空则使用主播名称作为文件夹
  output_dir: ./直播回放

  # 录制文件名称格式，可使用关键字替换，默认效果：飞天狙想要努力变胖-2023年3月1日20点30分，注意这里不能含有冒号，斜杠等非法字符！！
  output_name: '{STREAMER}-{YEAR}年{MONTH}月{DAY}日{HOUR}点{MINUTE}分'

  # 录制程序引擎，可选ffmpeg（由ffmpeg提供拉流服务）或者streamgears（使用streamgears提供拉流服务，此功能正在测试）
  # 在使用streamgears作为录制引擎时，录制视频格式只能是flv
  engine: ffmpeg

  # 录播分段时间（秒），默认一个小时
  segment: 3600

  # 是否录制弹幕
  danmaku: True

  # 是否录制直播流
  video: True

  # 启动自动渲染
  auto_render: True

  # 延迟下播计时（分钟）
  end_cnt: 1

  # 默认分辨率，如果程序无法正常判断流的分辨率可以使用以下参数强行指定
  resolution: [1920,1080]

  # 录制视频的格式，默认mp4，如果经常遇到文件损坏播不了可以选择flv或者ts
  # 使用streamgears作为录制引擎应该使用flv
  vid_format: mp4

  # 直播流CDN选项
  # 对于虎牙直播，此项可选al, tx, hw等cdn服务器的缩写，默认al
  # 对于B站，此项可选0-n表示不同的cdn服务器，默认为0
  # 斗鱼和抖音暂时没用
  flow_cdn: ~

  # ffmpeg http参数
  # 使用streamgears作为录制引擎时不生效
  ffmpeg_stream_args: [-fflags,+discardcorrupt,-reconnect,'1',-rw_timeout,'10000000',
                        '-analyzeduration','15000000',
                        '-probesize','50000000',
                        '-thread_queue_size', '16']
  
  # 关闭下载过慢自动重启功能，默认false
  # 使用streamgears作为录制引擎时不生效
  disable_lowspeed_interrupt: False

  # 检测流变化，在推流信息变化时立即分段，默认true
  # 使用streamgears作为录制引擎时不生效
  check_stream_changes: True
  
  # 以下是弹幕录制参数

  # 弹幕行距，默认6
  margin: 6

  # 指定弹幕占屏幕的最大比例（即屏幕上半部分有多少可以用来显示弹幕），默认为0.4
  dmrate: 0.4

  # 指定弹幕字体，默认为微软雅黑字体(Microsoft YaHei)
  font: Microsoft YaHei

  # 指定弹幕字体大小，默认为36
  fontsize: 36 

  # 指定过量弹幕的处理方法，
  # 可选ignore（忽略过量弹幕）或者override（强行叠加弹幕），默认override
  overflow_op: override

  # 指定单条弹幕持续时间（秒），默认为16
  dmduration: 16

  # 指定弹幕不透明度，默认为0.8
  opacity: 0.8

  # 使用自适应弹幕大小（会让把设置的弹幕大小按1080P标准缩放）
  auto_fontsize: True

  # 弹幕描边颜色(6位十六进制)
  outlinecolor: 000000

  # 弹幕描边宽度
  outlinesize: 1.0
  
  # 弹幕延迟补偿（秒），一般情况下弹幕比视频慢，设置这个强行把弹幕提前，不同直播间不一样
  dm_delay_fixed: 3.0

  # 弹幕录制程序自动重启间隔（在没人发弹幕的时候会定时重启，保证录制正常，默认300秒，0关闭）
  dm_auto_restart: 300

# 渲染参数
render:
  # 渲染输出文件夹，默认为空（在录制输出文件夹后面加上“带弹幕版”）
  output_dir: ~

  # 生成的视频文件格式，默认mp4
  format: mp4

  # 渲染引擎，可选ffmpeg（纯ffmpeg渲染）或者python（Python PIL作为弹幕的图像渲染器，ffmpeg作为视频编码器，此功能正在测试，请勿使用）
  engine: ffmpeg

  # 硬件解码参数，NVIDIA显卡默认使用cuda硬件解码器，AMD显卡或者CPU设为空
  hwaccel_args: [-hwaccel,cuda,-noautorotate]

  # 视频编码器，NVIDIA设置为h264_nvenc，AMD设置为h264_amf，CPU设置为libx264
  vencoder: h264_nvenc

  # 视频编码器参数，默认恒定码率15Mbps
  vencoder_args: [-b:v, 15M]

  # 音频编码器
  aencoder: aac

  # 音频编码器参数，默认恒定码率320Kbps
  aencoder_args: [-b:a,320K]

  # 输出重缩放，会把输出重缩放到指定分辨率，可以设置为'3840x2160'用于在B站传伪4K保证清晰度
  output_resize: ~

  # 以下参数只适用于python渲染器
  # 渲染线程数（单个渲染器使用的进程数量），默认2
  nproc: 2

  # 渲染管道缓冲区大小（MB）
  bufsize: 100

  # 弹幕重排序
  danmaku_resort: False

# 自动上传参数
uploader:
  # 上传目标（目前只有B站）
  bilibili:
    # 上传引擎，目前只能选biliuprs
    engine: biliuprs

    # 登录信息保存的cookies路径，默认<上传器名字>.json
    cookies: ~

    # 上传的视频最短长度，小于此长度的视频会被自动过滤，默认五分钟
    min_length: 300

    # 以下参数来自biliuprs，详细内容可以参考 https://biliup.github.io/biliup-rs/index.html
    # 上传线路
    line: bda2

    # 上传线程数
    limit: 3

    # 是否为转载视频 1-自制 2-转载
    copyright: 1

    # 转载来源
    source: ''

    # 分区号，分区参考 https://biliup.github.io/tid-ref.html
    tid: 65

    # 封面
    cover: ''

    # 标题，可以使用关键字替换
    # {STREAMER}主播名称，{TITLE}标题，{YEAR}年，{MONTH}月，{DAY}日，{HAS_DANMU}“带弹幕版”这几个字，{URL}直播间链接
    # 默认的例子：[飞天狙想要努力变胖/直播回放] 晚上七点半比赛 2023年2月24日 （带弹幕版）
    title: '[{STREAMER}/直播回放] {TITLE} {YEAR}年{MONTH}月{DAY}日 {HAS_DANMU}'

    # 简介，可以使用关键字替换
    desc: "{STREAMER}: {URL} \n直播回放 {TITLE} {YEAR}年{MONTH}月{DAY}日 {HAS_DANMU} \nPowered by DanmakuRender \nhttps://github.com/SmallPeaches/DanmakuRender"
    
    # 动态内容，可以使用关键字替换
    dynamic: ''

    # 互动视频
    interactive: 0

    # 标签（一定要有！多个标签逗号分割）
    tag: '直播回放'

    # 延迟发布，单位秒
    dtime: 0

    # 是否开启杜比音效? 0-关闭 1-开启
    dolby: 0

    # 允许转载? 0-允许转载，1-禁止转载
    no_reprint: 1

    # 是否开启充电? 0-关闭 1-开启
    open_elec: 1
```
### 可选参数
程序运行时可以指定以下参数
- `-c` 指定录制配置文件位置，默认replay.yml
- `--default_config` 指定默认配置文件位置，默认default_config.yml
- `--render_only` 自动渲染录像文件夹里的视频
- `--input_dir`  和`--render_only`参数一起使用，可以指定需要渲染的文件夹
- `--version` 查看版本号

## 更多
感谢 THMonster/danmaku, wbt5/real-url, ForgQi/biliup,ForgQi/stream-gears      
出现问题了可以把日志文件发给我，我会尽量帮忙修复
