import logging
import threading
import queue
import time

from DMR.message import PipeMessage
from DMR.utils import FFprobe


class Uploader():
    def __init__(self, pipe, replay_config: dict, nuploaders: int, debug=False, **kwargs):
        self.nuploaders = nuploaders
        self.replay_config = replay_config
        self.debug = debug
        self.sender = pipe
        self.kwargs = kwargs

        self._lock = threading.Lock()
        self.upload_queue = queue.Queue()
        self.video_buffer = {}
        self.uploaders = {}
        self.state_dict = {}

        for taskname, rep_conf in replay_config.items():
            for upd_type, upd_configs in rep_conf.get('upload', {}).items():
                for upid, upd_conf in enumerate(upd_configs):
                    uploader_name = upd_conf['uploader_name']
                    engine = upd_conf['engine']
                    account = upd_conf['account']
                    if engine.lower() == 'biliuprs':
                        from .biliuprs import biliuprs
                        uploader = biliuprs(debug=self.debug, **upd_conf)
                        self.uploaders[uploader_name] = uploader

        if self.nuploaders <= 0:
            self.nuploaders = len(self.uploaders)

    def pipeSend(self, msg, type='info', group=None, **kwargs):
        if self.sender:
            self.sender.put(PipeMessage(
                'uploader', msg=msg, type=type, group=group, **kwargs))
        else:
            print(PipeMessage('uploader', msg=msg, type=type, group=group, **kwargs))

    def _distribute(self, task):
        with self._lock:
            if task == 'exit':
                for _ in range(len(self.uploaders)):
                    self.upload_queue.put(task)
                return
            
            group = task['group']
            realtime = task['upload_config']['realtime']
            # 实时上传
            if realtime:
                if self.state_dict.get(group):
                    self.state_dict[group].append(task)
                elif task['msg_type'] == 'end':
                    uploader_name = task['uploader_name']
                    uploader = self.uploaders[uploader_name]
                    uploader.end_upload()
                    self.pipeSend(group, type='end', group=group)
                else:
                    self.state_dict[group] = [task]
                if task['msg_type'] == 'upload':
                    self.upload_queue.put(task)
            # 普通上传
            else:
                uploader_name = task['uploader_name']
                if task.get('msg_type') == 'end':
                    buffer_tasks = self.video_buffer.pop(uploader_name, 0)
                    if not buffer_tasks:
                        logging.debug(f'uploader {uploader_name} buffer tasks empty.')
                        return

                    self.upload_queue.put(buffer_tasks)
                    if self.state_dict.get(group):
                        self.state_dict[group].append(buffer_tasks)
                    else:
                        self.state_dict[group] = [buffer_tasks]
                    self.state_dict[group].append(task)

                elif task.get('msg_type') == 'upload':
                    if self.video_buffer.get(uploader_name):
                        self.video_buffer[uploader_name].append(task)
                    else:
                        self.video_buffer[uploader_name] = [task]

    def _gather(self, task, status, desc=''):
        with self._lock:
            if isinstance(task, dict):
                group = task['group']
                video_info=task['video_info']
                self.state_dict[group] = list(filter(lambda x: x!=task, self.state_dict[group]))
                files = [task['video']]
            else:
                group = task[0]['group']
                video_info=task[0].get('video_info')
                self.state_dict[group] = list(filter(lambda x: x!=task, self.state_dict[group]))
                files = [item['video'] for item in task]
            
            self.pipeSend(files, type=status, desc=desc, group=group, video_info=video_info, task=task)

            if self.state_dict[group] and isinstance(self.state_dict[group][0], dict) and self.state_dict[group][0]['msg_type'] == 'end':
                # 实时上传，需要发送结束信号
                if isinstance(task, dict):
                    uploader_name = self.state_dict[group][0]['uploader_name']
                    uploader = self.uploaders[uploader_name]
                    uploader.end_upload()
                
                self.state_dict[group].pop(0)
                self.pipeSend(group, type='end', group=group)

    def _uploader_subprocess(self):
        while not self.stoped:
            task = self.upload_queue.get()
            if task == 'exit':
                self.upload_queue.task_done()
                return

            # 使用实时上传
            if isinstance(task, dict):
                task_config = task['upload_config']
                uploader_name = task['uploader_name']
                uploader = self.uploaders[uploader_name]
                video = task['video']
                video_info = task['video_info']
                upload_func = uploader.upload_one
            # 使用普通上传
            else:
                task_config = task[0]['upload_config']
                uploader_name = task[0]['uploader_name']
                uploader = self.uploaders[uploader_name]
                video = [t['video'] for t in task]
                video_info = [t['video_info'] for t in task]
                upload_func = uploader.upload_batch
            
            retry = task_config.get('retry', 0)
            status = info = None
            while retry >= 0:
                try:
                    logging.info(
                        f"正在上传 {video} 至 {task_config['account']}")
                    logging.debug(task)

                    status, info = upload_func(
                        video=video, 
                        video_info=video_info,
                        config=task_config,
                    )
                except KeyboardInterrupt:
                    self.stop()
                    return
                except Exception as e:
                    status, info = False, e
                    logging.exception(e)
                
                if status:
                    break
                else:
                    logging.warn(f'上传 {video} 时出现错误，即将重传.')
                    logging.debug(info)
                    time.sleep(60)
                    retry -= 1
            
            if status:
                self._gather(task, 'info', desc=info)
            else:
                self._gather(task, 'error', desc=info)

            self.upload_queue.task_done()

    def start(self):
        self.stoped = False
        for _ in range(self.nuploaders):
            thread = threading.Thread(
                target=self._uploader_subprocess, daemon=True)
            thread.start()
        return

    def add(self, video, group=None, video_info=None, upload_configs=None, **kwargs):
        for upload_config in upload_configs:
            if video == 'end':
                self._distribute({
                    'msg_type': 'end',
                    'group': group,
                    'video_info': video_info,
                    'upload_config': upload_config,
                    'uploader_name': upload_config['uploader_name'],
                    'kwargs': kwargs,
                })
            else:
                min_length = upload_config.get('min_length', 0)
                duration = FFprobe.get_duration(video)
                if duration <= 0:
                    duration = video_info.get('duration', duration)
                if duration > min_length:
                    self._distribute({
                        'msg_type': 'upload',
                        'video': video,
                        'group': group,
                        'video_info': video_info,
                        'upload_config': upload_config,
                        'uploader_name': upload_config['uploader_name'],
                        'kwargs': kwargs,
                    })
                else:
                    logging.info(f'视频 {video} 过短，设置 {min_length}s，实际 {duration}s，跳过上传.')

    def stop(self):
        self.stoped = True
        for uploader in self.uploaders.values():
            try:
                uploader.stop()
            except Exception as e:
                logging.debug(e)

        self._distribute('exit')
        logging.debug('uploader exit.')
