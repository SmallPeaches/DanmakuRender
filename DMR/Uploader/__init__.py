import logging
import threading
import queue

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

            group = task.get('group')
            if task.get('msg_type') == 'end':
                buffer_tasks = self.video_buffer.pop(group, 0)
                if not buffer_tasks:
                    logging.debug(f'uploader {group} buffer tasks empty.')
                    return

                self.upload_queue.put(buffer_tasks)
                if self.state_dict.get(group):
                    self.state_dict[group].append(buffer_tasks)
                else:
                    self.state_dict[group] = [buffer_tasks]
                self.state_dict[group].append(task)

            elif task.get('msg_type') == 'upload':
                if self.video_buffer.get(group):
                    self.video_buffer[group].append(task)
                else:
                    self.video_buffer[group] = [task]

    def _gather(self, task, status, desc=''):
        with self._lock:
            group = task[0].get('group')

            def filter_func(x) -> bool:
                return x != task
            self.state_dict[group] = list(filter(filter_func, self.state_dict[group]))
            files = [item['video'] for item in task]
            self.pipeSend(files, type=status, desc=desc, group=group, video_info=task[0].get('video_info'), task=task)

            if self.state_dict[group] and isinstance(self.state_dict[group][0], dict) and self.state_dict[group][0]['msg_type'] == 'end':
                self.state_dict[group].pop(0)
                self.pipeSend(group, type='end', group=group)

    def _uploader_subprocess(self):
        while not self.stoped:
            task = self.upload_queue.get()
            if task == 'exit':
                self.upload_queue.task_done()
                return

            logging.info(
                f"正在上传: {task[0]['group']} 至 {task[0]['upload_config']['account']}")
            logging.debug(f'uploading: {task}')
            try:
                task_config = task[0]['upload_config']
                uploader_name = task_config['uploader_name']
                uploader = self.uploaders[uploader_name]
                ok, info = True, ''
                # ok, info = uploader.upload_batch(task, task_config.copy())
                if ok:
                    self._gather(task, 'info', desc=info)
                else:
                    self._gather(task, 'error', desc=info)
            except KeyboardInterrupt:
                self.stop()
            except Exception as e:
                logging.exception(e)
                self._gather(task, 'error', desc=e)

            self.upload_queue.task_done()

    def start(self):
        self.stoped = False
        for _ in range(self.nuploaders):
            thread = threading.Thread(
                target=self._uploader_subprocess, daemon=True)
            thread.start()
        return

    def add(self, video, group=None, video_info=None, upload_configs=None, **kwargs):
        if video == 'end':
            self._distribute({
                'msg_type': 'end',
                'group': group,
            })
        else:
            for upload_config in upload_configs:
                min_length = upload_config.get('min_length', 0)
                if FFprobe.get_duration(video) > min_length:
                    self._distribute({
                        'msg_type': 'upload',
                        'video': video,
                        'group': group,
                        'video_info': video_info,
                        'upload_config': upload_config,
                        'kwargs': kwargs,
                    })

    def stop(self):
        self.stoped = True
        for uploader in self.uploaders.values():
            try:
                uploader.stop()
            except Exception as e:
                logging.debug(e)

        self._distribute('exit')
        logging.debug('uploader exit.')
