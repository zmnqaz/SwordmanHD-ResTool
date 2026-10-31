#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""原版点阵字库 Misc/Tfont.dat -> 矢量字体 (每个像素一个方块) + 字库清单叠加层, 设定里多一个「原版点阵」字体。

Tfont.dat 是原版唯一的字库: 13791 个 12x12 字模 (每字 24 字节, 12 行 x 2 字节, 每行高位在左, 用前 12 位), 简体字形。
字模下标与 Big5/cp950 码位的对应 (用游戏对白/物品/技能名渲染后逐字读过, 次常用字区也对; 单测 tools/tests/test_tfont.py 锁边界):
  0~255          单字节码: 下标 = 字符码 (0x20~0x7E 是 ASCII 半角字模, 画在字格左半 6 列)
  256~5656       Big5 常用字 A440~C67E (5401 字), 下标 = 256 + 线性号 - 471
  5657~13349     Big5 次常用字 C940~F9FE (含倚天 F9D6~F9FE), 不含 C6A1~C8FE 那一段, 下标 = 5657 + 线性号 - 6280
  13350~13790    符号 A140~A3E0 (标点/希腊/注音/箱线, 441 个), 下标 = 13350 + 线性号
  线性号 = (高字节-0xA1)*157 + (低字节 < 0x7F ? 低-0x40 : 低-0xA1+63)
字模表是 GB 字形按 Big5 码位摆的, 稀疏: Big5 里有、GB2312 里没有的字 (闇、祂、欸、鼩 等) 和简体专用字的码位 (气 术 极 复 …) 是空字模,
真正的字形在对应的繁体码位上 (氣 術 極 復)。所以这个字体**只服务繁体文本** (原版文本本来就是 Big5 繁体): 每个非空字模挂在它码位的 Unicode 字上, 仅此而已,
不做简繁别名; 清单带 "lang": "hant", 设定里只在繁体下列出 (简体下 UiFonts 不选它)。注意字形是简体字形 (氣 的码位上画的是 气), 这是原版字库本来的样子。
空字模不进字体: 没有字形的字 (闇 莲 等少数) 由 UiFonts 的缺字回退交给思源黑体, 不会画成空白。

补字: 原版字模表里游戏文本用到、却是空字模的字 (繁体文本约 20 种, 如 闇 蓮 祂 鼩 布, 共 150 多个字符; 原版 exe 只读 Tfont.dat, 不回退系统字体, 各版本字库相同,
  所以原版里这些字大概率就是空的) 在这里补进内存里的字模表 (只补空槽, 不覆盖原版已有的字形), 三种来源, 优先级从上到下:
  ALIAS    原版自己在变体字码位上画了同一个字形 (布 在 佈 的码位、錘 在 鎚、噁 在 惡、墬 在 墜): 复制过来;
  EXTRA    tools/assets/tfont_extra.json: 十几个字借 Ark Pixel 12px (OFL) 的字形, 入库 (tools/assets/make_tfont_extra.py 生成);
  COMPOSE  原版字形拼: 鼩 = 鼬 的左 6 列 + 狗 的右 6 列 (「灵鼩」是游戏里的神兽名, 136 处; 两个开源点阵字体也没有这个字)。
  补出来的字形是 12 像素点阵的近似, 不是原版字库本来的字。

字体坐标: 1200 单位/em = 12 像素, 每个像素 100x100 单位的方块, 基线在字格最后一行的下沿 (baseline_in_cell = 12);
全角 1200 宽, 半角 600 宽。12 号字的整数倍字号下像素与屏幕像素对齐, 非整数倍会有抗锯齿 (像素字体的通病)。

产物 (写进 game/content/tdj/ui_theme/, 随内容包 common_story.pck 一起打包; 整个目录是生成物, 不入库, 字形有版权不随源码/开源版分发):
  tfont.ttf    字体
  fonts.json   只含一条 id=tfont、lang=hant 的叠加清单 (UiFonts 按包合并, 缺字回退思源黑体)

用法: python3 tools/assets/make_tfont.py [--src Tfont.dat 或原版/原图目录] [--out DIR] [--check]
  --src    缺省找 <原图目录>/Misc/Tfont.dat; 也接受原版游戏目录 (Misc/Tfont.dat 在其中)
  --check  不写文件, 只报繁体文本 (内容包 locale/hant 叠加层) 里补字后还有多少字没有字形 (会回退思源黑体) 及是哪些
