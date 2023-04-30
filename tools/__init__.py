
class ToolsList(dict):
    _tools = {}

    @classmethod
    def get(cls, name:str):
        return cls._tools.get(name)
    
    @classmethod
    def set(cls, name:str, path:str):
        cls._tools[name] = path