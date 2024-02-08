from __future__ import annotations

import base64
import hashlib
import random
import re
import string
import time
import urllib.parse
import requests

from typing import Any


wbi_img_cache = None  # Simulate the LocalStorage of the browser
dm_img_str_cache: str = base64.b64encode("".join(random.choices(string.printable, k=random.randint(16, 64))).encode())[:-2].decode()  # fmt: skip
dm_cover_img_str_cache: str = base64.b64encode("".join(random.choices(string.printable, k=random.randint(32, 128))).encode())[:-2].decode()  # fmt: skip
BILI_HEADERS = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 \
                (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36 Edg/91.0.864.67',
            'Referer': 'https://www.bilibili.com/',
        }


def getWbiKeys(sess:requests.Session=None) -> tuple[str, str]:
    '获取最新的 img_key 和 sub_key'
    resp = requests.get('https://api.bilibili.com/x/web-interface/nav', headers=BILI_HEADERS)
    resp.raise_for_status()
    json_content = resp.json()
    img_url: str = json_content['data']['wbi_img']['img_url']
    sub_url: str = json_content['data']['wbi_img']['sub_url']
    img_key = img_url.rsplit('/', 1)[1].split('.')[0]
    sub_key = sub_url.rsplit('/', 1)[1].split('.')[0]
    return img_key, sub_key


def _get_mixin_key(string: str) -> str:
    char_indices = [
        46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5,
        49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55,
        40, 61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57,
        62, 11, 36, 20, 34, 44, 52,
    ]  # fmt: skip
    return "".join(list(map(lambda idx: string[idx], char_indices[:32])))


def encode_wbi(params: dict[str, Any], wbi_img: tuple[str, str]) -> dict[str, Any]:
    img_key, sub_key = wbi_img
    illegal_char_remover = re.compile(r"[!'\(\)*]")

    mixin_key = _get_mixin_key(img_key + sub_key)
    time_stamp = int(time.time())
    params_with_wts = dict(params, wts=time_stamp)
    params_with_dm = {
        **params_with_wts,
        "dm_img_list": "[]",
        "dm_img_str": dm_img_str_cache,
        "dm_cover_img_str": dm_cover_img_str_cache,
    }
    url_encoded_params = urllib.parse.urlencode(
        {
            key: illegal_char_remover.sub("", str(params_with_dm[key]))
            for key in sorted(params_with_dm.keys())
        }
    )  # fmt: skip
    w_rid = hashlib.md5((url_encoded_params + mixin_key).encode()).hexdigest()
    all_params = dict(params_with_dm, w_rid=w_rid)
    return all_params
    