# 获取斗鱼直播间的真实流媒体地址，默认最高画质
# 使用 https://github.com/wbt5/real-url/issues/185 中两位大佬@wjxgzz @4bbu6j5885o3gpv6ss8找到的的CDN，在此感谢！
try:
    from .BaseAPI import BaseAPI
except ImportError:
    from BaseAPI import BaseAPI
import hashlib
import warnings
import re
import time

import execjs
import requests
from lxml import etree

class douyu(BaseAPI):
    header = {
            'Content-Type': 'application/x-www-form-urlencoded',
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/88.0.4324.150 Safari/537.36 Edg/88.0.705.68",
        }
    header_mobile = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'User-Agent': 'Mozilla/5.0 (Linux; Android 5.0; SM-G900P Build/LRX21T) AppleWebKit/537.36 (KHTML, like Gecko) '
                          'Chrome/75.0.3770.100 Mobile Safari/537.36 '
        }
    host_list = ['hw-tct.douyucdn.cn','tx2play1.douyucdn.cn','hdltctwk.douyucdn2.cn','akm-tct.douyucdn.cn','tc-tct1.douyucdn.cn']

    def __init__(self,rid:str) -> None:
        self.rid = rid

        self.did = '10000000000000000000000000001501'
        self.s = requests.Session()
        res = self.s.get('https://m.douyu.com/' + str(rid)).text

        try:
            self.rid = re.findall(r'rid":(\d*),"vipId', res)[0]
        except:
            raise Exception('房间号错误')
    
    def __del__(self):
        self.s.close()

    @staticmethod
    def md5(data):
        return hashlib.md5(data.encode('utf-8')).hexdigest()

    def get_pre(self):
        self.t13 = str(int((time.time() * 1000)))
        url = 'https://playweb.douyucdn.cn/lapi/live/hlsH5Preview/' + self.rid
        data = {
            'rid': self.rid,
            'did': self.did
        }
        auth = douyu.md5(self.rid + self.t13)
        headers = {
            'rid': self.rid,
            'time': self.t13,
            'auth': auth
        }
        res = self.s.post(url, headers=headers, data=data).json()
        error = res['error']
        data = res['data']
        key = ''
        if data:
            rtmp_live = data['rtmp_live']
            key = re.search(r'(\d{1,8}[0-9a-zA-Z]+)_?\d{0,4}(/playlist|.m3u8)', rtmp_live).group(1)
        return error, key
    
    def get_resp_new(self):
        resp = requests.get(f'https://www.douyu.com/betard/{self.rid}', headers=self.header).json()
        return resp
    
    def get_h5play_resp(self, cdn='', rate=0):
        t10 = str(int(time.time()))
        res = self.s.get('https://www.douyu.com/' + str(self.rid)).text
        result = re.search(r'(vdwdae325w_64we[\s\S]*function ub98484234[\s\S]*?)function', res).group(1)
        func_ub9 = re.sub(r'eval.*?;}', 'strc;}', result)
        js = execjs.compile(func_ub9)
        res = js.call('ub98484234')

        v = re.search(r'v=(\d+)', res).group(1)
        rb = self.md5(self.rid + self.did + t10 + v)

        func_sign = re.sub(r'return rt;}\);?', 'return rt;}', res)
        func_sign = func_sign.replace('(function (', 'function sign(')
        func_sign = func_sign.replace('CryptoJS.MD5(cb).toString()', '"' + rb + '"')

        js = execjs.compile(func_sign)
        params = js.call('sign', self.rid, self.did, t10)

        params += '&cdn={}&rate={}'.format(cdn, rate)
        url = 'https://www.douyu.com/lapi/live/getH5Play/{}'.format(self.rid)
        res = self.s.post(url, params=params).json()
        return res
    
    def is_available(self) -> bool:
        error, key = self.get_pre()
        if error == 102:
            return False
        else:
            return True

    def onair(self) -> bool:
        h5play_resp = self.get_h5play_resp()
        error = h5play_resp.get('error')
        resp = self.get_resp_new()
        videoloop = resp['room']['videoLoop']
        show_status = resp['room']['show_status']
        if error == 0 and show_status == 1 and videoloop == 0:
            return True
        else:
            return False

    def get_info(self):
        """
        return: title,uname,face_url,keyframe_url
        """
        resp = self.get_resp_new()
        try:
            title = resp['room']['room_name']
        except:
            title = 'douyu'+self.rid
        try:
            uname = resp['room']['nickname']
        except:
            uname = 'douyu'+self.rid
        try:
            face_url = resp['room']['owner_avatar']
        except:
            face_url = None
        try:
            keyframe_url = resp['room']['room_pic']
        except:
            keyframe_url = None
        return title,uname,face_url,keyframe_url

    def get_pc_js(self, cdn='ws-h5', rate=0):
        """
        通过PC网页端的接口获取完整直播源。
        :param cdn: 主线路ws-h5、备用线路tct-h5
        :param rate: 1流畅；2高清；3超清；4蓝光4M；0蓝光8M或10M
        :return: JSON格式
        """
        t10 = str(int(time.time()))
        res = self.s.get('https://www.douyu.com/' + str(self.rid)).text
        result = re.search(r'(vdwdae325w_64we[\s\S]*function ub98484234[\s\S]*?)function', res).group(1)
        func_ub9 = re.sub(r'eval.*?;}', 'strc;}', result)
        js = execjs.compile(func_ub9)
        res = js.call('ub98484234')

        v = re.search(r'v=(\d+)', res).group(1)
        rb = self.md5(self.rid + self.did + t10 + v)

        func_sign = re.sub(r'return rt;}\);?', 'return rt;}', res)
        func_sign = func_sign.replace('(function (', 'function sign(')
        func_sign = func_sign.replace('CryptoJS.MD5(cb).toString()', '"' + rb + '"')

        js = execjs.compile(func_sign)
        params = js.call('sign', self.rid, self.did, t10)

        params += '&cdn={}&rate={}'.format(cdn, rate)
        url = 'https://www.douyu.com/lapi/live/getH5Play/{}'.format(self.rid)
        res = self.s.post(url, params=params).json()
        data = res.get('data')
        if data:
            rtmp_live = data['rtmp_live']
            key = re.search(r'(\d{1,8}[0-9a-zA-Z]+)_?\d{0,4}(/playlist|.flv)', rtmp_live).group(1)
        return key

    def get_stream_url(self, flow_cdn='', **kwargs) -> str:
        error, key = self.get_pre()
        if error == 0:
            pass
        elif error == 102:
            raise Exception('房间不存在')
        elif error == 104:
            raise Exception('未开播')
        else:
            key = self.get_pc_js()
        
        flag = False
        for host in self.host_list:
            real_url = f"http://{host}/live/{key}.xs?uuid="
            try:
                if requests.get(real_url,stream=True).status_code == 200:
                    flag = True
                    break
            except:
                pass
        
        if not flag:
            warnings.warn('直播CDN可能已经失效.')
        
        # if not isinstance(flow_cdn,str):
        #     flow_cdn = ''
        # resp = self.get_h5play_resp(cdn=flow_cdn)
        # live_data = resp["data"]
        # if type(live_data) is dict:
        #     real_url = f"{live_data.get('rtmp_url')}/{live_data.get('rtmp_live')}"
        
        # if requests.get(real_url,stream=True,headers=self.header).status_code != 200:
        #     warnings.warn(f'直播CDN可能已经失效. URL: {real_url}')
        
        return {
            'url': real_url
        }

if __name__ == '__main__':
    api = douyu('44198')
    print(api.onair())
