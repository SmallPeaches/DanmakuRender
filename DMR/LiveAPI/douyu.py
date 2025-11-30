# 获取斗鱼直播间的真实流媒体地址，默认最高画质
# 使用 https://github.com/wbt5/real-url/issues/185 中两位大佬@wjxgzz @4bbu6j5885o3gpv6ss8找到的的CDN，在此感谢！
# 2025.11.30 更新，https://github.com/biliup/biliup/blob/master/biliup/plugins/douyu.py
import hashlib
import json
import logging
import random
import re
import threading
import time
import requests

from typing import Any, Union
from urllib.parse import parse_qs, quote, urlencode

from DMR.utils import random_user_agent, match1

try:
    from .BaseAPI import BaseAPI
except ImportError:
    from BaseAPI import BaseAPI

DOUYU_DEFAULT_DID = "10000000000000000000000000001501"
DOUYU_WEB_DOMAIN = "www.douyu.com"
DOUYU_PLAY_DOMAIN = "playweb.douyucdn.cn"
DOUYU_MOBILE_DOMAIN = "m.douyu.com"


logger = logging.getLogger(__name__)

class douyu(BaseAPI):
    fake_headers = BaseAPI._default_header.copy()
    
    def __init__(self,rid:str) -> None:
        self.rid = rid

        self.sess = requests.Session()
        self.fake_headers['referer'] = f"https://{DOUYU_WEB_DOMAIN}"
        self.stream_headers = self.fake_headers.copy()
        res = self.sess.get('https://m.douyu.com/'+str(rid),timeout=5).text

        try:
            self.rid = re.findall(r'rid":(\d*),"vipId', res)[0]
        except:
            raise Exception('房间号错误')
        
        self.__js_runable = True
        self.plugin_msg = f"douyu-{self.rid}"
        self.__req_query = {
            'cdn': 'hw-h5',
            'rate': '0',
            'ver': '219032101',
            'iar': '0', # ispreload? 1: 忽略 rate 参数，使用默认画质
            'ive': '0', # rate? 0~19 时、19~24 时请求数 >=3 为真
            'rid': self.rid,
            'hevc': '0',
            'fa': '0', # isaudio
            'sov': '0', # use wasm?
        }
    
    def __del__(self):
        self.sess.close()

    @staticmethod
    def md5(data):
        return hashlib.md5(data.encode('utf-8')).hexdigest()

    def get_resp_new(self):
        resp = self.sess.get(f'https://www.douyu.com/betard/{self.rid}', headers=self.fake_headers, timeout=5).json()
        return resp
    
    def is_available(self) -> bool:
        return True

    def onair(self) -> bool:
        resp = self.get_resp_new()
        videoloop = resp['room']['videoLoop']
        show_status = resp['room']['show_status']
        if show_status == 1 and videoloop == 0:
            return True
        else:
            return False

    def get_info(self):
        """
        return: title,uname,face_url,keyframe_url
        """
        resp = self.get_resp_new()
        if resp['room']['isVip'] == 1:
            with DouyuUtils._lock:
                DouyuUtils.VipRoom.add(self.rid)
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
    
    def aget_sign(self, rid: Union[str, int]) -> dict[str, Any]:
        '''
        :param rid: 房间号
        :return: sign dict
        '''
        if not self.__js_runable:
            raise RuntimeError("jsengine not found")
        try:
            import jsengine
            ctx = jsengine.jsengine()
            js_enc = (
                self.sess.get(f'https://www.douyu.com/swf_api/homeH5Enc?rids={rid}',
                                 headers=self.fake_headers)
            ).json()['data'][f'room{rid}']
            js_enc = js_enc.replace('return eval', 'return [strc, vdwdae325w_64we];')

            sign_fun, sign_v = ctx.eval(f'{js_enc};ub98484234();') # type: ignore

            tt = str(int(time.time()))
            did = hashlib.md5(tt.encode('utf-8')).hexdigest()
            rb = hashlib.md5(f"{rid}{did}{tt}{sign_v}".encode('utf-8')).hexdigest()
            sign_fun = sign_fun.rstrip(';').replace("CryptoJS.MD5(cb).toString()", f'"{rb}"')
            sign_fun += f'("{rid}","{did}","{tt}");'

            params = parse_qs(ctx.eval(sign_fun))

        except Exception as e:
            logger.exception(f"{self.plugin_msg}: 获取签名参数异常")
            raise e
        return params
    
    def get_web_play_info(
        self,
        room_id: Union[str, int],
        req_query: dict[str, Any],
        req_method: str = "POST",
        did: str = DOUYU_DEFAULT_DID,
    ) -> dict[str, Any]:
        '''
        :param room_id: 房间号
        :param req_query: 请求参数
        :param req_method: 请求方法。可选 GET, POST（默认）
        :param did: douyuid
        :return: PlayInfo
        '''
        if type(room_id) == int:
            room_id = str(room_id)
        if not self.__js_runable:
            s = DouyuUtils.sign(type="stream", ts=int(time.time()), did=did, rid=room_id)
            logger.debug(f"{self.plugin_msg}: 免 JSEngine 签名参数 {s}")
            auth_param = {
                "enc_data": s['key']['enc_data'],
                "tt": s['ts'],
                "did": did,
                "auth": s['auth'],
            }
            req_query.update(auth_param)
        else:
            s = self.aget_sign(room_id)
            # logger.debug(f"{self.plugin_msg}: JSEngine 签名参数 {s}")
            req_query.update(s)
        api_ver = "V1" if not self.__js_runable else ""
        is_vip = room_id in DouyuUtils.VipRoom # 非 vip room 需要 e 参数，部分直播间可直接请求 hs-h5
        req_method = "GET" if is_vip and not api_ver else "POST"
        path = f"/lapi/live/getH5Play{api_ver}/{room_id}"
        url = f"https://{DOUYU_PLAY_DOMAIN}{path}" if req_method == "GET" else f"https://{DOUYU_WEB_DOMAIN}{path}"
        # url += f"?{urlencode(req_query, doseq=True, encoding='utf-8')}"
        if req_method == "GET":
            rsp = self.sess.get(
                url,
                headers=self.fake_headers,
                params=req_query
            )
        else:
            rsp = self.sess.post(
                url,
                headers={**self.fake_headers, 'user-agent': DouyuUtils.UserAgent},
                params=req_query, # V1 接口需使用查询参数
                data=req_query # 原接口需使用请求体
            )
        rsp.raise_for_status()
        play_data = json.loads(rsp.text)
        if not play_data:
            raise RuntimeError(f"获取播放信息失败 {rsp}")
        if play_data['error'] != 0 or not play_data.get('data', {}):
            raise ValueError(f"获取播放信息错误 {str(play_data)}")
        return play_data['data']


    def get_mobile_play_info(
        self,
        req_query: dict[str, Any]
    ) -> dict[str, Any]:
        if not self.__js_runable:
            raise RuntimeError("jsengine not found")
        url = f'https://{DOUYU_MOBILE_DOMAIN}/api/room/ratestream'
        # elif preview:
        #     c_time_str = str(time.time_ns())
        #     url = f'https://playweb.douyucdn.cn/lapi/live/hlsH5Preview/{room_id}?{c_time_str[:18]}'
        #     data = {
        #         'rid': self.__room_id,
        #         'did': data.get('did', ["10000000000000000000000000001501"])[0],
        #     }
        #     req_headers.update({
        #         'Rid': self.__room_id,
        #         'Time': c_time_str[:13],
        #         'Auth': hashlib.md5(f"{self.__room_id}{c_time_str[:13]}".encode('utf-8')).hexdigest(),
        #     })
        rsp = self.sess.post(
            url,
            headers={**self.fake_headers, 'user-agent': random_user_agent('mobile')},
            data=req_query
        )
        rsp.raise_for_status()
        play_data = json.loads(rsp.text)
        if play_data['code'] != 0:
            raise ValueError(f"获取播放信息错误 {str(play_data)}")
        return play_data['data']

    def parse_stream_info(self, url) -> tuple[str, str, dict]:
        '''
        解析推流信息
        '''
        def get_tx_app_name(rtmp_url) -> str:
            '''
            获取腾讯云推流应用名
            '''
            host = rtmp_url.split('//')[1].split('/')[0]
            app_name = rtmp_url.split('/')[-1]
            # group 按顺序排序
            i = match1(host, r'.+(sa|3a|1a|3|1)')
            if i:
                if i == "sa":
                    i = "1"
                return f"dyliveflv{i}"
            return app_name
        list = url.split('?')
        query = {k: v[0] for k, v in parse_qs(list[1]).items()}
        stream_id = list[0].split('/')[-1].split('.')[0].split('_')[0]
        rtmp_url = list[0].split(stream_id)[0]
        return get_tx_app_name(rtmp_url[:-1]), stream_id, query


    def build_tx_url(self, tx_app_name, stream_id, query) -> str:
        '''
        构建腾讯CDN URL
        return: tx_url
        '''
        origin = query.get('origin', 'unknown')
        if origin not in ['tct', 'hw', 'dy']:
            '''
            dy: 斗鱼自建
            tct: 腾讯云
            hw: 华为云
            '''
            raise ValueError(f"当前流来源 {origin} 不支持切换为腾讯云推流")
        elif origin == 'dy':
            logger.warning(f"{self.plugin_msg}: 当前流来源 {origin} 可能不存在腾讯云流")
        tx_host = "tc-tct.douyucdn2.cn"
        tx_url = f"https://{tx_host}/{tx_app_name}/{stream_id}.flv?%s"
        m_play_info = self.get_mobile_play_info(self.__req_query)
        _, _, m_query = self.parse_stream_info(m_play_info['url'])
        # 需要移动端的宽松验证 token
        m_query.pop('vhost', None)
        query.update({
            'fcdn': 'tct',
            **m_query,
        })
        query = urlencode(query, doseq=True, encoding='utf-8')
        return tx_url % query


    def build_hs_url(self, url: str, is_tct: bool = False) -> tuple[str, str]:
        '''
        构建火山CDN URL
        :param url: 腾讯云 URL
        :param is_tct: 是否为 tct 流
        return: fake_hs_host, hs_cname_url
        '''
        tx_app_name, stream_id, query = self.parse_stream_info(url)
        # 必须从 tct 转 hs
        if not is_tct:
            url = self.build_tx_url(tx_app_name, stream_id, query)
        tx_host = url.split('//')[1].split('/')[0]
        hs_host = f"{tx_app_name.replace('dyliveflv', 'huos')}.douyucdn2.cn"
        hs_host = hs_host.replace('huos1.', 'huosa.')
        encoded_url = quote(url, safe='')
        query.update({
            'fp_user_url': encoded_url,
            'vhost': tx_host,
            'domain': tx_host,
        })
        query = urlencode(query, doseq=True, encoding='utf-8')
        hs_cname_host = "douyu-pull.s.volcfcdndvs.com"
        hs_cname_url = f"http://{hs_cname_host}/live/{stream_id}.flv?{query}"
        return (hs_host, hs_cname_url)

    def get_stream_urls(self, stream_cdn=None, **kwargs) -> str:
        for _ in range(2): # 允许多重试一次以剔除 scdn
            # self.__js_runable = False
            try:
                play_info = self.get_web_play_info(self.rid, self.__req_query)
                if play_info['rtmp_cdn'].startswith('scdn'):
                    new_cdn = play_info['cdnsWithName'][-1]['cdn']
                    logger.debug(f"{self.plugin_msg}: 回避 scdn 为 {new_cdn}")
                    self.__req_query['cdn'] = new_cdn
                    continue
            except (RuntimeError, ValueError) as e:
                logger.warning(f"{self.plugin_msg}: {e}")

        raw_stream_url = f"{play_info['rtmp_url']}/{play_info['rtmp_live']}"

        # HACK: 构造 hs-h5 cdn 直播流链接
        # self.douyu_cdn = 'hs-h5'
        # 修改：当用户选择 hs-h5 时，允许通过配置强制构造 hs 链接（即使 play_info 已经返回 hs-h5）
        if stream_cdn == 'hs-h5':
            need_build = play_info['rtmp_cdn'] != 'hs-h5'
            if need_build:
                if not self.__js_runable:
                    logger.warning(f"{self.plugin_msg}: 未找到 jsengine，无法构建 hs-h5 链接")
                is_tct = play_info['rtmp_cdn'] == 'tct-h5'
                try:
                    fake_host, cname_url = self.build_hs_url(raw_stream_url, is_tct)
                except:
                    logger.exception(f"{self.plugin_msg}: 构建 hs-h5 链接失败")
                else:
                    raw_stream_url = cname_url
                    self.stream_headers['Host'] = fake_host
            else:
                logger.debug(f"{self.plugin_msg}: play_info 返回的 rtmp_cdn 已是 hs-h5，且未开启 douyu_force_hs，跳过构建 hs-h5")
        return [{
            'stream_url': raw_stream_url,
        }]
    
    def get_stream_header(self):
        return self.stream_headers
    

