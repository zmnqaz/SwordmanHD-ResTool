#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""贴图分类表: 原图目录里每张贴图的高清方式 -> 内容包 game/content/tdj/textures.json (一键流水线 build_assets.py 的 content 阶段)。

  texture_classes.py [--out game/content/tdj/textures.json]

方式 (规则见 tools/assets/hd_pipeline.py classify, 2026-10-03 对比 demo 后确定):
  px                         像素画 (人物、小贴图、小发光): 游戏运行时从原图在 GPU 上生成 6 倍 (game/engine/render/hq)
  genv3 / x4plus / animev3   AI 类 (头像、地图、大发光、大图): 由 hd 阶段离线放大, 存在 hd_images.pck (hd4x/); 没有则显示原图
游戏 (Assets) 只从这张表认定哪些贴图运行时高清化, 与 hd_images.pck 是否存在无关; 内容包 (含 mod) 可覆盖此表。
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tools/
import _boot  # noqa: E402,F401
from hd_pipeline import METHODS, classify, glow_textures, walk_original  # noqa: E402
from paths import REPO, original_dir  # noqa: E402
from PIL import Image  # noqa: E402

FORMAT = "tdj-textures/1"


def classes(src):
    glow = glow_textures(src)
    index = os.path.join(src, "index.json")
    known = set(json.load(open(index, encoding="utf-8"))) if os.path.isfile(index) else None
    out = {}
    for d, _, fs in walk_original(src):
        for f in fs:
            if not f.endswith(".png"):
                continue
            rel = os.path.relpath(os.path.join(d, f), src).replace(os.sep, "/")
            if known is not None and rel not in known:
                continue  # 分类表只覆盖原版导出的文件 (index.json), 混进原图目录的 AI 实验中间产物不算
            with Image.open(os.path.join(d, f)) as im:
                out[rel] = classify(rel, im.size, glow)[0]
    return dict(sorted(out.items()))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=os.path.join(REPO, "game", "content", "tdj", "textures.json"))
    a = ap.parse_args()
    tex = classes(original_dir())
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"format": FORMAT, "methods": {k: list(v) for k, v in METHODS.items()}, "textures": tex},
                  f, ensure_ascii=False, indent=0)
    n_px = sum(1 for v in tex.values() if v == "px")
    print(f"贴图分类 {len(tex)} 张 (像素画 px {n_px}, AI 类 {len(tex) - n_px}) -> {os.path.relpath(a.out, REPO)}")


if __name__ == "__main__":
    main()
