#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""原版事件字节码 EVENT_NN.COD → 剧情脚本 (.evs, 格式见 docs/剧情脚本格式.md)。

  decompile_events.py                  反编译全部关卡与城镇到 game/content/tdj/scripts/
  decompile_events.py SRC.COD [battle|town]   反编译一个文件, 打印到标准输出

对白原文取自 data/emsg/ (繁体), 转成简体写在注释里。
"""
import glob
import json
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tools/
import _boot  # noqa: E402,F401
import paths  # noqa: E402
from compile_events import (BATCH, CMP_BASE, CMP_NAMES, GROUPS, I, L, OPS,  # noqa: E402
                            UNIT_LIST_OPS, op_size, read_cod)

OUT_DIR = os.path.join(paths.REPO, "game", "content", "tdj", "scripts")
EMSG_DIR = os.path.join(paths.REPO, "data", "emsg")
EXT = ".evs"

try:
    import opencc
    _cc = opencc.OpenCC("t2s")
    to_simplified = _cc.convert
except Exception:  # 没装 opencc 时注释保留繁体
    def to_simplified(s):
        return s


# ---------------------------------------------------------------------------
# 数据源
# ---------------------------------------------------------------------------
def _find(dirpath, pattern):
    for f in os.listdir(dirpath):
        if re.fullmatch(pattern, f, re.I):
            return os.path.join(dirpath, f)
    return None


def _emsg(sub, dirname):
    p = os.path.join(EMSG_DIR, sub, dirname + ".json")
    if os.path.exists(p):
        return json.load(open(p, encoding="utf-8"))["groups"]
    return []


def all_sources(include_extra=False):
    """-> (kind, COD 路径, 输出文件名|None, 对白组)
    城镇目录里另有旧版残留 (Rpg01/EVENT_00、rpg02/EVENT_01, 游戏不读), 只在 include_extra 时参与往返校验。"""
    orig = paths.original_dir()
    for d in sorted(glob.glob(os.path.join(orig, "Stage", "*")), key=lambda p: p.lower()):
        m = re.fullmatch(r"stage(\d\d)", os.path.basename(d), re.I)
        if not m:
            continue
        n = int(m.group(1))
        f = _find(d, rf"EVENT_{n:02d}\.COD")
        if f:
            yield "battle", f, f"stage_{n:02d}{EXT}", _emsg("Stage", os.path.basename(d))
    for d in sorted(glob.glob(os.path.join(orig, "Rpg", "*")), key=lambda p: p.lower()):
        m = re.fullmatch(r"rpg(\d\d)", os.path.basename(d), re.I)
        if not m:
            continue
        n = int(m.group(1))
        groups = _emsg("Rpg", os.path.basename(d))
        for f in sorted(os.listdir(d)):
            fm = re.fullmatch(r"EVENT_(\d\d)\.COD", f, re.I)
            if not fm:
                continue
            if int(fm.group(1)) == n:
                yield "town", os.path.join(d, f), f"town_{n:02d}{EXT}", groups
            elif include_extra:
                yield "town", os.path.join(d, f), None, groups


# ---------------------------------------------------------------------------
# 反编译
# ---------------------------------------------------------------------------
def _params(kind, op, d):
    vals, o = [], 0
    for _, t, _ in OPS[kind][op][1]:
        if t in (I, L):
            vals.append(struct.unpack_from("<i", d, o)[0])
            o += 4
        else:
            vals.append(struct.unpack_from("<h", d, o)[0])
            o += 2
    return vals


def _well_formed(kind, op, d):
    return op in OPS[kind] and len(d) == op_size(kind, op)


def _text(groups, ev, num):
    if 0 <= ev < len(groups) and 0 <= num < len(groups[ev]):
        s = groups[ev][num]
        return to_simplified(s).replace("\n", "／") if s else "(空)"
    return "(无此句)"


def _fmt_val(pname, v):
    if pname == "color":
        return f"0x{v & 0xFFFF:04X}"
    return str(v)


def _cmd_line(kind, op, vals, labels, n, skip=()):
    name, params, _ = OPS[kind][op]
    parts = [name]
    comment = ""
    is_cmp = name == "if_var"
    for (pname, t, default), v in zip(params, vals):
        if pname in skip:
            continue
        if is_cmp and pname == "value":
            parts.append(f"cmp={CMP_NAMES[op - CMP_BASE[kind]]}")
        if t == L:
            if v in labels:
                parts.append(f"{pname}={labels[v]}")
            else:
                parts.append(f"{pname}={v}")
                comment = f"越界跳转 (事件只有 {n} 条): 等于结束事件"
            continue
        if default is not None and v == default:
            continue
        parts.append(f"{pname}={_fmt_val(pname, v)}")
    return " ".join(parts), comment


def decompile_event(kind, eid, cmds, groups):
    n = len(cmds)
    # 1. 跳转目标 -> 标签
    targets = set()
    for op, d in cmds:
        if _well_formed(kind, op, d):
            for (pname, t, _), v in zip(OPS[kind][op][1], _params(kind, op, d)):
                if t == L and 0 <= v <= n:
                    targets.add(v)
    labels = {t: f"L{i + 1}" for i, t in enumerate(sorted(targets))}

    lines = []
    ind = "    "
    j = 0

    def emit(text, comment=""):
        lines.append(f"{ind}{text}" + (f"    # {comment}" if comment else ""))

    while j < n:
        if j in labels:
            lines.append(f"{labels[j]}:")
        op, d = cmds[j]
        if not _well_formed(kind, op, d):
            emit(f"raw op=0x{op:02X} data={d.hex()}", "未知指令或参数长度不符")
            j += 1
            continue
        vals = _params(kind, op, d)
        name = OPS[kind][op][0]

        # 批量指令
        if op in BATCH[kind]:
            rec = BATCH[kind][op]
            count = vals[0]
            body = cmds[j + 1:j + 1 + count] if count > 0 else []
            foldable = (count > 0 and len(body) == count
                        and all(o == rec and _well_formed(kind, o, dd) for o, dd in body)
                        and not any(t in labels for t in range(j + 1, j + 1 + count)))
            if op in UNIT_LIST_OPS:
                if count == -1:
                    text, _ = _cmd_line(kind, op, vals, labels, n, skip=("count", "arg"))
                    g = vals[1]
                    gname = {v: k for k, v in GROUPS.items()}.get(g, str(g))
                    emit(f"{text} group={gname}")
                    j += 1
                    continue
                if foldable:
                    ids = ",".join(str(_params(kind, rec, dd)[0]) for _, dd in body)
                    text, _ = _cmd_line(kind, op, vals, labels, n, skip=("count",))
                    emit(f"{text} ids={ids}")
                    j += 1 + count
                    continue
            elif foldable:
                text, _ = _cmd_line(kind, op, vals, labels, n, skip=("count",))
                emit(text + " {")
                for o, dd in body:
                    t2, _ = _cmd_line(kind, o, _params(kind, o, dd), labels, n)
                    lines.append(f"{ind}{ind}{t2}")
                lines.append(f"{ind}}}")
                j += 1 + count
                continue
            # 不能折叠: 头指令写出 count, 后续记录各自成行
            text, _ = _cmd_line(kind, op, vals, labels, n)
            if "count=" not in text:
                text += f" count={count}"
            emit(text, f"后续 {count} 条指令被原版当作记录读取 (数据异常, 原样保留)" if count > 0 else "")
            j += 1
            continue

        text, comment = _cmd_line(kind, op, vals, labels, n)
        if name == "say":
            comment = "「" + _text(groups, eid, vals[-1]) + "」"
        elif name == "choose":
            m = vals[3]
            comment = " / ".join("「" + _text(groups, eid, m + k) + "」" for k in range(3))
        emit(text, comment)
        j += 1
    if n in labels:
        lines.append(f"{labels[n]}:")
    return lines


def decompile(data, kind, groups, src_rel=""):
    events = read_cod(data)
    out = [
        f"# 由 tools/assets/decompile_events.py 从原版 {src_rel} 生成; 格式见 docs/剧情脚本格式.md",
        "# 对白 msg=N 指本事件 (事件号 = 对白组号) 的第 N 句, 注释里是简体原文",
        f"script {kind}",
    ]
    out.append(f"events {len(events)}")
    for eid, cmds in enumerate(events):
        if not cmds:
            continue
        out.append("")
        out.append(f"event {eid}")
        out += decompile_event(kind, eid, cmds, groups)
    return "\n".join(out) + "\n"


def main(argv):
    if len(argv) >= 2:
        kind = argv[2] if len(argv) > 2 else ("town" if "rpg" in argv[1].lower() else "battle")
        d = os.path.basename(os.path.dirname(os.path.abspath(argv[1])))
        groups = _emsg("Rpg" if kind == "town" else "Stage", d)
        sys.stdout.write(decompile(open(argv[1], "rb").read(), kind, groups, argv[1]))
        return 0
    os.makedirs(OUT_DIR, exist_ok=True)
    n = 0
    for kind, src, out_name, groups in all_sources():
        rel = os.path.relpath(src, paths.original_dir()).replace(os.sep, "/")  # 注释里的来源路径跨平台一致
        text = decompile(open(src, "rb").read(), kind, groups, rel)
        with open(os.path.join(OUT_DIR, out_name), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        n += 1
    print(f"已写出 {n} 个脚本到 {os.path.relpath(OUT_DIR, paths.REPO)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
