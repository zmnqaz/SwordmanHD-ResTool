#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""标题画面「天地劫」大字与「神魔至尊傳」字带修复: 原版 Misc/Title 贴图 (330x192) 里这五个字是清楚的红字加暗影, hd 阶段的 AI 放大 (x4plus) 把它们糊成一团
(2026-10-31 玩家反馈「标题的神魔至尊传太模糊」)。这里把字带那一块改用像素画放大 (ffmpeg xbr, 4 倍) 的结果拼回 hd4x/Misc/Title/t0.webp,
四周羽化, 与周围 AI 放大的底图自然过渡。幂等: 每次都从原版贴图重新取这一块, 重跑结果相同。build_assets 的 hd 阶段在 AI 放大之后自动跑。

  python3 tools/assets/fix_title_text.py --src <原图目录> --out <hd4x 目录>
  python3 tools/assets/fix_title_text.py --game <原版游戏目录> --out <hd4x 目录>    (没有导出的原图目录时直接读 Misc/Title.saf)
"""
import argparse
import os
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # tools/
sys.path.insert(0, os.path.join(HERE, "original"))
import _boot  # noqa: E402,F401
from ai_upscale import ffmpeg_scale  # noqa: E402

SCALE = 4
BOX = (15, 28, 305, 162)   # 原版像素 (x0, y0, x1, y1): 「天地劫」三个大字 (约 x 25~295, y 39~133) 加「神魔至尊傳」五个字 (x 111~207, y 144~157) 及四周余量
FEATHER = 6                  # 羽化宽度 (原版像素)
WEBP_QUALITY = 96


def load_original(src: str, game: str) -> Image.Image:
    p = os.path.join(src, "Misc", "Title", "t0.png") if src else ""
    if p and os.path.isfile(p):
        return Image.open(p).convert("RGB")
    if game:
        from tdjfmt import Saf
        return Saf(os.path.join(game, "Misc", "Title.saf")).construct_image(0).convert("RGB")
    sys.exit("找不到原版标题贴图: 用 --src <原图目录> (含 Misc/Title/t0.png) 或 --game <原版游戏目录>")


def mask(w: int, h: int) -> np.ndarray:
    """字带的权重图 (放大后的像素): 中间 1, 四边按 FEATHER 线性降到 0"""
    x0, y0, x1, y1 = (v * SCALE for v in BOX)
    f = FEATHER * SCALE
    m = np.zeros((h, w), np.float32)
    ys, xs = np.mgrid[0:h, 0:w]
    dx = np.minimum(xs - x0, x1 - 1 - xs)
    dy = np.minimum(ys - y0, y1 - 1 - ys)
    d = np.minimum(dx, dy).astype(np.float32)
    m = np.clip((d + 1) / f, 0.0, 1.0)
    m[(xs < x0) | (xs >= x1) | (ys < y0) | (ys >= y1)] = 0.0
    return m


def fix(orig: Image.Image, hd: Image.Image) -> Image.Image:
    w, h = orig.size
    if hd.size != (w * SCALE, h * SCALE):
        sys.exit("高清标题图尺寸 %s 与原版 %s x %d 不符" % (hd.size, orig.size, SCALE))
    px = ffmpeg_scale(np.array(orig), "xbr=%d" % SCALE, SCALE).astype(np.float32)
    base = np.array(hd.convert("RGB")).astype(np.float32)
    m = mask(*hd.size)[..., None]
    out = base * (1 - m) + px * m
    return Image.fromarray(np.clip(out + 0.5, 0, 255).astype(np.uint8), "RGB")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--src", default="", help="原图目录 (含 Misc/Title/t0.png)")
    ap.add_argument("--game", default="", help="原版游戏目录 (没有原图目录时读 Misc/Title.saf)")
    ap.add_argument("--out", required=True, help="hd4x 目录 (改 Misc/Title/t0.webp)")
    ap.add_argument("--dst", default="", help="写到别处 (试效果用), 缺省就地改 hd4x/Misc/Title/t0.webp")
    a = ap.parse_args()
    hd_path = os.path.join(a.out, "Misc", "Title", "t0.webp")
    if not os.path.isfile(hd_path):
        print("没有 %s (hd 阶段没出这张图), 跳过" % hd_path)
        return
    res = fix(load_original(a.src, a.game), Image.open(hd_path))
    dst = a.dst or hd_path
    res.save(dst, "WEBP", quality=WEBP_QUALITY, method=6)
    print("标题字带已用像素画放大替换 ->", dst)


if __name__ == "__main__":
    main()
