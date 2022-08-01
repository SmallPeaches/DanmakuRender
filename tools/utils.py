import struct
import json
import re
import subprocess
from downloader.getrealurl import get_stream_url

BANNED_WORDS = ['\{','赞']

def get_lnk_file(path):
    target = ''
    with open(path, 'rb') as stream:
        content = stream.read()
        # skip first 20 bytes (HeaderSize and LinkCLSID)
        # read the LinkFlags structure (4 bytes)
        lflags = struct.unpack('I', content[0x14:0x18])[0]
        position = 0x18
        # if the HasLinkTargetIDList bit is set then skip the stored IDList 
        # structure and header
        if (lflags & 0x01) == 1:
            position = struct.unpack('H', content[0x4C:0x4E])[0] + 0x4E
        last_pos = position
        position += 0x04
        # get how long the file information is (LinkInfoSize)
        length = struct.unpack('I', content[last_pos:position])[0]
        # skip 12 bytes (LinkInfoHeaderSize, LinkInfoFlags, and VolumeIDOffset)
        position += 0x0C
        # go to the LocalBasePath position
        lbpos = struct.unpack('I', content[position:position+0x04])[0]
        position = last_pos + lbpos
        # read the string at the given position of the determined length
        size= (length + last_pos) - position - 0x02
        temp = struct.unpack('c' * size, content[position:position+size])
        target = ''.join([chr(ord(a)) for a in temp])
    return target

def read_json(filename):
    """ Parse a JSON file
        First remove comments and then use the json module package
        Comments look like :
            // ...
    """
    res = []
    with open(filename,'r',encoding='utf-8') as f:
        all_lines = f.readlines()
    for line in all_lines:
        if not line.strip().startswith("//"):
            res.append(line)
    str_res = ""
    for i in res:
        str_res += i
    return json.loads(str_res.encode('gbk'))

def onair(url):
    try:
        get_stream_url(url)
        return True
    except Exception as e:
        return False

def url_available(url):
    try:
        get_stream_url(url)
        return True
    except Exception as e:
        if '未开播' in str(e):
            return True
        else:
            return False

def get_video_info(ffmpeg,video,header=None):
    if 'http' in video:
        ffmpeg_args = [ffmpeg, '-headers', ''.join('%s: %s\r\n' % x for x in header.items()),'-i', video]
    else:
        ffmpeg_args = [ffmpeg, '-i', video]
    proc = subprocess.Popen(ffmpeg_args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    # proc = subprocess.Popen(ffmpeg_args, stdout=sys.stdout, stderr=subprocess.STDOUT)
    info = {}
    lines = [l.decode('utf-8') for l in proc.stdout.readlines()]

    for line in lines:
        if ' displayWidth ' in line:
            info['width'] = int(line.split(':')[-1])
        elif ' displayHeight ' in line:
            info['height'] = int(line.split(':')[-1])
        elif ' fps ' in line:
            info['fps'] = float(line.split(':')[-1])
        elif 'Duration:' in line:
            tic = line.split(':')[1].split(',')[0]
            hrs,mins,secs,fs = [int(x) for x in re.split('[:.]',tic)]
            info['duration'] = hrs*3600+mins*60+secs+0.01*fs
    
    if len(info) < 4:
        for line in lines:
            if 'Video:' in line:
                metadata = line.split(',')
                for x in metadata:
                    if 'fps' in x:
                        info['fps'] = float([i for i in x.split(' ') if len(i)>0][0])
                    elif 'x' in x:
                        wh = [i for i in x.split(' ') if len(i)>0][0]
                        if len(wh.split('x')) == 2:
                            info['width'] = int(wh.split('x')[0])
                            info['height'] = int(wh.split('x')[1])
                    if len(info) == 3:
                        break
    return info


def danmu_available(dm:dict) -> bool:
    if not (dm.get('content') and dm.get('time') and dm.get('color') and dm.get('name')):
        return False
    for word in BANNED_WORDS:
        if word in dm['content']:
            return False
    return True
