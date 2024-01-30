import subprocess
import time
import os

class runcmd():
    @staticmethod
    def runcmd(cmd:list, wait=True, timeout=None, **kwargs):
        shell = isinstance(cmd, str)
        if shell:
            _cmd = [str(x) for x in cmd]
        p = subprocess.Popen(_cmd, shell=shell, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kwargs)
        if wait:
            p.wait(timeout=timeout)
        return p