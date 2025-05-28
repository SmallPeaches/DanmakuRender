from datetime import datetime

class SimpleDanmaku():
    def __init__(self,
                 time:float=None,
                 timestamp:float=None,
                 dtype:str=None,
                 uname:str=None,
                 color:str='ffffff',
                 content:str=None,
                 text:str=None,
                 **kwargs,
                 ) -> None:
        # time 表示相对时间，单位为秒
        # timestamp 表示绝对时间，单位为秒
        self.time = time
        if isinstance(timestamp, datetime):
            self.timestamp = timestamp.timestamp()
        elif timestamp is None:
            self.timestamp = datetime.now().timestamp()
        else:
            self.timestamp = float(timestamp)

        self.dtype = dtype      # 弹幕类型，未知类型需要设置为 'other'
        self.uname = uname      # 发送者名称
        self.color = color      # 弹幕颜色，6位16进制颜色码
        self.content = content  # 弹幕内容，可能是纯文本或其他格式

        for key, value in kwargs.items():
            self.__dict__[key] = value

        # text属性表示最终显示的字符串
        self.text = text if text is not None else self.content

    def __getitem__(self, key):
        return self.__dict__[key]

    def __iter__(self):
        for key, value in self.__dict__.items():
            yield key, value


class GiftDanmaku(SimpleDanmaku):
    def __init__(
        self,
        text: str = None,
        price: float = None,
        gift_name: str = '',
        gift_count: int = 1,
        gift_price: float = 0.0,
        price_unit: str = '',
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.gift_name = gift_name
        self.gift_count = int(gift_count)
        self.gift_price = float(gift_price)
        self.price_unit = price_unit
        self.price = price if price is not None else self.gift_price * self.gift_count
        self.dtype = 'gift'

        self.text = text if text is not None else\
            f'{self.uname} 赠送给主播价值 {self.price} {self.price_unit} 的 {self.gift_count} 个 {self.gift_name}'


class SuperChatDanmaku(SimpleDanmaku):
    def __init__(
        self,
        price: float = 0.0,
        price_unit: str = '',
        duration: int = 0,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.price = price
        self.price_unit = price_unit
        self.duration = duration
        self.dtype = 'superchat'


class EntryDanmaku(SimpleDanmaku):
    def __init__(
        self,
        text:str=None,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.dtype = 'entry'

        self.text = text if text is not None else f'{self.uname} 进入直播间'
