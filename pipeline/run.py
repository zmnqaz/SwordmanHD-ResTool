#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""资源获取器的流水线入口 (由 Go 程序用随包的 Python 调用): 提取 + 打包, 只做这两件事。

  run.py --game <原版游戏目录> --out <资源包输出目录> [--wav]

1. 提取: 主仓库 SwordmanHD 的 tools/build_assets.py 的 export / data / content / movie / icon 阶段 (原样使用, 不改)。
2. 打包: pack.py (纯 Python 写 .pck, 不需要 Godot)。
音效缺省压缩成 Ogg Vorbis (包小); --wav 保留原版无损 WAV (包大约多 90 MB, 游戏同样能读: 先找 .wav 再找 .ogg)。
输出里 "== <阶段名>" 的行是给界面显示进度用的。
"""
import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)          # 内嵌工具包展开后的根目录 (含 tools/ restool/ game/)
NEED_ENCODERS = ("libx264", "libtheora", "libvorbis")


def say(msg):
    print(msg, flush=True)


def die(msg):
    say("错误: " + msg)
    sys.exit(1)


def check_ffmpeg():
    try:
        out = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=60).stdout
    except (OSError, subprocess.TimeoutExpired):
        die("找不到 ffmpeg (发布包的 runtime/ffmpeg 文件夹不见了?)")
    miss = [e for e in NEED_ENCODERS if e not in out]
    if miss:
        die("ffmpeg 缺少编码器 %s" % ", ".join(miss))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--game", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--wav", action="store_true", help="音效保留原版无损 WAV, 不转 Ogg")
    a = ap.parse_args()
    game, out = os.path.abspath(a.game), os.path.abspath(a.out)
    if not os.path.isdir(os.path.join(game, "Sprite")):
        die("%s 不像原版游戏目录 (没有 Sprite/)" % game)
    check_ffmpeg()
    os.makedirs(os.path.join(ROOT, "game", "assets"), exist_ok=True)   # icon 阶段要往这里写 .ico

    env = dict(os.environ, PYTHONUNBUFFERED="1")
    # 1. 提取: build_assets 的前五个阶段; 打包 (pack) 与要 Godot 的校验 (verify) 不在这里跑, 高清化 (--no-ai) 不做
    cmd = [sys.executable, os.path.join(ROOT, "tools", "build_assets.py"), "--game", game, "--out", out, "--no-ai", "--skip", "pack", "verify"]
    rc = subprocess.run(cmd, cwd=ROOT, env=env).returncode
    if rc != 0:
        die("提取失败 (退出码 %d), 日志在 %s" % (rc, os.path.join(ROOT, ".work", "build_assets")))

    # 2. 打包
    say("== pack")
    cmd = [sys.executable, os.path.join(HERE, "pack.py"), "--out", out] + (["--wav"] if a.wav else [])
    rc = subprocess.run(cmd, cwd=ROOT, env=env).returncode
    if rc != 0:
        die("打包失败 (退出码 %d)" % rc)
    say("\n完成。资源包在: %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
