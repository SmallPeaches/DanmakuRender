from datetime import datetime
import json, re, select, random, traceback
import asyncio, aiohttp, zlib, brotli
from struct import pack, unpack

from DMR.utils import random_user_agent, SuperChatDanmaku, SimpleDanmaku
from DMR.LiveAPI.bilivideo_utils import encode_wbi, getWbiKeys
from .DMAPI import DMAPI

class Bilibili(DMAPI):
    heartbeat = b"\x00\x00\x00\x1f\x00\x10\x00\x01\x00\x00\x00\x02\x00\x00\x00\x01\x5b\x6f\x62\x6a\x65\x63\x74\x20\x4f\x62\x6a\x65\x63\x74\x5d"
    headers = {
        'accept': '*/*',
        'accept-encoding': 'gzip, deflate',
        'accept-language': 'zh-CN,zh;q=0.8,en-US;q=0.5,en;q=0.3',
        'user-agent': random_user_agent(),
        'origin': 'https://live.bilibili.com',
        'referer': 'https://live.bilibili.com'
    }
    interval = 30

    async def get_ws_info(url, **kwargs):
        url = "https://api.live.bilibili.com/room/v1/Room/room_init?id=" + url.split("/")[-1]
        reg_datas = []
        async with aiohttp.ClientSession(headers=Bilibili.headers) as session:
            async with session.get(url) as resp:
                room_json = await resp.json()
                room_id = room_json["data"]["room_id"]

        encoded_parms = encode_wbi(
            params = {
                "id": room_id,
                'type': 0,
                'web_location': 444.8,
            },
            wbi_img=getWbiKeys(),
        )
        async with aiohttp.ClientSession(headers=Bilibili.headers) as session:
            # 2025-06-28 B站新风控需要cookies中存在buvid3
            current_cookie = Bilibili.headers.get('cookie', '')
            if 'buvid3' not in current_cookie or 'buvid4' not in current_cookie:
                async with session.get("https://api.bilibili.com/x/frontend/finger/spi",timeout=5) as resp:
                    buvid_json = await resp.json()
                    current_cookie += f"buvid3={buvid_json['data']['b_3']};buvid4={buvid_json['data']['b_4']};"
                    Bilibili.headers['cookie'] = current_cookie
            async with session.get('https://api.live.bilibili.com/xlive/web-room/v1/index/getDanmuInfo',headers=Bilibili.headers, params=encoded_parms) as resp:
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
                        'SUPER_CHAT_MESSAGE': 'super_chat',  # 新增此行
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
                            msg['timestamp'] = j.get('info')[0][4]/1000
                            if j.get('info')[13] != r'{}':
                                emoticon_info = j.get('info')[0][13]
                                emoticon_url = emoticon_info['url']
                                emoticon_desc = j.get('info')[1]
                                msg["content"] = json.dumps({'url':emoticon_url,'desc':emoticon_desc},ensure_ascii=False)
                                msg['text'] = f'[{emoticon_desc}]'
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

                    elif msg["msg_type"] == "super_chat":  # 新增此部分
                        msg["name"] = j.get('data', {}).get('uinfo', {}).get('base', {}).get('name', '')
                        msg["content"] = j.get('data', {}).get('message', '')
                        msg["price"] = j.get('data', {}).get('price', 0)
                        msg["color"] = j.get('data', {}).get('background_color', 'ffffff')
                        try:
                            msg['timestamp'] = j.get('data', {}).get('ts')
                        except:
                            msg['timestamp'] = datetime.now().timestamp()  # 如果没有时间戳，则使用当前时间
                        msg = SuperChatDanmaku(**msg)  # 转换为 SuperChatDanmaku 对象
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
