import queue
import logging
import threading

from .Cleaner import Cleaner
from .Downloader import Downloader
from .Render import Render
from .Uploader import Uploader
from .Task import ReplayTask
from .WebService import WebService
from .utils import *


class DMREngine():
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.task_dict = {}
        self.plugin_dict = {}
        self.recv_queue = None
        self.stoped = True
        
    def _resolve_target(self, target:str) -> tuple[str, str]:
        """把消息的 ``target`` 解析为 ``(类型, 名称)``。

        类型为 ``'task'`` / ``'plugin'`` / ``'engine'`` / ``'unknown'``。

        为什么需要归一化：``target`` 有两种写法在做同一件事 —— 插件名（``uploader``）
        和任务名（``replay/<taskname>`` 或裸 ``<taskname>``）。上传器回包时会**把消息
        来源原样当作 target**（``Uploader/__init__.py`` 的 ``target=task['source']``），
        而来源是否带 ``replay/`` 前缀曾取决于 liveevents 怎么填 —— 一旦没带，消息就会
        落进 ``else`` 分支被**静默丢弃**：上传明明成功，``onUploadEnd`` 却从不执行，
        产物状态永远停在 ``uploading``/``recorded``，清理也不再触发。

        因此这里**不再依赖前缀约定**：只要 target 是已知任务名就直接投递，前缀有或
        没有都能工作。前缀仅作为兼容形式保留。
        """
        if target == 'engine':
            return 'engine', target

        # 兼容 ``replay/<taskname>``：任务名本身可能含 ``/``，所以按前缀剥离而不是
        # 取 ``split('/')[1]``（后者会把带斜杠的任务名截断）。
        if target.startswith('replay/'):
            candidate = target[len('replay/'):]
            if candidate in self.task_dict:
                return 'task', candidate
            # 前缀存在但任务不在（例如刚被删除）：仍当作任务名上报，便于定位
            return 'task', candidate

        # 插件名是**保留标识**，优先于同名任务：否则一个叫 "uploader" 的任务会把
        # 发往上传器的消息截走（原有实现是插件名硬编码匹配，没有这个问题）。
        if target in self.plugin_dict:
            return 'plugin', target

        # 裸任务名：这是本次修复的主路径（无前缀即可匹配）
        if target in self.task_dict:
            return 'task', target

        return 'unknown', target

    def pipeSend(self, message:PipeMessage):
        kind, name = self._resolve_target(message.target)
        self.logger.debug(message)
        if kind == 'engine':
            self.recv_queue.put(message)
        elif kind == 'task':
            if name not in self.task_dict:
                # 带上前缀/来源/事件，便于定位"谁发出的、本该去哪"
                self.logger.warning(
                    f'目标任务 {name!r} 不存在（source={message.source!r}, '
                    f'event={message.event!r}），消息已丢弃。')
                return
            self.task_dict[name]['send_queue'].put(message)
        elif kind == 'plugin':
            self.plugin_dict[name]['send_queue'].put(message)
        else:
            self.logger.error(
                f'Unknown target {message.target!r}（source={message.source!r}, '
                f'event={message.event!r}），消息已丢弃。')

    def _pipeRecvMonitor(self):
        while not self.stoped:
            message:PipeMessage = self.recv_queue.get()
            try:
                if message.target == 'engine':
                    if message.event == 'info':
                        self.logger.info(message.msg)
                    elif message.event == 'addtask':
                        self.add_task(message.data['taskname'], message.data['config'])
                    elif message.event == 'deltask':
                        self.del_task(message.data)
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
        elif name == 'webservice':
            plugin = WebService((self.recv_queue, send_queue), engine=self, **config)
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
        # 未 start() 过时 recv_queue 为 None：此时没有接收线程需要唤醒，
        # 但是仍然要允许 stop() 被安全调用（例如 start() 中途失败后的清理）。
        if self.recv_queue is not None:
            self.recv_queue.put(PipeMessage('engine', 'engine', 'exit'))
        self.logger.info('DMR engine stoped.')
