#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""把《天地劫：神魔至尊传》原版的核心配置 DAT/MSG 解析成 JSON.

输入: original/Misc/*.DAT|*.MSG, original/Stage/StageNN/{MAN,SDES}_NN.DAT, map NN.dtl
输出: data/*.json (UTF-8, 文本保持繁体)

字段布局参考 foxgame/Sword (Unity 重制版) 的 Data/*.cs, 并对照原始数据核对过.
字段含义的说明与可信度见 docs/原版数据格式.md.

用法: python3 tools/assets/parse_data.py [--root <仓库根>]
"""
import argparse
import glob
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tools/
import _boot  # noqa: E402,F401
from paths import original_dir  # noqa: E402
from export_text import to_simplified  # noqa: E402

# ---------------------------------------------------------------- 常量 / 枚举

ITEM_TYPE = {0: "道具", 1: "武器", 2: "护具", 3: "饰物"}
# GameAttributeType: 伤害/抗性的六个属性槽 + 治疗
ATTR = {-1: None, 0: "雷", 1: "火", 2: "冰", 3: "幻", 4: "光", 5: "暗", 6: "治疗"}
ATTR6 = ["雷", "火", "冰", "幻", "光", "暗"]
SPIRIT = ["迅", "烈", "神", "魔", "魂"]          # 五魂
PARTY = ["殷剑平", "封寒月", "上官远", "紫枫", "鲜于超", "真胤", "韩千秀", "燕明蓉", "夏侯仪", "不净散人"]
RANGE_TYPE = {0: "菱形(曼哈顿距离)", 1: "直线"}
TARGET = {-1: None, 0: "我方", 1: "敌方", 2: "空格(召唤)"}
ATTACK_ADD = {-1: None, 0: "吸血", 1: "中毒", 2: "麻痹", 3: "封咒", 4: "地缚", 5: "驱散增益"}
ITEM_USE = {-1: None, 0: "恢复(Recovery)", 1: "治疗(Cure)", 2: "上限提升(Limit)", 3: "发动技能(Skill)"}
ITEM_EFFECT = {-1: None, 0: "体力", 1: "术力", 2: "解毒", 3: "解麻痹", 4: "解封咒",
               5: "体力上限", 6: "术力上限", 7: "攻击(膂力)上限", 8: "咒术(灵智)上限",
               9: "行动力上限", 10: "防御(筋骨)上限", 11: "机运上限"}
SKILL_RESULT = {-1: None, 0: "伤害", 1: "治疗", 2: "净化", 3: "祝福", 4: "诅咒", 5: "特殊"}
SKILL_EFFECT = {-1: None, 0: "攻击提升", 1: "防御提升", 2: "咒术提升", 3: "行动力提升", 4: "狂暴",
                5: "物理免疫", 6: "咒术免疫", 7: "闪避", 8: "中毒", 9: "麻痹", 10: "封咒", 11: "地缚",
                12: "驱散增益", 13: "反召唤(对召唤物伤害x2)", 14: "召唤", 15: "召唤复活", 16: "遁地"}
SKILL_OTHER_TYPE = {-1: None, 0: "Normal", 1: "Target", 2: "Self"}
SKILL_OTHER = {-1: None, 0: "伤害x2", 1: "伤害x3", 2: "伤害x4", 3: "附加麻痹", 4: "附加中毒",
               5: "附加封咒", 6: "吸血", 7: "吸取术力", 8: "附加地缚", 9: "自爆", 10: "物理无敌",
               11: "咒术无敌", 12: "驱散增益", 13: "全复+全净化", 14: "能力全提升", 15: "术力恢复"}
SKILL_ADD_TYPE = {-1: None, 0: "目标", 1: "自身"}
BATTLE_TYPE = {-1: "全屏咒术动画(Magic/)", 0: "战斗画面(物理绝技)", 1: "地图上演出", 2: "战斗画面+地图"}
MOVE_TYPE = {0: "步行0", 1: "步行1", 2: "步行2", 3: "步行3", 4: "飞行4", 5: "飞行5", 6: "飞行6",
             7: "步行7", 8: "飞行8", 9: "飞行9", 10: "步行10", 11: "不可移动", 12: "飞行(事件)"}
CAMP = {0: "我方", 1: "敌方"}
AI = {-1: None, 0: "原地待机", 1: "主动出击", 2: "消极(被打后转主动)", 3: "向指定单位移动",
      4: "向指定坐标移动"}
# 地形类别 (DTL 的 Move 字节) —— 名称是根据地图图像比对推测的
TERRAIN_GUESS = {0: "石阶/铺砌路面(推测)", 1: "土地/平地(推测)", 2: "草丛/田地/杂物(推测)",
                 3: "未确认", 4: "小型障碍(车轮/木桩等, 推测)", 5: "碎石/岩块(推测)", 6: "未确认",
                 7: "树林/墙/虚空(步行不可通过, 部分飞行可过)", 8: "悬崖/大障碍(仅部分飞行可过)",
                 9: "绝对障碍(所有移动类型不可过)"}

IMPASSABLE = 0x7FFF


# ---------------------------------------------------------------- 工具函数

def text(raw):
    """Big5 定长字符串 -> str. 原版用了倚天扩展字, 所以用 cp950 并以 hkscs 兜底."""
    raw = raw.split(b"\0")[0]
    try:
        s = raw.decode("cp950")
    except UnicodeDecodeError:
        s = raw.decode("big5hkscs", "replace")
    return to_simplified(s.replace("　", " ").strip())


def shorts(b, off, n):
    return list(struct.unpack_from("<%dh" % n, b, off))


def find(root, pattern):
    """大小写不敏感地找文件 (原版目录名/扩展名大小写混用)."""
    hits = [p for p in glob.glob(os.path.join(root, "**", "*"), recursive=True)
            if os.path.basename(p).lower() == pattern.lower()]
    return hits[0] if hits else None


def opt(v):
    return None if v == -1 else v


# ---------------------------------------------------------------- 各文件解析

def parse_items(path, skill_names):
    b = open(path, "rb").read()
    out = []
    for i in range(len(b) // 182):
        r = b[i * 182:(i + 1) * 182]
        v = shorts(r, 0, 56)
        equip = [u for u in v[1:17] if u != -1]
        use_target = v[41] - 1 if v[41] > 0 else v[41]   # 同 Sword: 文件里 1=我方 2=敌方 3=召唤
        it = {
            "id": i,
            "name": text(r[112:122]),
            "desc": text(r[122:182]),
            "type": v[0], "type_name": ITEM_TYPE.get(v[0]),
            "equip_units": equip,
            "equip_names": [PARTY[u] if 0 <= u < 10 else u for u in equip],
            "attack_range": {"type": v[17], "type_name": RANGE_TYPE.get(v[17]), "area": v[18],
                             "min": v[19], "max": v[20]},
            "hit": v[21], "miss": v[22], "critical": v[23], "double": v[24],
            "attack_add": {"type": v[25], "name": ATTACK_ADD.get(v[25]), "ratio": v[26],
                           "time": v[28], "turns": (v[28] // 100) if v[28] >= 100 else (1 if v[25] >= 0 else 0),
                           "cost": v[29]},
            "attack_attribute": v[27], "attack_attribute_name": ATTR.get(v[27]),
            "unknown30": v[30],
            "attack": v[31], "defence": v[32], "unknown33": v[33],
            "attribute_defence": dict(zip(ATTR6, v[34:40])),
            "use": {
                "mp_cost": v[40], "target_raw": v[41], "target": use_target,
                "target_name": TARGET.get(use_target),
                "range_type": v[42], "range_area": v[43], "range_min": v[44], "range_max": v[45],
                "unknown46": v[46], "base_power": v[47], "time_cost": v[48],
                "consumable": bool(v[49]),
                "use_type": v[51], "use_type_name": ITEM_USE.get(v[51]),
                "effect": v[52], "effect_name": ITEM_EFFECT.get(v[52]),
                "skill_id": opt(v[53]),
                "skill_name": skill_names.get(v[53]) if v[53] >= 0 else None,
            },
            "price": v[50],
            "synthesis": [v[54], v[55]] if v[54] != -1 else None,
        }
        out.append(it)
    names = {it["id"]: it["name"] for it in out}
    for it in out:
        if it["synthesis"]:
            it["synthesis_names"] = [names.get(x) for x in it["synthesis"]]
    return out


def parse_skills(path):
    b = open(path, "rb").read()
    out = []
    for i in range(len(b) // 144):
        r = b[i * 144:(i + 1) * 144]
        v = shorts(r, 0, 37)
        spirit = []
        for k in range(5):
            t, req, plus = v[16 + k * 3:19 + k * 3]
            spirit.append({"spirit": SPIRIT[k], "type": t, "type_name": SKILL_ADD_TYPE.get(t),
                           "request": req, "plus": plus})
        battle_type = v[33]
        other = v[15]
        # 同 Sword 的分类: 战斗画面型 或 附带"伤害倍数/附加状态"的为物理绝技, 其余为咒术
        physical = battle_type == 0 or other in (0, 1, 2, 3, 4, 6, 8)
        out.append({
            "id": i,
            "name": text(r[74:84]),
            "desc": text(r[84:144]),
            "kind": "绝技(物理)" if physical else "咒术",
            "move_attack_type": v[0], "can_use_after_move": v[0] == 1,
            "target": v[1], "target_name": TARGET.get(v[1]),
            "range": {"type": v[2], "type_name": RANGE_TYPE.get(v[2]), "area": v[3],
                      "min": v[4], "max": v[5]},
            "rate6": v[6],      # Sword 称 HitAdd: 咒术=命中率(推测), 物理绝技=附加状态几率
            "mp_cost": v[7],
            "move_cost": v[8],
            "power": v[9],      # Sword 称 BasePower: 伤害/恢复量; 状态类为持续(x100回合); 召唤类为单位ID
            "rate10": v[10],    # Sword 称 Hit
            "attribute": v[11], "attribute_name": ATTR.get(v[11]),
            "result_type": v[12], "result_type_name": SKILL_RESULT.get(v[12]),
            "result_effect": v[13], "result_effect_name": SKILL_EFFECT.get(v[13]),
            "other_type": v[14], "other_type_name": SKILL_OTHER_TYPE.get(v[14]),
            "other_effect": other, "other_effect_name": SKILL_OTHER.get(other),
            "spirit_addition": spirit,
            "animation_id": v[31], "has_movie": bool(v[32]),
            "battle_type": battle_type, "battle_type_name": BATTLE_TYPE.get(battle_type),
            "battle_ranged": v[34], "battle_sprite": v[35], "unknown36": v[36],
        })
    return out


def parse_units(path):
    b = open(path, "rb").read()
    out = []
    for i in range(len(b) // 58):
        r = b[i * 58:(i + 1) * 58]
        v = shorts(r, 0, 24)
        u16 = lambda k: v[k] & 0xFFFF
        out.append({
            "id": i,
            "name": text(r[48:58]),
            "attribute_defence_id": v[0],
            "move_type": v[1], "move_type_name": MOVE_TYPE.get(v[1]),
            "camp": v[2], "camp_name": CAMP.get(v[2]),
            "hp": u16(3), "hp_grow": u16(4), "mp": u16(5), "mp_grow": u16(6),
            "move": v[7],
            "str": v[8], "str_grow": v[9],
            "int": v[10], "int_grow": v[11],
            "avg": v[12], "avg_grow": v[13],
            "vit": v[14], "vit_grow": v[15],
            "luk": v[16], "luk_grow": v[17],
            "sprite": v[18], "unknown19": v[19],
            "defence_type": v[20],
            "attack_type": v[21], "attack_type_name": {0: "近战", 1: "远程"}.get(v[21]),
            "base_lv": v[22], "base_exp": v[23],
        })
    return out


def parse_levelup(path, skill_names):
    b = open(path, "rb").read()
    recs = []
    for i in range(10):
        v = shorts(b, i * 26, 13)
        recs.append({
            "unit_id": v[0], "name": PARTY[v[0]],
            "hp_rand": v[1], "mp_rand": v[2],
            "str": {"base": v[3], "rand": v[4]}, "int": {"base": v[5], "rand": v[6]},
            "avg": {"base": v[7], "rand": v[8]}, "vit": {"base": v[9], "rand": v[10]},
            "luk": {"base": v[11], "rand": v[12]},
            "skills": [],
        })
    off = 260
    for i in range(10):
        for j in range(10):
            v = shorts(b, off + (i * 10 + j) * 14, 7)
            if v[6] == -1:
                continue
            recs[i]["skills"].append({
                "lv": v[0], "spirit_request": dict(zip(SPIRIT, v[1:6])),
                "skill_id": v[6], "skill_name": skill_names.get(v[6])})
    tail = b[off + 1400:]
    return {"units": recs, "trailing_bytes_hex": tail.hex()}


def parse_init(path, item_names, skill_names):
    b = open(path, "rb").read()
    out = []
    for i in range(len(b) // 80):
        v = shorts(b, i * 80, 40)
        items = [x for x in v[20:30] if x != -1]
        skills = [x for x in v[30:40] if x != -1]
        out.append({
            "unit_id": v[0], "name": PARTY[v[0]], "lv": v[1], "exp": v[2],
            "hp": v[3] & 0xFFFF, "mp": v[4] & 0xFFFF,
            "str": v[5], "int": v[6], "avg": v[7], "vit": v[8], "luk": v[9],
            "spirit": dict(zip(SPIRIT, v[10:15])),
            "weapon": opt(v[15]), "armor": opt(v[16]), "accessory": opt(v[17]),
            "in_team": v[18], "spirit_points": v[19],
            "items": items, "item_names": [item_names.get(x) for x in items],
            "skills": skills, "skill_names": [skill_names.get(x) for x in skills],
        })
    return out


def parse_attr_def(path):
    b = open(path, "rb").read()
    out = []
    for i in range(len(b) // 14):
        v = shorts(b, i * 14, 7)
        out.append({"index": i, "values": dict(zip(ATTR6, v[:6])), "id_field": v[6]})
    return out


def parse_terrain(path):
    b = open(path, "rb").read()
    out = []
    for i in range(len(b) // 32):
        v = shorts(b, i * 32, 16)
        costs = {}
        for t in range(10):
            costs[t] = None if (v[t] & 0xFFFF) == IMPASSABLE else v[t]
        out.append({"move_type": v[15], "move_type_name": MOVE_TYPE.get(v[15]),
                    "cost": costs, "unknown10_14": v[10:15]})
    return {"terrain_classes": TERRAIN_GUESS, "move_types": out,
            "note": "cost[t] = 进入地形类别 t 的一格所耗行动力, null=不可通过; 地形类别取自 mapNN.dtl 每格的 Move 字节"}


def parse_msg(path):
    """*.MSG: int32 段数, int32 头长, 每段 (pos,count,unk,len); 段内 4 字节 + count 个绝对偏移.
    字符串以 00 01 表示换行, 00 02 表示一段结束; 段与段之间一串 0 是占位符, 输出为 {0}."""
    b = open(path, "rb").read()
    c, _ = struct.unpack_from("<ii", b, 0)
    secs = []
    for s in range(c):
        pos, count, unk, ln = struct.unpack_from("<iiii", b, 8 + s * 16)
        offs = list(struct.unpack_from("<%di" % count, b, pos + 4))
        ends = offs[1:] + [pos + ln]
        strs = []
        for o, e in zip(offs, ends):
            raw = b[o:e]
            parts, cur = [], b""
            k = 0
            while k < len(raw):
                if raw[k] == 0:
                    j = k
                    while j < len(raw) and raw[j] == 0:
                        j += 1
                    if j < len(raw) and raw[j] == 1:
                        parts.append(cur.decode("cp950", "replace") + "\n"); cur = b""; k = j + 1; continue
                    if j < len(raw) and raw[j] == 2:
                        parts.append(cur.decode("cp950", "replace")); cur = b""; k = j + 1; continue
                    if j < len(raw):          # 一串 0 后接正文: 数字占位符 (金额/经验值/物品名)
                        parts.append(cur.decode("cp950", "replace") + "{0}"); cur = b""
                    k = j
                    continue
                cur += raw[k:k + 1]
                k += 1
            if cur:
                parts.append(cur.decode("cp950", "replace"))
            strs.append(to_simplified("".join(parts)))
        secs.append(strs)
    return secs


def parse_stage_start(path):
    b = open(path, "rb").read()
    return [{"stage": i, "music": struct.unpack_from("<h", b, i * 26)[0],
             "name": text(b[i * 26 + 2:i * 26 + 26])} for i in range(len(b) // 26)]


def parse_stage(dir_, stage, item_names, skill_names, units):
    res = {"stage": stage}
    sdes = find(dir_, "SDES_%02d.DAT" % stage)
    if sdes:
        b = open(sdes, "rb").read()
        res["title"] = text(b[0:24])
        res["win"] = text(b[0x18:0x18 + 52])
        res["lose"] = text(b[0x4C:0x4C + 52])
    dtl = find(dir_, "map%02d.dtl" % stage)
    if dtl:
        b = open(dtl, "rb").read()
        w, h = struct.unpack_from("<hh", b, 7)
        if 29 + w * h * 4 <= len(b):
            cnt = {}
            for k in range(w * h):
                t = b[29 + k * 4]
                cnt[t] = cnt.get(t, 0) + 1
            res["map"] = {"width": w, "height": h, "terrain_count": dict(sorted(cnt.items()))}
    man = find(dir_, "MAN_%02d.DAT" % stage)
    if man:
        b = open(man, "rb").read()
        n = struct.unpack_from("<h", b, 0)[0]
        lst = []
        for i in range(n):
            v = shorts(b, 2 + i * 116, 58)
            uid = v[0]
            items = [x for x in v[19:29] if x != -1]
            skills = [x for x in v[29:39] if x != -1]
            lst.append({
                "index": i, "unit_id": uid,
                "name": units[uid]["name"] if 0 <= uid < len(units) else None,
                "lv": v[1], "hp_add": v[2], "hp_sub": v[3], "mp_add": v[4], "mp_sub": v[5],
                "str": v[6], "int": v[7], "avg": v[8], "vit": v[9], "luk": v[10],
                "spirit": dict(zip(SPIRIT, v[11:16])),
                "weapon": opt(v[16]), "armor": opt(v[17]), "accessory": opt(v[18]),
                "items": items, "item_names": [item_names.get(x) for x in items],
                "skills": skills, "skill_names": [skill_names.get(x) for x in skills],
                "event_parm": [v[39], v[40]], "kill_get_type": v[41], "kill_get_name": {0: "金钱", 1: "物品"}.get(v[41]), "kill_get_parm": v[42],
                "kill_event": v[43], "unknown44": v[44],
                "ai": v[45], "ai_name": AI.get(v[45], "AI%d" % v[45]), "ai_target": [v[46], v[47]],
                "unknown48_57": v[48:58],
            })
        res["units"] = lst
    return res


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=_boot.REPO)
    a = ap.parse_args()
    misc = os.path.join(original_dir(), "Misc")
    out_dir = os.path.join(a.root, "data")
    os.makedirs(out_dir, exist_ok=True)

    def dump(name, obj):
        with open(os.path.join(out_dir, name), "w", encoding="utf-8", newline="\n") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
        print("wrote", name)

    skills = parse_skills(find(misc, "Mag_dat.DAT"))
    skill_names = {s["id"]: s["name"] for s in skills}
    items = parse_items(find(misc, "Item_dat.dat"), skill_names)
    item_names = {it["id"]: it["name"] for it in items}
    units = parse_units(find(misc, "Man_base.dat"))

    dump("skills.json", skills)
    dump("items.json", items)
    dump("units.json", units)
    dump("levelup.json", parse_levelup(find(misc, "KMAN_LEV.DAT"), skill_names))
    dump("party_init.json", parse_init(find(misc, "KMAN_STA.DAT"), item_names, skill_names))
    dump("attribute_defense.json", parse_attr_def(find(misc, "MAG_OPP.DAT")))
    dump("terrain.json", parse_terrain(find(misc, "TER_EFF.DAT")))
    dump("messages.json", {n: parse_msg(find(misc, n))
                           for n in ["CSSCON.MSG", "GITEPRO.MSG", "MLEVPRO.MSG", "Respro.msg", "TREPRO.MSG"]})
    starts = parse_stage_start(find(misc, "STA_SCR.DAT"))
    stage_root = os.path.join(original_dir(), "Stage")
    stages = []
    for st in starts:
        d = [p for p in glob.glob(os.path.join(stage_root, "*"))
             if os.path.basename(p).lower() == "stage%02d" % st["stage"]]
        s = dict(st)
        if d:
            s.update(parse_stage(d[0], st["stage"], item_names, skill_names, units))
        stages.append(s)
    dump("stages.json", stages)


if __name__ == "__main__":
    main()
