from enum import Enum
import json
import random
import requests
import re
import base64
from lxml import etree
from urllib.parse import parse_qs, unquote, quote
import urllib.parse
import hashlib
import time
import logging
from typing import Union

try:
    from .BaseAPI import BaseAPI
except ImportError:
    from BaseAPI import BaseAPI

from DMR.utils import random_user_agent, multi_unescape
from .huya_wup import Wup, DEFAULT_TICKET_NUMBER
from .huya_wup.packet import (
    HuyaGetCdnTokenExReq,
    HuyaGetCdnTokenExRsp,
)
from .huya_wup.wup_struct.UserId import HuyaUserId


logger = logging.getLogger(__name__)

# 2025.9.3 改用了 https://github.com/biliup/biliup/blob/master/biliup/plugins/huya.py 实现
# 2026.1.7 改用了 https://github.com/biliup/biliup/blob/master/biliup/plugins/huya.py 实现

HUYA_WEB_BASE_URL = "https://www.huya.com"
HUYA_MOBILE_BASE_URL = "https://m.huya.com"
HUYA_MP_BASE_URL = "https://mp.huya.com"
HUYA_WUP_BASE_URL = "https://wup.huya.com"
HUYA_WUP_YST_URL = "https://snmhuya.yst.aisee.tv"
HUYA_WEB_ROOM_DATA_REGEX = r"var TT_ROOM_DATA = (.*?);"

WUP_UA = "HYSDK(Windows,30000002)_APP(pc_exe&7030003&official)_SDK(trans&2.29.0.5493)"
rotl64 = lambda t: ((t & 0xFFFFFFFF) << 8 | (t & 0xFFFFFFFF) >> 24) & 0xFFFFFFFF | (t & ~0xFFFFFFFF)

class huya(BaseAPI):
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
        "user-agent": random_user_agent(),
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
            # 可能存在多次嵌套
            resp = json.loads(multi_unescape(resp.text))
            if resp['status'] != 200:
                raise Exception(f"{resp['message']}")
        else:
            resp = self.sess.get(
                f"{HUYA_WEB_BASE_URL}/{self.rid}",
                headers=self.headers, timeout=5)
            resp.raise_for_status()
            resp = multi_unescape(resp.text)
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
            data = data['data']
            if data['liveStatus'] != 'ON' or not data.get('liveData', {}).get('bitRateInfo'):
                return {
                    'live': False,
                    'message': '未开播' if data['liveStatus'] != 'ON' else '未推流',
                }
            live_info = data['liveData']
            bitrate_info = json.loads(live_info['bitRateInfo'])
            streams_info = data['stream']['baseSteamInfoList']
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

    def get_cdn_token_info_ex(self, stream_name: str) -> str:
        '''
        获取 wup anti_code (getCdnTokenInfoEx)
        :param stream_name: 流名称
        :return: wup anti_code
        '''
        tid = HuyaUserId()
        tid.sHuYaUA = UAGenerator.get_random_hyapp_ua()
        wup_req = Wup()
        wup_req.requestid = abs(DEFAULT_TICKET_NUMBER)
        wup_req.servant = "liveui"
        wup_req.func = "getCdnTokenInfoEx"
        token_info_req = HuyaGetCdnTokenExReq()
        token_info_req.sStreamName = stream_name
        token_info_req.tId = tid
        wup_req.put(HuyaGetCdnTokenExReq, "tReq", token_info_req)
        data = wup_req.encode_v3()
        url = HUYA_WUP_BASE_URL
        if random.random() > 0.5:
            url = f"{HUYA_WUP_YST_URL}/{wup_req.servant}/{wup_req.func}"
        headers = {}
        self.update_headers(headers)
        rsp = self.sess.post(url, data=data, headers=headers)
        wup_rsp = Wup()
        wup_rsp.decode_v3(rsp.content)
        token_info_rsp = wup_rsp.get(HuyaGetCdnTokenExRsp, "tRsp")
        token_info = token_info_rsp.as_dict()
        return token_info['sFlvToken']
    
    def build_anticode(
        self,
        stream_name: str,
        anti_code: str,
        uid: Union[str, int] = 0,
        random_platform: bool = False,
    ) -> str:
        '''
        构建anti_code
        :param stream_name: 流名称
        :param anti_code: 原始anti_code
        :param uid: 主播uid
        :return: 构建后的anti_code
        '''
        url_query = parse_qs(anti_code)
        if not url_query.get("fm"):
            return anti_code

        ctype = url_query.get('ctype', [])
        platform_id = url_query.get('t', [])
        if len(ctype) == 0 or random_platform:
            ctype, platform_id = PLATFORM.get_random_as_tuple()
        elif len(platform_id) == 0:
            ctype = ctype[0]
            platform_id = PLATFORM.get_platform_id(ctype)
        else:
            ctype = ctype[0]
            platform_id = platform_id[0]

        is_wap = int(platform_id) in {103}
        calc_start_time = time.time()

        if isinstance(uid, str):
            uid = int(uid) if uid.isdigit() else 0
        if uid == 0:
            uid = self.generate_random_uid()
        seq_id = uid + int(calc_start_time * 1000)
        secret_hash = hashlib.md5(f"{seq_id}|{ctype}|{platform_id}".encode()).hexdigest()
        convert_uid = rotl64(uid)
        calc_uid = uid if is_wap else convert_uid

        fm = unquote(url_query['fm'][0])
        secret_prefix = base64.b64decode(fm.encode()).decode().split('_')[0]

        ws_time = url_query['wsTime'][0]
        if int(ws_time, 16) - int(calc_start_time) < (20 * 60):
            ws_time = hex(24 * 60 * 60 + int(calc_start_time))[2:]
        secret_str = f'{secret_prefix}_{calc_uid}_{stream_name}_{secret_hash}_{ws_time}'
        ws_secret = hashlib.md5(secret_str.encode()).hexdigest()

        ct = int((int(ws_time, 16) + random.random()) * 1000)
        uuid = str(int((ct % 1e10 + random.random()) * 1e3 % 0xffffffff))

        anti_code = {
            "wsSecret": ws_secret,
            "wsTime": ws_time,
            "seqid": seq_id,
            "ctype": ctype,
            "ver": "1",
            "fs": url_query['fs'][0],
            "fm": quote(url_query['fm'][0], encoding='utf-8'),
            "t": platform_id,
        }
        if is_wap:
            anti_code.update({
                "uid": uid,
                "uuid": uuid,
            })
        else:
            anti_code.update({
                "u": convert_uid,
            })
        return '&'.join([f"{k}={v}" for k, v in anti_code.items()])

    @staticmethod
    def generate_random_uid() -> int:
        return int(f"1234{random.randint(0, 9999):04d}") \
            if random.random() > 0.5 else \
            int(f"140000{random.randint(0, 9999999):07d}")

    def get_stream_urls(self, stream_type=None, stream_codec=None, huya_mobile_api=False, **kwargs) -> str:
        room_profile = self.get_room_profile(use_api=huya_mobile_api)
        streams_info = room_profile['streams_info']

        proto = 'Hls' if stream_type == 'hls' else 'Flv'
        codec = stream_codec or '264'

        urls = []
        cached_anticode = ""
        for stream in streams_info:
            # 优先级<0代表不可用
            priority = stream['iWebPriorityRate']
            if priority < 0:
                continue
            stream_name = stream['sStreamName']
            cdn = stream['sCdnType'].lower()
            suffix = stream[f's{proto}UrlSuffix']
            if not cached_anticode:
                cached_anticode = self.build_anticode(
                    stream_name,
                    self.get_cdn_token_info_ex(stream_name),
                    stream['lPresenterUid'],
                )
                cached_anticode = cached_anticode + f"&codec={codec}"
            base_url = stream[f's{proto}Url'].replace('http://', 'https://')
            uri = f"{base_url}/{stream_name}.{suffix}?{cached_anticode}"
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
        return {"User-Agent": WUP_UA}
    
    def update_headers(self, headers: dict):
        headers['User-Agent'] = WUP_UA
        headers['Origin'] = HUYA_WEB_BASE_URL
        headers['Referer'] = HUYA_WEB_BASE_URL




