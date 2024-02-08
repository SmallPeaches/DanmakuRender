import subprocess
import os
from .toolsmgr import ToolsList

__all__ = ['bili_islogin', 'bili_login']

def bili_islogin(cookies_path:str, **kwargs) -> bool:
    renew_args = [ToolsList.get('biliup'), '-u', cookies_path, 'renew']
    proc = subprocess.Popen(renew_args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=10**8)
    proc.wait()
    out = proc.stdout.read()
    out = out.decode('utf-8')
    if 'error' in out.lower() or proc.returncode != 0:
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
    