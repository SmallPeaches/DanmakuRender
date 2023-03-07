# DanmakuRender-4 —— 一个录制带弹幕直播的小工具（版本4）
结合网络上的代码写的一个能录制带弹幕直播流的小工具，主要用来录制包含弹幕的视频流。     
- 可以录制纯净直播流和弹幕，并且支持在本地预览带弹幕直播流。
- 可以自动渲染弹幕到视频中，并且渲染速度快。
- 支持同时录制多个直播。    
- 支持录播自动上传至B站（正在测试，可能遇到很多问题！！！）。

### 注意：默认分支已经修改为v4，使用方法和B站的专栏的教程有出入，请以本文为准！！
旧版本可以在分支v1-v3找到。   

**BUG：Python3.10及以上版本可能会导致部分平台录制弹幕出现问题，请使用Python3.7版本录制**           
2023.3.5更新：添加自动上传功能，修改默认分支为v4        
2023.1.6更新：更新版本4，优化逻辑       
2022.10.13更新：修改了API逻辑，而且现在可以支持录制不带弹幕的抖音直播        
2022.8.1更新：版本3.1和在线弹幕渲染的新功能（暂时只支持MDY的几个主播）        
2022.5.30版本更新：更新了版本3    
2022.2.9版本更新：主要修复了直播流错误时无法正常重启的情况    
2022.2.22更新：修复了弹幕闪烁的问题    
2022.2.28更新：增加不录制弹幕的功能

## 使用说明
### 前置要求
- Python 3.7+
- Python库 aiohttp,requests,execjs,lxml,yaml
- FFmpeg
- 满足条件的NVIDIA或者AMD显卡（也可以不用，但是渲染弹幕会很卡）    

### 安装
- 下载源代码
- 将ffmpeg.exe和ffprobe.exe移动到`tools`文件夹下    

### 使用方法
新版本使用yaml配置文件的方法来指定参数，配置文件一共有两个，分别为`default.yml`（默认配置文件）和`replay.yml`（录制配置文件），
一般情况下默认配置文件不需要修改，只需要修改录制配置文件。      
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

带自动上传功能的录制（实验性功能）     
**注意此功能正在测试，可能遇到意料之外的问题，真的要用记得拿小号测试！**    
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
**注意：具体参数以default.yml为准.**
```yaml
# FFprobe 可执行程序地址，为空自动搜索
ffprobe: ~
# FFmpeg 可执行程序地址，为空自动搜索
ffmpeg: ~

# 录制参数
downloader:
  # 录制输出文件夹，设置为空则使用主播名称作为文件夹
  output_dir: ./直播回放

  # 录制文件名称格式，可使用关键字替换，默认效果：飞天狙想要努力变胖-2023年3月1日20点30分
  output_name: '{STREAMER}-{YEAR}年{MONTH}月{DAY}日{HOUR}点{MINUTE}分'

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

  # 录制视频的格式，默认mp4，如果经常遇到文件损坏播不了可以选择ts
  vid_format: mp4

  # 录制程序引擎，只能是ffmpeg
  engine: ffmpeg

  # 直播流CDN选项
  # 对于虎牙直播，此项可选al, tx, hw等cdn服务器的缩写，默认al
  # 对于B站，此项可选0-n表示不同的cdn服务器，默认为0
  # 斗鱼和抖音暂时没用
  flow_cdn: ~

  # ffmpeg http参数
  ffmpeg_stream_args: [-fflags,+discardcorrupt,-reconnect,'1',-rw_timeout,'10000000',
                        '-analyzeduration','15000000',
                        '-probesize','50000000',
                        '-thread_queue_size', '16']
  
  # 关闭编码过慢自动重启功能，默认false
  disable_lowspeed_interrupt: False
  
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

# 渲染参数
render:
  # 渲染输出文件夹，默认为空（在录制输出文件夹后面加上“带弹幕版”）
  output_dir: ~

  # 生成的视频文件格式，默认mp4
  format: mp4

  # 渲染引擎，只能是ffmpeg
  engine: ffmpeg

  # 硬件解码参数，NVIDIA显卡默认使用cuda硬件解码器，AMD显卡或者CPU设为空
  hwaccel_args: [-hwaccel,cuda,-noautorotate]

  # 视频编码器，NVIDIA设置为h264_nvenc，AMD设置为h264_amf，CPU设置为libx264
  vencoder: h264_nvenc

  # 视频编码器参数，默认恒定码率15Mbps
  vencoder_args: [-b:v,15M]

  # 音频编码器
  aencoder: aac

  # 音频编码器参数，默认恒定码率320Kbps
  aencoder_args: [-b:a,320K]

# 自动上传参数
uploader:
  # 上传目标（目前只有B站）
  bilibili:
    # 上传引擎，目前只能选biliuprs
    engine: biliuprs

    # biliup-rs可执行文件地址
    biliup: tools/biliup.exe

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
感谢 THMonster/danmaku, wbt5/real-url, ForgQi/biliup     
出现问题了可以把日志文件发给我，我会尽量帮忙修复