class PLATFORM(Enum):
    HUYA_PC_EXE = 0
    HUYA_ADR = 2
    HUYA_IOS = 3
    TV_HUYA_NFTV = 10
    HUYA_WEBH5 = 100
    HUYA_LIVE = 100
    TARS_MP = 102
    TARS_MOBILE = 103
    HUYA_LIVESHAREH5 = 104

    @classmethod
    def get_random_as_tuple(cls):
        _ = random.choice(list(cls))
        return _.name.lower(), _.value

    @classmethod
    def get_platform_id(cls, platform: str) -> int:
        return cls[platform.upper()].value if platform.upper() in cls.__members__ else 100

    @property
    def short_name(self) -> str:
        name = self.name.lower()
        idx = name.find('_')
        return name[idx + 1:] if idx != -1 else name

class UAGenerator:
    # Configuration dictionary mapping PLATFORM enum to UA components
    HYAPP_CONFIGS = {
        PLATFORM.HUYA_ADR: {
            'version': '13.1.0',
        },
        PLATFORM.HUYA_IOS: {
            'version': '13.1.0',
        },
        PLATFORM.TV_HUYA_NFTV: {
            'version': '2.6.10',
        },
        PLATFORM.HUYA_PC_EXE: {
            'version': '7000000',
        },
        # PLATFORM.HUYA_WEBH5: {       # 星秀区不可用
        #     'version': '%y%m%d%H%M', # 2410101630
        #     'channel': 'websocket'
        # }
    }

    @staticmethod
    def generate_hyapp_ua(platform: PLATFORM) -> str:
        '''
        Generate hyapp user agent string
        :param platform: Platform type from PLATFORM enum
        :return: User agent string
        '''
        config = UAGenerator.HYAPP_CONFIGS.get(platform)
        if not config:
            platform = random.choice(list(UAGenerator.HYAPP_CONFIGS.keys()))
            config = UAGenerator.HYAPP_CONFIGS[platform]

        hyapp_platform = platform.short_name
        hyapp_version = config.get("version", "0.0.0")
        hyapp_channel = config.get("channel", "official")

        if platform in {PLATFORM.HUYA_ADR, PLATFORM.TV_HUYA_NFTV}:
            hyapp_version += f".{random.randint(3000, 5000)}"

        ua = f"{hyapp_platform}&{hyapp_version}&{hyapp_channel}"

        if platform in {PLATFORM.HUYA_ADR, PLATFORM.TV_HUYA_NFTV}:
            android_api_level = random.randint(28, 36)
            ua = f"{ua}&{android_api_level}"

        return ua

    @staticmethod
    def get_random_hyapp_ua() -> str:
        random_platform = random.choice(list(PLATFORM))
        return UAGenerator.generate_hyapp_ua(random_platform)


def _raise_for_room_block(text: str):
    for err_key in ("找不到这个主播", "该主播涉嫌违规，正在整改中"):
        if err_key in text:
            raise Exception(err_key)


if __name__ == '__main__':
    api = huya('660002')
    print(api.get_info())
