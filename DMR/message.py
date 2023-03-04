import logging

class PipeMessage(dict):
    def __init__(self, src, msg, type='info', group=None, **kwargs):
        self['src'] = src
        self['msg'] = msg
        self['type'] = type
        self['group'] = group
        for k,v in kwargs.items():
            self[k] = v

        logging.debug(f'PIPE MESSAGE: {self}')