import json
import tempfile
import streamlink
import subprocess
try:
    from .BaseAPI import BaseAPI
except ImportError:
    from BaseAPI import BaseAPI

class defaultapi(BaseAPI):
    def __init__(self, url:str):
        self.url = url

    def is_available(self) -> bool:
        try:
            streamlink.streams(self.url)
            return True
        except streamlink.NoPluginError:
            return False
    
    def onair(self) -> bool:
        streams = streamlink.streams(self.url)
        return bool(streams)
    
    def get_info(self) -> tuple:
        args = ['streamlink', '--json', self.url, 'best']
        with tempfile.TemporaryFile() as tempf:
            proc = subprocess.Popen(args, stdout=tempf, stderr=subprocess.STDOUT)
            proc.wait()
            tempf.seek(0)
            metadata = tempf.read().decode('utf-8')
            try:
                metadata = json.loads(metadata)['metadata']
            except json.JSONDecodeError:
                raise RuntimeError('Streamlink failed to get metadata: {}'.format(metadata))
        
        title = metadata['title']
        uname = metadata['author']
        face_url = None
        keyframe_url = None
        return title, uname, face_url, keyframe_url
    
    def get_stream_urls(self, **kwargs) -> list:
        streams = streamlink.streams(self.url)
        stream = streams['best']
        stream_info = json.loads(stream.json)
        self._stream_header = stream_info.get('headers', {})

        return [{
            'stream_type': stream_info.get('type', ''),
            'stream_url': stream.url,
        }]
    
    def get_stream_header(self) -> dict:
        if hasattr(self, '_stream_header') and self._stream_header:
            return self._stream_header
        return super().get_stream_header()
    

if __name__ == '__main__':
    api = defaultapi('https://www.twitch.tv/faide')
    print(api.get_stream_url())