#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""资源获取器的窗口 (桌面程序, tkinter + customtkinter; 不是网页)。

  gui.py [--game <原版游戏目录>] [--out <资源包输出目录>] [--wav] [--start] [--selftest]

选原版游戏文件夹 -> 点「开始生成」-> 进度条与日志 -> 完成后打开资源包文件夹。真正干活的是 run.py (提取 + 打包), 这里只负责界面。
--start 打开就直接开始 (调试 / 重跑用); --selftest 把窗口打开、画完、关掉, 打印 GUI OK 就退出 (发布流水线在真实的目标系统上检查用)。
"""
import argparse
import os
import subprocess
import sys
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

import gui_core as core

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)             # 内嵌工具包展开后的目录 (「restool-data」)
HOME = os.path.dirname(ROOT)             # 程序所在目录: 资源包缺省放在这里
FAMILY = {"nt": "Microsoft YaHei UI"}.get(os.name, "PingFang SC" if sys.platform == "darwin" else None)

GREEN, RED, MUTED = ("#1a8a4a", "#4cc27f"), ("#c62d2d", "#ff7070"), ("#667085", "#9aa4b5")


def font(size=14, weight="normal"):
    return ctk.CTkFont(family=FAMILY, size=size, weight=weight)


def open_folder(path):
    if os.name == "nt":
        os.startfile(path)  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


class App(ctk.CTk):
    def __init__(self, game="", out="", wav=False, start=False):
        super().__init__()
        self.title("SwordmanHD 资源获取器")
        self.geometry("820x760")
        self.minsize(720, 640)
        self.runner = core.Runner()
        self.stage_pct = 0
        self.game_ok = False
        self.log_lines = []
        self.out_dir = ""

        # ---- 标题 ----
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=28, pady=(22, 6))
        logo = ctk.CTkLabel(top, text="天", width=52, height=52, corner_radius=13, fg_color=("#2f6fed", "#3d6fe0"), text_color="white", font=font(28, "bold"))
        logo.pack(side="left")
        box = ctk.CTkFrame(top, fg_color="transparent")
        box.pack(side="left", padx=14)
        ctk.CTkLabel(box, text="SwordmanHD 资源获取器", font=font(22, "bold"), anchor="w").pack(anchor="w")
        ctk.CTkLabel(box, text="用你自己的《天地劫：神魔至尊传》原版, 生成 SwordmanHD 需要的资源包 (.pck)", font=font(13), text_color=MUTED, anchor="w").pack(anchor="w")

        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True, padx=28, pady=(6, 20))
        self.build_setup()
        self.build_run()
        self.build_done()
        self.build_fail()

        self.game_var.set(game)
        self.out_var.set(out or os.path.join(HOME, "packs"))
        self.wav_var.set(wav)
        self.show("setup")
        self.check_game()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(100, self.pump)
        if start:
            self.after(400, self.start_job)

    # ------------------------------------------------------------------ 各个画面
    def card(self, parent, title, hint):
        c = ctk.CTkFrame(parent, corner_radius=14)
        c.pack(fill="x", pady=8)
        ctk.CTkLabel(c, text=title, font=font(16, "bold"), anchor="w").pack(fill="x", padx=20, pady=(16, 0))
        if hint:
            ctk.CTkLabel(c, text=hint, font=font(12), text_color=MUTED, anchor="w", justify="left", wraplength=680).pack(fill="x", padx=20, pady=(2, 8))
        return c

    def folder_row(self, card, var, command):
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=20, pady=(0, 6))
        e = ctk.CTkEntry(row, textvariable=var, height=36, font=font(13))
        e.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(row, text="浏览…", width=92, height=36, font=font(13), command=command).pack(side="left", padx=(10, 0))
        return e

    def build_setup(self):
        f = self.setup = ctk.CTkFrame(self.body, fg_color="transparent")
        c1 = self.card(f, "1   原版游戏文件夹", "选里面有 Sprite、Stage 文件夹和 Swordman.exe 的那一层。")
        self.game_var = tk.StringVar()
        self.folder_row(c1, self.game_var, self.browse_game)
        self.game_var.trace_add("write", lambda *a: self.after_idle(self.check_game))
        self.game_status = ctk.CTkLabel(c1, text="", font=font(13), anchor="w", justify="left", wraplength=680)
        self.game_status.pack(fill="x", padx=20, pady=(0, 4))
        self.suggest_btn = ctk.CTkButton(c1, text="", height=28, font=font(12), fg_color="transparent", border_width=1, text_color=("#1d2330", "#e6e9ef"),
                                         command=self.use_suggest)
        self.suggest = None
        ctk.CTkFrame(c1, height=10, fg_color="transparent").pack()

        c2 = self.card(f, "2   资源包保存到", "生成完成后, 里面的 resource 文件夹要放到游戏程序旁边。")
        self.out_var = tk.StringVar()
        self.folder_row(c2, self.out_var, self.browse_out)
        self.wav_var = tk.BooleanVar()
        ctk.CTkCheckBox(c2, text="音效保留原版无损 WAV", variable=self.wav_var, font=font(14)).pack(anchor="w", padx=22, pady=(8, 0))
        ctk.CTkLabel(c2, text="默认把音效压缩成 OGG (资源包小约 90 MB, 听感几乎无差别); 勾选后原样打进包, 游戏照样能读。", font=font(12), text_color=MUTED,
                     anchor="w", justify="left", wraplength=640).pack(fill="x", padx=52, pady=(0, 16))

        self.start_btn = ctk.CTkButton(f, text="开始生成", height=46, font=font(17, "bold"), corner_radius=10, command=self.start_job, state="disabled")
        self.start_btn.pack(fill="x", pady=(14, 6))
        ctk.CTkLabel(f, text="所有需要的工具都已随程序带好, 不用安装任何东西, 全程不联网。生成物仅供个人使用, 请勿分享。", font=font(12), text_color=MUTED,
                     wraplength=720, justify="left").pack(anchor="w", pady=(4, 0))

    def build_run(self):
        f = self.run = ctk.CTkFrame(self.body, corner_radius=14)
        self.phase_lbl = ctk.CTkLabel(f, text="准备", font=font(17, "bold"), anchor="w")
        self.phase_lbl.pack(fill="x", padx=22, pady=(20, 6))
        self.bar = ctk.CTkProgressBar(f, height=14, corner_radius=7)
        self.bar.set(0)
        self.bar.pack(fill="x", padx=22)
        self.tail_lbl = ctk.CTkLabel(f, text="", font=font(12), text_color=MUTED, anchor="w")
        self.tail_lbl.pack(fill="x", padx=22, pady=(6, 6))
        self.log = ctk.CTkTextbox(f, font=ctk.CTkFont(family="Consolas" if os.name == "nt" else None, size=12), wrap="char", corner_radius=8)
        self.log.pack(fill="both", expand=True, padx=22, pady=(0, 8))
        self.log.configure(state="disabled")
        row = ctk.CTkFrame(f, fg_color="transparent")
        row.pack(fill="x", padx=22, pady=(4, 18))
        self.cancel_btn = ctk.CTkButton(row, text="取消", width=110, height=36, font=font(14), fg_color="transparent", border_width=1,
                                        text_color=("#1d2330", "#e6e9ef"), command=self.cancel_job)
        self.cancel_btn.pack(side="left")
        ctk.CTkLabel(row, text="取消后再次开始会从中断的地方接着做。", font=font(12), text_color=MUTED).pack(side="left", padx=12)

    def build_done(self):
        f = self.done = ctk.CTkFrame(self.body, corner_radius=14)
        ctk.CTkLabel(f, text="✓ 生成完成", font=font(22, "bold"), text_color=GREEN, anchor="w").pack(fill="x", padx=24, pady=(22, 4))
        self.done_path = ctk.CTkLabel(f, text="", font=font(13), anchor="w", justify="left", wraplength=700)
        self.done_path.pack(fill="x", padx=24)
        self.done_packs = ctk.CTkLabel(f, text="", font=ctk.CTkFont(family="Consolas" if os.name == "nt" else None, size=13), anchor="w", justify="left")
        self.done_packs.pack(fill="x", padx=24, pady=(10, 4))
        self.done_raw = ctk.CTkLabel(f, text="", font=font(12), text_color=MUTED, anchor="w", justify="left", wraplength=700)
        self.done_raw.pack(fill="x", padx=24, pady=(0, 8))
        ctk.CTkLabel(f, text="下一步: 把其中的 resource 文件夹 (有 mod 就连它一起) 放到游戏程序旁边, 再启动游戏。\n生成的资源包仅供你个人使用, 请勿上传或分享。",
                     font=font(13), anchor="w", justify="left", wraplength=700).pack(fill="x", padx=24, pady=(4, 14))
        row = ctk.CTkFrame(f, fg_color="transparent")
        row.pack(fill="x", padx=24, pady=(0, 22))
        ctk.CTkButton(row, text="打开资源包文件夹", height=40, font=font(14, "bold"), command=lambda: open_folder(self.out_dir)).pack(side="left")
        ctk.CTkButton(row, text="再做一次", height=40, font=font(14), fg_color="transparent", border_width=1, text_color=("#1d2330", "#e6e9ef"),
                      command=lambda: self.show("setup")).pack(side="left", padx=10)
        ctk.CTkButton(row, text="退出", height=40, font=font(14), fg_color="transparent", border_width=1, text_color=("#1d2330", "#e6e9ef"),
                      command=self.destroy).pack(side="left")

    def build_fail(self):
        f = self.fail = ctk.CTkFrame(self.body, corner_radius=14)
        self.fail_title = ctk.CTkLabel(f, text="生成失败", font=font(22, "bold"), text_color=RED, anchor="w")
        self.fail_title.pack(fill="x", padx=24, pady=(22, 4))
        self.fail_msg = ctk.CTkLabel(f, text="", font=font(13), anchor="w", justify="left", wraplength=700)
        self.fail_msg.pack(fill="x", padx=24)
        self.fail_log = ctk.CTkTextbox(f, font=ctk.CTkFont(family="Consolas" if os.name == "nt" else None, size=12), wrap="char", corner_radius=8)
        self.fail_log.pack(fill="both", expand=True, padx=24, pady=10)
        ctk.CTkButton(f, text="返回, 再试一次", height=40, font=font(14, "bold"), command=lambda: self.show("setup")).pack(anchor="w", padx=24, pady=(0, 22))

    def show(self, name):
        for k in ("setup", "run", "done", "fail"):
            getattr(self, k).pack_forget()
        getattr(self, name).pack(fill="both", expand=True)

    # ------------------------------------------------------------------ 选目录与检查
    def browse_game(self):
        d = filedialog.askdirectory(title="选择原版游戏文件夹", initialdir=self.game_var.get() or os.path.expanduser("~"))
        if d:
            self.game_var.set(os.path.normpath(d))

    def browse_out(self):
        d = filedialog.askdirectory(title="选择资源包保存位置", initialdir=self.out_var.get() or HOME)
        if d:
            self.out_var.set(os.path.normpath(d))

    def check_game(self):
        ok, msg, sug = core.check_game(self.game_var.get())
        self.game_ok = ok
        self.game_status.configure(text=(("✓ " if ok else "✗ ") + msg) if msg else "", text_color=GREEN if ok else RED)
        self.suggest = sug
        if sug:
            self.suggest_btn.configure(text="用这个文件夹")
            self.suggest_btn.pack(anchor="w", padx=20, pady=(0, 4))
        else:
            self.suggest_btn.pack_forget()
        self.start_btn.configure(state="normal" if ok else "disabled")

    def use_suggest(self):
        if self.suggest:
            self.game_var.set(self.suggest)

    # ------------------------------------------------------------------ 任务
    def start_job(self):
        if not self.game_ok or self.runner.running():
            return
        out = os.path.abspath(self.out_var.get().strip() or os.path.join(HOME, "packs"))
        game = os.path.abspath(self.game_var.get().strip().strip('"'))
        if out == game or (out + os.sep).startswith(game + os.sep):
            messagebox.showerror("保存位置不对", "资源包不能保存在原版游戏文件夹里, 请换一个位置。")
            return
        try:
            os.makedirs(out, exist_ok=True)
        except OSError as e:
            messagebox.showerror("不能创建文件夹", str(e))
            return
        self.out_dir = out
        self.log_lines = []
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.phase_lbl.configure(text="准备")
        self.bar.set(0)
        self.tail_lbl.configure(text="")
        self.cancel_btn.configure(state="normal")
        cmd = [core.console_python(), os.path.join(HERE, "run.py"), "--game", game, "--out", out] + (["--wav"] if self.wav_var.get() else [])
        env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1", TDJ_NO_PAUSE="1")
        self.append_log("原版游戏: " + game)
        self.append_log("输出到: " + out)
        try:
            self.runner.start(cmd, ROOT, env)
        except OSError as e:
            self.finish_fail("不能启动处理进程: %s" % e)
            return
        self.show("run")

    def cancel_job(self):
        self.cancel_btn.configure(state="disabled")
        self.runner.cancel()

    def append_log(self, line):
        self.log_lines.append(line)
        self.log.configure(state="normal")
        self.log.insert("end", line + "\n")
        if len(self.log_lines) % 400 == 0:   # 太长就从头截掉
            self.log.delete("1.0", "200.0")
        self.log.see("end")
        self.log.configure(state="disabled")

    def pump(self):
        try:
            for _ in range(200):
                try:
                    kind, val = self.runner.events.get_nowait()
                except Exception:
                    break
                if kind == "log":
                    self.append_log(val)
                    self.tail_lbl.configure(text="")
                    sp = core.stage_progress(val)
                    if sp:
                        name, step, total, pct = sp
                        self.phase_lbl.configure(text=name + ("   (%d/%d)" % (step, total) if total else ""))
                        if pct is not None:
                            self.bar.set(pct / 100.0)
                elif kind == "tail":
                    self.tail_lbl.configure(text=val[:140])
                elif kind == "done":
                    self.finish(val)
                elif kind == "cancelled":
                    self.finish_fail("已取消。再次开始会从中断的地方接着做。", title="已取消")
        finally:
            self.after(100, self.pump)

    def finish(self, rc):
        packs = core.list_packs(self.out_dir)
        if rc != 0 or not packs:
            self.finish_fail("处理进程异常结束 (退出码 %s)。日志在 %s" % (rc, os.path.join(ROOT, ".work", "build_assets")) if rc != 0
                             else "流程结束了, 但输出目录里没有找到资源包 (.pck)。")
            return
        self.bar.set(1)
        self.done_path.configure(text="资源包在: " + self.out_dir)
        self.done_packs.configure(text="\n".join("%-30s %6.0f MB" % (n, mb) for n, mb in packs))
        raw = os.path.join(ROOT, "original")
        self.done_raw.configure(text=("另外, 从原版解出来的全部原始资源 (图片、音效、数值等, 做 mod 用) 在: " + raw) if os.path.isfile(os.path.join(raw, "index.json")) else "")
        self.show("done")

    def finish_fail(self, msg, title="生成失败"):
        self.fail_title.configure(text=title)
        self.fail_msg.configure(text=msg)
        self.fail_log.configure(state="normal")
        self.fail_log.delete("1.0", "end")
        self.fail_log.insert("end", "\n".join(self.log_lines[-200:]))
        self.fail_log.see("end")
        self.show("fail")

    def on_close(self):
        if self.runner.running():
            if not messagebox.askyesno("还在生成中", "生成还没做完, 现在退出会中断它 (下次运行会接着做)。\n确定退出吗?"):
                return
            self.runner.cancel()
        self.destroy()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--game", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--wav", action="store_true")
    ap.add_argument("--start", action="store_true", help="打开就直接开始生成")
    ap.add_argument("--selftest", action="store_true", help="打开窗口、画完、关掉就退出 (自检)")
    a = ap.parse_args()
    if os.name == "nt":   # 高分屏下不要被系统放大成模糊的图
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    ctk.set_appearance_mode("system")
    ctk.set_default_color_theme("blue")
    app = App(a.game, a.out, a.wav, a.start)
    if a.selftest:
        app.after(800, lambda: (print("GUI OK", flush=True), app.destroy()))
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
