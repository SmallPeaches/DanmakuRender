import json
import logging
import requests
from .BaseAPI import BaseAPI

class bilibili(BaseAPI):
    def __init__(self,rid) -> None:
        self.rid = rid

    def _get_response(self):
        r_url = 'https://api.live.bilibili.com/room/v1/Room/room_init?id={}'.format(self.rid)
        with requests.Session() as s:
            res = s.get(r_url).json()
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

    def get_stream_url(self) -> str:
        real_url = ''
        r_url = 'https://api.live.bilibili.com/room/v1/Room/room_init?id={}'.format(self.rid)
        with requests.Session() as s:
            res = s.get(r_url).json()
        code = res['code']
        if code == 0:
            live_status = res['data']['live_status']
            # if live_status == 1:
            #     room_id = res['data']['room_id']
            #     f_url = 'https://api.live.bilibili.com/xlive/web-room/v1/playUrl/playUrl'
            #     params = {
            #         'cid': room_id,
            #         'platform': 'mb',
            #         'otype': 'json',
            #         'qn': 10000
            #     }
            #     resp = s.get(f_url, params=params).json()
            #     try:
            #         durl = resp['data']['durl']
            #         real_url = durl[0]['url']
            #         # real_url = real_url.replace('_bluray','')
            #         # real_url = re.sub(r'live_(\d+)_(\d+)_\d+.m3u8', r'live_\1_\2.m3u8', real_url)
            #     except KeyError or IndexError:
            #         raise RuntimeError('未知错误')
            if live_status == 1:
                room_id = res['data']['room_id']
                f_url = 'https://api.live.bilibili.com/xlive/web-room/v2/index/getRoomPlayInfo'
                params = {
                    'room_id': room_id,
                    'platform': 'web',
                    'protocol': '0,1',
                    'format': '0,1,2',
                    'codec': '0',
                    'qn': 30000,
                    'ptype': 8,
                    'dolby': 5,
                    'panorama': 1
                }
                resp = s.get(f_url, params=params).json()
                try:
                    stream = resp['data']['playurl_info']['playurl']['stream']
                    http_info = stream[1]['format'][1]['codec'][0]
                    base_url = http_info['base_url']
                    host = http_info['url_info'][0]['host']
                    extra = http_info['url_info'][0]['extra']
                    real_url = host + base_url  + extra
                except KeyError or IndexError:
                    raise RuntimeError('bilibili直播流获取错误.')
        return real_url

    def get_info(self) -> tuple:
        rid = int(self.rid)
        liverInfo = []
        data = json.dumps({'ids': [rid]})  # 根据直播间房号批量获取直播间信息
        r = requests.post(r'https://api.live.bilibili.com/room/v2/Room/get_by_ids', data=data)
        r.encoding = 'utf8'
        data = json.loads(r.text)['data']
        uidList = []
        for roomID in data:
            uidList.append(data[roomID]['uid'])
        data = json.dumps({'uids': uidList})
        r = requests.post(r'https://api.live.bilibili.com/room/v1/Room/get_status_info_by_uids', data=data)
        r.encoding = 'utf8'
        data = json.loads(r.text)['data']
        if data:
            exist = False
            for uid, info in data.items():
                if rid == info['room_id']:
                    title = info['title']
                    uname = info['uname']
                    face = info['face']
                    keyFrame = info['keyframe']
                    exist = True
                    liverInfo.append([title, uname, face, keyFrame])
                    break
            try:
                if not exist:
                    r = requests.get(r'https://api.live.bilibili.com/xlive/web-room/v1/index/getInfoByRoom?room_id=%s' % rid)
                    r.encoding = 'utf8'
                    banData = json.loads(r.text)['data']
                    if banData:
                        try:
                            uname = banData['anchor_info']['base_info']['uname']
                        except:
                            uname = ''
                    else:
                        uname = ''
                    liverInfo.append([None, str(rid), uname])
            except Exception as e:
                logging.error(str(e))
        if liverInfo:
            return liverInfo[0]
        