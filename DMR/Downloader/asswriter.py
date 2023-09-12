from datetime import datetime
import threading
from DMR.danmaku import SimpleDanmaku
from DMR.utils import *

__all__ = ['AssWriter']

class AssWriter():
    """
    ASS弹幕写入器，定义了ASS弹幕格式和信息，用于流式处理弹幕
    """
    def __init__(self,
                 description:str,
                 width:int,
                 height:int,
                 dst:int,
                 dmrate:float,
                 font:str,
                 fontsize:int,
                 margin_h:int,
                 margin_w:int,
                 dmduration:float,
                 opacity:float,
                 auto_fontsize:bool,
                 outlinecolor:str,
                 outlinesize:int,
                 **kwargs) -> None:
        self.description = description
        self.height = height
        self.width = width
        self.dmrate = dmrate
        if auto_fontsize:
            self.fontsize = int(height / 1080 * fontsize)
        else:
            self.fontsize = int(fontsize)
        self.font = font

        self.margin_h = margin_h if margin_h > 1 else margin_h * self.height
        self.margin_w = margin_w if margin_w > 1 else margin_w * self.width
        self.dst = dst
        self.dmduration = dmduration
        self.opacity = hex(255-int(opacity*255))[2:].zfill(2)
        self.outlinecolor = str(outlinecolor).zfill(6)
        self.outlinesize = outlinesize
        self.kwargs = kwargs

        self._lock = threading.Lock()
        self._ntracks = int(((self.height - self.dst) * self.dmrate) / (self.fontsize + self.margin_h))

        self.meta_info = [
            '[Script Info]',
            f'Title: {self.description}',
            'ScriptType: v4.00+',
            'Collisions: Normal',
            f'PlayResX: {self.width}',
            f'PlayResY: {self.height}',
            'Timer: 100.0000',
            '',
            '[V4+ Styles]',
            'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding',
            # f'Style: Fix,Microsoft YaHei UI,25,&H66FFFFFF,&H66FFFFFF,&H66000000,&H66000000,1,0,0,0,100,100,0,0,1,2,0,2,20,20,2,0',
            f'Style: R2L,{self.font},{self.fontsize},&H{self.opacity}ffffff,,&H{self.opacity}{self.outlinecolor},,-1,0,0,0,100,100,0,0,1,{self.outlinesize},0,1,0,0,0,0',
            '',
            '[Events]',
            'Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text',
        ]
    
    def _get_length(self, string:str):
        length = 0
        for s in string:
            if len(s.encode('utf-8')) == 1:
                length += 0.5*self.fontsize
            else:
                length += self.fontsize
        return int(length)

    def open(self, filename):
        self._filename = filename
        self._track_tails = [None for _ in range(self._ntracks)]
        with self._lock, open(self._filename,'w',encoding='utf-8') as f:
            for info in self.meta_info:
                f.write(info+'\n')
    
    def add(self, danmu:SimpleDanmaku, calc_collision=True):
        """
        添加弹幕到ASS文件 
        danmu: 待添加弹幕
        calc_collision: 是否计算冲突，冲突的弹幕将会被自动忽略
        """
        tid, max_dist = 0, -1e5
        
        # 计算给出弹幕到指定弹幕的距离
        def tail_dist(tail_dm:SimpleDanmaku, tic:float):
            if not tail_dm:
                return 1e5
            dm_length = self._get_length(tail_dm.content)
            dist = (tic - tail_dm.time) * (dm_length + self.width) / self.dmduration - dm_length 
            return dist
        
        for i, tail_dm in enumerate(self._track_tails):
            dist = tail_dist(tail_dm, danmu.time)
            if dist > 0.2 * self.width and dist > self.margin_w:
                tid = i
                max_dist = dist
                break
            if dist > max_dist:
                max_dist = dist
                tid = i
        
        if calc_collision and max_dist < self.margin_w:
            return False
        
        dm_length = self._get_length(danmu.content)
        x0 = self.width
        x1 = -dm_length
        y = self.fontsize + (self.fontsize + self.margin_h) * tid

        t0 = danmu.time
        t1 = t0 + self.dmduration

        t0 = '%02d:%02d:%05.2f'%sec2hms(t0)
        t1 = '%02d:%02d:%05.2f'%sec2hms(t1)
        
        # set ass Dialogue
        dm_info = f'Dialogue: 0,{t0},{t1},R2L,,0,0,0,,'
        dm_info += '{\move(%d,%d,%d,%d)}'%(x0, y + self.dst, x1, y + self.dst)
        dm_info += '{\\alpha&H%s\\1c%s&}'%(self.opacity, BGR2RGB(danmu.color))
        content = danmu.content.replace('\n',' ').replace('\r',' ')
        dm_info += content

        with self._lock, open(self._filename, 'a', encoding='utf-8') as f:
            f.write(dm_info + '\n')
        
        self._track_tails[tid] = danmu
        return True

    def close(self):
        del self._filename
        del self._track_tails
