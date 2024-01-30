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
from DMR.utils import split_url
from .dy_pb2 import PushFrame, Response, ChatMessage

# 抖音的弹幕录制参考了 https://github.com/biliup/biliup/blob/master/biliup/plugins/Danmaku/douyin.py
import aiohttp
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

def build_request_url(url: str) -> str:
    parsed_url = urlparse(url)
    existing_params = parse_qs(parsed_url.query)
    existing_params['aid'] = ['6383']
    existing_params['device_platform'] = ['web']
    existing_params['browser_language'] = ['zh-CN']
    existing_params['browser_platform'] = ['Win32']
    existing_params['browser_name'] = ['Chrome']
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

    @staticmethod
    async def get_ws_info(url):
        async with aiohttp.ClientSession() as session:
            _, room_id = split_url(url)
            async with session.get(
                    build_request_url(f"https://live.douyin.com/webcast/room/web/enter/?web_rid={room_id}"),
                    headers=douyin_cache.get_headers(), timeout=5) as resp:
                room_info = json.loads(await resp.text())['data']['data'][0]
                url = build_request_url(
                    f"wss://webcast3-ws-web-lf.douyin.com/webcast/im/push/v2/?room_id={room_info['id_str']}&compress=gzip&signature=00000000")
                return url, []

    @staticmethod
    def decode_msg(data):
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
            now = datetime.now()
            if msg.method == 'WebcastChatMessage':
                chatMessage = ChatMessage()
                chatMessage.ParseFromString(msg.payload)
                data = json_format.MessageToDict(chatMessage, preserving_proto_field_name=True)
                name = data['user']['nickName']
                content = data['content']
                msg_dict = {"time": now, "name": name, "content": content, "msg_type": "danmaku", "color": "ffffff"}
                # print(msg_dict)
            else:
                msg_dict = {"time": now, "name": "", "content": "", "msg_type": "other", "raw_data": msg}
            msgs.append(msg_dict)
        
        return msgs, ack
