import json
import logging
import os
import re
import requests
import json
import random

from DMR.utils import match1, random_user_agent
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
            'User-Agent': random_user_agent(),
        }

        # 获取标准房间号
        room_json = self._get_response()
        self.rid = room_json["data"]["room_id"]

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
            'qn': 25000,
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

        # 先按用户要求筛掉不符合的流，再做画质选择。
        #
        # 注意：这里必须先过滤再选画质，否则"指定流类型"会被静默忽略 ——
        # 原实现虽然算了 selected_urls，但随后又被一行"只按 quality 选"的赋值
        # 整个覆盖，导致无论传什么 stream_type（hls/fmp4/ts-avc…）都会走到
        # ``random.choice(avail_urls)``，随机返回任意一路（通常是 flv）。
        if stream_type == 'hls':
            # 兼容旧配置：hls 在所有 B站实现里都对应 fmp4 分片
            stream_type = 'fmp4'

        filtered_urls = avail_urls
        if stream_cdn:
            filtered_urls = [
                url_info for url_info in filtered_urls
                if url_info['stream_cdn'] == stream_cdn
                or re.search(stream_cdn, url_info['stream_cdn']) is not None
            ]
        if stream_type:
            filtered_urls = [
                url_info for url_info in filtered_urls
                if stream_type in url_info['stream_type']
            ]

        if not filtered_urls:
            logger.warning(f'Bilibili{self.rid}没有满足 {stream_cdn},{stream_type},{quality} 的流，将使用默认选项.')
            return random.choice(avail_urls)['stream_url']

        if quality:
            selected_quality = quality
        else:
            selected_quality = max(filtered_urls, key=lambda x: x['quality'])['quality']

        selected_urls = [url_info['stream_url'] for url_info in filtered_urls
                         if url_info['quality'] == selected_quality]

        if not selected_urls:
            # 指定画质在筛选结果里不存在时，退回该筛选条件下的最高画质
            best_quality = max(filtered_urls, key=lambda x: x['quality'])['quality']
            selected_urls = [url_info['stream_url'] for url_info in filtered_urls
                             if url_info['quality'] == best_quality]

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
