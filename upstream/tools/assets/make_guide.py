#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""游戏内「攻略」面板的内容 (docs/内容格式.md §16): 从玩家版攻略 docs/攻略.md 生成内容包数据
  game/content/remake/guide/guide.json        目录 {"format": "tdj-guide/1", "chapters": [{"id", "file", "stage"?}]}
  game/content/remake/guide/<id>.json         一章 {"title", "label", "stage"?, "body": 正文 (markdown 子集)}
  game/content/remake/locale/hant/guide/...   繁体叠加层 (OpenCC s2tw + tools/assets/hant_fixes.json, 同 make_hant_text.py;
                                              物品/技能/单位名再换成游戏繁体原名, 见 game_name_fixes)
docs/攻略.md 的写法:
  - 每个 "## 标题 {#id}" 是一章, 顺序 = 面板左栏顺序; 第一个 "## " 之前的内容、HTML 注释 (<!-- -->) 不进游戏;
  - 关卡章 id = stage_NN (NN = 关号), 标题 "第N幕 名称" / "番外 名称"; 幕号要符合游戏的叫法 (第 24 关起 = 关号 - 1, 第 35 关 = 番外), 这里核对;
  - 左栏短名: 关卡章 "N 名称" / "番外 名称", 其他章 = 标题。
正文是 markdown 子集 (标题 #、列表 - (缩进两格一级)、粗体 **、分隔线 ---), 面板运行时转 BBCode (engine/ui/guide_text.gd)。
产物进库; 改了 docs/攻略.md 要重跑。用法: python3 tools/assets/make_guide.py [--check]   --check 只比对不写 (CI 用), 过期退出码 1。
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tools/
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _boot  # noqa: E402,F401
from paths import REPO, missing  # noqa: E402
import make_hant_text as MH  # noqa: E402
import make_locale as ML  # noqa: E402

FORMAT = "tdj-guide/1"
SRC = "docs/攻略.md"
OUT = "game/content/remake/guide"
OUT_HANT = "game/content/remake/locale/hant/guide"
CHAPTER_RE = re.compile(r"^##\s+(.+?)\s*\{#([a-z0-9_]+)\}\s*$")
STAGE_ID_RE = re.compile(r"^stage_(\d\d)$")
STAGE_TITLE_RE = re.compile(r"^(?:第(\d+)幕|(番外))\s+(.+)$")
EXTRA_STAGE = 35   # 番外关 (第 34 关打倒心脏后的隐藏关)
SHIFT_FROM = 24    # 第 23 幕有两关 (23 焚炎劫火 / 24 黄泉幽径), 此后幕号 = 关号 - 1
NAME_TABLES = ("items", "skills", "units")   # 繁体里这些名字用游戏原名 (game/content/tdj/locale/hant/data)


def stage_mu(n):
    """关号 -> 游戏里的幕号文字 ("番外" 或数字)"""
    if n == EXTRA_STAGE:
        return "番外"
    return str(n - 1 if n >= SHIFT_FROM else n)


def parse(text):
    """docs/攻略.md -> [(id, 标题, 正文)]"""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    chapters = []
    for ln in text.split("\n"):
        m = CHAPTER_RE.match(ln)
        if m:
            chapters.append([m.group(2), m.group(1), []])
        elif ln.startswith("# ") or ln.startswith("## "):
            if chapters:
                raise SystemExit("%s: 章标题要写成 \"## 标题 {#id}\": %s" % (SRC, ln))
        elif chapters:
            chapters[-1][2].append(ln.rstrip())
    if not chapters:
        raise SystemExit("%s: 没有章 (\"## 标题 {#id}\")" % SRC)
    out = []
    seen = set()
    for cid, title, body in chapters:
        if cid in seen or cid == "guide":
            raise SystemExit("%s: 章 id 重复或保留: %s" % (SRC, cid))
        seen.add(cid)
        out.append((cid, title, re.sub(r"\n{3,}", "\n\n", "\n".join(body)).strip("\n") + "\n"))
    return out


def stage_name(n):
    """游戏数据里的关名 (stage.json 的 name 去掉「第X幕」与空白); 没有则空串"""
    p = os.path.join(REPO, "game", "content", "tdj", "stages", "%02d" % n, "stage.json")
    if not os.path.exists(p):
        return ""
    with open(p, encoding="utf-8") as fh:
        name = str(json.load(fh).get("name", ""))
    return re.sub(r"^第[零一二三四五六七八九十百]+幕", "", name).replace(" ", "").replace("\u3000", "")


def chapter(cid, title, body):
    """-> (目录项, 章对象)"""
    m = STAGE_ID_RE.match(cid)
    if not m:
        return {"id": cid, "file": "guide/%s.json" % cid}, {"title": title, "label": title, "body": body}
    n = int(m.group(1))
    t = STAGE_TITLE_RE.match(title)
    mu = t and (t.group(2) or t.group(1))
    if mu != stage_mu(n):
        raise SystemExit("%s: 第 %d 关的标题应以「%s」开头: %s" % (
            SRC, n, "番外" if stage_mu(n) == "番外" else "第%s幕" % stage_mu(n), title))
    game_name = stage_name(n)
    if game_name and t.group(3).replace(" ", "") != game_name:   # 章名以游戏自己的关名为准 (网上攻略常有异写)
        raise SystemExit("%s: 第 %d 关章名「%s」与游戏关名「%s」不一致" % (SRC, n, t.group(3), game_name))
    label = "%s %s" % (mu, t.group(3))
    return ({"id": cid, "file": "guide/%s.json" % cid, "stage": n},
            {"title": title, "label": label, "stage": n, "body": body})


def build():
    """-> {相对 OUT 的文件名: 对象}"""
    with open(os.path.join(REPO, SRC), encoding="utf-8") as f:
        chapters = parse(f.read())
    files, toc = {}, []
    for cid, title, body in chapters:
        entry, obj = chapter(cid, title, body)
        toc.append(entry)
        files[cid + ".json"] = obj
    files["guide.json"] = {"format": FORMAT,
                           "_note": "游戏内攻略 (F4 / 设定面板「攻略」) 的目录, 由 tools/assets/make_guide.py 从 docs/攻略.md 生成, 不要手改。格式见 docs/内容格式.md §16",
                           "chapters": toc}
    return files


def game_name_fixes(fixes):
    """物品/技能/单位名: 机器转出的繁体 -> 游戏里的繁体原名 (如 天河硃砂 -> 天河朱砂), 让攻略和游戏里看到的名字一致"""
    out = {}
    for table in NAME_TABLES:
        simp = os.path.join(REPO, "game/content/tdj/data/%s.json" % table)
        trad = os.path.join(REPO, "game/content/tdj/locale/hant/data/%s.json" % table)
        if not (os.path.isfile(simp) and os.path.isfile(trad)):
            continue
        # 叠加层只写和简体不同的字段: 没写 name 的, 繁体名就是简体名 (如 天河朱砂)
        tnames = {r.get("id"): r["name"] for r in json.load(open(trad, encoding="utf-8")) if r.get("name")}
        for r in json.load(open(simp, encoding="utf-8")):
            s = r.get("name")
            t = tnames.get(r.get("id"), s)
            if s and len(s) >= 2:
                conv = MH.to_hant(s, fixes)
                if conv != t and len(conv) == len(t):
                    out[conv] = t
    return sorted(out.items(), key=lambda kv: -len(kv[0]))   # 长的先换


def hant_tree(o, fixes, names):
    if isinstance(o, str):
        s = MH.to_hant(o, fixes)
        for a, b in names:
            s = s.replace(a, b)
        return s
    if isinstance(o, dict):
        return {k: (v if str(k).startswith("_") else hant_tree(v, fixes, names)) for k, v in o.items()}
    return o


def hant(files):
    fixes = MH.load_fixes()
    names = game_name_fixes(fixes)
    out = {}
    for name, obj in files.items():
        if name == "guide.json":
            continue
        d = ML.Diff()
        r = ML.text_diff(obj, hant_tree(obj, fixes, names), d, name)
        if r:
            out[name] = r
    return out


def dump(o):
    return json.dumps(o, ensure_ascii=False, indent=1) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    files = build()
    targets = [(OUT, files)]
    if missing("content"):   # 繁体叠加层要用 tdj 里的游戏繁体原名 (game_name_fixes), 缺时生成结果不对: 不比对也不改写
        print("注意: 缺生成内容包 game/content/tdj, 跳过繁体叠加层 %s 与关名核对 (python3 tools/build_assets.py 生成后再跑)" % OUT_HANT)
    else:
        targets.append((OUT_HANT, hant(files)))
    bad = 0
    for d, fs in targets:
        absd = os.path.join(REPO, d)
        have = set(os.listdir(absd)) if os.path.isdir(absd) else set()
        for name, obj in sorted(fs.items()):
            p = os.path.join(absd, name)
            text = dump(obj)
            cur = open(p, encoding="utf-8").read() if os.path.isfile(p) else None
            if cur == text:
                continue
            if a.check:
                print("过期: %s/%s (重跑 tools/assets/make_guide.py)" % (d, name))
                bad += 1
                continue
            os.makedirs(absd, exist_ok=True)
            with open(p, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
        for extra in sorted(have - set(fs)):
            if extra.endswith(".json"):
                if a.check:
                    print("多余: %s/%s (%s 里已没有这一章, 重跑 tools/assets/make_guide.py)" % (d, extra, SRC))
                    bad += 1
                else:
                    os.remove(os.path.join(absd, extra))
    if not a.check:
        print("攻略: %d 章 -> %s (繁体叠加层 %s)" % (len(files) - 1, OUT, OUT_HANT))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
