#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""剧情脚本 (.evs, 格式见 docs/剧情脚本格式.md) → 原版事件字节码 EVENT_NN.COD。

  compile_events.py SRC.evs OUT.COD     编译一个脚本
  compile_events.py --check             往返校验: 全部关卡与城镇的原版 COD
                                        反编译再编译后逐字节相同; 并校验
                                        game/content/tdj/scripts/ 下的脚本编译结果与原版一致
  compile_events.py --export-ops        把指令表导出为 game/engine/script/evs_ops.json
                                        (引擎运行时编译 .evs 用, engine/script/evs_compiler.gd)

本文件同时是指令表的唯一定义 (OPS), decompile_events.py 从这里导入。
"""
import json
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tools/
import _boot  # noqa: E402,F401
import paths  # noqa: E402

# ---------------------------------------------------------------------------
# 指令表
# 每条: 原版指令号 -> (命令名, [(参数名, 类型, 默认值)], 说明)
#   类型 h = int16, i = int32, L = int32 跳转目标 (脚本里写标签名)
#   默认值 None 表示必填; 其余参数省略时取默认值 (反编译时等于默认值的参数不写出)
# 批量指令 (0x09/0x0A/0x0B/0x0E/0x10) 的后续记录由 BATCH 描述。
# ---------------------------------------------------------------------------
H, I, L = "h", "i", "L"

BATTLE = {
    0x00: ("return", [], "结束本事件"),
    0x01: ("unit_ref", [("unit", H, None)], "单位记录 (只作为 show/hide/fade_out 的后续记录; 单独出现时原样保留)"),
    0x02: ("end_stage", [("town", H, -1), ("camp", H, -1), ("next", H, -1)], "关卡结束: camp≠-1 进营地 CAMPcamp, 否则 town≠-1 进城镇, 否则直接进第 next 关"),
    0x03: ("game_over", [], "GAME OVER"),
    0x04: ("show_title", [], "关卡标题卡"),
    0x05: ("wait", [("frames", H, None)], "延时 frames 帧"),
    0x06: ("next_frame", [], "让出一帧"),
    0x07: ("camera_set", [("x", H, None), ("y", H, None)], "镜头立即对准格 (x,y)"),
    0x08: ("camera_pan", [("x", H, None), ("y", H, None), ("speed_x", H, None), ("speed_y", H, None)], "镜头平移到格 (x,y), 阻塞"),
    0x09: ("fade_out", [("count", H, None), ("arg", H, -1)], "单位淡出离场 (阻塞); ids= 或 group="),
    0x0A: ("hide", [("count", H, None), ("arg", H, -1)], "单位立即离场; ids= 或 group="),
    0x0B: ("show", [("count", H, None)], "单位立即出场; ids="),
    0x0C: ("face", [("unit", H, None), ("dir", H, None)], "单位转向"),
    0x0D: ("place", [("unit", H, None), ("x", H, None), ("y", H, None), ("dir", H, None)], "单位放到 (x,y) 并设朝向 (不会让单位出场)"),
    0x0E: ("move", [("count", H, None), ("start", H, 0), ("follow", H, 0), ("speed", H, 0)], "一批单位同时走到目标格, 块内为 walk_to"),
    0x0F: ("walk_to", [("unit", H, None), ("x", H, None), ("y", H, None), ("vfirst", H, 0)], "move 块内: 单位走直角折线到 (x,y); vfirst=0 先横后竖, ≠0 先竖后横"),
    0x10: ("move_steps", [("count", H, None), ("start", H, 0), ("follow", H, 0), ("steps", H, None), ("speed", H, 0)], "一批单位同时朝某方向直走 steps 格, 块内为 walk_dir"),
    0x11: ("walk_dir", [("unit", H, None), ("dir", H, None)], "move_steps 块内: 单位朝 dir 直走 (0 北 1 南 2 西 3 东)"),
    0x12: ("screen_fade", [("color", H, None), ("mix_from", H, 0), ("mix_to", H, 0), ("mix_step", H, 0),
                           ("light_from", H, 0), ("light_to", H, 0), ("light_step", H, 0), ("delay", H, 0)],
           "全屏色彩渐变 (闪白等): color 为 RGB555"),
    0x13: ("fade_to_black", [("delay", H, 0)], "画面渐黑"),
    0x14: ("fade_from_black", [("delay", H, 0)], "画面由黑渐亮"),
    0x15: ("screen_clear", [], "撤掉全屏色彩遮罩"),
    0x16: ("say", [("unit", H, -1), ("cursor", H, 0), ("face", H, -1), ("expr", H, 0), ("pos", H, 0), ("msg", H, None)],
           "对白: 光标指向单位 unit (cursor=1 平滑移过去), 头像 face/表情 expr/位置 pos, 本事件对白第 msg 句"),
    0x17: ("show_group", [("group", H, None), ("effect", H, 0)], "出场组号 (MAN event_parm[0]) 为 group 的单位全部出场"),
    0x18: ("anim_load", [("file", H, None), ("slot", H, None)], "把 Eanm_file 载入动画槽 slot"),
    0x19: ("anim_play", [("slot", H, None), ("sound", I, 0), ("from", H, -1), ("to", H, -1)], "播放动画槽 slot 的帧 from~to (阻塞)"),
    0x1A: ("anim_start", [("slot", H, None), ("arg", H, 0)], "动画槽开始播放 (不阻塞)"),
    0x1B: ("anim_show", [("slot", H, None)], "动画槽显示标志开"),
    0x1C: ("anim_hide", [("slot", H, None)], "动画槽显示标志关"),
    0x1D: ("anim_free", [("slot", H, None)], "释放动画槽"),
    0x1E: ("set_var", [("var", H, None), ("value", I, None)], "剧情变量 var = value"),
    0x1F: ("display_on", [], "画面标志 +0x2d 开 (含义待查)"),
    0x20: ("display_off", [], "画面标志 +0x2d 关 (含义待查)"),
    0x21: ("cursor_show", [], "显示光标 (镜头中心)"),
    0x22: ("cursor_hide", [], "隐藏光标"),
    0x23: ("layer_load", [("layer", H, None)], "载入地图图层"),
    0x24: ("layer_unload", [("layer", H, None)], "卸载地图图层"),
    0x25: ("obj_show", [("layer", H, None), ("obj", H, None)], "显示图层物件"),
    0x26: ("obj_hide", [("layer", H, None), ("obj", H, None)], "隐藏图层物件"),
    0x27: ("obj_play3", [("layer", H, None), ("obj", H, None), ("arg", H, 0)], "图层物件播放 (阻塞; 数据未用)"),
    0x28: ("obj_play", [("layer", H, None), ("obj", H, None), ("from", H, -1), ("to", H, -1)], "播放图层物件帧 from~to (阻塞)"),
    0x29: ("movie", [("id", H, None)], "播放过场 Movie_id"),
    0x2A: ("music_load", [("music", H, None), ("ch", H, None)], "音乐 Music_music 载入通道 ch"),
    0x2B: ("music_close", [("ch", H, None)], "关闭音乐通道"),
    0x2C: ("music_play", [("ch", H, None), ("fade", H, 0)], "音乐通道开始播放 (fade=1 淡入)"),
    0x2D: ("music_pause", [("ch", H, None), ("arg", H, 0)], "音乐通道暂停/淡出"),
    0x2E: ("music_resume", [("ch", H, None), ("arg", H, 0)], "音乐通道继续"),
    0x2F: ("set_ai", [("unit", H, None), ("ai", H, None), ("p1", H, 0), ("p2", H, 0), ("p3", H, 0), ("p4", H, 0)], "单位 AI 类型与参数 (+0xba~+0xc2)"),
    0x30: ("goto", [("to", L, None)], "跳转"),
    0x31: ("if_var", [("var", H, None), ("value", I, None), ("goto", L, None)], "var == value 时跳转"),
    0x32: ("if_var", [("var", H, None), ("value", I, None), ("goto", L, None)], "var > value 时跳转"),
    0x33: ("if_var", [("var", H, None), ("value", I, None), ("goto", L, None)], "var >= value 时跳转"),
    0x34: ("if_var", [("var", H, None), ("value", I, None), ("goto", L, None)], "var < value 时跳转"),
    0x35: ("if_var", [("var", H, None), ("value", I, None), ("goto", L, None)], "var <= value 时跳转"),
    0x36: ("clear_status", [], "全体单位清除状态, 召唤物退场 (原版漏 break, 接着执行 0x37)"),
    0x37: ("count_enemies", [("var", H, None)], "var = 在场敌人数 (不含 +0xa8 单位)"),
    0x38: ("count_npcs", [("var", H, None)], "var = 在场友军 NPC 数 (数据未用)"),
    0x39: ("debug_var", [("var", H, None)], "调试输出变量 (数据未用)"),
    0x3A: ("add_var", [("var", H, None), ("value", I, None)], "var += value"),
    0x3B: ("sub_var", [("var", H, None), ("value", I, None)], "var -= value"),
    0x3C: ("get_unit_pos", [("unit", H, None), ("var_x", H, None), ("var_y", H, None)], "var_x, var_y = 单位坐标"),
    0x3D: ("get_camera_cell", [("var_x", H, None), ("var_y", H, None)], "var_x, var_y = 镜头所在格"),
    0x3E: ("camera_pan_var", [("var_x", H, None), ("var_y", H, None), ("speed_x", H, None), ("speed_y", H, None)], "镜头平移到 (var[var_x], var[var_y]), 阻塞"),
    0x3F: ("get_turn", [("var", H, None)], "var = 当前回合数"),
    0x40: ("equip", [("unit", H, None), ("item", H, None)], "单位装备物品"),
    0x41: ("is_hurt", [("unit", H, None), ("var", H, None)], "var = (单位 hp ≠ hpmax)"),
    0x42: ("fade_out_var", [("var", H, None)], "编号为 var[var] 的单位淡出离场 (阻塞)"),
    0x43: ("copy_hero", [("hero", H, None), ("unit", H, None)], "按队伍名册里角色 hero 的数据重设单位 unit"),
    0x44: ("set_npc", [("unit", H, None), ("npc", H, None)], "单位 +0xac = npc (1 AI 控制, 0 玩家控制)"),
    0x45: ("get_weapon", [("unit", H, None), ("var", H, None)], "var = 单位当前武器"),
    0x46: ("damage_party", [], "玩家单位 hp -= hp/3 (最少剩 1)"),
    0x47: ("all_below", [("y", H, None), ("var", H, None)], "var = 所有玩家单位 y >= 此值"),
    0x48: ("all_left_of", [("x", H, None), ("var", H, None)], "var = 所有玩家单位 x <= 此值"),
    0x49: ("equip_var", [("var", H, None), ("unit", H, None)], "单位装备 var[var] 里存的物品"),
    0x4A: ("damage_unit", [("unit", H, None)], "单位 hp -= hp/3, mp -= mp/3"),
    0x4B: ("heal_unit", [("unit", H, None)], "单位 HP/MP 回满"),
    0x4C: ("show_group_var", [("var", H, None), ("effect", H, 0)], "出场组号为 var[var] 的单位出场"),
    0x4D: ("var_odd", [("src", H, None), ("dst", H, None)], "var[dst] = var[src] & 1"),
    0x4E: ("give_item", [("item", H, None)], "物品放进公共行囊"),
    0x4F: ("set_member", [("hero", H, None), ("in_party", H, None)], "队伍名册: 角色 hero 入队(1)/离队(0)"),
    0x50: ("shake_on", [("x", H, None), ("y", H, None)], "屏幕震动开"),
    0x51: ("shake_off", [], "屏幕震动关"),
    0x52: ("has_item", [("item", H, None), ("var", H, None)], "var = 是否持有物品 (数据未用)"),
    0x53: ("take_item", [("item", H, None), ("var", H, None)], "持有则收走物品, var = 1/0"),
    0x54: ("to_title", [], "结束战斗回到标题"),
    0x55: ("op55", [("arg", H, None)], "未知 (画面对象 0x405340; 数据未用)"),
    0x56: ("show_clear_rank", [], "通关序号框 (第 35 关)"),
}

TOWN = {
    0x00: ("return", [], "结束本事件"),
    0x01: ("wait", [("frames", H, None)], "延时 frames 帧"),
    0x02: ("next_frame", [], "让出一帧"),
    0x03: ("camera_set", [("x", H, None), ("y", H, None)], "镜头立即定位 (数据未用)"),
    0x04: ("camera_pan", [("x", H, None), ("y", H, None), ("speed_x", H, None), ("speed_y", H, None)], "镜头平移, 阻塞"),
    0x05: ("screen_fade", [("color", H, None), ("mix_from", H, 0), ("mix_to", H, 0), ("mix_step", H, 0),
                           ("light_from", H, 0), ("light_to", H, 0), ("light_step", H, 0), ("delay", H, 0)],
           "全屏色彩渐变 (数据未用)"),
    0x06: ("fade_to_black", [("delay", H, 0)], "画面渐黑"),
    0x07: ("fade_from_black", [("delay", H, 0)], "画面由黑渐亮"),
    0x08: ("screen_clear", [], "撤掉全屏色彩遮罩 (数据未用)"),
    0x09: ("say", [("u0", H, -1), ("u1", H, -1), ("u2", H, -1), ("face", H, -1), ("expr", H, 0), ("pos", H, 0), ("msg", H, None)],
           "对白: 头像 face/表情 expr/位置 pos, 本事件对白第 msg 句 (u0~u2 引擎不读)"),
    0x0A: ("anim_load", [("file", H, None), ("slot", H, None)], "载入动画 (数据未用)"),
    0x0B: ("anim_play", [("slot", H, None), ("sound", I, 0), ("from", H, -1), ("to", H, -1)], "播放动画 (阻塞; 数据未用)"),
    0x0C: ("anim_start", [("slot", H, None), ("arg", H, 0)], "动画开始播放 (数据未用)"),
    0x0D: ("anim_show", [("slot", H, None)], "动画显示标志开 (数据未用)"),
    0x0E: ("anim_hide", [("slot", H, None)], "动画显示标志关 (数据未用)"),
    0x0F: ("anim_free", [("slot", H, None)], "释放动画 (数据未用)"),
    0x10: ("set_var", [("var", H, None), ("value", I, None)], "剧情变量 var = value"),
    0x11: ("display_on", [], "画面标志 +0x2d 开 (数据未用)"),
    0x12: ("display_off", [], "画面标志 +0x2d 关 (数据未用)"),
    0x13: ("layer_load", [("layer", H, None)], "载入图层 (数据未用)"),
    0x14: ("layer_unload", [("layer", H, None)], "卸载图层 (数据未用)"),
    0x15: ("obj_show", [("layer", H, None), ("obj", H, None)], "显示图层物件"),
    0x16: ("obj_hide", [("layer", H, None), ("obj", H, None)], "隐藏图层物件"),
    0x17: ("obj_play3", [("layer", H, None), ("obj", H, None), ("arg", H, 0)], "图层物件播放 (阻塞; 数据未用)"),
    0x18: ("obj_play", [("layer", H, None), ("obj", H, None), ("from", H, -1), ("to", H, -1)], "播放图层物件帧 from~to (阻塞)"),
    0x19: ("movie", [("id", H, None)], "播放过场 (数据未用)"),
    0x1A: ("music_load", [("music", H, None), ("ch", H, None)], "音乐载入通道"),
    0x1B: ("music_close", [("ch", H, None)], "关闭音乐通道"),
    0x1C: ("music_play", [("ch", H, None), ("fade", H, 0)], "音乐通道开始播放 (fade=1 淡入)"),
    0x1D: ("music_pause", [("ch", H, None), ("arg", H, 0)], "音乐通道暂停/淡出"),
    0x1E: ("music_resume", [("ch", H, None), ("arg", H, 0)], "音乐通道继续"),
    0x1F: ("goto", [("to", L, None)], "跳转 (数据未用)"),
    0x20: ("if_var", [("var", H, None), ("value", I, None), ("goto", L, None)], "var == value 时跳转"),
    0x21: ("if_var", [("var", H, None), ("value", I, None), ("goto", L, None)], "var > value 时跳转"),
    0x22: ("if_var", [("var", H, None), ("value", I, None), ("goto", L, None)], "var >= value 时跳转"),
    0x23: ("if_var", [("var", H, None), ("value", I, None), ("goto", L, None)], "var < value 时跳转"),
    0x24: ("if_var", [("var", H, None), ("value", I, None), ("goto", L, None)], "var <= value 时跳转"),
    0x25: ("debug_var", [("var", H, None)], "调试输出变量 (数据未用)"),
    0x26: ("goto_town", [("town", H, None), ("entry", H, 0)], "切换到城镇 town 的入口 entry (结束事件)"),
    0x27: ("shop", [("id", H, None)], "打开商店 (结束事件)"),
    0x28: ("leave_town", [], "出城进入下一关 (结束事件)"),
    0x29: ("camp", [("id", H, None)], "进入营地 CAMPid (结束事件)"),
    0x2A: ("hero_show", [], "显示主角精灵 (数据未用)"),
    0x2B: ("hero_hide", [], "隐藏主角精灵"),
    0x2C: ("add_var", [("var", H, None), ("value", I, None)], "var += value"),
    0x2D: ("sub_var", [("var", H, None), ("value", I, None)], "var -= value"),
    0x2E: ("choose", [("a0", H, 1), ("a1", H, 0), ("a2", H, 0), ("msg", H, None), ("var", H, None)],
           "是/否 选择框: 对白 msg (问题)、msg+1 (是)、msg+2 (否), 结果 1/0 写入 var"),
    0x2F: ("give_item", [("item", H, None)], "物品放进公共行囊"),
    0x30: ("has_item", [("item", H, None), ("var", H, None)], "var = 是否持有物品 (队员身上或行囊)"),
    0x31: ("get_gold", [("var", H, None)], "var = 金钱"),
    0x32: ("pay", [("gold", H, None)], "金钱 -= gold"),
    0x33: ("set_stage", [("stage", H, None)], "当前关卡号 = stage (出城时进入)"),
}

OPS = {"battle": BATTLE, "town": TOWN}

# 条件跳转: 运算符 <-> 指令号
CMP_NAMES = ["eq", "gt", "ge", "lt", "le"]
CMP_BASE = {"battle": 0x31, "town": 0x20}

# 批量指令: 头指令 -> (记录指令, 块内命令名)
BATCH = {
    "battle": {0x09: 0x01, 0x0A: 0x01, 0x0B: 0x01, 0x0E: 0x0F, 0x10: 0x11},
    "town": {},
}
UNIT_LIST_OPS = (0x09, 0x0A, 0x0B)  # 用 ids= 列出单位
GROUPS = {"player": 0, "npc": 1, "enemy": 2}  # 0x09/0x0A count=-1 时 arg 的取值

EVENT_SLOTS = {"battle": 20, "town": 65}

# 运行时语义标志 (X4: 也只在这里定义)。引擎里的同名常量 (event_vm.gd / rpg_vm.gd 的 YIELD_OPS、rpg_scene.gd 的 SCENE_OPS / WAIT_OPS)
# 保持为 GDScript 常量 (热路径), 由 tests/test_evs_ops_gate.py 校验与这里逐项相同; 同时导出到 evs_ops.json 的 flags。
#   yield = 让出帧的指令 (完成后原版解释器再多 2 帧), 名单来自反汇编分派表
#   scene = 会切换场景的指令 (城镇: 走到这里事件就结束)   wait = 会打开界面等待玩家的指令
OP_FLAGS = {
    "battle": {"yield": [0x04, 0x05, 0x06, 0x08, 0x09, 0x0E, 0x10, 0x12, 0x13, 0x14, 0x16, 0x29, 0x3E, 0x42, 0x54],
               "scene": [], "wait": []},
    "town": {"yield": [0x01, 0x02, 0x04, 0x05, 0x06, 0x07, 0x09, 0x2E],
             "scene": [0x26, 0x28, 0x29, 0x33], "wait": [0x27, 0x2E]},
}

# 引擎 VM 没有登记 handler 的指令 (原版数据里从不使用, 或原版自己是空操作); 其余指令必须在 VM 的 _register_ops 里登记。
# 新增指令时: 要么写 handler 并 register_op, 要么列在这里并写明原因 (闸门测试逐项检查)。
UNIMPLEMENTED = {
    "battle": {0x1B: "数据未用", 0x27: "数据未用", 0x38: "数据未用", 0x39: "调试输出, 数据未用", 0x52: "数据未用", 0x55: "未知, 数据未用"},
    "town": {0x03: "数据未用", 0x05: "数据未用", 0x08: "数据未用", 0x0A: "数据未用", 0x0B: "数据未用", 0x0C: "数据未用",
             0x0D: "数据未用", 0x0E: "数据未用", 0x0F: "数据未用", 0x11: "数据未用", 0x12: "数据未用", 0x13: "数据未用",
             0x14: "数据未用", 0x17: "数据未用", 0x19: "数据未用", 0x1F: "数据未用", 0x25: "调试输出, 数据未用"},
}

# 变量参数: 参数名属于 VAR_PARAMS 的都是「剧情变量号」; VAR_WRITES 列出会**写**变量的命令及其写入的参数 (其余只读)。
# 只用于校验 (lint_vars / tools/checks/content_schema.py --strict 的保留变量检查), 不影响编译。
VAR_PARAMS = ("var", "var_x", "var_y", "src", "dst")
VAR_WRITES = {
    "set_var": ("var",), "add_var": ("var",), "sub_var": ("var",), "count_enemies": ("var",), "count_npcs": ("var",),
    "get_unit_pos": ("var_x", "var_y"), "get_camera_cell": ("var_x", "var_y"), "get_turn": ("var",), "is_hurt": ("var",),
    "get_weapon": ("var",), "all_below": ("var",), "all_left_of": ("var",), "var_odd": ("dst",), "has_item": ("var",),
    "take_item": ("var",), "choose": ("var",), "get_gold": ("var",),
}


def lint_vars(text, path="<script>"):
    """脚本里出现的变量号 -> [(行号, 命令名, 参数名, 变量号, 是否写)]; 供保留变量检查 (值为 0x.. 或十进制; 无法解析的跳过)"""
    sc = parse_script(text, path)
    out = []

    def visit(st):
        _, name, args, children, no = st
        for k, v in args.items():
            if k in VAR_PARAMS:
                try:
                    out.append((no, name, k, int(v, 0), k in VAR_WRITES.get(name, ())))
                except ValueError:
                    pass
        for ch in children or []:
            visit(ch)

    for stmts in sc["events"].values():
        for st in stmts:
            if st[0] == "cmd":
                visit(st)
    return out


def op_size(kind, op):
    return sum(4 if t in (I, L) else 2 for _, t, _ in OPS[kind][op][1])


def name_to_ops(kind):
    """命令名 -> [指令号] (if_var 对应 5 个)"""
    m = {}
    for op, (name, _, _) in OPS[kind].items():
        m.setdefault(name, []).append(op)
    return m


def pack_params(kind, op, values):
    """values: 与参数表等长的整数列表"""
    out = b""
    for (pname, t, _), v in zip(OPS[kind][op][1], values):
        out += struct.pack("<i" if t in (I, L) else "<h", v)
    return out


# ---------------------------------------------------------------------------
# COD 读写
# ---------------------------------------------------------------------------
def read_cod(data):
    """-> [[(op, bytes), ...] for each event slot]"""
    count, size = struct.unpack_from("<ii", data, 0)
    events = []
    for i in range(count):
        pos, n, _unk, total = struct.unpack_from("<iiii", data, 8 + 16 * i)
        offs = [struct.unpack_from("<i", data, pos + 4 * j)[0] for j in range(n)] + [pos + total]
        events.append([(struct.unpack_from("<i", data, offs[j])[0], data[offs[j] + 4:offs[j + 1]]) for j in range(n)])
    return events


def write_cod(events):
    """布局与原版相同: 文件头 (count, 头长), count 个事件头 {偏移表位置, 指令数, 0, 字节数},
    然后各事件依次为 偏移表 + 指令 (type i32 + 参数)。空事件字节数为 0。"""
    count = len(events)
    head = 8 + 16 * count
    body = b""
    hdrs = b""
    pos = head
    for cmds in events:
        n = len(cmds)
        q = pos + 4 * n
        table = b""
        blob = b""
        for op, d in cmds:
            table += struct.pack("<i", q)
            rec = struct.pack("<i", op) + d
            blob += rec
            q += len(rec)
        total = len(table) + len(blob)
        hdrs += struct.pack("<iiii", pos, n, 0, total)
        body += table + blob
        pos += total
    return struct.pack("<ii", count, head) + hdrs + body


# ---------------------------------------------------------------------------
# 脚本解析
# ---------------------------------------------------------------------------
class ScriptError(Exception):
    pass


TOKEN_RE = re.compile(r'\s*(?:([A-Za-z_][\w]*)=("(?:[^"\\]|\\.)*"|[^\s#]+)|([^\s#=]+))')


def _strip_comment(line):
    out, q = [], False
    for ch in line:
        if ch == '"':
            q = not q
        if ch == "#" and not q:
            break
        out.append(ch)
    return "".join(out).strip()


def _int(s, where):
    try:
        return int(s, 0)
    except ValueError:
        raise ScriptError(f"{where}: 不是整数: {s}")


def parse_script(text, path="<script>"):
    """-> dict(kind, slots, events={id: [stmt]})
    stmt = ("label", name) | ("cmd", name, {k: v}, children|None, lineno)"""
    kind, slots = None, None
    events = {}
    cur = None
    block = None  # 当前块 (children 列表)
    for no, raw in enumerate(text.splitlines(), 1):
        where = f"{path}:{no}"
        line = _strip_comment(raw)
        if not line:
            continue
        if line == "}":
            if block is None:
                raise ScriptError(f"{where}: 多余的 }}")
            block = None
            continue
        m = re.fullmatch(r"([A-Za-z_]\w*):", line)
        if m:
            if cur is None or block is not None:
                raise ScriptError(f"{where}: 标签只能写在事件内、块外")
            cur.append(("label", m.group(1)))
            continue
        opens = line.endswith("{")
        if opens:
            line = line[:-1].strip()
        parts = line.split(None, 1)
        word, rest = parts[0], (parts[1] if len(parts) > 1 else "")
        if word == "script":
            kind = rest.strip()
            if kind not in OPS:
                raise ScriptError(f"{where}: script 只能是 battle 或 town")
            continue
        if word == "events":
            slots = _int(rest.strip(), where)
            continue
        if word == "event":
            if block is not None:
                raise ScriptError(f"{where}: 块未关闭")
            eid = _int(rest.strip().rstrip(":"), where)
            if eid in events:
                raise ScriptError(f"{where}: 事件 {eid} 重复")
            cur = events[eid] = []
            continue
        if cur is None:
            raise ScriptError(f"{where}: 命令必须写在 event 之后")
        args = {}
        pos = 0
        while pos < len(rest):
            m = TOKEN_RE.match(rest, pos)
            if not m or m.end() == pos:
                break
            pos = m.end()
            if m.group(1):
                args[m.group(1)] = m.group(2)
            elif m.group(3):
                raise ScriptError(f"{where}: 参数必须写成 名=值: {m.group(3)}")
        stmt = ("cmd", word, args, [] if opens else None, no)
        if block is not None:
            if opens:
                raise ScriptError(f"{where}: 块不能嵌套")
            block.append(stmt)
        else:
            cur.append(stmt)
            if opens:
                block = stmt[3]
    if block is not None:
        raise ScriptError(f"{path}: 文件结束时块未关闭")
    if kind is None:
        raise ScriptError(f"{path}: 缺少 script battle|town")
    return {"kind": kind, "slots": slots, "events": events}


def _encode_cmd(kind, name, args, labels, where, cmp_op=None):
    """单条命令 -> (op, bytes)。labels: 标签名 -> 指令序号"""
    byname = name_to_ops(kind)
    if name == "raw":
        op = _int(args.get("op", ""), where)
        data = bytes.fromhex(args.get("data", ""))
        return op, data
    if name not in byname:
        raise ScriptError(f"{where}: 未知命令 {name}")
    ops = byname[name]
    if name == "if_var":
        c = args.get("cmp")
        if c not in CMP_NAMES:
            raise ScriptError(f"{where}: if_var 的 cmp 必须是 {'/'.join(CMP_NAMES)}")
        op = CMP_BASE[kind] + CMP_NAMES.index(c)
    else:
        op = ops[0]
    params = OPS[kind][op][1]
    vals = []
    known = {p for p, _, _ in params} | {"cmp"}
    for k in args:
        if k not in known:
            raise ScriptError(f"{where}: {name} 没有参数 {k}")
    for pname, t, default in params:
        if pname in args:
            s = args[pname]
            if t == L:
                if re.fullmatch(r"-?\d+|0x[0-9a-fA-F]+", s):
                    v = int(s, 0)
                elif s in labels:
                    v = labels[s]
                else:
                    raise ScriptError(f"{where}: 未定义的标签 {s}")
            else:
                v = _int(s, where)
        elif default is not None:
            v = default
        else:
            raise ScriptError(f"{where}: {name} 缺少参数 {pname}")
        vals.append(v)
    return op, pack_params(kind, op, vals)


def _expand(kind, stmt, where):
    """把一条语句展开为原版指令数 (用于计算标签位置)"""
    _, name, args, children, _ = stmt
    if children is not None:
        return 1 + len(children)
    if kind == "battle" and name in ("show", "hide", "fade_out") and "ids" in args:
        return 1 + len([x for x in args["ids"].split(",") if x.strip()])
    return 1


def compile_event(kind, stmts, path):
    labels = {}
    idx = 0
    for st in stmts:
        if st[0] == "label":
            if st[1] in labels:
                raise ScriptError(f"{path}: 标签 {st[1]} 重复")
            labels[st[1]] = idx
        else:
            idx += _expand(kind, st, f"{path}:{st[4]}")
    cmds = []
    for st in stmts:
        if st[0] == "label":
            continue
        _, name, args, children, no = st
        where = f"{path}:{no}"
        args = dict(args)
        if kind == "battle" and name in ("show", "hide", "fade_out"):
            op = {"show": 0x0B, "hide": 0x0A, "fade_out": 0x09}[name]
            if "ids" in args:
                ids = [_int(x, where) for x in args.pop("ids").split(",") if x.strip()]
                args["count"] = str(len(ids))
                cmds.append(_encode_cmd(kind, name, args, labels, where))
                cmds += [(0x01, struct.pack("<h", u)) for u in ids]
                continue
            if "group" in args:
                g = args.pop("group")
                args["count"] = "-1"
                args["arg"] = str(GROUPS[g]) if g in GROUPS else g
            cmds.append(_encode_cmd(kind, name, args, labels, where))
            continue
        if children is not None:
            byname = name_to_ops(kind)
            if name not in byname or byname[name][0] not in BATCH[kind]:
                raise ScriptError(f"{where}: {name} 不能带块")
            op = byname[name][0]
            rec_name = OPS[kind][BATCH[kind][op]][0]
            if "count" in args:
                raise ScriptError(f"{where}: 带块时不写 count (由块内命令数决定)")
            args["count"] = str(len(children))
            cmds.append(_encode_cmd(kind, name, args, labels, where))
            for ch in children:
                if ch[1] != rec_name:
                    raise ScriptError(f"{path}:{ch[4]}: {name} 块内只能写 {rec_name}")
                cmds.append(_encode_cmd(kind, ch[1], ch[2], labels, f"{path}:{ch[4]}"))
            continue
        cmds.append(_encode_cmd(kind, name, args, labels, where))
    return cmds


def compile_script(text, path="<script>"):
    sc = parse_script(text, path)
    kind = sc["kind"]
    slots = sc["slots"] if sc["slots"] is not None else EVENT_SLOTS[kind]
    if sc["events"] and max(sc["events"]) >= slots:
        raise ScriptError(f"{path}: 事件号超出 events {slots}")
    events = [compile_event(kind, sc["events"].get(i, []), path) for i in range(slots)]
    return write_cod(events)


# ---------------------------------------------------------------------------
# 往返校验
# ---------------------------------------------------------------------------
def check():
    import decompile_events as dec
    out_dir = dec.OUT_DIR
    ok = bad = 0
    for kind, src, out_name, emsg in dec.all_sources(include_extra=True):
        orig = open(src, "rb").read()
        text = dec.decompile(orig, kind, emsg, os.path.relpath(src, paths.original_dir()))
        again = compile_script(text, src)
        same = again == orig
        disk_note = ""
        if out_name:
            p = os.path.join(out_dir, out_name)
            if os.path.exists(p):
                disk = compile_script(open(p, encoding="utf-8").read(), p)
                if disk != orig:
                    same = False
                    disk_note = " (磁盘脚本编译结果不同)"
            else:
                disk_note = " (磁盘脚本缺失)"
                same = False
        rel = os.path.relpath(src, paths.original_dir())
        if same:
            ok += 1
        else:
            bad += 1
            print(f"不一致: {rel} -> {out_name}{disk_note}")
    print(f"往返校验: {ok} 个一致, {bad} 个不一致")
    return bad == 0


OPS_JSON = os.path.join(paths.REPO, "game/engine/script/evs_ops.json")


def ops_json_text():
    """指令表 -> JSON 文本 (引擎的 .evs 编译器读它; 指令表仍只在本文件定义)"""
    kinds = {}
    for kind, table in OPS.items():
        kinds[kind] = {
            "slots": EVENT_SLOTS[kind],
            "cmp_base": CMP_BASE[kind],
            "batch": {str(k): v for k, v in BATCH[kind].items()},
            "flags": {k: sorted(v) for k, v in OP_FLAGS[kind].items()},
            "ops": [{"op": op, "name": name, "params": [[p, t, d] for p, t, d in params]}
                    for op, (name, params, _) in sorted(table.items())],
        }
    out = {"_comment": "由 tools/assets/compile_events.py --export-ops 生成, 请勿手改", "format": "tdj-evs-ops/1",
           "cmp_names": CMP_NAMES, "groups": GROUPS, "unit_list_ops": list(UNIT_LIST_OPS), "kinds": kinds}
    text = json.dumps(out, ensure_ascii=False, indent=1)
    # 每条指令占一行, 便于对照
    text = re.sub(r'\{\n\s+"op": [^{}]*?\]\n\s+\]\n\s+\}', lambda m: json.dumps(json.loads(m.group(0)), ensure_ascii=False), text)
    text = re.sub(r'\{\n\s+"op": [^{}]*?"params": \[\]\n\s+\}', lambda m: json.dumps(json.loads(m.group(0)), ensure_ascii=False), text)
    return text + "\n"


def export_ops(path=OPS_JSON):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(ops_json_text())
    print(f"{path}: 战场 {len(OPS['battle'])} 条, 城镇 {len(OPS['town'])} 条")


def main(argv):
    if len(argv) == 2 and argv[1] == "--export-ops":
        export_ops()
        return 0
    if len(argv) == 2 and argv[1] == "--check":
        return 0 if check() else 1
    if len(argv) != 3:
        print(__doc__)
        return 2
    try:
        data = compile_script(open(argv[1], encoding="utf-8").read(), argv[1])
    except ScriptError as e:
        print(f"错误: {e}")
        return 1
    open(argv[2], "wb").write(data)
    print(f"{argv[2]}: {len(data)} 字节")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
