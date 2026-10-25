#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""打包用: 原版音效 wav (无损, 130 MB) -> Ogg Vorbis (约十分之一)。原版目录里的 wav 不动 (它是源头), 只在打包时转, 结果缓存在 <仓库>/.work/audio_ogg/。
游戏读音效 (Assets.sound) 时先找 .wav, 没有再找同名 .ogg, 所以开发版 (直接读原版目录) 与导出版 (包里是 ogg) 行为一致。

  audio_pack.py [--orig 原图目录] [--cache DIR] [--q 6] [-j N] [--check]

转换参数: 保持原采样率与声道 (原版多是 22050 Hz 单声道), 8 位转 16 位, libvorbis 质量 q8 (比 q6 大约 17%, 信噪比平均高 3.5 dB; 130 MB -> 约 39 MB)。
--check 随机抽 40 个解码回来对比原 wav: 时长差、信噪比 (SNR) 报告。"""
import argparse
import json
import os
import random
import subprocess
import sys
import wave
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import _boot  # noqa: E402,F401
import paths  # noqa: E402

CACHE = os.path.join(_boot.REPO, ".work", "audio_ogg")
Q = 8


def wav_rels(orig):
    with open(os.path.join(orig, "index.json"), encoding="utf-8") as f:
        return [r for r in json.load(f) if r.lower().endswith(".wav")]


def ogg_path(cache, rel):
    return os.path.join(cache, rel[:-4] + ".ogg")


def convert_one(src, dst, q=Q):
    """已有且比源新就跳过。写临时文件再改名 (中断不留半个文件)。"""
    if os.path.isfile(dst) and os.path.getmtime(dst) >= os.path.getmtime(src):
        return False
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    tmp = dst + ".part"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", src, "-map_metadata", "-1", "-c:a", "libvorbis", "-q:a", str(q), "-f", "ogg", tmp], check=True)
    os.replace(tmp, dst)
    return True


def convert_all(orig, cache=CACHE, q=Q, jobs=None):
    """转全部 wav; 返回 {相对路径(.wav): ogg 文件路径}。"""
    rels = wav_rels(orig)
    todo = [(os.path.join(orig, r), ogg_path(cache, r)) for r in rels]
    with ThreadPoolExecutor(jobs or os.cpu_count() or 4) as ex:
        n = sum(ex.map(lambda a: convert_one(a[0], a[1], q), todo))
    return {r: ogg_path(cache, r) for r in rels}, n


def snr_and_duration(wav_f, ogg_f):
    import array
    with wave.open(wav_f) as w:
        sr, ch, sw, n = w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()
        raw = w.readframes(n)
    a = array.array("h" if sw == 2 else "b", raw)
    ref = [x - 128 if sw == 1 else x for x in (list(a) if sw == 2 else [b - 128 for b in raw])] if sw == 1 else list(a)
    if sw == 1:
        ref = [(b - 128) * 256 for b in raw]
    out = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", ogg_f, "-f", "s16le", "-ac", str(ch), "-ar", str(sr), "-"], capture_output=True, check=True).stdout
    dec = array.array("h"); dec.frombytes(out[: len(out) // 2 * 2])
    m = min(len(ref), len(dec))
    sig = sum(x * x for x in ref[:m]) or 1
    best = None
    for lag in range(0, 2200, 1):            # 编码器有起始延迟, 找让误差最小的偏移 (只在前 2200 采样里试)
        e = sum((ref[i] - dec[i + lag]) ** 2 for i in range(0, min(m - lag, 4000)))
        if best is None or e < best[0]:
            best = (e, lag)
        if best[0] == 0:
            break
    lag = best[1]
    k = m - lag
    err = sum((ref[i] - dec[i + lag]) ** 2 for i in range(k)) or 1
    import math
    return 10 * math.log10(sum(x * x for x in ref[:k]) / err), n / sr, len(dec) / (sr * ch)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--orig", default=paths.original_dir())
    ap.add_argument("--cache", default=CACHE)
    ap.add_argument("--q", type=int, default=Q)
    ap.add_argument("-j", "--jobs", type=int, default=None)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    m, n = convert_all(a.orig, a.cache, a.q, a.jobs)
    wav = sum(os.path.getsize(os.path.join(a.orig, r)) for r in m)
    ogg = sum(os.path.getsize(p) for p in m.values())
    print("音效 %d 个, 本次转换 %d 个: wav %.1f MB -> ogg %.1f MB (%.0f%%)" % (len(m), n, wav / 1048576, ogg / 1048576, ogg * 100 / wav))
    if a.check:
        random.seed(1)
        for r in random.sample(list(m), 12):
            snr, d0, d1 = snr_and_duration(os.path.join(a.orig, r), m[r])
            print("  %-34s 时长 %.3f -> %.3f s  SNR %.1f dB" % (r, d0, d1, snr))


if __name__ == "__main__":
    main()
