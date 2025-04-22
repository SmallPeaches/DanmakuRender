import json
import logging
import os
import re
import requests
import json
import random
try:
    from .BaseAPI import BaseAPI
except ImportError:
    from BaseAPI import BaseAPI

logger = logging.getLogger(__name__)

class bilibili(BaseAPI):
    def __init__(self,rid) -> None:
        self.rid = rid
        self.sess = requests.Session()
        self.header = {
            'Referer': 'https://live.bilibili.com',
            'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36 Edg/108.0.1462.54',
        }

    def _get_response(self):
        r_url = 'https://api.live.bilibili.com/room/v1/Room/room_init?id={}'.format(self.rid)
        res = self.sess.get(r_url, timeout=5, headers=self.header).json()
        return res

    def is_available(self) -> bool:
        code = self._get_response()['code']
        if code == 0:
            return True
        else:
            return False
        
    def onair(self) -> bool:
        resp = self._get_response()
        code = resp['code']
        if code == 0:
            live_status = resp['data']['live_status']
            if live_status == 1:
                return True
            else:
                return False

    def get_stream_urls(self,
                        bili_watch_cookies=None,
                        **kwargs) -> dict:
        bili_watch_cookies = bili_watch_cookies or '.login_info/.bili_watch_cookies.json'
        watch_cookies = {}
        if bili_watch_cookies.lower() != 'none':
            try:
                if not os.path.exists(bili_watch_cookies) and os.path.exists('.login_info/bilibili.json'):
                    bili_watch_cookies = '.login_info/bilibili.json'
                elif not os.path.exists(bili_watch_cookies):
                    from DMR.Uploader.biliuprs import biliuprs
                    logger.info(f'即将登录用于B站获取直播流的账号，如果不想登录请设置bili_watch_cookies为空.')
                    biliuprs(cookies=bili_watch_cookies)
                with open(bili_watch_cookies, 'r') as f:
                    cookies = json.load(f)
                watch_cookies = {c['name']: c['value'] for c in cookies['cookie_info']['cookies']}
                logger.info(f'正在使用 {bili_watch_cookies} 的cookies登录B站.')
            except Exception as e:
                logger.warning(f'B站观看cookies设置错误:{e}，即将使用无登录模式.')

        res = self._get_response()
        room_id = res['data']['room_id']
        f_url = 'https://api.live.bilibili.com/xlive/web-room/v2/index/getRoomPlayInfo'
        params = {
            'room_id': room_id,
            'platform': 'html5',
            'protocol': '0,1',
            'format': '0,1,2',
            'codec': '0,1,2',   # 0:avc, 1:hevc, 2:av1
            'qn': 20000,
            'ptype': 8,
            'dolby': 5,
            'panorama': 1
        }
        resp = self.sess.get(f_url, params=params, headers=self.header, cookies=watch_cookies, timeout=5).json()
        real_urls = []
        try:
            stream = resp['data']['playurl_info']['playurl']['stream']
            for protocol_info in stream:
                for format_info in protocol_info['format']:
                    format_name = format_info['format_name']
                    for http_info in format_info['codec']:
                        base_url = http_info['base_url']
                        codec_name = http_info['codec_name']
                        for info in http_info['url_info']:
                            host = info['host']
                            extra = info['extra']
                            url = host + base_url + extra
                            real_urls.append({
                                'quality': http_info['current_qn'],
                                'stream_cdn': host.split('//')[1],
                                'stream_type': f'{format_name}-{codec_name}',
                                'stream_url': url,
                            })
        except Exception as e:
            raise RuntimeError(f'bilibili {self.rid} 直播流获取错误: {e}')
        
        if max(real_urls, key=lambda x: x['quality'])['quality'] < 10000:
            logger.warning('未登录B站账号，无法录制原画，将录制最低画质直播.')
        
        return real_urls
    
    def get_stream_url(self,
                       stream_cdn=None, 
                       stream_type=None,
                       quality=None,
                       **kwargs) -> str:
        avail_urls = self.get_stream_urls(**kwargs)

        # 有可能返回的流存在多种质量，因为H.265和H.264压缩策略不同
        max_quality = max(avail_urls, key=lambda x: x['quality'])['quality']
        avail_urls = [max_res_urls for max_res_urls in avail_urls if max_res_urls['quality'] == max_quality]

        # 找出URL里面不带bluray字样的原画流
        best_urls = [best_urls for best_urls in avail_urls if not re.search(r'live_\d+_[a-zA-Z_]{0,10}\d+_[a-zA-Z]{1,10}', best_urls['stream_url'])]
        if best_urls:
            avail_urls = best_urls

        # 如果没有指定cdn和流类型，并且没有找到原画流，则使用fmp4流用于强制原画
        if not stream_cdn and not stream_type and not best_urls:
            stream_cdn = '.*gotcha.*'
            stream_type = 'fmp4'
        else:
            stream_type = 'fmp4' if stream_type == 'hls' else 'flv'

        selected_urls = []
        for url_info in avail_urls:
            if stream_cdn \
                and url_info['stream_cdn'] != stream_cdn \
                and re.search(stream_cdn, url_info['stream_cdn']) is None:
                continue
            if stream_type and stream_type not in url_info['stream_type']:
                continue
            uri = url_info['stream_url']
            selected_urls.append(uri)

        if not selected_urls:
            logger.warning(f'Bilibili{self.rid}没有满足 {stream_cdn},{stream_type} 的流，将使用默认选项.')
            return random.choice(avail_urls)['stream_url']
        else:
            return random.choice(selected_urls)

    def get_info(self) -> tuple:
        try:
            resp = self.sess.get(f'https://api.live.bilibili.com/xlive/web-room/v1/index/getInfoByRoom?room_id={self.rid}', headers=self.header, timeout=5).json()
            data = resp['data']
            
            title = data['room_info']['title']
            uname = data['anchor_info']['base_info']['uname']
            face_url = data['anchor_info']['base_info']['face']
            cover_url = data['room_info']['cover']
        
        # 海外服务器可能报错就用下面的方法
        except Exception as e:
            resp = self.sess.get(f'https://api.live.bilibili.com/room/v1/Room/get_info?room_id={self.rid}', headers=self.header, timeout=5).json()
            title = resp['data']['title']
            cover_url = resp['data']['user_cover']

            resp = self.sess.get(f'https://api.live.bilibili.com/live_user/v1/UserInfo/get_anchor_in_room?roomid={self.rid}', headers=self.header, timeout=5).json()
            info = resp['data']['info']
            uname = info['uname']
            face_url = info['face']

        return title, uname, face_url, cover_url
    
    def get_stream_header(self) -> dict:
        return self.header

if __name__ == '__main__':
    api = bilibili('13308358')    
    print(api.get_stream_url()) 