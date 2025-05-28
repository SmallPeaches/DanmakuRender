# 抖音的弹幕录制参考了 https://github.com/LyzenX/DouyinLiveRecorder 和 https://github.com/YunzhiYike/live-tool
# 抖音的弹幕录制参考了 https://github.com/biliup/biliup/blob/master/biliup/plugins/Danmaku/douyin.py
# 2024.6.23 抖音的弹幕录制参考了 https://github.com/SecPhases/DanmakuRender/commit/fd6d85afede5845274ad699bbcdf5db98e68977e

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

from DMR.LiveAPI.douyin import douyin_utils
from DMR.utils import split_url, cookiestr2dict, SimpleDanmaku, GiftDanmaku, EntryDanmaku
from .dy_pb2 import PushFrame, Response, ChatMessage, GiftMessage, MemberMessage
from .utils import DouyinDanmakuUtils

import aiohttp
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

logger = logging.getLogger(__name__)


def build_request_url(url: str) -> str:
    parsed_url = urlparse(url)
    existing_params = parse_qs(parsed_url.query)
    existing_params['aid'] = ['6383']
    existing_params['device_platform'] = ['web']
    existing_params['browser_language'] = ['zh-CN']
    existing_params['browser_platform'] = ['Win32']
    existing_params['browser_name'] = ['Mozilla']
    existing_params['browser_version'] = ['92.0.4515.159']
    new_query_string = urlencode(existing_params, doseq=True)
    new_url = urlunparse((
        parsed_url.scheme,
        parsed_url.netloc,
        parsed_url.path,
        parsed_url.params,
        new_query_string,
        parsed_url.fragment
    ))
    return new_url

