import logging
import threading
import queue
from flask import Flask, request

from DMR.utils import *


class WebApi:
    def __init__(self,
                 pipe:Tuple[queue.Queue, queue.Queue],
                 **kwargs,
                 ) -> None:
        self.send_queue, self.recv_queue = pipe
        self.logger = logging.getLogger('DMR.Downloader')
        self.kwargs = kwargs
        self.stoped = True

        self.webapp = None
        self.webapp_thread = None

    def api_v1_func(self):
        req_data = request.get_json()
        message = PipeMessage(**req_data['data'])
        print(message)
        self.send_queue.put(message)
        return 'success', 200

    def start_helper(self):
        self.webapp = Flask(__name__)
        self.webapp.logger = self.logger
        self.webapp.add_url_rule('/api/put_message', view_func=self.api_v1_func, methods=['POST'])
        self.webapp.run('0.0.0.0', 5000, debug=True, use_reloader=False)

    def start(self):
        self.webapp_thread = threading.Thread(target=self.start_helper, daemon=True)
        self.webapp_thread.start()

    def stop(self):
        self.stoped = True
        func = request.environ.get('werkzeug.server.shutdown')
        if func is None:
            self.logger.debug('Not running with the Werkzeug Server')
        func()
