#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""把字库字体裁成「游戏实际用到的字」的子集, 并量出每个字体在 12x12 字格里的基线 (可重建)。

清单: game/content/remake/ui_theme/fonts.json。带 "source" 的字体 (file = 上游完整字体文件名, url = 官方发布地址)
由本工具从 --src 目录 (默认 <仓库>/.work/fontsrc/, 缺则报错并说明) 读取原字体, 裁剪后写到 "file" 指向的 game/assets/font/ 下; 不带 source 的 (思源黑体) 原样随游戏。
字符集 = ASCII + GB2312 一二级汉字 + 常用标点/全半角符号 + data/ 与 game/ 全部文本 (json / evs / gd 字符串) 里出现过的字
         (有 opencc 时再加 t2s 转换后的字), 再与字体 cmap 求交。
改名: 带 "family" 时把子集的 name 表改成该名字 (OFL 保留字体名, 改过的子集不再叫原名, 见 docs/字体许可.md)。
基线: 按「国天地劫的口」墨迹中心对齐原版字格第 6.4 行 (与思源黑体 10.75 同一算法, 见 docs/界面布局.md §2.2),
      取 1/4 像素, 写回清单的 baseline_in_cell。
用法: python3 tools/assets/make_font_subset.py [--src DIR] [--measure-only]
需要 fontTools (pip install fonttools); 不需要 brotli (输出 ttf/otf)。
"""
import argparse
import glob
import json
import os
import sys

from fontTools import subset
from fontTools.pens.boundsPen import BoundsPen
from fontTools.ttLib import TTFont

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tools/
import _boot  # noqa: E402,F401
from paths import REPO  # noqa: E402

FONTS_JSON = os.path.join(REPO, "game", "content", "remake", "ui_theme", "fonts.json")
PROBE = "国天地劫的口"
PROBE_ROW = 6.4          # 原版 Tfont 墨迹中心所在的字格行 (docs/界面布局.md §2.2)
PUNCT_RANGES = [(0x2000, 0x206F), (0x2190, 0x21FF), (0x2500, 0x257F), (0x25A0, 0x25FF), (0x3000, 0x303F), (0xFF00, 0xFFEF)]


def strings(o):
    if isinstance(o, str):
        yield o
    elif isinstance(o, dict):
        for k, v in o.items():
            yield k
            yield from strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from strings(v)


def gb2312():
    out = set()
    for hi in range(0xB0, 0xF8):
        for lo in range(0xA1, 0xFF):
            try:
                out.add(bytes([hi, lo]).decode("gb2312"))
            except UnicodeDecodeError:
                pass
    return out


def game_chars():
    """data/ 与 game/ 下全部文本里出现的字符。"""
    chars = set()
    for pat in ("data/**/*.json", "game/**/*.json"):
        for f in glob.glob(os.path.join(REPO, pat), recursive=True):
            if "/.godot/" in f:
                continue
            try:
                for s in strings(json.load(open(f, encoding="utf-8"))):
                    chars.update(s)
            except (ValueError, UnicodeDecodeError):
                pass
    for pat in ("game/**/*.gd", "game/**/*.evs", "game/**/*.cfg"):
        for f in glob.glob(os.path.join(REPO, pat), recursive=True):
            if "/.godot/" not in f:
                chars.update(open(f, encoding="utf-8", errors="ignore").read())
    return chars


def charset():
    cs = {chr(c) for c in range(0x20, 0x7F)} | gb2312() | game_chars()
    for a, b in PUNCT_RANGES:
        cs.update(chr(c) for c in range(a, b + 1))
    try:
        import opencc
        cc = opencc.OpenCC("t2s")
        cs.update("".join(cc.convert(c) for c in cs))
    except ImportError:
        pass
    return {c for c in cs if ord(c) >= 0x20}


def ink_center(font):
    """12 号下探针字墨迹中心在基线上方多少 (原版像素)。"""
    gs = font.getGlyphSet()
    cmap = font.getBestCmap()
    upm = font["head"].unitsPerEm
    cs = []
    for ch in PROBE:
        g = cmap.get(ord(ch))
        if g is None:
            continue
        bp = BoundsPen(gs)
        gs[g].draw(bp)
        if bp.bounds:
            cs.append((bp.bounds[1] + bp.bounds[3]) / 2)
    return sum(cs) / len(cs) / upm * 12.0


def baseline_of(font):
    return round((PROBE_ROW + ink_center(font)) * 4) / 4


def set_family(font, family):
    ps = family.replace(" ", "") + "-Medium"
    for rec in font["name"].names:
        if rec.nameID in (1, 16):
            rec.string = family
        elif rec.nameID == 4:
            rec.string = family + " Medium"
        elif rec.nameID in (3, 6):
            rec.string = ps


def make(entry, src_dir, chars):
    s = entry["source"]
    src = os.path.join(src_dir, s["file"])
    if not os.path.isfile(src):
        sys.exit("找不到原字体 %s: 把 fonts.json 里 source.file 指的字体放到 --src 目录 (默认 <仓库>/.work/fontsrc), 许可见 docs/字体许可.md" % src)
    out = os.path.join(REPO, "game", entry["file"].replace("res://", ""))
    opts = subset.Options()
    opts.layout_features = ["kern", "locl"]
    opts.hinting = False
    opts.desubroutinize = True
    opts.notdef_outline = True
    font = TTFont(src)
    cmap = font.getBestCmap()
    keep = sorted(ord(c) for c in chars if ord(c) in cmap)
    sub = subset.Subsetter(opts)
    sub.populate(unicodes=keep)
    sub.subset(font)
    if s.get("family"):
        set_family(font, s["family"])
    font.save(out)
    print(f"{entry['id']}: {len(keep)}/{len(chars)} 字 -> {os.path.relpath(out, REPO)} {os.path.getsize(out)/1e6:.2f} MB")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=os.path.join(REPO, ".work", "fontsrc"), help="原字体目录 (默认 <仓库>/.work/fontsrc)")
    ap.add_argument("--measure-only", action="store_true")
    a = ap.parse_args()
    data = json.load(open(FONTS_JSON, encoding="utf-8"))
    chars = None if a.measure_only else charset()
    for e in data["fonts"]:
        if "source" in e and not a.measure_only:
            make(e, a.src, chars)
        path = os.path.join(REPO, "game", e["file"].replace("res://", ""))
        e["baseline_in_cell"] = baseline_of(TTFont(path))
        print(f"  {e['id']} 基线 {e['baseline_in_cell']}")
    with open(FONTS_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


if __name__ == "__main__":
    main()
