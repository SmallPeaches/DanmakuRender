import shutil
import os


class delete():
    @staticmethod
    def delete(path):
        return os.remove(path)
