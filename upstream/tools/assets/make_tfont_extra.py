#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""生成 tools/assets/tfont_extra.json: 原版字库 Tfont.dat 里没有字形、游戏文本却用到的字, 借 Ark Pixel Font 12px (SIL OFL 1.1, TakWolf) 的字形补。
结果入库 (只有十几个字、每字 24 字节, 许可文本 tools/assets/tfont_extra.OFL.txt), 平时不用跑这个脚本; 要重生成时:

  1. 从 https://github.com/TakWolf/ark-pixel-font/releases 下 ark-pixel-font-12px-monospaced-otb-<版本>.zip, 解压到一个新目录
  2. python3 tools/assets/make_tfont_extra.py --src <那个目录>

做法: 12x12 字格, 格式同 Tfont (12 行 x 2 字节, 高位在左), 位图按 Ark 的 EBLC 上升线对到字格行上 (与原版字模的行位置一致: 汉字占第 0~10 行, ASCII 字母第 2~9 行)。
字形取 Ark 的简体 (zh_hans) 版, 因为原版字库本来就是简体字形; 有简体写法的字 (蓮→莲, 喲→哟) 画简体写法, 其余照字本身画。
Tfont 里「布 錘 噁 墬」在变体字码位上有字形、「鼩」Ark 也没有: 它们不走这里, 见 make_tfont.py 的 ALIAS / COMPOSE。
"""
import argparse
import json
import os
import sys

from fontTools.ttLib import TTFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "tfont_extra.json")
SRC_CHAR = {"喲": "哟", "蓮": "莲"}      # 画简体写法的字 (没列的照字本身画)
CHARS = "喲旛欸猦祂蓮袪褟豨鵿鷏鷡闇" + "}~"
SHIFT = {"}": 1}                          # 原版的 { 占第 2~11 行, Ark 的占第 1~10 行, 与它配对的 } 下移一行
VERSION = "2026.10.25"


def glyph(font, ch, shift=0):
    cmap = font.getBestCmap()
    name = cmap.get(ord(ch))
    if name is None:
        sys.exit("Ark Pixel 没有「%s」" % ch)
    strike = font["EBDT"].strikeData[0][name]
    mt = strike.metrics
    asc = font["EBLC"].strikes[0].bitmapSizeTable.hori.ascender
    rows = [0] * 12
    for i in range(mt.height):
        bits = strike.getRow(i, bitDepth=1, metrics=mt)
        r = asc - mt.horiBearingY + i + shift
        for c in range(mt.width):
            x = mt.horiBearingX + c
            if bits[c >> 3] >> (7 - (c & 7)) & 1 and 0 <= r < 12 and 0 <= x < 12:
                rows[r] |= 0x8000 >> x
    return b"".join(v.to_bytes(2, "big") for v in rows).hex()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--src", required=True, help="解压后的 ark-pixel-font-12px-monospaced-otb 目录")
    a = ap.parse_args()
    font = TTFont(os.path.join(a.src, "ark-pixel-12px-monospaced-zh_hans.otb"))
    out = {
        "format": "tfont-extra/1",
        "note": "原版 Tfont.dat 没有字形、游戏文本用到的字; 24 字节 = 12 行 x 2 字节, 高位在左 (同 Tfont)。生成: tools/assets/make_tfont_extra.py",
        "source": {"font": "Ark Pixel Font 12px monospaced zh_hans", "version": VERSION, "author": "TakWolf",
                   "url": "https://github.com/TakWolf/ark-pixel-font", "license": "SIL OFL 1.1 (tools/assets/tfont_extra.OFL.txt)"},
        "glyphs": {ch: glyph(font, SRC_CHAR.get(ch, ch), SHIFT.get(ch, 0)) for ch in CHARS},
    }
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print("写入 %s (%d 个字)" % (os.path.relpath(OUT), len(out["glyphs"])))


if __name__ == "__main__":
    main()
