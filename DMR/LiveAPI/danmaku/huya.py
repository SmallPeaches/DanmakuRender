from datetime import datetime
import json, re, select, random
from struct import pack, unpack

import asyncio, aiohttp

from DMR.utils import split_url
from DMR.LiveAPI.tars import tarscore
from DMR.LiveAPI.huya_wup.wup_struct import EWebSocketCommandType
from DMR.LiveAPI.huya_wup.wup_struct.WebSocketCommand import HuyaWebSocketCommand
from DMR.LiveAPI.huya_wup.wup_struct.WSUserInfo import HuyaWSUserInfo
from DMR.utils import random_user_agent
from .DMAPI import DMAPI



class User(tarscore.struct):
    @staticmethod
    def readFrom(ios):
        return ios.read(tarscore.string, 2, False).decode("utf8")

class DColor(tarscore.struct):
    @staticmethod
    def readFrom(ios):
        return ios.read(tarscore.int32, 0, False)


class Huya(DMAPI):
    wss_url = 'wss://cdnws.api.huya.com/'
    heartbeat = b'\x00\x03\x1d\x00\x00\x69\x00\x00\x00\x69\x10\x03\x2c\x3c\x4c\x56\x08\x6f\x6e\x6c\x69\x6e\x65\x75' \
                b'\x69\x66\x0f\x4f\x6e\x55\x73\x65\x72\x48\x65\x61\x72\x74\x42\x65\x61\x74\x7d\x00\x00\x3c\x08\x00' \
                b'\x01\x06\x04\x74\x52\x65\x71\x1d\x00\x00\x2f\x0a\x0a\x0c\x16\x00\x26\x00\x36\x07\x61\x64\x72\x5f' \
                b'\x77\x61\x70\x46\x00\x0b\x12\x03\xae\xf0\x0f\x22\x03\xae\xf0\x0f\x3c\x42\x6d\x52\x02\x60\x5c\x60' \
                b'\x01\x7c\x82\x00\x0b\xb0\x1f\x9c\xac\x0b\x8c\x98\x0c\xa8\x0c '
    heartbeatInterval = 60
    headers = {
        'user-agent': random_user_agent(),
    }

    async def get_ws_info(url, **kwargs):
        reg_datas = []
        room_id = split_url(url)[1]
        async with aiohttp.ClientSession() as session:
            async with session.get(f'https://www.huya.com/{room_id}', headers=Huya.headers, timeout=5) as resp:
                room_page = await resp.text()
                uid = re.search(r"uid\":\"?(\d+)\"?", room_page).group(1)
                uid = int(uid)
                # tid = re.search(r"lChannelId\":\"?(\d+)\"?", room_page).group(1)
                # sid = re.search(r"lSubChannelId\":\"?(\d+)\"?", room_page).group(1)

        ws_user_info = HuyaWSUserInfo()
        ws_user_info.iUid = uid
        ws_user_info.bAnonymous = False
        ws_user_info.lGroupId = uid
        ws_user_info.lGroupType = 3
        oos = tarscore.TarsOutputStream()
        ws_user_info.writeTo(oos, ws_user_info)

        # b64data = base64.b64encode(oos.getBuffer())
        # print(b64data)

        ws_cmd = HuyaWebSocketCommand()
        ws_cmd.iCmdType = EWebSocketCommandType.EWSCmd_RegisterReq
        ws_cmd.vData = oos.getBuffer()
        oos = tarscore.TarsOutputStream()
        ws_cmd.writeTo(oos, ws_cmd)

        # oos = tarscore.TarsOutputStream()
        # oos.write(tarscore.int64, 0, uid)
        # oos.write(tarscore.boolean, 1, False)  # Anonymous
        # oos.write(tarscore.string, 2, "")  # sGuid
        # oos.write(tarscore.string, 3, "")
        # oos.write(tarscore.int64, 4, 0)  # tid
        # oos.write(tarscore.int64, 5, 0)  # sid
        # oos.write(tarscore.int64, 6, uid)
        # oos.write(tarscore.int64, 7, 3)

        # b64data = base64.b64encode(oos.getBuffer())
        # print(b64data)

        # wscmd = tarscore.TarsOutputStream()
        # wscmd.write(tarscore.int32, 0, 1)
        # wscmd.write(tarscore.bytes, 1, oos.getBuffer())

        # b64data = base64.b64encode(oos.getBuffer())
        # print(b64data)

        reg_datas.append(oos.getBuffer())

        return Huya.wss_url, reg_datas

    def decode_msg(data):
        msgs = []
        try:
            name = ""
            content = ""
            color = 16777215
            msgs = []
            ios = tarscore.TarsInputStream(data)
            if ios.read(tarscore.int32, 0, False) == 7:
                ios = tarscore.TarsInputStream(ios.read(tarscore.bytes, 1, False))
                if ios.read(tarscore.int64, 1, False) == 1400:
                    ios = tarscore.TarsInputStream(ios.read(tarscore.bytes, 2, False))
                    name = ios.read(User, 0, False)  # username
                    content = ios.read(tarscore.string, 3, False).decode("utf8")  # content
                    color = ios.read(DColor, 6, False)  # danmaku color
                    if color == -1:
                        color = 16777215
                    if name != "":
                        msg = {"name": name, "color": f"{color:06x}", "content": content, "msg_type": "danmaku"}
                        msgs.append(msg)
            else:
                msg = {"name": "", "content": "", "msg_type": "other","raw_data": data}
                msgs.append(msg)
        except Exception as e:
            # print(e)
            pass

        return msgs
