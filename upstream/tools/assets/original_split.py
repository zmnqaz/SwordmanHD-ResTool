#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""把原版资源拆成「核心」和「原版画质图」两个包的辅助函数 (build_assets.pack_lists 用)。

高清包 (hd_images.pck) 里已有高清版的原版贴图 (hd4x.json 登记的, 头像/地图/大特效/界面大图) 在高清模式下用不到原版 1 倍图,
把它们单独装进 classic_images.pck: 装了 hd_images 的玩家可以不放它 (省约 270 MB); 没装高清包的需要它 (原版画质)。
排版用的「不透明区域」(Assets.used_rect) 以前直接读原版 1 倍图, 图不在时改读核心包里预先算好的 used_rects.json
(键 = 相对路径, 值 = [x, y, w, h]; 算法与 Godot Image.get_used_rect 一致: alpha > 0 的像素的外框, 无 alpha 的图是整张, 全透明是 [0,0,0,0])。"""
import json
import os
from concurrent.futures import ThreadPoolExecutor

from PIL import Image


def replaceable(orig, hd4x_json):
    """原版目录里、高清清单 hd4x.json 登记过的 PNG 相对路径集合 (清单里的键就是原版相对路径, 大小写已是真实的)。"""
    if not os.path.isfile(hd4x_json):
        return set()
    with open(hd4x_json, encoding="utf-8") as f:
        keys = set(json.load(f).get("textures", {}))
    return {k for k in keys if k.lower().endswith(".png") and os.path.isfile(os.path.join(orig, k))}


def used_rect(path):
    with Image.open(path) as im:
        a = im.convert("RGBA").getchannel("A").point(lambda v: 255 if v > 0 else 0)
        b = a.getbbox()
    return [0, 0, 0, 0] if b is None else [b[0], b[1], b[2] - b[0], b[3] - b[1]]


def used_rects(orig, rels, jobs=None):
    """{相对路径: [x, y, w, h]}"""
    rels = sorted(rels)
    with ThreadPoolExecutor(jobs or os.cpu_count() or 4) as ex:
        return dict(zip(rels, ex.map(lambda r: used_rect(os.path.join(orig, r)), rels)))


def split(items, rel_set):
    """items = [(源文件, "res://common/<相对路径>")] -> (核心, 原版画质图): 相对路径在 rel_set 里的进后者。"""
    prefix = "res://common/"
    core, img = [], []
    for it in items:
        rel = it[1][len(prefix):] if it[1].startswith(prefix) else None
        (img if rel in rel_set else core).append(it)
    return core, img
