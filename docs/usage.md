# DanmakuRender-4 使用指南
本文档描述了使用DMR录制直播流、渲染弹幕和上传直播回放的操作方法。    

**目录：**      
[简介](#简介)     
[简易使用](#简易使用)      
[高阶使用](#高阶使用)      
[常见问题](#常见问题)      

更新日期：2024.02.08。     

## 简介     
**本程序的主要功能包括：**
- 可以录制纯净直播流和弹幕，并且支持在本地预览带弹幕直播流。
- 可以自动渲染弹幕到视频中，并且渲染速度快。
- 支持同时录制多个直播。    
- 支持录播自动上传至B站。
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

- 关键字替换说明      

在一些配置选项中可能会说可用关键字替换，录制文件名称中的`{}`表示在程序运行的过程中自动替换为相应的内容，例如`{CTIME.YEAR}年{CTIME.MONTH}月{CTIME.DAY}日`在运行时会被动态替换为`2023年8月10日`，具体可用关键字如下：  

`{TITLE}` 直播标题/视频标题      
`{URL}` 直播间链接或者视频链接      
`{TASKNAME}` 任务名称（配置文件DMR-后面那个）         
`{SEGMENT_ID}` 视频分段序号，从0开始（仅在录制分P视频时有效）        
`{GROUP_ID}` 视频组ID，在录制B站分P视频时此字段代表视频总标题，TITLE代表各分P标题，其他情况下此ID为随机数       
`{CTIME.YEAR}, {CTIME.MONTH}, {CTIME.DAY}, {CTIME.HOUR}, {CTIME.MINUTE}, {CTIME.SECOND}` 直播分段时间/视频上传时间，年月日时分秒，YouTube视频只能精确到天（时分秒都会是0）       
`{STREAMER.NAME}` 主播/UP主名称      
`{STREAMER.URL}` 主播主页/直播间链接      
`{STREAMER.ROOM_ID}` 直播房间号      
`{COVER_URL}` 封面链接（仅YouTube视频可用）     
`{DESC}` 视频简介（仅YouTube视频可用）      
`{TAG}` 视频标签（仅YouTube视频可用）       

实际上，关键字替换使用了Python的字符串格式化功能，也就是可以使用类似`{CTIME.DAY:02d}`的语句来实现自动补0。关键字不区分大小写，所有关键字都会被自动转换为小写，不过出于阅读考虑，仍然推荐使用大写表示。

- 配置弹幕渲染参数（**非N卡用户必读！**）       
非N卡用户需要在`config/global.yml`里面修改渲染弹幕的参数，具体描述如下：
```yaml
render_args: 
  # 硬件解码参数，默认自动
  # 请注意，使用远程桌面时auto可能出现问题，请设置为空
  hwaccel_args: [-hwaccel,auto] 
  # 使用NVIDIA H.264编码器，A卡用户设置为h264_amf，I卡设置为h264_qsv，CPU渲染设置为libx264
  vencoder: h264_nvenc   
  # 指定编码器参数，默认15M码率         
  vencoder_args: ['-b:v','15M'] 
  # 输出重缩放，会把输出重缩放到指定分辨率，可以设置为'WxH'直接指定输出分辨率
  # 也可以指定为当前视频的大小倍数，例如 1.5
  output_resize: ~
```
**关于硬件加速**：使用硬件加速编码遇到渲染失败问题，首先检查显卡驱动有没有更新！    

**关于输出重缩放**：很多人发现视频上传B站之后变糊（尤其是带弹幕的视频），但是本地看又很清晰，主要原因是B站现在对视频的码率做了限制，普通1080P视频码率一般不超过2Mbps(AV1编码)，只有直播的五分之一。   
为了绕过这个限制，需要使用伪4K的功能，简单地说就是把视频缩放到4K（3840x2160），让B站以为是4K视频然后按4K分配码率，这样一般能够分到15M的码率，最后看的时候就会很清晰。      

## 高阶使用     
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
  # 上传目标，目前只能是bilibili
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
此参数列表包括了所有可选的参数。
```yaml
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
  # 如果启用此项，程序将自动更新配置文件（也就是可以在运行时添加任务）
  dynamic_config: False
  # 动态更新的配置文件路径
  # 程序将自动更新此文件夹下的配置文件
  dynmaic_config_path: ./configs

# 默认下载参数
download_args:
  # 直播录制
  live:
    # 直播间链接
    url: ''
    # 录制输出文件夹，设置为空则使用主播名称作为文件夹
    output_dir: ./直播回放
    # 录制文件名称格式，可使用关键字替换，默认效果：飞天狙想要努力变胖-2023年3月1日20点30分，注意这里不能含有冒号，斜杠等非法字符！！
    output_name: '{STREAMER.NAME}-{CTIME.YEAR}年{CTIME.MONTH:02d}月{CTIME.DAY:02d}日{CTIME.HOUR:02d}点{CTIME.MINUTE:02d}分'
    # 录播分段时间（秒），默认一个小时
    segment: 3600
    # 录制程序引擎，可选ffmpeg或者streamgears
    # 在使用streamgears作为录制引擎时，录制视频格式可能会根据直播流的不同而不同
    # 建议PC推流的直播使用ffmpeg录制，手机推流的直播使用streamgears录制
    engine: ffmpeg
    # 是否录制弹幕
    danmaku: True
    # 是否录制直播流
    video: True
    # 延迟下播计时（分钟）
    # 使用这个功能可以把主播短暂下播又开播认定为同一场直播
    stop_wait_time: 5
    # 录制视频的格式，默认flv
    vid_format: flv
    # 直播流选项
    stream_option:
      # 直播流CDN
      # 对于虎牙直播，此项可选al, tx, hw等cdn服务器的缩写，默认tx
      # 对于B站，可选特定的CDN域名前缀，例如 c1--cn-gotcha208
      stream_cdn: ~
      # 直播流类型，可选flv, hls，默认flv
      # 暂时只对B站生效（部分情况下B站的flv流是不可用的，只能用hls）
      stream_type: flv 
      # B站观看cookies，用于获取直播流，如果不填写则使用登录B站上传视频的cookies
      # 如果希望不登录录制最低画质，请设置为'None'
      bili_watch_cookies: .login_info/bili_watch_cookies.json
    # 高级视频录制参数
    # 请注意此参数随时可能删减，正常情况下不应该修改
    advanced_video_args: 
      # 默认分辨率，此选项用于在程序无法获取流分辨率时指定默认分辨率用于弹幕录制
      default_resolution: [1920, 1080]
      # 开播检测间隔，每隔这样一段时间检测一次是否开播
      start_check_interval: 60
      # 下播检测间隔，在主播下播但是未超过延迟下播时间时使用
      stop_check_interval: 30
      # ffmpeg取流参数(仅ffmpeg下载引擎生效)
      ffmpeg_stream_args: [ '-rw_timeout','10000000',
                            '-analyzeduration','15000000',
                            '-probesize','50000000',
                            '-thread_queue_size', '16']
      # ffmpeg输出参数(仅ffmpeg下载引擎生效)
      ffmpeg_output_args: [ '-movflags','faststart+frag_keyframe+empty_moov']
      # 检测流变化(仅ffmpeg下载引擎生效)
      check_stream_changes: false
      # 禁用下载速度慢时自动重启(仅ffmpeg下载引擎生效)
      disable_lowspeed_interrupt: false

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
    # 弹幕过滤规则，满足其中任意条件的弹幕将被过滤
    dm_filter:
      # 关键字过滤，只要有关键字的弹幕都会被过滤
      # 例如：[菜, fw]
      keywords: ~
      # 用户名称过滤，只有用户名称完全与发弹幕的用户名相同才会过滤
      # 此功能暂不生效
      username: ~
    # 高级弹幕录制参数
    # 请注意此参数随时可能删减，正常情况下不应该修改
    advanced_dm_args:
      # 弹幕延迟补偿(秒)，将弹幕强行提前
      dm_delay_fixed: 6
      # 弹幕超时自动重启（秒），超过一段时间无弹幕会自动重启弹幕录制，0表示关闭
      dm_auto_restart: 300
      # 额外弹幕流输入
      # 部分主播可能同时在平台同时开播，可以用这个同时录制多个直播间的弹幕到一个视频
      # 应该设置为一个列表（不包括原来录制的房间），例如：['https://live.bilibili.com/123456', 'https://live.bilibili.com/654321']
      dm_extra_inputs: []
  
  # 视频下载
  videos:
    # 需要下载的视频链接
    # 可以是UP主主页，播放列表，合集等
    url: ''
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

# 渲染器核心参数
render_kernel_args:
  # 指定同时执行的渲染任务数，默认1
  # 一般情况下此值不应该超过5
  nrenders: 1

# 渲染器默认参数
render_args:
  # 弹幕渲染
  dmrender:
    # 渲染输出文件夹，默认为在录制输出文件夹后面加上“带弹幕版”
    output_dir: ~
    # 渲染文件名称，默认在录制文件后面加上“带弹幕版”
    output_name: ~
    # 生成的视频文件格式，默认mp4
    format: mp4
    # 硬件解码参数，默认由FFmpeg自动判断，如果出现问题可以设为空
    hwaccel_args: [-hwaccel, auto]
    # 视频编码器，NVIDIA设置为h264_nvenc，AMD设置为h264_amf，CPU设置为libx264
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
    # 请注意此参数随时可能删减，正常情况下不应该修改
    advanced_render_args:
      # 指定输出帧率。此选项不同于'-r'，这里的帧率将直接作用在video filter上，默认保持原视频帧率
      fps: ~
      # 直接定义video filter，这里的{DANMAKU}代表弹幕文件路径
      # 注意设置filter_complex之后将会禁用fps等其他有关filter的选项
      filter_complex: subtitles=filename='{DANMAKU}'
  # 原视频转码
  transcode:
    # 渲染输出文件夹，默认为在录制输出文件夹后面加上“带弹幕版”
    output_dir: ~
    # 渲染文件名称，默认在录制文件后面加上“带弹幕版”
    output_name: ~
    # 生成的视频文件格式，默认mp4
    format: mp4
    # 硬件解码参数，默认由FFmpeg自动判断，如果出现问题可以设为空
    hwaccel_args: [-hwaccel, auto]
    # 视频编码器，NVIDIA设置为h264_nvenc，AMD设置为h264_amf，CPU设置为libx264
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
    # 请注意此参数随时可能删减，正常情况下不应该修改
    advanced_render_args: ~
  # 自定义ffmpeg调用
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
  bilibili:
    # 上传引擎，目前只支持biliuprs
    engine: biliuprs
    # 上传账号名称，程序依靠这个来识别不同的账号，如果打算传不同账号就要设置不同的名称
    account: bilibili
    # 上传cookies路径，如果设置为空将会保存到./login_info/{ACCOUNT}.json
    cookies: ~
    # 重试次数，如果上传遇到错误将会重试，设置为0表示不重试
    # 注意：重试会整个视频重传，并且阻塞后面视频的上传，不应该设置太大
    retry: 0
    # 实时上传（边录边传），每录制一个分段上传一次，同一场直播的不同分P仍然会在一个视频下，默认开启
    # 注意：实时上传可能无法上传很短的视频，尤其是在网速较快的情况下（B站对修改稿件的间隔有限制）
    realtime: True
    # 上传的视频最短长度，小于此长度的视频会被自动过滤，默认120s
    min_length: 120
    # 以下参数来自biliuprs，详细内容可以参考 https://biliup.github.io/biliup-rs/index.html
    # 上传线路
    line: bda2
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
    # 是否开启杜比音效? 0-关闭 1-开启
    dolby: 0
    # 允许转载? 0-允许转载，1-禁止转载
    no_reprint: 1
    # 是否开启充电? 0-关闭 1-开启
    open_elec: 1

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
```

## 常见问题
1. 渲染失败？       
最常见的原因是没设置好编码器（比如说A卡没设置 h264_amf 编码器），或者是显卡驱动没更新。如果检查都没问题可以开一个issue讨论。

2. 渲染太慢？       
首先我给一个渲染速度的参考（默认参数，1080P情况下），使用i7-8700H + 1060，渲染速度4-5倍速。i7-12700H + 3060，渲染速度5-6倍速。如果速度大概在这个范围内就不要说慢啦。    
如果慢得很异常，首先检查CPU和GPU占用是否正常（GPU占用只看任务管理器里Video Encoder的占用），如果占用已经接近满了，那就说明是硬件性能瓶颈了。如果都没怎么占用，那就要考虑更新驱动程序，或者调节编码参数了。你可以单独开一个issue讨论一下。
