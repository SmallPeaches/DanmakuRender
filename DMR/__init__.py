import logging
import os
import shutil
import threading
import json
import time
import logging
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from .engine import DMREngine
from .Config import Config

class ConfigEventHandler(FileSystemEventHandler):
    def __init__(self, dmr):
        self.dmr = dmr
        self.last_check = 0
        self.debounce_interval = 1.0

    def on_any_event(self, event):
        if event.is_directory:
            return
        filename = os.path.basename(event.src_path)
        if filename == 'global.yml' or (filename.startswith('DMR-') and filename.endswith('.yml')):
            if time.time() - self.last_check < self.debounce_interval:
                return
            self.last_check = time.time()
            self.dmr.check_config_update()

class DanmakuRender():
    def __init__(self, config:Config, **kwargs) -> None:
        self.logger = logging.getLogger('DMR')
        self.config = config
        self.kwargs = kwargs
        self.stoped = True
        self.engine_args = self.config.get_config('dmr_engine_args')
        self.engine = DMREngine()
        self.observer = None

    def start(self):
        self.stoped = False
        os.makedirs('.temp', exist_ok=True)
        
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
            self.start_watchdog()

        threading.Thread(target=self._monintor, daemon=True).start()

    def start_watchdog(self):
        self.observer = Observer()
        event_handler = ConfigEventHandler(self)
        
        # Watch global config directory (parent of global.yml)
        global_config_dir = os.path.dirname(os.path.abspath(self.config.global_config_path))
        self.observer.schedule(event_handler, global_config_dir, recursive=False)
        
        # Watch task config directory
        if isinstance(self.config.replay_config_path_raw, str):
            task_config_dir = self.config.replay_config_path_raw
            if task_config_dir != global_config_dir:
                 self.observer.schedule(event_handler, task_config_dir, recursive=False)
        else:
             # If list of paths, watch directories of those paths
             # This is a bit complex if they are scattered. 
             # Assuming they are in the same dir or we watch common parents.
             # For simplicity, if raw is list, we iterate and watch unique dirs.
             watched_dirs = set()
             for path in self.config.replay_config_path_raw:
                 d = os.path.dirname(os.path.abspath(path))
                 if d not in watched_dirs:
                     self.observer.schedule(event_handler, d, recursive=False)
                     watched_dirs.add(d)

        self.observer.start()
        self.logger.info("Config watchdog started.")

    def check_config_update(self):
        try:
            update_type, update_info = self.config.check_update()
            
            if update_type == 'global':
                self.logger.info('检测到全局配置更新，请重启程序以生效。')
            
            elif update_type == 'tasks':
                for config_path in update_info['new']:
                    taskname = self.config.update_task_config(config_path)
                    if taskname:
                        self.logger.info(f'检测到新任务配置文件: {taskname}，正在添加任务...')
                        self.engine.add_task(taskname, self.config.get_replay_config(taskname))
                
                for config_path in update_info['deleted']:
                    taskname = os.path.splitext(os.path.basename(config_path))[0].split('-', 1)[-1]
                    self.logger.info(f'检测到任务配置文件删除: {taskname}，正在停止任务...')
                    self.engine.del_task(taskname)
                    if taskname in self.config.replay_config:
                        del self.config.replay_config[taskname]

                for config_path in update_info['updated']:
                    taskname = os.path.splitext(os.path.basename(config_path))[0].split('-', 1)[-1]
                    self.logger.info(f'检测到任务配置文件更新: {taskname}，正在重启任务...')
                    
                    self.engine.del_task(taskname)
                    time.sleep(5) 
                    
                    new_taskname = self.config.update_task_config(config_path)
                    if new_taskname:
                        self.engine.add_task(new_taskname, self.config.get_replay_config(new_taskname))

        except Exception as e:
            self.logger.error(f'动态载入配置文件错误:')
            self.logger.exception(e)

    def _monintor(self):
        REFRESH_INTERVAL = 60
        time.sleep(REFRESH_INTERVAL)
        while not self.stoped:
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
        if self.observer:
            self.observer.stop()
            self.observer.join()
        self.engine.stop()