class Douyin:
    heartbeat = b':\x02hb'
    heartbeatInterval = 10

    def __init__(self, douyin_dm_cookies:str=None) -> None:
        if not douyin_dm_cookies:
            self.headers = douyin_utils.get_headers()
        else:
            try:
                if douyin_dm_cookies.endswith('.json'):
                    with open(douyin_dm_cookies, 'r', encoding='utf-8') as f:
                        cookies = json.load(f)
                else:
                    cookies = cookiestr2dict(douyin_dm_cookies)
                self.headers = douyin_utils.get_headers(extra_cookies=cookies)
            except Exception as e:
                logger.exception(f'解析抖音cookies错误: {e}, 使用默认cookies.')
                self.headers = douyin_utils.get_headers()

    async def get_ws_info(self, url, **kwargs):
        async with aiohttp.ClientSession() as session:
            _, room_id = split_url(url)
            async with session.get(
                    build_request_url(f"https://live.douyin.com/webcast/room/web/enter/?web_rid={room_id}"),
                    headers=self.headers, timeout=5) as resp:
                room_info = json.loads(await resp.text())['data']['data'][0]
                USER_UNIQUE_ID = DouyinDanmakuUtils.get_user_unique_id()
                VERSION_CODE = 180800 # https://lf-cdn-tos.bytescm.com/obj/static/webcast/douyin_live/7697.782665f8.js -> a.ry
                WEBCAST_SDK_VERSION = "1.0.14-beta.0" # https://lf-cdn-tos.bytescm.com/obj/static/webcast/douyin_live/7697.782665f8.js -> ee.VERSION
                # logger.info(f"user_unique_id: {USER_UNIQUE_ID}")
                sig_params = {
                    "live_id": "1",
                    "aid": "6383",
                    "version_code": VERSION_CODE,
                    "webcast_sdk_version": WEBCAST_SDK_VERSION,
                    "room_id": room_info['id_str'],
                    "sub_room_id": "",
                    "sub_channel_id": "",
                    "did_rule": "3",
                    "user_unique_id": USER_UNIQUE_ID,
                    "device_platform": "web",
                    "device_type": "",
                    "ac": "",
                    "identity": "audience"
                }
                try:
                    signature = DouyinDanmakuUtils.get_signature(DouyinDanmakuUtils.get_x_ms_stub(sig_params))
                except Exception as e:
                    signature = 0
                    logger.exception('获取抖音弹幕签名失败:')
                    logger.exception(e)
                # logger.info(f"signature: {signature}")
                webcast5_params = {
                    "room_id": room_info['id_str'],
                    "compress": 'gzip',
                    # "app_name": "douyin_web",
                    "version_code": VERSION_CODE,
                    "webcast_sdk_version": WEBCAST_SDK_VERSION,
                    # "update_version_code": "1.0.14-beta.0",
                    # "cookie_enabled": "true",
                    # "screen_width": "1920",
                    # "screen_height": "1080",
                    # "browser_online": "true",
                    # "tz_name": "Asia/Shanghai",
                    # "cursor": "t-1718899404570_r-1_d-1_u-1_h-7382616636258522175",
                    # "internal_ext": "internal_src:dim|wss_push_room_id:7382580251462732598|wss_push_did:7344670681018189347|first_req_ms:1718899404493|fetch_time:1718899404570|seq:1|wss_info:0-1718899404570-0-0|wrds_v:7382616716703957597",
                    # "host": "https://live.douyin.com",
                    "live_id": "1",
                    "did_rule": "3",
                    # "endpoint": "live_pc",
                    # "support_wrds": "1",
                    "user_unique_id": USER_UNIQUE_ID,
                    # "im_path": "/webcast/im/fetch/",
                    "identity": "audience",
                    # "need_persist_msg_count": "15",
                    # "insert_task_id": "",
                    # "live_reason": "",
                    # "heartbeatDuration": "0",
                    "signature": signature,
                }
                wss_url = f"wss://webcast5-ws-web-lf.douyin.com/webcast/im/push/v2/?{'&'.join([f'{k}={v}' for k, v in webcast5_params.items()])}"
                url = build_request_url(wss_url)
                return url, []

    @classmethod
    def decode_msg(cls, data):
        wss_package = PushFrame()
        wss_package.ParseFromString(data)
        log_id = wss_package.logId
        decompressed = gzip.decompress(wss_package.payload)
        payload_package = Response()
        payload_package.ParseFromString(decompressed)

        ack = None
        if payload_package.needAck:
            obj = PushFrame()
            obj.payloadType = 'ack'
            obj.logId = log_id
            obj.payloadType = payload_package.internalExt
            ack = obj.SerializeToString()
        
        msgs = []
        for msg in payload_package.messagesList:
            now = datetime.now().timestamp()
            if msg.method == 'WebcastChatMessage':
                chatMessage = ChatMessage()
                chatMessage.ParseFromString(msg.payload)
                data = json_format.MessageToDict(chatMessage, preserving_proto_field_name=True)
                name = data['user']['nickName']
                content = data['content']
                msg_dict = SimpleDanmaku(
                    timestamp=now,
                    uname=name,
                    content=content,
                    dtype='danmaku',
                    color='ffffff'
                )
                # msg_dict = {"timestamp": now, "name": name, "content": content, "msg_type": "danmaku", "color": "ffffff"}
                # print(msg_dict)
            elif msg.method == 'WebcastMemberMessage':
                memberMessage = MemberMessage()
                memberMessage.ParseFromString(msg.payload)
                data = json_format.MessageToDict(memberMessage, preserving_proto_field_name=True)
                name = data['user']['nickName']
                msg_dict = EntryDanmaku(
                    timestamp=now,
                    uname=name,
                    content=f"{name}来了",
                    dtype='entry',
                    color='ffffff'
                )
            elif msg.method == 'WebcastGiftMessage':
                giftMessage = GiftMessage()
                giftMessage.ParseFromString(msg.payload)
                data = json_format.MessageToDict(giftMessage, preserving_proto_field_name=True)
                if 'combo' in data['gift'] and not 'repeatEnd' in data:
                  continue
                name = data['user']['nickName']
                diamondCount=str(data['gift']['diamondCount'])
                msg_dict = GiftDanmaku(
                    timestamp=now,
                    uname=name,
                    content=f"{name}送给主播{data['repeatCount']}个{data['gift']['name']}每个价值抖币{diamondCount}",
                    gift_name=data['gift']['name'],
                    gift_count=data['repeatCount'],
                    gift_price=diamondCount,
                    price_unit='抖币',
                    dtype='gift',
                    color='ffffff'
                )
            else:
                msg_dict = {"timestamp": now, "name": "", "content": "", "msg_type": "other", "raw_data": msg}
            msgs.append(msg_dict)
        
        return msgs, ack
