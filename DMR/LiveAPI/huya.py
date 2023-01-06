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

class huya(BaseAPI):
    header = {
            'Content-Type': 'application/x-www-form-urlencoded',
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/88.0.4324.150 Safari/537.36 Edg/88.0.705.68",
        }
    header_mobile = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'User-Agent': 'Mozilla/5.0 (Linux; Android 5.0; SM-G900P Build/LRX21T) AppleWebKit/537.36 (KHTML, like Gecko) '
                          'Chrome/75.0.3770.100 Mobile Safari/537.36 '
        }
    def __init__(self,rid:str) -> None:
        self.rid = rid
        if not self.rid.isdigit():
            try:
                response = self._get_response()
                selector = etree.HTML(response)
                self.rid = selector.xpath('//*[@class="host-rid"]/em')[0].text
            except:
                pass
    
    def _get_response(self,mobile=False):
        if not mobile:
            room_url = 'https://www.huya.com/' + self.rid
            response = requests.get(url=room_url, headers=self.header).text
        else:
            room_url = 'https://m.huya.com/' + self.rid
            response = requests.get(url=room_url, headers=self.header_mobile).text
        return response

    def is_available(self) -> bool:
        try:
            response = self._get_response(mobile=True)
            liveLineUrl = re.findall(r'"liveLineUrl":"([\s\S]*?)",', response)[0]
            liveline = base64.b64decode(liveLineUrl).decode('utf-8')
            return True
        except:
            return False

    def onair(self) -> bool:
        try:
            room_url = 'https://mp.huya.com/cache.php?m=Live&do=profileRoom&roomid=' + str(self.rid)
            data = requests.get(url=room_url, headers=self.header_mobile).json()
            
            status=data['data']['realLiveStatus']
            if status == 'ON':
                return True
            else:
                return False
        except:
            return None

    def get_info(self):
        """
        return: title,uname,face_url,keyframe_url
        """
        response = self._get_response()
        selector = etree.HTML(response)
        try:
            title = selector.xpath('//*[@id="J_roomTitle"]')[0].text
        except:
            title = 'huya'+self.rid
        try:
            uname = selector.xpath('//*[@id="J_roomHeader"]/div[1]/div[2]/div/h3')[0].text
        except:
            uname = 'huya'+self.rid
        try:
            face_url = selector.xpath('//*[@id="avatar-img"]/@src')[0]
        except:
            face_url = 'huya'+self.rid
        keyframe_url = None
        return title,uname,face_url,keyframe_url

    def get_stream_url(self) -> str:
        room_url = 'https://mp.huya.com/cache.php?m=Live&do=profileRoom&roomid=' + str(self.rid)
        data = requests.get(url=room_url, headers=self.header_mobile).json()
        
        multiLine=data['data']['stream']['flv']['multiLine']
        urls=[]
        
        for i in range(len(multiLine)):
            obj=multiLine[i]
            if obj['url'] is not None:
                # liveline = live(obj['url'])
                # urls.append(liveline)
                urls.append(obj['url'])
        return {
            'url': urls[0]
        }

if __name__ == '__main__':
    api = huya('125836')
    print(api.onair())


        
