import logging
import random
import re
import os
from typing import Optional
import requests
import urllib
import json
try:
    from .BaseAPI import BaseAPI
except ImportError:
    from BaseAPI import BaseAPI
try:
    from .abogus import ABogus
except ImportError:
    from abogus import ABogus
from DMR.utils import random_user_agent
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse


logger = logging.getLogger(__name__)


class douyin_utils():
    base_headers = {
        'authority': 'live.douyin.com',
        'accept-encoding': 'gzip, deflate',         # brotli 会导致返回内容无法解码
        'Referer': "https://live.douyin.com/",
        'user-agent': random_user_agent(),
    }
    cookies = {}

    _douyin_ttwid: Optional[str] = None
    # DOUYIN_USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.159 Safari/537.36'
    CHARSET = "abcdef0123456789"
    LONG_CHATSET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"

    @staticmethod
    def get_ttwid() -> Optional[str]:
        if not douyin_utils._douyin_ttwid:
            try:
                page = requests.get("https://live.douyin.com/1-2-3-4-5-6-7-8-9-0", timeout=15, 
                                    headers=douyin_utils.base_headers)
                douyin_utils._douyin_ttwid = page.cookies.get("ttwid")
            except Exception as e:
                logger.exception(f'获取抖音ttwid失败: {e}')
                raise e
        return douyin_utils._douyin_ttwid

    @staticmethod
    def generate_ms_token() -> str:
        '''生成随机 msToken'''
        return ''.join(random.choice(douyin_utils.LONG_CHATSET) for _ in range(184))


    @staticmethod
    def generate_nonce() -> str:
        """生成 21 位随机十六进制小写 nonce"""
        return ''.join(random.choice(douyin_utils.CHARSET) for _ in range(21))


    @staticmethod
    def generate_odin_ttid() -> str:
        """生成 160 位随机十六进制小写 odin_ttid"""
        return ''.join(random.choice(douyin_utils.CHARSET) for _ in range(160))
    
    @classmethod
    def get_headers(cls, extra_cookies:dict=None) -> dict:
        headers = cls.base_headers.copy()
        cookies = {
            'ttwid': cls.get_ttwid(),
            '__ac_nonce': cls.generate_nonce(),
            'odin_ttid': cls.generate_odin_ttid(),
        }
        if extra_cookies:
            cookies.update(extra_cookies)
        headers['cookie'] = '; '.join(f'{k}={v}' for k,v in cookies.items())
        return headers
    
    @classmethod
    def build_request_url(cls, url:str, query:dict=None) -> str:
        headers = cls.get_headers()
        user_agent = headers.get('user-agent')
        
        parsed_url = urlparse(url)
        params_to_encode = (query or parse_qs(parsed_url.query)).copy()
        
        try:
            browser_info = user_agent.split(' ')[-1]
            browser_name = browser_info.split('/')[0]
            browser_version = browser_info.split('/')[1]
        except IndexError:
            browser_name = "Edge"
            browser_version = "124.0.0.0"
        params_to_encode.update({
            'aid': '6383',
            'enter_from': random.choice(['link_share', 'web_live']),
            'device_platform': 'web',
            'browser_language': 'zh-CN',
            'browser_platform': 'Win32',
            'browser_name': browser_name,
            'browser_version': browser_version,
        })
        
        encoded_params_str = urlencode(params_to_encode, doseq=True)
        abogus_generator = ABogus(user_agent=user_agent)
        abogus_value = abogus_generator.generate_abogus(params=encoded_params_str, body="")[1]
        final_params = params_to_encode
        final_params['a_bogus'] = abogus_value
        new_query_string = urlencode(final_params, doseq=True)
        new_url = urlunparse((
            parsed_url.scheme,
            parsed_url.netloc,
            parsed_url.path,
            parsed_url.params,
            new_query_string,
            parsed_url.fragment
        ))
        return new_url


class douyin(BaseAPI):
    def __init__(self, rid:str) -> None:
        self.web_rid = rid
        self.sess = requests.Session()
        self.headers = douyin_utils.get_headers()
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
        }
        self.headers = douyin_utils.get_headers()
        url = douyin_utils.build_request_url(url, query=params)
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
                if not str(url).startswith('http'):
                    continue
                real_urls.append({
                    'quality': this_quality,
                    'stream_type': stype,
                    'stream_url': url,
                })
        except Exception as e:
            logger.debug(e)
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
            logger.warning(f'抖音{self.web_rid}没有{stream_type}流，将使用默认选项.')
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