class DouyuUtils:
    '''
    逆向实现 //shark2.douyucdn.cn/front-publish/live-master/js/player_first_preload_stream/player_first_preload_stream_6cd7aab.js
    '''
    WhiteEncryptKey: dict = dict()
    VipRoom: set = set()
    # enc_data 会校验 UA
    UserAgent: str = ""
    # 防止并发访问
    _lock = threading.Lock()
    _update_key_event: threading.Event = None

    @staticmethod
    def is_key_valid():
        return (
            bool(DouyuUtils.WhiteEncryptKey) # Key 存在
            and
            DouyuUtils.WhiteEncryptKey.get('expire_at', 0) > int(time.time()) # Key 过期
        )

    @staticmethod
    def update_key(
        domain: str = DOUYU_WEB_DOMAIN,
        did: str = DOUYU_DEFAULT_DID
    ) -> bool:
        # single-flight
        with DouyuUtils._lock:
            if DouyuUtils._update_key_event is not None:
                evt = DouyuUtils._update_key_event
                leader = False
            else:
                DouyuUtils._update_key_event = threading.Event()
                evt = DouyuUtils._update_key_event
                leader = True
        if not leader:
            evt.wait()
            return DouyuUtils.is_key_valid()

        try:
            # 防风控
            with DouyuUtils._lock:
                DouyuUtils.UserAgent = random_user_agent()

            rsp = requests.get(
                f"https://{domain}/wgapi/livenc/liveweb/websec/getEncryption",
                params={"did": did},
                headers={
                    "User-Agent": DouyuUtils.UserAgent
                },
            )
            rsp.raise_for_status()
            data = json.loads(rsp.text)
            if data['error'] != 0:
                raise RuntimeError(f'getEncryption error: code={data["error"]}, msg={data["msg"]}')
            data['data']['cpp']['expire_at'] = int(time.time()) + 86400

            with DouyuUtils._lock:
                DouyuUtils.WhiteEncryptKey = data['data']
            return True
        except Exception:
            logger.exception(f"{DouyuUtils.__name__}: 获取加密密钥失败")
            return False
        finally:
            with DouyuUtils._lock:
                if DouyuUtils._update_key_event is not None:
                    DouyuUtils._update_key_event.set()
                    DouyuUtils._update_key_event = None


    @staticmethod
    def sign(
        type: str, # unused
        ts: int,
        did: str,
        rid: Union[str, int],
    ) -> dict[str, Any]:
        '''
        :param type: unused
        :param ts: 10位Unix时间戳
        :param did: douyuid
        :param rid: 房间号
        '''
        if not rid:
            raise ValueError("rid is None")

        # 确保密钥有效
        for _ in range(2): # 重试两次
            if not DouyuUtils.is_key_valid():
                if not (DouyuUtils.update_key()):
                    continue
            break
        else:
            raise RuntimeError("获取加密密钥失败")

        if not type:
            type = "stream"
        if not ts:
            ts = int(time.time())
        if not did:
            did = DOUYU_DEFAULT_DID

        rand_str = DouyuUtils.WhiteEncryptKey['rand_str']
        enc_time = DouyuUtils.WhiteEncryptKey['enc_time']
        key = DouyuUtils.WhiteEncryptKey['key']
        is_special = DouyuUtils.WhiteEncryptKey['is_special']
        key_data = {k: v for k, v in DouyuUtils.WhiteEncryptKey.items() if k not in ["cpp"]}

        secret = rand_str
        salt = "" if is_special else f"{rid}{ts}"
        for _ in range(enc_time):
            secret = hashlib.md5(f"{secret}{key}".encode('utf-8')).hexdigest()
        auth = hashlib.md5(f"{secret}{key}{salt}".encode('utf-8')).hexdigest()

        return {
            'key': key_data,
            'alg_ver': "1.0",
            "key_ver": "",
            'auth': auth,
            'ts': ts,
        }