需要 fontTools。"""
import argparse
import json
import os
import sys

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tools/
import _boot  # noqa: E402,F401
import paths  # noqa: E402

REPO = paths.REPO
OUT_DIR = os.path.join(REPO, "game", "content", "tdj", "ui_theme")
GLYPH_BYTES = 24
COUNT = 13791
UPM = 1200
PX = 100
FONT_ID = "tfont"
FONT_FILE = "tfont.ttf"
FAMILY = "TDJ Tfont"
EXTRA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tfont_extra.json")
ALIAS = {"布": "佈", "錘": "鎚", "噁": "惡", "墬": "墜"}   # 补字: 原版在变体字码位上画了同一字形 (见文件头)
COMPOSE = {"鼩": ("鼬", "狗", 6)}                          # 补字: 左 6 列取前者、右 6 列取后者


def find_src(arg):
    """--src 可以是 Tfont.dat 本身、含 Misc/Tfont.dat 的目录、或含 Swordman/Misc 的目录; 缺省取原图目录。"""
    cands = [arg] if arg else [paths.original_dir()]
    for c in cands:
        if os.path.isfile(c):
            return c
        for sub in ("Misc/Tfont.dat", "Misc/TFONT.DAT", "Swordman/Misc/Tfont.dat"):
            p = os.path.join(c, *sub.split("/"))
            if os.path.isfile(p):
                return p
    return ""


def load(path):
    data = open(path, "rb").read()
    if len(data) != COUNT * GLYPH_BYTES:
        sys.exit("Tfont.dat 大小 %d 不是 %d x %d (版本不对?)" % (len(data), COUNT, GLYPH_BYTES))
    return data


def bitmap(data, i):
    """第 i 个字模 -> 12 行 x 12 列的 0/1"""
    g = data[i * GLYPH_BYTES:(i + 1) * GLYPH_BYTES]
    return [[(g[r * 2 + (c >> 3)] >> (7 - (c & 7))) & 1 for c in range(12)] for r in range(12)]


def linear(hi, lo):
    return (hi - 0xA1) * 157 + (lo - 0x40 if lo < 0x7F else lo - 0xA1 + 63)


def glyph_index(hi, lo):
    """Big5 双字节码 -> 字模下标; 字库里没有的返回 -1。"""
    if not (0x40 <= lo <= 0x7E or 0xA1 <= lo <= 0xFE):
        return -1
    n = linear(hi, lo)
    if 0xA1 <= hi <= 0xA3:
        return 13350 + n if n <= 440 else -1                # A140~A3E0 符号
    if 0xA4 <= hi <= 0xC6:
        return 256 + n - 471 if n <= linear(0xC6, 0x7E) else -1   # A440~C67E 常用字
    if 0xC9 <= hi <= 0xF9:
        return 5657 + n - 6280 if n <= linear(0xF9, 0xFE) else -1  # C940~F9FE 次常用字
    return -1


def decode(hi, lo):
    raw = bytes([hi, lo])
    for enc in ("cp950", "big5hkscs"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return ""


def code_points():
    """[(字模下标, Unicode 字)]: 单字节 ASCII + 全部 Big5 码位 (按码位顺序)。"""
    out = [(c, chr(c)) for c in range(0x20, 0x7F)]
    for hi in range(0xA1, 0xFA):
        for lo in list(range(0x40, 0x7F)) + list(range(0xA1, 0xFF)):
            gi = glyph_index(hi, lo)
            ch = decode(hi, lo) if gi >= 0 else ""
            if gi >= 0 and len(ch) == 1:
                out.append((gi, ch))
    return out


def patch(data, cps, extra_path=EXTRA):
    """补字 (规则见文件头): 返回补过空槽的字模表 (bytes), 原版已有字形的槽不动。"""
    buf = bytearray(data)
    slot = {ch: gi for gi, ch in cps}

    def put(ch, raw):
        gi = slot.get(ch)
        if gi is not None and not any(buf[gi * GLYPH_BYTES:(gi + 1) * GLYPH_BYTES]):
            buf[gi * GLYPH_BYTES:(gi + 1) * GLYPH_BYTES] = raw

    def get(ch):
        gi = slot[ch]
        return bytes(buf[gi * GLYPH_BYTES:(gi + 1) * GLYPH_BYTES])
    for x, y in ALIAS.items():
        if y in slot and any(get(y)):
            put(x, get(y))
    if os.path.isfile(extra_path):
        with open(extra_path, encoding="utf-8") as f:
            for ch, hx in json.load(f)["glyphs"].items():
                put(ch, bytes.fromhex(hx))
    for x, (left, right, cut) in COMPOSE.items():
        if left in slot and right in slot and any(get(left)) and any(get(right)):
            lw, rw = get(left), get(right)
            mask = ((1 << cut) - 1) << (16 - cut)       # 16 位行字里高 cut 位 = 左 cut 列
            raw = bytearray()
            for r in range(12):
                lv = int.from_bytes(lw[r * 2:r * 2 + 2], "big")
                rv = int.from_bytes(rw[r * 2:r * 2 + 2], "big")
                raw += ((lv & mask) | (rv & ~mask & 0xFFF0)).to_bytes(2, "big")
            put(x, bytes(raw))
    return bytes(buf)


def blank(data, gi):
    return not any(data[gi * GLYPH_BYTES:(gi + 1) * GLYPH_BYTES])


def build_cmap(data, cps):
    """Unicode -> 字模下标: 非空字模挂在码位自己的 Unicode 字上; 空格类字符保留 (字形为空但要有宽度)。"""
    return {ord(ch): gi for gi, ch in cps if ch.isspace() or not blank(data, gi)}


def rects(bm):
    """点阵 -> 每行连续的黑像素段 [(行, 起列, 止列(含))]; 方块在字体坐标里以基线为字格最后一行的下沿。"""
    out = []
    for r, row in enumerate(bm):
        c = 0
        while c < 12:
            if row[c]:
                s = c
                while c + 1 < 12 and row[c + 1]:
                    c += 1
                out.append((r, s, c))
            c += 1
    return out


def draw(bm):
    pen = TTGlyphPen(None)
    for r, s, e in rects(bm):
        y0, y1 = (11 - r) * PX, (12 - r) * PX
        x0, x1 = s * PX, (e + 1) * PX
        pen.moveTo((x0, y0))   # 顺时针 (TrueType 外轮廓)
        pen.lineTo((x0, y1))
        pen.lineTo((x1, y1))
        pen.lineTo((x1, y0))
        pen.closePath()
    return pen.glyph()


def build(data, cmap, path):
    used = sorted(set(cmap.values()))
    names = [".notdef"] + ["g%d" % gi for gi in used]
    gmap = {gi: "g%d" % gi for gi in used}
    glyphs = {".notdef": TTGlyphPen(None).glyph()}
    metrics = {".notdef": (UPM, 0)}
    for gi in used:
        bm = bitmap(data, gi)
        glyphs[gmap[gi]] = draw(bm)
        metrics[gmap[gi]] = (UPM // 2 if gi < 256 else UPM, 0)
    fb = FontBuilder(UPM, isTTF=True)
    fb.setupGlyphOrder(names)
    fb.setupCharacterMap({cp: gmap[gi] for cp, gi in cmap.items()})
    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics({n: (w, 0) for n, (w, _) in metrics.items()})
    fb.setupHorizontalHeader(ascent=UPM, descent=-2 * PX)
    fb.setupNameTable({"familyName": FAMILY, "styleName": "Regular"})
    fb.setupOS2(sTypoAscender=UPM, sTypoDescender=-2 * PX, usWinAscent=UPM, usWinDescent=2 * PX)
    fb.setupPost()
    fb.save(path)


def fonts_json():
    return {
        "format": "ui-fonts/1",
        "fonts": [{
            "id": FONT_ID,
            "name": "原版点阵",
            "desc": "原版 12 像素点阵 (仅繁体)。",
            "file": "res://content/tdj/ui_theme/" + FONT_FILE,
            "baseline_in_cell": 12.0,
            "embolden": 0.0,
            "hinting": "none",
            "order": 100,   # 排在内置字体之后 (设定里的选项顺序)
            "lang": "hant",   # 只在繁体下可选可用
            "license": "原版游戏字库 (由你自己的原版生成, 不随游戏分发)",
        }],
    }


def text_chars():
    """繁体文本里出现的字符及次数: 内容包 locale/hant 叠加层 (只含与简体不同的字段) 与手写界面文案的繁体层。"""
    import collections
    import glob
    cnt = collections.Counter()

    def walk(o):
        if isinstance(o, str):
            cnt.update(o)
        elif isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    for pat in ("game/content/tdj/locale/hant/**/*.json", "game/content/remake/locale/hant/**/*.json"):
        for f in glob.glob(os.path.join(REPO, pat), recursive=True):
            try:
                with open(f, encoding="utf-8") as fh:
                    walk(json.load(fh))
            except ValueError:
                pass
    return cnt


def check(cmap):
    cnt = text_chars()
    miss = {c: n for c, n in cnt.items() if ord(c) > 0x20 and ord(c) not in cmap}
    print("繁体文本 %d 种字 / %d 个字符, 没有字形的 %d 种 / %d 个 (回退思源黑体): %s" % (
        len(cnt), sum(cnt.values()), len(miss), sum(miss.values()), "".join(sorted(miss))))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--src", default="")
    ap.add_argument("--out", default=OUT_DIR)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    src = find_src(a.src)
    if not src:
        sys.exit("找不到 Misc/Tfont.dat: 用 --src 指向原版游戏目录或 Tfont.dat")
    data = load(src)
    cps = code_points()
    data = patch(data, cps)
    cmap = build_cmap(data, cps)
    if a.check:
        check(cmap)
        return
    os.makedirs(a.out, exist_ok=True)
    build(data, cmap, os.path.join(a.out, FONT_FILE))
    with open(os.path.join(a.out, "fonts.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(fonts_json(), f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("原版点阵: %d 个字 (%d 个字模) -> %s" % (len(cmap), len(set(cmap.values())), os.path.relpath(os.path.join(a.out, FONT_FILE), REPO)))


if __name__ == "__main__":
    main()
