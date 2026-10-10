import subprocess
import os
from .toolsmgr import ToolsList
from .runcmd import run_and_capture_output

__all__ = ['bili_islogin', 'bili_login']

def bili_islogin(cookies_path:str, **kwargs) -> bool:
    renew_args = [ToolsList.get('biliup'), '-u', cookies_path, 'renew']
    # 用临时文件收输出：原来的 PIPE + wait() + read() 在输出超过管道缓冲时会死锁，
    # 而 bufsize=10**8 既解决不了死锁、又白白预留上百 MB 内存。
    out, returncode = run_and_capture_output(renew_args, timeout=60)
    if 'error' in out.lower() or returncode != 0:
        return False
    else:
        return True

def bili_login(cookies:str, account:str=None, **kwargs):
    if not (cookies or account):
        raise ValueError('cookies or account must be set.')
    if cookies is None:
        account = account
        cookies = f'.login_info/{account}.json'
    else:
        account = os.path.basename(cookies).split('.')[0]
        cookies = cookies
    
    os.makedirs(os.path.dirname(cookies), exist_ok=True)
    login_args = [ToolsList.get('biliup'), '-u', cookies, 'login']
    while not bili_islogin(cookies):
        print(f'正在登录名称为 {account} 的B站账户:')
        proc = subprocess.Popen(login_args)
        proc.wait()
    # print(f'将 {account} 的登录信息保存到 {cookies}.')
    return cookies
    