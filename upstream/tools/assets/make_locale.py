#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""生成内容包的繁体叠加层 game/content/tdj/locale/hant/ (设计 docs/设计_繁简切换.md)。
做法与简体一致, 都是导入时一次性生成, 运行时不转换:
  1. 用 TDJ_TEXT_LANG=hant 把导入链路 (parse_data -> export_text -> import_content) 再跑一遍到临时目录 .work/locale_hant/,
     与简体版唯一的区别是文本保留原版 Big5 繁体原文 (tools/assets/export_text.py 的 to_simplified);
  2. 对内容包里每个 JSON, 逐字段比对简体版与繁体版, **只把不同的文字**写进 locale/hant/<同路径>:
       对象: 只含不同的叶子 (`_` 开头的说明字段不比);  数据表 (manifest.tables): 只含 {键, 不同的字段} 的记录;
       其他数组 (对白 groups 等): 有差异就整个数组替换。
     ContentDB 在繁体模式下把它们合到简体数据之上 (对象深合并, 数组整个替换, 表按键合并)。
  叠加层与内容包一样是生成物, 不手改。
用法: python3 tools/assets/make_locale.py [--keep-tmp]      需要原版目录 (tools/paths.py), 约一分钟。
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tools/
import _boot  # noqa: E402,F401
from paths import REPO, original_dir  # noqa: E402

PACK = os.path.join(REPO, "game", "content", "tdj")
LANG = "hant"
SKIP_TOP = ("scripts", "ui_theme", "locale")   # 不是导入工具生成的文本, 不比
SKIP_FILES = ("textures.json", "manifest.json", "events_raw.json")


class Diff:
    def __init__(self):
        self.warnings = []
        self.strings = 0


def strip_notes(x):
    """去掉 `_` 开头的说明字段 (它们不进游戏, 繁简两版里本来就不同), 比较数组是否相同时用"""
    if isinstance(x, dict):
        return {k: strip_notes(v) for k, v in x.items() if not str(k).startswith("_")}
    if isinstance(x, list):
        return [strip_notes(v) for v in x]
    return x


def text_diff(a, b, d: Diff, path="", table_key=None):
    """b 相对 a 不同的文字叶子, 保持结构; 没有差异返回 None。非文字的差异 (两版结构不一致) 记 warning。"""
    if isinstance(a, str) and isinstance(b, str):
        if a != b:
            d.strings += 1
            return b
        return None
    if isinstance(a, dict) and isinstance(b, dict):
        out = {}
        for k, vb in b.items():
            if str(k).startswith("_"):
                continue
            if k not in a:
                d.warnings.append("%s/%s: 繁体版多出的键" % (path, k))
                continue
            r = text_diff(a[k], vb, d, "%s/%s" % (path, k))
            if r is not None:
                out[k] = r
        return out or None
    if isinstance(a, list) and isinstance(b, list):
        if strip_notes(a) == strip_notes(b):
            return None
        if table_key and len(a) == len(b) and all(isinstance(x, dict) and table_key in x for x in a + b):
            out = []
            for i, (ra, rb) in enumerate(zip(a, b)):
                if ra.get(table_key) != rb.get(table_key):
                    d.warnings.append("%s[%d]: 两版键不一致" % (path, i))
                    continue
                r = text_diff(ra, rb, d, "%s[%d]" % (path, i))
                if r is not None:
                    out.append({table_key: rb[table_key], **r})
            return out or None
        if len(a) != len(b):
            d.warnings.append("%s: 数组长度不同 (%d / %d), 整个替换" % (path, len(a), len(b)))
        n = sum(1 for x, y in zip(a, b) if x != y) if len(a) == len(b) else 1
        d.strings += n
        return b
    if a != b:
        d.warnings.append("%s: 非文字字段两版不同 (%r / %r), 忽略" % (path, a, b))
    return None


def table_keys(manifest: dict) -> dict:
    """数据表文件 (相对内容包根) -> 合并键"""
    return {spec["file"]: spec.get("key", "id") for spec in manifest.get("tables", {}).values()}


def json_files(root):
    for r, ds, fs in os.walk(root):
        rel_dir = os.path.relpath(r, root).replace(os.sep, "/")
        if rel_dir == ".":
            ds[:] = [x for x in ds if x not in SKIP_TOP]
        for f in sorted(fs):
            if f.endswith(".json") and f not in SKIP_FILES:
                yield (f if rel_dir == "." else rel_dir + "/" + f)


def build_overlay(base_root: str, hant_root: str, out_root: str):
    """比对两个内容包目录, 把差异写到 out_root (相对路径同内容包)。返回 (写出文件数, Diff)"""
    keys = table_keys(json.load(open(os.path.join(base_root, "manifest.json"), encoding="utf-8")))
    d = Diff()
    n = 0
    for rel in json_files(base_root):
        pb = os.path.join(hant_root, rel)
        if not os.path.isfile(pb):
            d.warnings.append("%s: 繁体版没有生成" % rel)
            continue
        a = json.load(open(os.path.join(base_root, rel), encoding="utf-8"))
        b = json.load(open(pb, encoding="utf-8"))
        r = text_diff(a, b, d, rel, keys.get(rel))
        if r is None:
            continue
        dst = os.path.join(out_root, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "w", encoding="utf-8", newline="\n") as f:
            json.dump(r, f, ensure_ascii=False, indent=1)
            f.write("\n")
        n += 1
    return n, d


def run(script, *args, env):
    r = subprocess.run([sys.executable, os.path.join(REPO, "tools", "assets", script), *args], env=env,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print(r.stdout[-2000:])
        raise SystemExit("错误: %s 失败 (退出码 %d)" % (script, r.returncode))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep-tmp", action="store_true", help="保留 .work/locale_hant/ (排查用)")
    a = ap.parse_args()
    tmp = os.path.join(REPO, ".work", "locale_hant")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    env = dict(os.environ, TDJ_TEXT_LANG=LANG)
    orig = original_dir()
    print("== 繁体导入链路 (原版 Big5 原文, 不转简体) -> %s" % os.path.relpath(tmp, REPO))
    run("parse_data.py", "--root", tmp, env=env)
    run("export_text.py", orig, os.path.join(tmp, "data", "emsg"), env=env)
    run("import_content.py", "--out", os.path.join(tmp, "content"), "--data-root", tmp, env=env)
    out = os.path.join(PACK, "locale", LANG)
    shutil.rmtree(out, ignore_errors=True)
    n, d = build_overlay(PACK, os.path.join(tmp, "content"), out)
    print("== 叠加层 %s: %d 个文件, %d 处文字差异" % (os.path.relpath(out, REPO), n, d.strings))
    for w in d.warnings[:30]:
        print("  警告:", w)
    if len(d.warnings) > 30:
        print("  ... 另有 %d 条警告" % (len(d.warnings) - 30))
    if not a.keep_tmp:
        shutil.rmtree(tmp, ignore_errors=True)
    return 1 if d.warnings else 0


if __name__ == "__main__":
    sys.exit(main())
