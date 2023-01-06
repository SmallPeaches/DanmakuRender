
class PipeMessage(dict):
    def __init__(self, src, msg, type='info', **kwargs):
        self['src'] = src
        self['msg'] = msg
        self['type'] = type
        for k,v in kwargs.items():
            self[k] = v