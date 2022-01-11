import json, re, select, random, traceback
from struct import pack, unpack

import asyncio, aiohttp, zlib


class Bilibili:
    heartbeat = b"\x00\x00\x00\x1f\x00\x10\x00\x01\x00\x00\x00\x02\x00\x00\x00\x01\x5b\x6f\x62\x6a\x65\x63\x74\x20\x4f\x62\x6a\x65\x63\x74\x5d"

    async def get_ws_info(url):
        url = "https://api.live.bilibili.com/room/v1/Room/room_init?id=" + url.split("/")[-1]
        reg_datas = []
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                room_json = json.loads(await resp.text())
                room_id = room_json["data"]["room_id"]
                data = json.dumps(
                    {"roomid": room_id, "uid": int(1e14 + 2e14 * random.random()), "protover": 2},
                    separators=(",", ":"),
                ).encode("ascii")
                data = (
                    pack(">i", len(data) + 16)
                    + b"\x00\x10\x00\x01"
                    + pack(">i", 7)
                    + pack(">i", 1)
                    + data
                )
                reg_datas.append(data)

        return "wss://broadcastlv.chat.bilibili.com/sub", reg_datas

    def decode_msg(data):
        dm_list_compressed = []
        dm_list = []
        ops = []
        msgs = []
        # print(data)
        while True:
            try:
                packetLen, headerLen, ver, op, seq = unpack("!IHHII", data[0:16])
            except Exception as e:
                break
            if len(data) < packetLen:
                break
            if ver == 1 or ver == 0:
                ops.append(op)
                dm_list.append(data[16:packetLen])
            elif ver == 2:
                dm_list_compressed.append(data[16:packetLen])
            if len(data) == packetLen:
                data = b""
                break
            else:
                data = data[packetLen:]

        for dm in dm_list_compressed:
            d = zlib.decompress(dm)
            while True:
                try:
                    packetLen, headerLen, ver, op, seq = unpack("!IHHII", d[0:16])
                except Exception as e:
                    break
                if len(d) < packetLen:
                    break
                ops.append(op)
                dm_list.append(d[16:packetLen])
                if len(d) == packetLen:
                    d = b""
                    break
                else:
                    d = d[packetLen:]

        for i, d in enumerate(dm_list):
            try:
                msg = {}
                if ops[i] == 5:
                    j = json.loads(d)
                    msg["msg_type"] = {
                        "SEND_GIFT": "gift",
                        "DANMU_MSG": "danmaku",
                        "WELCOME": "enter",
                        "NOTICE_MSG": "broadcast",
                    }.get(j.get("cmd"), "other")
                    if msg["msg_type"] == "danmaku":
                        msg["name"] = j.get("info", ["", "", ["", ""]])[2][1] or j.get(
                            "data", {}
                        ).get("uname", "")
                        msg["content"] = j.get("info", ["", ""])[1]
                        msg["color"] = f"{j.get('info', [[0, 0, 0, 16777215]])[0][3]:06x}"
                    elif msg["msg_type"] == "broadcast":
                        msg["type"] = j.get("msg_type", 0)
                        msg["roomid"] = j.get("real_roomid", 0)
                        msg["content"] = j.get("msg_common", "none")
                        msg["raw"] = j
                    else:
                        msg["content"] = j
                else:
                    msg = {"name": "", "content": d, "msg_type": "other"}
                msgs.append(msg)
            except Exception as e:
                # traceback.print_exc()
                # print(e)
                pass

        return msgs
