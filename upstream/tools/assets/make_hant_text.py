#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""手写文字 (不是原版文本, 没有繁体原文) 转繁体, 生成 locale/hant 叠加层 (设计 docs/设计_繁简切换.md §4):
  game/content/remake/text/ui.json      界面文案           -> game/content/remake/locale/hant/text/ui.json
  game/content/tdj/data/enums.json      数据表里编号字段的显示名 -> game/content/tdj/locale/hant/data/enums.json
转换: OpenCC s2tw (词组级, 头发/發现、干净/树干、前历/历史 能分清; 不用 s2twp 的台湾电脑用语, 菜单仍是「菜單」),
再套 tools/assets/hant_fixes.json 人工校对表:
  "exact":   {简体整句: 繁体整句}      整句替换 (优先, 机器转错的整句在这里写对)
  "replace": {转换后的片段: 改成的片段}  片段替换 (按表顺序)
产物进库, 评审时看 locale/hant 即可。原版文本 (对白/物品/技能名) 不走这里, 见 make_locale.py。
用法: python3 tools/assets/make_hant_text.py [--check]   --check 只检查产物与表是否一致 (不写文件, CI 用), 不一致退出码 1。
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tools/
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _boot  # noqa: E402,F401
from paths import REPO, missing  # noqa: E402
import make_locale as ML  # noqa: E402

FIXES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hant_fixes.json")
# (简体源文件, 叠加层输出)  路径相对仓库根
SOURCES = [
    ("game/content/remake/text/ui.json", "game/content/remake/locale/hant/text/ui.json"),
    ("game/content/tdj/data/enums.json", "game/content/tdj/locale/hant/data/enums.json"),
]
_cc = None


def load_fixes(path=FIXES):
    if not os.path.isfile(path):
        return {"exact": {}, "replace": {}}
    d = json.load(open(path, encoding="utf-8"))
    return {"exact": d.get("exact", {}), "replace": d.get("replace", {})}


def to_hant(s: str, fixes: dict) -> str:
    global _cc
    if s in fixes["exact"]:
        return fixes["exact"][s]
    if _cc is None:
        import opencc
        _cc = opencc.OpenCC("s2tw")
    out = _cc.convert(s)
    for a, b in fixes["replace"].items():
        out = out.replace(a, b)
    return out


def convert_tree(o, fixes):
    """结构不变, 字符串叶子转繁体 (`_` 开头的说明键原样保留, 不进叠加层)"""
    if isinstance(o, str):
        return to_hant(o, fixes)
    if isinstance(o, dict):
        return {k: (v if str(k).startswith("_") else convert_tree(v, fixes)) for k, v in o.items()}
    if isinstance(o, list):
        return [convert_tree(v, fixes) for v in o]
    return o


def build(src_rel: str, fixes: dict):
    a = json.load(open(os.path.join(REPO, src_rel), encoding="utf-8"))
    d = ML.Diff()
    r = ML.text_diff(a, convert_tree(a, fixes), d, src_rel)
    return r, d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    fixes = load_fixes()
    bad = 0
    no_tdj = bool(missing("content"))
    for src, dst in SOURCES:
        if no_tdj and src.startswith("game/content/tdj/"):  # 生成内容包不在 (公开仓库/无原版): 只处理手写部分
            print("注意: 缺生成内容包 game/content/tdj, 跳过 %s (python3 tools/build_assets.py 生成后再跑)" % src)
            continue
        r, d = build(src, fixes)
        text = json.dumps(r or {}, ensure_ascii=False, indent=1) + "\n"
        p = os.path.join(REPO, dst)
        if a.check:
            cur = open(p, encoding="utf-8").read() if os.path.isfile(p) else ""
            if cur != text:
                print("过期: %s (重跑 tools/assets/make_hant_text.py)" % dst)
                bad += 1
            continue
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        print("%s: %d 处文字 -> %s" % (src, d.strings, dst))
        for w in d.warnings:
            print("  警告:", w)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
