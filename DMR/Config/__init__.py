
import warnings
import shutil
import yaml

from tools import ToolsList
from tools.check_env import *
from DMR.utils import *
from DMR.LiveAPI import GetStreamerInfo, split_url, AVAILABLE_DANMU, AVAILABLE_LIVE

__all__ = ['Config', 'new_config']


class Config():
    _base_config = 'DMR/Config/default_config.yml'

    def __init__(self, default_conf: dict, replay_conf: dict) -> None:
        with open(self._base_config, 'r', encoding='utf-8') as f:
            self.base_conf = yaml.safe_load(f)

        self.default_conf = self.base_conf.copy()
        for k, v in default_conf.items():
            if isinstance(v, dict) and self.default_conf.get(k):
                self.default_conf[k].update(v)
            else:
                self.default_conf[k] = v

        self.replay_conf = replay_conf.copy()
        self.config = default_conf.copy()
        self.config['upload'] = {}

        # 处理 render 配置
        if self.replay_conf.get('render'):
            self.config['render'].update(self.replay_conf.get('render'))

        # 处理 uploader 配置
        if self.replay_conf.get('uploader'):
            for k, v in self.replay_conf['uploader'].items():
                if isinstance(v, dict) and self.config['uploader'].get(k):
                    self.config['uploader'][k].update(v)
                else:
                    self.config['uploader'][k] = v

        # 处理 replay 配置
        if self.replay_conf.get('replay'):
            self.config['replay'] = {}
            replay = self.replay_conf['replay']
            if isinstance(replay, list):
                for rep in replay:
                    rep_conf = self.default_conf['downloader'].copy()
                    rep_conf.update(rep)
                    name = GetStreamerInfo(rep['url'])[1]
                    self.config['replay'][name] = rep_conf
            elif isinstance(replay, dict):
                for name, rep in replay.items():
                    rep_conf = self.default_conf['downloader'].copy()
                    rep_conf.update(rep)
                    self.config['replay'][name] = rep_conf

            for name, conf in self.config['replay'].items():
                if conf.get('render'):
                    render_config = self.config['render'].copy()
                    render_config.update(conf.get('render'))
                    conf['render'] = render_config
                else:
                    conf['render'] = self.config['render'].copy()

        # 处理旧版上传器配置
        if self.replay_conf.get('upload'):
            upload = self.replay_conf['upload']
            for upd in upload.keys():
                if not upload[upd].get('target'):
                    upload[upd]['target'] = 'bilibili'
                target = upload[upd]['target']
                upload_conf = self.default_conf['uploader'][target].copy()
                upload_conf.update(upload[upd])
                self.config['upload'][upd] = upload_conf

        # 写入新版上传配置
        for name, rep_conf in self.config['replay'].items():
            for vtype, upd_configs in rep_conf.get('upload', {}).items():
                if isinstance(upd_configs, str):
                    upd_configs = upd_configs.split(',')
                elif isinstance(upd_configs, dict):
                    upd_configs = [upd_configs]
                for upid, upd_conf in enumerate(upd_configs):
                    if len(upd_conf) < 0:
                        continue
                    if isinstance(upd_conf, dict):
                        target = upd_conf.get('target', 'bilibili')
                        full_upload_conf = self.default_conf['uploader'][target].copy()
                        full_upload_conf.update(upd_conf)
                        upd_conf = full_upload_conf
                    elif self.config.get('upload') and self.config['upload'].get(upd_conf):
                        upd_conf = self.config['upload'].get(upd_conf).copy()
                    elif self.default_conf['uploader'].get(upd_conf):
                        upd_conf = self.default_conf['uploader'][upd_conf].copy()
                    else:
                        raise ValueError(f'不存在上传器 {upd_conf}.')
                    
                    if not upd_conf.get('uploader_name'):
                        upd_conf['uploader_name'] = f'{name}_{vtype}_{upid}'
                    if not upd_conf.get('target'):
                        upd_conf['target'] = 'bilibili'
                    upd_configs[upid] = upd_conf
                
                self.config['replay'][name]['upload'][vtype] = upd_configs

        # 写入自动清理配置
        for name, rep_conf in self.config['replay'].items():
            if not rep_conf.get('clean'):
                continue

            clean_conf = rep_conf.get('clean').copy()
            if not ('dm_video' in list(clean_conf.keys()) or 'src_video' in list(clean_conf.keys())):
                conf_copy = clean_conf.copy()
                clean_conf.clear()
                for vtype in ['src_video', 'dm_video', 'dm_file']:
                    clean_conf[vtype] = conf_copy.copy()

            for vtype, clean_configs in clean_conf.items():
                if isinstance(clean_configs, dict):
                    if not clean_configs.get('method'):
                        clean_configs = None
                        continue
                    clean_configs = [clean_configs]
                for cid, conf in enumerate(clean_configs):
                    method = conf.get('method')
                    default_clean_config = self.config.get('cleaner')
                    clean_config = default_clean_config[method].copy()
                    clean_config.update(conf)
                    clean_configs[cid] = clean_config
                
                self.config['replay'][name]['clean'][vtype] = clean_configs

        # check 3rd party tools
        TOOLS = ['ffmpeg']
        if 'upload' in str(self.config['replay']):
            TOOLS.append('biliup')
        for k, v in self.default_conf.items():
            if isinstance(v, str):
                ToolsList.set(k, v)
        for tool in TOOLS:
            if not ToolsList.get(tool):
                eval(f"check_{tool}")()

        # check replay config
        for name, rep in self.config['replay'].items():
            plat, _ = split_url(rep['url'])
            # check platform
            if plat not in AVAILABLE_LIVE:
                raise ValueError(f'不支持的平台: {plat}.')
            if plat not in AVAILABLE_DANMU:
                warnings.warn(f'平台 {plat} 不支持录制弹幕，程序将只录制直播流.')
                rep['danmaku'] = False

            # check downloader output name validation
            output_name = rep['output_name']
            if replace_invalid_chars(output_name) != output_name:
                raise ValueError(f'自定义录制文件名称不合法: {output_name}')

        # check bilibili config
        for name, rep_conf in self.config['replay'].items():
            for vtype, upd_confs in rep_conf.get('upload', {}).items():
                for upd_conf in upd_confs:
                    if upd_conf['target'] == 'bilibili':
                        if upd_conf['title'] is None:
                            raise ValueError(
                                '上传参数 title 不能为空，请检查配置文件.')
                        elif upd_conf['desc'] is None:
                            raise ValueError(
                                '上传参数 desc 不能为空，请检查配置文件.')
                        elif upd_conf['tid'] is None:
                            raise ValueError(
                                '上传参数 tid 不能为空，请检查配置文件.')
                        elif upd_conf['tag'] is None:
                            raise ValueError(
                                '上传参数 tag 不能为空，请检查配置文件.')
                        elif upd_conf['dtime'] is None:
                            raise ValueError(
                                '上传参数 dtime 不能为空，请检查配置文件.')
                        elif int(upd_conf['dtime']) < 0 or int(upd_conf['dtime']) > 0 and int(upd_conf['dtime']) < 14400 or int(upd_conf['dtime']) > 1296000:
                            raise ValueError(
                                '上传参数 dtime 的值必须 ≥14400(4小时) 且 ≤1296000(15天), 请重新设置 dtime 参数.')

    @property
    def render_config(self) -> dict:
        return self.config.get('render')

    @property
    def uploader_config(self) -> dict:
        return self.config.get('uploader')

    @property
    def replay_config(self) -> dict:
        return self.config.get('replay')

    def get_replay_config(self, name) -> dict:
        return self.replay_config.get(name)


def new_config(config_path, config_type='replay'):
    src = f'DMR/Config/{config_type}_config.yml'
    shutil.copyfile(src, config_path)
