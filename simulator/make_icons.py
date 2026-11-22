"""Generate installable PNG icons using Python standard library only."""
import math
import struct
import sys
import zlib
from pathlib import Path

def create_icon(path, size):
    colors={"bg":(11,23,40,255),"panel":(20,37,60,255),
            "outline":(226,155,53,255),"ball":(245,180,66,255),
            "highlight":(255,226,166,255),"center":(111,191,229,255)}
    center=size/2
    rows=[]
    def within_round_rect(x,y):
        edge=size*.078
        rad=size*.17
        xmin,ymin=edge,edge
        xmax,ymax=size-edge,size-edge
        px=min(max(x,xmin+rad),xmax-rad)
        py=min(max(y,ymin+rad),ymax-rad)
        return (x-px)**2+(y-py)**2<=rad**2
    dots=[]
    for k in range(6):
        a=2*math.pi*k/6-math.pi/2
        dots.append((center+size*.19*math.cos(a),center+size*.19*math.sin(a)))
    for y in range(size):
        raw=bytearray([0])
        for x in range(size):
            r=math.hypot(x-center,y-center)
            rgb=colors["bg"]
            if within_round_rect(x,y):
                rgb=colors["panel"]
            if size*.28<r<size*.31:rgb=colors["outline"]
            for dx,dy in dots:
                if (x-dx)**2+(y-dy)**2<(size*.07)**2:rgb=colors["ball"]
            if r<size*.084:rgb=colors["center"]
            raw.extend(rgb)
        rows.append(bytes(raw))
    def chunk(tag,data):
        return struct.pack(">I",len(data))+tag+data+struct.pack(">I",zlib.crc32(tag+data)&0xffffffff)
    png=b"\x89PNG\r\n\x1a\n"+chunk(b"IHDR",struct.pack(">IIBBBBB",size,size,8,6,0,0,0))
    png+=chunk(b"IDAT",zlib.compress(b"".join(rows),9))+chunk(b"IEND",b"")
    Path(path).write_bytes(png)

if __name__=="__main__":
    output=Path(sys.argv[1]) if len(sys.argv)>1 else Path("site/simulator")
    output.mkdir(parents=True,exist_ok=True)
    for n in (192,512):create_icon(output/f"icon-{n}.png",n)
