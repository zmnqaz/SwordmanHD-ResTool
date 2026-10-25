#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Godot 4 .pck 的写入与读取 (纯 Python, 不需要 Godot)。

资源包 = 把文件原样排在一起 + 目录表, 没有压缩、没有加密、不导入。这样生成资源包的工具不必下载 Godot (约 70 MB)。
格式 (pack format 4, Godot 4.7; 与 Godot 的 PCKPacker 逐字节一致, 见 tools/tests/test_pck_writer.py):
  头    "GDPC" | format=4 | 引擎版本 major minor patch | flags(2 = 偏移相对 file_base) | file_base u64 | dir_offset u64 | 16 个保留 u32
  数据  从 file_base (头部补零到 32 字节对齐) 起, 依次放每个文件, 每个文件后补零到 32 字节对齐 (最后一个也补)
  目录  dir_offset 处: 文件数 u32, 然后每个文件: 路径长度 u32 (补到 4 的倍数) | 路径 UTF-8 (不含 res://, 补零) | 偏移 u64 (相对 file_base) | 大小 u64 | MD5 16 字节 | flags u32 (0)

  python3 tools/assets/pck_writer.py pack  <清单> <输出.pck>   清单每行 "源文件<TAB>res://包内路径" (同 tools/release/pack_pck.gd)
  python3 tools/assets/pck_writer.py check <x.pck> ...        校验目录与每个文件的 MD5
  python3 tools/assets/pck_writer.py list  <x.pck>            列出包内文件
"""
import hashlib
import os
import struct
import sys

MAGIC = b"GDPC"
PACK_FORMAT_VERSION = 4
GODOT_VERSION = (4, 7, 2)   # 写进头部的引擎版本; 加载它的 Godot 必须不低于这个版本
PACK_REL_FILEBASE = 2
ALIGNMENT = 32
CHUNK = 4 << 20


def _pad(n, a):
    return (a - n % a) % a


def write_pck(out, items, version=GODOT_VERSION, alignment=ALIGNMENT):
    """把 items [(源文件路径, 'res://包内路径')] 按顺序打成 out。返回文件数。"""
    entries = []
    with open(out, "wb") as f:
        f.write(struct.pack("<4sIIIIIQQ", MAGIC, PACK_FORMAT_VERSION, *version, PACK_REL_FILEBASE, 0, 0))
        f.write(b"\0" * 64)                                   # 保留字段
        file_base = f.tell() + _pad(f.tell(), alignment)
        f.write(b"\0" * (file_base - f.tell()))
        for src, res in items:
            if not res.startswith("res://"):
                raise ValueError("包内路径要以 res:// 开头: %s" % res)
            off = f.tell() - file_base
            md5, size = hashlib.md5(), 0
            with open(src, "rb") as g:
                while True:
                    b = g.read(CHUNK)
                    if not b:
                        break
                    md5.update(b)
                    size += len(b)
                    f.write(b)
            f.write(b"\0" * _pad(f.tell(), alignment))      # 每个文件后补齐, 包括最后一个 (目录表因此也从对齐处开始)
            entries.append((res[len("res://"):].encode("utf-8"), off, size, md5.digest()))
        dir_offset = f.tell()
        f.write(struct.pack("<I", len(entries)))
        for path, off, size, md5 in entries:
            pad = _pad(len(path), 4)
            f.write(struct.pack("<I", len(path) + pad) + path + b"\0" * pad)
            f.write(struct.pack("<QQ", off, size) + md5 + struct.pack("<I", 0))
        f.seek(24)
        f.write(struct.pack("<QQ", file_base, dir_offset))
    return len(entries)


def read_pck(path):
    """返回 [(包内路径, 绝对偏移, 大小, md5 字节)]; 格式不对抛 ValueError。"""
    with open(path, "rb") as f:
        head = f.read(40)
        if len(head) < 40 or head[:4] != MAGIC:
            raise ValueError("%s 不是 Godot 资源包" % path)
        _, fmt, _, _, _, flags, file_base, dir_offset = struct.unpack("<4sIIIIIQQ", head)
        if fmt != PACK_FORMAT_VERSION or flags != PACK_REL_FILEBASE:
            raise ValueError("%s 的格式 (v%d, flags %d) 不是本工具写的那一种" % (path, fmt, flags))
        f.seek(dir_offset)
        n, = struct.unpack("<I", f.read(4))
        out = []
        for _ in range(n):
            plen, = struct.unpack("<I", f.read(4))
            p = f.read(plen).rstrip(b"\0").decode("utf-8")
            off, size = struct.unpack("<QQ", f.read(16))
            md5 = f.read(16)
            f.read(4)
            out.append((p, file_base + off, size, md5))
        return out


def check_pck(path):
    """校验每个文件的 MD5 与目录是否越界; 返回文件数, 有问题抛 ValueError。"""
    total = os.path.getsize(path)
    ents = read_pck(path)
    with open(path, "rb") as f:
        for p, off, size, md5 in ents:
            if off + size > total:
                raise ValueError("%s: %s 超出文件末尾" % (path, p))
            f.seek(off)
            h, left = hashlib.md5(), size
            while left:
                b = f.read(min(CHUNK, left))
                if not b:
                    raise ValueError("%s: %s 数据不全" % (path, p))
                h.update(b)
                left -= len(b)
            if h.digest() != md5:
                raise ValueError("%s: %s 的 MD5 对不上" % (path, p))
    return len(ents)


def main(argv):
    if len(argv) >= 3 and argv[0] == "pack":
        items = []
        with open(argv[1], encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\r\n")
                if line:
                    src, res = line.split("\t")
                    items.append((src, res))
        print("%s %d 个文件" % (argv[2], write_pck(argv[2], items)))
        return 0
    if len(argv) >= 2 and argv[0] == "check":
        for p in argv[1:]:
            print("%s: %d 个文件, MD5 全部一致" % (os.path.basename(p), check_pck(p)))
        return 0
    if len(argv) == 2 and argv[0] == "list":
        for p, off, size, _ in read_pck(argv[1]):
            print("%10d %10d  %s" % (off, size, p))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
