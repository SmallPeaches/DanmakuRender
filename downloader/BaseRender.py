import os
from PIL import Image,ImageDraw,ImageFont

class DmItem():
    def __init__(self,time,content,color,fontsize,font,opacity) -> None:
        self.time = time
        self.content = content
        self.color = color
        self.fontsize = fontsize
        self.font = font
        self.opacity = opacity
        self.length, self.height = font.getsize(content)
        self.height += 2

    def render(self,track):
        self.track = track
        self.bitmap = Image.new('RGBA',(self.length,self.height))
        draw = ImageDraw.Draw(self.bitmap)

        if self.color[0:2] == '0x':
                color = self.color[2:8]
        else:
            color = self.color
        r = int(color[0:2],16)
        g = int(color[2:4],16)
        b = int(color[4:6],16)
        a = int(self.opacity*256)

        draw.text(xy=(0,0),text=self.content,font=self.font,fill=(r,g,b,a),stroke_width=1,stroke_fill=(10,10,10,a))
        self.bitmask = self.bitmap.split()[-1]
        self.bitmap = self.bitmap.convert('RGB')
    
class DmScreen():
    def __init__(self,width,height,dmstartpixel,fps,margin,dmrate,font,fontsize,overflow_op,dmduration,opacity,engine='PIL') -> None:
        self.height = height
        self.width = width
        self.fps = fps
        self.dmstartpixel = dmstartpixel
        self.dmrate = dmrate
        self.fontsize = fontsize
        self.font = ImageFont.truetype(font,fontsize)
        self.margin = margin
        self.overflow_op = overflow_op
        self.duration = dmduration
        self.opacity = opacity
        self.dmlist = []
        
        self.ntrack = int((height*dmrate - self.dmstartpixel)/(fontsize+margin))
        self.trackinfo = [None for _ in range(self.ntrack)]

    def add(self,dm):
        if not isinstance(dm,DmItem):
            dm = DmItem(float(dm['time']),dm['content'],dm['color'],self.fontsize,self.font,self.opacity)
        
        tid = 0
        maxbias = -1
        
        def calc_bias(dm,tic):
            if not dm:
                return self.width
            bias = (tic - dm.time)*(dm.length+self.width)/self.duration - dm.length 
            return bias
        
        for i,tinfo in enumerate(self.trackinfo):
            bias = calc_bias(tinfo,dm.time)
            if bias > 0.4*self.width:
                tid = i
                maxbias = bias
                break
            if bias > maxbias:
                maxbias = bias
                tid = i

        if maxbias<0.1*self.width and self.overflow_op == 'ignore':
            return False
        
        dm.render(tid)
        self.trackinfo[tid] = dm
        self.dmlist.append(dm)

        while dm.time-self.dmlist[0].time > self.dmlist[0].time*2:
            self.dmlist.pop(0)

        return True

    def render(self,fid):        
        sec = fid/self.fps
        frame = Image.new(mode='RGBA', size=(self.width,self.height))

        for dm in self.dmlist:
            if dm.time < sec-self.duration:
                continue
            if dm.time > sec:
                break
            
            x = self.width - (sec-dm.time)/self.duration*(dm.length+self.width)
            y = self.dmstartpixel + (self.fontsize+self.margin)*dm.track
            x,y = int(x),int(y)

            frame.paste(dm.bitmap,(x,y),dm.bitmask)
            
        return frame

        
