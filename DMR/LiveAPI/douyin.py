import re
import requests
import urllib
import json
try:
    from .BaseAPI import BaseAPI
except ImportError:
    from BaseAPI import BaseAPI

class douyin(BaseAPI):
    headers = {
        'authority': 'live.douyin.com',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/104.0.5112.81 Safari/537.36 Edg/104.0.1293.54',
    }
    def __init__(self,rid:str) -> None:
        self.web_rid = rid
        
        if not self.headers.get('cookie'):
            response = requests.get(f'https://live.douyin.com/{self.web_rid}',headers=self.headers,timeout=5)
            self.headers.update({'cookie': '__ac_nonce='+response.cookies.get('__ac_nonce')})
            
        if len(rid) == 19:
            self.real_rid = rid
        else:
            try:
                resp = self._get_response_douyin()
                self.real_rid = resp['app']['initialState']['roomStore']['roomInfo']['roomId']
            except:
                raise Exception('房间号错误.')

    def is_available(self) -> bool:
        return len(self.real_rid) == 19
    
    def _get_response_douyin(self):
        text = requests.get(f'https://live.douyin.com/{self.web_rid}',headers=self.headers,timeout=5).text
        render_data = re.findall(r"<script id=\"RENDER_DATA\" type=\"application/json\">.*?</script>",text)[0]
        data = urllib.parse.unquote(render_data)
        data = re.sub(r'(<script.*?>|</script>)','',data)
        data = json.loads(data)

        return data

    def onair(self) -> bool:
        resp = self._get_response_douyin()
        code = resp['app']['initialState']['roomStore']['roomInfo']['room']['status']
        return code == 2

    def get_stream_url(self, **kwargs) -> str:
        resp = self._get_response_douyin()
        stream_info = resp['app']['initialState']['roomStore']['roomInfo']['room']['stream_url']
        try:
            extra_data = stream_info['live_core_sdk_data']['pull_data']['stream_data']
            extra_data = json.loads(urllib.parse.unquote(extra_data))
            url_dict = extra_data['data']
            url = url_dict['origin']['main']['flv']
        except:
            urls = list(stream_info['flv_pull_url'].values())
            url = urls[0]
        return url

    def get_info(self) -> tuple:
        resp = self._get_response_douyin()
        room_info = resp['app']['initialState']['roomStore']['roomInfo']
        title = room_info['room']['title']
        uname = room_info['anchor']['nickname']
        face_url = room_info['anchor']['avatar_thumb']['url_list'][0]
        keyframe_url = None
        return title,uname,face_url,keyframe_url

if __name__ == '__main__':
    api = douyin('314150336339')
    print(api.get_info())