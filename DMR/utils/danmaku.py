
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

    def todict(self):
        return {
            'time': self.time,
            'dtype': self.dtype,
            'uname': self.uname,
            'color': self.color,
            'content': self.content
        }