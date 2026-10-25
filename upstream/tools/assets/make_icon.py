# SPDX-License-Identifier: GPL-3.0-only
"""做 Windows 导出用的多尺寸 .ico: 输入原版 exe (抽 RT_GROUP_ICON) 或任意图片 (居中裁方):
make_icon.py <Swordman.exe | 图片> <out.ico>"""
import io, struct, sys
from PIL import Image

if sys.argv[1].lower().endswith(".exe"):
    # 极简 PE 资源表解析 (只找 RT_ICON=3 与 RT_GROUP_ICON=14)
    d=open(sys.argv[1],'rb').read()
    pe=struct.unpack_from('<I',d,0x3c)[0]
    nsec=struct.unpack_from('<H',d,pe+6)[0]; optsz=struct.unpack_from('<H',d,pe+20)[0]
    opt=pe+24; magic=struct.unpack_from('<H',d,opt)[0]
    ddoff=opt+(96 if magic==0x10b else 112)
    rva,size=struct.unpack_from('<II',d,ddoff+2*8)
    secs=[]
    for i in range(nsec):
        o=opt+optsz+i*40
        vs,va,rs,ra=struct.unpack_from('<IIII',d,o+8)
        secs.append((va,max(vs,rs),ra))
    def off(r):
        for va,sz,ra in secs:
            if va<=r<va+sz: return r-va+ra
    base=off(rva)
    def entries(o):
        n=sum(struct.unpack_from('<HH',d,o+12))
        for i in range(n):
            name,ptr=struct.unpack_from('<II',d,o+16+i*8)
            yield name,ptr
    def leaf(ptr):
        while ptr&0x80000000:
            ptr=next(entries(base+(ptr&0x7fffffff)))[1]
        r,sz=struct.unpack_from('<II',d,base+ptr)
        return d[off(r):off(r)+sz]
    res={}
    for t,p in entries(base):
        if t in (3,14):
            for n,p2 in entries(base+(p&0x7fffffff)):
                res[(t,n)]=leaf(p2)
    grp = [v for k, v in res.items() if k[0] == 14][0]
    # 取组里最大的一张, 拼成单图 .ico 交给 Pillow 解码
    w, h, cc, r, pl, bc, sz, iid = max((struct.unpack_from('<BBBBHHIH', grp, 6 + i * 14) for i in range(struct.unpack_from('<H', grp, 4)[0])), key=lambda e: e[0] or 256)
    b = res[(3, iid)]
    src = Image.open(io.BytesIO(struct.pack('<HHHBBBBHHII', 0, 1, 1, w, h, cc, r, pl, bc, len(b), 22) + b)).convert('RGBA')
else:
    src = Image.open(sys.argv[1]).convert('RGBA')
    if src.width != src.height:  # 居中裁方 (.ico 各档都是正方形, 直接 resize 会把非方形图拉变形)
        s = min(src.size)
        src = src.crop(((src.width - s) // 2, (src.height - s) // 2, (src.width + s) // 2, (src.height + s) // 2))
# 像素字图标: 小尺寸平滑缩, 大尺寸最近邻放大保持字形锐利
sizes = [16, 24, 32, 48, 64, 128, 256]
frames = [src.resize((s, s), Image.NEAREST if s >= src.width else Image.LANCZOS) for s in sizes]
frames[-1].save(sys.argv[2], format='ICO', sizes=[(s, s) for s in sizes], append_images=frames[:-1])
print('图标', sys.argv[2], sizes)
