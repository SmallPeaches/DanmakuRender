import os
import re
import argparse
from render import DanmuRender
from tools.utils import *

if __name__ == '__main__':
    config_path = 'config.json'
    config = read_json(config_path)
    
    parser = argparse.ArgumentParser(description='Render')
    parser.add_argument('-f','--file',type=str,default=config['dmfile'])
    parser.add_argument('-a','--ae',type=str,default=config['aepath'])
    parser.add_argument('--nosave',action='store_true')

    args = parser.parse_args()

    while not os.path.isfile(args.file):
        args.file = input('DanmuFile:')
    
    if args.ae == 'auto':
        try:
            start_menu = 'C:\ProgramData\Microsoft\Windows\Start Menu\Programs'
            for lnk in os.listdir(start_menu):
                if re.match('.*After Effects.*.lnk',lnk):
                    lnk = os.path.join(start_menu,lnk)
                    args.ae = get_lnk_file(lnk)
                    break
        except:
            print('AE 路径错误.')
            exit(0)

    dmr = DanmuRender(config)
    dmr.readfile(args.file)
    dmr.render(args.ae,saveto=~args.nosave)


