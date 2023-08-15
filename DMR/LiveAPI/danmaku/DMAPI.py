
class DMAPI():
    """
    使用标准DMC接口实现弹幕录制
    必须实现两个类方法和填写heatbeat字段
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36 Edg/115.0.1901.203',
    }
    interval = 30
    
    @property
    def heatbeat(self):
        raise NotImplementedError()

    async def get_ws_info(url):
        raise NotImplementedError()
    
    def decode_msg(data):
        raise NotImplementedError()