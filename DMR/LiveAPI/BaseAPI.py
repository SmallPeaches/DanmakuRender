from abc import ABC, abstractmethod
import random

class BaseAPI(ABC):
    _default_header = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'User-Agent': 'Mozilla/5.0 (Linux; Android 5.0; SM-G900P Build/LRX21T) AppleWebKit/537.36 '
                            '(KHTML, like Gecko) Chrome/75.0.3770.100 Mobile Safari/537.36 '
        }
    
    @abstractmethod
    def is_available(self) -> bool:
        pass

    @abstractmethod
    def onair(self) -> bool:
        pass
    
    @abstractmethod
    def get_info(self) -> tuple:
        """
        return: title,uname,face_url,keyframe_url
        """
        pass
    
    def get_stream_url(self, **kwargs) -> str:
        return random.choice(self.get_stream_urls(**kwargs))['stream_url']

    @abstractmethod
    def get_stream_urls(self, **kwargs) -> list:
        pass

    def get_stream_header(self) -> dict:
        """
        return: HTTP header of stream url
        """
        return self._default_header
    
