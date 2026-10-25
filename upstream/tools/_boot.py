# SPDX-License-Identifier: GPL-3.0-only
"""tools/ 下脚本的统一路径引导 (取代各脚本自己写的 `HERE = ...; sys.path.insert(0, HERE)` 样板)。

在 tools/ 顶层的脚本里, Python 已经把脚本目录放进 sys.path, 直接  import paths  即可, 用不着本模块。
放在 tools/ 子目录 (assets/ checks/ qa/ docgen/ legal/ perf/ platform/ parity/ ...) 的脚本开头写两行:

    import os, sys; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tools/ (子目录再深一层就多套一个 dirname)
    import _boot  # noqa: F401,E402  之后 import paths / import regress_compare 等 tools/ 顶层模块都能用

提供:
    _boot.TOOLS   tools/ 目录绝对路径
    _boot.REPO    仓库根 (= paths.REPO)
    _boot.paths   tools/paths.py (original_dir()/hd4x_dir()/godot_exe()/require() ...)
    _boot.rel(p)  相对仓库根的路径 (用于打印)
脚本里不要写死 <工作目录>/... 之类的本机路径: 一律经 paths.py 或环境变量 (守卫: tools/checks/no_abs_paths.py, CI 的 no-abs-paths 步骤)。
"""
import os
import sys

TOOLS = os.path.dirname(os.path.abspath(__file__))
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)
# 按用途分类的子目录也进 sys.path: 脚本之间仍按模块名互相 import (import paths / import compile_events / import regress_compare ...),
# 与所在子目录无关; 子目录排在 tools/ 前面, 保证拿到真实模块而不是旧路径 shim。
for _sub in ("assets", "checks", "qa", "docgen", "legal", "perf", "platform"):
    _d = os.path.join(TOOLS, _sub)
    if _d not in sys.path:
        sys.path.insert(0, _d)

import paths  # noqa: E402

REPO = paths.REPO


def rel(p):
    return paths.relpath(p)
