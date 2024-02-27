import queue
import logging
import threading

from .Cleaner import Cleaner
from .Downloader import Downloader
from .Render import Render
from .Uploader import Uploader
from .Task import ReplayTask
from .utils import *


class DMREngine():
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.task_dict = {}
        self.plugin_dict = {}
        self.recv_queue = None
        self.stoped = True
        
    def pipeSend(self, message:PipeMessage):
        target = message.target
        self.logger.debug(message)
        if target == 'engine':
            self.recv_queue.put(message)
        elif target.startswith('replay/'):
            taskname = target.split('/')[1]
            if taskname not in self.task_dict:
                self.logger.error(f'Task {taskname} not exists.')
                return
            self.task_dict[taskname]['send_queue'].put(message)
        elif target == 'render':
            self.plugin_dict['render']['send_queue'].put(message)
        elif target == 'uploader':
            self.plugin_dict['uploader']['send_queue'].put(message)
        elif target == 'cleaner':
            self.plugin_dict['cleaner']['send_queue'].put(message)
        elif target == 'downloader':
            self.plugin_dict['downloader']['send_queue'].put(message)
        else:
            # raise Exception(f'Unknown target {target}.')
            self.logger.error(f'Unknown target {target}.')

    def _pipeRecvMonitor(self):
        while not self.stoped:
            message:PipeMessage = self.recv_queue.get()
            try:
                if message.target == 'engine':
                    if message.event == 'info':
                        self.logger.info(message.msg)
                else:
                    self.pipeSend(message)
            except Exception as e:
                self.logger.error(f'Message:{message} raise an error.')
                self.logger.exception(e)
    
    def start(self):
        self.stoped = False
        self.recv_queue = queue.Queue()
        self._piperecvprocess = threading.Thread(target=self._pipeRecvMonitor, daemon=True)
        self._piperecvprocess.start()
        self.logger.debug('DMR engine started.')

        for name, plugin in self.plugin_dict.values():
            if plugin['status'] == 0:
                plugin['class'].start()
                self.plugin_dict['name']['status'] = 1
                self.logger.debug(f'Plugin {name} started.')
        
        for name, task in self.task_dict.values():
            if task['status'] == 0:
                task['class'].start()
                self.task_dict['name']['status'] = 1
                self.pipeSend(PipeMessage('engine', f'replay/{name}', 'ready'))
                self.logger.debug(f'Task {name} started.')

    def add_plugin(self, name, config):
        send_queue = queue.Queue()
        if name == 'render':
            plugin = Render((self.recv_queue, send_queue), **config)
        elif name == 'uploader':
            plugin = Uploader((self.recv_queue, send_queue), **config)
        elif name == 'cleaner':
            plugin = Cleaner((self.recv_queue, send_queue), **config)
        elif name == 'downloader':
            plugin = Downloader((self.recv_queue, send_queue), **config)
        else:
            self.logger.error(f'Unknown plugin {name}.')
            # raise Exception(f'Unknown plugin {name}.')
        if self.stoped == False:
            plugin.start()
            self.logger.debug(f'Plugin {name} started.')
        else:
            self.logger.debug(f'Plugin {name} created.')
        self.plugin_dict[name] = {
            'class': plugin,
            'config': config,
            'send_queue': send_queue,
            'status': 0 if self.stoped else 1,
        }

    def add_task(self, taskname, config):
        send_queue = queue.Queue()
        task = ReplayTask(taskname, config, (self.recv_queue, send_queue))
        self.task_dict[taskname] = {
            'class': task,
            'config': config,
            'send_queue': send_queue,
            'status': 0 if self.stoped else 1,
        }
        if self.stoped == False:
            task.start()
            self.pipeSend(PipeMessage('engine', f'replay/{taskname}', 'ready'))
            self.logger.debug(f'Task {taskname} started.')
        else:
            self.logger.debug(f'Task {taskname} created.')

    def del_task(self, taskname):
        if taskname in self.task_dict:
            self.pipeSend(PipeMessage('engine', f'replay/{taskname}', 'exit'))
            # self.task_dict[taskname]['class'].stop()
            del self.task_dict[taskname]
            self.logger.debug(f'Task {taskname} deleted.')
        else:
            self.logger.debug(f'Task {taskname} not exists.')

    def stop(self):
        self.stoped = True
        for taskname in list(self.task_dict.keys()):
            self.del_task(taskname)
        for name in self.plugin_dict.keys():
            try:
                self.plugin_dict[name]['class'].stop()
            except Exception as e:
                self.logger.exception(e)
        self.task_dict.clear()
        self.plugin_dict.clear()
        self.recv_queue.put(PipeMessage('engine', 'engine', 'exit'))
        self.logger.info('DMR engine stoped.')
