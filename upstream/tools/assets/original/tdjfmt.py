#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""天地劫-神魔至尊传 原版资源格式解码库 (与引擎无关)。

  Saf         SAF 动画文件: 帧参数、贴图构成、30x24 像素块、内嵌音效
  load_map    FB2 + MPL 地图背景
  decode_block / blocks_to_image   30x24 像素块 RLE 解码与拼图
"""
import struct
import sys
import wave

import numpy as np
from PIL import Image

BLOCK_W, BLOCK_H = 30, 24
BLOCK_PX = BLOCK_W * BLOCK_H
SAF_MAGIC = b"SAF\x05"


class SafError(Exception):
    pass


def u16(b, o):
    return struct.unpack_from("<H", b, o)[0]


def s16(b, o):
    return struct.unpack_from("<h", b, o)[0]


def u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def decode_block(data, where=""):
    """解压一个 30x24 像素块, 返回 (rgb555 数组, 不透明掩码)。
    操作码: 0xC0|n 同色重复 n+1 次; 0x80|n 照抄 n+1 个颜色; 0x40|n / 0x00|n 跳过 n+1 个像素 (透明)。"""
    color = np.zeros(BLOCK_PX, dtype=np.uint16)
    mask = np.zeros(BLOCK_PX, dtype=bool)
    p = j = 0
    while j < len(data):
        op = data[j]
        n = min((op & 0x1F) + 1, BLOCK_PX - p)  # 个别原版数据 (Stage23/Eanm_04) 会写出块外, 截断
        if n <= 0:
            print(f"警告: {where}: 像素块数据超出 30x24, 已截断", file=sys.stderr)
            break
        if op & 0x80:
            if op & 0x40:
                color[p:p + n] = u16(data, j + 1)
                j += 3
            else:
                color[p:p + n] = np.frombuffer(data, dtype="<u2", count=n, offset=j + 1)
                j += 1 + 2 * ((op & 0x1F) + 1)
            mask[p:p + n] = True
        else:
            j += 1
        p += n
    return color, mask


def blocks_to_image(indices, bw, bh, blocks, where=""):
    """按行优先把 bw*bh 个块拼成 RGBA 图像; 负编号为空块 (全透明)。"""
    rgba = np.zeros((bh * BLOCK_H, bw * BLOCK_W, 4), dtype=np.uint8)
    cache = {}
    for k, idx in enumerate(indices):
        if idx < 0:
            continue
        if idx >= len(blocks):
            raise SafError(f"{where}: 引用不存在的像素块 {idx}")
        if idx not in cache:
            col, mask = decode_block(blocks[idx], where)
            col = col.reshape(BLOCK_H, BLOCK_W)
            rgb = np.stack([(col >> 10) & 0x1F, (col >> 5) & 0x1F, col & 0x1F], axis=-1).astype(np.uint8)
            rgb = (rgb << 3) | (rgb >> 2)  # 5 位扩展到 8 位
            alpha = np.where(mask.reshape(BLOCK_H, BLOCK_W), 255, 0).astype(np.uint8)
            cache[idx] = np.dstack([rgb, alpha])
        y, x = (k // bw) * BLOCK_H, (k % bw) * BLOCK_W
        rgba[y:y + BLOCK_H, x:x + BLOCK_W] = cache[idx]
    return Image.fromarray(rgba, "RGBA")


class Saf:
    """SAF 文件结构:
    0x00  12 字节文件头 (SAF\\x05 ...)
    0x0C  4 个区段描述, 每个 10 字节: count(u16) table_offset(u32) data_length(u32)
          区段 0 帧参数, 区段 1 贴图构成, 区段 2 30x24 像素块, 区段 3 音效
          table_offset 指向 count 个 u32 偏移; 第 i 项数据 = [tab[i], tab[i+1]), 最后一项到 table_offset+data_length
    0x34  32 个 s16: 各动作 (站立/移动/...) 的帧数, 对应 Unity 的 safHead.count3
    帧参数 = 10 字节帧头 (sound,time,hit,color,shake,unk,count) + count 个 13 字节部件
    贴图构成 = 宽(块) 高(块) + 宽*高 个 s16 像素块编号
    音效 = 声道(u8) 位深(u8) 采样率(u16) 长度(u32) + PCM, 均为小端
    """

    def __init__(self, path):
        self.path = path
        with open(path, "rb") as f:
            self.buf = f.read()
        if self.buf[:4] != SAF_MAGIC:
            raise SafError(f"{path}: 不是 SAF 文件")
        self.frames, self.constructs, self.units, self.waves = [self._read_section(0x0C + i * 10) for i in range(4)]
        self.counts = list(struct.unpack_from("<32h", self.buf, 0x34))
        self._validate()

    def _read_section(self, hdr):
        count = u16(self.buf, hdr)
        table = u32(self.buf, hdr + 2)
        length = u32(self.buf, hdr + 6)
        if count == 0:
            return []
        offs = [u32(self.buf, table + 4 * i) for i in range(count)]
        offs.append(table + length)
        items = []
        for i in range(count):
            a, b = offs[i], offs[i + 1]
            if not (0 < a <= b <= len(self.buf)):
                raise SafError(f"{self.path}: 区段数据越界 hdr=0x{hdr:x} item={i} [{a:#x},{b:#x})")
            items.append(self.buf[a:b])
        return items

    def _validate(self):
        for i, fr in enumerate(self.frames):
            n = s16(fr, 8)
            if len(fr) != 10 + 13 * n:
                raise SafError(f"{self.path}: 帧 {i} 长度 {len(fr)} 与部件数 {n} 不符")
        for i, c in enumerate(self.constructs):
            bw, bh = u16(c, 0), u16(c, 2)
            if len(c) != 4 + 2 * bw * bh:
                raise SafError(f"{self.path}: 贴图 {i} 长度 {len(c)} 与 {bw}x{bh} 块不符")
        for i, w in enumerate(self.waves):
            if u32(w, 4) != len(w) - 8:
                raise SafError(f"{self.path}: 音效 {i} 长度不符")

    def construct_size(self, idx):
        c = self.constructs[idx]
        return u16(c, 0) * BLOCK_W, u16(c, 2) * BLOCK_H

    def construct_image(self, idx):
        c = self.constructs[idx]
        bw, bh = u16(c, 0), u16(c, 2)
        indices = struct.unpack_from(f"<{bw * bh}h", c, 4)
        return blocks_to_image(indices, bw, bh, self.units, f"{self.path} 贴图 {idx}")

    def write_wave(self, idx, path):
        """写 PCM wav。自己写头而不用 wave 模块: 8 位单声道的数据长度常为奇数, RIFF 规定奇数长度的块后补 1 字节对齐
        (wave 模块不补), Godot 读完数据要跳过补位字节, 缺了会报 seek 越界错误 (23/3318 个音效); 偶数长度的文件与 wave 模块输出逐字节相同。"""
        w = self.waves[idx]
        ch, bits, rate, data = w[0], w[1], u16(w, 2), bytes(w[8:])
        width = bits // 8
        pad = b"\x00" if len(data) & 1 else b""
        with open(path, "wb") as f:
            f.write(b"RIFF" + struct.pack("<I", 36 + len(data) + len(pad)) + b"WAVE")
            f.write(b"fmt " + struct.pack("<IHHIIHH", 16, 1, ch, rate, rate * ch * width, ch * width, bits))
            f.write(b"data" + struct.pack("<I", len(data)) + data + pad)

    def to_faf(self):
        """生成 GameAnimation.load() 读取的二进制格式; 帧参数与 SAF 原始字节一致, 直接拷贝。"""
        out = bytearray()
        out += struct.pack("<hh", len(self.frames), len(self.constructs))
        out += struct.pack("<32h", *self.counts)
        for fr in self.frames:
            out += fr
        for i in range(len(self.constructs)):
            out += struct.pack("<hh", *self.construct_size(i))
        return bytes(out)


def load_map(fb2_path, mpl_path):
    """战场/RPG 地图背景: MPL = 'MPL' 头 + 宽(块,@7) 高(块,@9) + 块编号表(@0x0B); FB2 = 块数量(@0x0B) + 偏移表(@0x0F)。"""
    with open(mpl_path, "rb") as f:
        mpl = f.read()
    with open(fb2_path, "rb") as f:
        fb2 = f.read()
    bw, bh = s16(mpl, 7), s16(mpl, 9)
    indices = struct.unpack_from(f"<{bw * bh}h", mpl, 0x0B)
    n = u16(fb2, 0x0B)
    offs = [u32(fb2, 0x0F + 4 * i) for i in range(n)] + [len(fb2)]
    blocks = [fb2[offs[i]:offs[i + 1]] for i in range(n)]
    return blocks_to_image(indices, bw, bh, blocks, fb2_path)
