import logging
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

        if self.engine_args['dynamic_config']:
            threading.Thread(target=self._monintor, daemon=True).start()

    def _monintor(self):
        time.sleep(60)
        task_buffer = {}
        while not self.stoped:
            new_config = Config(self.config.global_config_path, self.engine_args.get('dynamic_config_path'))
            new_tasks = set(new_config.get_replaytasks()) - set(self.config.get_replaytasks())
            # del_tasks = set(self.config.get_replaytasks()) - set(new_config.get_replaytasks())
            for nt in new_tasks:
                if task_buffer.get(nt) is None:
                    task_buffer[nt] = 1
                else:
                    task_buffer[nt] += 1

            for taskname, count in task_buffer.items():
                if taskname not in new_tasks:
                    task_buffer[taskname] -= 1
                if count > 2:
                    self.logger.info(f'即将动态载入任务 {taskname}.')
                    new_task_config = new_config.get_replay_config(taskname)
                    self.logger.debug(f'New Task {taskname} Config:\n{json.dumps(new_task_config, indent=4, ensure_ascii=False)}')
                    self.config.replay_config[taskname] = new_task_config
                    self.engine.add_task(taskname, new_task_config)
                    task_buffer.pop(taskname)
                if count < 0:
                    task_buffer.pop(taskname)
            
            time.sleep(60)

    def stop(self):
        self.stoped = True
        self.engine.stop()
