# SPDX-License-Identifier: GPL-3.0-only
"""资源获取器窗口的非界面部分 (可单测): 原版目录检查、子进程输出分行、阶段进度、后台任务的启动 / 取消。"""
import os
import queue
import signal
import subprocess
import sys
import threading

CREATE_NO_WINDOW = 0x08000000   # Windows: 子进程不弹黑色控制台窗口

# build_assets.py 的阶段名 (跑起来会打印 "== <名字>") 与界面显示的名字; 获取器只做提取 + 打包
STAGES = ["export", "data", "content", "movie", "icon", "pack"]
LABEL = {"export": "解出原版资源", "data": "解析数值与对白", "content": "生成剧情与关卡",
         "movie": "转换过场动画", "icon": "生成图标", "pack": "打包资源包"}


def file_exists(p):
    return os.path.isfile(p)


def looks_like_game(d):
    """粗查是不是原版《天地劫：神魔至尊传》目录: 有 Sprite/ Stage/ 和游戏主程序。返回 (是否, 说明)。"""
    miss = [n + "/" for n in ("Sprite", "Stage") if not os.path.isdir(os.path.join(d, n))]
    if not any(file_exists(os.path.join(d, f)) for f in ("Swordman.exe", "Sm_win2.exe", "SWORDMAN.EXE")):
        miss.append("Swordman.exe")
    return (not miss), ("" if not miss else "缺少 " + "、".join(miss))


def check_game(d):
    """返回 (是否可用, 提示文字, 建议改用的子目录或 None)。选了上一层时往下找一层给出建议。"""
    d = d.strip().strip('"').strip("'")
    if not d:
        return False, "", None
    if not os.path.isdir(d):
        return False, "这个文件夹不存在", None
    ok, why = looks_like_game(d)
    if ok:
        return True, "看起来是原版游戏文件夹", None
    try:
        for name in sorted(os.listdir(d)):
            sub = os.path.join(d, name)
            if os.path.isdir(sub) and looks_like_game(sub)[0]:
                return False, "这里面还有一层, 原版游戏文件夹应该是: " + sub, sub
    except OSError:
        pass
    return False, "不像原版游戏文件夹 (%s)。要选里面有 Sprite、Stage 文件夹和 Swordman.exe 的那一层" % why, None


class LineSplitter:
    """子进程输出 (字节流) -> 事件: ("log", 行) 或 ("tail", 进度文字)。
    \\n 结尾是一行日志; \\r 覆盖的进度 (pip / 下载进度条等) 只作为 tail; \\r\\n 当换行。"""

    def __init__(self):
        self.buf = bytearray()
        self.pending_cr = False

    def feed(self, data):
        out = []
        for b in data:
            if self.pending_cr and b != 10:
                self.buf.clear()
            self.pending_cr = False
            if b == 10:
                if self.buf:
                    out.append(("log", self.buf.decode("utf-8", "replace")))
                self.buf.clear()
            elif b == 13:
                if self.buf:
                    out.append(("tail", self.buf.decode("utf-8", "replace")))
                self.pending_cr = True
            else:
                self.buf.append(b)
        return out

    def flush(self):
        out = [("log", self.buf.decode("utf-8", "replace"))] if self.buf else []
        self.buf.clear()
        return out


def stage_progress(line):
    """"== export" 这样的阶段行 -> (显示名, 第几步, 共几步, 进度百分比); 其他 "== xxx" 原样显示; 不是阶段行返回 None。"""
    if not line.startswith("== "):
        return None
    name = line[3:].strip()
    if name in STAGES:
        i = STAGES.index(name)
        return LABEL[name], i + 1, len(STAGES), 5 + i * 93 // len(STAGES)   # 前 5% 留给准备
    return name, 0, 0, None


def list_packs(out):
    """输出目录里的资源包: [(相对名, MB)]"""
    res = []
    for sub in ("resource", "mod"):
        d = os.path.join(out, sub)
        if os.path.isdir(d):
            for fn in sorted(os.listdir(d)):
                if fn.endswith(".pck"):
                    res.append((sub + "/" + fn, os.path.getsize(os.path.join(d, fn)) / 1048576))
    return res


def kill_tree(proc):
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], creationflags=CREATE_NO_WINDOW,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            proc.kill()


def console_python():
    """pythonw.exe 没有控制台, 子进程要用同目录的 python.exe 才有正常的标准输出"""
    exe = sys.executable
    if exe.lower().endswith("pythonw.exe"):
        cand = exe[:-len("pythonw.exe")] + "python.exe"
        if os.path.isfile(cand):
            return cand
    return exe


class Runner:
    """在后台线程里跑一个子进程, 把输出变成事件放进队列 (界面线程定时取)。事件: ("log"|"tail", 文字) ("done", 退出码) ("cancelled", None)"""

    def __init__(self):
        self.events = queue.Queue()
        self.proc = None
        self.cancelled = False

    def start(self, cmd, cwd, env):
        kw = {"creationflags": CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
        self.cancelled = False
        self.proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, **kw)
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        sp = LineSplitter()
        while True:
            chunk = self.proc.stdout.read1(65536)
            if not chunk:
                break
            for ev in sp.feed(chunk):
                self.events.put(ev)
        for ev in sp.flush():
            self.events.put(ev)
        rc = self.proc.wait()
        self.events.put(("cancelled", None) if self.cancelled else ("done", rc))

    def cancel(self):
        self.cancelled = True
        if self.proc:
            kill_tree(self.proc)

    def running(self):
        return self.proc is not None and self.proc.poll() is None
