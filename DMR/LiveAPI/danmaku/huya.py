from datetime import datetime
import json, re, select, random
from struct import pack, unpack

import asyncio, aiohttp

from DMR.LiveAPI.utils import split_url
from .tars import tarscore
from .huya_utils import WebSocketCommand, EWebSocketCommandType, WSPushMessage, MessageNotice, WSPushMessage_V2
from .DMAPI import DMAPI

class Huya(DMAPI):
    heartbeat = b"\x00\x03\x1d\x00\x00\x69\x00\x00\x00\x69\x10\x03\x2c\x3c\x4c\x56\x08\x6f\x6e\x6c\x69\x6e\x65\x75\x69\x66\x0f\x4f\x6e\x55\x73\x65\x72\x48\x65\x61\x72\x74\x42\x65\x61\x74\x7d\x00\x00\x3c\x08\x00\x01\x06\x04\x74\x52\x65\x71\x1d\x00\x00\x2f\x0a\x0a\x0c\x16\x00\x26\x00\x36\x07\x61\x64\x72\x5f\x77\x61\x70\x46\x00\x0b\x12\x03\xae\xf0\x0f\x22\x03\xae\xf0\x0f\x3c\x42\x6d\x52\x02\x60\x5c\x60\x01\x7c\x82\x00\x0b\xb0\x1f\x9c\xac\x0b\x8c\x98\x0c\xa8\x0c"

    async def get_ws_info(url):
        reg_datas = []
        url = "https://m.huya.com/" + split_url(url)[1]
        headers = {
            "user-agent": "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/79.0.3945.88 Mobile Safari/537.36"
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                room_page = await resp.text()
                # print(room_page)
                m = re.search(r"window.HNF_GLOBAL_INIT *= *(\{.+?\})\s*</script>", room_page, re.MULTILINE)
                j = json.loads(m.group(1))
                ayyuid = j["roomInfo"]["tProfileInfo"]["lUid"]
                # tid = j["roomInfo"]["tLiveInfo"]["tLiveStreamInfo"]["vStreamInfo"]["value"][0]["lChannelId"]
                # sid = j["roomInfo"]["tLiveInfo"]["tLiveStreamInfo"]["vStreamInfo"]["value"][0]["lSubChannelId"]

                # print(ayyuid)
                # print(tid)
                # print(sid)

        # a = tarscore.string

        l = tarscore.vctclass(tarscore.string)()
        l.append(f"live:{ayyuid}")
        l.append(f"chat:{ayyuid}")
        oos = tarscore.TarsOutputStream()
        oos.write(tarscore.vctclass(tarscore.string), 0, l)
        oos.write(tarscore.string, 1, "")

        # oos.write(tarscore.int64, 0, int(ayyuid))
        # oos.write(tarscore.boolean, 1, True)  # Anonymous
        # oos.write(tarscore.string, 2, "")  # sGuid
        # oos.write(tarscore.string, 3, "")
        # oos.write(tarscore.int64, 4, int(tid))
        # oos.write(tarscore.int64, 5, int(sid))
        # oos.write(tarscore.int64, 6, 0)
        # oos.write(tarscore.int64, 7, 0)


        wscmd = tarscore.TarsOutputStream()
        wscmd.write(tarscore.int32, 0, 16)
        # wscmd.write(tarscore.int32, 0, 1)
        wscmd.write(tarscore.bytes, 1, oos.getBuffer())

        reg_datas.append(wscmd.getBuffer())
        return "wss://cdnws.api.huya.com/", reg_datas

    def decode_msg(data):
        stream = tarscore.TarsInputStream(data)
        command = WebSocketCommand()
        command.readFrom(stream)

        name = ""
        content = ""
        msgs = []

        try:
            if command.iCmdType == EWebSocketCommandType.EWSCmdS2C_MsgPushReq:
                stream = tarscore.TarsInputStream(command.vData)
                msg = WSPushMessage()
                msg.readFrom(stream)
                if msg.iUri == 1400:
                    stream = tarscore.TarsInputStream(msg.sMsg)
                    msg = MessageNotice()
                    msg.readFrom(stream)
            
                    name = msg.tUserInfo.sNickName.decode("utf-8")
                    content = msg.sContent.decode("utf-8")
                    color = msg.tBulletFormat.iFontColor
                    if color == -1:
                        color = 16777215
                    msg = {"name": name, "color": f"{color:06x}", "content": content, "msg_type": "danmaku"}
                    msgs.append(msg)        
            elif command.iCmdType == EWebSocketCommandType.EWSCmdS2C_MsgPushReq_V2:
                stream = tarscore.TarsInputStream(command.vData)
                msgv2 = WSPushMessage_V2()
                msgv2.readFrom(stream)
                for msg in msgv2.vMsgItem:
                    if msg.iUri == 1400:
                        stream = tarscore.TarsInputStream(msg.sMsg)
                        msg = MessageNotice()
                        msg.readFrom(stream)
                
                        name = msg.tUserInfo.sNickName.decode("utf-8")
                        content = msg.sContent.decode("utf-8")
                        color = msg.tBulletFormat.iFontColor
                        if color == -1:
                            color = 16777215
                        msg = {"name": name, "color": f"{color:06x}", "content": content, "msg_type": "danmaku"}
                        msgs.append(msg)
            else:
                msg = {"name": "", "content": "", "msg_type": "other","raw_data": data}
                msgs.append(msg)
        except Exception as e:
            # print(e)
            pass

        return msgs
