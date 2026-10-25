#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""组装「随包运行环境」runtime/: 便携版 Python (依赖库已装好) + ffmpeg。玩家下载解压就能用, 运行时不用联网下载任何东西。

  python3 bundle/bundle.py --platform win64|linux-x64|macos-arm64|macos-x64 --out <目录> [--requirements bundle/requirements.txt]

在任何系统上都能给任何平台组装 (用 pip download 按目标平台取 wheel, 不需要目标系统)。产物:
  <out>/runtime/python/...          python-build-standalone 的 install_only 构建 (带 tkinter: 获取器的窗口界面用它)
  <out>/runtime/python/.../site-packages  依赖库 (Pillow、numpy、fonttools、opencc、customtkinter; 见 bundle/requirements.txt), 来自 PyPI 的 wheel
  <out>/runtime/ffmpeg/ffmpeg[.exe]       带 libx264 / libtheora / libvorbis 的 GPL 静态构建 (只带 ffmpeg, 不带 ffprobe 和 ffplay)
  <out>/runtime/LICENSES.txt        各组件的许可与源码出处 (ffmpeg 是 GPL, 要附源码出处)
下载的 Python 与 macOS ffmpeg 按 bundle/pins.json 里的 SHA256 校验; BtbN 的 ffmpeg 是滚动发布无法固定哈希, 改为检查编译配置里有没有需要的编码器。
下载缓存在 .cache/ (不入库)。
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CACHE = os.path.join(ROOT, ".cache")
PINS_FILE = os.path.join(HERE, "pins.json")

PY_MINOR = "3.12"
PBS_TAG = "20261021"
PBS_VER = "3.12.15"


def PBS(triple):
    return ("https://github.com/astral-sh/python-build-standalone/releases/download/%s/cpython-%s%%2B%s-%s-install_only.tar.gz"
            % (PBS_TAG, PBS_VER, PBS_TAG, triple))


BTBN = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
OSX = "https://www.osxexperts.net/"

PLATFORMS = {
    "win64": {
        "python": PBS("x86_64-pc-windows-msvc"), "wheel_platforms": ["win_amd64"],
        "ffmpeg": [BTBN + "ffmpeg-master-latest-win64-gpl.zip"],
    },
    "linux-x64": {
        "python": PBS("x86_64-unknown-linux-gnu"),
        "wheel_platforms": ["manylinux2014_x86_64", "manylinux_2_17_x86_64", "manylinux_2_27_x86_64", "manylinux_2_28_x86_64"],
        "ffmpeg": [BTBN + "ffmpeg-master-latest-linux64-gpl.tar.xz"],
    },
    "macos-arm64": {
        "python": PBS("aarch64-apple-darwin"),
        "wheel_platforms": ["macosx_11_0_arm64", "macosx_12_0_arm64", "macosx_13_0_arm64", "macosx_14_0_arm64", "macosx_15_0_arm64"],
        "ffmpeg": [OSX + "ffmpeg71arm.zip"],
    },
    "macos-x64": {
        "python": PBS("x86_64-apple-darwin"),
        "wheel_platforms": ["macosx_10_13_x86_64", "macosx_10_15_x86_64", "macosx_11_0_x86_64", "macosx_12_0_x86_64",
                            "macosx_13_0_x86_64", "macosx_14_0_x86_64", "macosx_15_0_x86_64"],
        "ffmpeg": [OSX + "ffmpeg71intel.zip"],
    },
}
NEED_ENCODERS = (b"libx264", b"libtheora", b"libvorbis")


def say(msg):
    print(msg, flush=True)


def die(msg):
    print("错误: " + msg, file=sys.stderr)
    sys.exit(1)


