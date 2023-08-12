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

from main import load_config, VERSION
from DMR.message import PipeMessage
from DMR import DanmakuRender
from DMR.Render import Render
from DMR.Config import Config, new_config

import requests.packages.urllib3.util.ssl_
requests.packages.urllib3.util.ssl_.DEFAULT_CIPHERS = 'ALL'

if __name__ == '__main__':    
    parser = argparse.ArgumentParser()
    parser.add_argument('-c','--config',default='replay.yml')
    parser.add_argument('--default_config',default='configs/default.yml')
    parser.add_argument('--debug',action='store_true')
    args = parser.parse_args()
    
    config = load_config(args.default_config, args.config)
    
    for name , rep_conf in config.config['replay'].items():
        config.config['replay'][name]['segment'] = 60
        for upd_type, upd_configs in rep_conf.get('upload', {}).items():
            for upid, upd_conf in enumerate(upd_configs):
                config.config['replay'][name]['upload'][upd_type][upid]['dtime'] = 86400
                config.config['replay'][name]['upload'][upd_type][upid]['min_length'] = 0
    
    logging.getLogger().setLevel(logging.DEBUG)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO) 
    console_handler.setFormatter(logging.Formatter("[%(asctime)s][%(levelname)s]: %(message)s"))
    
    os.makedirs('logs', exist_ok=True)
    log_file = f'logs/DMR-dryrun-{datetime.now().strftime("%Y%m%d")}.log'
    num = 1
    while os.path.exists(log_file):
        log_file = f'logs/DMR-dryrun-{datetime.now().strftime("%Y%m%d")}-{num}.log'
        num += 1
    file_handler = logging.handlers.TimedRotatingFileHandler(log_file, when='D', interval=1, backupCount=0, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter("[%(asctime)s][%(module)s][%(levelname)s]: %(message)s"))
    
    logging.getLogger().addHandler(console_handler)
    logging.getLogger().addHandler(file_handler)

    logging.debug(f'VERSION: 4-{VERSION}')
    logging.debug(f'args: {args}')
    logging.debug(f'Full config: {config.config}')

    dmr = DanmakuRender(config, args.debug)

    logging.info('正在启动测试')
    dmr.start()

    time.sleep(180)
    for taskname, task in dmr.downloaders.items():
        try:
            task['class'].stop()
            dmr.signal_queue.put(PipeMessage('downloader',msg='end',type='info',group=taskname))
        except Exception as e:
            logging.exception(e)
    
    logging.info('录制完成，请检查录制文件')
    while 1:
        time.sleep(60)




    
            