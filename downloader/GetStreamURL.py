import json
import sys
import requests
import re

class GetStreamURL():
    header = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'User-Agent': 'Mozilla/5.0 (Linux; Android 5.0; SM-G900P Build/LRX21T) AppleWebKit/537.36 '
                            '(KHTML, like Gecko) Chrome/75.0.3770.100 Mobile Safari/537.36 '
        }
    @classmethod
    def _get_huya_url(cls,rid) -> dict:
        room_url = 'https://m.huya.com/' + str(rid)
        response = requests.get(url=room_url, headers=cls.header).text
        info = json.loads(re.findall(r"<script> window.HNF_GLOBAL_INIT = (.*)</script>", response)[0])
        if info == {'exceptionType': 0}:
            raise ValueError(f'房间{rid}不存在')
        roomInfo = info["roomInfo"]
        real_url = {}

        # not live
        if roomInfo["eLiveStatus"] == 1:
            raise RuntimeError('未开播')

        # live
        elif roomInfo["eLiveStatus"] == 2:
            streamInfos = roomInfo["tLiveInfo"]["tLiveStreamInfo"]["vStreamInfo"]["value"]
            for streamInfo in streamInfos:
                real_url[streamInfo["sCdnType"].lower() + "_flv"] = streamInfo["sFlvUrl"] + "/" + streamInfo["sStreamName"] + "." + \
                                                                streamInfo["sFlvUrlSuffix"] + "?" + streamInfo["sFlvAntiCode"]
                real_url[streamInfo["sCdnType"].lower() + "_hls"] = streamInfo["sHlsUrl"] + "/" + streamInfo["sStreamName"] + "." + \
                                                                streamInfo["sHlsUrlSuffix"] + "?" + streamInfo["sHlsAntiCode"]

        # replay
        elif roomInfo["eLiveStatus"] == 3:
            real_url["replay"] = roomInfo["tReplayInfo"]["tReplayVideoInfo"]["sUrl"]
        else:
            raise RuntimeError('未知错误')
        
        return real_url

    @classmethod
    def _get_bilibili_url(cls,rid) -> str:
        real_url = ''
        r_url = 'https://api.live.bilibili.com/room/v1/Room/room_init?id={}'.format(rid)
        with requests.Session() as s:
            res = s.get(r_url).json()
        code = res['code']
        if code == 0:
            live_status = res['data']['live_status']
            if live_status == 1:
                room_id = res['data']['room_id']
                f_url = 'https://api.live.bilibili.com/xlive/web-room/v1/playUrl/playUrl'
                params = {
                    'cid': room_id,
                    'platform': 'flash',
                    'otype': 'json',
                    'qn': 10000
                }
                resp = s.get(f_url, params=params).json()
                try:
                    durl = resp['data']['durl']
                    real_url = durl[0]['url']
                    real_url = re.sub(r'live_(\d+)_(\d+)_\d+.m3u8', r'live_\1_\2.m3u8', real_url)
                except KeyError or IndexError:
                    raise RuntimeError('未知错误')
            else:
                raise RuntimeError('未开播')
        else:
            raise ValueError(f'房间{rid}不存在')
        
        return real_url

    @classmethod
    def _get_douyu_url(cls,rid):
        raise NotImplementedError()

    @classmethod
    def get_url(cls,urlx:str) -> str:
        url = None
        platform = re.findall(r'\.(.*).com/',urlx)[0]
        rid = re.findall(r'\.com/([\w]*)',urlx)[0]
        
        if platform in ['hy','huya']:
            urls = cls._get_huya_url(rid)
            url = urls['al_flv']
        
        elif platform in ['bili','bilibili','bl']:
            urls = cls._get_bilibili_url(rid)
            url = urls

        elif platform in ['dy','douyu']:
            urls = cls._get_douyu_url(rid)
            url = urls
        
        else:
            raise ValueError(f"无法解析URL: {urlx}")

        return url
