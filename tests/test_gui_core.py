# SPDX-License-Identifier: GPL-3.0-only
"""gui_core: 原版目录检查、输出分行 (\\r 进度)、阶段进度、后台任务运行 / 取消。不需要窗口。"""
import os
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "pipeline"))
import gui_core as G  # noqa: E402


def make_game(d):
    for sub in ("Sprite", "Stage"):
        os.makedirs(os.path.join(d, sub), exist_ok=True)
    open(os.path.join(d, "Swordman.exe"), "wb").close()


class GameCheckTest(unittest.TestCase):
    def test_empty_and_missing(self):
        self.assertEqual(G.check_game("")[:2], (False, ""))
        self.assertFalse(G.check_game("/no/such/dir/xyz")[0])
        with tempfile.TemporaryDirectory() as d:
            ok, msg, _ = G.check_game(d)
            self.assertFalse(ok)
            self.assertIn("Sprite", msg)

    def test_ok_and_parent_suggestion(self):
        with tempfile.TemporaryDirectory() as d:
            game = os.path.join(d, "天地劫")
            make_game(game)
            self.assertTrue(G.check_game(game)[0])
            ok, msg, sug = G.check_game(d)       # 选了上一层
            self.assertFalse(ok)
            self.assertEqual(sug, game)
            self.assertIn("还有一层", msg)

    def test_quotes_are_stripped(self):
        with tempfile.TemporaryDirectory() as d:
            make_game(d)
            self.assertTrue(G.check_game('"%s"' % d)[0])


class SplitterTest(unittest.TestCase):
    def test_cr_is_tail_and_crlf_is_newline(self):
        sp = G.LineSplitter()
        ev = sp.feed(b"one\nprog1\rprog2\rdone\nwin\r\nla") + sp.feed(b"st") + sp.flush()
        logs = [t for k, t in ev if k == "log"]
        tails = [t for k, t in ev if k == "tail"]
        self.assertEqual(logs, ["one", "done", "win", "last"])
        self.assertEqual(tails[:2], ["prog1", "prog2"])

    def test_utf8_split_across_chunks(self):
        sp = G.LineSplitter()
        raw = "解出原版资源\n".encode("utf-8")
        ev = sp.feed(raw[:4]) + sp.feed(raw[4:])
        self.assertEqual([t for k, t in ev if k == "log"], ["解出原版资源"])


class ProgressTest(unittest.TestCase):
    def test_stage_lines(self):
        label, step, total, pct = G.stage_progress("== content")
        self.assertEqual((label, step, total), ("生成剧情与关卡", 3, len(G.STAGES)))
        self.assertTrue(5 < pct < 98)
        self.assertEqual(G.stage_progress("== 别的事")[:3], ("别的事", 0, 0))
        self.assertIsNone(G.stage_progress("普通日志"))


class RunnerTest(unittest.TestCase):
    def wait(self, r, kinds, timeout=15):
        got, end = [], time.time() + timeout
        while time.time() < end:
            try:
                ev = r.events.get(timeout=0.2)
            except Exception:
                continue
            got.append(ev)
            if ev[0] in kinds:
                return got
        self.fail("超时, 收到 %r" % got)

    def test_runs_and_reports_exit_code(self):
        r = G.Runner()
        r.start([sys.executable, "-c", "print('hello'); import sys; sys.exit(3)"], os.getcwd(), dict(os.environ))
        got = self.wait(r, ("done", "cancelled"))
        self.assertIn(("log", "hello"), got)
        self.assertEqual(got[-1], ("done", 3))

    def test_cancel_kills_process_tree(self):
        r = G.Runner()
        code = "import subprocess,sys,time;subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);print('up',flush=True);time.sleep(60)"
        r.start([sys.executable, "-c", code], os.getcwd(), dict(os.environ))
        self.wait(r, ("log",))
        r.cancel()
        got = self.wait(r, ("done", "cancelled"))
        self.assertEqual(got[-1][0], "cancelled")


if __name__ == "__main__":
    unittest.main()