def load_pins():
    if os.path.isfile(PINS_FILE):
        with open(PINS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def download(url, trust_new):
    """下载到缓存 (已有就复用); 有固定哈希的校验, 没有的在 --trust-new 时记下。返回本地路径。"""
    os.makedirs(CACHE, exist_ok=True)
    dst = os.path.join(CACHE, re.sub(r"[^A-Za-z0-9._+-]", "_", url.split("://", 1)[1]))
    if not os.path.isfile(dst):
        say("  下载 " + url)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 SwordmanHD-bundle"})
        with urllib.request.urlopen(req, timeout=120) as r, open(dst + ".part", "wb") as f:
            shutil.copyfileobj(r, f, 1 << 20)
        os.replace(dst + ".part", dst)
    pins = load_pins()
    if url in pins:
        got = sha256_file(dst)
        if got != pins[url]:
            os.remove(dst)
            die("SHA256 对不上: %s\n  期望 %s\n  实际 %s (缓存已删, 重跑一次; 仍不一致说明来源被换过, 先查清楚)" % (url, pins[url], got))
    elif url.startswith(BTBN):
        pass  # 滚动发布, 不固定
    elif trust_new:
        pins[url] = sha256_file(dst)
        with open(PINS_FILE, "w", encoding="utf-8", newline="\n") as f:
            json.dump(pins, f, ensure_ascii=False, indent=1, sort_keys=True)
            f.write("\n")
        say("  记下 SHA256 " + pins[url][:16])
    else:
        die("%s 没有固定的 SHA256 (bundle/pins.json); 确认来源可信后加 --trust-new 记录" % url)
    return dst


def extract_zip(path, dst):
    with zipfile.ZipFile(path) as z:
        z.extractall(dst)
        for info in z.infolist():   # zipfile 不还原可执行权限
            mode = (info.external_attr >> 16) & 0o777
            if mode:
                try:
                    os.chmod(os.path.join(dst, info.filename), mode)
                except OSError:
                    pass


def site_packages(rt, plat):
    return os.path.join(rt, "python", "Lib", "site-packages") if plat == "win64" else os.path.join(rt, "python", "lib", "python" + PY_MINOR, "site-packages")


def install_python(plat, rt, trust_new):
    src = download(PLATFORMS[plat]["python"], trust_new)
    say("== Python")
    with tarfile.open(src) as t:
        t.extractall(rt, filter="data") if sys.version_info >= (3, 12) else t.extractall(rt)
    os.makedirs(site_packages(rt, plat), exist_ok=True)


def install_wheels(plat, rt, requirements):
    say("== 依赖库 (pip download --platform %s)" % ",".join(PLATFORMS[plat]["wheel_platforms"][:1]))
    wd = os.path.join(CACHE, "wheels-" + plat)
    shutil.rmtree(wd, ignore_errors=True)
    os.makedirs(wd)
    cmd = [sys.executable, "-m", "pip", "download", "--only-binary=:all:", "--python-version", PY_MINOR, "--implementation", "cp",
           "--abi", "cp" + PY_MINOR.replace(".", ""), "-r", requirements, "-d", wd, "--disable-pip-version-check", "-q"]
    for p in PLATFORMS[plat]["wheel_platforms"]:
        cmd += ["--platform", p]
    if subprocess.run(cmd).returncode != 0:
        die("pip download 失败 (平台 %s)" % plat)
    sp = site_packages(rt, plat)
    for fn in sorted(os.listdir(wd)):
        if not fn.endswith(".whl"):
            continue
        with zipfile.ZipFile(os.path.join(wd, fn)) as z:
            for info in z.infolist():
                name = info.filename
                m = re.match(r"[^/]+\.data/(purelib|platlib)/(.*)", name)
                if m:
                    name = m.group(2)
                elif ".data/" in name.split("/", 1)[0] + "/":
                    continue    # scripts / headers / data: 运行流水线用不到
                if not name or name.endswith("/"):
                    continue
                out = os.path.join(sp, *name.split("/"))
                os.makedirs(os.path.dirname(out), exist_ok=True)
                with z.open(info) as s, open(out, "wb") as d:
                    shutil.copyfileobj(s, d)
        say("  " + fn)


def slim(plat, rt):
    """去掉运行流水线用不到的部分 (测试、静态库、pip ...), 发布包小一半。只删肯定用不到的; tkinter 与 Tcl/Tk 要留 (窗口界面用)。"""
    py = os.path.join(rt, "python")
    victims = []
    if plat != "win64":
        lib = os.path.join(py, "lib")
        victims += [os.path.join(py, "include"), os.path.join(py, "share")]
        for fn in os.listdir(lib):
            if fn.endswith(".a"):
                victims.append(os.path.join(lib, fn))
        std = os.path.join(lib, "python" + PY_MINOR)
        for d in ("test", "idlelib", "turtledemo", "ensurepip", "idle_test") + tuple(x for x in os.listdir(std) if x.startswith("config-")):
            victims.append(os.path.join(std, d))
    else:
        for dp, _, fns in os.walk(py):          # 调试符号 (.pdb) 几十 MB, 运行用不到
            victims += [os.path.join(dp, fn) for fn in fns if fn.endswith(".pdb")]
        victims += [os.path.join(py, "include"), os.path.join(py, "libs"), os.path.join(py, "Lib", "test"), os.path.join(py, "Lib", "idlelib"),
                    os.path.join(py, "Lib", "turtledemo"), os.path.join(py, "Lib", "ensurepip")]
    sp = site_packages(rt, plat)
    if os.path.isdir(sp):
        victims += [os.path.join(sp, x) for x in os.listdir(sp) if x == "pip" or x.startswith("pip-") or x in ("setuptools", "pkg_resources", "_distutils_hack")
                    or x.startswith("setuptools-")]
    for v in victims:
        if os.path.isdir(v):
            shutil.rmtree(v, ignore_errors=True)
        elif os.path.isfile(v):
            os.remove(v)


def check_encoders(binary):
    with open(binary, "rb") as f:
        data = f.read()
    cfg = re.search(rb"--prefix=[^\x00]{0,3000}", data) or re.search(rb"--enable-gpl[^\x00]{0,3000}", data)
    text = cfg.group(0) if cfg else b""
    missing = [e.decode() for e in NEED_ENCODERS if (b"--enable-" + e) not in text]
    if missing:
        die("%s 的编译配置里没有 %s, 流水线转过场会失败" % (os.path.basename(binary), ", ".join(missing)))


def install_ffmpeg(plat, rt, trust_new):
    say("== ffmpeg")
    ex = ".exe" if plat == "win64" else ""
    dst = os.path.join(rt, "ffmpeg")
    os.makedirs(dst, exist_ok=True)
    for url in PLATFORMS[plat]["ffmpeg"]:
        src = download(url, trust_new)
        tmp = os.path.join(CACHE, "ff-tmp")
        shutil.rmtree(tmp, ignore_errors=True)
        os.makedirs(tmp)
        if src.endswith(".zip"):
            extract_zip(src, tmp)
        else:
            with tarfile.open(src) as t:
                t.extractall(tmp, filter="data") if sys.version_info >= (3, 12) else t.extractall(tmp)
        for dp, _, fns in os.walk(tmp):
            for fn in fns:
                if fn == "ffmpeg" + ex and "__MACOSX" not in dp:
                    shutil.copy2(os.path.join(dp, fn), os.path.join(dst, fn))
                    os.chmod(os.path.join(dst, fn), 0o755)
        shutil.rmtree(tmp, ignore_errors=True)
    if not os.path.isfile(os.path.join(dst, "ffmpeg" + ex)):
        die("没有取到 ffmpeg" + ex)
    check_encoders(os.path.join(dst, "ffmpeg" + ex))


LICENSES = """SwordmanHD 资源获取器 — 随包运行环境的组成与许可 (Bundled runtime components and licenses)

本文件夹里的第三方组件原样未改, 各自按自己的许可分发; 获取器本身是 GPL-3.0-only。

组件                         许可                         出处
Python (CPython 3.12)        PSF License                  https://www.python.org/  (macOS/Linux: https://github.com/astral-sh/python-build-standalone)
numpy                        BSD-3-Clause                 https://numpy.org/
Pillow                       MIT-CMU (HPND)               https://python-pillow.org/
opencv-python-headless       Apache-2.0 (OpenCV), 含 FFmpeg 的 LGPL 部分  https://github.com/opencv/opencv-python
fonttools                    MIT                          https://github.com/fonttools/fonttools
customtkinter / darkdetect / packaging  MIT / BSD-3-Clause / Apache-2.0 或 BSD-2-Clause  https://github.com/TomSchimansky/CustomTkinter
Tcl/Tk (tkinter 的底层)      Tcl/Tk License (BSD 类)      https://www.tcl-lang.org/
opencc-python-reimplemented  Apache-2.0                   https://github.com/yichen0831/opencc-python
FFmpeg (ffmpeg / ffprobe)    GPL-2.0-or-later (含 libx264 等 GPL 组件的构建)

FFmpeg 是 GPL 构建, 源码出处 (Corresponding source):
  FFmpeg 源码: https://ffmpeg.org/download.html  与  https://github.com/FFmpeg/FFmpeg
  Windows / Linux 构建来自 BtbN: https://github.com/BtbN/FFmpeg-Builds  (构建脚本与各组件源码版本见该仓库)
  macOS 构建来自 osxexperts: https://www.osxexperts.net/
各依赖库的许可文本在 python 目录下 site-packages/<包名>-<版本>.dist-info/ 里。
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--platform", required=True, choices=list(PLATFORMS))
    ap.add_argument("--out", required=True)
    ap.add_argument("--requirements", default=os.path.join(HERE, "requirements.txt"), help="要装的 Python 依赖清单 (缺省 bundle/requirements.txt)")
    ap.add_argument("--trust-new", action="store_true", help="没有固定哈希的下载, 记录它的 SHA256 到 pins.json (确认来源可信时才用)")
    a = ap.parse_args()
    rt = os.path.join(os.path.abspath(a.out), "runtime")
    shutil.rmtree(rt, ignore_errors=True)
    os.makedirs(rt)
    install_python(a.platform, rt, a.trust_new)
    install_wheels(a.platform, rt, os.path.abspath(a.requirements))
    install_ffmpeg(a.platform, rt, a.trust_new)
    slim(a.platform, rt)
    with open(os.path.join(rt, "LICENSES.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write(LICENSES)
    size = sum(os.path.getsize(os.path.join(dp, fn)) for dp, _, fns in os.walk(rt) for fn in fns)
    say("完成: %s (%.0f MB)" % (rt, size / 1048576))
    return 0


if __name__ == "__main__":
    sys.exit(main())
