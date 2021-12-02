from io import FileIO
import os
import csv
import re
import json
import tempfile
from os.path import join
from tools.utils import *

class DanmuRender():
    def __init__(self,config=None,tmpdir='./render/.tmp') -> None:
        self.template = join(os.path.dirname(__file__),'danmu_template.jsx')
        self.config = config
        self.dmlist = []
        
        with open(self.template,'r') as f:
            self.script = f.readlines()
        for k,v in self.config.items():
            for i,line in enumerate(self.script):
                if line == '}\n':
                    break
                elif k in line:
                    if isinstance(v,str):
                        newline = f'    {k} : "{v}",\n'
                    else:
                        newline = f'    {k} : {v},\n'
                    self.script[i] = newline
                    break

    def readfile(self,dmfile):
        if not os.path.exists(dmfile):
            raise ValueError("弹幕文件不存在.")
        
        with open(dmfile,'r',encoding='utf-8') as f:
            try:
                if os.path.splitext(dmfile)[-1] == '.csv':
                    dmlist = csv.reader(f)
                    header = next(dmlist)
                    timeidx = header.index('time')[1:]
                    coloridx = header.index('color')
                    textidx = header.index('content')
                    
                elif os.path.splitext(dmfile)[-1] == '.json':
                    dmlist = json.load(f)
                    timeidx,coloridx,textidx = 'time','color','content'
            except:
                raise ValueError("弹幕文件格式错误.")

            for danmu in dmlist:
                try:
                    time,color,text = danmu[timeidx],danmu[coloridx],danmu[textidx]
                except:
                    continue
                time = float(time)
                if color[:2] == '0x':
                    color = color[2:]
                r = int(color[0:2],16)/255
                g = int(color[2:4],16)/255
                b = int(color[4:6],16)/255
                color = [r,g,b]
                self.dmlist.append({'time':time,'color':color,'text':text})

    def _gen_script(self,file,saveto=None):
        self.script.append('var dmc = new DanmuCompound();\n')
        for dm in self.dmlist:
            text,color,time = dm['text'],dm['color'],dm['time']
            self.script.append(f'dmc.add(new DanmuItem("{text}",{color},{time}));\n')
        self.script.append('\ndmc.render()\n')
        self.script.append('writeLn(dmc.dmcnt+" 条弹幕被加载.")\n')

        if saveto:
            self.script.append('app.project.saveWithDialog()\n')

        with open(file,'w',encoding='utf-8') as f:
            f.writelines(self.script)
        return file

    def render(self,AE_PATH='',saveto=True):
        fn = tempfile.mktemp(suffix='.jsx')
        self._gen_script(fn,saveto=saveto)
        if not AE_PATH:
            start_menu = 'C:\ProgramData\Microsoft\Windows\Start Menu\Programs'
            for ink in os.listdir(start_menu):
                if re.match('.*After Effect.*.lnk',ink):
                    ink = os.path.join(start_menu,ink)
                    AE_PATH = get_lnk_file(ink)
                    break
        os.system(f'"{AE_PATH}" -r {fn}')
        os.remove(fn)

if __name__ == "__main__":
    dmr = DanmuRender()
    dmr.readfile('danmu.json')
    dmr.render()
    print("渲染完成")