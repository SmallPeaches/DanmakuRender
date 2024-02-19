import logging
import random
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
        with requests.Session() as sess:
            try:
                response = sess.get(f'https://live.douyin.com/462574904325',headers=cls.base_headers,timeout=5)
                assert response.cookies.get('__ac_nonce')
                cls.cookies['__ac_nonce'] = response.cookies.get('__ac_nonce')
            except Exception as e:
                logging.exception(f'获取抖音cookies错误: {e}')
            
            try:
                response = sess.get(f'https://live.douyin.com',headers=cls.base_headers,timeout=5)
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
    def __init__(self,rid:str) -> None:
        self.web_rid = rid
        self.sess = requests.Session()
        self.headers = douyin_cache.get_headers()
        if len(rid) == 19:
            self.real_rid = rid
        else:
            try:
                resp = self._get_response_douyin()
                self.real_rid = resp['data'][0]['id_str']
            except:
                raise Exception(f'解析抖音房间号{rid}错误.')
    
    def __del__(self):
        self.sess.close()

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
        text = self.sess.get(url, headers=self.headers, params=params, timeout=5).text
        data = json.loads(text)['data']
        return data

    def onair(self) -> bool:
        resp = self._get_response_douyin()
        code = resp['data'][0]['status']
        return code == 2

    def get_stream_urls(self, **kwargs) -> str:
        resp = self._get_response_douyin()
        stream_info = resp['data'][0]['stream_url']
        real_urls = []
        try:
            extra_data = stream_info['live_core_sdk_data']['pull_data']['stream_data']
            extra_data = json.loads(urllib.parse.unquote(extra_data))
            qualities = stream_info['live_core_sdk_data']['pull_data']['options']['qualities']
            this_quality = qualities[-1]['sdk_key']
            url_dict = extra_data['data']
            for stype, url in url_dict[this_quality]['main'].items():
                if not url.startswith('http'):
                    continue
                real_urls.append({
                    'quality': this_quality,
                    'stream_type': stype,
                    'stream_url': url,
                })
        except Exception as e:
            logging.debug(e)
            url = list(stream_info['flv_pull_url'].items())[0]
            real_urls = [{
                    'quality': url[0],
                    'stream_type': 'flv',
                    'stream_url': url[1],
                }]
        return real_urls
    
    def get_stream_url(self, stream_type=None, **kwargs) -> str:
        stream_type = 'flv'
        
        avail_urls = self.get_stream_urls()
        selected_urls = []
        for url_info in avail_urls:
            if url_info['stream_type'] != stream_type:
                continue
            uri = url_info['stream_url']
            selected_urls.append(uri)
        
        if not selected_urls:
            logging.warning(f'抖音{self.web_rid}没有{stream_type}流，将使用默认选项.')
            return random.choice(avail_urls)['stream_url']
        else:
            return random.choice(selected_urls)

    def get_info(self) -> tuple:
        resp = self._get_response_douyin()
        title = resp['data'][0]['title']
        uname = resp['user']['nickname']
        face_url = resp['user']['avatar_thumb']['url_list'][0]
        keyframe_url = None
        return title, uname, face_url, keyframe_url

if __name__ == '__main__':
    api = douyin('458897981613')
    print(api.get_stream_url())