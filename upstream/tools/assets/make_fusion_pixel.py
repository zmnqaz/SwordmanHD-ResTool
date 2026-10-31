#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""「Fusion Pixel」字体: 12 像素点阵, 来自 Fusion Pixel Font 12px (SIL OFL 1.1, TakWolf), 简体 / 繁体界面都能选, 是独立的一项 (和原版字体不混用)。
繁体文本里的字取它的繁体 (zh_tw) 字形, 其余 (简体文本) 取简体 (zh_hans) 字形; 一个字体文件里装两套码位。

字形入库 (tools/assets/fusion_pixel.json, 简繁文本用到的全部字 + ASCII, 每字 24 字节; 许可文本 tools/assets/fusion_pixel.LICENSES.txt),
平时不用跑生成; 要重生成 (文本多了字) 时:

  1. 从 https://github.com/TakWolf/fusion-pixel-font/releases 下 fusion-pixel-font-12px-monospaced-otb-<版本>.zip, 解压到一个新目录
  2. python3 tools/assets/make_fusion_pixel.py --src <那个目录>

字格格式同 Tfont (12 行 x 2 字节, 高位在左, 位图按 EBLC 上升线对到字格行上, 与 make_tfont_extra.py 同法)。
字体里没有的字: 墬 画成 墜 的字形 (变体字), 鼩 = 鼬 的左 6 列 + 狗 的右 6 列 (与 make_tfont.py 的补法一致)。
产物 (由 make_tfont.py 一并写进 ui_theme/): fusion_pixel.ttf (度量同 tfont.ttf: 全角 1200 / 半角 600)。
"""
import argparse
import json
import os
import sys

from fontTools.ttLib import TTFont

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import make_tfont_extra as X  # noqa: E402  (glyph(): 从 Ark / Fusion 的 EBDT 取一个字的 24 字节)

DATA = os.path.join(HERE, "fusion_pixel.json")
VERSION = "2026.10.31"
OTB_TW = "fusion-pixel-12px-monospaced-zh_tw.otb"
OTB_HANS = "fusion-pixel-12px-monospaced-zh_hans.otb"
ALIAS = {"墬": "墜"}
COMPOSE = {"鼩": ("鼬", "狗", 6)}
FONT_ID = "fusionpixel"
FONT_FILE = "fusion_pixel.ttf"
FAMILY = "TDJ Fusion Pixel"


def glyph_chars(hant: dict, hans: dict) -> tuple:
    """(繁体字, 只在简体文本里出现的字): 各自带上 ASCII 可见字符只放繁体那组, 非 ASCII 字按码位排序"""
    def pick(src):
        return sorted(c for c in src if ord(c) >= 0x80 and (c == "\u3000" or not c.isspace()))
    t = [chr(c) for c in range(0x21, 0x7F)] + pick(hant)
    h = [c for c in pick(hans) if c not in set(t)]
    return t, h


def extract(font: TTFont, chars: list) -> dict:
    cmap = font.getBestCmap()
    raw = {}
    helpers = set(ALIAS.values()) | {c for l, r, _ in COMPOSE.values() for c in (l, r)}   # 补字要借用的字: 不一定在文本里, 也要取
    base = {}
    for ch in list(chars) + sorted(helpers):
        if ord(ch) in cmap:
            base[ch] = X.glyph(font, ch)
    for ch in chars:
        if ch in base:
            raw[ch] = base[ch]
    for x, y in ALIAS.items():
        if x in chars and x not in raw and y in base:
            raw[x] = base[y]
    for x, (left, right, cut) in COMPOSE.items():
        if x in chars and x not in raw and left in base and right in base:
            mask = ((1 << cut) - 1) << (16 - cut)
            lw, rw = bytes.fromhex(base[left]), bytes.fromhex(base[right])
            out = bytearray()
            for r in range(12):
                lv = int.from_bytes(lw[r * 2:r * 2 + 2], "big")
                rv = int.from_bytes(rw[r * 2:r * 2 + 2], "big")
                out += ((lv & mask) | (rv & ~mask & 0xFFF0)).to_bytes(2, "big")
            raw[x] = bytes(out).hex()
    return raw


def table(glyphs: dict):
    """glyphs {字: 24 字节十六进制} -> (字模表 bytes, cmap {码点: 字模下标}), 下标约定同 Tfont: ASCII 用码点本身 (半角), 其余从 256 起 (全角)"""
    chars = [c for c in glyphs if ord(c) >= 0x80]
    chars.sort()
    data = bytearray((256 + len(chars)) * 24)
    cmap = {}
    for ch, hx in glyphs.items():
        cp = ord(ch)
        gi = cp if cp < 0x80 else 256 + chars.index(ch)
        data[gi * 24:(gi + 1) * 24] = bytes.fromhex(hx)
        cmap[cp] = gi
    return bytes(data), cmap


def load_glyphs(path=DATA) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)["glyphs"]


def build_font(out_path: str, path=DATA) -> int:
    """读入库的字形 -> fusion_pixel.ttf, 返回字数; 没有数据文件返回 0 (不写)"""
    if not os.path.isfile(path):
        return 0
    import make_tfont as T
    glyphs = load_glyphs(path)
    data, cmap = table(glyphs)
    old = T.FAMILY
    T.FAMILY = FAMILY
    try:
        T.build(data, cmap, out_path)
    finally:
        T.FAMILY = old
    return len(cmap)


def font_entry() -> dict:
    return {
        "id": FONT_ID,
        "name": "Fusion Pixel",
        "desc": "12 像素点阵 (三方字体)。",
        "file": "res://content/tdj/ui_theme/" + FONT_FILE,
        "baseline_in_cell": 12.0,
        "embolden": 0.0,
        "hinting": "none",
        "order": 101,
        "license": "SIL OFL 1.1 (Fusion Pixel Font 12px, TakWolf; 许可文本 tools/assets/fusion_pixel.LICENSES.txt)",
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--src", required=True, help="解压后的 fusion-pixel-font-12px-monospaced-otb 目录")
    a = ap.parse_args()
    import make_tfont as T
    hant_chars, hans_only = glyph_chars(T.text_chars(), T.text_chars_hans())
    raw = extract(TTFont(os.path.join(a.src, OTB_TW)), hant_chars)
    raw.update(extract(TTFont(os.path.join(a.src, OTB_HANS)), hans_only))
    miss = [c for c in hant_chars + hans_only if c not in raw]
    out = {
        "format": "fusion-pixel/1",
        "note": "「Fusion Pixel」字体的字形: 24 字节 = 12 行 x 2 字节, 高位在左 (同 Tfont); 繁体文本取 zh_tw 字形, 只在简体文本里的字取 zh_hans。生成: tools/assets/make_fusion_pixel.py",
        "source": {"font": "Fusion Pixel Font 12px monospaced zh_tw / zh_hans", "version": VERSION, "author": "TakWolf",
                   "url": "https://github.com/TakWolf/fusion-pixel-font", "license": "SIL OFL 1.1 (tools/assets/fusion_pixel.LICENSES.txt)"},
        "glyphs": raw,
    }
    with open(DATA, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=0)
        f.write("\n")
    print("写入 %s (%d 个字), 没有字形的 %d 个: %s" % (os.path.relpath(DATA), len(raw), len(miss), "".join(miss)))


if __name__ == "__main__":
    main()
