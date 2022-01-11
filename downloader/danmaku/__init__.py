from datetime import datetime
import re, asyncio, aiohttp

from .youtube import Youtube
from .twitch import Twitch
from .bilibili import Bilibili
from .douyu import Douyu
from .huya import Huya

__all__ = ["DanmakuClient"]


class DanmakuClient:
    def __init__(self, url, q, **kargs):
        self.__url = ""
        self.__site = None
        self.__usite = None
        self.__hs = None
        self.__ws = None
        self.__stop = False
        self.__dm_queue = q
        self.__link_status = True
        self.__extra_data = kargs
        if "http://" == url[:7] or "https://" == url[:8]:
            self.__url = url
        else:
            self.__url = "http://" + url
        for u, s in {
            "douyu.com": Douyu,
            "live.bilibili.com": Bilibili,
            "twitch.tv": Twitch,
            "huya.com": Huya,
        }.items():
            if re.match(r"^(?:http[s]?://)?.*?%s/(.+?)$" % u, url):
                self.__site = s
                break
        if self.__site == None:
            for u, s in {"youtube.com/channel": Youtube, "youtube.com/watch": Youtube}.items():
                if re.match(r"^(?:http[s]?://)?.*?%s(.+?)$" % u, url):
                    self.__usite = s
            if self.__usite == None:
                raise Exception("Invalid link!")
        self.__hs = aiohttp.ClientSession()

    async def init_ws(self):
        ws_url, reg_datas = await self.__site.get_ws_info(self.__url)
        self.__ws = await self.__hs.ws_connect(ws_url)
        for reg_data in reg_datas:
            if type(reg_data) == str:
                await self.__ws.send_str(reg_data)
            else:
                await self.__ws.send_bytes(reg_data)

    async def heartbeats(self):
        while self.__stop != True:
            # print('heartbeat')
            await asyncio.sleep(20)
            try:
                if type(self.__site.heartbeat) == str:
                    await self.__ws.send_str(self.__site.heartbeat)
                else:
                    await self.__ws.send_bytes(self.__site.heartbeat)
            except:
                pass

    async def fetch_danmaku(self):
        while self.__stop != True:
            async for msg in self.__ws:
                # self.__link_status = True
                ms = self.__site.decode_msg(msg.data)
                for m in ms:
                    if not m.get('time',0):
                        m['time'] = datetime.now()
                    await self.__dm_queue.put(m)
            if self.__stop != True:
                await asyncio.sleep(1)
                await self.init_ws()
                await asyncio.sleep(1)

    async def start(self):
        if self.__site != None:
            await self.init_ws()
            await asyncio.gather(
                self.heartbeats(),
                self.fetch_danmaku(),
            )
        else:
            await self.__usite.run(self.__url, self.__dm_queue, self.__hs, **self.__extra_data)

    async def stop(self):
        self.__stop = True
        if self.__site != None:
            await self.__hs.close()
        else:
            await self.__usite.stop()
            await self.__hs.close()
