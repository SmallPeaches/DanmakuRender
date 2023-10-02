import logging
import re
import os
import requests
import urllib
import json
try:
    from .BaseAPI import BaseAPI
except ImportError:
    from BaseAPI import BaseAPI

class douyin_cache():
    base_headers = {
        'authority': 'live.douyin.com',
        'Referer': "https://live.douyin.com/",
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/104.0.5112.81 Safari/537.36 Edg/104.0.1293.54',
    }
    cookies = {}

    @classmethod
    def refresh_cookies(cls):
        try:
            response = requests.get(f'https://live.douyin.com/462574904325',headers=cls.base_headers,timeout=5)
            assert response.cookies.get('__ac_nonce')
            cls.cookies['__ac_nonce'] = response.cookies.get('__ac_nonce')
        except Exception as e:
            logging.exception(f'获取抖音cookies错误: {e}')
        
        try:
            response = requests.get(f'https://live.douyin.com',headers=cls.base_headers,timeout=5)
            assert response.cookies.get('ttwid')
            cls.cookies['ttwid'] = response.cookies.get('ttwid')
        except Exception as e:
            logging.exception(f'获取抖音cookies错误: {e}')

    @classmethod
    def get_cookies(cls) -> dict:
        if not cls.cookies:
            cls.refresh_cookies()
        return cls.cookies

    @classmethod
    def get_headers(cls) -> dict:
        headers = cls.base_headers.copy()
        headers['cookie'] = '; '.join(f'{k}={v}' for k,v in cls.get_cookies().items())
        return headers


class douyin(BaseAPI):
    headers = douyin_cache.get_headers()
    def __init__(self,rid:str) -> None:
        self.web_rid = rid
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
            qualities = stream_info['live_core_sdk_data']['pull_data']['options']['qualities']
            this_quality = qualities[-1]['sdk_key']
            url_dict = extra_data['data']
            url = url_dict[this_quality]['main']['flv']
        except Exception as e:
            logging.debug(e)
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
    api = douyin('739453887773')
    print(api.get_stream_url())