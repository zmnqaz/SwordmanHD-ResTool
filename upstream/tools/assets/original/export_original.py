#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""把原版游戏资源无损解出成与引擎无关的格式, 按原版目录结构存放 (一键流水线 tools/build_assets.py 的第一步)。
(2026-10-05 从原图仓库 tdj-original/tools 搬入, 便于开源: 玩家用自己的原版游戏生成资源。)

  export_original.py --game Swordman -o . [-j 8] [--skip-movie]

每个 SAF 变成一个同名目录 (<原路径去扩展名>/):
  anim.json   动画数据 (格式见 README.md)
  t<N>.png    贴图 (RGBA, 原版像素尺寸; 透明来自压缩数据里的"跳过", 不是按黑色抠图)
  s<N>.wav    内嵌音效
FB2+MPL 地图   -> <同目录>/<FB2 名>.png
Bink 过场 .mov -> <同路径>.mp4 (H.264 + AAC)
其余文件 (DAT/MSG/COD/DTL/MPL/CSP/TXT/MP3) 原样复制。
"""
import argparse
import json
import os
import shutil
import stat
import struct
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tdjfmt import Saf, SafError, load_map, u16  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))  # tools/
import _boot  # noqa: E402,F401

GAME_DIRS = _boot.paths.TOPS  # 原版资源目录表唯一来源 (tools/paths.py)
ANIM_FORMAT = "tdj-anim/1"


def anim_json(saf, source):
    frames = []
    for fr in saf.frames:
        sound, time_, hit, color, shake, unk4, n = struct.unpack_from("<hhBBBBh", fr, 0)
        parts = []
        for k in range(n):
            tid, x, y, ptype, p8, p10, p12 = struct.unpack_from("<HhhBhhh", fr, 10 + 13 * k)
            part = {"tex": tid, "x": x, "y": y, "type": ptype, "p8": p8, "p10": p10, "p12": p12}
            if tid >= 0x8000:  # 引用另一个动画 (攻击方/受击方) 第 ref 帧的第一张贴图
                part = {"tex": None, "ref": tid - 0x8000 + 1, **{k: v for k, v in part.items() if k != "tex"}}
            parts.append(part)
        frames.append({"sound": sound, "time": time_, "hit": hit, "color": color, "shake": shake, "unk4": unk4,
                       "parts": parts})
    textures = []
    for i in range(len(saf.constructs)):
        w, h = saf.construct_size(i)
        textures.append({"file": f"t{i}.png", "w": w, "h": h})
    sounds = [{"file": f"s{i}.wav", "channels": wv[0], "bits": wv[1], "rate": u16(wv, 2)} for i, wv in enumerate(saf.waves)]
    return {"format": ANIM_FORMAT, "source": source, "action_counts": saf.counts,
            "textures": textures, "sounds": sounds, "frames": frames}


def write_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
        f.write("\n")


def job_saf(src, rel, out):
    saf = Saf(src)
    d = os.path.join(out, os.path.splitext(rel)[0])
    os.makedirs(d, exist_ok=True)
    write_json(os.path.join(d, "anim.json"), anim_json(saf, rel))
    for i in range(len(saf.constructs)):
        saf.construct_image(i).save(os.path.join(d, f"t{i}.png"), optimize=True)
    for i in range(len(saf.waves)):
        saf.write_wave(i, os.path.join(d, f"s{i}.wav"))
    return ("saf", rel, len(saf.frames), len(saf.constructs), len(saf.waves))


def job_map(fb2, mpl, dst):
    img = load_map(fb2, mpl)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    img.save(dst, optimize=True)
    return ("map", dst, img.width, img.height, 0)


def job_movie(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", src, "-c:v", "libx264", "-crf", "16", "-preset", "slow",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", dst], check=True)
    return ("movie", dst, 0, 0, 0)


def copy_plain(src, dst):
    """原样复制。copy2 会连只读属性一起复制 (光盘/模拟器目录里的文件常是只读), 重跑时覆盖只读的旧副本会 PermissionError, 所以先解除目标只读、复制后也保持可写。"""
    if os.path.exists(dst):
        os.chmod(dst, os.stat(dst).st_mode | stat.S_IWUSR)
    shutil.copy2(src, dst)
    os.chmod(dst, os.stat(dst).st_mode | stat.S_IWUSR)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--game", required=True, help="原版游戏目录")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("-j", "--jobs", type=int, default=os.cpu_count())
    ap.add_argument("--skip-movie", action="store_true")
    args = ap.parse_args()

    jobs, copied = [], 0
    for top in GAME_DIRS:
        for dirpath, _, files in os.walk(os.path.join(args.game, top)):
            lower = {f.lower(): f for f in files}
            for f in sorted(files):
                src = os.path.join(dirpath, f)
                rel = os.path.relpath(src, args.game).replace(os.sep, "/")
                stem, ext = os.path.splitext(f)
                ext = ext.lower()
                if ext == ".saf":
                    jobs.append((job_saf, (src, rel, args.out)))
                elif ext == ".fb2":
                    mpl = lower.get(stem.lower() + ".mpl")
                    if not mpl:
                        print(f"警告: {rel} 缺少同名 MPL, 跳过", file=sys.stderr)
                        continue
                    jobs.append((job_map, (src, os.path.join(dirpath, mpl), os.path.join(args.out, rel[:-4] + ".png"))))
                elif ext == ".mov":
                    if not args.skip_movie:
                        jobs.append((job_movie, (src, os.path.join(args.out, rel[:-4] + ".mp4"))))
                else:
                    dst = os.path.join(args.out, rel)
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    copy_plain(src, dst)
                    copied += 1

    print(f"任务 {len(jobs)}, 原样复制 {copied}", flush=True)
    t0 = time.time()
    results, failures = [], []
    jobs.sort(key=lambda j: j[0] is not job_movie)  # 动画最慢, 先提交
    with ProcessPoolExecutor(args.jobs) as ex:
        futs = {ex.submit(fn, *a): a[0] for fn, a in jobs}
        for n, fut in enumerate(as_completed(futs), 1):
            try:
                results.append(fut.result())
            except (SafError, subprocess.CalledProcessError, OSError, ValueError) as e:
                failures.append((futs[fut], str(e)))
                print(f"失败: {futs[fut]}: {e}", file=sys.stderr)
            if n % 200 == 0 or n == len(futs):
                print(f"  {n}/{len(futs)}  {time.time() - t0:.0f}s", flush=True)
    summary = {
        "saf": sum(1 for r in results if r[0] == "saf"),
        "frames": sum(r[2] for r in results if r[0] == "saf"),
        "textures": sum(r[3] for r in results if r[0] == "saf"),
        "sounds": sum(r[4] for r in results if r[0] == "saf"),
        "maps": sum(1 for r in results if r[0] == "map"),
        "movies": sum(1 for r in results if r[0] == "movie"),
        "copied": copied,
        "failures": failures,
    }
    print(json.dumps(summary, ensure_ascii=False))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
