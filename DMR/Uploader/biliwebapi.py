import asyncio
import base64
import concurrent.futures
import hashlib
from io import BytesIO
import json
import logging
import math
import os
import re
import sys
import threading
import time
import queue
import urllib.parse
from dataclasses import asdict, dataclass, field, InitVar
from json import JSONDecodeError
from os.path import splitext, basename
from typing import Callable, Dict, Union, Any, List
from urllib import parse
from urllib.parse import quote

# import aiohttp
from DMR.utils import VideoInfo, replace_keywords
from concurrent.futures.thread import ThreadPoolExecutor
import concurrent
import requests.utils
import rsa
from requests.adapters import HTTPAdapter, Retry

from .biliuprs import biliuprs


logger = logging.getLogger(__name__)


class BiliWebApi:
    def __init__(self,
        cookies:str=None,
        account:str=None,
        threads=3,
        sort_videos:bool=False,
        **kwargs,
    ):
        self.cookies = cookies
        self.account = account
        self.threads = threads
        self.sort_videos = sort_videos

        self.app_key = 'ae57252b0c09105d'
        self.appsec = 'c75875c596a69eb55bd119e74b07cfe3'
        self.__session = requests.Session()
        self.__session.mount('https://', HTTPAdapter(max_retries=Retry(total=5)))
        self.__session.headers.update({
            'user-agent': "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/63.0.3239.108",
            'referer': "https://www.bilibili.com/",
            'connection': 'keep-alive'
        })
        self._auto_os = None
        login_info = self.login_by_biliuprs()
        self.cookies = {}
        for item in login_info['cookie_info']['cookies']:
            self.cookies[item['name']] = item['value']
        self.__bili_jct = self.cookies['bili_jct']
        self.__session.cookies = requests.utils.cookiejar_from_dict(self.cookies)
        self.access_token = login_info['token_info']['access_token']
        self.refresh_token = login_info['token_info']['refresh_token']

        self.videos = None
        self.stoped = False


    def login_by_biliuprs(self):
        biliup_rs = biliuprs(cookies=self.cookies, account=self.account)
        with open(biliup_rs.cookies, 'r', encoding='utf-8') as f:
            cookies = json.load(f)
        return cookies

    def sign(self, param):
        return hashlib.md5(f"{param}{self.appsec}".encode()).hexdigest()

    def get_key(self):
        url = "https://passport.bilibili.com/x/passport-login/web/key"
        payload = {
            'appkey': f'{self.app_key}',
            'sign': self.sign(f"appkey={self.app_key}"),
        }
        response = self.__session.get(url, data=payload, timeout=5)
        r = response.json()
        if r and r["code"] == 0:
            return r['data']['hash'], rsa.PublicKey.load_pkcs1_openssl_pem(r['data']['key'].encode())

    def probe(self):
        ret = self.__session.get('https://member.bilibili.com/preupload?r=probe', timeout=5).json()
        logger.debug(f"线路:{ret['lines']}")
        data, auto_os = None, None
        min_cost = 0
        if ret['probe'].get('get'):
            method = 'get'
        else:
            method = 'post'
            data = bytes(int(1024 * 0.1 * 1024))
        for line in ret['lines']:
            start = time.perf_counter()
            test = self.__session.request(method, f"https:{line['probe_url']}", data=data, timeout=30)
            cost = time.perf_counter() - start
            # logger.debug(line['query'], cost)
            if test.status_code != 200:
                return
            if not min_cost or min_cost > cost:
                auto_os = line
                min_cost = cost
        auto_os['cost'] = min_cost
        return auto_os
    
    def creditsToDesc_v2(self, desc:str, credits:List[Dict[str, Union[str, int]]]):
        desc_v2 = []
        desc_v2_tmp = desc
        for credit in credits:
            try:
                num = desc_v2_tmp.index("@credit")
                desc_v2.append({
                    "raw_text": " " + desc_v2_tmp[:num],
                    "biz_id": "",
                    "type": 1
                })
                desc_v2.append({
                    "raw_text": credit["username"],
                    "biz_id": str(credit["uid"]),
                    "type": 2
                })
                desc = desc.replace(
                    "@credit", "@" + credit["username"] + "  ", 1)
                desc_v2_tmp = desc_v2_tmp[num + 7:]
            except IndexError:
                logger.error('简介中的@credit占位符少于credits的数量,替换失败')
        desc_v2.append({
            "raw_text": " " + desc_v2_tmp,
            "biz_id": "",
            "type": 1
        })
        desc_v2[0]["raw_text"] = desc_v2[0]["raw_text"][1:]  # 开头空格会导致识别简介过长
        return desc, desc_v2

    def videoinfo_to_videos(self, video_info, config):
        video = Data(
            tid=config.get('tid', 21),
            copyright=config.get('copyright', 1),
            dolby=config.get('dolby', 0),
            hires=config.get('hires', 0),
            no_reprint=config.get('no_reprint', 0),
            is_only_self=config.get('is_only_self', 0),
            charging_pay=config.get('charging_pay', 0),
            open_subtitle=config.get('open_subtitle', False),
            extra_kwargs=config.get('extra_kwargs', {}),
        )
        if config.get('dtime') and config['dtime'] >= 14400:
            video.delay_time(int(time.time() + config['dtime']))
        if config.get('title'):
            video.title = replace_keywords(config['title'], video_info)
            if len(config['title']) > 80:
                video.title = video.title[:80]
                logger.warning(f'视频标题超过80字符，已自动截取为: {video.title}.')
        if config.get('desc'):
            video.desc = replace_keywords(config['desc'], video_info)
        if config.get('credits'):
            video.desc, video.desc_v2 = self.creditsToDesc_v2(video.desc, config['credits'])
        else:
            video.desc_v2 = [{
                "raw_text": video.desc,
                "biz_id": "",
                "type": 1
            }]
        if config.get('dynamic'):
            video.dynamic = replace_keywords(config['dynamic'], video_info)
        if config.get('tag'):
            if isinstance(config['tag'], list):
                video.tag = ','.join(config['tag'])
            video.tag = replace_keywords(video.tag, video_info)
        if config.get('source'):
            video.source = replace_keywords(config['source'], video_info)
        if config.get('cover'):
            cover_file = replace_keywords(config['cover'], video_info)
            try:
                if cover_file.startswith('http'):
                    import requests
                    resp = requests.get(cover_file, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10.0)
                    resp.raise_for_status()
                    cover_file = BytesIO(resp.content)
                video.cover = self.cover_up(cover_file)

            except Exception as e:
                logger.error(f'视频 {config["title"]} 封面图片下载失败: {e}, 跳过设置.')
                video.cover = ''
        return video

    def upload(
        self,
        files:list[VideoInfo],
        stream_queue: queue.SimpleQueue=None,
        **kwargs,
    ):
        if not self.videos:
            self.videos = self.videoinfo_to_videos(files[0], kwargs)
        if stream_queue is None:
            for file in files:
                status, info = self.upload_file(
                    filepath=file.path,
                    lines=kwargs.get('line', 'AUTO'),
                    videos=self.videos,
                    auto_submit=True,
                    submit_api='web'
                )
            # self.submit(submit_api='web', videos=self.videos)
                
        else:
            status, info = self.upload_stream(
                stream_queue=stream_queue,
                file_name=files[0].path,
                total_size=30*1024*1024*1024,
                lines=kwargs.get('line', 'AUTO'),
                videos=self.videos,
                auto_submit=True,
                submit_api='web'
            )
        return status, info

    def cover_up(self, img: str):
        """
        :param img: img path or stream
        :return: img URL
        """
        from PIL import Image
        from io import BytesIO

        with Image.open(img) as im:
            # 宽和高,需要16：10
            xsize, ysize = im.size
            if xsize / ysize > 1.6:
                delta = xsize - ysize * 1.6
                region = im.crop((delta / 2, 0, xsize - delta / 2, ysize))
            else:
                delta = ysize - xsize * 10 / 16
                region = im.crop((0, delta / 2, xsize, ysize - delta / 2))
            buffered = BytesIO()
            region.save(buffered, format=im.format)
        r = self.__session.post(
            url='https://member.bilibili.com/x/vu/web/cover/up',
            data={
                'cover': b'data:image/jpeg;base64,' + (base64.b64encode(buffered.getvalue())),
                'csrf': self.__bili_jct
            }, timeout=30
        )
        buffered.close()
        res = r.json()
        if res.get('data') is None:
            raise Exception(res)
        return res['data']['url']

    def upload_file(
        self,
        filepath:str,
        lines='AUTO',
        auto_submit: bool=True,
        videos: 'Data'=None,
        submit_api: Callable[[str], None] = None,
    ):
        status, message = self.upload_stream(
            stream_queue=filepath,
            file_name=os.path.basename(filepath),
            total_size=os.path.getsize(filepath),
            lines=lines,
            auto_submit=auto_submit,
            videos=videos,
            submit_api=submit_api,
        )
        return status, message

    def upload_stream(
        self,
        stream_queue: queue.SimpleQueue,
        file_name,
        total_size,
        lines='AUTO',
        auto_submit: bool=True,
        videos: 'Data'=None,
        submit_api: Callable[[str], None] = None,
    ):

        logger.info(f"{file_name} 开始上传")
        cs_upcdn = ['alia', 'bda', 'bda2', 'bldsa', 'qn', 'tx', 'txa']
        jd_upcdn = ['jd-alia', 'jd-bd', 'jd-bldsa', 'jd-tx', 'jd-txa']
        preferred_upos_cdn = None
        if not self._auto_os:
            if lines in cs_upcdn:
                self._auto_os = {"os": "upos", "query": f"upcdn={lines}&probe_version=20221109",
                                 "probe_url": f"//upos-cs-upcdn{lines}.bilivideo.com/OK"}
                preferred_upos_cdn = lines
            elif lines in jd_upcdn:
                lines = lines.split('-')[1]
                self._auto_os = {"os": "upos", "query": f"upcdn={lines}&probe_version=20221109",
                                 "probe_url": f"//upos-jd-upcdn{lines}.bilivideo.com/OK"}
                preferred_upos_cdn = lines
            else:
                self._auto_os = self.probe()
            logger.debug(f"线路选择 => {self._auto_os['os']}: {self._auto_os['query']}. time: {self._auto_os.get('cost')}")
        if self._auto_os['os'] == 'upos':
            upload = self.upos_stream
        else:
            logger.error(f"NoSearch:{self._auto_os['os']}")
            raise NotImplementedError(self._auto_os['os'])
        logger.debug(f"os: {self._auto_os['os']}")
        query = {
            'r': self._auto_os['os'],
            'profile': 'ugcupos/bup',
            'ssl': 0,
            'version': '2.8.12',
            'build': 2081200,
            'name': file_name,
            'size': total_size,
        }
        resp = self.__session.get(
            f"https://member.bilibili.com/preupload?{self._auto_os['query']}", params=query,
            timeout=5)
        ret = resp.json()
        if "chunk_size" not in ret:
            # stop_event.set()
            return False, f"预上传失败: {ret}"
        logger.debug(f"preupload: {ret}")
        if preferred_upos_cdn:
            # 如果返回的endpoint不在probe_url中，则尝试在endpoints中校验probe_url是否可用
            if ret['endpoint'] not in self._auto_os['probe_url']:
                for endpoint in ret['endpoints']:
                    if endpoint in self._auto_os['probe_url']:
                        ret['endpoint'] = endpoint
                        logger.info(f"修改endpoint: {ret['endpoint']}")
                        break
                else:
                    logger.warning(f"选择的线路 {self._auto_os['os']} 没有返回对应 endpoint，不做修改")
        video_part = asyncio.run(upload(stream_queue, file_name, total_size, ret))
        if video_part is None:
            # stop_event.set()
            return False, '分P上传失败'
        video_part['title'] = video_part['title'][:80]

        videos.append(video_part)  # 添加已经上传的视频
        if auto_submit:
            ret = self.submit(submit_api=submit_api, videos=videos)
            logger.info(f"上传成功: {ret}")
            bvid = ret['data']['bvid']
            videos.bvid = bvid
            return True, bvid
        else:
            return True, f'分P上传成功{video_part}，等待提交'

    async def upos_stream(self, stream_queue, file_name, total_size, ret):
        # print("--------------, ", file_name)
        chunk_size = ret['chunk_size']
        auth = ret["auth"]
        endpoint = ret["endpoint"]
        biz_id = ret["biz_id"]
        upos_uri = ret["upos_uri"]
        url = f"https:{endpoint}/{upos_uri.replace('upos://', '')}"  # 视频上传路径
        headers = {
            "X-Upos-Auth": auth
        }
        # 向上传地址申请上传，得到上传id等信息
        upload_id = self.__session.post(f'{url}?uploads&output=json', timeout=15,
                                        headers=headers).json()["upload_id"]
        # 开始上传
        parts = []  # 分块信息
        chunks = math.ceil(total_size / chunk_size)  # 获取分块数量
        total_size = chunks * chunk_size  # 补齐总大小

        start = time.perf_counter()

        # print("-----------")
        # print(upload_id, chunks, chunk_size, total_size)
        logger.info(
            f"{file_name} - upload_id: {upload_id}, chunks: {chunks}, chunk_size: {chunk_size}, total_size: {total_size}")
        
        
        if isinstance(stream_queue, (str, os.PathLike)):
            # 文件路径
            chunk_generator = self.file_reader_generator(stream_queue, chunk_size)
        else:
            # 视频流队列
            chunk_generator = self.queue_reader_generator(stream_queue, chunk_size, total_size)
        
        n = 0
        st = time.perf_counter()
        max_workers = 3
        semaphore = threading.Semaphore(max_workers)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []
            for index, chunk in enumerate(chunk_generator):
                if not chunk:
                    break
                const_time = time.perf_counter() - st
                speed = len(chunk) * 8 / 1024 / 1024 / const_time
                # logger.info(f"{file_name} - chunks-({index+1}/{chunks}) - down - speed: {speed:.2f}Mbps")
                n += len(chunk)
                params = {
                    'uploadId': upload_id,
                    'chunks': chunks,
                    'total': total_size,
                    'chunk': index,
                    'size': chunk_size,
                    'partNumber': index + 1,
                    'start': index * chunk_size,
                    'end': index * chunk_size + chunk_size
                }
                params_clone = params.copy()
                semaphore.acquire()
                future = executor.submit(self.upload_chunk_thread,
                                         url, chunk, params_clone, headers, file_name)
                future.add_done_callback(lambda x: semaphore.release())
                futures.append(future)
                st = time.perf_counter()

                for f in list(futures):
                    if f.done():
                        futures.remove(f)

                # 等待所有分片上传完成，并按顺序收集结果
            for future in concurrent.futures.as_completed(futures):
                pass

            results = [{
                "partNumber": i + 1,
                "eTag": "etag"
            } for i in range(chunks)]
            parts.extend(results)

        if n == 0:
            return None
        # logger.info(f"{file_name} - total_size: {total_size}, n: {n}")
        cost = time.perf_counter() - start
        p = {
            'name': file_name,
            'uploadId': upload_id,
            'biz_id': biz_id,
            'output': 'json',
            'profile': 'ugcupos/bup'
        }
        attempt = 1
        while attempt <= 3:  # 一旦放弃就会丢失前面所有的进度，多试几次吧
            try:
                r = self.__session.post(url, params=p, json={"parts": parts}, headers=headers, timeout=15).json()
                if r.get('OK') == 1:
                    # logger.info(f'{file_name} uploaded >> {total_size / 1000 / 1000 / cost:.2f}MB/s. {r}')
                    return {"title": splitext(file_name)[0], "filename": splitext(basename(upos_uri))[0], "desc": ""}
                raise IOError(r)
            except IOError:
                logger.info(f"请求合并分片 {file_name} 时出现问题，尝试重连，次数：" + str(attempt))
                attempt += 1
                time.sleep(10)
        pass

    def upload_chunk_thread(self, url, chunk, params_clone, headers, file_name, max_retries=3, backoff_factor=1):
        st = time.perf_counter()
        retries = 0
        while retries < max_retries:
            try:
                r = requests.put(url=url, params=params_clone, data=chunk, headers=headers)

                # 如果上传成功，退出重试循环
                if r.status_code == 200:
                    const_time = time.perf_counter() - st
                    speed = len(chunk) * 8 / 1024 / 1024 / const_time
                    logger.info(
                        f"{file_name} - chunks-{params_clone['chunk'] +1 } - up status: {r.status_code} - speed: {speed:.2f}Mbps"
                    )
                    return {
                        "partNumber": params_clone['chunk'] + 1,
                        "eTag": "etag"
                    }

                # 如果上传失败，但未达到最大重试次数，等待一段时间后重试
                else:
                    retries += 1
                    logger.warning(
                        f"{file_name} - chunks-{params_clone['chunk']} - up failed: {r.status_code}. Retrying {retries}/{max_retries}")

                    # 计算退避时间，逐步增加重试间隔
                    backoff_time = backoff_factor ** retries
                    time.sleep(backoff_time)

            except Exception as e:
                retries += 1
                logger.error(f"upload_chunk_thread err {str(e)}. Retrying {retries}/{max_retries}")

                # 计算退避时间，逐步增加重试间隔
                backoff_time = backoff_factor ** retries
                time.sleep(backoff_time)

        # 如果重试了所有次数仍然失败，记录错误
        logger.error(f"{file_name} - chunks-{params_clone['chunk']} - Upload failed after {max_retries} attempts.")
        return None

    def file_reader_generator(self, filepath: str, chunk_size: int):
        """
        从文件中读取数据并按 chunk_size 大小分块产出 (yield)
        :param filepath: 文件路径
        :param chunk_size: 消费者每次想要获取的数据块大小
        :return: 生成器，按 chunk_size 大小分批次产出数据
        """
        with open(filepath, 'rb') as f:
            while True:
                data = f.read(chunk_size)
                if not data:
                    break
                yield data
        yield None

    def queue_reader_generator(self, simple_queue: queue.SimpleQueue, chunk_size: int, max_size: int):
        """
        从 simple_queue 中读取数据并按 chunk_size 大小分块产出 (yield)
        当队列中获取到 None 或者数据总量达到 max_size 后，就用 0x00 补齐到 chunk_size

        :param simple_queue: queue.SimpleQueue 实例，数据流会以多个分包 (bytes) 入队，最后以 None 表示结束
        :param chunk_size: 消费者每次想要获取的数据块大小
        :param max_size: 需要最终补齐的总大小（单位：字节），必须是 chunk_size 的整数倍
        :return: 生成器，按 chunk_size 大小分批次产出数据
        """
        if max_size % chunk_size != 0:
            raise ValueError("max_size must be a multiple of chunk_size")

        total_chunks = max_size // chunk_size
        chunks_yielded = 0
        current_buffer = bytearray()
        save_file = None
        # save_file = f'{int(time.time())}.flv'
        # save_file = open(save_file, 'wb')

        while chunks_yielded < total_chunks:
            try:
                data = simple_queue.get(timeout=300)
            except queue.Empty:
                logger.info("数据读取超时，结束当前分P")
                break

            if data is None:
                # 数据流结束，用0x00填充剩余的块
                remaining_chunks = total_chunks - chunks_yielded
                if remaining_chunks == total_chunks:
                    # print("空包跳过")
                    break
                if len(current_buffer) > 0:
                    # 处理当前缓冲区中的最后一块数据
                    padding_size = chunk_size - len(current_buffer)
                    if padding_size > 0:
                        current_buffer += b'\x00' * padding_size
                        logger.info(f"最后一个包差了 {padding_size} 个字节")
                    yield bytes(current_buffer)
                    chunks_yielded += 1
                    remaining_chunks -= 1
                logger.info(f"数据流结束.")
                break
                logger.info(f"还差 {remaining_chunks} 个完整包")

                # 输出剩余的全0块
                for _ in range(remaining_chunks):
                    yield b'\x00' * chunk_size
                    chunks_yielded += 1
                break

            save_file and save_file.write(data)

            # 将新数据添加到缓冲区
            current_buffer.extend(data)

            # 输出完整的块
            while len(current_buffer) >= chunk_size and chunks_yielded < total_chunks:
                yield bytes(current_buffer[:chunk_size])
                current_buffer = current_buffer[chunk_size:]
                chunks_yielded += 1

        # print("本段分p完成")
        save_file and save_file.close()
        yield None

    def submit(self, submit_api=None, videos:'Data'=None):
        edit = videos.bvid is not None
        if self.sort_videos:
            videos.videos.sort(key=lambda x: x['title'], reverse=True)
        # 不能提交 extra_kwargs 字段，提前处理
        post_data = asdict(videos)
        if post_data.get('extra_kwargs'):
            for key, value in post_data.pop('extra_kwargs').items():
                post_data.setdefault(key, value)

        # self.__session.get('https://member.bilibili.com/x/geetest/pre/add', timeout=5)
        ret = self.submit_web(post_data, edit=edit)
        if not ret:
            raise Exception(f'不存在的选项：{submit_api}')
        if ret["code"] == 0:
            return ret
        else:
            raise Exception(ret)

    def submit_web(self, post_data, edit=False):
        # logger.info('使用网页端api提交')
        if not self.__bili_jct:
            raise RuntimeError("bili_jct is required!")
        api = 'https://member.bilibili.com/x/vu/web/add?csrf=' + self.__bili_jct
        if edit:
            api = 'https://member.bilibili.com/x/vu/web/edit?csrf=' + self.__bili_jct
        return self.__session.post(api, timeout=5,
                                   json=post_data).json()
    
    def stop(self):
        self.stoped = True


