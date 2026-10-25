#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""生成内嵌进程序的「流水线工具包」payload/tools.zip: upstream/ (从游戏仓库同步来的提取脚本) + 本仓库 pipeline/ 的窗口、入口与纯 Python 打包。

  python3 pipeline/make_payload.py [--out payload/tools.zip]

包里的布局 (展开后在 restool-data/): tools/ game/ (来自 upstream/) 与 restool/ (来自 pipeline/ 的 gui.py gui_core.py run.py pack.py pck_writer.py)。
"""
import argparse
import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
UP = os.path.join(REPO, "upstream")
TOP = "SwordmanHD-restool"
OWN = ("gui.py", "gui_core.py", "run.py", "pack.py", "pck_writer.py")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=os.path.join(REPO, "payload", "tools.zip"))
    a = ap.parse_args()
    if not os.path.isfile(os.path.join(UP, "tools", "build_assets.py")):
        sys.exit("错误: upstream/ 是空的 (先运行 python3 pipeline/sync_upstream.py <游戏仓库目录>)")
    items = []
    for dp, _, fns in os.walk(UP):
        for fn in fns:
            full = os.path.join(dp, fn)
            rel = os.path.relpath(full, UP).replace(os.sep, "/")
            if rel != "UPSTREAM.txt" and "__pycache__" not in rel:
                items.append((rel, full))
    items += [("restool/" + fn, os.path.join(HERE, fn)) for fn in OWN]
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with zipfile.ZipFile(a.out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for arc, full in sorted(items):
            info = zipfile.ZipInfo(TOP + "/" + arc, date_time=(2026, 1, 1, 0, 0, 0))   # 固定时间戳: 同样的输入出同样的 zip
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            with open(full, "rb") as f:
                z.writestr(info, f.read())
    print("%s  %d 个文件  %.1f MB" % (a.out, len(items), os.path.getsize(a.out) / 1048576))
    return 0


if __name__ == "__main__":
    sys.exit(main())
