import requests

from .bilivideo_utils import encode_wbi, getWbiKeys, BILI_HEADERS


class BiliVideoAPI:
    def __init__(self, headers=None, cookies: dict[str, str] = None):
        self._session = requests.Session()
        self.wbi_img = getWbiKeys()
        self.headers = headers or BILI_HEADERS
        self.cookies = cookies or {}

    def fetch_user_videos(self, user_id, page=1, page_size=30):
        encoded_parms = encode_wbi(
                params = {
                "mid": user_id,
                "ps": page_size,
                "tid": 0,
                "pn": page,
                "order": "pubdate",
            },
            wbi_img=self.wbi_img,
        )
        resp = self._session.get(
            url='https://api.bilibili.com/x/space/wbi/arc/search',
            params=encoded_parms,
            headers=self.headers,
            cookies=self.cookies,
        ).json()
        return resp['data']
    
    def fetch_video_info(self, bvid):
        resp = self._session.get(
            url=f'https://api.bilibili.com/x/web-interface/view?bvid={bvid}',
            headers=self.headers,
        ).json()
        return resp['data']
