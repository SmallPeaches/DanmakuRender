import struct
import json
import re

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

from downloader.getrealurl import get_stream_url
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