#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""打包阶段: 复用主仓库 build_assets.py 的 pack_all (决定哪些文件进哪个包, 生成 BUILD.json), 只把「调 Godot 的 PCKPacker 写 .pck」
这一步换成 pck_writer.py (纯 Python, 与 Godot 的输出逐字节一致), 这样发布包里不用带 Godot。主仓库的代码一行不改。

  pack.py --out <资源包输出目录> [--wav]
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [os.path.join(ROOT, "tools"), os.path.join(ROOT, "tools", "assets"), HERE]
# pack_all 开头只检查「Godot 在不在」, 实际打包马上被下面换掉; 指向本解释器即可 (不会被运行)
os.environ["TDJ_GODOT"] = sys.executable
import build_assets as B  # noqa: E402
import pck_writer  # noqa: E402


def pack_without_godot(godot, out, items):
    tmp = out + ".tmp"
    try:
        pck_writer.write_pck(tmp, items)
        pck_writer.check_pck(tmp)
    except (OSError, ValueError) as e:
        if os.path.isfile(tmp):
            os.remove(tmp)
        B.die("打包失败 %s: %s" % (out, e))
    os.replace(tmp, out)
    print("  %-26s %6d 个文件  %5.0f MB" % (B.pack_label(out), len(items), os.path.getsize(out) / 1048576), flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--wav", action="store_true", help="音效保留原版无损 WAV, 不转 Ogg")
    a = ap.parse_args()
    B.pack = pack_without_godot
    if a.wav:   # 不转换时, 原版 wav 按原样进包 (游戏读音效先找 .wav 再找 .ogg)
        B.audio_pack.convert_all = lambda orig, *args, **kw: ({}, 0)
    B.pack_all(os.path.abspath(a.out), hd=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
