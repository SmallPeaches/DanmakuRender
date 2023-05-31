import requests

try:
    from .BaseAPI import BaseAPI
except ImportError:
    from BaseAPI import BaseAPI


class cc(BaseAPI):
    def __init__(self, rid):
        self.rid = rid

    def _get_info(self):
        room_url = f'https://api.cc.163.com/v1/activitylives/anchor/lives?anchor_ccid={self.rid}'
        response = requests.get(url=room_url).json()
        data = response.get('data', 0)
        if data:
            channel_id = data.get(f'{self.rid}').get('channel_id', 0)
            if channel_id:
                response = requests.get(f'https://cc.163.com/live/channel/?channelids={channel_id}').json()
                info = response.get('data')[0]
            else:
                raise Exception('直播间不存在')
        else:
            raise Exception('输入错误')
        return info

    def is_available(self) -> bool:
        return True

    def onair(self) -> bool:
        return True

    def get_info(self) -> tuple:
        info = self._get_info()
        title = info['title']
        uname = info['nickname']
        face_url = info['nickname']
        keyframe_url = info['nickname']
        return title, uname, face_url, keyframe_url

    def _find_max_vbr(self, resolution_data):
        max_vbr = float('-inf')  # 初始化最大 vbr 值为负无穷大
        max_vbr_item = None  # 初始化最大 vbr 的项为 None

        for resolution, data in resolution_data.items():
            if 'vbr' in data and data['vbr'] > max_vbr:
                max_vbr = data['vbr']
                max_vbr_item = resolution

        return max_vbr_item

    def get_stream_url(self, **kwargs):
        info = self._get_info()
        max_vbr = self._find_max_vbr(info['quickplay']['resolution'])
        return info['quickplay']['resolution'][max_vbr]['cdn']['ks']
