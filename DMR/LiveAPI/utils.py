import re

def concat_rid(plat:str,rid:str) -> str:
    if plat == 'bilibili':
        url = f'https://live.{plat}.com/{str(rid)}'
    else:
        url = f'https://www.{plat}.com/{str(rid)}'
    return url

def split_url(url:str):
    platform = re.findall(r'\.(.*).com/',url)[0]
    rid = re.findall(r'\.com/([\w]*)',url)[0]

    if platform == 'douyu':
        try:
            int(rid)
        except:
            if 'rid=' in url:
                rid = re.findall(r'rid=[0-9]*',url)[0][4:]
    if platform == "163":
        platform = "cc"
    return platform, rid
