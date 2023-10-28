
class ToolsList(dict):
    _tools = {}

    @classmethod
    def get(cls, name:str, auto_install=True):
        if not cls._tools.get(name) and auto_install:
            if name == 'biliup':
                from .check_env import check_biliup
                check_biliup()
            elif name == 'ffmpeg' or name == 'ffprobe':
                from .check_env import check_ffmpeg
                check_ffmpeg()

        return cls._tools.get(name)
    
    @classmethod
    def set(cls, name:str, path:str):
        cls._tools[name] = path