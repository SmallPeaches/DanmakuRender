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

#: 测试期间使用的分段时间（秒）。必须小于下方的运行时长（180 秒），
#: 否则一个分段都录不完。
DRYRUN_SEGMENT = 30

#: 做法是把各上传目标的 ``min_length`` 抬到测试分段永远达不到的高度：上传流程本身
#: 仍会完整走一遍（状态登记、上传组归属），但不会有视频被提交到真实账号。
#:
#: 为什么需要这道闸门：dryrun 用的是**你当前的配置文件**，其中的账号真实可用。
#: 早期版本把 ``min_length`` 设为 ``0``，于是测试片段被真实上传到了 B 站账号。
#: 若你确实要测试上传链路，把它改成 ``0`` 即可（请自行确认账号可接受测试稿件）。
DRYRUN_MIN_LENGTH = 0

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default='configs/global.yml',
                        help='全局配置；dryrun 会按它加载当前的全部任务配置')
    parser.add_argument('--debug', action='store_true')
    args = parser.parse_args()

    # 按当前配置启动：加载 --config 里 config_path 所指的**全部任务**，
    # 以便在真实配置下做冒烟验证（而不是另造一份测试配置）。
    config = Config(args.config)

    for name, rep_conf in config.replay_config.items():
        config.replay_config[name]['download_args']['segment'] = DRYRUN_SEGMENT
        for upd_type, upd_configs in rep_conf.get('upload_args', {}).items():
            for upid, upd_conf in enumerate(upd_configs):
                # 延迟发布：即使真的触发了上传，稿件也不会立即公开
                config.replay_config[name]['upload_args'][upd_type][upid]['dtime'] = 86400
                # 见 DRYRUN_MIN_LENGTH：阻止测试片段被真实上传
                config.replay_config[name]['upload_args'][upd_type][upid]['min_length'] = DRYRUN_MIN_LENGTH

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
    try:
        while 1:
            time.sleep(60)
    except KeyboardInterrupt:
        dmr.stop()
        exit(0)
