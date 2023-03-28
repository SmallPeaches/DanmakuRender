import re
import os

from abc import ABC, abstractmethod
from PIL import Image,ImageDraw,ImageFont
from os.path import exists, join
from DMR.utils import *

class BaseDanmaku(ABC):
    @abstractmethod
    def __init__(self, st, et, sp, ep, content, fontsize, opacity, **kwargs):
        pass

    @property
    def image(self):
        pass

    @property
    def size(self):
        pass

class TextDanmaku(BaseDanmaku):
    match_emoji = re.compile(r'([\U00010000-\U0010ffff]+)')
    def __init__(self, st, et, sp, ep, content, font, fontsize, color, opacity, outlinecolor, outlinesize, **kwargs):
        self.st = st
        self.et = et
        self.sp = sp
        self.ep = ep
        self.content = content
        self.word_font, self.emoji_font = ImageFont.truetype('msyhbd.ttc', fontsize), ImageFont.truetype('seguiemj.ttf', fontsize)
        self.fontsize = fontsize
        self.color = color
        self.opacity = opacity
        self.outlinecolor = outlinecolor
        self.outlinesize = int(outlinesize)
        self.rendered = False

    @staticmethod
    def have_emoji(text):
        return bool(TextDanmaku.match_emoji.search(text))
    
    @property
    def size(self):
        if self.rendered:
            return self.length, self.height
        else:
            self.render()
            return self.length, self.height
    
    @property
    def image(self):
        if self.rendered:
            return self.rgb, self.alpha
        else:
            self.render()
            return self.rgb, self.alpha

    def render(self, **kwargs):
        self.length, self.height = self.word_font.getsize(self.content)
        self.height += self.outlinesize*2

        have_emoji = bool(self.have_emoji(self.content))
        if have_emoji:
            self.word_split = [x for x in self.match_emoji.split(self.content) if len(x)>0]
            self.length *= 2
        else:
            self.word_split = [self.content]

        rgba = Image.new('RGBA',(self.length,self.height))
        draw = ImageDraw.Draw(rgba)

        if self.color[0:2] == '0x':
            color = self.color[2:8]
        else:
            color = self.color
        r = int(color[0:2],16)
        g = int(color[2:4],16)
        b = int(color[4:6],16)
        a = int(self.opacity,16)
        out_a = int(self.outlinecolor[0:2],16)
        out_r = int(self.outlinecolor[2:4],16)
        out_g = int(self.outlinecolor[4:6],16)
        out_b = int(self.outlinecolor[4:6],16)

        x = 0
        for word in self.word_split:
            if self.match_emoji.search(word):
                y = int(self.height*0.2)
                draw.text(xy=(x,y),text=word,font=self.emoji_font,embedded_color=True)
                x += self.emoji_font.getsize(word)[0]
            else:
                draw.text(xy=(x,0),text=word,font=self.word_font,fill=(r,g,b,a),stroke_width=self.outlinesize,stroke_fill=(out_r,out_g,out_b,out_a))
                x += self.word_font.getsize(word)[0]
        
        if have_emoji:
            self.length = x
            rgba = rgba.crop((0,0,self.length,self.height))
        
        self.alpha = rgba.split()[-1]
        self.alpha.point(lambda x:x>a and a)
        self.rgb = rgba.convert('RGB')
        self.rendered = True


class ImageDanmaku(BaseDanmaku):
    def __init__(self, st, et, sp, ep, content, fontsize, opacity, vdir=None, **kwargs):
        self.st = st
        self.et = et
        self.sp = sp
        self.ep = ep
        self.content = content
        self.fontsize = fontsize
        self.opacity = opacity
        self.vdir = vdir if vdir else os.getcwd()
        self.rendered = False

    @property
    def size(self):
        if self.rendered:
            return self.length, self.height
        else:
            self.load_image()
            return self.length, self.height
    
    @property
    def image(self):
        if self.rendered:
            return self.rgb, self.alpha
        else:
            self.load_image()
            return self.rgb, self.alpha
    
    def load_image(self):
        imp = None
        if exists(self.content):
            imp = self.content
        elif exists(join(self.vdir,self.content)):
            imp = join(self.vdir,self.content)
        
        if not imp:
            self.length = self.height = 0
            self.rgb = self.alpha = None
        
        rgba = Image.open(imp)
        a = int(self.opacity*255)
        self.alpha = rgba.split()[-1]
        self.alpha.point(lambda x:x>a and a)
        self.rgb = rgba.convert('RGB')
        self.rendered = True
        
    
