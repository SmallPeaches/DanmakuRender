import re
import requests

from .BaseAPI import BaseAPI

class douyin(BaseAPI):
    headers = {
        'authority': 'live.douyin.com',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/104.0.5112.81 Safari/537.36 Edg/104.0.1293.54',
    }
    def __init__(self,rid:str) -> None:
        self.web_rid = rid
        if len(rid) == 19:
            self.real_rid = rid
        else:
            try:
                if not self.headers.get('cookie'):
                    response = requests.get(f'https://live.douyin.com/{rid}',headers=self.headers)
                    self.headers.update({'cookie': '__ac_nonce='+response.cookies.get('__ac_nonce')})
                response = requests.get(f'https://live.douyin.com/{rid}',headers=self.headers)
                text = response.text
                self.real_rid = text[text.find('roomId%22%3A%22'):][15:34]
            except:
                self.real_rid = ''

    def is_available(self) -> bool:
        return len(self.real_rid == 19)

    def _get_response(self):
        headers = self.headers.copy()
        headers.update({
            'authority': 'webcast.amemv.com',
            'cookie': '_tea_utm_cache_1128={%22utm_source%22:%22copy%22%2C%22utm_medium%22:%22android%22%2C%22utm_campaign%22:%22client_share%22}',
        })
        params = (
            ('type_id', '0'),
            ('live_id', '1'),
            ('room_id', self.real_rid),
            ('app_id', '1128'),
        )
        response = requests.get('https://webcast.amemv.com/webcast/room/reflow/info/', headers=headers, params=params).json()

        return response

    def onair(self) -> bool:
        resp = self._get_response()
        code = resp['data']['room']['status']
        return code == 2

    def get_stream_url(self) -> str:
        response = self._get_response()
        rtmp_pull_url = response['data']['room']['stream_url']['rtmp_pull_url']
        return rtmp_pull_url

    def get_info(self) -> tuple:
        response = self._get_response()
        data = response['data']['room']
        title = data['title']
        uname = data['owner']['nickname']
        face_url = data['owner']['avatar_thumb']['url_list'][0]
        keyframe_url = None
        return title,uname,face_url,keyframe_url
