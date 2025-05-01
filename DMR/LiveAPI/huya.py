import json
import random

try:
    from .BaseAPI import BaseAPI
except ImportError:
    from BaseAPI import BaseAPI
import requests
import re
import base64
from lxml import etree
import urllib.parse
import hashlib
import time
import logging

from DMR.utils import random_user_agent


logger = logging.getLogger(__name__)

# 2025.4.16 改用了 https://github.com/biliup/biliup/blob/master/biliup/plugins/huya.py 实现

HUYA_WEB_BASE_URL = "https://www.huya.com"
HUYA_MOBILE_BASE_URL = "https://m.huya.com"
HUYA_MP_BASE_URL = "https://mp.huya.com"
HUYA_WEB_ROOM_DATA_REGEX = r"var TT_ROOM_DATA = (.*?);"

class huya(BaseAPI):
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
        "User-Agent": random_user_agent(),
    }
    header_mobile = {
        'Content-Type': 'application/x-www-form-urlencoded',
        'User-Agent': 'Mozilla/5.0 (Linux; Android 5.0; SM-G900P Build/LRX21T) AppleWebKit/537.36 (KHTML, like Gecko) '
                      'Chrome/75.0.3770.100 Mobile Safari/537.36 '
    }

    def __init__(self, rid: str) -> None:
        self.rid = rid
        self.sess = requests.Session()
        if not self.rid.isdigit():
            try:
                response = self._get_response()
                selector = etree.HTML(response)
                self.rid = selector.xpath('//*[@class="host-rid"]/em')[0].text
            except:
                pass
        
    def __del__(self):
        self.sess.close()

    def _get_response(self, mobile=False):
        if not mobile:
            room_url = 'https://www.huya.com/' + self.rid
            response = self.sess.get(url=room_url, headers=self.headers, timeout=5).text
        else:
            room_url = 'https://m.huya.com/' + self.rid
            response = self.sess.get(url=room_url, headers=self.header_mobile, timeout=5).text
        return response

    def _get_api_response(self):
        room_url = 'https://mp.huya.com/cache.php?m=Live&do=profileRoom&roomid=' + str(self.rid)
        data = self.sess.get(url=room_url, headers=self.header_mobile, timeout=5).json()
        return data
    
    def get_room_profile(self, use_api=False) -> dict:
        '''
        获取房间信息
        :param use_api: 是否使用API
        :return: 房间信息
        '''
        if use_api:
            params = {
                'm': 'Live',
                'do': 'profileRoom',
                'roomid': self.rid,
                'showSecret': 1,
            }
            resp = self.sess.get(
                f"{HUYA_MP_BASE_URL}/cache.php",
                headers=self.header_mobile, params=params, timeout=5)
            resp.raise_for_status()
            resp = json.loads(resp.text)
            if resp['status'] != 200:
                raise Exception(f"{resp['message']}")
        else:
            resp = self.sess.get(
                f"{HUYA_WEB_BASE_URL}/{self.rid}",
                headers=self.headers, timeout=5)
            resp.raise_for_status()
            resp = resp.text
            for err_key in ("找不到这个主播", "该主播涉嫌违规，正在整改中"):
                if err_key in resp:
                    raise Exception(err_key)
        return self.extract_room_profile(resp)
    
    def extract_room_profile(self, data):
        '''
        ON: 直播
        REPLAY: 重播
        OFF: 未开播
        '''
        if isinstance(data, str):
            room_data = json.loads(re.search(HUYA_WEB_ROOM_DATA_REGEX, data).group(1))
            s = data.split('stream: ')[1].split('};')[0]
            s_json = json.loads(s)
            bitrate_info = s_json.get('vMultiStreamInfo')
            if room_data['state'] != 'ON' or not bitrate_info:
                return {
                    'live': False,
                    'message': '未开播' if room_data['state'] != 'ON' else '未推流',
                }
            live_info = s_json['data'][0]['gameLiveInfo']
            streams_info = s_json['data'][0]['gameStreamInfoList']
        elif isinstance(data, dict):
            if data['liveStatus'] != 'ON' or not data.get('liveData', {}).get('bitRateInfo'):
                return {
                    'live': False,
                    'message': '未开播' if data['liveStatus'] != 'ON' else '未推流',
                }
            live_info = data['liveData']
            bitrate_info = live_info['bitRateInfo']
            streams_info = live_info['streamsInfo']
        return {
            'artist': live_info['nick'],
            'artist_img': live_info['avatar180'].replace('http://', 'https://'),
            'bitrate_info': bitrate_info,
            'gid': live_info['gid'],
            'live': True,
            'live_start_time': live_info['startTime'],
            'max_bitrate': live_info['bitRate'],
            'room_cover': live_info['screenshot'].replace('http://', 'https://'),
            'room_title': live_info['introduction'],
            'streams_info': streams_info,
        }

    def is_available(self) -> bool:
        return True

    def onair(self) -> bool:
        SKIP_PREFIX = ['【回放】', '【录像】', '【重播】']
        try:
            room_profile = self.get_room_profile()
            status = room_profile['live']
            if not status:
                return False
            else:
                for prefix in SKIP_PREFIX:
                    if room_profile['room_title'].startswith(prefix):
                        return False
                return True
        except Exception as e:
            # logging.debug(e)
            return None

    def get_info(self):
        """
        return: title,uname,face_url,cover_url
        """
        room_profile = self.get_room_profile()
        try:
            title = room_profile['room_title']
        except:
            title = 'huya' + self.rid
        try:
            uname = room_profile['artist']
        except:
            uname = 'huya' + self.rid
        try:
            face_url = room_profile['artist_img']
        except:
            face_url = None
        try:
            cover_url = room_profile['room_cover']
        except:
            cover_url = None
        return title, uname, face_url, cover_url

    def build_query(self, stream_name, anti_code, uid: int) -> str:
        '''
        构建anti_code
        :param stream_name: 流名称
        :param anti_code: 原始anti_code
        :param uid: 主播uid
        :return: 构建后的anti_code
        '''
        url_query = urllib.parse.parse_qs(anti_code)
        platform_id = url_query.get('t', [100])[0]
        ws_time = url_query['wsTime'][0]
        convert_uid = (uid << 8 | uid >> (32 - 8)) & 0xFFFFFFFF
        seq_id = uid + int(time.time() * 1000)
        ctype = url_query['ctype'][0]
        fm = urllib.parse.unquote(url_query['fm'][0])
        ct = int((int(ws_time, 16) + random.random()) * 1000)
        ws_secret_prefix = base64.b64decode(fm.encode()).decode().split('_')[0]
        ws_secret_hash = hashlib.md5(f"{seq_id}|{ctype}|{platform_id}".encode()).hexdigest()
        secret_str = f'{ws_secret_prefix}_{convert_uid}_{stream_name}_{ws_secret_hash}_{ws_time}'
        ws_secret = hashlib.md5(secret_str.encode()).hexdigest()

        # &codec=av1
        # &codec=264
        # &codec=265
        # dMod: wcs-25 / mesh-0 DecodeMod-SupportMod
        # chrome > 104 or safari = mseh, chrome = mses
        # sdkPcdn: 1_1 第一个1连接次数 第二个1是因为什么连接
        # t: 平台信息 100 web(ctype=huya_live/huya_webh5) 102 小程序(ctype=tars_mp)
        # PLATFORM_TYPE = {'adr': 2, 'huya_liveshareh5': 104, 'ios': 3, 'mini_app': 102, 'wap': 103, 'web': 100}
        # sv: 2401090219 版本
        # sdk_sid:  _sessionId sdkInRoomTs 当前毫秒时间
        # return f"wsSecret={ws_secret}&wsTime={ws_time}&seqid={seq_id}&ctype={url_query['ctype'][0]}&ver=1&fs={url_query['fs'][0]}&u={convert_uid}&t={platform_id}&sv=2401090219&sdk_sid={int(time.time() * 1000)}&codec=264"
        anti_code = {
            "wsSecret": ws_secret,
            "wsTime": ws_time,
            "seqid": str(seq_id),
            "ctype": ctype,
            "ver": "1",
            "fs": url_query['fs'][0],
            "t": platform_id,
            "u": convert_uid,
            "uuid": str(int((ct % 1e10 + random.random()) * 1e3 % 0xffffffff)),
            "sdk_sid": str(int(time.time() * 1000)),
        }
        return '&'.join([f"{k}={v}" for k, v in anti_code.items()])

    @staticmethod
    def __get_uid(stream_name: str) -> int:
        try:
            if stream_name:
                anchor_uid = int(stream_name.split('-')[0])
                if anchor_uid > 0:
                    return anchor_uid
        except IndexError:
            pass
        return random.randint(1400000000000, 1499999999999)

    def get_stream_urls(self, stream_type=None, stream_codec=None, **kwargs) -> str:
        room_profile = self.get_room_profile()
        is_xingxiu = (room_profile['gid'] == 1663)
        streams_info = room_profile['streams_info']

        proto = 'Hls' if stream_type == 'hls' else 'Flv'
        codec = stream_codec or '264'

        urls = []
        for stream in streams_info:
            # 优先级<0代表不可用
            priority = stream['iWebPriorityRate']
            if priority < 0:
                continue
            stream_name = stream['sStreamName']
            cdn = stream['sCdnType'].lower()
            suffix = stream[f's{proto}UrlSuffix']
            anti_code = stream[f's{proto}AntiCode']
            if not is_xingxiu:
                anti_code = self.build_query(stream_name, anti_code, self.__get_uid(stream_name))
            anti_code = anti_code + f"&codec={codec}"
            base_url = stream[f's{proto}Url'].replace('http://', 'https://')
            uri = f"{base_url}/{stream_name}.{suffix}?{anti_code}"
            urls.append({
                'stream_cdn': cdn,
                'stream_type': stream_type,
                'stream_url': uri
            })

        return urls
    
    def get_stream_url(self, stream_cdn=None, stream_type=None, **kwargs) -> str:
        avail_urls = self.get_stream_urls(stream_type=stream_type, **kwargs)
        selected_urls = []
        for url_info in avail_urls:
            if stream_cdn and url_info['stream_cdn'] != stream_cdn:
                continue
            if stream_type and url_info['stream_type'] != stream_type:
                continue
            uri = url_info['stream_url']
            selected_urls.append(uri)
        
        if not selected_urls:
            logger.warning(f'虎牙{self.rid}没有满足 {stream_cdn},{stream_type} 的流，将使用默认选项.')
            return random.choice(avail_urls)['stream_url']
        else:
            return random.choice(selected_urls)
        
    def get_stream_header(self) -> dict:
        return self.headers


if __name__ == '__main__':
    api = huya('660002')
    print(api.get_info())
