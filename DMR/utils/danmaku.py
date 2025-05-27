
class SimpleDanmaku():
    def __init__(self,
                 time:float=-1,
                 dtype:str=None,
                 uname:str=None,
                 color:str='ffffff',
                 content:str=None
                 ) -> None:
        self.time = time
        self.dtype = dtype
        self.uname = uname
        self.color = color
        self.content = content

    def __getitem__(self, key):
        return self.__dict__[key]

    def __iter__(self):
        for key, value in self.__dict__.items():
            yield key, value
