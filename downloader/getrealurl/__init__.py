import os
import re

def split_url(url:str):
    platform = re.findall(r'\.(.*).com/',url)[0]
    rid = re.findall(r'\.com/([\w]*)',url)[0]

    if platform == 'douyu':
        try:
            int(rid)
        except:
            if 'rid=' in url:
                rid = re.findall(r'rid=[0-9]*',url)[0][4:]
    
    return (platform, rid)

def get_stream_url(live_url,type='flv'):
    stream_url = None
    platform,rid = split_url(live_url)
    
    if platform in ['hy','huya']:
        from . import huya
        url = huya.get_real_url(rid)
        if url.startswith('http'):
            stream_url = url
        elif ('未开播' in url) or ('直播录像' in url):
            raise RuntimeError('未开播')
        else:
            raise RuntimeError('无法解析URL')
    
    elif platform in ['bili','bilibili']:
        from . import bilibili
        if type == 'm3u8':
            url_dict = bilibili.get_real_url(rid)['m3u8']
            key = list(url_dict)[0]
            stream_url = url_dict[key]
        else: 
            stream_url = bilibili.get_real_url(rid)['flv']

    elif platform in ['dy','douyu']:
        from . import douyu
        url = douyu.get_real_url(rid)['x-p2p']
        stream_url = url
    
    if not stream_url:
        raise ValueError('无法解析URL')
    
    return stream_url
        
