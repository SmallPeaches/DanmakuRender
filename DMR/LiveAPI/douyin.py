import re
import requests
import urllib
import json
from lxml import etree
try:
    from .BaseAPI import BaseAPI
except ImportError:
    from BaseAPI import BaseAPI

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
                resp = self._get_response_douyin()
                self.real_rid = resp['app']['initialState']['roomStore']['roomInfo']['roomId']
            except:
                self.real_rid = ''

    def is_available(self) -> bool:
        return len(self.real_rid) == 19

    def _get_response_amemv(self):
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
    
    def _get_response_douyin(self):
        if not self.headers.get('cookie'):
            response = requests.get(f'https://live.douyin.com/{self.web_rid}',headers=self.headers)
            self.headers.update({'cookie': '__ac_nonce='+response.cookies.get('__ac_nonce')})
        
        text = requests.get(f'https://live.douyin.com/{self.web_rid}',headers=self.headers).text
        render_data = re.findall(r"<script id=\"RENDER_DATA\" type=\"application/json\">.*?</script>",text)[0]
        data = urllib.parse.unquote(render_data)
        data = re.sub(r'(<script.*?>|</script>)','',data)
        data = json.loads(data)

        return data

    def onair(self) -> bool:
        # resp = self._get_response()
        # code = resp['data']['room']['status']
        resp = self._get_response_douyin()
        code = resp['app']['initialState']['roomStore']['roomInfo']['room']['status']
        return code == 2

    def get_stream_url(self, **kwargs) -> str:
        # response = self._get_response()
        # url = response['data']['room']['stream_url']['rtmp_pull_url']
        resp = self._get_response_douyin()
        urls = list(resp['app']['initialState']['roomStore']['roomInfo']['room']['stream_url']['flv_pull_url'].values())
        url = urls[0]
        return {
            'url': url
        }

    def get_info(self) -> tuple:
        # response = self._get_response()
        # data = response['data']['room']
        # title = data['title']
        # uname = data['owner']['nickname']
        # face_url = data['owner']['avatar_thumb']['url_list'][0]
        # keyframe_url = None
        resp = self._get_response_douyin()
        room_info = resp['app']['initialState']['roomStore']['roomInfo']
        title = room_info['room']['title']
        uname = room_info['anchor']['nickname']
        face_url = room_info['anchor']['avatar_thumb']['url_list'][0]
        keyframe_url = None
        return title,uname,face_url,keyframe_url

if __name__ == '__main__':
    api = douyin('314150336339')
    print(api.get_info())