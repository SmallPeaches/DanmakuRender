import random
from .BaseAPI import BaseAPI
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
            response = self._get_response(mobile=True)
            liveLineUrl = re.findall(r'"liveLineUrl":"([\s\S]*?)",', response)[0]
            liveline = base64.b64decode(liveLineUrl).decode('utf-8')
            if liveline and 'replay' not in liveline:
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
        
        def live(e):
            try:
                i, b = e.split('?')
                r = i.split('/')
                s = re.sub(r'.(flv|m3u8)', '', r[-1])
                c = b.split('&')
                c = [i for i in c if i != '']
                n = {i.split('=')[0]: i.split('=')[1] for i in c}
                
                fm = urllib.parse.unquote(n['fm']) if ('fm' in n.keys()) else ''
                u = base64.b64decode(fm).decode('utf-8') if ('fm' in n.keys()) else ''
                p = u.split('_')[0]
                f = str(int(time.time() * 1e7))
                l = n['wsTime']
                
                mt = n['txyp'] if ('txyp' in n.keys()) else 'a'
                t = str(random.randint(1460000000000, 1660000000000))

                mm = t+f
                ml = n['ctype']
                fs = n['fs']
                sp = n['sphdcdn'] if ('sphdcdn' in n.keys()) else 'al_7-tx_3-js_3-ws_7-bd_2-hw_2'
                spp = n['sphdDC'] if ('sphdDC' in n.keys()) else 'huya'
                spd = n['sphd'] if ('sphd' in n.keys()) else '264_*-265_'
                ll = mm+'|'+ml+'|103'
                ms = hashlib.md5(ll.encode("utf-8")).hexdigest()
                h = '_'.join([p, t, s, ms, l])
                m = hashlib.md5(h.encode('utf-8')).hexdigest()
                urls = "{}?wsSecret={}&wsTime={}&seqid={}&ctype={}&ver=1&txyp={}&fs={}&&sphdcdn={}&sphdDC={}&sphd={}&t=103&ratio=0&u={}&t=103&sv=2110211124".format(i, m, l, mm, ml, mt, fs, sp, spp, spd, t)
                aa, ab = urls.split('//')
                url = 'https://'+ab
            
                return url
            except Exception as e: 
                return ''

        if not self.rid.isdigit():
            try:
                response = self._get_response()
                selector = etree.HTML(response)
                rid = selector.xpath('//*[@class="host-rid"]/em')[0].text
            except:
                rid = self.rid
        else:
            rid = self.rid
        
        room_url = 'https://mp.huya.com/cache.php?m=Live&do=profileRoom&roomid=' + str(rid)
        data = requests.get(url=room_url, headers=self.header_mobile).json()
        
        multiLine=data['data']['stream']['flv']['multiLine']
        urls=[]
        liveData=data['data']['liveData']
        
        for i in range(len(multiLine)):
            obj=multiLine[i]
            if obj['url'] is not None:
                liveline = live(obj['url'])
                urls.append(liveline)
        return urls[0]


        
