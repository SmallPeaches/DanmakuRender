import shutil
import os

class copy():
    @staticmethod
    def copy(src, dst, **kwargs):
        if not dst:
            raise ValueError('复制路径不能为空')
        
        return shutil.copy(src, dst)
