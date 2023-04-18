import json
import logging
import requests
try:
    from .BaseAPI import BaseAPI
except ImportError:
    from BaseAPI import BaseAPI

class bilibili(BaseAPI):
    def __init__(self,rid) -> None:
        self.rid = rid
        self.header = {
            'referer': 'https://live.bilibili.com',
            'user-agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36 Edg/108.0.1462.54',
        }

    def _get_response(self):
        r_url = 'https://api.live.bilibili.com/room/v1/Room/room_init?id={}'.format(self.rid)
        with requests.Session() as s:
            res = s.get(r_url,timeout=5).json()
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

    def get_stream_url(self, flow_cdn=None, **kwargs) -> str:
        real_url = ''
        r_url = 'https://api.live.bilibili.com/room/v1/Room/room_init?id={}'.format(self.rid)
        with requests.Session() as s:
            res = s.get(r_url,timeout=5).json()
        code = res['code']
        if code == 0:
            live_status = res['data']['live_status']
            if live_status == 1:
                room_id = res['data']['room_id']
                f_url = 'https://api.live.bilibili.com/xlive/web-room/v2/index/getRoomPlayInfo'
                params = {
                    'room_id': room_id,
                    'platform': 'web',
                    'protocol': '0,1',
                    'format': '0,1,2',
                    'codec': '0',
                    'qn': 20000,
                    'ptype': 8,
                    'dolby': 5,
                    'panorama': 1
                }
                resp = requests.get(f_url, params=params, headers=self.header,timeout=5).json()
                try:
                    stream = resp['data']['playurl_info']['playurl']['stream']
                    http_info = stream[0]['format'][0]['codec'][0]
                    base_url = http_info['base_url']
                    flv_urls = []
                    for info in http_info['url_info']:
                        host = info['host']
                        extra = info['extra']
                        flv_url = host + base_url + extra
                        flv_urls.append(flv_url)
                    if flow_cdn:
                        real_url = flv_urls[min(int(flow_cdn), len(flv_urls)-1)]
                    else:
                        real_url = flv_urls[0]
                        for uri in flv_urls:
                            if 'mcdn.' not in uri:
                                real_url = uri
                                break
                except:
                    raise RuntimeError('bilibili直播流获取错误.')
                # try:
                #     stream = resp['data']['playurl_info']['playurl']['stream']
                #     http_info = stream[1]['format'][1]['codec'][0]
                #     base_url = http_info['base_url']
                #     host = http_info['url_info'][0]['host']
                #     extra = http_info['url_info'][0]['extra']
                #     real_url = host + base_url + extra
                # except KeyError or IndexError:
                #     raise RuntimeError('bilibili直播流获取错误.')
        return real_url

    def get_info(self) -> tuple:
        rid = int(self.rid)
        liverInfo = []
        data = json.dumps({'ids': [rid]})  # 根据直播间房号批量获取直播间信息
        r = requests.post(r'https://api.live.bilibili.com/room/v2/Room/get_by_ids', data=data,timeout=5)
        r.encoding = 'utf8'
        data = json.loads(r.text)['data']
        uidList = []
        for roomID in data:
            uidList.append(data[roomID]['uid'])
        data = json.dumps({'uids': uidList})
        r = requests.post(r'https://api.live.bilibili.com/room/v1/Room/get_status_info_by_uids', data=data,timeout=5)
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
                    r = requests.get(r'https://api.live.bilibili.com/xlive/web-room/v1/index/getInfoByRoom?room_id=%s'%rid,timeout=5)
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
        else:
            return '','',None,None
    
    def get_stream_header(self) -> dict:
        return self.header

if __name__ == '__main__':
    api = bilibili('5851637')    
    print(api.get_stream_url()) 