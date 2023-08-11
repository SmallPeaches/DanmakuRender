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
from os.path import exists

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.append('./tools')

VERSION = '2023.8.11'
VERSION_FULLNAME = 'DanmakuRender-4 2023.8.11.'
VERSION_DEBUG = '4-2023.8.11'

from DMR import DanmakuRender
from DMR.Render import Render
from DMR.Config import Config, new_config

import requests.packages.urllib3.util.ssl_
requests.packages.urllib3.util.ssl_.DEFAULT_CIPHERS = 'ALL'

if __name__ == '__main__':    
    parser = argparse.ArgumentParser()
    parser.add_argument('-c','--config',default='replay.yml')
    parser.add_argument('--default_config',default='default.yml')
    parser.add_argument('--debug',action='store_true')
    parser.add_argument('--render_only',action='store_true')
    parser.add_argument('--input_dir',type=str)
    parser.add_argument('--version',action='store_true')
    parser.add_argument('--skip_update',action='store_true')
    args = parser.parse_args()

    if args.version:
        print(f'DanmakuRender-4 {VERSION}.')
        print('https://github.com/SmallPeaches/DanmakuRender')
        exit(0)
    
    if not args.skip_update:
        check_update(VERSION)
    
    if not exists(args.default_config):
        print(f'未检测到配置文件：{args.default_config}, 即将自动创建.')
        new_config(args.default_config, 'default')
    if not exists(args.config):
        print(f'未检测到配置文件：{args.config}, 即将自动创建.')
        new_config(args.config, 'replay')

    with open(args.default_config,'r',encoding='utf-8') as f:
        default_config = yaml.safe_load(f)
    with open(args.config,'r',encoding='utf-8') as f:
        replay_config = yaml.safe_load(f)

    config = Config(default_config, replay_config)
    
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
    file_handler = logging.handlers.TimedRotatingFileHandler(log_file, when='D', interval=1, backupCount=0, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter("[%(asctime)s][%(module)s][%(levelname)s]: %(message)s"))
    
    logging.getLogger().addHandler(console_handler)
    logging.getLogger().addHandler(file_handler)

    logging.debug(f'DEBUG VERSION: {VERSION_DEBUG}')
    logging.debug(f'args: {args}')
    logging.debug(f'Full config: {config.config}')
    dmr = DanmakuRender(config, args.debug)

    if args.render_only:
        logging.warn('此功能已不受支持，请运行 render_only.py 进行渲染.')
        exit(0)
    
    dmr.start()
    
    try:
        while 1:
            time.sleep(60)
    except KeyboardInterrupt:
        dmr.stop()
            
    


    
