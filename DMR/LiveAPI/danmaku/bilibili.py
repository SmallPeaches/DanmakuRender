from datetime import datetime
import json, re, select, random, traceback
import asyncio, aiohttp, zlib, brotli
from struct import pack, unpack

from .DMAPI import DMAPI

class Bilibili(DMAPI):
    heartbeat = b"\x00\x00\x00\x1f\x00\x10\x00\x01\x00\x00\x00\x02\x00\x00\x00\x01\x5b\x6f\x62\x6a\x65\x63\x74\x20\x4f\x62\x6a\x65\x63\x74\x5d"
    headers = {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Encoding': 'gzip, deflate',
        'Accept-Language': 'zh-CN,zh;q=0.8,en-US;q=0.5,en;q=0.3',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.159 Safari/537.36',
        'Referer': 'https://live.bilibili.com/',
    }
    interval = 30

    async def get_ws_info(url, **kwargs):
        url = "https://api.live.bilibili.com/room/v1/Room/room_init?id=" + url.split("/")[-1]
        reg_datas = []
        async with aiohttp.ClientSession(headers=Bilibili.headers) as session:
            async with session.get(url) as resp:
                room_json = await resp.json()
                room_id = room_json["data"]["room_id"]

        async with aiohttp.ClientSession(headers=Bilibili.headers) as session:
            async with session.get(f'https://api.live.bilibili.com/xlive/web-room/v1/index/getDanmuInfo?id={room_id}') as resp:
                room_json = await resp.json()
                token = room_json['data']['token']
            
        data = json.dumps({
            "roomid": room_id, 
            "uid": 0, 
            "protover": 3, 
            "key": token, 
            "type":2, 
            "platform": "web",
        },separators=(",", ":"),).encode("ascii")
        data = (
            pack(">i", len(data) + 16)
            + pack(">h", 16)
            + pack(">h", 1)
            + pack(">i", 7)
            + pack(">i", 1)
            + data
        )
        reg_datas.append(data)

        return "wss://broadcastlv.chat.bilibili.com/sub", reg_datas
    
    def decode_msg(data):
        dm_list = []
        msgs = []

        def decode_packet(packet_data):
            dm_list = []
            while True:
                try:
                    packet_len, header_len, ver, op, seq = unpack('!IHHII', packet_data[0:16])
                except Exception:
                    break
                if len(packet_data) < packet_len:
                    break

                if ver == 2:
                    dm_list.extend(decode_packet(zlib.decompress(packet_data[16:packet_len])))\
                # version3: 参考https://github.com/biliup/biliup/blob/master/biliup/plugins/Danmaku/bilibili.py
                elif ver == 3:
                    dm_list.extend(decode_packet(brotli.decompress(packet_data[16:packet_len])))
                elif ver == 0 or ver == 1:
                    dm_list.append({
                        'type': op,
                        'body': packet_data[16:packet_len]
                    })
                else:
                    break

                if len(packet_data) == packet_len:
                    break
                else:
                    packet_data = packet_data[packet_len:]
            return dm_list

        dm_list = decode_packet(data)

        for i, dm in enumerate(dm_list):
            try:
                msg = {}
                if dm.get('type') == 5:
                    j = json.loads(dm.get('body'))
                    msg['msg_type'] = {
                        'SEND_GIFT': 'gift',
                        'DANMU_MSG': 'danmaku',
                        'WELCOME': 'enter',
                        'NOTICE_MSG': 'broadcast',
                        # 'LIVE_INTERACTIVE_GAME': 'interactive_danmaku'  # 互动弹幕，与普通弹幕重复，已被弃用(#121)
                    }.get(j.get('cmd'), 'other')

                    if 'DANMU_MSG' in j.get('cmd'):
                        msg["msg_type"] = "danmaku"

                    if msg["msg_type"] == "danmaku":
                        msg["name"] = j.get("info", ["", "", ["", ""]])[2][1] or j.get(
                            "data", {}
                        ).get("uname", "")
                        msg["color"] = f"{j.get('info', [[0, 0, 0, 16777215]])[0][3]:06x}"
                        msg["content"] = j.get("info")[1]
                        try:
                            msg['time'] = datetime.fromtimestamp(j.get('info')[0][4]/1000)
                            if j.get('info')[13] != r'{}':
                                emoticon_info = j.get('info')[0][13]
                                emoticon_url = emoticon_info['url']
                                emoticon_desc = j.get('info')[1]
                                msg["content"] = json.dumps({'url':emoticon_url,'desc':emoticon_desc},ensure_ascii=False)
                                msg['msg_type'] = 'emoticon'
                        except:
                            pass

                    elif msg['msg_type'] == 'interactive_danmaku':
                        msg["msg_type"] = "danmaku"
                        msg['name'] = j.get('data', {}).get('uname', '')
                        msg['content'] = j.get('data', {}).get('msg', '')
                        msg["color"] = 'ffffff'
                        
                    elif msg["msg_type"] == "broadcast":
                        msg["type"] = j.get("msg_type", 0)
                        msg["roomid"] = j.get("real_roomid", 0)
                        msg["content"] = j.get("msg_common", "none")
                        msg["raw"] = j

                    else:
                        msg["content"] = j
                else:
                    msg = {"name": "", "content": dm.get('body'), "msg_type": "other"}
                msgs.append(msg)
            except Exception as e:
                # traceback.print_exc()
                # print(e)
                pass

        return msgs
