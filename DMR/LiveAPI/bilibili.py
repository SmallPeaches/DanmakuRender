import json
import logging
import requests
import json
try:
    from .BaseAPI import BaseAPI
except ImportError:
    from BaseAPI import BaseAPI

class bilibili(BaseAPI):
    def __init__(self,rid) -> None:
        self.rid = rid
        self.header = {
            'Referer': 'https://live.bilibili.com',
            'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36 Edg/108.0.1462.54',
        }

    def _get_response(self):
        r_url = 'https://api.live.bilibili.com/room/v1/Room/room_init?id={}'.format(self.rid)
        with requests.Session() as s:
            res = s.get(r_url, timeout=5, headers=self.header).json()
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

    def get_stream_url(self, 
                       flow_cdn=None, 
                       bili_watch_cookies=None,
                       bili_force_origin=('_1500',''), 
                       **kwargs,
        ) -> str:
        watch_cookies = {}
        if bili_watch_cookies:
            try:
                with open(bili_watch_cookies, 'r') as f:
                    cookies = json.load(f)
                watch_cookies = {c['name']: c['value'] for c in cookies['cookie_info']['cookies']}
            except Exception as e:
                logging.warn(f'B站观看cookies设置错误:{e}，即将使用无登录模式')

        res = self._get_response()
        room_id = res['data']['room_id']
        f_url = 'https://api.live.bilibili.com/xlive/web-room/v2/index/getRoomPlayInfo'
        params = {
            'room_id': room_id,
            'platform': 'html5',
            'protocol': '0,1',
            'format': '0,1,2',
            'codec': '0',
            'qn': 20000,
            'ptype': 8,
            'dolby': 5,
            'panorama': 1
        }
        resp = requests.get(f_url, params=params, headers=self.header, cookies=watch_cookies, timeout=5).json()
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
            if isinstance(flow_cdn, int):
                real_url = flv_urls[min(int(flow_cdn), len(flv_urls)-1)]
            elif isinstance(flow_cdn, str):
                host = f'https://{flow_cdn}.bilivideo.com'
                real_url = host + base_url + extra
            else:
                real_url = flv_urls[0]
                for uri in flv_urls:
                    if 'mcdn.' not in uri:
                        real_url = uri
                        break
        except:
            raise RuntimeError('bilibili直播流获取错误.')
        
        if http_info['current_qn'] != max(http_info['accept_qn']) and bili_force_origin:
            logging.warn('未登录B站账号，无法使用传统方法录制原画，即将启用强制原画功能.')
            src, tgt = bili_force_origin
            real_url = real_url.replace(src, tgt)
        
        return real_url

    def get_info(self) -> tuple:
        resp = requests.get(f'https://api.live.bilibili.com/xlive/web-room/v1/index/getInfoByRoom?room_id={self.rid}', headers=self.header).json()
        data = resp['data']
        
        title = data['room_info']['title']
        uname = data['anchor_info']['base_info']['uname']
        face_url = data['anchor_info']['base_info']['face']
        keyframe_url = data['room_info']['keyframe']

        return title, uname, face_url, keyframe_url
    
    def get_stream_header(self) -> dict:
        return self.header

if __name__ == '__main__':
    api = bilibili('15019349')    
    print(api.get_stream_url()) 