import json
import re

import requests

try:
    from .BaseAPI import BaseAPI
except ImportError:
    from BaseAPI import BaseAPI


class cc(BaseAPI):
    def __init__(self, rid):
        self.rid = rid

    def _get_info(self):
        room_url = f'https://cc.163.com/{self.rid}'
        response = requests.get(url=room_url).text
        data = re.findall(r'<script id="__NEXT_DATA__" type="application/json" crossorigin="anonymous">(.*?)</script>',
                          response)[0]
        data = json.loads(data)
        info = data['props']['pageProps']['roomInfoInitData']
        return info

    def is_available(self) -> bool:
        # 没看到使用的地方，暂时返回True
        return True

    def onair(self) -> bool:
        info = self._get_info()
        return info['live']['swf'] != ''

    def get_info(self) -> tuple:
        info = self._get_info()
        title = info['title']
        try:
            uname = info['nickname']
        except:
            uname = info['live']['nickname']
        try:
            face_url = info['live']['purl']
        except:
            face_url = None
        keyframe_url = None
        return title, uname, face_url, keyframe_url

    def _find_max_vbr(self, resolution_data):
        max_vbr = float('-inf')
        max_vbr_item = None

        for resolution, data in resolution_data.items():
            if 'vbr' in data and data['vbr'] > max_vbr:
                max_vbr = data['vbr']
                max_vbr_item = resolution

        return max_vbr_item

    def get_stream_url(self, **kwargs):
        info = self._get_info()
        max_vbr = self._find_max_vbr(info['live']['quickplay']['resolution'])
        return info['live']['quickplay']['resolution'][max_vbr]['cdn']['ks']
