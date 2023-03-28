from abc import ABC, abstractmethod

class BaseRender(ABC):
    @abstractmethod
    def __init__(self, debug, **kwargs):
        pass
    
    @abstractmethod
    def render_one(self, video:str, danmaku:str, output:str, **kwargs):
        pass

    @abstractmethod
    def stop(self):
        pass