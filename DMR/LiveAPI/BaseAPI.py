from abc import ABC,abstractmethod

class BaseAPI():
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
    
    @abstractmethod
    def get_stream_url(self, **kwargs) -> dict:
        """
        return dict{url,(header,...)}
        """
        pass