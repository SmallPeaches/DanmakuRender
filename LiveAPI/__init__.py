

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
