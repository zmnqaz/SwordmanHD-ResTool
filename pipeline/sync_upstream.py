#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""把游戏仓库 SwordmanHD 里「从原版提取资源」要用的脚本同步到本仓库的 upstream/ (原样复制, 一行不改)。

  python3 pipeline/sync_upstream.py <游戏仓库的 clone 目录>

- 只取 git 跟踪、且游戏仓库的开源清单 (tools/legal/oss_manifest.txt) 标为 keep 的文件, 按下面的白名单取。
- 不含高清化工具; tools/assets/hd_pipeline.py 里提取阶段只用到贴图分类函数, 这里只把那几段原样摘出来 (AST) 生成精简版, 不带放大代码。
- 不含游戏的手写内容: 提取流程只要 game/content/remake/text/ui.json 存在 (它只用来生成给游戏本体用的繁体文字, 不进资源包), 这里放一个空的占位。
- 同步后在 upstream/UPSTREAM.txt 记下来源提交。
"""
import argparse
import ast
import os
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UP = os.path.join(REPO, "upstream")
ALLOW = ("tools/_boot.py", "tools/paths.py", "tools/build_assets.py", "tools/assets/")
HD_TOOLS = ("tools/assets/hd_pipeline.py", "tools/assets/ai_upscale.py", "tools/assets/face_upscale.py",
            "tools/assets/pixel_upscale.py", "tools/assets/movie_hd.py")   # 高清化: 不进获取器 (hd_pipeline 另生成精简版)
KEEP_ASSIGN = {"METHODS", "SMALL_W", "SMALL_H", "TEX_RE"}
KEEP_FUNC = {"glow_textures", "classify"}
STUB_HEAD = '''# SPDX-License-Identifier: GPL-3.0-only
"""贴图分类函数 (从游戏仓库 tools/assets/hd_pipeline.py 原样摘出, 资源获取器的精简版): 不含任何放大 / 高清化代码。"""
import collections
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tools/
from paths import REPO, original_dir, walk_original  # noqa: E402,F401

'''
MODEL_LABELS = {"RealESRGAN_General_x4_v3": "头像", "realesrgan-x4plus": "地图背景与大图", "realesr-animevideov3": "大发光贴图"}
UI_PLACEHOLDER = ("game/content/remake/text/ui.json", "{}\n")


def hd_pipeline_stub(src_path):
    src = open(src_path, encoding="utf-8").read()
    parts, got = [], set()
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign):
            names = {n.id for t in node.targets for n in ast.walk(t) if isinstance(n, ast.Name)}
            if names & KEEP_ASSIGN:
                text = ast.unparse(node)   # unparse 去掉行尾注释 (注释里提到放大脚本的名字)
                for model, label in MODEL_LABELS.items():   # METHODS 里的放大模型名换成中性的说明 (textures.json 的 methods 字段引擎不读)
                    text = text.replace(model, label)
                parts.append(text)
                got |= names
        elif isinstance(node, ast.FunctionDef) and node.name in KEEP_FUNC:
            parts.append("\n" + ast.get_source_segment(src, node))
            got.add(node.name)
    miss = (KEEP_ASSIGN | KEEP_FUNC) - got
    if miss:
        sys.exit("错误: 在 %s 里没找到 %s (游戏仓库改过 hd_pipeline.py? 更新本脚本的摘取清单)" % (src_path, ", ".join(sorted(miss))))
    return STUB_HEAD + "\n\n".join(parts) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("game_repo", help="游戏仓库 SwordmanHD 的 clone 目录")
    a = ap.parse_args()
    game = os.path.abspath(a.game_repo)
    sys.path.insert(0, os.path.join(game, "tools", "legal"))
    import oss_audit as oa  # 用游戏仓库自己的版权清单把关
    rules = oa.load_manifest(os.path.join(game, "tools", "legal", "oss_manifest.txt"))
    listing = subprocess.run(["git", "-C", game, "ls-files", "-z"], capture_output=True, check=True).stdout
    files = []
    for p in listing.decode("utf-8").split("\0"):
        if not p or not p.startswith(ALLOW) or p in HD_TOOLS or not os.path.isfile(os.path.join(game, p)):
            continue
        r = oa.classify(p, rules)
        if not r or r["disp"] not in ("keep", "placeholder"):
            sys.exit("错误: %s 不在游戏仓库的开源清单 keep 范围内, 不能放进获取器" % p)
        files.append(p)
    shutil.rmtree(UP, ignore_errors=True)
    for p in files:
        dst = os.path.join(UP, *p.split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(os.path.join(game, p), dst)
    stub = os.path.join(UP, "tools", "assets", "hd_pipeline.py")
    with open(stub, "w", encoding="utf-8", newline="\n") as f:
        f.write(hd_pipeline_stub(os.path.join(game, "tools", "assets", "hd_pipeline.py")))
    ui = os.path.join(UP, *UI_PLACEHOLDER[0].split("/"))
    os.makedirs(os.path.dirname(ui), exist_ok=True)
    with open(ui, "w", encoding="utf-8", newline="\n") as f:
        f.write(UI_PLACEHOLDER[1])
    head = subprocess.run(["git", "-C", game, "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    with open(os.path.join(UP, "UPSTREAM.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write("来源: 游戏仓库 SwordmanHD 提交 %s\n由 pipeline/sync_upstream.py 同步 (原样复制, 不要手改; 要改去游戏仓库改再同步)。\n" % head)
    print("已同步 %d 个文件 (来源提交 %s) -> upstream/" % (len(files) + 2, head))
    return 0


if __name__ == "__main__":
    sys.exit(main())
