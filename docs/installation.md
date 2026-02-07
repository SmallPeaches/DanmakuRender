# DanmakuRender-4 安装指南
本文档描述了DanmakuRender-4（以下简称DMR）在不同平台下的安装步骤和常见问题。适用于从未接触过Python程序的新手阅读。     

**目录：**      
[Windows安装](#Windows安装)     
[Linux安装](#Linux安装)         
[macOS安装](#macOS安装)         
[备注](#备注)           

更新日期：2026.01.10。     

## Windows安装 

1. 安装Python            
[点击这里下载Python 3.12安装包](https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe)，需要下载其他版本的可以前往[官网](https://www.python.org/downloads/)自行下载。下载完成后点击安装，安装时注意选择`Add Python xxx to PATH`这个选项，其他默认就可以。     

2. 下载DMR主程序    
[点击这里下载](https://github.com/SmallPeaches/DanmakuRender/releases/latest)，选择下面的`Source code.zip`，下载完成之后解压即可。 

下载完成之后就可以运行了，程序会在第一次运行时自动安装FFmpeg等需要的组件，无需手动安装。这里仍然展示手动安装的步骤，供特殊情况下使用。

3. 安装Python包     
打开命令行窗口（win10系统shift+右键点击页面空白处，在菜单中选择“在此处打开powershell窗口”，win11在页面右键选择“在终端中打开”），输入下面的命令安装Python包。    
```shell
pip install -r requirements.txt
```

4. 安装FFmpeg       
[点击这里下载](https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip)，下载完成后解压，将`bin`文件夹里面的`ffmpeg.exe`、`ffprobe.exe`和`ffplay.exe`移动到程序中的`tools`文件夹下。如果下载慢的话可以考虑挂梯子或者自行前往国内镜像站下载，最后保证在程序的tools文件夹下有这三个文件即可。

5. 安装biliup-rs        
如果需要使用自动上传B站的功能则需要下载安装biliup-rs，可以前往其GitHub主页[下载](https://github.com/biliup/biliup-rs/releases/latest)，下载选择`版本名称-x86_64-windows.zip`，将解压得到的`biliup.exe`移动到程序中的`tools`文件夹下。

## Linux安装
这里以Ubuntu为例说明，其他的Linux发行版方法基本类似。   
**服务器录播建议参考([#368](https://github.com/SmallPeaches/DanmakuRender/discussions/368))**       

1. 安装Python            
Linux一般已经默认安装Python，使用命令`python -V`检测是否安装Python。如果没有安装请输入以下指令安装：
```shell
sudo apt install python3.12
```

2. 安装程序     
安装release版本的方法类似Windows，安装测试版的话可以使用git命令安装：
```git
git clone https://github.com/SmallPeaches/DanmakuRender.git
```

3. 安装Python包     
打开命令行窗口，输入下面的命令安装Python包。    
```shell
pip install -r requirements.txt
```

4. 安装FFmpeg       
使用apt-get快速安装：
```shell
sudo apt-get install ffmpeg
```
如果需要安装最新版本，请前往：https://ffmpeg.org/download.html      

5. 安装biliup-rs        
方法类似Windows安装，下载时选择Linux的预编译版本（xxx-linux.tar.xz），将其解压得到名为`biliup`的文件，并放入`tools`文件夹中。        

6. 安装JavaScript解释器           
在录制斗鱼和抖音弹幕时需要JavaScript解释器，部分Linux并没有预装，需要手动安装（这里以nodejs为例）：
```shell
sudo apt install nodejs npm
```
Linux平台下录制抖音直播时可能出现无法找到js引擎的问题(#349)，可以通过安装quickjs包解决：
```shell
pip install quickjs
```

## macOS安装
与Linux的安装方法基本类似，示例系统版本为macOS Sequoia 15.1.1。   

1. 安装Python            
macOS一般已经默认安装Python，使用命令`python -V`检测是否安装Python。如果没有请先安装 [Homebrew](https://brew.sh/) 之后输入以下指令安装：
```shell
brew install python@3.9
```

2. 安装程序     
安装release版本的方法类似Windows，安装测试版的话可以使用git命令安装：
```git
git clone https://github.com/SmallPeaches/DanmakuRender.git
```

3. 安装Python包     
打开 `终端` 应用程序，输入下面的命令安装Python包。    
```shell
pip install -r requirements.txt
```

4. 安装FFmpeg       
使用Homebrew快速安装：
```shell
brew install ffmpeg
```
如果需要安装最新版本，请前往：https://ffmpeg.org/download.html      

5. 安装biliup-rs        
方法类似Linux安装，下载时选择macOS的预编译版本（根据处理器平台选择aarch64或x86_64版本）        

6. 安装JavaScript解释器           
在录制斗鱼弹幕时需要JavaScript解释器，macOS并没有预装，需要手动安装（这里以nodejs为例）：
```shell
brew install node
```

## 备注     
- 如果需要使用硬件加速，请根据显卡类型自行前往官网下载最新的驱动程序，**渲染失败的最可能原因是没安装最新显卡驱动！**        
- DMR录制斗鱼弹幕的功能目前无法工作在Python 3.10以上，如果有需要的话请使用Python 3.9版本。        

