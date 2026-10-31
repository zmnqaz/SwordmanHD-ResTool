#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""把关卡/RPG 对白 EMSG_NN.MSG (Big5) 导出成 UTF-8 JSON: data/emsg/Stage/StageNN.json、data/emsg/Rpg/rpgNN.json。
格式参照重制版 GameBattleData.loadEMSG: count(i32) size(i32), count 个组头 {偏移, 句数, 未知, 字节数};
每组: 4 字节后为句子偏移表; 句子是若干 Big5 片段, 片段以 0 结尾, 其后 1=换行继续, 2=结束。
输出: {"source": 原文件, "groups": [[句子, ...], ...]}, 组号即事件编号, 句号即对白指令里的 talkNum。
文本统一转简体 (to_simplified, parse_data.py 也用它): OpenCC t2s, 再按原版字库 (Tfont, 大陆版简体字形) 修正。
环境变量 TDJ_TEXT_LANG=hant 时不转简体 (保留原版 Big5 繁体原文, 只做标点修正): tools/assets/make_locale.py 用它跑出繁体版再与简体逐字段比对,
生成内容包的 locale/hant 叠加层 (docs/设计_繁简切换.md)。缺省 (hans) 行为不变。"""
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tools/
import _boot  # noqa: E402,F401
from paths import original_dir  # noqa: E402

# 转简体: OpenCC t2s 后按原版字库字形核对, 与原版简体实机不一致处在这里修正。
KEEP = "闇"                       # 原文就是这个字 (光闇、诸闇、灭闇穹张), 不转成「暗」 (原版字库其实没画它, 实机显示空白, 见 docs/界面布局.md §2.2.1「补字」)
PHRASES = {"珠鍊": "珠鏈",        # OpenCC 会把「鍊」一律转「炼」, 首饰名应为「链」
           "牠": "它",            # OpenCC 不转「牠」, 原版字库画的是「它」
           "徵調": "征調",
           "墬": "墜"}            # 异体字, 原版字库没有这个字形
PUNCT = {"∼": "～", "〝": "“", "〞": "”"}   # Big5 特有符号换成简体常用写法
_cc = None


def text_lang():
    return os.environ.get("TDJ_TEXT_LANG", "hans")


def to_simplified(s):
    """繁体 (原版 Big5 文本) -> 简体。逐字等长转换, 原版字库保留的字不转。
    TDJ_TEXT_LANG=hant: 保留繁体原文, 只换 Big5 特有标点 (函数名沿用, 调用方不用改)。"""
    global _cc
    if text_lang() == "hant":
        for a, b in PUNCT.items():
            s = s.replace(a, b)
        return s
    if _cc is None:
        import opencc
        _cc = opencc.OpenCC("t2s")
    src = s
    for a, b in PHRASES.items():
        src = src.replace(a, b)
    out = _cc.convert(src)
    if len(out) == len(src):
        out = "".join(a if a in KEEP else b for a, b in zip(src, out))
    for a, b in PUNCT.items():
        out = out.replace(a, b)
    return out


def decode(raw):
    """Big5 片段 -> str。原版用了倚天扩展字 (如 F9D8「裏」), 所以用 cp950 并以 hkscs 兜底。"""
    try:
        return raw.decode("cp950")
    except UnicodeDecodeError:
        return raw.decode("big5hkscs", "replace")


def parse(b):
    c, _ = struct.unpack_from("<ii", b, 0)
    heads = [struct.unpack_from("<iiii", b, 8 + 16 * i) for i in range(c)]
    groups = []
    for pos, count, _unk, length in heads:
        offs = [struct.unpack_from("<i", b, pos + 4 + 4 * i)[0] for i in range(count)]
        rest = length - 4 - count * 4
        sents = []
        for i in range(count):
            size = rest if i == count - 1 else offs[i + 1] - offs[i]
            rest -= 0 if i == count - 1 else size
            seg, out, j, end = offs[i], [], offs[i], offs[i] + size
            while j < end:
                if b[j] == 0:
                    out.append(decode(b[seg:j]))
                    k = j + 1
                    while k < len(b) and b[k] == 0:
                        k += 1
                    if k >= len(b) or b[k] == 2:
                        break
                    if b[k] == 1:
                        out.append("\n")
                    seg = j = k + 1
                    continue
                j += 1
            sents.append(to_simplified("".join(out)))
        groups.append(sents)
    return groups


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else original_dir()
    dst = sys.argv[2] if len(sys.argv) > 2 else "data/emsg"
    n = 0
    for top in ("Stage", "Rpg"):
        for d in sorted(os.listdir(os.path.join(src, top))):
            full = os.path.join(src, top, d)
            if not os.path.isdir(full):
                continue
            num = "".join(ch for ch in d if ch.isdigit())
            f = next((x for x in os.listdir(full) if x.lower() == f"emsg_{num}.msg"), None)
            if not f:
                continue
            groups = parse(open(os.path.join(full, f), "rb").read())
            os.makedirs(os.path.join(dst, top), exist_ok=True)
            with open(os.path.join(dst, top, f"{d}.json"), "w", encoding="utf-8", newline="\n") as fo:
                json.dump({"source": f"{top}/{d}/{f}", "groups": groups}, fo, ensure_ascii=False, indent=1)
            n += 1
    print(f"{n} 个对白文件 -> {dst}")


if __name__ == "__main__":
    main()
