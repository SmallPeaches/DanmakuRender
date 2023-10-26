from .utils import *
import logging

AVAILABLE_DANMU = ['huya','douyu','bilibili','douyin','cc']
AVAILABLE_LIVE = ['huya','douyu','bilibili','douyin','cc']

class LiveAPI():
    def __init__(self,platform,rid) -> None:
        self.platform = platform
        self.rid = rid

        if platform in ['huya']:
            from .huya import huya
            self.api_class = huya(rid=self.rid)
        elif platform in ['douyu']:
            from .douyu import douyu
            self.api_class = douyu(rid=self.rid)
        elif platform in ['bilibili']:
            from .bilibili import bilibili
            self.api_class = bilibili(rid=self.rid)
        elif platform in ['douyin']:
            from .douyin import douyin
            self.api_class = douyin(rid=self.rid)
        elif platform in ['cc']:
            from .cc import cc
            self.api_class = cc(rid=self.rid)
        else:
            raise NotImplementedError

    def GetStreamerInfo(self):
        try:
            return self.api_class.get_info()
        except Exception as e:
            logging.debug(e)

    def GetStreamURL(self, **kwargs):
        try:
            return self.api_class.get_stream_url(**kwargs)
        except Exception as e:
            logging.debug(e)

    def Onair(self):
        try:
            return self.api_class.onair()
        except Exception as e:
            logging.debug(e)

    def IsAvailable(self):
        try:
            return self.api_class.is_available()
        except Exception as e:
            logging.debug(e)

    def GetStreamHeader(self) -> dict:
        try:
            return self.api_class.get_stream_header()
        except Exception as e:
            logging.debug(e)

    def IsStable(self) -> bool:
        try:
            return self.api_class.is_stable()
        except Exception as e:
            logging.debug(e)

    def __getattribute__(self, __name: str):
        try:
            return object.__getattribute__(self,__name)
        except AttributeError:
            return self.api_class.__getattribute__(__name)

def GetStreamerInfo(plat,rid=None) -> tuple:
    if rid is None:
        plat,rid = split_url(plat)
    api = LiveAPI(plat,rid)
    try:
        return api.get_info()
    except:
        return None

def GetStreamURL(plat,rid=None,**kwargs) -> dict:
    if rid is None:
        plat,rid = split_url(plat)
    api = LiveAPI(plat,rid)
    try:
        return api.get_stream_url(**kwargs)
    except:
        return None

def Onair(plat,rid=None) -> bool:
    if rid is None:
        plat,rid = split_url(plat)
    api = LiveAPI(plat,rid)
    try:
        return api.onair()
    except:
        return None

def UrlAvailable(plat,rid=None) -> bool:
    if rid is None:
        plat,rid = split_url(plat)
    api = LiveAPI(plat,rid)
    try:
        return api.is_available()
    except:
        return None
