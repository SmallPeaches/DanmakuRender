# modified from https://github.com/biliup/biliup/blob/master/biliup/plugins/twitch.py

import json
import logging
import random
import re
from urllib.parse import urlencode
import requests
import streamlink
try:
    from .BaseAPI import BaseAPI
except ImportError:
    from BaseAPI import BaseAPI

logger = logging.getLogger(__name__)
_CLIENT_ID = 'kimne78kx3ncx6brgo4mv6wki5h1ko'


class twitch(BaseAPI):
    def __init__(self, rid):
        self.rid = rid
    
    def is_available(self) -> bool:
        return True
    
    @staticmethod
    def _post_gql(ops):
        headers = {
            'Content-Type': 'text/plain;charset=UTF-8',
            'Client-ID': _CLIENT_ID,
        }

        gql = requests.post(
            'https://gql.twitch.tv/gql',
            json=ops,
            headers=headers,
            timeout=15,
        )
        gql.close()
        data = gql.json()
        return data
    
    def _get_response(self) -> dict:
        user = self._post_gql({
            "query": '''
                query query($channel_name:String!) {
                    user(login: $channel_name){
                        stream {
                            id
                            title
                            type
                            previewImageURL(width: 0,height: 0)
                            playbackAccessToken(
                                params: {
                                    platform: "web",
                                    playerBackend: "mediaplayer",
                                    playerType: "site"
                                }
                            ) {
                                signature
                                value             
                            }
                        }
                    }
                }
            ''',
            'variables': {'channel_name': self.rid}
        }).get('data', {}).get('user')
        return user
    
    def get_info(self) -> list:
        info = self._get_response()
        title = info['stream']['title']
        face_url = None
        covel_url = info['stream']['previewImageURL']
        return [title, self.rid, face_url, covel_url]

    def onair(self) -> bool:
        info =  self._get_response()
        if info['stream'] and info['stream']['type'] == 'live':
            return True
        return False
    
    def get_stream_urls(self, **kwargs) -> list:
        info = self._get_response()
        query = {
            "player": "twitchweb",
            "p": random.randint(1000000, 10000000),
            "allow_source": "true",
            "allow_audio_only": "true",
            "allow_spectre": "false",
            'fast_bread': "true",
            'sig': info.get('stream').get('playbackAccessToken').get('signature'),
            'token': info.get('stream').get('playbackAccessToken').get('value'),
        }
        raw_stream_url = f'https://usher.ttvnw.net/api/channel/hls/{self.rid}.m3u8?{urlencode(query)}'
        stream_urls = streamlink.streams(raw_stream_url)
        return [{
            'stream_url': stream_urls['best'].url,
        }]
    
    def get_stream_header(self) -> dict:
        return {
            'Client-ID': _CLIENT_ID,
            'Referer': f'https://www.twitch.tv/{self.rid}',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        }
    

if __name__ == '__main__':
    twitch_api = twitch('faide')
    print(twitch_api.onair())
    print(twitch_api.get_info())
    print(twitch_api.is_available())
    print(twitch_api.get_stream_urls())
