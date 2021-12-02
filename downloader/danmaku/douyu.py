import json, re, select, random
from struct import pack, unpack
import asyncio, aiohttp

color_tab = {
    "2": "1e87f0",
    "3": "7ac84b",
    "4": "ff7f00",
    "6": "ff69b4",
    "5": "9b39f4",
    "1": "ff0000",
}


class Douyu:
    heartbeat = b"\x14\x00\x00\x00\x14\x00\x00\x00\xb1\x02\x00\x00\x74\x79\x70\x65\x40\x3d\x6d\x72\x6b\x6c\x2f\x00"

    async def get_ws_info(url):
        reg_datas = []
        room_id = url.split("/")[-1]
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
