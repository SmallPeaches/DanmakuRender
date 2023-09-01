import json
from tools.check_env import check_pypi, check_update
check_pypi()

import time
import argparse
from datetime import datetime
import os
import sys
import logging
import logging.handlers
import yaml
from glob import glob
from os.path import exists, split

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.append('./tools')

VERSION = '2023.9.1'
VERSION_DEBUG = '4-2023.9.1'

from DMR import DanmakuRender
from DMR.Render import Render
from DMR.Config import Config, new_config

import requests.packages.urllib3.util.ssl_
requests.packages.urllib3.util.ssl_.DEFAULT_CIPHERS = 'ALL'

def load_config(default_config, replay_config, config_dir='configs'):
    try:
        if not exists(default_config):
            print(f'未检测到配置文件：{default_config}, 即将自动创建.')
            new_config(default_config, 'default')
        if not exists(replay_config):
            print(f'未检测到配置文件：{replay_config}, 即将自动创建.')
            new_config(replay_config, 'replay')

        with open(default_config,'r',encoding='utf-8') as f:
            default_config = yaml.safe_load(f)
        with open(replay_config,'r',encoding='utf-8') as f:
            replay_config = yaml.safe_load(f)

        if not replay_config.get('replay'):
            replay_config['replay'] = {}
            config_paths = sorted(glob(f'{config_dir}/replay-**.yml'))
            print(f'即将添加以下配置文件：{config_paths}')
            for path in config_paths:
                taskname = split(path)[1][7:-4]
                with open(path,'r',encoding='utf-8') as f:
                    config = yaml.safe_load(f)
                replay_config['replay'][taskname] = config
        
        config = Config(default_config, replay_config)
    except Exception as e:
        print(f'配置文件读取错误: {e}')
        input('')
        exit(1)
    
    return config

if __name__ == '__main__':    
    parser = argparse.ArgumentParser()
    parser.add_argument('-c','--config',default='replay.yml')
    parser.add_argument('--default_config',default='configs/default.yml')
    parser.add_argument('--debug',action='store_true')
    parser.add_argument('--version',action='store_true')
    parser.add_argument('--skip_update',action='store_true')
    args = parser.parse_args()

    if args.version:
        print(f'DanmakuRender-4 {VERSION}.')
        print('https://github.com/SmallPeaches/DanmakuRender')
        exit(0)
    
    if not args.skip_update:
        check_update(VERSION)
    
    config = load_config(args.default_config, args.config)
    
    logging.getLogger().setLevel(logging.DEBUG)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO) 
    console_handler.setFormatter(logging.Formatter("[%(asctime)s][%(levelname)s]: %(message)s"))
    
    os.makedirs('logs', exist_ok=True)
    log_file = f'logs/DMR-{datetime.now().strftime("%Y%m%d")}.log'
    num = 1
    while os.path.exists(log_file):
        log_file = f'logs/DMR-{datetime.now().strftime("%Y%m%d")}-{num}.log'
        num += 1
    file_handler = logging.handlers.TimedRotatingFileHandler(log_file, when='D', interval=1, backupCount=7, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter("[%(asctime)s][%(module)s][%(levelname)s]: %(message)s"))
    
    logging.getLogger().addHandler(console_handler)
    logging.getLogger().addHandler(file_handler)

    logging.debug(f'DEBUG VERSION: {VERSION_DEBUG}')
    logging.debug(f'args: {args}')
    logging.debug(f'Full config: {json.dumps(config.replay_config, indent=4, ensure_ascii=False)}')
    dmr = DanmakuRender(config, args.debug)
    dmr.start()
    
    try:
        while 1:
            time.sleep(60)
    except KeyboardInterrupt:
        dmr.stop()
            
    


    
