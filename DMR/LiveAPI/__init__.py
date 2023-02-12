from .utils import *

AVAILABLE_DANMU = ['huya','douyu','bilibili']
AVAILABLE_LIVE = ['huya','douyu','bilibili','douyin']

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
        else:
            raise NotImplementedError

    def __getattribute__(self, __name: str):
        try:
            return object.__getattribute__(self,__name)
        except AttributeError:
            return self.api_class.__getattribute__(__name)

def GetStreamerInfo(plat,rid=None) -> tuple:
    if rid is None:
        plat,rid = split_url(plat)
    api = LiveAPI(plat,rid)
    return api.get_info()

def GetStreamURL(plat,rid=None,flow_cdn=None) -> dict:
    if rid is None:
        plat,rid = split_url(plat)
    api = LiveAPI(plat,rid)
    return api.get_stream_url(flow_cdn=flow_cdn)

def Onair(plat,rid=None) -> bool:
    if rid is None:
        plat,rid = split_url(plat)
    api = LiveAPI(plat,rid)
    return api.onair()

def UrlAvailable(plat,rid=None) -> bool:
    if rid is None:
        plat,rid = split_url(plat)
    api = LiveAPI(plat,rid)
    return api.is_available()
