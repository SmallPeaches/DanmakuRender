# 抖音的弹幕录制参考了 https://github.com/LyzenX/DouyinLiveRecorder 和 https://github.com/YunzhiYike/live-tool

from datetime import datetime
import threading
import asyncio
import gzip
import re
import time
import re
import requests
import urllib
import json
import logging
import random
import websocket
from google.protobuf import json_format
from concurrent.futures import ThreadPoolExecutor, as_completed

from DMR.LiveAPI.douyin import douyin_cache
from .dy_pb2 import PushFrame, Response, ChatMessage


class Douyin:
    headers = douyin_cache.get_headers()
    def __init__(self, rid, q):
        self.ws = None
        self.stop_signal = False
        self.web_rid = rid
        self.q: asyncio.Queue = q

        if len(rid) == 19:
            self.real_rid = rid
        else:
            try:
                resp = self._get_response_douyin()
                self.real_rid = resp['data'][0]['id_str']
            except:
                raise Exception(f'解析抖音房间号{rid}错误.')
            
    def _get_response_douyin(self):
        url = 'https://live.douyin.com/webcast/room/web/enter/'
        params = {
            'web_rid': self.web_rid,
            'aid': '6383',
            'device_platform': 'web',
            'browser_language': 'zh-CN',
            'browser_platform': 'Win32',
            'browser_name': 'Edge',
            'browser_version': '104.0.1293.54',
        }
        text = requests.get(url, headers=self.headers, params=params, timeout=5).text
        data = json.loads(text)['data']
        return data
    
    def get_danmu_ws_url(self):
        # resp = self._get_response_douyin()
        user_unique_id = random.randint(1e19, 1e20)
        return f"wss://webcast3-ws-web-lf.douyin.com/webcast/im/push/v2/?app_name=douyin_web&version_code=180800&webcast_sdk_version=1.3.0&update_version_code=1.3.0&compress=gzip&internal_ext=internal_src:dim|wss_push_room_id:{self.real_rid}|wss_push_did:{user_unique_id}|dim_log_id:2023011316221327ACACF0E44A2C0E8200|fetch_time:${int(time.time())}123|seq:1|wss_info:0-1673598133900-0-0|wrds_kvs:WebcastRoomRankMessage-1673597852921055645_WebcastRoomStatsMessage-1673598128993068211&cursor=u-1_h-1_t-1672732684536_r-1_d-1&host=https://live.douyin.com&aid=6383&live_id=1&did_rule=3&debug=false&endpoint=live_pc&support_wrds=1&im_path=/webcast/im/fetch/&device_platform=web&cookie_enabled=true&screen_width=1228&screen_height=691&browser_language=zh-CN&browser_platform=Mozilla&browser_name=Mozilla&browser_version=5.0%20(Windows%20NT%2010.0;%20Win64;%20x64)%20AppleWebKit/537.36%20(KHTML,%20like%20Gecko)%20Chrome/100.0.4896.75%20Safari/537.36&browser_online=true&tz_name=Asia/Shanghai&identity=audience&room_id={self.real_rid}&heartbeatDuration=0&signature=00000000"

    async def start(self):
        self.ws = websocket.WebSocketApp(
            url=self.get_danmu_ws_url(),
            header=self.headers, 
            cookie=self.headers.get('cookie'),
            on_message=self._onMessage, 
            on_error=self._onError,
            on_open=self._onOpen,
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            task = executor.submit(self.ws.run_forever)
            while not self.stop_signal:
                if task.done() or self.ws.has_errored:
                    res = task.result()
                    raise RuntimeError(f'弹幕下载线程异常退出: {res}')
                
                await asyncio.sleep(10)

    async def stop(self):
        self.stop_signal = True
        logging.debug(f'Douyin {self.web_rid} danmaku client exit.')
        self.ws.close()

    def _onOpen(self, ws):
        t = threading.Thread(target=self._heartbeat, args=(ws,), daemon=True)
        t.start()

    def _onMessage(self, ws: websocket.WebSocketApp, message: bytes):
        wssPackage = PushFrame()
        wssPackage.ParseFromString(message)
        logid = wssPackage.logId
        decompressed = gzip.decompress(wssPackage.payload)
        payloadPackage = Response()
        payloadPackage.ParseFromString(decompressed)

        # 发送ack包
        if payloadPackage.needAck:
            obj = PushFrame()
            obj.payloadType = 'ack'
            obj.logId = logid
            obj.payloadType = payloadPackage.internalExt
            data = obj.SerializeToString()
            ws.send(data, websocket.ABNF.OPCODE_BINARY)
        # 处理消息
        for msg in payloadPackage.messagesList:
            now = datetime.now()
            if msg.method == 'WebcastChatMessage':
                chatMessage = ChatMessage()
                chatMessage.ParseFromString(msg.payload)
                data = json_format.MessageToDict(chatMessage, preserving_proto_field_name=True)
                name = data['user']['nickName']
                content = data['content']
                msg_dict = {"time": now, "name": name, "content": content, "msg_type": "danmaku", "color": "ffffff"}
                # print(msg_dict)
                self.q.put_nowait(msg_dict)
            else:
                msg_dict = {"time": now, "name": "", "content": "", "msg_type": "other", "raw_data": msg}
                # self.q.put_nowait(msg_dict)

    def _heartbeat(self, ws: websocket.WebSocketApp):
        while not self.stop_signal:
            obj = PushFrame()
            obj.payloadType = 'hb'
            data = obj.SerializeToString()
            ws.send(data, websocket.ABNF.OPCODE_BINARY)
            time.sleep(10)
            ws.has_errored

    def _onError(self, ws, error):
        raise error
