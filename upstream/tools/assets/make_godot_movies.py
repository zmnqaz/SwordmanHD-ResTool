#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""原图目录下的过场 mp4 -> game/classic/movies/*.ogv (Godot 4 只支持 Ogg Theora), 保留原版 320x200, 由引擎放大。
跨平台实现 (make_godot_movies.sh 是薄封装)。需要 ffmpeg (带 libtheora/libvorbis) 在 PATH 里。原图位置见 tools/paths.py。
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tools/
import _boot  # noqa: E402,F401
import paths  # noqa: E402


def main():
    ff = shutil.which("ffmpeg")
    if not ff:
        print("找不到 ffmpeg (Windows: winget install Gyan.FFmpeg, 装完重开终端)", file=sys.stderr)
        return 2
    orig = paths.original_dir()
    if not os.path.isdir(orig):
        print(paths.missing_original_hint(), file=sys.stderr)
        return 2
    outroot = os.path.join(paths.REPO, "game", "classic", "movies")
    for dp, _, fns in os.walk(orig):
        for fn in sorted(fns):
            if not fn.lower().endswith(".mp4"):
                continue
            rel = os.path.relpath(os.path.join(dp, fn), orig)
            out = os.path.join(outroot, os.path.splitext(rel)[0] + ".ogv")
            os.makedirs(os.path.dirname(out), exist_ok=True)
            if not (os.path.isfile(out) and os.path.getsize(out) > 0):
                subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-i", os.path.join(dp, fn), "-c:v", "libtheora", "-q:v", "9",
                                "-c:a", "libvorbis", "-q:a", "6", out], check=True)
            print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
