import os
import glob
import yaml

from copy import deepcopy
from typing import List
from DMR.utils import *

# __all__ = ['Config', 'new_config']

class Config():
    _base_config_path = 'DMR/Config/default.yml'

    def __init__(self, global_config_path:str, replay_config_path:List[str]) -> None:
        with open(self._base_config_path, 'r', encoding='utf-8') as f:
            self._base_config = yaml.safe_load(f)

        self.global_config_path = global_config_path
        if isinstance(replay_config_path, str):
            self.replay_config_path = sorted(glob.glob(os.path.join(replay_config_path, 'DMR-**.yml')))
        else:
            self.replay_config_path = replay_config_path
        
        self.global_config = deepcopy(self._base_config)
        self.replay_config = {}

        with open(global_config_path, 'r', encoding='utf-8') as f:
            _global_config = yaml.safe_load(f)
        
        self.global_config = merge_dict(self.global_config, _global_config)

        for toolname, path in self.global_config.get('executable_tools_path',{}).items():
            if not path:
                ToolsList.get(toolname, auto_install=True)
            else:
                ToolsList.set(toolname, path)

        for config_path in self.replay_config_path:
            with open(config_path, 'r', encoding='utf-8') as f:
                _replay_config = yaml.safe_load(f)
            taskname = os.path.splitext(os.path.basename(config_path))[0].split('-', 1)[-1]
            replay_config = {}
            # self.replay_config[taskname] = replay_config
            common_args = _replay_config.get('common_event_args')
            replay_config['common_event_args'] = deepcopy(common_args)
            
            global_download_args = self.global_config['download_args']
            dltype = _replay_config.get('download_args', {}).get('dltype', 'live')
            replay_config['download_args'] = deepcopy(global_download_args[dltype])
            if _replay_config.get('download_args'):
                replay_config['download_args'] = merge_dict(replay_config['download_args'], _replay_config['download_args'])

            if common_args.get('auto_render') or common_args.get('auto_transcode'):
                replay_config['render_args'] = deepcopy(self.global_config['render_args'])
                if _replay_config.get('render_args'):
                    replay_config['render_args'] = merge_dict(replay_config['render_args'], _replay_config['render_args'])

            if common_args.get('auto_upload'):
                global_upload_args = self.global_config['upload_args']
                replay_config['upload_args'] = {}
                if _replay_config.get('upload_args'):
                    for upload_file_types, upload_args in _replay_config['upload_args'].items():
                        if isinstance(upload_args, dict):
                            upload_args = [upload_args]
                        replay_config['upload_args'][upload_file_types] = []
                        for upload_arg in upload_args:
                            target = upload_arg.get('target', 'bilibili')
                            if not global_upload_args.get(target):
                                raise ValueError(f'不存在可用的上传目标 {target}.')
                            upload_config = deepcopy(global_upload_args[target])
                            upload_config.update(upload_arg)
                            replay_config['upload_args'][upload_file_types].append(upload_config)

            if common_args.get('auto_clean'):
                global_clean_args = self.global_config['clean_args']
                replay_config['clean_args'] = {}
                if _replay_config.get('clean_args'):
                    for clean_file_types, clean_args in _replay_config['clean_args'].items():
                        if isinstance(clean_args, dict):
                            clean_args = [clean_args]
                        replay_config['clean_args'][clean_file_types] = []
                        for clean_arg in clean_args:
                            method = clean_arg.get('method')
                            if not method:
                                continue
                            if not global_clean_args.get(method):
                                raise ValueError(f'不存在可用的清理方法 {method}.')
                            clean_config = deepcopy(global_clean_args[method])
                            clean_config.update(clean_arg)
                            replay_config['clean_args'][clean_file_types].append(clean_config)

            self.replay_config[taskname] = deepcopy(replay_config)

    def get_config(self, name):
        return self.global_config.get(name)
    
    def get_replay_config(self, taskname):
        return self.replay_config.get(taskname)
    
    def get_replaytasks(self):
        return list(self.replay_config.keys())