def parser_ass(filename):
    meta_info = {
        'width': 0,
        'height': 0,
        'validheight': 0,
        'style': {},
        'danmu': [],
    }
    with open(filename, encoding='utf8') as f:
        for row in f.readlines():
            if row.startswith('PlayResX:'):
                meta_info['width'] = int(row.split(':')[-1].strip())
            elif row.startswith('PlayResY:'):
                meta_info['height'] = int(row.split(':')[-1].strip())
            elif row.startswith('Style:'):
                try:
                    row = row.split(':')[-1].strip()
                    info = row.split(',')
                    name = info[0]
                    style = {
                        'font': info[1],
                        'fontsize': int(info[2]),
                        'color': BGR2RGB(info[3][-6:]),
                        'opacity': hex(255-int(info[3][-8:-6],16))[2:].zfill(2),
                        'outlinecolor': info[5][-8:],
                        'outlinesize': float(info[16]),
                    }
                    meta_info['style'][name] = style
                except:
                    pass
            elif row.startswith('Dialogue:'):
                try:
                    row = row.split(':',1)[-1].strip()
                    info = row.split(',',9)
                    origin_style = meta_info['style'][info[3]]
                    event = {
                        'type': 'text',
                        'st': hms2sec(*info[1].split(':')),
                        'et': hms2sec(*info[2].split(':')),
                        **origin_style,
                    }
                    if event['st'] > event['et']:
                        continue

                    text = info[-1]
                    try:
                        movepos = re.findall(r'{\\move\(.*?\)}', text)[0]
                        x0,y0,x1,y1 = [int(x) for x in movepos[7:-2].split(',')]
                        event['sp'] = (x0,y0)
                        event['ep'] = (x1,y1)
                        if meta_info['validheight'] < max(y0,y1):
                            meta_info['validheight'] = min(max(y0,y1)+5,meta_info['height'])
                        text = re.sub(r'{\\move\(.*\)}','', text)
                    except:
                        pass
                    try:
                        newcolor = re.findall(r'{\\1c&H.*&}', text)[0][-10:-2]
                        event['opacity'] = hex(255-int(newcolor[:2],16))[2:].zfill(2)
                        event['color'] = BGR2RGB(newcolor[2:])
                        text = re.sub(r'{\\1c&H.*&}','', text)
                    except:
                        pass
                    event['content'] = text
                    meta_info['danmu'].append(event)
                except:
                    pass
            elif row.startswith('Picture:'):
                try:
                    row = row.split(':',1)[-1].strip()
                    info = row.split(',',9)
                    origin_style = meta_info['style'][info[3]]
                    event = {
                        'type': 'image',
                        'st': hms2sec(*info[1].split(':')),
                        'et': hms2sec(*info[2].split(':')),
                        **origin_style,
                    }
                    if event['st'] > event['et']:
                        continue
                    
                    text = info[-1]
                    try:
                        movepos = re.findall(r'{\\move\(.*?\)}', text)[0]
                        x0,y0,x1,y1 = [int(x) for x in movepos[7:-2].split(',')]
                        event['sp'] = (x0,y0)
                        event['ep'] = (x1,y1)
                        if meta_info['validheight'] < max(y0,y1):
                            meta_info['validheight'] = min(max(y0,y1)+5,meta_info['height'])
                        text = re.sub(r'{\\move\(.*\)}','', text)
                    except:
                        pass
                    try:
                        newcolor = re.findall(r'{\\1c&H.*&}', text)[0][-10:-2]
                        event['opacity'] = hex(255-int(newcolor[:2],16))[2:].zfill(2)
                        event['color'] = BGR2RGB(newcolor[2:])
                        text = re.sub(r'{\\1c&H.*&}','', text)
                    except:
                        pass
                    event['content'] = text
                    meta_info['danmu'].append(event)
                except:
                    pass
    return meta_info
