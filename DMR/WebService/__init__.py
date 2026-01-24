import logging
import os
import queue

from DMR.utils import *


class WebService:
    def __init__(self,
                 pipe:Tuple[queue.Queue, queue.Queue],
                 web_api=True,
                 engine=None,
                 **kwargs,
                 ) -> None:
        
        self.send_queue, self.recv_queue = pipe
        self.web_api = web_api
        self.engine = engine
        self.kwargs = kwargs

        self.logger = logging.getLogger(__name__)

    def start(self):
        if self.web_api:
            from .webapi import WebApi
            self.web_api = WebApi((self.send_queue, self.recv_queue), engine=self.engine, **self.kwargs)
            self.web_api.start()
    
    def stop(self):
        return
        if self.web_api:
            self.web_api.stop()
