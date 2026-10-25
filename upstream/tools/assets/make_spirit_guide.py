#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""玩家版攻略 docs/攻略.md 里的「五魂」各页: 按数据表 (levelup.json 技能习得条件 + party_init.json 初始五魂) 生成,
写进 docs/攻略.md 的 <!-- spirit:begin --> ... <!-- spirit:end --> 之间 (整段替换, 其余内容不动); 之后跑 make_guide.py 生成游戏内章节。
每个主角一页「五魂 <名>」: 初始状态、技能习得表 (等级 + 五魂要求)、五魂规划 (学全要加多少点、几级够、点数不够时怎么取舍);
外加一页「五魂说明」(规则)。章节 id: spirit (说明)、spirit_<unit_id> (各人), 营地「五魂化蘊」按查看键打开的就是 spirit_<unit_id>。
用法: python3 tools/assets/make_spirit_guide.py [--check]   --check 只检查 docs/攻略.md 里的段落是否与数据一致 (不写), 不一致退出码 1。
"""
import argparse
import itertools
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tools/
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _boot  # noqa: E402,F401
from paths import REPO  # noqa: E402

DOC = os.path.join(REPO, "docs", "攻略.md")
DATA = os.path.join(REPO, "game", "content", "tdj", "data")
BEGIN = "<!-- spirit:begin -->"
END = "<!-- spirit:end -->"
SP = ["迅", "烈", "神", "魔", "魂"]
LV_CAP = 99      # 等级上限 (规划用)
SLOTS = 10       # 技能栏格数
PER_LEVEL = 2    # 每级五魂点
SPIRIT_CAP = 100


def load(name):
    with open(os.path.join(DATA, name), encoding="utf-8") as f:
        return json.load(f)


def fmt_req(req):
    """五魂要求: 只写非 0 的 '迅25 烈25'; 全 0 = 无要求"""
    parts = ["%s%d" % (SP[i], req[i]) for i in range(5) if req[i] > 0]
    return " ".join(parts) if parts else "无五魂要求"


def fmt_vals(v):
    return " ".join("%s%d" % (SP[i], v[i]) for i in range(5))


def deficit(target, init):
    return [max(0, target[i] - init[i]) for i in range(5)]


def union(skills):
    return [max((s["req"][i] for s in skills), default=0) for i in range(5)]


def best_subsets(skills, init, budget):
    """点数预算内能同时学会的最多招数的组合 (五魂要求取并集的缺口之和 <= budget, 每魂 <= 100); 返回 [(招数, 缺口合计, [技能])]"""
    n = len(skills)
    best = []
    top = 0
    for m in range(1, 1 << n):
        sel = [skills[i] for i in range(n) if m >> i & 1]
        u = union(sel)
        if max(u) > SPIRIT_CAP:
            continue
        d = sum(deficit(u, init))
        if d > budget:
            continue
        if len(sel) > top:
            top, best = len(sel), []
        if len(sel) == top:
            best.append((top, d, sel))
    return best


def hero_page(h, p):
    uid = h["unit_id"]
    init = [p["spirit"][k] for k in SP]
    join = p["lv"]
    skills = [{"lv": s["lv"], "name": s["_skill_name"], "req": [s["spirit_request"][k] for k in SP]}
              for s in h["skills"] if s["skill_id"] >= 0]
    skills.sort(key=lambda s: s["lv"])   # 稳定排序: 同级保持数据表顺序
    name = h["_name"]
    budget = PER_LEVEL * (LV_CAP - join)
    out = []
    out.append("## 五魂 %s {#spirit_%d}" % (name, uid))
    out.append("")
    out.append("- **初始**：Lv%d，五魂 %s（合计 %d 点）" % (join, fmt_vals(init), sum(init)))
    have = p.get("_skill_names") or []
    if have:
        out.append("- **已会的技能**：" + "、".join(have))
    out.append("- **点数**：每升 1 级得 %d 点（营地「五魂化蕴」里加），每魂最多 %d。从 Lv%d 起算，升到 Lv%d 一共能加 %d 点" % (PER_LEVEL, SPIRIT_CAP, join, LV_CAP, budget))
    out.append("")
    out.append("**技能习得**（等级和五魂都够，下一次升级时学会）")
    for s in skills:
        out.append("- Lv%d %s：%s" % (s["lv"], s["name"], fmt_req(s["req"])))
    out.append("")
    out.append("**五魂规划**")
    u = union(skills)
    d = deficit(u, init)
    need = sum(d)
    lv_last = max(s["lv"] for s in skills)
    if need <= budget:
        lv_pts = join + (need + PER_LEVEL - 1) // PER_LEVEL
        out.append("- 全部学会，五魂至少要到：%s。比初始多加 %d 点（%s），点数够用要 Lv%d，最后一招要 Lv%d" % (
            fmt_vals(u), need, fmt_vals(d), max(lv_pts, join), lv_last))
        out.append("- 缺口多的魂先加；每次加完要再升一级才会学到")
    else:
        out.append("- 全部学会要五魂 %s，比初始多加 %d 点，而升到 Lv%d 最多只能加 %d 点，**学不全，要取舍**" % (fmt_vals(u), need, LV_CAP, budget))
        combos = best_subsets(skills, init, budget)
        if combos:
            top = combos[0][0]
            out.append("- 点数最多能同时学会 %d 招，有 %d 种取法：" % (top, len(combos)))
            for _, dd, sel in combos[:4]:
                keep = [s["name"] for s in sel]
                lost = [s["name"] for s in skills if s["name"] not in keep]
                out.append("  - 放弃 %s（要加 %d 点）" % ("、".join(lost), dd))
    n_have = len(have)
    if n_have + len(skills) > SLOTS:
        out.append("- 技能栏只有 %d 格：已会 %d 招 + 可学 %d 招 = %d 招，装不下的学不进去（升级窗仍会提示）" % (SLOTS, n_have, len(skills), n_have + len(skills)))
    # 五魂紧缺的人: 各魂缺口一览
    out.append("- 各魂离学全还差（按初始值）：%s" % fmt_vals(d))
    out.append("")
    return "\n".join(out)


def general_page():
    return "\n".join([
        "## 五魂说明 {#spirit}",
        "",
        "五魂：迅、烈、神、魔、魂。五魂不影响攻击、防御、命中、回避，作用有两处：学技能的条件、法术打在人身上的效果。",
        "",
        "**怎么加**",
        "- 每升 1 级得 2 点，不能买、不能捡；只能在营地「五魂化蕴」里分配（战斗中不行）。",
        "- 每一魂最多加到 100。",
        "- 营地「五魂化蕴」里按查看键（F，手柄 X），直接打开这个人的「五魂」页。",
        "",
        "**怎么学技能**",
        "- 技能要等级和五魂都够，在**升级的那一刻**才判定；营地里把五魂加够后，要再升一级才会学到，刚好凑够的那一级也一样。",
        "- 以前等级到了、五魂没够的技能，之后五魂补够，任意一次升级都会补学。",
        "- 技能栏 10 格，满了学不进去。",
        "",
        "**五魂和法术效果**",
        "- 看的是**被打的那个人**的五魂。冰、火系法术，对方烈、魔越高伤害越小；雷系看迅、神；暗系看魔、魂；光系对方魂高伤害小、魔高反而更痛（破魔）。",
        "- 治疗术：对方神越高，回复越多。",
        "- 物理绝技多数是烈、迅高的人吃得少。",
        "",
        "各人的技能要求和五魂规划，见后面每个人的「五魂」页。",
        "",
    ])


def build():
    levelup = {h["unit_id"]: h for h in load("levelup.json")}
    party = {p["unit_id"]: p for p in load("party_init.json")}
    order = [0, 1, 2, 3, 4, 5, 6, 7, 8]
    parts = [general_page()]
    for uid in order:
        if uid in levelup and uid in party and any(s["skill_id"] >= 0 for s in levelup[uid]["skills"]):
            parts.append(hero_page(levelup[uid], party[uid]))
    return "\n".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    with open(DOC, encoding="utf-8") as f:
        text = f.read()
    if BEGIN not in text or END not in text:
        print("docs/攻略.md 里没有 %s / %s 标记" % (BEGIN, END))
        return 2
    head, rest = text.split(BEGIN, 1)
    _, tail = rest.split(END, 1)
    new = head + BEGIN + "\n\n" + build() + "\n" + END + tail
    if new == text:
        print("五魂各页: 已是最新")
        return 0
    if a.check:
        print("五魂各页过期: python3 tools/assets/make_spirit_guide.py")
        return 1
    with open(DOC, "w", encoding="utf-8", newline="\n") as f:
        f.write(new)
    print("五魂各页已写入 docs/攻略.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
