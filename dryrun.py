from tools import check_pypi
check_pypi()

import time
import argparse
from datetime import datetime
import os
import sys
import logging
import logging.handlers
from os.path import exists, splitext
from glob import glob

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.append('./tools')

from DMR.utils import *
from DMR import DanmakuRender
from DMR.Config import Config

if __name__ == '__main__':    
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default='configs')
    parser.add_argument('--global_config',default='configs/global.yml')
    parser.add_argument('--debug', action='store_true')
    args = parser.parse_args()
    
    config = Config(args.global_config, args.config)
    
    for name, rep_conf in config.replay_config.items():
        config.replay_config[name]['download_args']['segment'] = 30
        for upd_type, upd_configs in rep_conf.get('upload_args', {}).items():
            for upid, upd_conf in enumerate(upd_configs):
                config.replay_config[name]['upload_args'][upd_type][upid]['dtime'] = 86400
                config.replay_config[name]['upload_args'][upd_type][upid]['min_length'] = 0
    
    logger = logging.getLogger('DMR')
    logger.setLevel(logging.DEBUG)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO) 
    console_handler.setFormatter(logging.Formatter("[%(asctime)s][%(levelname)s]: %(message)s"))
    
    os.makedirs('logs', exist_ok=True)
    log_file = f'logs/DMR-dryrun-{datetime.now().strftime("%Y%m%d")}.log'
    if exists(log_file):
        _cnt = len(glob(splitext(log_file)[0] + '*'))
        log_file = splitext(log_file)[0] + f'({_cnt})' + splitext(log_file)[1]
    file_handler = logging.handlers.TimedRotatingFileHandler(log_file, when='D', interval=1, backupCount=0, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter("[%(asctime)s][%(module)s][%(levelname)s]: %(message)s"))
    
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    dmr = DanmakuRender(config, debug=args.debug)

    logger.info('正在启动测试...')
    dmr.start()

    time.sleep(180)
    for taskname, task in dmr.engine.task_dict.items():
        msg = PipeMessage(
            source='dryrun',
            target='downloader',
            event='stoptask',
            dtype='str',
            data=taskname,
        )
        dmr.engine.pipeSend(msg)
    
    # logging.info('录制完成，请检查录制文件')
    while 1:
        time.sleep(60)




    
            