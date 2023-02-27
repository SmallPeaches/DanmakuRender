import logging
import threading
import queue
import importlib
import warnings

from DMR.message import PipeMessage
from DMR.utils import FFprobe

class Uploader():
    def __init__(self, name, pipe, uploader_config, debug=False):
        self.uploader_config = uploader_config
        self.debug = debug
        self.name = name
        self.sender = pipe
        self.uploading = False

        pkg = importlib.import_module(f"DMR.Uploader.{uploader_config['engine']}")
        self.uploader = getattr(pkg,uploader_config['engine'])(debug=self.debug, name=name, **uploader_config)
        self.wait_queue = queue.Queue()
        self.video_buffer = {}

    def pipeSend(self,msg,type='info',**kwargs):
        if self.sender:
            self.sender.put(PipeMessage('upload',msg=msg,type=type,**kwargs))
        else:
            print(PipeMessage('upload',msg=msg,type=type,**kwargs))

    def upload_queue(self):
        while not self.stoped:
            task = self.wait_queue.get()
            self.uploading = True
            logging.info(f'正在上传: {task[0]["group"]}')
            logging.debug(f'uploading: {task}')
            try:
                status = self.uploader.upload_batch(task)
                if status == True:
                    self.pipeSend(task[0]['group'], status)
            except KeyboardInterrupt:
                self.stop()
            except Exception as e:
                logging.exception(e)
                self.pipeSend(task[0]['group'],'error',desc=e)
            self.uploading = False

    def check_uploader_config(uploader_config):
        # check bilibili config
        if list(uploader_config)[0] == 'bilibili':
            config_dict = uploader_config['bilibili']
            if config_dict['title'] is None:
                return '上传参数 title 不能为空，请检查 default.yml 中 uploader 的 title 参数.'
            elif config_dict['desc'] is None:
                return '上传参数 desc 不能为空，请检查 default.yml 中 uploader 的 desc 参数.'
            elif config_dict['tid'] is None:
                return '上传参数 tid 不能为空，请检查 default.yml 中 uploader 的 tid 参数.'
            elif config_dict['tag'] is None:
                return '上传参数 tag 不能为空，请检查 default.yml 中 uploader 的 tag 参数.'
            elif config_dict['dtime'] is None:
                return '上传参数 dtime 不能为空，请检查 default.yml 中 uploader 的 dtime 参数.'
            elif int(config_dict['dtime']) < 0 or int(config_dict['dtime']) > 0 and int(config_dict['dtime']) < 14400 or int(config_dict['dtime']) > 1296000:
                return '上传参数 dtime 的值必须 ≥14400(4小时) 且 ≤1296000(15天), 请重新设置 dtime 参数.'
            
        return 'ok'

    def start(self):
        self.stoped = False
        thread = threading.Thread(target=self.upload_queue,daemon=True)
        thread.start()
        return thread

    def add(self, video, group=None, video_info=None, **kwargs):
        if video == 'end':
            task = self.video_buffer.pop(group,0)
            if task:
                self.wait_queue.put(task)
            if self.uploading:
                logging.warn('视频上传速度慢于录制速度，可能导致队列阻塞.')
        else:
            if not self.video_buffer.get(group):
                self.video_buffer[group] = []

            min_length = kwargs.get('min_length')
            if FFprobe.get_duration(video) > min_length:
                task = {
                    'video': video,
                    'group': group,
                    'video_info': video_info,
                    'kwargs': kwargs
                }
                self.video_buffer[group].append(task)

    def stop(self):
        self.stoped = True
        if self.uploading:
            warnings.warn('上传被终止，可能导致部分文件未能上传完成.')
        try:
            self.uploader.stop()
        except Exception as e:
            logging.debug(e)
