import logging
import os
import queue
import threading

from os.path import exists, isdir, isfile, abspath, dirname
from DMR.message import PipeMessage
from DMR.utils import replace_keywords


class Cleaner():
    def __init__(self, pipe, replay_config, debug, **kwargs) -> None:
        self.sender = pipe
        self.replay_config = replay_config
        self.debug = debug
        self.kwargs = kwargs
        self.stoped = True
        self.execute_queue = queue.Queue()

    def pipeSend(self, msg, type='info', group=None, **kwargs):
        if self.sender:
            self.sender.put(PipeMessage(
                'cleaner', msg=msg, type=type, group=group, **kwargs))
        else:
            print(PipeMessage('cleaner', msg=msg, type=type, group=group, **kwargs))

    def start(self):
        self.stoped = False
        t = threading.Thread(target=self._run_queue, daemon=True)
        t.start()
        return t

    def _run_queue(self):
        while not self.stoped:
            task = self.execute_queue.get()
            if task == 'exit':
                self.execute_queue.task_done()
                return
            
            try:
                logging.debug(f'Clean files: {task}')
                method = task['method']
                src = abspath(task['video'])
                dst = task['config'].get('dest')
                if dst and not dst.startswith('*'):
                    dst = abspath(replace_keywords(dst, task.get('video_info'), replace_invalid=True))
                    if not exists(dst):
                        logging.info(f'目标文件夹 {dst} 不存在，即将自动创建.')
                        os.makedirs(dst)
                
                if method == 'move':
                    from .move import move
                    move.move(src, dst)
                elif method == 'copy':
                    from .copy import copy
                    copy.copy(src, dst)
                elif method == 'delete':
                    from .delete import delete
                    delete.delete(src)
                self.pipeSend(src, 'info', desc=f'{method} {src} -> {dst}.')
                
            except Exception as e:
                logging.exception(e)
                self.pipeSend(src, 'error', desc=e)

    def add(self, videos, group=None, video_info=None, clean_configs=None, **kwargs):
        for clean_config in clean_configs:
            if isinstance(videos, str):
                videos = [videos]
            
            if len(videos) == 1 and clean_config['strict'] == False:
                extra = [video_info.get('src_file'), video_info.get('dm_file')]
                logging.info(f'即将清理额外的原视频：{extra}')
                videos += [x for x in extra if x]

            for video in videos:
                if not exists(video):
                    continue
                task = {
                    'msg_type': 'clean',
                    'method': clean_config['method'],
                    'video': video,
                    'group': group, 
                    'video_info': video_info,
                    'config': clean_config,
                    'kwargs': kwargs,
                }
                if clean_config.get('delay') > 0:
                    threading.Timer(clean_config.get('delay'), self.execute_queue.put, args=(task,)).start()
                else:
                    self.execute_queue.put(task)

    def stop(self):
        self.stoped = True
        self.execute_queue.put('exit')
        logging.debug('Cleaner exit.')