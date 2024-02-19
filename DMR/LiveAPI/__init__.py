from ..utils import *
import logging

logger = logging.getLogger(__name__)


class LiveAPI():
    def __init__(self, platform, rid=None) -> None:
        if not rid:
            self.platform, self.rid = split_url(platform)
            self.raw_url = platform
        else:
            self.platform, self.rid = platform, rid
            self.raw_url = concat_rid(platform, rid)

        if self.platform in ['huya']:
            from .huya import huya
            self.api_class = huya(rid=self.rid)
        elif self.platform in ['douyu']:
            from .douyu import douyu
            self.api_class = douyu(rid=self.rid)
        elif self.platform in ['bilibili']:
            from .bilibili import bilibili
            self.api_class = bilibili(rid=self.rid)
        elif self.platform in ['douyin']:
            from .douyin import douyin
            self.api_class = douyin(rid=self.rid)
        elif self.platform in ['cc']:
            from .cc import cc
            self.api_class = cc(rid=self.rid)
        elif self.platform in ['twitch']:
            from .twitch import twitch
            self.api_class = twitch(rid=self.rid)
        else:
            logger.warning(f'平台 {self.platform, self.rid}: {self.raw_url} 可能不受支持，即将使用默认API.')
            from .defaultapi import defaultapi
            self.api_class = defaultapi(self.raw_url)
            # raise NotImplementedError(f'Platform {platform} is not supported.')

    def GetStreamerInfo(self) -> StreamerInfo:
        try:
            info = self.api_class.get_info()
            return StreamerInfo(
                name=info[1], 
                uid=None, 
                platform=self.platform, 
                room_id=self.rid, 
                url=concat_rid(self.platform, self.rid), 
                face_url=info[2], 
                cover_url=info[3],
            )
        except Exception as e:
            logger.debug(f'GetStreamerInfo {self.platform, self.rid} Error: {e}')

    def GetRoomInfo(self) -> dict:
        try:
            info = self.api_class.get_info()
            return {'title': info[0], 'name': info[1], 'face_url': info[2], 'cover_url': info[3]}
        except Exception as e:
            logger.debug(f'GetRoomInfo {self.platform, self.rid} Error: {e}')

    def GetStreamURL(self, **kwargs):
        try:
            return self.api_class.get_stream_url(**kwargs)
        except Exception as e:
            logger.debug(e)

    def GetStreamURLs(self, **kwargs):
        try:
            return self.api_class.get_stream_urls(**kwargs)
        except Exception as e:
            logger.debug(e)

    def Onair(self):
        try:
            return self.api_class.onair()
        except Exception as e:
            logger.debug(e)

    def IsAvailable(self):
        try:
            return self.api_class.is_available()
        except Exception as e:
            logger.debug(e)

    def GetStreamHeader(self) -> dict:
        try:
            return self.api_class.get_stream_header()
        except Exception as e:
            logger.debug(e)

    def __getattribute__(self, __name: str):
        try:
            return object.__getattribute__(self,__name)
        except AttributeError:
            return self.api_class.__getattribute__(__name)

def GetStreamerInfo(plat,rid=None) -> tuple:
    api = LiveAPI(plat,rid)
    try:
        return api.GetStreamerInfo()
    except:
        return None
    
def GetRoomInfo(plat,rid=None) -> dict:
    api = LiveAPI(plat,rid)
    try:
        return api.GetRoomInfo()
    except:
        return None
    
def GetStreamURLs(plat,rid=None,**kwargs) -> list:
    api = LiveAPI(plat,rid)
    try:
        return api.get_stream_urls(**kwargs)
    except:
        return None

def GetStreamURL(plat, rid=None, **kwargs) -> dict:
    api = LiveAPI(plat,rid)
    try:
        return api.get_stream_url(**kwargs)
    except:
        return None

def Onair(plat, rid=None) -> bool:
    api = LiveAPI(plat,rid)
    try:
        return api.onair()
    except:
        return None

def UrlAvailable(plat,rid=None) -> bool:
    api = LiveAPI(plat,rid)
    try:
        return api.is_available()
    except:
        return None