@dataclass
class Data:
    """
    cover: 封面图片，可由recovers方法得到视频的帧截图
    """
    copyright: int = 1
    source: str = ''
    tid: int = 21
    cover: str = ''
    title: str = ''
    desc_format_id: int = 0
    desc: str = ''
    desc_v2: list = field(default_factory=list)
    dynamic: str = ''
    subtitle: dict = field(init=False)
    tag: Union[list, str] = ''
    videos: list = field(default_factory=list)
    dtime: Any = None
    open_subtitle: InitVar[bool] = False
    dolby: int = 0
    hires: int = 0
    no_reprint: int = 0
    is_only_self: int = 0
    charging_pay: int = 0
    extra_kwargs: dict = field(default_factory=dict)

    bvid: int = None
    # interactive: int = 0
    # no_reprint: int 1
    # charging_pay: int 1

    def __post_init__(self, open_subtitle):
        self.subtitle = {"open": int(open_subtitle), "lan": ""}
        if self.dtime and self.dtime - int(time.time()) <= 14400:
            self.dtime = None
        if isinstance(self.tag, list):
            self.tag = ','.join(self.tag)

    def delay_time(self, dtime: int):
        """设置延时发布时间，距离提交大于2小时，格式为10位时间戳"""
        if dtime - int(time.time()) > 7200:
            self.dtime = dtime

    def set_tag(self, tag: list):
        """设置标签，tag为数组"""
        self.tag = ','.join(tag)

    def append(self, video):
        self.videos.append(video)
