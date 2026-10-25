#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""导入工具: 原图仓库 (原版二进制) + data/ (parse_data.py / export_text.py 的输出) -> 内容包 game/content/tdj/。

格式定义见 docs/内容格式.md。引擎运行时只读内容包, 不再读原版二进制 (DAT/COD/DTL/MSG)。
贴图、动画、音频不复制, 内容里只写资源相对路径 (原图仓库里的真实大小写路径; 高清版在 hd4x/ 同路径)。

二进制解析与现有运行时逐字段一致 (game/engine/battle/battle_stage.gd、rpg/rpg_stage.gd、camp_scene.gd),
由 tools/checks/check_content.py 逐项比对验证。data/ 变了 (如文本转简体) 要重新运行本工具。

用法: python3 tools/assets/import_content.py [--out game/content/tdj]
"""
import argparse
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tools/
import _boot  # noqa: E402,F401
from paths import REPO, original_dir  # noqa: E402

FORMAT = "tdj-content/1"
STAGE_COUNT = 36
TOWN_COUNT = 27

# 部分城镇共用别处的地图 (同 rpg_stage.gd MAP_FIX, 来自重制版 GameRPGData.loadLayer 的修正)
TOWN_MAP_FIX = {1: "map00", 3: "map00", 4: "map02", 7: "map05", 9: "map05", 8: "map06", 10: "map06", 13: "map11",
                15: "map11", 14: "map12", 16: "map12", 19: "map17", 21: "map17", 23: "map17", 20: "map18", 22: "map18",
                24: "map18", 25: "map18"}

# data/messages.json 的原文件名 -> 内容包里的表名
SYSTEM_TEXT = {"CSSCON.MSG": "system_confirm", "GITEPRO.MSG": "give_item", "MLEVPRO.MSG": "exp_gain",
               "Respro.msg": "battle_result", "TREPRO.MSG": "treasure"}

# 写在 exe 里的系统文本 (不在 .MSG 里), 简体: 0x56 通关序号框两个 MessageBox 的文字 (0x45e868 / 0x45e7d4, Big5), {0}~{4} = %X 各项
EXE_TEXT = {"clear_rank": [[
    "恭喜您！您已通过了「天地劫」中最\n艰难的考验，请立刻将下面序号抄下\n，连同回函卡上的截角印花，和五百\n字的过关心得，一起寄到本公司参加\n赠奖活动，前五十名将获赠绝对限量\n的「天地劫」特殊赠品！",
    "为了本活动的公正性，若发现有两封\n，应募来函中的序号相同，这两封应\n募来函都将失去资格，因此请不要把\n您辛苦得到的序号告诉别人！\n序号：\n{0}-{1}-{2}-{3}-{4}"]]}

# 按 id 合并的数据表: 表名 -> (内容包内路径, 合并键)
TABLES = {
    "units": ("data/units.json", "id"),
    "items": ("data/items.json", "id"),
    "skills": ("data/skills.json", "id"),
    "levelup": ("data/levelup.json", "unit_id"),
    "party_init": ("data/party_init.json", "unit_id"),
    "attribute_defense": ("data/attribute_defense.json", "index"),
    "terrain": ("data/terrain.json", "move_type"),
    "shops": ("data/shops.json", "id"),
    "camps": ("camps/camps.json", "stage"),
}


# stages/NN/、towns/NN/ 下由本工具生成的文件 (重新导入时只删这些)
GENERATED = {"stage.json", "town.json", "map.json", "layers.json", "units.json", "events_raw.json", "text.json"}
# 完全由本工具生成的目录: 重建时删掉本次没再生成的旧文件 (表改名等), 其余文件一律保留。
GENERATED_DIRS = ("data", "text", "camps")
# 手写数据 (不由本工具生成, 重建时绝不能删或覆盖): 布局表、演出表等, 见 docs/界面布局.md §3。
HANDWRITTEN = ("ui_theme/layout.json", "fx/cast.json")


# ---------------------------------------------------------------- 原图仓库访问 (不区分大小写, 同 Assets.resolve)

class Original:
    def __init__(self, root):
        self.root = root
        self.files = json.load(open(os.path.join(root, "index.json"), encoding="utf-8"))
        self.low = {p.lower(): p for p in self.files}

    def resolve(self, rel):
        return self.low.get(rel.lower(), "")

    def exists(self, rel):
        return rel.lower() in self.low

    def bytes(self, rel):
        r = self.resolve(rel)
        assert r, "原图仓库缺文件: " + rel
        return open(os.path.join(self.root, r), "rb").read()

    def list_files(self, dir_rel):
        pre = dir_rel.lower().rstrip("/") + "/"
        return [self.low[k] for k in self.low if k.startswith(pre)]

    def anim_dir(self, rel):
        """动画目录的真实路径 (含 anim.json), 没有则返回 None"""
        r = self.resolve(rel + "/anim.json")
        return os.path.dirname(r) if r else None


# ---------------------------------------------------------------- 二进制小工具 (越界读为 0, 同 Godot decode_*)

def s16(b, o):
    return struct.unpack_from("<h", b, o)[0] if 0 <= o and o + 2 <= len(b) else 0


def s32(b, o):
    return struct.unpack_from("<i", b, o)[0] if 0 <= o and o + 4 <= len(b) else 0


def cstr(b, o, n):
    s = b[o:o + n]
    z = s.find(b"\0")
    return (s if z < 0 else s[:z]).decode("ascii", "replace")


def basename_noext(name):
    return name.rsplit(".", 1)[0] if "." in name else name


# ---------------------------------------------------------------- 共用: 事件脚本 / 图层物件 / 地图格

def parse_events(b):
    """EVENT_NN.COD -> [[{op, data(hex)}]] (同 BattleStage.parse_events)"""
    out = []
    count = s32(b, 0)
    for i in range(count):
        h = 8 + 16 * i
        pos1, cnt = s32(b, h), s32(b, h + 4)
        rest = s32(b, h + 12) - cnt * 4
        cmds = []
        for j in range(cnt):
            o = s32(b, pos1 + 4 * j)
            size = rest if j == cnt - 1 else s32(b, pos1 + 4 * (j + 1)) - o
            rest -= 0 if j == cnt - 1 else size
            cmds.append({"op": s32(b, o), "data": b[o + 4:o + size].hex()})
        out.append(cmds)
    return out


def parse_layer_objects(b, base_dir, orig, warn):
    """LAYER_NN.DAT -> (L0 背景列表, L1 物件列表), 布局同 battle_stage.gd _load_layer"""
    c0, c1 = s16(b, 0), s16(b, 2)
    p = 64
    backgrounds, objects = [], []
    for _ in range(c0 - 1):
        name = cstr(b, p + 34, 13)
        bg = {"layer": s16(b, p), "z": s32(b, p + 2), "view": [s16(b, p + 16), s16(b, p + 18)],
              "draw_layer": s16(b, p + 20), "file": name}
        if name.lower().endswith(".saf"):
            bg["anim"] = orig.anim_dir("%s/%s" % (base_dir, basename_noext(name))) or warn("缺动画 %s/%s" % (base_dir, name))
        else:
            bg["image"] = orig.resolve("%s/%s.png" % (base_dir, basename_noext(name))) or warn("缺贴图 %s/%s" % (base_dir, name))
        backgrounds.append(bg)
        p += 60
    for i in range(c1):
        if p + 31 > len(b):
            warn("%s LAYER 物件 %d 越出文件末尾 (声明 %d 个, 实有 %d 个), 丢弃" % (base_dir, i, c1, i))
            break
        name = cstr(b, p + 18, 13)
        objects.append({
            "layer": s16(b, p), "tag": s16(b, p + 2), "x": s16(b, p + 4), "y": s16(b, p + 6),
            "flag_var": s16(b, p + 8), "play_mode": s16(b, p + 12), "delay": s16(b, p + 14),
            "hidden": s16(b, p + 16), "file": name,
            "anim": orig.anim_dir("%s/%s" % (base_dir, basename_noext(name))),
        })
        p += 31
    return backgrounds, objects


def parse_dtl(b):
    """mapNN.dtl -> (w, h, [byte0 行], [byte1 行], [s16 行])"""
    w, h = s16(b, 7), s16(b, 9)
    g0, g1, g2 = [], [], []
    for y in range(h):
        r0, r1, r2 = [], [], []
        for x in range(w):
            o = 29 + 4 * (y * w + x)
            r0.append(b[o])
            r1.append(b[o + 1])
            r2.append(s16(b, o + 2))
        g0.append(r0)
        g1.append(r1)
        g2.append(r2)
    return w, h, g0, g1, g2


# ---------------------------------------------------------------- 数据表

def label_keys(obj, extra=()):
    """把派生的显示名字段 (xxx_name / xxx_names, 以及 extra 里的键) 改为 "_" 前缀注释字段"""
    if isinstance(obj, list):
        return [label_keys(v, extra) for v in obj]
    if not isinstance(obj, dict):
        return obj
    out = {}
    for k, v in obj.items():
        derived = k.endswith("_name") or k.endswith("_names") or k in extra
        out[("_" + k) if derived else k] = label_keys(v, extra)
    return out


def build_tables(data):
    """data/*.json -> 内容包 data/*.json + enums"""
    out = {
        "units": label_keys(data["units"]),
        "items": label_keys(data["items"]),
        "skills": label_keys(data["skills"]),
        "levelup": label_keys(data["levelup"]["units"], ("name",)),
        "party_init": label_keys(data["party_init"], ("name",)),
        "attribute_defense": data["attribute_defense"],
        "terrain": label_keys(data["terrain"]["move_types"]),
    }
    for it in out["items"]:  # attack_add.name 是派生名 (同 ATTACK_ADD)
        it["attack_add"] = {("_name" if k == "name" else k): v for k, v in it["attack_add"].items()}
    misc = {"levelup_trailing_bytes_hex": data["levelup"]["trailing_bytes_hex"]}
    return out, misc


def build_enums(data):
    sys.path.insert(0, os.path.join(REPO, "tools"))
    import parse_data as pd
    t = lambda d: {str(k): v for k, v in d.items() if k != -1}  # noqa: E731
    return {
        "_comment": "数据表里各编号字段的显示名 (来自 tools/assets/parse_data.py)。引擎显示用这些名字, 不写死在代码里。",
        "item_type": t(pd.ITEM_TYPE), "attribute": t(pd.ATTR), "attribute6": pd.ATTR6, "spirit": pd.SPIRIT,
        "range_type": t(pd.RANGE_TYPE), "target": t(pd.TARGET), "attack_add": t(pd.ATTACK_ADD),
        "item_use": t(pd.ITEM_USE), "item_effect": t(pd.ITEM_EFFECT), "skill_result": t(pd.SKILL_RESULT),
        "skill_effect": t(pd.SKILL_EFFECT), "skill_other_type": t(pd.SKILL_OTHER_TYPE),
        "skill_other": t(pd.SKILL_OTHER), "skill_add_type": t(pd.SKILL_ADD_TYPE),
        "battle_type": {str(k): v for k, v in pd.BATTLE_TYPE.items()}, "move_type": t(pd.MOVE_TYPE),
        "camp": t(pd.CAMP), "ai": t(pd.AI), "kill_get": {"0": "金钱", "1": "物品"},
        "shop_type": {"0": "武器店", "1": "杂物店", "2": "药店"},  # 原版名称表 0x4688a8 (商店物品窗左栏标签)
        "attack_type": {"0": "近战", "1": "远程"},
        "terrain_class": data["terrain"]["terrain_classes"],
        "party": pd.PARTY,
    }


# ---------------------------------------------------------------- 关卡

def build_stage(n, orig, data, warn):
    d = os.path.dirname(orig.resolve("Stage/Stage%02d/EVENT_%02d.COD" % (n, n)))
    B = lambda f: orig.bytes("%s/%s" % (d, f))  # noqa: E731
    info = data["stages"][n]
    files = {}

    # 单位配置 (MAN, 经 data/stages.json) + 出场坐标 (XY_NN.COD: 第 i 条给第 i 个单位)
    xb = B("XY_%02d.COD" % n)
    xy = [(s16(xb, 9 + 6 * i), s16(xb, 11 + 6 * i), s16(xb, 13 + 6 * i)) for i in range(s16(xb, 7))]
    if len(xy) > len(info["units"]):
        warn("第 %d 关 XY 比 MAN 多 %d 条, 多出的丢弃" % (n, len(xy) - len(info["units"])))
    units = []
    for i, m in enumerate(info["units"]):
        u = {}
        for k, v in m.items():
            if k == "name":
                u["_name"] = v
            elif k.endswith("_name") or k.endswith("_names"):
                continue  # 派生名, 引擎按 id 查表
            else:
                u[k] = v
            if k == "unit_id" and i < len(xy):
                uid, x, y = xy[i]
                u["x"], u["y"] = x, y
                if uid != m["unit_id"]:
                    u["xy_unit_id"] = uid
        units.append(u)
    files["units.json"] = units

    # 地图格
    w, h, g0, g1, g2 = parse_dtl(B("map%02d.dtl" % n))
    files["map.json"] = {"width": w, "height": h, "terrain": g0, "floor": g1, "event": g2}

    # 图层
    bgs, objs = parse_layer_objects(B("LAYER_%02d.DAT" % n), d, orig, warn)
    files["layers.json"] = {"backgrounds": bgs, "objects": objs}

    # 回合事件
    tb = B("TEVT_%02d.DAT" % n)
    tevt = [{"turn": s16(tb, 6 * i), "timing": s16(tb, 6 * i + 2), "event": s16(tb, 6 * i + 4)}
            for i in range(len(tb) // 6)]

    # 地图事件
    mb = B("MEVT_%02d.DAT" % n)
    mevt = []
    for i in range(len(mb) // 14):
        v = struct.unpack_from("<7h", mb, 14 * i)
        mevt.append({"index": i, "type": v[0], "trigger": v[1], "event": v[2], "item_type": v[3],
                     "item": v[4], "prompt": v[5], "show": v[6]})

    # 胜负条件
    jb = B("JUDGE_%02d.COD" % n)
    judge = {"win": [], "lose": []}
    for side, ptr, cnt in (("win", s32(jb, 8), s32(jb, 0x0C)), ("lose", s32(jb, 0x18), s32(jb, 0x1C))):
        for i in range(cnt):
            p = s32(jb, ptr + 4 * i)
            t = s32(jb, p)
            if t != 0:
                judge[side].append({"type": t, "unit": s16(jb, p + 4), "event": s16(jb, p + 6)})

    # 剧情脚本与对白
    files["events_raw.json"] = parse_events(B("EVENT_%02d.COD" % n))
    emsg = data["emsg_stage"][os.path.basename(d)]
    files["text.json"] = {"_source": emsg["source"], "groups": emsg["groups"]}

    # 资源
    anims = {}
    for p in orig.list_files(d):
        parts = p.split("/")
        if len(parts) == 4 and parts[3] == "anim.json" and parts[2].lower().startswith("eanm_"):
            anims[str(int(parts[2][5:]))] = os.path.dirname(p)
    anims = dict(sorted(anims.items(), key=lambda kv: int(kv[0])))
    assets = {"dir": d,
              "title_card": orig.anim_dir("%s/Tanm_%02d" % (d, n)) or warn("第 %d 关缺 Tanm" % n),
              "battle_floor": orig.anim_dir("%s/Floor_%02d" % (d, n)) or warn("第 %d 关缺 Floor" % n),
              "event_anims": anims}

    stage = {
        "id": n,
        "name": info["name"],
        "music": info["music"],
        "briefing": {"title": info.get("title", ""), "win": info.get("win", ""), "lose": info.get("lose", "")},
        "assets": assets,
        "turn_events": tevt,
        "map_events": mevt,
        "judge": judge,
        "script": {"source": "scripts/stage_%02d.evs" % n, "raw": "stages/%02d/events_raw.json" % n},
        "text": "stages/%02d/text.json" % n,
    }
    files["stage.json"] = stage
    return files


# ---------------------------------------------------------------- 城镇

def build_town(n, orig, data, warn, shops):
    d = os.path.dirname(orig.resolve("Rpg/Rpg%02d/EVENT_%02d.COD" % (n, n)))
    B = lambda f: orig.bytes("%s/%s" % (d, f))  # noqa: E731
    files = {}
    lb = B("LAYER_%02d.DAT" % n)
    map_file = cstr(lb, 64 + 34, 13)
    map_name = TOWN_MAP_FIX.get(n, basename_noext(map_file))
    map_image = ""
    for p in orig.files:  # 同 rpg_stage.gd: 在 Rpg/ 下按文件名找 (图在使用它的那个 RpgNN 目录里)
        if p.lower().startswith("rpg/") and os.path.basename(p).lower() == map_name.lower() + ".png":
            map_image = p
            break
    if not map_image:
        warn("城镇 %d 缺地图 %s" % (n, map_name))
    _, objs = parse_layer_objects(lb, d, orig, warn)

    # 入口与商店 (RPG_NN.DAT)
    b = B("RPG_%02d.DAT" % n)
    o = 0
    entries = []
    for _ in range(2):
        if o + 12 > len(b):
            break
        v = struct.unpack_from("<6h", b, o)
        entries.append({"music": v[0], "map_x": v[1], "map_y": v[2], "x": v[3], "y": v[4], "dir": v[5]})
        o += 12
    shop_ids = []
    while o + 4 <= len(b):
        rec = {"id": "town%02d.%d" % (n, len(shop_ids)), "type": s16(b, o), "keeper": s16(b, o + 2), "items": []}
        o += 4
        for _ in range(24):  # 重制版 MAX_RPG_SHOP_SLOT
            if o + 2 > len(b):
                break
            it = s16(b, o)
            o += 2
            if it >= 0:
                rec["items"].append(it)
        rec["keeper_anim"] = orig.anim_dir("Shop/Shop%02d" % rec["keeper"]) or warn("缺店主动画 Shop%02d" % rec["keeper"])
        rec["show"] = shop_show(orig, rec["keeper_anim"])
        rec["_item_names"] = [data["items"][i]["name"] if 0 <= i < len(data["items"]) else None for i in rec["items"]]
        shops.append(rec)
        shop_ids.append(rec["id"])

    # 地图格
    dtl = "%s/map%02d.dtl" % (d, n)
    if orig.exists(dtl):
        dtl_rel = orig.resolve(dtl)
    else:
        dtl_rel = [f for f in orig.list_files(d) if f.lower().endswith(".dtl")][0]
    w, h, g0, g1, g2 = parse_dtl(orig.bytes(dtl_rel))
    files["map.json"] = {"_source": dtl_rel, "width": w, "height": h, "block": g0, "talk": g1, "step": g2}
    files["layers.json"] = {"objects": objs}
    files["events_raw.json"] = parse_events(B("EVENT_%02d.COD" % n))
    emsg = data["emsg_rpg"][os.path.basename(d)]
    files["text.json"] = {"_source": emsg["source"], "groups": emsg["groups"]}
    files["town.json"] = {
        "id": n,
        "assets": {"dir": d, "map_file": map_file, "map_image": map_image},
        "entries": entries,
        "shops": shop_ids,
        "script": {"source": "scripts/town_%02d.evs" % n, "raw": "towns/%02d/events_raw.json" % n},
        "text": "towns/%02d/text.json" % n,
    }
    return files


# ---------------------------------------------------------------- 营地

# 原版商店外壳 Cshopro (0x43f7c0 状态机 / 0x43f920 时钟): 渐入 7 档 (表 0x469c88 = 2..14 /16, 每 2 tick 一档),
# 播开场 (动作 0, 第 1 帧起 count[0] 帧), 之后循环待机 (count[0]+2 帧起 count[1] 帧), 关窗后同表倒序渐出。
# 输出给通用场景演出 SceneShow (game/engine/ui/scene_show.gd) 的配置
SHOP_FADE = [2, 4, 6, 8, 10, 12, 14]


def shop_show(orig, anim):
    if anim is None:
        return None
    c = json.load(open(os.path.join(orig.root, anim, "anim.json"), encoding="utf-8"))["action_counts"]
    return {"anim": anim, "base": 0, "intro": [1, c[0]], "loop": [c[0] + 2, c[1]],
            "fade_in": SHOP_FADE, "fade_out": SHOP_FADE[::-1], "fade_tick": 2,
            # 原版实测 (Wine 40 ms 录像): 城镇渐黑 → 黑场 4 tick → 店面渐入; 退店 物品窗渐隐 7 档 x 1 tick → 店面渐黑 → 黑场 6 tick → 城镇渐入
            "via_black": True, "black_hold": [4, 6], "ui_fade_out": SHOP_FADE[::-1], "ui_fade_tick": 1}


def build_camps(orig, warn):
    out = []
    for n in range(STAGE_COUNT):
        rel = "Camp/Script/CAMP%02d.DAT" % n
        if orig.exists(rel):
            b = orig.bytes(rel)
            rec = {"stage": n, "background": s16(b, 0), "town": s16(b, 2), "town_entry": s16(b, 4)}
        else:  # 同 camp_scene.gd 的缺省 [0, 0, 255, 255, 0, 0]
            rec = {"stage": n, "background": 0, "town": -1, "town_entry": 0, "_note": "原版无 %s, 用缺省值" % rel}
        rec["background_anim"] = orig.anim_dir("Camp/Image/camp%02d" % rec["background"])
        if rec["background_anim"] is None:
            rec["_note"] = "原版无 Camp/Image/camp%02d, 营地无背景动画" % rec["background"]
        # 营地背景走通用场景演出 SceneShow: 整段循环, 进出营地的黑场由场景切换 (Game.goto_camp) 负责
        rec["background_show"] = {"anim": rec["background_anim"], "loop": [0, -1]} if rec["background_anim"] else None
        out.append(rec)
    return out


# ---------------------------------------------------------------- 输出

def fmt(o, ind=0):
    """JSON: 标量数组 (地图行、id 列表) 与短对象写一行, 其余缩进, 便于手改与 diff"""
    one = json.dumps(o, ensure_ascii=False, separators=(", ", ": "))
    if not isinstance(o, (dict, list)) or len(one) + ind <= 160 or (
            isinstance(o, list) and all(not isinstance(v, (dict, list)) for v in o)):
        return one
    pad, pad1 = " " * ind, " " * (ind + 1)
    if isinstance(o, dict):
        if not o:
            return "{}"
        body = ",\n".join("%s%s: %s" % (pad1, json.dumps(k, ensure_ascii=False), fmt(v, ind + 1)) for k, v in o.items())
        return "{\n%s\n%s}" % (body, pad)
    body = ",\n".join(pad1 + fmt(v, ind + 1) for v in o)
    return "[\n%s\n%s]" % (body, pad)


WRITTEN = set()  # 本次写出的文件 (相对内容包根, "/" 分隔)


def write(root, rel, obj):
    assert rel not in HANDWRITTEN, "手写数据不能由导入工具覆盖: " + rel
    WRITTEN.add(rel)
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(fmt(obj) + "\n")


def snapshot_handwritten(out):
    """记下手写文件的内容, 导入结束后核对没被删改。"""
    snap = {}
    for rel in HANDWRITTEN:
        p = os.path.join(out, rel)
        if os.path.isfile(p):
            with open(p, "rb") as f:
                snap[rel] = f.read()
    return snap


def prune_stale(out, written):
    """GENERATED_DIRS 里删掉本次没生成的旧文件 (只删 .json, 手写文件除外)。"""
    for sub in GENERATED_DIRS:
        for r, _, fs in os.walk(os.path.join(out, sub)):
            for f in fs:
                rel = os.path.relpath(os.path.join(r, f), out).replace(os.sep, "/")
                if f.endswith(".json") and rel not in written and rel not in HANDWRITTEN:
                    os.remove(os.path.join(r, f))


def check_handwritten(out, snap):
    for rel, data in snap.items():
        p = os.path.join(out, rel)
        if not os.path.isfile(p):
            raise SystemExit("错误: 导入后手写文件丢失: " + rel)
        with open(p, "rb") as f:
            if f.read() != data:
                raise SystemExit("错误: 导入改动了手写文件: " + rel)


def load_data(root=REPO):
    j = lambda rel: json.load(open(os.path.join(root, rel), encoding="utf-8"))  # noqa: E731
    data = {k: j("data/%s.json" % k) for k in
            ["units", "items", "skills", "levelup", "party_init", "attribute_defense", "terrain", "stages", "messages"]}
    data["emsg_stage"] = {f[:-5]: j("data/emsg/Stage/" + f) for f in os.listdir(os.path.join(root, "data/emsg/Stage"))}
    data["emsg_rpg"] = {f[:-5]: j("data/emsg/Rpg/" + f) for f in os.listdir(os.path.join(root, "data/emsg/Rpg"))}
    return data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(REPO, "game/content/tdj"))
    ap.add_argument("--data-root", default=REPO, help="data/ 所在的根目录 (缺省仓库根; make_locale 用它读繁体版 data)")
    a = ap.parse_args()
    orig = Original(original_dir())
    data = load_data(a.data_root)
    warnings = []

    def warn(msg):
        warnings.append(msg)
        return None

    out = a.out
    keep = snapshot_handwritten(out)
    # 只清掉本工具生成的文件; scripts/ (剧情脚本, tools/assets/decompile_events.py 生成)、ui_theme/layout.json 等手写内容保留
    for sub in ("stages", "towns"):
        for r, _, fs in os.walk(os.path.join(out, sub)):
            for f in fs:
                if f in GENERATED:
                    os.remove(os.path.join(r, f))
    WRITTEN.clear()

    tables, misc = build_tables(data)
    for name, recs in tables.items():
        write(out, "data/%s.json" % name, recs)
    write(out, "data/enums.json", build_enums(data))
    write(out, "data/misc.json", misc)
    sys_text = {SYSTEM_TEXT[k]: v for k, v in data["messages"].items()}
    sys_text.update(EXE_TEXT)
    write(out, "text/system.json", sys_text)

    for n in range(STAGE_COUNT):
        for f, obj in build_stage(n, orig, data, warn).items():
            write(out, "stages/%02d/%s" % (n, f), obj)
    shops = []
    for n in range(TOWN_COUNT):
        for f, obj in build_town(n, orig, data, warn, shops).items():
            write(out, "towns/%02d/%s" % (n, f), obj)
    write(out, "data/shops.json", shops)
    write(out, "camps/camps.json", build_camps(orig, warn))

    write(out, "ui_theme/theme.json", {
        "_comment": "界面主题 (待 M3 填写): 字库、面板贴图、坐标。原版主题 = Misc 素材 + Tfont 字库, 坐标 x4。",
        "scale": 4, "font": None, "components": {}})

    write(out, "manifest.json", {
        "format": FORMAT,
        "id": "tdj",
        "name": "天地劫：神魔至尊传 (原版内容)",
        "version": "1.3.0",
        "engine_min": "1.0.0",          # 要求的引擎版本 (game/engine/content/content_compat.gd ENGINE_VERSION)
        "save_compat_min": "1.3.0",     # 还能读的最旧存档版本 (存档记录的该包版本低于它则拒绝读档)
        "base": [],
        "description": "原版 1.3 内容包, 由 tools/assets/import_content.py 从原图仓库与 data/ 生成, 请勿手改 (改动请放到改动包)。",
        "asset_roots": ["original", "hd4x"],
        "stage_count": STAGE_COUNT,
        "town_count": TOWN_COUNT,
        # 播完后结束游戏回标题的过场 (Movie_13 = 第 31 关封寒月封印蚩尤的结局; 原为 event_vm.gd 里的特判)
        "ending_movies": [13],
        "tables": {k: {"file": f, "key": key} for k, (f, key) in TABLES.items()},
        "import_warnings": warnings,
    })
    prune_stale(out, WRITTEN)
    check_handwritten(out, keep)
    nfiles = sum(len(fs) for _, _, fs in os.walk(out))
    size = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(out) for f in fs)
    print("内容包 %s: %d 个文件, %.1f MB" % (out, nfiles, size / 1e6))
    for w in warnings:
        print("  警告:", w)


if __name__ == "__main__":
    main()
