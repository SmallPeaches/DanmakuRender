import json, re, select, random
from struct import pack, unpack

import aiohttp
from ..utils import *

# BGR Color
color_tab = {
    "2": "ffcc00", # '1e87f0' to 'ffcc00' light blue (lv.6)
    "3": "00ff66", # '7ac84b' to '00ff66' light green(teal) (lv.9)
    "4": "0066ff", # 'ff7f00' to '0066ff' orange (lv.15)
    "6": "7f44f6", # 'ff69b4' to '7f44f6' pink (lv.12)
    "5": "ff00cc", # '9b39f4' to 'ff00cc' purple (lv.18)
    "1": "2e2eff", # 'ff0000' to '2e2eff' red (lv.21)
}


class Douyu:
    heartbeat = b"\x14\x00\x00\x00\x14\x00\x00\x00\xb1\x02\x00\x00\x74\x79\x70\x65\x40\x3d\x6d\x72\x6b\x6c\x2f\x00"

    async def get_ws_info(url):
        reg_datas = []
        _, room_id = split_url(url)
        async with aiohttp.ClientSession() as session:
            async with session.get('https://m.douyu.com/' + str(room_id)) as resp:
                room_page = await resp.text()
                room_id = re.findall(r'rid":(\d*),"vipId', room_page)[0]

        data = f"type@=loginreq/roomid@={room_id}/"
        s = pack("i", 9 + len(data)) * 2
        s += b"\xb1\x02\x00\x00"  # 689
        s += data.encode("ascii") + b"\x00"
        reg_datas.append(s)
        data = f"type@=joingroup/rid@={room_id}/gid@=-9999/"
        s = pack("i", 9 + len(data)) * 2
        s += b"\xb1\x02\x00\x00"  # 689
        s += data.encode("ascii") + b"\x00"
        reg_datas.append(s)
        return "wss://danmuproxy.douyu.com:8506/", reg_datas

    def decode_msg(data):
        msgs = []
        for msg in re.findall(b"(type@=.*?)\x00", data):
            try:
                msg = msg.replace(b"@=", b'":"').replace(b"/", b'","')
                msg = msg.replace(b"@A", b"@").replace(b"@S", b"/")
                msg = json.loads((b'{"' + msg[:-2] + b"}").decode("utf8", "ignore"))
                msg["name"] = msg.get("nn", "")
                msg["content"] = msg.get("txt", "")
                msg["msg_type"] = {"dgb": "gift", "chatmsg": "danmaku", "uenter": "enter"}.get(
                    msg["type"], "other"
                )
                msg["color"] = color_tab.get(msg.get("col", "-1"), "ffffff")
                msgs.append(msg)
            except Exception as e:
                pass
        return msgs
