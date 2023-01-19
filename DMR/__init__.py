import logging
import threading
import multiprocessing
import queue
import time
from .Uploader import Uploader
from .Render import Render
from .Downloader import Downloader
from .utils import Config

class DanmakuRender():
    def __init__(self, config:Config, debug=False) -> None:
        self.config = config
        self.debug = debug

        self.downloaders = {}
        self.uploaders = {}
        self.downloader_recv = queue.Queue()
        self.render_recv = queue.Queue()
        self.uploader_recv = queue.Queue()
        
    def start(self):
        self.monitor = threading.Thread(target=self.start_monitor,daemon=True)
        self.monitor.start()

        self.render = Render(pipe=self.render_recv, debug=self.debug, **self.config.render_config)
        self.render.start()

        if self.config.uploader_config:
            for name, uploader_conf in self.config.uploader_config.items():
                uploader = Uploader(name,self.uploader_recv,uploader_conf,debug=True)
                proc = uploader.start()
                self.uploaders[name] = {
                    'class':uploader,
                    'proc':proc,
                    'config':uploader_conf
                }

        for taskname, replay_conf in self.config.replay_config.items():
            logging.getLogger().info(f'添加直播：{replay_conf["url"]}')
            
            downloader = Downloader(taskname=taskname, pipe=self.downloader_recv, debug=self.debug, **replay_conf)
            proc = downloader.start()

            self.downloaders[taskname] = {
                'class': downloader,
                'proc': proc,
                'status': None,
            }

    def start_monitor(self):
        while 1:
            try:
                msg = self.uploader_recv.get_nowait()
                self.process_uploader_message(msg)
                continue
            except queue.Empty:
                pass
            try:
                msg = self.downloader_recv.get_nowait()
                self.process_downloader_message(msg)
                continue
            except queue.Empty:
                pass
            try:
                msg = self.render_recv.get_nowait()
                self.process_render_message(msg)
                continue
            except queue.Empty:
                time.sleep(1)

    def process_uploader_message(self,msg):
        type = msg['type']
        if type == 'info':
            fp = msg['msg']
            logging.info(f'分片 {fp} 上传完成.')
            logging.info(msg.get('desc'))
        elif type == 'error':
            fp = msg['msg']
            logging.error(f'分片 {fp} 上传错误.')
            logging.exception(msg.get('desc'))
            
    def process_downloader_message(self, msg):
        type = msg['type']
        src = msg['src']
        if type == 'info':
            info = msg['msg']
            if info == 'start':
                self.downloaders[src]['status'] = 'start'
                logging.info(f'{msg["src"]} 录制开始.')
            elif info == 'end':
                if self.downloaders[src]['status'] is None:
                    logging.info(f'{msg["src"]} 直播结束，正在等待.')
                elif self.downloaders[src]['status'] == 'start':
                    logging.info(f'{msg["src"]} 录制结束，正在等待.')
                # logging.info(f'{msg["src"]} 直播结束，正在等待.')
                self.downloaders[src]['status'] = 'end'
        
        elif type == 'split':
            fp = msg['msg']
            logging.info(f'分片 {fp} 录制完成.')
            conf = self.config.get_replay_config(src)
            if conf.get('danmaku') and not conf.get('skip_render'):
                logging.info(f'添加分片 {fp} 至渲染队列.')
                self.render.add(fp, output_dir=conf.get('output_dir'), video_info=msg['video_info'])
            
            if conf.get('upload'):
                for upd in conf['upload']:
                    uploader = self.uploaders[upd]['class']
                    group = msg['video_info'].get('group')
                    upd_conf = self.uploaders[upd]['config']

                    if upd_conf.get('include') is None or upd_conf.get('include') == 'src_video':
                        logging.info(f'即将上传原始视频分片 {fp} 至 {upd}.')
                        uploader.add(fp, group, video_info=msg.get('video_info'), **upd_conf)

                    # TODO:
                    # if upd_conf.get('include') is None or upd_conf.get('include') == 'danmu':
                    #     continue

        elif type == 'error':
            logging.error(f'录制 {msg["src"]} 遇到错误，即将重试.')
            logging.exception(msg.get('desc'))

    def process_render_message(self, msg):
        type = msg['type']
        if type == 'info':
            fp = msg['msg']
            logging.info(f'分片 {fp} 渲染完成.')
            logging.info(msg.get('desc'))
            src = msg['video_info']['taskname']
            conf = self.config.get_replay_config(src)

            if conf.get('upload'):
                for upd in conf['upload']:
                    uploader = self.uploaders[upd]['class']
                    group = msg['video_info'].get('group')
                    upd_conf = self.uploaders[upd]['config']

                    if upd_conf.get('include') is None or upd_conf.get('include') == 'src_video':
                        logging.info(f'即将上传带弹幕视频分片 {fp} 至 {upd}.')
                        uploader.add(fp, group, video_info=msg.get('video_info'), **upd_conf)
            
        elif type == 'error':
            fp = msg['msg']
            logging.error(f'分片 {fp} 渲染错误.')
            logging.exception(msg.get('desc'))

    def stop(self):
        for taskname, task in self.downloaders.items():
            try:
                task['class'].stop()
            except Exception as e:
                logging.exception(e)
                # logging.debug(e)
        self.downloaders.clear()
        self.render.stop()
        time.sleep(1)
    
        