# DanmakuRender-5 使用指南
本文档描述了使用DMR录制直播流、渲染弹幕和上传直播回放的操作方法。    

**目录：**      
[简介](#简介)     
[简易使用](#简易使用)      
[常见问题](#常见问题)       
[完全使用说明](#完全使用说明)      
[特殊功能](#特殊功能)


更新日期：2025.9.21。     

## 简介     
**本程序的主要功能包括：**
- 可以录制纯净直播流和弹幕，并且支持在本地预览带弹幕直播流。
- 可以自动渲染弹幕到视频中，并且渲染速度快。
- 支持同时录制多个直播。    
- 支持录播自动上传至B站和YouTube。
- 支持动态载入配置文件。
- 支持更加复杂的录制、上传、渲染和清理逻辑。
- 支持搬运直播回放或者视频。
- 支持使用webhook与其他录制软件协同（正在开发）。

**程序的使用方法：**      
目前，程序已经可以简单的通过复制和修改录制文件实现多个主播的录制。      
根据需要录制的类型，在`configs`文件夹里复制一份`example-视频下载.yml`或者`example-直播录制.yml`文件，并且重命名为`DMR-<任务名称>.yml`，例如`DMR-飞天狙.yml`。然后修改复制后的文件，每个依照此规则命名的文件都将作为一个录制任务加入录制队列。            

**程序的工作流程：**      
直播录制：先录制一段时间（默认一个小时）的直播，然后在录制下一小时直播时启动对这一小时直播的渲染。录制完成后可以同时得到直播回放和带弹幕的直播回放（分为两个视频，存放于两个不同的文件夹）。上传将在当场直播结束（也就是主播下播之后）开始，上传到B站时会将同一场直播的视频放在同一个视频的不同分P下。        
视频录制：每隔特定时间检查一次链接，判断是否有新视频发布，如果有，则下载视频并上传。

## 简易使用     
根据需要录制的类型，在`configs`文件夹里复制一份`example-视频下载.yml`或者`example-直播录制.yml`文件，并且重命名为`DMR-<任务名称>.yml`，例如`DMR-飞天狙.yml`。然后修改复制后的文件，每个依照此规则命名的文件都将作为一个录制任务加入录制队列。      
推荐将任务名称设置为有意义的名称，这样方便为看是哪个任务在录制。      

运行时在程序目录打开控制台（win10系统shift+右键点击页面空白处，在菜单中选择“在此处打开powershell窗口”，win11在页面右键选择“在终端中打开”），输入`python main.py`执行程序。        
如果你已经可以正常运行程序了，那么也可以直接双击打开`main.py`文件运行。       

设置好配置文件后，你也可以运行`dryrun.py`进行测试，程序将录制三段一分钟的视频，并根据配置文件渲染和上传（**这里的上传会自动设置延迟24小时发布，记得24小时内去B站稿件管理删除**），录制完成后可以自行检查效果。      

如果运行时视频渲染失败，可以运行`render_only.py`手动渲染视频。

### 关键字替换说明      

在一些配置选项中可能会说可用关键字替换，录制文件名称中的`{}`表示在程序运行的过程中自动替换为相应的内容，例如`{CTIME.YEAR}年{CTIME.MONTH}月{CTIME.DAY}日`在运行时会被动态替换为`2023年8月10日`，具体可用关键字如下：  

`{TITLE}` 直播标题/视频标题      
`{URL}` 直播间链接或者视频链接      
`{TASKNAME}` 任务名称（配置文件DMR-后面那个）         
`{SEGMENT_ID}` 视频分段序号，从1开始。录制直播时不能保证数字的连续性，因为录制错误的分段也会占用一个序号        
`{GROUP_ID}` 视频组ID，在录制B站分P视频时此字段代表视频总标题，TITLE代表各分P标题，其他情况下此ID为随机数       
`{CTIME.YEAR}, {CTIME.MONTH}, {CTIME.DAY}, {CTIME.HOUR}, {CTIME.MINUTE}, {CTIME.SECOND}` 直播分段时间/视频上传时间，年月日时分秒，YouTube视频只能精确到天（时分秒都会是0）       
`{STREAMER.NAME}` 主播/UP主名称      
`{STREAMER.URL}` 主播主页/直播间链接      
`{STREAMER.ROOM_ID}` 直播房间号      
`{COVER_URL}` 封面链接（仅YouTube视频可用）     
`{DESC}` 视频简介（仅YouTube视频可用）      
`{TAG}` 视频标签（仅YouTube视频可用）       

实际上，关键字替换使用了Python的字符串格式化功能，也就是可以使用类似`{CTIME.DAY:02d}`的语句来实现自动补0。关键字不区分大小写，所有关键字都会被自动转换为小写，不过出于阅读考虑，仍然推荐使用大写表示。

### 平台兼容性说明      
**B站，斗鱼，虎牙，抖音，CC直播：** 可使用ffmpeg,streamgears录制引擎，并支持录制弹幕。       
**Twitch直播：** 推荐使用streamlink录制，可以传入cookies去除广告（需要在直播间有订阅），使用其他录制引擎也可录制，但是效果不如streamlink。如果未订阅也想去除广告可以使用特殊代理，请参阅[此项目](https://github.com/2bc4/streamlink-ttvlol)，并在配置文件中按要求设置`streamlink_extra_args`。twitch也可以录制弹幕，但是效果一般（因为英文弹幕真的太长了）。      
**其他受streamlink支持的直播：** 可用平台请参考[官方文档](https://streamlink.github.io/plugins.html)，除前述平台外均不支持录制弹幕。     

**B站视频：** 使用yutto录制主播的所有视频，不推荐录制收藏夹，视频合集。        
**YouTube及其他受yt-dlp支持的视频：** 可用平台请参考[官方文档](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md)，除YouTube视频外未经过严格测试。     

**特殊弹幕兼容性说明：**礼物弹幕、进场弹幕只支持抖音，superchat弹幕只支持B站。      


### 配置弹幕渲染参数（**非N卡用户必读！**）       
非N卡用户需要在`config/global.yml`里面修改渲染弹幕的参数，具体描述如下：
```yaml
render_args: 
  # 硬件解码参数，默认自动
  # 请注意，使用远程桌面时auto可能出现问题，请设置为空
  hwaccel_args: [-hwaccel,auto] 
  # 使用NVIDIA H.264编码器，A卡用户设置为h264_amf，I卡设置为h264_qsv，Apple用户设置为h264_videotoolbox，CPU渲染设置为libx264
  vencoder: h264_nvenc   
  # 指定编码器参数，默认15M码率         
  vencoder_args: ['-b:v','15M'] 
  # 输出重缩放，会把输出重缩放到指定分辨率，可以设置为'WxH'直接指定输出分辨率
  # 也可以指定为当前视频的大小倍数，例如 1.5
  output_resize: ~
```
**关于视频码率**：渲染得到的视频默认是15M码率，大约是一个小时7GB，如果觉得视频文件太大可以按比例减小码率，推荐渲染码率设置为原视频的1.2-1.5倍左右。     

**关于编码器及编码器参数**：理论上所有ffmpeg支持的编码器都可以使用，但是更加推荐使用H.264编码器，因为兼容性和速度上H.264比其他编码器都要好。如果希望了解其他可用编码器或者编码器参数，请参阅[FFmpeg官方文档](https://ffmpeg.org/ffmpeg-codecs.html)。

**关于硬件加速**：使用远程桌面或者其他特殊情况下默认的auto解码器可能出现问题，请设置为空，或者使用自定义解码器（解码器参数可以直接填在`hwaccel_args`里面）。    

**关于输出重缩放**：很多人发现视频上传B站之后变糊（尤其是带弹幕的视频），但是本地看又很清晰，主要原因是B站现在对视频的码率做了限制，普通1080P视频码率一般不超过2Mbps(AV1编码)，只有直播的五分之一。   
为了绕过这个限制，需要使用伪4K的功能，简单地说就是把视频缩放到4K（3840x2160），让B站以为是4K视频然后按4K分配码率，这样一般能够分到15M的码率，最后看的时候就会很清晰。      


## 常见问题
1. 渲染失败或者是渲染的视频无法播放？       
最常见的原因是没设置好编码器（比如说A卡没设置 h264_amf 编码器），或者是**显卡驱动没更新**。特别提醒，新版本ffmpeg总会要求新版本的显卡驱动，如果不想重装显卡驱动可以使用旧版本ffmpeg！

2. 渲染太慢？       
首先给一个渲染速度的参考（默认参数，1080P情况下），使用i7-8700H + 1060，渲染速度4-5倍速；i7-12700H + 3060，渲染速度5-6倍速，如果速度大概在这个范围内就不要说慢啦。    
如果慢得很异常，首先检查CPU和GPU占用是否正常（GPU占用只看任务管理器里Video Encoder的占用），如果占用已经接近满了，那就说明是硬件性能瓶颈了。如果都没怎么占用，那就要考虑更新驱动程序，或者调节编码参数了。你可以单独开一个issue讨论一下。     

3. 文件太大？       
请阅读上文的“关于视频码率”根据自己情况修改输出码率。      

4. 显示配置文件读取失败？         
仔细检查配置文件命名和内部的空格和缩进，格式错了就会读取不了配置文件！      

5. 录制出现花屏？       
请尝试使用streamgears或者streamlink录制引擎。       

6. 录制特殊平台（例如twitch, youtube）出现问题？      
请使用streamlink录制引擎，并且关闭弹幕录制。部分平台的部分直播间并不支持录制或者需要特殊设置，具体情况请参考[Streamlink官方文档](https://streamlink.github.io/plugins.html)。       

7. 出现“ffmpeg退出”或者是“弹幕录制错误”的提示？       
如果是偶尔出现且视频正常就不用理会，如果经常出现请使用streamgears录制或者单独提issue讨论。      

8. 如何更新？       
如果更新release版可以直接运行`update.py`，更新测试版可以下载安装包直接覆盖原文件，或者直接重新安装（Python环境不用重新安装，只用程序代码和tools内的文件即可）。     

9. B站强制原画功能出现问题？      
B站现在对一些观看人数较多的主播开启了强制二压的功能，隐藏了原画直播流。这些直播间网页端的原画实际上是蓝光画质，表现为流链接里含有`bluray`或者`prohevc`等字样，或者视频统计信息的encoder字段中有`hevc_n`或者`h264_n`，而不是只有`libobs xxx`。默认情况下录制会程序会自动绕过这个限制录制原画直播流（`stream_cdn,stream_type`设置为空，`engine`设置为`auto`）。       
**但是此功能不一定生效，并且录制可能出现延迟（约10-20s），如果出现问题请关闭强制原画功能（设置engine不为auto即可）。**


## 完全使用说明     
本节介绍配置文件可用的全部选项和功能。一般情况下简易使用已经可以满足90%以上需求，没有特殊需要的话可以不阅读此部分。     

本程序的配置文件分为两个，一个是全局配置文件`configs/global.yml`，一个是录制任务的配置文件`configs/DMR-<任务名称>.yml`。

### 录制任务配置文件
本节介绍录制参数的设置。每个录制任务的名称由其文件名称决定，任务名称不能重复。     
**注意**：一些录制参数是可变类型的，请注意分辨。      
```yaml
# 任务通用参数
common_event_args:
  # 启动自动渲染
  auto_render: False
  # 启动自动上传
  auto_upload: True
  # 启动自动清理
  auto_clean: False
  # 原视频自动转码（可以用于给原视频做伪4K）
  auto_transcode: False


# 下载参数
download_args:
  # 下载类型，设置为live则后面应该接录制直播的参数，设置为videos则后面应该接下载视频的参数
  # 图方便可以直接复制样例的参数
  dltype: live
  # 其他下载参数，具体可选值请参考全局参数中的下载参数部分
  ...

# 单独的渲染设置（可选）
# 如果希望对不同任务设置不同的渲染参数请设置此项
# 这里的可选参数和下文的渲染参数相同，故不再赘述
render_args: 
  # 对每种任务都要单独设置
  dmrender:
    ...
  transcode:
    ...
  
# 自动上传设置（可选）
# 自动上传设置分为三个部分，对应程序生成的三种文件类型，想上传哪种视频就填哪个，不上传就删掉那一部分
# 具体格式见下文
upload_args:
  # 原视频
  src_video:  
    ...
  # 弹幕视频
  dm_video:
    ...

# 自动清理设置（可选）
# 和自动上传一样，自动清理也分为三个部分，可以按需填写
clean:
  # 原视频
  src_video:  
    ...
  # 弹幕视频
  dm_video:
    ...
```

**自动上传的配置格式说明**      
每个视频类型都可以指定一个或者多个上传任务，组成一个数组。特别地，如果只上传一个地方，则可以直接指定参数，不必使用数组，示例如下：
```yaml
# 一种视频只上传到B站的一个账号，以原视频为例
src_video:
  # 上传目标，可选bilibili或者youtube
  target: bilibili
  # 接下来的参数在B站上传参数下选择（详情参考 全局上传参数列表）
  account: smallpeach
  ...
```

```yaml
# 一种视频只上传到B站的多个个账号，以原视频为例
src_video:
  # 这里设置为一个数组，数组的每个元素代表一种上传
  - target: bilibili
    # 接下来的参数在B站上传参数下选择
    account: smallpeach
    ...

  # 这里是数组的第二个元素
  - target: bilibili
    account: smallpeach2
    ...
```

```yaml
# 可以将多种不同类的视频上传到同一个视频下
# 这里的例子是弹幕视频和原视频
src_video+dm_video:
  # 上传目标
  target: bilibili
  # 接下来的参数在B站上传参数下选择（详情参考 全局上传参数列表）
  account: smallpeach
  ...
```

**自动清理的配置格式说明**      
和上传设置类似，自动清理也分为三个部分，每个视频类型可以指定一个或者多个上传任务，组成一个数组。特别地，如果只上传一个地方，则可以直接指定参数，不必使用数组。如果不指定文件类型，将会应用到全部三种文件（example.yml文件就是这样），示例如下：
```yaml
# 自动清理全部内容
clean:
  method: delete
  delay: 172800
```

```yaml
clean:
  # 只清理原视频
  src_video:
    method: delete
    delay: 172800
```

```yaml
clean:
  # 只清理原视频，并且设置多种清理方式
  # 注意，多种清理方式将顺序执行
  src_video:
    # 先复制到一个文件夹
    - method: copy
      dest: /copydir
      delay: 0
    # 再执行删除
    # 这里的延迟计时将从上传完成开始，而不是上一个复制结束开始
    - method: delete
      delay: 172800
```

```yaml
# 不上传原视频，设置在上传弹幕视频时自动清理全部内容
clean:
  method: delete
  delay: 172800
  w_srcfile: true
```

**注意**：清理将会在上传完成之后开始（如果使用边录边传，则每个视频单独计算）。    
如果使用move方法，目标文件夹还可以设置为`*TRASHBIN*`，这样会将文件放到回收站而不是直接删除。这个功能需要额外pip安装pywin32包（Linux下需要安装trash扩展包）。


### 全局配置文件参数列表
此参数列表包括了所有可选的参数，具体可用参数以`configs/global.yml`为准。    

<details>
<summary>点击展开全部可选参数</summary>

```yaml
# ######################
# 此文件非必要不修改！
# ######################

# 第三方工具路径，设置为空将会自动选择
executable_tools_path: 
  ffmpeg: ~
  ffprobe: ~
  biliup: ~

# DMR引擎参数
dmr_engine_args: 
  # 选择组件
  enabled_plugins: ['downloader', 'render', 'uploader', 'cleaner']
  # 是否动态更新配置文件
  dynamic_config: True
  # 动态更新的配置文件路径
  dynamic_config_path: ./configs

# 默认下载参数
download_args:
  # 直播录制
  live:
    # 直播间链接
    # 请填写标准格式链接，例如：https://live.bilibili.com/123456
    url: 
    # 录制程序引擎，可选ffmpeg, streamgears, pyrequests 或者 streamlink
    # 在使用streamgears作为录制引擎时不支持录制B站hls流
    # 建议PC推流的直播使用ffmpeg录制，手机推流的直播使用streamgears录制
    # 录制twitch等特殊平台建议使用streamlink
    # streamlink可用平台请参考 https://streamlink.github.io/plugins.html
    # 默认为auto，由程序自动选择
    engine: auto
    # 录制输出文件夹，设置为空则使用主播名称作为文件夹
    output_dir: ./直播回放
    # 录制文件名称模板
    # 可使用关键字替换，默认效果：飞天狙想要努力变胖-2023年3月1日20点30分，注意这里不能含有冒号，斜杠等非法字符！！
    output_name: '{STREAMER.NAME}-{CTIME.YEAR}年{CTIME.MONTH:02d}月{CTIME.DAY:02d}日{CTIME.HOUR:02d}点{CTIME.MINUTE:02d}分'
    # 录播分段时间（秒），默认一个小时
    segment: 3600
    # 录制视频的格式，默认flv
    output_format: flv
    # 是否录制弹幕
    danmaku: True
    # 是否录制直播流
    video: True
    # 延迟下播计时（分钟）
    # 使用这个功能可以把主播短暂下播又开播认定为同一场直播
    stop_wait_time: 120
    # 直播流选项
    # 使用streamlink录制时不生效
    stream_option:
      # 直播流CDN
      # 对于虎牙直播，此项可选al, tx, hw等cdn服务器的缩写
      # 对于B站，可选特定的CDN域名前缀，例如：c1--cn-gotcha208
      # 或者正则匹配特定CDN，例如：.*cn-gotcha.*
      # 默认为空，由程序随机选择可用cdn
      stream_cdn: ~
      # 直播流类型（暂时只对B站生效）可选flv，hls，avc，hevc，av1
      # 注意hls流无法使用streamgears录制
      # 如果需要同时指定codec类型，请使用'type-codec'的格式，例如：flv-avc
      # 默认为空，由程序自动选择
      stream_type: ~
      # B站观看cookies，用于获取直播流，如果不填写则使用登录B站上传视频的cookies
      # 如果希望不登录录制最低画质，请设置为'None'
      bili_watch_cookies: .login_info/bili_watch_cookies.json
    # 高级视频录制参数
    # 请确保你明白这些参数的含义后再修改
    advanced_video_args: 
      # 默认分辨率，此选项用于在程序无法获取流分辨率时指定默认分辨率用于弹幕录制
      default_resolution: [1920, 1080]
      # 开播检测间隔，每隔这段时间检测一次是否开播
      start_check_interval: 60
      # 下播检测间隔，在主播下播但是未超过延迟下播时间时使用
      stop_check_interval: 60
      # 视频文件名称最长长度，超过此长度的文件名称将会被裁剪，默认80（B站视频名称最大长度）
      # 最大设置为256，否则文件无法被创建
      max_fn_length: 80
      # 视频文件最小大小（MB），小于此大小的视频文件将会被删除，默认1MB
      # 此功能可用于删除因为录制错误导致的许多空视频文件
      min_video_size: 1
      # 视频文件最小录制时间（秒），小于此录制时间的视频文件将被删除，默认不启用
      # 和最小大小配合使用时，只要有一个满足就会被删除
      min_video_duration: ~
      # 录制组编号，可用于多任务协同，详情请参考文档
      group_id: ~
      # 使用B站强制原画功能，仅适用于pyrequests引擎下的hls流
      bili_force_origin: True
      # ffmpeg取流参数(仅ffmpeg下载引擎生效)
      ffmpeg_stream_args: [ '-rw_timeout','10000000',
                            '-analyzeduration','15000000',
                            '-probesize','50000000',
                            '-thread_queue_size', '16']
      # ffmpeg输出参数(仅ffmpeg下载引擎生效)
      ffmpeg_output_args: [ '-movflags','faststart+frag_keyframe+empty_moov']
      # 禁用下载速度慢时自动重启(仅ffmpeg下载引擎生效)
      disable_lowspeed_interrupt: false
      # streamlink 额外输入参数
      # 可用参数列表请参考 https://streamlink.github.io/cli.html
      streamlink_extra_args: [
        "--twitch-disable-ads",     # 去广告，去掉、跳过嵌入的广告流
        "--twitch-disable-reruns",  # 如果该频道正在重放回放，不打开流
      ]

    # 以下是弹幕录制参数
    # 弹幕录制格式，只能选择ass
    dm_format: ass 
    # 弹幕上下间距（行距），设置为0-1的表示为视频宽度的倍数，设置为大于1的数表示像素，默认6
    margin_h: 6
    # 弹幕左右间距，设置为-1表示允许弹幕叠加，设置为0-1的表示间距为视频宽度的倍数，设置为大于1的数表示像素，默认0.05
    # 实际上这个东西就是弹幕密度，弹幕左右间距越大密度越小
    margin_w: 0.05
    # 指定弹幕占屏幕的最大比例（即屏幕上半部分有多少可以用来显示弹幕），默认为0.4
    dmrate: 0.4
    # 指定弹幕字体，默认为微软雅黑字体(Microsoft YaHei)
    font: Microsoft YaHei
    # 指定弹幕字体大小，默认为36
    fontsize: 36
    # Distance from Screen Top 弹幕距离屏幕顶端的距离（像素，例如20，表示距离屏幕顶端20px）
    dst: 20
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
    # 弹幕流选项
    dm_stream_option:
      # 用于获取抖音弹幕流的cookies，用于特殊情况下录制抖音弹幕(https://github.com/SmallPeaches/DanmakuRender/issues/258)
      # 格式：'__ac_nonce=xxx; __ac_signature=xxx; sessionid=xxx'
      # 特别提醒，使用此方法传入参数会在日志文件中明文显示，如果需要共享日志文件请确保删除了敏感信息！
      # 推荐设置为cookies所在的json文件，这样cookies就不会明文显示，json文件应该为cookies字典：{'__ac_nonce': xxx, ...}
      douyin_dm_cookies: ~
    # 弹幕过滤规则，满足其中任意条件的弹幕将被过滤
    dm_filter:
      # 弹幕类型过滤，只获取指定类型的弹幕，支持情况请参考文档
      # 可选值：all（所有）, danmaku（纯弹幕）, gift（礼物信息）, entry（进场信息）, superchat（超级弹幕）
      # 默认只获取文字弹幕(danmaku)
      dm_type: ~
      # 关键字过滤，只要有关键字的弹幕都会被过滤
      # 例如：[菜, fw]
      keywords: ~
      # 用户名称过滤，只有用户名称完全与发弹幕的用户名相同才会过滤
      # 例如：[虎牙小助手, TwitchBot]
      username: ~
      # 最长弹幕长度，超过此长度的弹幕将被过滤，0表示不限制
      max_length: 0
    # 弹幕模板，具体使用请参考文档
    dm_template:
      # 不同类型弹幕的模板
      danmaku: ~
      superchat: ~
      gift: ~
      entry: ~
    # 高级弹幕录制参数
    # 请确保你明白这些参数的含义后再修改
    advanced_dm_args:
      # 弹幕延迟补偿(秒)，将弹幕强行提前
      # 也可以设置为负数延后弹幕
      dm_delay_fixed: 6
      # 弹幕超时自动重启（秒），超过一段时间无弹幕会自动重启弹幕录制，0表示关闭
      dm_auto_restart: 300
      # 额外弹幕流输入
      # 部分主播可能同时在平台同时开播，可以用这个同时录制多个直播间的弹幕到一个视频
      # 应该设置为一个列表（不包括原来录制的房间），例如：['https://live.bilibili.com/123456', 'https://live.bilibili.com/654321']
      dm_extra_inputs: []
      # 弹幕文件最小录制时间（秒），小于此录制时间的弹幕文件将被删除
      # 此功能可用于删除因为录制错误导致的许多空弹幕文件
      dm_file_min_time: 30
  
  # 视频下载
  videos:
    # 需要下载的视频链接
    # 可以是UP主主页，播放列表，合集等
    url: 
    # 录制输出文件夹
    output_dir: ./视频下载
    # 录制文件名称格式
    # 默认为 视频标题.视频格式，例如：【2024LPL春季赛】2月7日 IG vs RNG.mp4
    # 如果下载B站用户主页视频（https://space.bilibili.com/<mid> 格式的链接），则可以使用关键字替换，例如 {STREAMER.NAME}-{TITLE}
    # 如果下载其他的B站视频，例如合集，播放列表等，则应该设置yutto的输出格式，例如 {title}/{name}
    # 具体请参考 https://github.com/yutto-dev/yutto?tab=readme-ov-file#已支持的下载类型
    # 如果使用yt-dlp下载其他平台的视频，应该使用yt-dlp的输出格式，例如 '%(title)s.%(ext)s'
    # 具体请参考 https://github.com/yt-dlp/yt-dlp?tab=readme-ov-file#output-template
    output_name: ~
    # 下载引擎
    # B站视频默认使用yutto，其他平台默认使用yt-dlp
    engine: ~
    # 视频质量，默认可用的最高画质
    # 此参数将被直接传入下载引擎，具体可用值请参考相关文档
    quality: ~
    # 登录账号名称，程序依靠这个来识别不同的账号
    # 下载B站时，不登录只能下载480P视频，登录但是不是大会员只能下1080P30的视频
    # 其他平台暂不生效
    account: bilibili
    # 登录cookies路径
    # 如果设置为空将会保存到./login_info/{ACCOUNT}.json
    cookies: ~
    # 下载视频的起始时间，设置格式为'YYYY-MM-DD HH:MM:SS'，例如'2024-01-01 00:00:00'
    # 如果设置为空将从当前时间开始下载之后的新视频
    # YouTube视频只能精确到天，例如设置为'2024-01-01 12:00:00'仍然会从0点开始下载
    start_time: ~
    # 下载视频的结束时间
    # 一般情况下应该设置为空
    end_time: ~
    # 是否下载弹幕
    # 仅对B站视频有效
    danmaku: False
    # 是否下载字幕
    # 仅对B站视频有效，如果yt-dlp需要字幕请在extra_args中添加相应参数
    subtitle: False
    # 检测更新时长（秒），默认600
    # 每隔这么长时间检测一次是否有新视频
    check_interval: 600
    # 下载超时时间（秒）
    # 如果一次下载超过此时间没有结束，将会被强制终止
    subprocess_timeout: 86400
    # 附加参数列表
    # 此参数将直接传入下载引擎，可以用来设置一些特殊的下载参数
    extra_args: []
  
  # 虚拟下载（此功能暂不可用）
  # 可以监控文件夹中的视频文件，用于和其他软件协同，详情请参考文档
  virtual:
    # 监控文件夹
    input_dir: ~
    # 输出文件夹
    # 如果设置了输出文件夹，则视频会被复制到输出文件夹再处理
    output_dir: ~
    # 匹配视频文件的正则表达式
    # 默认匹配可用视频文件
    video_pattern: ~
    # 匹配视频文件名称中视频信息
    info_pattern:
      # 匹配主播名称，默认为任务名称
      name: ~
      # 匹配视频标题，默认为视频文件名称
      title: ~
      # 匹配视频时间，默认为视频文件的创建时间
      time_str: ~
      # 匹配视频时间字符串转换为datetime对象的格式，用于datetime.strptime
      # 必须与time_str同时使用
      time_format:
      # 是否匹配弹幕文件，仅支持同名的ass文件
      danmaku: True
    # 分段等待时间（分钟），如果视频在此时间内没有更新，则会被认为分段录制完成
    segment_wait_time: 3
    # 下播等待时间（分钟），如果没有视频在此时间内更新，则会被认为直播已经结束
    stop_wait_time: 10
    # 检测视频的起始时间，默认为当前时间
    start_time: ~
    # 高级视频参数
    advanced_video_args: 
      # 视频文件最小大小（MB），小于此大小的视频文件将会被忽略，默认1MB
      min_video_size: 1
      # 视频文件最小录制时间（秒），小于此录制时间的视频文件将被忽略，默认不启用
      # 和最小大小配合使用时，只要有一个满足就会被忽略
      # 此参数推荐不设置，因为虚拟下载中视频长度是由文件创建时间和修改时间计算得到的
      # 在部分情况下中这两个时间相等，会导致计算得到的视频长度为0
      min_video_duration: ~
    # 额外信息，暂时没用
    extra_info: ~

# 渲染器核心参数
render_kernel_args:
  # 指定同时执行的渲染任务数，默认1
  # 一般情况下此值不应该超过5（最好是不修改）
  nrenders: 1

# 渲染器默认参数
render_args:
  # 弹幕渲染
  dmrender:
    # 渲染输出文件夹，默认为在录制输出文件夹后面加上“弹幕版”
    output_dir: ~
    # 渲染文件名称，默认在录制文件后面加上“弹幕版”
    output_name: ~
    # 生成的视频文件格式，默认mp4
    format: mp4
    # 硬件解码参数，默认由FFmpeg自动判断，如果出现问题可以设为空
    hwaccel_args: [-hwaccel, auto]
    # 视频编码器，NVIDIA设置为h264_nvenc，AMD设置为h264_amf，Apple用户设置为h264_videotoolbox，CPU设置为libx264
    vencoder: h264_nvenc
    # 视频编码器参数，默认恒定码率15Mbps
    vencoder_args: [-b:v, 15M]
    # 音频编码器
    aencoder: aac
    # 音频编码器参数，默认恒定码率320Kbps
    aencoder_args: [-b:a, 320K]
    # 输出重缩放，会把输出重缩放到指定分辨率，可以设置为'WxH'直接指定输出分辨率，例如'3840x2160'（4K）
    # 也可以指定为当前视频的大小倍数，例如'1.5'，这样1080P视频将会被放大到2880x1620（这个也符合了B站的4K视频标准）
    output_resize: ~
    # 高级渲染参数
    # 请确保你明白这些参数的含义后再修改
    advanced_render_args:
      # 直接定义video filter，这里的{DANMAKU}代表弹幕文件路径
      # 注意设置filter_complex之后将会禁用fps等其他有关filter的选项
      filter_complex: subtitles=filename='{DANMAKU}'
  # 原视频转码
  transcode:
    # 渲染输出文件夹，默认为在录制输出文件夹后面加上“转码后”
    output_dir: ~
    # 渲染文件名称，默认在录制文件后面加上“转码后”
    output_name: ~
    # 生成的视频文件格式，默认mp4
    format: mp4
    # 硬件解码参数，默认由FFmpeg自动判断，如果出现问题可以设为空
    hwaccel_args: [-hwaccel, auto]
    # 视频编码器，NVIDIA设置为h264_nvenc，AMD设置为h264_amf，Apple用户设置为h264_videotoolbox，CPU设置为libx264
    vencoder: h264_nvenc
    # 视频编码器参数，默认恒定码率15Mbps
    vencoder_args: [-b:v, 15M]
    # 音频编码器
    aencoder: aac
    # 音频编码器参数，默认恒定码率320Kbps
    aencoder_args: [-b:a, 320K]
    # 输出重缩放，会把输出重缩放到指定分辨率，可以设置为'WxH'直接指定输出分辨率，例如'3840x2160'（4K）
    # 也可以指定为当前视频的大小倍数，例如'1.5'，这样1080P视频将会被放大到2880x1620（这个也符合了B站的4K视频标准）
    output_resize: 1.5
    # 高级渲染参数
    # 请确保你明白这些参数的含义后再修改
    advanced_render_args: ~
  # 自定义ffmpeg调用（暂不可用）
  rawffmpeg:
    # 输出文件类型，可选src_video或者dm_video
    output_dtype: ~
    # 命令行参数，可以使用关键字替换
    # 为保证安全调用，请使用参数列表的形式，例如：['{FFMPEG}', '-i', '{SRC_VIDEO}', '-c', 'copy', '{OUTPUT}']
    cmds: ~

# 上传器核心参数
uploader_kernel_args:
  # 指定同时执行的上传任务数，默认1
  nuploaders: 1

# 上传器默认参数
upload_args:
  # 上传到B站
  bilibili:
    # 上传引擎，目前只支持biliuprs
    engine: biliuprs
    # 上传账号名称，程序依靠这个来识别不同的账号，如果打算传不同账号就要设置不同的名称
    account: bilibili
    # 上传cookies路径，如果设置为空将会保存到./login_info/{ACCOUNT}.json
    cookies: ~
    # 任务级上传锁，此功能保证同一个任务中的上传是串行的从而保证视频顺序，默认True
    # 如果设置为False，那么除第一个视频外其他所有上传任务将会完全并行
    # 对非实时上传的任务无效
    task_upload_lock: True
    # 重试次数，如果上传遇到错误将会重试，设置为0表示不重试
    # 注意：重试会整个视频重传，并且阻塞后面视频的上传，不应该设置太大
    retry: 3
    # 上传超时时间（秒），如果上传时间超过这个时间将会被强制终止（用于防止biliup卡死），0表示不限制
    timeout: 0
    # 实时上传（边录边传），每录制一个分段上传一次，同一场直播的不同分P仍然会在一个视频下，默认开启
    # 注意：实时上传可能无法上传很短的视频，尤其是在网速较快的情况下（B站对修改稿件的间隔有限制）
    realtime: True
    # 上传的视频最短长度，小于此长度的视频会被自动过滤，默认120s
    min_length: 120
    # 以下参数来自biliuprs，详细内容可以参考 https://biliup.github.io/biliup-rs/index.html
    # 上传线路，设置为空则由biliuprs自动选择
    line: ~
    # 上传线程数
    limit: 3
    # 是否为转载视频 1-自制 2-转载
    copyright: 1
    # 转载来源，转载视频必填
    source: ''
    # 分区号，分区参考 https://biliup.github.io/tid-ref.html
    tid: 65
    # 封面，指向本地文件地址
    cover: ''
    # 标题，可以使用关键字替换
    # 默认的例子：[飞天狙想要努力变胖/直播回放] 晚上七点半比赛 2023年2月24日 （带弹幕版）
    title: '[{STREAMER.NAME}/直播回放] {TITLE} {CTIME.YEAR}年{CTIME.MONTH:02d}月{CTIME.DAY:02d}日'
    # 简介，可以使用关键字替换
    desc: |
      {STREAMER.NAME} 的直播回放
      标题：{TITLE} 
      时间：{CTIME.YEAR}年{CTIME.MONTH:02d}月{CTIME.DAY:02d}日
      直播地址：{STREAMER.URL} 

      ————————————
      由DanmakuRender录制：
      https://github.com/SmallPeaches/DanmakuRender
    # 动态内容，可以使用关键字替换
    dynamic: '{STREAMER.NAME} 的直播回放，{CTIME.YEAR}年{CTIME.MONTH:02d}月{CTIME.DAY:02d}日'
    # 标签（一定要有！多个标签逗号分割）
    tag: '直播回放'
    # 延迟发布，单位秒，如果需要的话至少设置14400秒（4个小时）
    dtime: 0
    # 允许转载? 0-允许转载，1-禁止转载
    no_reprint: 1
    # 是否开启充电? 0-关闭 1-开启
    open_elec: 1
    # 额外参数列表
    # 此参数将直接传入biliup-rs，可以用来设置一些特殊的功能，例如仅自己可见
    extra_args: ~
  
  # 上传到YouTube
  # 此功能使用较复杂，细节请参考文档
  youtube:
    # 上传引擎，目前只支持youtubev3 (Google API v3 for Youtube)
    engine: youtubev3
    # 应用程序密钥路径
    client_secrets: .login_info/client.json
    # Google账号名称
    # 也可以直接指向已授权的Oauth2文件路径
    account: .login_info/google-oauth2.json
    # Google账号验证选项
    # 例如：在服务器上无GUI验证时，应设置为['--noauth_local_webserver']
    credential_args: ~
    # 重试次数，如果上传遇到错误将会重试，设置为0表示不重试
    # 特别提示：此重试会完全重传视频并消耗API配额（除非由于配额不够失败），需要断点续传请设置下面的参数
    retry: 0
    # 断点续传次数，此次数为单次上传中断点续传的次数，设置为0表示无限续传，直到上传完成或者API返回错误
    # 强烈建议设置无限续传，否则完全重传需要消耗API配额，并且未上传成功的视频需要自己到YouTube页面删除
    retry_resume: 0
    # 上传超时时间（秒），如果上传时间超过这个时间将会被强制终止（用于防止卡死），0表示不限制
    timeout: 0
    # 实时上传（边录边传），每录制一个分段上传一次，youtube默认关闭
    realtime: False
    # 是否合并视频
    # 如果设置为True，那么会把所有分段视频合并成一个视频再上传，默认True
    # 使用实时上传时此功能不生效
    # 强烈建议关闭实时上传，并启动合并视频再上传，因为YouTube API默认每天只能上传6个视频
    # 使用此功能请确保延迟下播时间设置较短，否则不同分辨率的视频合并会导致上传失败
    concat_video: True
    # 上传的视频最短长度，小于此长度的视频会被自动过滤，默认120s
    min_length: 120
    # 以下参数来自Google API，部分选项请参考 https://developers.google.com/youtube/v3/docs/videos/insert
    # 标题，可以使用关键字替换
    # 默认的例子：[飞天狙想要努力变胖/直播回放] 晚上七点半比赛 2023年2月24日 （带弹幕版）
    title: '[{STREAMER.NAME}/直播回放] {TITLE} {CTIME.YEAR}年{CTIME.MONTH:02d}月{CTIME.DAY:02d}日'
    # 简介，可以使用关键字替换
    desc: |
      {STREAMER.NAME} 的直播回放
      标题：{TITLE} 
      时间：{CTIME.YEAR}年{CTIME.MONTH:02d}月{CTIME.DAY:02d}日
      直播地址：{STREAMER.URL} 

      ————————————
      由DanmakuRender录制：
      https://github.com/SmallPeaches/DanmakuRender
    # 视频标签，多个标签逗号分割，例如：'直播回放,ABC'
    # Youtube的视频标签可以为空
    tag: ~
    # 视频分区编号，默认20（游戏）
    # 请参考 https://developers.google.com/youtube/v3/docs/videoCategories/list?hl=zh-cn
    # 或者 https://gist.github.com/dgp/1b24bf2961521bd75d6c
    category: 20
    # 延迟发布（秒）（此功能暂不可用）
    # 延迟时间从上传启动时开始计算，使用延迟上传时privacy固定为private
    dtime: 0
    # 隐私设置，可选：public（公开）, unlisted（未列出）, private（私有），默认public
    privacy: public
    # 完全自定义上传请求（https://developers.google.com/youtube/v3/docs/videos/insert?hl=zh-cn#request-body）
    # 应设置为json格式字符串，可使用关键字替换
    raw_upload_body: ~

  # 完全自定义上传
  # 调用的上传程序应该在上传成功后返回0，失败返回非0，并将错误信息输出到stderr
  # 具体说明请参考GitHub文档
  custom:
    # 上传引擎，目前只支持子进程调用
    engine: subprocess
    # 重试次数，如果上传遇到错误将会重试，设置为0表示不重试
    # 注意：重试会整个视频重传，并且阻塞后面视频的上传，不应该设置太大
    retry: 3
    # 上传超时时间（秒），如果上传时间超过这个时间将会被强制终止（用于防止卡死），0表示不限制
    timeout: 0
    # 实时上传，自定义时必须启用
    realtime: True
    # 上传的视频最短长度，小于此长度的视频会被自动过滤，默认120s
    min_length: 120
    # 上传命令行参数，可以使用关键字替换
    # 为保证安全调用，请使用参数列表的形式，例如：['python', 'upload.py', '{PATH}']
    command: ~

# 清理器默认参数
clean_args:
  # 移动文件
  move:
    # 目标文件夹，可以使用关键字替换，文件夹不存在会自动创建
    # 如果设置为"*TRASHBIN*"，那么文件将会被移动至回收站（需要操作系统支持）
    dest: ~
    # 清理延迟（秒），在上传完成后会过一段时间再清理，下同
    # 如果指定多个清理任务，不同清理任务的延迟并不顺延，均会在上传完成后的指定时间后清理
    delay: 86400
    # 清理弹幕视频时同时清理原文件，默认false，下同
    # 特别注意：应该只在不上传原文件的情况下使用此选项，否则可能会导致原视频上传失败
    w_srcfile: False
    # 清理原文件时同时清理转码前文件（如果有的话），默认true，下同
    w_srcpre: True
  # 复制文件
  copy:
    dest: ~
    delay: 0
    w_srcfile: False
    w_srcpre: True
  # 删除文件
  delete:
    delay: 172800
    w_srcfile: False
    w_srcpre: True
  # 自定义命令
  custom: 
    # 命令行参数，可以使用关键字替换
    # 为保证安全调用，请使用参数列表的形式，例如：['rm', '-rf', '{PATH}']
    command: ~
    # 是否等待命令执行完成
    # 如果设置为false，那么程序会立即执行下一个清理任务，不会等待命令执行完成
    # 注意：程序自带的其他清理方式均为同步执行(wait=True)
    wait: True
    delay: 0
    w_srcfile: False
    w_srcpre: True

# WebAPI
webservice_kernel_args:
  web_api: True
```

</details>

## 特殊功能
本节介绍一些不常用的高级功能，这些功能可能随版本更新随时更改。    

### 弹幕模板(download_args.dm_template)
可以设置弹幕模板，让显示的弹幕内包含其他提示信息，例如用户名称，弹幕颜色等。对于不同的弹幕类型可以设置不同的提示信息，默认情况下，纯文本弹幕会显示弹幕内容。
```yaml
dm_template:
  # 设置纯文本弹幕显示发送者姓名
  danmaku: '{UNAME}: {CONTENT}'
```
设置后的弹幕会显示为`小明：你好`而不是默认情况下的`你好`。      
```yaml
dm_template:
  # 这就是礼物弹幕的默认设置
  gift: '{uname} 赠送给主播价值 {price} {price_unit} 的 {gift_count} 个 {gift_name}'
```
设置后的弹幕会显示为`小明 赠送给主播价值 10 元 的 10 个 灯牌`。      

通用关键字：      
`{UNAME}`：用户名称，B站和抖音不登录有可能是匿名，名称中间会有*号    
`{TEXT}`：默认显示文本      
`{CONTENT}`：弹幕内容，非文本弹幕的不同平台默认值不一样       
`{COLOR}`：弹幕颜色，六位字符，例如`fffffe`       
`{TIME}`：发送时间，发送时间不是绝对时间，是相对视频开始时的时间，单位秒    
`{DTYPE}`: 弹幕类型

礼物弹幕可选关键字为：      
`{PRICE}`：礼物总价值       
`{GIFT_NAME}`：礼物名称       
`{GIFT_PRICE}`：礼物单个价值       
`{GIFT_COUNT}`：礼物数量       
`{PRICE_UNIT}`：价值单位       

超级弹幕可选关键字为：
`{PRICE}`：礼物总价值       
`{DURATION}`：持续时间       
`{PRICE_UNIT}`：价值单位       

特别提示，弹幕屏蔽功能会在使用弹幕模板后的文本上执行过滤逻辑。      

### 使用BiliWebApi进行的同步上传
同步上传是参考biliup实现的一种特殊的上传方法，它可以将获取的直播流直接上传至B站，而不需要文件实际存储到磁盘上。使用这种方法可以在带宽大但是磁盘小的服务器上实现录制多个直播。     

要启用同步上传，需要设置`download_args.sync = True`，并且满足如下条件：     
1. 必须启用实时上传，且只能上传至B站，并且上传目标数不能超过一个（也就是只能设置上传到B站的一个账号，不能同时使用自定义上传）。      
2. 下载引擎只能选择streamlink_sync，pyrequests_sync，ffmpeg_sync中的一个，或者使用auto让程序自动选择。（目前暂时只支持streamlink_sync），上传引擎只能选择biliwebapi，**选错引擎可能导致内存溢出！**        
3. 同步上传不支持任何对文件本身的处理，例如转码，压制弹幕等操作，因此也不会录制弹幕。   

使用同步上传需要注意如下事项：      
- 上传线程数不能过大，推荐不超过3。同步上传比传统的上传方法更消耗资源，平均每个任务会消耗约50-100M的内存，占用约10-20M的带宽。    
- 使用同步上传不会占用`uploader_kernel_args.nuploaders`中设置的并行上传数，因此同步上传和普通上传是完全并行的。     
- 如果需要同时录制很多主播，使用同步上传时不能一次性同时启动，这样会导致启动上传任务时被B站风控，推荐每分钟加3-5个任务。      
- 如果条件允许，推荐还是使用传统方法录制，因为同步方法录制的视频并不会存储在磁盘上，如果出现问题或者网络故障视频会直接丢失，没有重试的机会。      


### 上传到Youtube(upload_args.youtube)
如果需要上传到YouTube，首先需要在Google API上启用YouTube Data API v3，并且使用账号登录到YouTube，然后再配置参数，接下来详细介绍这几个步骤

- **启用Google API v3:** 请参考[这里](https://cloud.tencent.com/developer/article/2454578)，按步骤操作到下载生成的凭据文件，并将凭据文件路径设置到`client_secrets`下。如果需要上传多个账号，`client_secrets`可以共享，但是API配额也会共享（会扣API所属的账号配额而不是上传视频的账号配额）。         
- **设置配置文件：** 接下来设置好上传的参数和配置文件，如果之前已经登录过可以直接设置`account`为登录信息文件路径，否则需要执行下一步。
- **运行一次程序获取登录授权：** 运行程序，然后程序会弹窗要求登录（特别提醒：如果在服务器上无GUI登录需要设置`credential_args`参数，或者先在本地登录后将登录信息复制到服务器上），此账号需要设置为上传视频的YouTube账号，登录信息会保存到`.login_info/<account>.json`文件中。    

注意：未经Google认证的API项目登录时需要白名单权限（要在API控制台上添加白名单），每天最大上传视频数量为6个。   

### 多任务上传至同一视频(download_args.advanced_video_args.group_id)
程序会为主播的每场直播分配一个`group_id`用于标记该场次直播，并上传到相同的视频分P下。通过手动设置`group_id`，可以实现将不同主播的直播上传到同一个视频下的功能，或者让主播每个月的视频都在一个视频下，此功能只支持上传至B站。      
示例如下：
```yaml
group_id: group1
```
设置为固定值，这样所有拥有相同group_id的主播录像分段都会在一个视频下。    
```yaml
group_id: zhubo{CTIME.MONTH}
```
设置为带关键字的可变值，示例设置为带月份的关键字，1月是zhubo1，2月变成zhubo2，以此类推。实现当月的录播都传在一个视频。      
特别提醒：默认情况下，主播超过七天不直播会重新上传到一个新视频。    

### 虚拟录制(download_args.virtual)       
虚拟录制可以监控文件夹中的视频文件，它不需要实际启动录制，而是将文件夹中最近创建的文件作为录制好的文件。该功能可以用于和其他录播软件协同，只需要将监控文件夹设置为其他软件的输出文件夹即可。      
实际上，程序会监控文件夹下的满足`video_pattern`格式的文件（只要部分匹配都算匹配到），并通过操作系统提供的文件创建时间(os.getctime)和文件修改时间(os.getmtime)来判定是否正在录制或者有文件已经录制完成，如果文件超过一定时间未修改则认为已经录制完成。直播信息将会从文件名称中匹配分析得到。       
```yaml
# 监控文件夹
input_dir: ~
# 输出文件夹
# 如果设置了输出文件夹，则视频会被复制到输出文件夹再处理
output_dir: ~
# 匹配视频文件的正则表达式
# 默认匹配所有视频文件
# 如果该文件夹下有多个不同主播就得手动设置表达式区分
video_pattern: ~
# 匹配视频文件名称中视频信息
info_pattern:
  # 匹配主播名称，默认为任务名称，请使用正则表达式
  name: ~
  # 匹配视频标题，默认为视频文件名称，请使用正则表达式
  title: ~
  # 匹配代表视频时间的字符串，默认为视频文件的创建时间，请使用正则表达式
  time_str: ~
  # 将匹配到的字符串转换为datetime对象的格式，用于datetime.strptime
  # 必须与time_str同时使用
  time_format:
  # 是否匹配弹幕文件，仅支持同名的ass文件，默认true
  danmaku: True
# 分段等待时间（分钟），如果视频在此时间内没有更新，则会被认为分段录制完成
segment_wait_time: 3
# 下播等待时间（分钟），如果没有视频在此时间内更新，则会被认为直播已经结束
stop_wait_time: 10
# 检测视频的起始时间，默认为当前时间
# 示例：'2025-01-01 12:34:56'
start_time: ~
# 高级视频参数
advanced_video_args: 
  # 视频文件最小大小（MB），小于此大小的视频文件将会被忽略，默认1MB
  min_video_size: 1
  # 视频文件最小录制时间（秒），小于此录制时间的视频文件将被忽略，默认不启用
  # 和最小大小配合使用时，只要有一个满足就会被忽略
  # 此参数推荐不设置，因为虚拟下载中视频长度是由文件创建时间和修改时间计算得到的
  # 在部分情况下中这两个时间相等，会导致计算得到的视频长度为0
  min_video_duration: ~
```
如果设置了自动清理，那么使用虚拟录制处理的所有文件都将被正常清理，如果希望保留源文件或者完全分离不同软件之间的处理逻辑，可以设置output_dir让程序复制文件后处理。      