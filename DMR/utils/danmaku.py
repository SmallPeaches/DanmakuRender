
class SimpleDanmaku():
    def __init__(self,
                 time:float=-1,
                 dtype:str=None,
                 uname:str=None,
                 color:str='ffffff',
                 content:str=None,
                 price: float = 0  # 新增 price 字段
                 ) -> None:
        self.time = time
        self.dtype = dtype
        self.uname = uname
        self.color = color
        self.content = content
        self.price = price  # 将 price 存储在 SimpleDanmaku 对象中

    def __getitem__(self, key):
        return self.__dict__[key]

    def __iter__(self):
        for key, value in self.__dict__.items():
            yield key, value
