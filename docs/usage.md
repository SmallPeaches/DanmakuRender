# DanmakuRender-4 使用指南
本文档描述了使用DMR录制直播流、渲染弹幕和上传直播回放的操作方法。    

**目录：**      
[简介](#简介)     
[简易使用](#简易使用)      
[高阶使用](#高阶使用)      
[常见问题](#常见问题)      

更新日期：2023.10.24。     

## 简介     
**本程序的主要功能包括：**
- 可以录制纯净直播流和弹幕，并且支持在本地预览带弹幕直播流。
- 可以自动渲染弹幕到视频中，并且渲染速度快。
- 支持同时录制多个直播。    
- 支持录播自动上传至B站。

**程序的使用方法是：**      
新版本已经可以简单的通过复制和修改录制文件实现多个主播的录制。      
在`configs`文件夹里复制一份`example.yml`文件，并且重命名为`replay-<任务名称>.yml`，例如`replay-飞天狙.yml`。然后修改复制后的文件，每个依照此规则命名的文件都将作为一个录制任务加入录制队列。      

**程序的工作流程是：**      
先录制一段时间（默认一个小时）的直播，然后在录制下一小时直播时启动对这一小时直播的渲染。录制完成后可以同时得到直播回放和带弹幕的直播回放（分为两个视频，存放于两个不同的文件夹）。上传将在当场直播结束（也就是主播下播之后）开始，上传到B站时会将同一场直播的视频放在同一个视频的不同分P下。        

## 简易使用     
在`configs`文件夹里复制一份`example.yml`文件，并且重命名为`replay-<任务名称>.yml`，例如`replay-飞天狙.yml`。然后修改复制后的文件，每个依照此规则命名的文件都将作为一个录制任务加入录制队列。      

运行时在程序目录打开控制台（win10系统shift+右键点击页面空白处，在菜单中选择“在此处打开powershell窗口”，win11在页面右键选择“在终端中打开”），输入`python main.py`执行程序。        
如果你已经可以正常运行程序了，那么也可以直接双击打开`main.py`文件运行。

**请注意：使用新方法指定录制配置请保证原有`replay.yml`中的replay项为空。**
- 关键字替换说明      

在一些配置选项中可能会说可用关键字替换，录制文件名称中的`{}`表示在程序运行的过程中自动替换为相应的内容，例如`{YEAR}年{MONTH}月{DAY}日`在运行时会被动态替换为`2023年8月10日`，具体可用关键字如下：     

| 关键字   | 注释  |
| :-------: | :-------: | 
| {STREAMER} |   主播名称   |  
| {TITLE} |   直播标题   | 
| {URL} |   直播间链接   | 
| {HAS_DANMU} | `带弹幕版`这几个字   | 
| {YEAR} |  年   | 
| {MONTH} | 月   | 
| {DAY} | 日   | 
| {HOUR} | 时   |
| {MINUTE} | 分 |
| {SECOND} | 秒 |
| {TASKNAME} | 任务名称，就是配置文件名称里面那个 |   

- 配置弹幕渲染参数（**非N卡用户必读！**）       
非N卡用户需要在`replay.yml`里面修改渲染弹幕的参数，具体描述如下：
```yaml
render: 
  # 硬件解码参数，默认自动，如果是CPU编码记得改为空
  hwaccel_args: [-hwaccel,auto] 
  # 使用NVIDIA H.264编码器，A卡用户设置为h264_amf，CPU渲染设置为libx264
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
2023.9.16版本新功能：可以设置输出缩放的倍数（例如设置为1.5，1080P的视频将会被放大到2880x1620，正好符合B站的4K视频标准），这样可以适应不同分辨率的视频，避免视频被错误缩放。       

- 注意事项      

1. 如果遇到渲染失败，可以使用`render_only.py`进行渲染操作，渲染的配置将会由`replay.yml`决定。     
2. 设置好配置文件后，可以运行`dryrun.py`进行测试，程序将录制三段一分钟的视频，并根据配置文件渲染和上传（**这里的上传会自动设置延迟24小时发布，记得24小时内去B站稿件管理删除**），录制完成后可以自行检查效果。

## 高阶使用     
本节介绍配置文件可用的全部选项和功能。一般情况下简易使用已经可以满足90%以上需求，没有特殊需要的话可以不阅读此部分。     

### 配置文件格式简介    
本程序的配置文件replay.yml为yaml文件（本质上就是个Python字典），其大致结构如下：
```yaml
# 此部分为渲染参数
render:
  <参数名称>: <参数值>
  ...

# 此部分为上传参数
uploader:
  <参数名称>: <参数值>
  ...

# 此部分为录制参数
replay:
  <任务1名称>:
    <参数名称>: <参数值>
    ...
  
  <任务2名称>:
    <参数名称>: <参数值>
    ...
  ...
```
实际上，configs文件夹里面的配置文件只是将录制参数拆分了，原来的录制参数下面是一个一个的任务，现在录制参数变成了一个任务一个文件，可以单独设置各种上传参数和渲染参数。replay.yml里面的设置起到了默认参数的作用。     
**注意**：两种方法在实现上是一致的（可选参数都是一样的），因此下文将不再区分两种设置方法的区别。     

### 录制参数设置
本节介绍录制参数的设置。一个录制任务由一个任务名称和录制参数组成，任务名称不能重复。下文将主要介绍录制参数的格式（也就是configs里配置文件的参数）。     
**注意**：一些录制参数是可变类型的（可以简写），请注意分辨。      
```yaml
# 录制参数
<参数名称>: <参数值>
...

# 单独的渲染设置（可选）
# 这里的可选参数和下文的渲染参数相同，故不再赘述
render: 
  ...

# 自动上传设置（可选）
# 自动上传设置分为三个部分，对应程序生成的三种文件类型，想上传哪种视频就填哪个，不上传就删掉那一部分
# 具体格式见下文
upload:
  # 原视频
  src_video:  
    ...
  # 弹幕视频
  dm_video:
    ...
  # 弹幕文件（这部分暂时没用）
  dm_file:
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

录制参数的可选内容如下：
```yaml
# 直播间链接
url: ''

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
# 使用这个功能可以把主播短暂下播又开播认定为同一场直播
end_cnt: 5

# 默认分辨率，此功能暂不可用
resolution: ~

# 录制视频的格式，默认flv
# 使用streamgears作为录制引擎应该使用flv
vid_format: flv

# 直播流CDN选项
# 对于虎牙直播，此项可选al, tx, hw等cdn服务器的缩写，默认tx
# 对于B站，此项可选0-n表示不同的cdn服务器，默认为0，也可以输入特定的CDN域名前缀，例如 c1--cn-gotcha208
# 斗鱼和抖音暂时没用
flow_cdn: ~

# 高级视频录制参数，具体可用选项请参考文档
advanced_video_args: ~

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

# 弹幕过滤规则，一个正则表达式数组（也可以直接输入关键字），满足其中任意条件的弹幕将被过滤，默认为空（不过滤弹幕）
# 例如：[菜, fw]
dm_filter: []

# 高级弹幕录制参数，具体可用选项请参考文档
advanced_dm_args: ~
```

其中，高级视频录制参数、高级弹幕录制参数应该被指定为一个键值对。它可以用来调整一些特殊的功能，例如ffmpeg请求流时的http参数、弹幕录制的延迟补偿时间等。默认情况下这些参数都由程序内部决定，这里的值只用于参考。你可以单独设置其中的一个或者多个。具体可选参数如下。      

```yaml
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
  # 设置用于获取B站直播流的cookies路径，默认为.temp/.bili_watch_cookies.json或者.temp/bilibili.json
  # 如果不想登录到B站，请设置为空
  bili_watch_cookies: .temp/.bili_watch_cookies.json
  # 设置用于未登录情况下强制生成原画直播流的参数，表示为[src, tgt]，将特定的画质字符串替换掉，设置为空表示不启用这个功能
  # 注意：此功能不一定生效，具体效果视直播间而定
  bili_force_origin: ['_1500', '']
```

```yaml
advanced_dm_args:
  # 弹幕延迟补偿(秒)，将弹幕强行提前
  dm_delay_fixed: 6
  # 弹幕超时自动重启（秒），超过一段时间无弹幕会自动重启弹幕录制，0表示关闭
  dm_auto_restart: 300
```

**自动上传的配置格式说明**      
每个视频类型都可以指定一个或者多个上传任务，组成一个数组。特别地，如果只上传一个地方，则可以直接指定参数，不必使用数组，示例如下：
```yaml
# 一种视频只上传到B站的一个账号，以原视频为例
src_video:
  # 上传目标，目前只能是bilibili
  target: bilibili
  # 接下来的参数在B站上传参数下选择（详情参考 上传参数说明 小节）
  account: smallpeach
  ...
```

```yaml
# 一种视频只上传到B站的多个个账号，以原视频为例
src_video:
  # 这里设置为一个数组，数组的每个元素代表一种上传
  - target: bilibili
    # 接下来的参数在B站上传参数下选择（参考下文 上传参数说明 小节）
    account: smallpeach
    ...

  # 这里是数组的第二个元素
  - target: bilibili
    account: smallpeach2
    ...
```

**自动清理的配置格式说明**      
自动清理的可选参数如下：
```yaml
# 清理方法，可选copy（复制），move（移动），delete（删除），默认不清理
# 请注意：清理过程不可逆！最好还是自己手动清理！
method: ~

# 目标文件夹，可以使用关键字替换，文件夹不存在会自动创建
dest: ~

# 处理延迟（秒），在上传完成后会过一段时间再处理
delay: 0

# （此功能暂不生效）只处理此次运行中上传成功的文件
strict: True

# （此功能暂不生效）是否等待执行完成
wait: True
```

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
**注意**：清理将会在上传完成之后开始（如果使用流式上传，则每个视频单独计算）。    
如果使用move方法，目标文件夹还可以设置为`*TRASHBIN*`，这样会将文件放到回收站而不是直接删除。这个功能需要额外pip安装pywin32包（Linux下需要安装trash扩展包）。

### 渲染参数说明
本节介绍可用的渲染参数及其功能。      
```yaml
# 同时执行的渲染任务数，默认1，若渲染时CPU和GPU使用都低于80%可以调高这个，一般情况下设置应该小于5
# 特别提示：如果渲染一个CPU或者显卡占用都很高，调高这个反而有副作用！
nrenders: 1

# 渲染输出文件夹，默认为空（在录制输出文件夹后面加上“带弹幕版”）
output_dir: ~

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

# 输出重缩放，会把输出重缩放到指定分辨率，可以设置为'3840x2160'用于在B站传伪4K保证清晰度
output_resize: ~

# 高级渲染参数
advanced_render_args: ~
```

其中，高级渲染参数应该被指定为一个键值对（Python字典）。它可以用来指定帧率、GOP等，甚至可以直接控制调用FFmpeg的参数。默认情况下这些参数都由程序内部决定，你可以单独设置其中的一个或者多个。具体可选参数如下。
```yaml
advanced_render_args:
  # 指定输出帧率。此选项不同于'-r'，这里的帧率将直接作用在video filter上，默认保持原视频帧率
  fps: 0
  # 指定GOP，用于解决特殊情况下B站音画不同步的问题，默认5s
  gop: 5
  # 直接定义video filter，这里的{DANMAKU}代表弹幕文件路径
  # 注意设置filter_complex之后将会禁用fps等其他有关filter的选项
  filter_complex: subtitles=filename='{DANMAKU}'
```

### 上传参数说明      
本节介绍可用的上传参数及其功能。      
上传参数分为两个部分，一个是程序的全局上传参数，它只能设置一次（目前只有nuploaders这一个）。第二部分是不同平台单独的上传参数，它可以在录制参数里面被指定，也可以在上传参数里指定。      

**注意**：在上传参数里指定这些参数将会覆盖config/default.yml里的设置，并不能起到上传的作用！需要上传的话要在录制参数里面设置！    
```yaml
# 这里是程序的全局上传参数
# 允许同时上传的任务数，默认1
nuploaders: 1

# 下面这些都是B站的上传参数
# 上传目标（目前只有B站）
bilibili:
  # 上传引擎，目前只能选biliuprs
  engine: biliuprs

  # 上传账号名称，程序依靠这个来识别不同的账号，如果打算传不同账号就要设置不同的名称
  account: bilibili

  # （此功能暂不生效）重试次数，如果上传遇到错误将会重试，设置为0表示不重试
  retry: 0

  # 实时上传，每录制一个分段上传一次，同一场直播的不同分P仍然会在一个视频下，默认关闭
  # 如果启用实时上传，请保证上传速度足够，否则可能阻塞上传队列
  realtime: False

  # 登录信息保存的cookies路径，默认为空（由程序自动生成".temp/<上传账号名称>.json"的文件）
  # 如果同时指定上传账号和cookies，那么程序会优先使用cookies路径
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

  # 封面，指向本地文件地址
  cover: ''

  # 标题，可以使用关键字替换
  # {STREAMER}主播名称，{TITLE}标题，{YEAR}年，{MONTH}月，{DAY}日，{HAS_DANMU}“带弹幕版”这几个字，{URL}直播间链接
  # 默认的例子：[飞天狙想要努力变胖/直播回放] 晚上七点半比赛 2023年2月24日 （带弹幕版）
  title: '[{STREAMER}/直播回放] {TITLE} {YEAR}年{MONTH}月{DAY}日 {HAS_DANMU}'

  # 简介，可以使用关键字替换
  desc: "{STREAMER} 的直播回放{HAS_DANMU} \n标题：{TITLE} \n时间：{YEAR}年{MONTH}月{DAY}日 \n直播地址：{URL} \n\n————————————\n由DanmakuRender录制： \nhttps://github.com/SmallPeaches/DanmakuRender"
  
  # 动态内容，可以使用关键字替换
  dynamic: '{STREAMER} 的直播回放，{YEAR}年{MONTH}月{DAY}日'

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

## 常见问题
1. 渲染失败？       
最常见的原因是没设置好编码器（比如说A卡没设置 h264_amf 编码器），或者是显卡驱动没更新。如果检查都没问题可以开一个issue或者B站私信我。

2. 渲染太慢？       
首先我给一个渲染速度的参考（默认参数，1080P情况下），使用i7-8700H + 1060，渲染速度4-5倍速。i7-12700H + 3060，渲染速度5-6倍速。如果速度大概在这个范围内就不要说慢啦。    
如果慢得很异常，首先检查CPU和GPU占用是否正常（GPU占用只看任务管理器里Video Encoder的占用），如果占用已经接近满了，那就说明是硬件性能瓶颈了。如果都没怎么占用，那就要考虑更新驱动程序，或者调节编码参数了。你可以单独开一个issue讨论一下。
