import json, re, select, random, traceback
from struct import pack, unpack

import asyncio, aiohttp, zlib


class Twitch:
    heartbeat = "PING"

    async def get_ws_info(url):
        reg_datas = []
        room_id = re.search(r"/([^/?]+)[^/]*$", url).group(1)

        reg_datas.append("CAP REQ :twitch.tv/tags twitch.tv/commands twitch.tv/membership")
        reg_datas.append("PASS SCHMOOPIIE")
        nick = f"justinfan{int(8e4 * random.random() + 1e3)}"
        reg_datas.append(f"NICK {nick}")
        reg_datas.append(f"USER {nick} 8 * :{nick}")
        reg_datas.append(f"JOIN #{room_id}")

        return "wss://irc-ws.chat.twitch.tv", reg_datas

    def decode_msg(data):
        # print(data)
        # print('----------------')
        msgs = []
        for d in data.splitlines():
            try:
                msg = {}
                msg["name"] = re.search(r"display-name=([^;]+);", d).group(1)
                msg["content"] = re.search(r"PRIVMSG [^:]+:(.+)", d).group(1)
                # msg['msg_type']  = {'dgb': 'gift', 'chatmsg': 'danmaku',
                # 'uenter': 'enter'}.get(msg['type'], 'other')
                msg["msg_type"] = "danmaku"
                c = re.search(r"color=#([a-zA-Z0-9]{6});", d)
                msg["color"] = "ffffff" if c == None else c.group(1).lower()
                msgs.append(msg)
            except Exception as e:
                # traceback.print_exc()
                pass
        return msgs
