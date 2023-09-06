import logging
import re
from urllib.parse import urlparse, parse_qs, urlunparse, urlencode
import requests
import urllib
import json
try:
    from .BaseAPI import BaseAPI
except ImportError:
    from BaseAPI import BaseAPI

class douyin(BaseAPI):
    headers = {
        'authority': 'live.douyin.com',
        'Referer': "https://live.douyin.com/",
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/104.0.5112.81 Safari/537.36 Edg/104.0.1293.54',
    }
    def __init__(self,rid:str) -> None:
        self.web_rid = rid
        
        if not self.headers.get('cookie'):
            try:
                response = requests.get(f'https://live.douyin.com/{self.web_rid}',headers=self.headers,timeout=5)
                self.headers.update({'cookie': '__ac_nonce='+response.cookies.get('__ac_nonce')})

                response = requests.get(f'https://live.douyin.com/{self.web_rid}',headers=self.headers,timeout=5)
                self.headers['cookie'] += '; ttwid=' + response.cookies.get('ttwid')
            except Exception as e:
                logging.exception(e)
                raise Exception('获取抖音cookies错误.')
        
        if len(rid) == 19:
            self.real_rid = rid
        else:
            try:
                resp = self._get_response_douyin()
                self.real_rid = resp['data'][0]['id_str']
            except:
                raise Exception(f'解析抖音房间号{rid}错误.')

    def is_available(self) -> bool:
        return len(self.real_rid) == 19
    
    def _get_response_douyin(self):
        url = 'https://live.douyin.com/webcast/room/web/enter/'
        params = {
            'web_rid': self.web_rid,
            'aid': '6383',
            'device_platform': 'web',
            'browser_language': 'zh-CN',
            'browser_platform': 'Win32',
            'browser_name': 'Edge',
            'browser_version': '104.0.1293.54',
        }
        text = requests.get(url, headers=self.headers, params=params, timeout=5).text
        data = json.loads(text)['data']
        return data

    def onair(self) -> bool:
        resp = self._get_response_douyin()
        code = resp['data'][0]['status']
        return code == 2

    def get_stream_url(self, **kwargs) -> str:
        resp = self._get_response_douyin()
        stream_info = resp['data'][0]['stream_url']
        try:
            extra_data = stream_info['live_core_sdk_data']['pull_data']['stream_data']
            extra_data = json.loads(urllib.parse.unquote(extra_data))
            url_dict = extra_data['data']
            url = url_dict['origin']['main']['flv']
        except:
            urls = list(stream_info['flv_pull_url'].values())
            url = urls[0]
        return url

    def get_info(self) -> tuple:
        resp = self._get_response_douyin()
        title = resp['data'][0]['title']
        uname = resp['user']['nickname']
        face_url = resp['user']['avatar_thumb']['url_list'][0]
        keyframe_url = None
        return title, uname, face_url, keyframe_url

if __name__ == '__main__':
    api = douyin('941912339860')
    print(api.get_stream_url())