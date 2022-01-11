import os
import re

def get_stream_url(live_url):
    stream_url = None
    platform = re.findall(r'\.(.*).com/',live_url)[0]
    rid = re.findall(r'\.com/([\w]*)',live_url)[0]
    
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
        # url_dict = bilibili.get_real_url(rid)['flv']
        # key = list(url_dict)[0]
        # stream_url = url_dict[key]
        stream_url = bilibili.get_real_url(rid)['flv']

    elif platform in ['dy','douyu']:
        from . import douyu
        url = douyu.get_real_url(rid)['flv']
        stream_url = url
    
    if not stream_url:
        raise ValueError('无法解析URL')
    
    return stream_url
        