#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""生成 index.json (用法: make_index.py <原图目录>): 原图目录里全部资源文件的相对路径列表 (只含原版目录, 不含 tools/、Swordman/ 等)。
原版文件名大小写不统一 (FACE01 / Face05), 游戏用它做不区分大小写的查找。"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))  # tools/
import _boot  # noqa: E402,F401

TOPS = _boot.paths.TOPS  # 原版资源目录表唯一来源 (tools/paths.py)

root = sys.argv[1]  # 原图目录 (export_original.py 的 -o)
files = sorted(os.path.relpath(os.path.join(d, f), root).replace(os.sep, "/")
               for top in TOPS if os.path.isdir(os.path.join(root, top))
               for d, _, fs in os.walk(os.path.join(root, top)) for f in fs)
with open(os.path.join(root, "index.json"), "w", encoding="utf-8") as f:
    json.dump(files, f, ensure_ascii=False, separators=(",", ":"))
print(f"{len(files)} 个文件 -> {root}/index.json")
