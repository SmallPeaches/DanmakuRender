import queue
import logging
import threading

from typing import Tuple
from .liveevents import LiveEvents
from ..utils import *


class ReplayTask():
    def __init__(self, taskname, config:dict, pipe:Tuple[queue.Queue, queue.Queue]):
        self.send_queue, self.recv_queue = pipe
        self.taskname = taskname
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.event_class = LiveEvents(self.taskname, self.config)
        self._event_dict = {}
        self.stoped = True

    def add_event(self, event, trigger):
        if self._event_dict.get(event) != None:
            self._event_dict[event].append(trigger)
        self._event_dict[event] = [trigger]

    def _pipeSend(self, msg:PipeMessage):
        if not msg.source.startswith('replay/'):
            msg.source = 'replay/' + msg.source
        self.send_queue.put(msg)

    def _pipeRecvMonitor(self):
        while self.stoped == False:
            msg:PipeMessage = self.recv_queue.get()
            try:
                if msg.target.startswith('replay/') and msg.target.split('/')[1] == self.taskname:
                    event = msg.source +'/'+ msg.event
                    funcs = self._event_dict.get(event) or self._event_dict.get(msg.event)
                    if isinstance(funcs, list):
                        for func in funcs:
                            ret_msgs = func(msg)
                            if not ret_msgs:
                                continue
                            elif isinstance(ret_msgs, list):
                                for return_msg in ret_msgs:
                                    self._pipeSend(return_msg)
                            elif isinstance(ret_msgs, PipeMessage):
                                self._pipeSend(ret_msgs)
                            else:
                                self.logger.error(f'Event:{event} return an unknown type of message.')
                    else:
                        if self._event_dict.get('default') is None:
                            self.logger.info(f'Event:{event} is not registered at task:{self.taskname}.')
                        else:
                            for func in self._event_dict['default']:
                                ret_msgs = func(msg)
                                if not ret_msgs:
                                    continue
                                elif isinstance(ret_msgs, list):
                                    for return_msg in ret_msgs:
                                        self._pipeSend(return_msg)
                                elif isinstance(ret_msgs, PipeMessage):
                                    self._pipeSend(ret_msgs)
                                else:
                                    self.logger.error(f'Event:{event} return an unknown type of message.')
                    
                    if msg.event == 'exit':
                        self.logger.debug(f'Task:{self.taskname} recieved exit message.')
                        self.stop()
                        break
            except Exception as e:
                self.logger.error(f'Message:{msg} raise an error: {e}')
                self.logger.exception(e)

    def start(self):
        self.stoped = False
        self._piperecvprocess = threading.Thread(target=self._pipeRecvMonitor, daemon=True)
        self._piperecvprocess.start()

        for event, trigger in self.event_class.event_dict.items():
            if isinstance(trigger, (list, tuple, set)):
                for func in trigger:
                    self.add_event(event, func)
            self.add_event(event, trigger)

    def stop(self):
        self.stoped = True
        self._event_dict.clear()