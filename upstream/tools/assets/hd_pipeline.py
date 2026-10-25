# SPDX-License-Identifier: GPL-3.0-only
"""贴图分类函数 (从游戏仓库 tools/assets/hd_pipeline.py 原样摘出, 资源获取器的精简版): 不含任何放大 / 高清化代码。"""
import collections
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tools/
from paths import REPO, original_dir, walk_original  # noqa: E402,F401

METHODS = {'genv3': ('ai', '头像'), 'x4plus': ('ai', '地图背景与大图'), 'animev3': ('ai', '大发光贴图'), 'px': ('gen', '运行时生成')}

SMALL_W, SMALL_H = (60, 72)

TEX_RE = re.compile('^(.*)/t(\\d+)\\.png$')


def glow_textures(src):
    """扫描 anim.json, 返回以发光方式 (Type2~6, 且不是 Type2+p10=0) 使用的贴图: {动画目录小写: {贴图编号}}。"""
    glow = collections.defaultdict(set)
    for d, _, fs in walk_original(src):
        if "anim.json" not in fs:
            continue
        anim = os.path.relpath(d, src).lower().replace(os.sep, "/")  # 键一律正斜杠 (Windows os.path.relpath 是反斜杠, 会查不到)
        with open(os.path.join(d, "anim.json"), encoding="utf-8") as f:
            data = json.load(f)
        for fr in data["frames"]:
            for p in fr["parts"]:
                if p["tex"] is not None and 2 <= p["type"] <= 6 and not (p["type"] == 2 and p["p10"] == 0):
                    glow[anim].add(p["tex"])
    return glow


def classify(rel, size, glow):
    """rel: 相对 src 的路径, 如 Sprite/man001/001-1A/t5.png 或 Stage/Stage01/map01.png。返回 (方式, 原因)。"""
    low = rel.lower()
    parts = low.split("/")
    m = TEX_RE.match(low)
    if parts[0] == "face":
        return "genv3", "头像"
    if not m:
        return "x4plus", "地图背景"
    small = size[0] <= SMALL_W and size[1] <= SMALL_H
    if int(m.group(2)) in glow.get(m.group(1), ()):
        return ("px", "小发光贴图") if small else ("animev3", "发光贴图")
    if parts[0] == "sprite" or (parts[0] == "rpg" and (parts[1] == "rpgman" or (len(parts) > 3 and parts[2].startswith("man")))):
        return "px", "人物"
    if small:
        return "px", "小贴图"
    return "x4plus", "场景物件/大图"
