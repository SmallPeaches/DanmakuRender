import logging
import os
import shutil
import threading
import json
import time
import logging

from .engine import DMREngine
from .Config import Config


class DanmakuRender():
    def __init__(self, config:Config, **kwargs) -> None:
        self.logger = logging.getLogger('DMR')
        self.config = config
        self.kwargs = kwargs
        self.stoped = True
        self.engine_args = self.config.get_config('dmr_engine_args')
        self.engine = DMREngine()

    def start(self):
        self.stoped = False
        self.logger.debug(f'Global Config:\n{json.dumps(self.config.global_config, indent=4, ensure_ascii=False)}')
        self.logger.debug(f'Replay Config:\n{json.dumps(self.config.replay_config, indent=4, ensure_ascii=False)}')
        self.engine.start()
        plugin_enabled = self.config.get_config('dmr_engine_args')['enabled_plugins']
        for plugin_name in plugin_enabled:
            plugin_config = self.config.get_config(plugin_name+'_kernel_args')
            self.engine.add_plugin(plugin_name, plugin_config)

        for taskname in self.config.get_replaytasks():
            replay_config = self.config.get_replay_config(taskname)
            self.engine.add_task(taskname, replay_config)

        threading.Thread(target=self._monintor, daemon=True).start()

    def _monintor(self):
        REFRESH_INTERVAL = 60
        time.sleep(REFRESH_INTERVAL)
        task_buffer = {}
        while not self.stoped:
            # dynamic load config
            if self.engine_args['dynamic_config']:
                new_config = Config(self.config.global_config_path, self.engine_args.get('dynamic_config_path'))
                new_tasks = set(new_config.get_replaytasks()) - set(self.config.get_replaytasks())
                del_tasks = set(self.config.get_replaytasks()) - set(new_config.get_replaytasks())
                for nt in new_tasks:
                    if task_buffer.get(nt) is None:
                        task_buffer[nt] = 1
                    else:
                        task_buffer[nt] += 1
                for dt in del_tasks:
                    if task_buffer.get(dt) is None:
                        task_buffer[dt] = -1
                    else:
                        task_buffer[dt] -= 1
                
                for taskname, count in list(task_buffer.items()):
                    if taskname not in new_tasks and count > 0:
                        task_buffer[taskname] -= 1
                    if taskname not in del_tasks and count < 0:
                        task_buffer[taskname] += 1
                    if count > 2:
                        self.logger.info(f'即将动态载入任务 {taskname}.')
                        new_task_config = new_config.get_replay_config(taskname)
                        self.logger.debug(f'New Task {taskname} Config:\n{json.dumps(new_task_config, indent=4, ensure_ascii=False)}')
                        self.config.replay_config[taskname] = new_task_config
                        self.engine.add_task(taskname, new_task_config)
                        task_buffer.pop(taskname)
                    elif count < -2:
                        self.logger.info(f'即将动态取消任务 {taskname}.')
                        self.engine.del_task(taskname)
                        self.config.replay_config.pop(taskname)
                        task_buffer.pop(taskname)
                    elif count == 0:
                        task_buffer.pop(taskname)

            # clean temp file
            files = os.listdir('.temp')
            for file in files:
                try:
                    basename = os.path.splitext(os.path.basename(file))[0]
                    expired_time = basename.split('_')[-1]
                    if expired_time.isdigit():
                        expired_time = int(expired_time)
                    else:
                        expired_time = 0
                    # 只清理2024.01.01之后的过期文件，过早的文件认为不是程序创建的不清理
                    if expired_time > 1704038400 and expired_time < int(time.time()):
                        file = os.path.join('.temp', file)
                        if os.path.isfile(file):
                            os.remove(file)
                            self.logger.debug(f'已清理临时文件: {file}')
                        elif os.path.isdir(file):
                            shutil.rmtree(file)
                            self.logger.debug(f'已清理临时文件夹: {file}')
                except Exception as e:
                    self.logger.debug(f'清理临时文件{file}失败: {e}')
            
            time.sleep(REFRESH_INTERVAL)

    def stop(self):
        self.stoped = True
        self.engine.stop()
