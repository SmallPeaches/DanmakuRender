import logging
import threading
import multiprocessing
import queue
import time
import os

from .Cleaner import Cleaner
from .Uploader import Uploader
from .Render import Render
from .Downloader import Downloader
from .Config import Config


class DanmakuRender():
    def __init__(self, config: Config, debug=False) -> None:
        self.config = config
        self.debug = debug
        self.stoped = True

        self.downloaders = {}
        self.uploaders = {}
        self.signal_queue = queue.Queue()

    def start(self):
        self.stoped = False
        self.monitor = threading.Thread(
            target=self.message_monitor, daemon=True)
        self.monitor.start()

        self.render = Render(
            pipe=self.signal_queue,
            debug=self.debug,
            replay_config=self.config.replay_config,
            **self.config.render_config
        )
        self.render.start()

        self.uploader = Uploader(
            pipe=self.signal_queue,
            debug=self.debug,
            replay_config=self.config.replay_config,
            **self.config.uploader_config
        )
        self.uploader.start()

        self.cleaner = Cleaner(
            pipe=self.signal_queue,
            debug=self.debug,
            replay_config=self.config.replay_config,
        )
        self.cleaner.start()

        for taskname, replay_conf in self.config.replay_config.items():
            logging.getLogger().info(f'添加直播：{replay_conf["url"]}')

            downloader = Downloader(
                taskname=taskname, pipe=self.signal_queue, debug=self.debug, **replay_conf)
            proc = downloader.start()

            self.downloaders[taskname] = {
                'class': downloader,
                'proc': proc,
                'status': None,
            }

    def message_monitor(self):
        while not self.stoped:
            msg = self.signal_queue.get()
            if self.stoped or msg == 'exit':
                return
            logging.debug(f'PIPE MESSAGE: {msg}')
            if msg.get('src') == 'downloader':
                self.process_downloader_message(msg)
            elif msg.get('src') == 'render':
                self.process_render_message(msg)
            elif msg.get('src') == 'uploader':
                self.process_uploader_message(msg)
            elif msg.get('src') == 'cleaner':
                self.process_cleaner_message(msg)

    def process_cleaner_message(self, msg):
        type = msg['type']
        file = msg['msg']
        if type == 'info':
            logging.info(f"文件 {file} 清理完成: {msg.get('desc')}")
        elif type == 'error':
            logging.error(f'文件 {file} 清理错误.')
            logging.error(msg.get('desc'))

    def process_uploader_message(self, msg):
        type = msg['type']
        group, vtype = msg['group']
        replay_config = self.config.get_replay_config(group)
        if type == 'info':
            files = msg['msg']
            logging.info(f'视频 {files} 上传完成:')
            logging.info(msg.get('desc'))
            clean_configs = replay_config.get('clean')
            if clean_configs and clean_configs.get(vtype):
                if vtype == 'src_video':
                    files += [os.path.splitext(f)[0]+'.ass' for f in files]
                logging.info(f'添加以下文件到清理队列： {files}.')
                self.cleaner.add(files, group, video_info=msg.get('video_info'), clean_configs=clean_configs[vtype])

        elif type == 'error':
            files = msg['msg']
            logging.error(f'视频 {files} 上传错误.')
            logging.error(msg.get('desc'))

    def process_downloader_message(self, msg):
        type = msg['type']
        group = msg['group']
        replay_config = self.config.get_replay_config(group)
        if type == 'info':
            info = msg['msg']
            if info == 'start':
                self.downloaders[group]['status'] = 'start'
                logging.info(f'{group} 录制开始.')
            elif info == 'end':
                if self.downloaders[group]['status'] is None:
                    logging.info(f'{group} 直播结束，正在等待.')
                elif self.downloaders[group]['status'] == 'start':
                    logging.info(f'{group} 录制结束，正在等待.')
                    if replay_config.get('danmaku') and replay_config.get('auto_render'):
                        self.render.add('end', group=group, video_info=msg.get('video_info'),
                                        render_config=replay_config['render'])
                    if replay_config.get('upload') and replay_config['upload'].get('src_video'):
                        self.uploader.add('end', group=(group, 'src_video'), video_info=msg.get('video_info'),
                                          upload_configs=replay_config['upload']['src_video'])
                self.downloaders[group]['status'] = 'end'

        elif type == 'split':
            fp = msg['msg']
            logging.info(f'分片 {fp} 录制完成.')

            if replay_config.get('danmaku') and replay_config.get('auto_render') and replay_config.get('video'):
                logging.info(f'添加分片 {fp} 至渲染队列.')
                self.render.add(fp, group=group, video_info=msg.get('video_info'),
                                render_config=replay_config.get('render'))

            if replay_config.get('upload') and replay_config['upload'].get('src_video'):
                self.uploader.add(fp, group=(group, 'src_video'), video_info=msg.get('video_info'),
                                    upload_configs=replay_config['upload']['src_video'])

        elif type == 'error':
            logging.error(f'录制 {group} 遇到错误，即将重试.')
            logging.error(msg.get('desc'))

    def process_render_message(self, msg):
        type = msg['type']
        group = msg['group']
        replay_config = self.config.get_replay_config(group)
        if type == 'info':
            fp = msg['msg']
            logging.info(f'分片 {fp} 渲染完成.')
            logging.info(msg.get('desc'))

            if replay_config.get('upload') and replay_config['upload'].get('dm_video'):
                self.uploader.add(fp, group=(group, 'dm_video'), video_info=msg.get('video_info'),
                                    upload_configs=replay_config['upload']['dm_video'])

        elif type == 'end':
            logging.info(f'完成对 {group} 的全部视频渲染.')

            if replay_config.get('upload') and replay_config['upload'].get('dm_video'):
                self.uploader.add('end', group=(group, 'dm_video'), video_info=msg.get('video_info'),
                                    upload_configs=replay_config['upload']['dm_video'])

        elif type == 'error':
            fp = msg['msg']
            logging.error(f'分片 {fp} 渲染错误.')
            logging.error(msg.get('desc'))

    def stop(self):
        self.stoped = True
        for taskname, task in self.downloaders.items():
            try:
                task['class'].stop()
            except Exception as e:
                logging.exception(e)

        self.downloaders.clear()
        self.render.stop()
        self.uploader.stop()
        self.cleaner.stop()
        self.signal_queue.put('exit')
        logging.debug('DMR engine stop.')
