# SPDX-License-Identifier: GPL-3.0-only
"""tools/assets/pck_writer.py: 纯 Python 写出的 .pck 能读回、能校验; 有 Godot 时与 PCKPacker 的输出逐字节一致 (换 Godot 版本时由它发现格式变化)。"""
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "pipeline"))
import pck_writer as W  # noqa: E402

# 覆盖: 空文件、路径长度恰为 4 的倍数 (目录表补零 0 字节)、中文路径、大小不是对齐倍数的最后一个文件 (末尾补齐)
FILES = [("a.txt", b"hello"), ("empty.bin", b""), ("dir/abcd.bin", b"x" * 31), ("dir/中文/图.webp", bytes(range(256)) * 9), ("z" * 13, b"y" * 33)]


def make_items(d):
    items = []
    for i, (res, data) in enumerate(FILES):
        p = os.path.join(d, "src%d" % i)
        with open(p, "wb") as f:
            f.write(data)
        items.append((p, "res://" + res))
    return items


class PckWriterTest(unittest.TestCase):
    def test_roundtrip_and_check(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "t.pck")
            self.assertEqual(W.write_pck(out, make_items(d)), len(FILES))
            self.assertEqual(W.check_pck(out), len(FILES))
            ents = W.read_pck(out)
            self.assertEqual([e[0] for e in ents], [r for r, _ in FILES])
            data = open(out, "rb").read()
            for (p, off, size, _), (_, want) in zip(ents, FILES):
                self.assertEqual(data[off:off + size], want)
                self.assertEqual(off % W.ALIGNMENT, 0)

    def test_corruption_is_detected(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "t.pck")
            W.write_pck(out, make_items(d))
            off = W.read_pck(out)[0][1]
            b = bytearray(open(out, "rb").read())
            b[off] ^= 0xFF
            open(out, "wb").write(bytes(b))
            with self.assertRaises(ValueError):
                W.check_pck(out)

    def test_not_a_pck(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.pck")
            open(p, "wb").write(b"not a pack at all" * 10)
            with self.assertRaises(ValueError):
                W.read_pck(p)

    def test_identical_to_godot_pckpacker(self):
        """有 Godot 4.7.2 (环境变量 GODOT) 和主仓库 (MAIN_REPO_DIR, 用它的 tools/release/pack_pck.gd 与 game/ 工程) 时, 与 PCKPacker 输出逐字节比较。"""
        godot, main = os.environ.get("GODOT", ""), os.environ.get("MAIN_REPO_DIR", "")
        gd = os.path.join(main, "tools", "release", "pack_pck.gd")
        if not (godot and os.path.isfile(godot) and os.path.isfile(gd)):
            self.skipTest("没有 GODOT / MAIN_REPO_DIR")
        with tempfile.TemporaryDirectory() as d:
            items = make_items(d)
            lst = os.path.join(d, "list.txt")
            with open(lst, "w", encoding="utf-8", newline="\n") as f:
                for src, res in items:
                    f.write("%s\t%s\n" % (src.replace("\\", "/"), res))
            ref = os.path.join(d, "godot.pck")
            r = subprocess.run([godot, "--headless", "--path", os.path.join(main, "game"), "--script", gd, "--", "--list=" + lst, "--out=" + ref],
                               capture_output=True, text=True, timeout=300)
            self.assertTrue(os.path.isfile(ref), r.stdout + r.stderr)
            mine = os.path.join(d, "mine.pck")
            W.write_pck(mine, items)
            with open(mine, "rb") as a, open(ref, "rb") as b:
                self.assertEqual(a.read(), b.read(), "纯 Python 写出的包与 Godot PCKPacker 不一致 (格式变了? 见 pck_writer.py 文件头)")


if __name__ == "__main__":
    unittest.main()
