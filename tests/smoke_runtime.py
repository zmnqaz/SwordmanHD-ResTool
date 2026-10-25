# SPDX-License-Identifier: GPL-3.0-only
"""随包运行环境的冒烟检查: 在真实的目标系统上 (GitHub Actions 的 Windows / macOS / Linux 机器) 用包里的 Python 跑。

  <runtime>/python/... python tests/smoke_runtime.py --runtime <runtime 目录> --data <展开后的「restool-data」目录> [--no-tk]

检查: 依赖库都能导入并真的能用 (Pillow 画图、numpy 计算、fonttools、opencc 转换)、Tk 能起来、ffmpeg 带三个编码器 (libx264 / libtheora / libvorbis)、
内嵌的流水线脚本在这个系统上能导入并运行、纯 Python 的 .pck 写入器能写能校验。任何一项不对就退出码非 0。
"""
import argparse
import os
import subprocess
import sys
import tempfile

ok_all = True
for _s in (sys.stdout, sys.stderr):   # Windows 控制台默认 cp1252, 打印中文会崩: 一律 UTF-8
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def check(name, fn):
    global ok_all
    try:
        detail = fn()
        print("  ok   %-26s %s" % (name, detail or ""), flush=True)
    except Exception as e:   # noqa: BLE001
        ok_all = False
        print("  FAIL %-26s %s: %s" % (name, type(e).__name__, e), flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runtime", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--no-tk", action="store_true", help="没有显示环境时跳过 Tk 检查")
    a = ap.parse_args()
    rt, data = os.path.abspath(a.runtime), os.path.abspath(a.data)
    print("Python %s (%s)" % (sys.version.split()[0], sys.executable))

    def libs():
        import numpy
        from PIL import Image
        import fontTools
        import opencc
        import customtkinter
        im = Image.new("RGBA", (4, 4), (10, 20, 30, 255))
        assert im.getpixel((1, 1)) == (10, 20, 30, 255)
        assert int(numpy.arange(10).sum()) == 45
        assert opencc.OpenCC("s2t").convert("汉字") == "漢字"
        return "numpy %s, Pillow %s, fonttools %s, customtkinter %s" % (numpy.__version__, Image.__version__, fontTools.version, customtkinter.__version__)
    check("依赖库", libs)

    def tk():
        import tkinter
        import customtkinter as ctk
        root = ctk.CTk()
        ctk.CTkLabel(root, text="自检 selftest").pack()
        root.update()
        root.destroy()
        return "Tk %s" % tkinter.TkVersion
    if a.no_tk:
        print("  skip Tk (--no-tk)")
    else:
        check("Tk 窗口", tk)

    def ffmpeg():
        exe = os.path.join(rt, "ffmpeg", "ffmpeg.exe" if os.name == "nt" else "ffmpeg")
        out = subprocess.run([exe, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=120).stdout
        miss = [e for e in ("libx264", "libtheora", "libvorbis") if e not in out]
        assert not miss, "缺编码器 %s" % miss
        return "libx264 libtheora libvorbis"
    check("ffmpeg 编码器", ffmpeg)

    sys.path[:0] = [os.path.join(data, "tools"), os.path.join(data, "tools", "assets"), os.path.join(data, "restool")]

    def payload():
        os.environ["TDJ_GODOT"] = sys.executable
        import build_assets  # noqa: F401
        import gui_core
        import pck_writer  # noqa: F401
        import texture_classes  # noqa: F401
        r = subprocess.run([sys.executable, os.path.join(data, "tools", "build_assets.py"), "--list"], capture_output=True, text=True, timeout=120)
        assert r.returncode == 0 and "export" in r.stdout, r.stdout + r.stderr
        assert gui_core.looks_like_game(data)[0] is False
        return "build_assets / gui_core / texture_classes 能导入"
    check("内嵌流水线脚本", payload)

    def pck():
        import pck_writer
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "a.bin")
            with open(f, "wb") as fh:
                fh.write(b"x" * 100)
            out = os.path.join(d, "t.pck")
            pck_writer.write_pck(out, [(f, "res://a/b.bin"), (f, "res://中文.bin")])
            return "%d 个文件校验通过" % pck_writer.check_pck(out)
    check("pck 写入与校验", pck)

    print("全部通过" if ok_all else "有失败项")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
