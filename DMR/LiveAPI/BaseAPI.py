
class BaseAPI():
    def is_available(self) -> bool:
        raise NotImplementedError

    def onair(self) -> bool:
        raise NotImplementedError
    
    def get_info(self) -> tuple:
        """
        return: title,uname,face_url,keyframe_url
        """
        raise NotImplementedError

    def get_stream_url(self, **kwargs) -> dict:
        """
        return dict{url,(header,...)}
        """
        raise NotImplementedError