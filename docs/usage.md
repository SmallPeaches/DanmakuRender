# DanmakuRender-4 使用指南
本文档描述了使用DMR录制直播流、渲染弹幕和上传直播回放的操作方法。    

**目录：**      
[简介](#简介)     
[简易使用](#简易使用)      
[高阶使用](#高阶使用)      
[常见问题](#常见问题)      

更新日期：2023.8.10。     

## 简介     
**本程序的主要功能包括：**
- 可以录制纯净直播流和弹幕，并且支持在本地预览带弹幕直播流。
- 可以自动渲染弹幕到视频中，并且渲染速度快。
- 支持同时录制多个直播。    
- 支持录播自动上传至B站。

**程序的使用方法是：**      
新版本使用yaml配置文件的方法来指定参数，配置文件一共有两个，分别为`default.yml`（默认配置文件，描述了程序可用的所有参数及其默认值）和`replay.yml`（录制配置文件，用户自定义的用于录制的配置文件），一般情况下默认配置文件不需要修改，只需要修改录制配置文件。     

注意：如果忘记了配置文件的默认值，可以删掉重新打开程序，程序会自动生成一份配置文件。    

运行时在程序目录打开控制台（win10系统shift+右键点击页面空白处，在菜单中选择“在此处打开powershell窗口”，win11在页面右键选择“在终端中打开”），输入`python main.py`执行程序。        
如果你已经可以正常运行程序了，那么也可以直接双击打开`main.py`文件运行。

**程序的工作流程是：**      
先录制一段时间（默认一个小时）的直播，然后在录制下一小时直播时启动对这一小时直播的渲染。录制完成后可以同时得到直播回放和带弹幕的直播回放（分为两个视频，存放于两个不同的文件夹）。上传将在当场直播结束（也就是主播下播之后）开始，上传到B站时会将同一场直播的视频放在同一个视频的不同分P下。        

## 简易使用
`replay.yml`配置文件内录制任务应该满足如下格式（**注意空格缩进！**）
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
- 录制单个直播间
```yaml
replay:
  - url: https://live.bilibili.com/15019349
```
此示例是最简单的录播配置，程序录制给定的直播间，其他所有的选项都将设置为默认。        

- 录制单个直播间，并调整一些常用参数
```yaml
replay:
  # 第一行填URL
  - url: https://live.bilibili.com/15019349
    # 录制输出文件夹
    output_dir: ./直播回放
    # 录制文件名称，效果：飞天狙想要努力变胖-2023年3月1日20点30分
    output_name: '{STREAMER}-{YEAR}年{MONTH}月{DAY}日{HOUR}点{MINUTE}分'
    # 分段时间3600秒
    segment: 3600
    # 弹幕占比
    dmrate: 0.4
    # 弹幕字体大小
    fontsize: 36
    # 弹幕字体透明度
    opacity: 0.8
```
在此示例中，程序将会以一个小时一段录制直播，录制文件名称中的`{}`表示在程序运行的过程中自动替换为相应的内容，具体可用关键字如下：     
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
| {TASKNAME} | 任务名称，默认和主播名称一样

- 录制多个直播间
```yaml
replay:
  # 第一个直播间的URL
  - url: https://live.bilibili.com/15019349
    # 接下来的都是可选参数
    output_dir: ./直播回放
    output_name: '{STREAMER}-{YEAR}年{MONTH}月{DAY}日{HOUR}点{MINUTE}分'
    segment: 3600
    fontsize: 36
    opacity: 0.8

  # 第二个直播间的URL
  - url: https://live.bilibili.com/55
    # 可选参数
    output_name: '{STREAMER}-{YEAR}年{MONTH}月{DAY}日{HOUR}点{MINUTE}分'
    segment: 1800
    dmrate: 0.4
    fontsize: 36
    opacity: 0.5
```

- 带自动上传功能的录制    
```yaml
replay:
  - url: https://live.bilibili.com/13308358
    upload:                     # 指定此任务需要自动上传
      src_video: bilibili       # 指定上传源视频到B站
      dm_video: bilibili        # 指定上传弹幕视频到B站
```
此配置为自动上传的最简配置，视频会上传到B站的默认账号，所有参数都选择默认，弹幕视频和源视频将会分别上传。如果不想上传源视频就删掉src_video那一条。    

- 自定义自动上传配置
```yaml
replay:
  # 直播间URL
  - url: https://live.bilibili.com/55
    # 此处省略一些可选参数

    # 上传设置
    upload:
      # 原视频
      src_video: 
        # 上传账号名称，程序依靠这个来识别不同的账号，如果打算传不同账号就要设置不同的名称
        account: bilibili
        # 上传的视频最短长度，小于此长度的视频会被自动过滤，默认五分钟
        min_length: 300
        # 是否为转载视频 1-自制 2-转载
        copyright: 1
        # 转载来源，如果设置为转载则必填
        source: ''
        # 分区号，分区参考 https://biliup.github.io/tid-ref.html
        tid: 65
        # 封面，指向本地文件地址
        cover: ''
        # 标题，可以使用关键字替换
        # 默认效果：[飞天狙想要努力变胖/直播回放] 晚上七点半比赛 2023年2月24日 （带弹幕版）
        title: '[{STREAMER}/直播回放] {TITLE} {YEAR}年{MONTH}月{DAY}日 {HAS_DANMU}'
        # 简介，可以使用关键字替换
        desc: '{STREAMER} 的直播回放，{YEAR}年{MONTH}月{DAY}日'
        # 动态内容，可以使用关键字替换
        dynamic: '{STREAMER} 的直播回放，{YEAR}年{MONTH}月{DAY}日'
        # 标签（一定要有！多个标签逗号分割）
        tag: '直播回放'
        # 允许转载? 0-允许转载，1-禁止转载
        no_reprint: 1
        # 是否开启充电? 0-关闭 1-开启
        open_elec: 1

      # 弹幕视频，选项和源视频都一样
      dm_video: 
        account: bilibili
        min_length: 300
        copyright: 1
        source: ''
        tid: 65
        cover: ''
        title: '[{STREAMER}/直播回放] {TITLE} {YEAR}年{MONTH}月{DAY}日 {HAS_DANMU}'
        desc: '{STREAMER} 的直播回放，{YEAR}年{MONTH}月{DAY}日'
        dynamic: '{STREAMER} 的直播回放，{YEAR}年{MONTH}月{DAY}日'
        tag: '直播回放'
        no_reprint: 1
        open_elec: 1
```
为了方便，这里只展示了录制一个直播间的设置，录制多个直播间同理。    
如果不想上传源视频就删掉src_video对应的所有参数。        
**特别提醒：登录信息将会保存在`.temp`文件夹里（以账户名称命名），不要将他分享给任何人！**

- 配置弹幕渲染参数（**非N卡用户必读！**）
```yaml
render: 
  # 硬件解码参数，默认自动，如果是CPU编码记得改为空
  hwaccel_args: [-hwaccel,auto] 
  # 使用NVIDIA H.264编码器，A卡用户设置为h264_amf，CPU渲染设置为libx264
  vencoder: h264_nvenc   
  # 指定编码器参数，默认15M码率         
  vencoder_args: ['-b:v','15M'] 
  # 输出重缩放，默认为空，可以设置为3840x2160绕过B站码率限制
  output_resize: ~              

# 这里replay的内容和上面例子一样可以随便改
replay:
  - url: https://live.bilibili.com/13308358
```
**关于硬件加速**：使用硬件加速编码遇到渲染失败问题，首先检查显卡驱动有没有更新！    

**关于输出重缩放**：很多人发现视频上传B站之后变糊（尤其是带弹幕的视频），但是本地看又很清晰，主要原因是B站现在对视频的码率做了限制，普通1080P视频码率一般不超过2Mbps(AV1编码)，只有直播的五分之一。   
为了绕过这个限制，需要使用伪4K的功能，简单地说就是把视频缩放到4K（3840x2160），让B站以为是4K视频然后按4K分配码率，这样一般能够分到15M的码率，最后看的时候就会很清晰。     

## 高阶使用     
本节介绍配置文件可用的全部选项和功能。如果你不理解的话随意修改可能会出现不可预料的问题。

