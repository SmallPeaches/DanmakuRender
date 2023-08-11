import os
import shutil
import platform
import subprocess


class move():
    @staticmethod
    def move2Trash(deletePath):
        # windows
        if (platform.system() == 'Windows'):
            from win32com.shell import shell, shellcon
            return shell.SHFileOperation((0, shellcon.FO_DELETE, deletePath, None,
                                          shellcon.FOF_SILENT | shellcon.FOF_ALLOWUNDO | shellcon.FOF_NOCONFIRMATION,
                                          None, None))
        # linux
        elif (platform.system() == 'Linux'):
            cmd = ['trash', deletePath]
            return subprocess.call(cmd, stdout=open(os.devnull, 'w'))
        # macOS
        elif (platform.system() == 'Darwin'):
            absPath = os.path.abspath(deletePath).replace(
                '\\', '\\\\').replace('"', '\\"')
            cmd = ['osascript', '-e',
                   'tell app "Finder" to move {the POSIX file "' + absPath + '"} to trash']
            return subprocess.call(cmd, stdout=open(os.devnull, 'w'))

    @staticmethod
    def move(src, dst, mkdir=True, **kwargs):
        if not dst:
            raise ValueError('移动路径不能为空')
        elif dst == '*TRASHBIN*':
            return move.move2Trash(src)

        if not os.path.exists(dst):
            if mkdir:
                os.makedirs(dst)
            else:
                raise ValueError(f'Path not exists: {dst}')
        return shutil.move(src, dst)
