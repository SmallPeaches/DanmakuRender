import os
import shutil
import zipfile
from tools.check_env import compare_version

IGNORE_FILES = ['default.yml', 'replay.yml']

if __name__ == '__main__':
    from main import VERSION
    import requests
    resp = requests.get('https://api.github.com/repos/SmallPeaches/DanmakuRender/releases/latest').json()
    lastest_version = resp["tag_name"]
    if compare_version(lastest_version, VERSION) >= 0:
        print('存在可用更新：')
        print(f"版本：{lastest_version}")
        print(f"发行时间：{resp['published_at']}")
        print(f"发行说明：{resp.get('name')}")
        print(f"{resp.get('body','')}")
        input('回车开始更新：')

        durl = f"https://github.com/SmallPeaches/DanmakuRender/archive/refs/tags/{lastest_version}.zip"
        os.makedirs('.temp', exist_ok=True)
        r = requests.get(durl, stream=True)
        # 下载
        content = b''
        for i, chunk in enumerate(r.iter_content(1024)):
            print(f'\r已下载 {i}KB.', end='')
            content += chunk
        print('')

        # 写入文件
        with open('.temp/DMR-latest.zip', 'wb') as f:
            f.write(content)
        
        # 检测完整性
        try:
            f = zipfile.ZipFile('.temp/DMR-latest.zip', 'r')
        except Exception as e:
            print("解压安装包出错，请检查网络连接.")

        # 解压
        for file in f.namelist():
            f.extract(file, '.temp/DMR-latest')
        f.close()

        # 备份旧文件
        if os.path.exists('.oldfile'):
            shutil.rmtree('.oldfile')
        os.makedirs('.oldfile')

        main_dir = os.path.join('.temp/DMR-latest', os.listdir('.temp/DMR-latest')[0])
        for file in os.listdir(main_dir):
            if os.path.exists(file):
                shutil.move(file, os.path.join('.oldfile',file))

        for file in os.listdir(main_dir):
            if file not in IGNORE_FILES:
                shutil.move(os.path.join(main_dir,file), file)

        # 删除下载文件
        shutil.rmtree('.temp/DMR-latest')
        os.remove('.temp/DMR-latest.zip')

        print("更新完成, 旧文件被保存到 .oldfile 文件夹下.")
    else:
        print('无可用更新.')
    input('回车完成更新：')