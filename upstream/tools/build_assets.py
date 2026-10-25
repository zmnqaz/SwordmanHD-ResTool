#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""一键生成游戏资源: 玩家自己的原版游戏目录 -> 原版资源、内容包、高清贴图、过场视频 -> 资源包 (.pck)。
本项目不提供任何原版资源 (贴图/音频/剧情/数值均有版权), 用这个脚本从你自己的《天地劫：神魔至尊传》生成。

  python tools/build_assets.py --game <原版游戏目录>          全部阶段 (AI 贴图约 2 小时 + AI 过场约 40 分钟, 可断点续跑)
  python tools/build_assets.py --game <目录> --no-ai          不跑 AI, 不出 hd_images.pck: 像素画类照样运行时生成 6 倍, 头像/地图/过场用原版
  python tools/build_assets.py --only pack                     只把现有产物重新打包
  python tools/build_assets.py --only verify                   只做产物校验 (内容包 schema / 对原版逐项核对 / 用资源包无头冒烟一关)
  python tools/build_assets.py --check [--game <目录>] [--no-ai]   只做环境预检 (python 包、ffmpeg 编码器、Godot 版本、Real-ESRGAN、磁盘、原版版本), 不生成任何东西
  python tools/build_assets.py --dry-run ...                   预检 + 打印将要跑的阶段 (含 export 是否会被跳过), 不执行
  python tools/build_assets.py --list                          列出阶段
通用选项: --log <目录> (默认 <仓库>/.work/build_assets/<时间戳>/, 总日志 build.log + 每阶段 <阶段>.log + build_manifest.json)、
  --force (export 阶段不跳过已完成的导出)、--allow-unknown-version (原版文件与 tools/assets/original/known_versions.json 对不上时仍继续)、--skip-check (跳过自动预检)。

阶段 (按序; 产物就是开发时游戏直接读的目录, 位置见 tools/paths.py, 原图目录可用 --original 或 TDJ_ORIGINAL 指定):
  export   原版游戏 -> 原图目录 (tools/assets/original/export_original.py + make_index.py; SAF 动画/地图/音效无损解出, Bink 过场 -> mp4)
  data     原图目录 -> data/*.json (tools/assets/parse_data.py 数值表, tools/assets/export_text.py 对白)
  content  data/ + 原图目录 -> game/content/tdj/ (decompile_events.py 剧情脚本, import_content.py 数据/关卡/城镇,
           make_locale.py / make_hant_text.py 繁体叠加层 locale/hant (简体/繁体切换, docs/设计_繁简切换.md),
           texture_classes.py 贴图分类表 textures.json; 整个目录都是生成的, 项目手写的界面/演出配置在 game/content/remake)
  hd       原图目录 -> hd4x/ (tools/assets/hd_pipeline.py: AI 放大头像/地图/发光/大图, 目录 hd4x.json; 需要 Vulkan 显卡;
           已完成的跳过, 可断点续跑; 可选, --no-ai 跳过)
  movie    原图目录的 mp4 -> game/classic/movies/*.ogv (tools/assets/make_godot_movies.py, 原版 320x200)
  hdmovie  原版 Bink 过场 -> hd4x/<同路径>.ogv (tools/assets/movie_hd.py: animevideov3 4 倍 1280x800, 约 0.5GB / 40 分钟;
           需要 Vulkan 显卡; 已完成的跳过; 可选, --no-ai 跳过; 游戏有高清版就优先播放)
  icon     原版 Swordman.exe 的图标 -> game/assets/icon.ico (导出 exe 用)
  pack     以上产物 -> <--out>/ 下两个文件夹:
             resource/ 必备资源: common_assets.pck (公用素材: 动画/像素画/音乐音效)、common_story.pck (剧情/数值/分类表)、
                       hd_images.pck + hd_movies.pck (AI 高清图/过场, 可选) 或 classic_images.pck + classic_movies.pck (原版画质图/过场);
                       高清与原版画质二选一, 有高清时 classic_images 只含被高清替代的那部分原图, 装了 hd_images 就可以不放
             mod/      可选 mod: face_hk.pck (港漫头像; 目录 TDJ_FACE_HK 或 .work/face_hk 存在才出)
           另写 <--out>/BUILD.json (生成时间、git 版本、原版版本哈希; 同时放进 common_story.pck 的 content/tdj/BUILD.json)
  verify   产物校验: content_schema -> check_content -> check_items -> 用 --packs=<--out> 无头跑第 0 关到过关; 任何一项失败退出码非 0
幂等: export 已完成 (index.json 在、登记的文件都在、导出戳与当前原版指纹一致) 时自动跳过, --force 重导; 其余阶段各自断点续跑或几秒重算。
发布: tools/build_windows.py [--linux] 导出程序并调用本脚本的 pack 阶段, 把资源包放在可执行文件旁。
开发: 游戏直接读上述目录, 不必打包; 运行时加 --packs=<目录> 可改为挂载生成的资源包, 检验与发布版一致。
需要: Python 3 + numpy + Pillow, ffmpeg (带 libx264/libtheora/libvorbis), Godot (tools/paths.py), hd 阶段还要 tools/realesrgan。
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import paths  # noqa: E402
sys.path.insert(0, os.path.join(HERE, "assets"))
import audio_pack  # noqa: E402  (音效 wav -> ogg, 打包用)
import original_split  # noqa: E402  (原版资源拆 核心 / 原版画质图)

REPO = paths.REPO
STAGES = ["export", "data", "content", "hd", "movie", "hdmovie", "icon", "pack", "verify"]
AI_STAGES = ["hd", "hdmovie"]  # --no-ai 跳过
# 原图目录里只给导入工具用、运行时不读的文件 (剧情/数值已在内容包里, 过场用 classic_movies.pck 的 ogv), 不进 common_assets.pck
NOT_RUNTIME = (".mp4", ".dat", ".cod", ".msg", ".dtl", ".mpl", ".csp", ".txt")


class Tee:
    """stdout/stderr 同时写控制台和日志文件 (总日志 build.log; 阶段日志由 stage_log 切换)。"""

    def __init__(self, stream, files):
        self.stream, self.files = stream, files

    def write(self, text):
        self.stream.write(text)
        for f in self.files:
            f.write(text)
        return len(text)

    def flush(self):
        self.stream.flush()
        for f in self.files:
            f.flush()

    def __getattr__(self, k):
        return getattr(self.stream, k)


_extra_files = []  # Tee 共享的文件列表 (总日志 + 当前阶段日志)


def die(msg):
    print("错误: " + msg, file=sys.stderr)
    sys.exit(1)


def run(cmd, env=None, cwd=None):
    """跑子进程: 输出同时进控制台与日志。失败 die (退出码 1, 日志里有完整输出)。"""
    print("  $ " + " ".join(os.path.relpath(c, REPO) if os.path.isabs(c) and c.startswith(REPO) else c for c in cmd), flush=True)
    env = dict(env or os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    p = subprocess.Popen(cmd, env=env, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    for raw in iter(p.stdout.readline, b""):
        sys.stdout.write(raw.decode("utf-8", errors="replace"))
    p.wait()
    sys.stdout.flush()
    if p.returncode:
        die("命令失败 (退出码 %d): %s" % (p.returncode, " ".join(os.path.basename(c) for c in cmd[:3])))


def py(script, *args, env=None):
    """script 是相对 tools/ 的路径 (如 "assets/parse_data.py", "checks/content_schema.py")"""
    run([sys.executable, os.path.join(HERE, script)] + list(args), env=env)



# ---------------- 原版版本指纹 (只存哈希与大小, 不存内容) ----------------
KNOWN_VERSIONS = os.path.join(HERE, "assets", "original", "known_versions.json")
# 决定数值/剧情解析结果的原版文件 (任一变了 parse_data/import_content 的偏移就可能错位); 原图目录里 Misc/ 下同名文件字节相同
KEY_FILES = ["Misc/Item_dat.dat", "Misc/KMAN_STA.DAT", "Misc/KMAN_LEV.DAT", "Misc/Mag_dat.DAT", "Misc/Man_base.dat",
             "Misc/MAG_OPP.DAT", "Misc/STA_SCR.DAT", "Misc/TER_EFF.DAT"]


def ci_path(root, rel):
    """大小写不敏感地找 root 下的 rel (原版文件名大小写不统一); 找不到返回 None。"""
    p = root
    for part in rel.split("/"):
        try:
            hit = next((e for e in os.listdir(p) if e.lower() == part.lower()), None)
        except OSError:
            return None
        if hit is None:
            return None
        p = os.path.join(p, hit)
    return p


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fingerprint(root):
    """原版游戏目录或原图目录 -> {关键文件: {size, sha256}, exe: {...}, stages/towns 数}; 缺的文件记 None。"""
    files = {}
    for rel in KEY_FILES:
        p = ci_path(root, rel)
        files[rel] = {"size": os.path.getsize(p), "sha256": sha256_file(p)} if p else None
    exe = ci_path(root, "Swordman.exe")
    return {"files": files,
            "exe": {"size": os.path.getsize(exe), "sha256": sha256_file(exe)} if exe else None,
            "stage_dirs": len([d for d in os.listdir(os.path.join(root, "Stage"))]) if ci_path(root, "Stage") else None}


def identify_version(fp):
    """与 known_versions.json 比对: 返回 (版本 id 或 None, 说明)。"""
    try:
        with open(KNOWN_VERSIONS, encoding="utf-8") as f:
            known = json.load(f)["versions"]
    except (OSError, ValueError, KeyError):
        return None, "没有版本清单 %s" % os.path.relpath(KNOWN_VERSIONS, REPO)
    got = {k: (v or {}).get("sha256") for k, v in fp["files"].items()}
    for ver in known:
        want = {k: v["sha256"] for k, v in ver["files"].items()}
        if all(got.get(k) == h for k, h in want.items()):
            note = ""
            exes = ver.get("exe_sha256", [])
            if fp["exe"] and exes and fp["exe"]["sha256"] not in exes:
                note = " (Swordman.exe 哈希不在清单里, 可能是破解/补丁版, 不影响数据解析)"
            return ver["id"], "关键数据文件与 %s 一致%s" % (ver["id"], note)
    bad = [k for k, h in got.items() if h is None]
    return None, ("缺关键文件: " + ", ".join(bad)) if bad else "关键数据文件哈希与清单里的版本都不一致"


# ---------------- 预检 ----------------
# 阶段 -> 需要的外部依赖; 估算磁盘占用 (GB, 含中间文件, 2026-10 实测量级: 原图 1.1GB、hd4x 0.6GB、全部 pck 约 2GB)
STAGE_NEEDS = {
    "export": {"py": ["PIL", "numpy"], "ffmpeg": ["libx264"], "gb": 3},
    "data": {"gb": 0.2},
    "content": {"py": ["PIL"], "gb": 0.2},
    "hd": {"py": ["PIL", "numpy", "cv2"], "esrgan": True, "gb": 3},
    "movie": {"ffmpeg": ["libtheora", "libvorbis"], "gb": 1},
    "hdmovie": {"ffmpeg": ["libtheora", "libvorbis"], "esrgan": True, "gb": 8},
    "icon": {"py": ["PIL"], "gb": 0},
    "pack": {"godot": True, "gb": 3},
    "verify": {"godot": True, "gb": 0.3},
}


def ffmpeg_encoders():
    ff = shutil.which("ffmpeg")
    if not ff:
        return None
    try:
        out = subprocess.run([ff, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.TimeoutExpired):
        return set()
    return {m.group(1) for m in re.finditer(r"^ [VAS][\w.]+ +(\S+)", out, re.M)}


def esrgan_path():
    return os.path.join(HERE, "realesrgan", "realesrgan-ncnn-vulkan" + (".exe" if os.name == "nt" else ""))


def preflight(a, todo):
    """返回 (errors, warnings, info)。errors 非空则不开跑。只检查 todo 里的阶段用得到的东西。"""
    errs, warns, info = [], [], {}
    if sys.version_info < (3, 10):
        errs.append("需要 Python >= 3.10 (当前 %s)" % sys.version.split()[0])
    need = {k: set() for k in ("py", "ffmpeg")}
    esrgan = godot = False
    gb = 0.0
    for st in todo:
        n = STAGE_NEEDS.get(st, {})
        need["py"] |= set(n.get("py", []))
        need["ffmpeg"] |= set(n.get("ffmpeg", []))
        esrgan |= bool(n.get("esrgan"))
        godot |= bool(n.get("godot"))
        gb += n.get("gb", 0)
    for mod in sorted(need["py"]):
        try:
            __import__(mod)
        except ImportError:
            errs.append("缺 Python 包 %s: pip install -r tools/requirements-dev.txt (Pillow、numpy、opencv)" % {"PIL": "Pillow", "cv2": "opencv-python-headless"}.get(mod, mod))
    if need["ffmpeg"] or "export" in todo:
        enc = ffmpeg_encoders()
        if enc is None:
            errs.append("找不到 ffmpeg (Windows: winget install Gyan.FFmpeg; Linux: apt install ffmpeg), 需要 %s" % "/".join(sorted(need["ffmpeg"])))
        else:
            miss = sorted(e for e in need["ffmpeg"] if e not in enc)
            if miss:
                errs.append("ffmpeg 缺编码器 %s (换带 libtheora/libvorbis/libx264 的构建)" % ", ".join(miss))
    if godot:
        g = paths.godot_exe()
        if not os.path.isfile(g):
            errs.append(paths.missing_godot_hint())
        else:
            try:
                ver = subprocess.run([g, "--version"], capture_output=True, text=True, timeout=60).stdout.strip().splitlines()[0]
            except (OSError, IndexError, subprocess.TimeoutExpired):
                ver = ""
            info["godot"] = ver
            if not ver.startswith(paths.EXPECT_GODOT + "."):
                errs.append("Godot 版本 '%s' 不是 %s (打包/校验的结果可能与基线不一致; 设 TDJ_GODOT 指向 %s)" % (ver, paths.EXPECT_GODOT, paths.EXPECT_GODOT))
    if esrgan:
        if not os.path.isfile(esrgan_path()):
            errs.append("AI 阶段 (hd/hdmovie) 需要 %s: 先跑 tools/setup.sh 下载 Real-ESRGAN (或加 --no-ai 跳过 AI 高清)" % os.path.relpath(esrgan_path(), REPO))
        if not any(os.path.exists(p) for p in ("/dev/dri", "/usr/share/vulkan", "/etc/vulkan")) and os.name != "nt":
            warns.append("没找到 Vulkan 驱动痕迹 (/usr/share/vulkan), AI 放大需要 Vulkan 显卡 (vulkaninfo 能看到设备)")
    if "export" in todo:
        if not a.game:
            errs.append("export 阶段需要 --game <原版游戏目录>")
        elif not os.path.isdir(os.path.join(a.game, "Sprite")):
            errs.append("%s 不像原版游戏目录 (没有 Sprite/)" % a.game)
    # 磁盘: 取 原图目录/仓库/输出目录 所在的卷, 同一卷合并计
    vols = {}
    for label, d in (("原图目录", a.original), ("仓库", REPO), ("资源包输出", a.out)):
        probe = d
        while probe and not os.path.exists(probe):
            probe = os.path.dirname(probe)
        try:
            vols.setdefault(os.stat(probe or ".").st_dev, [probe or ".", []])[1].append(label)
        except OSError:
            pass
    free_info = []
    for dev, (probe, labels) in vols.items():
        free = shutil.disk_usage(probe).free / 1e9
        free_info.append("%s %.0fGB 可用" % ("+".join(labels), free))
        if free < gb:
            errs.append("磁盘空间不足: %s 所在卷只有 %.1f GB, 本次阶段估算需要 %.1f GB" % ("+".join(labels), free, gb))
    info["disk"] = "; ".join(free_info) + " (估算需要 %.1f GB)" % gb
    # 原版版本
    probe_dir = a.game if (a.game and os.path.isdir(a.game)) else (a.original if os.path.isfile(os.path.join(a.original, "index.json")) else None)
    if probe_dir and os.path.isdir(probe_dir):
        fp = fingerprint(probe_dir)
        vid, note = identify_version(fp)
        info["original_version"] = {"id": vid, "note": note, "checked": probe_dir, "files": {k: (v or {}).get("sha256", "")[:12] for k, v in fp["files"].items()}}
        if vid is None:
            msg = "原版版本未验证: %s。本项目以官方 1.3 验证, 其他版本数据解析可能错位; 确认无误可加 --allow-unknown-version" % note
            if "export" in todo and not a.allow_unknown_version:
                errs.append(msg)
            else:
                warns.append(msg)
    return errs, warns, info


# ---------------- 清单 (build_manifest.json) ----------------
def git_head():
    try:
        r = subprocess.run(["git", "-C", REPO, "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=10)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


class Manifest:
    def __init__(self, logdir, args, todo):
        self.path = os.path.join(logdir, "build_manifest.json")
        self.d = {"started": datetime.datetime.now().isoformat(timespec="seconds"), "git_head": git_head(), "python": sys.version.split()[0],
                  "platform": sys.platform, "args": args, "stages": {s: {"status": "pending"} for s in todo}, "info": {}}

    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(self.d, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)

    def stage(self, name, **kw):
        self.d["stages"][name].update(kw)
        self.save()


BUILD_INFO = {}  # main() 填: 写进 BUILD.json (pack 阶段)


def build_json_text(orig):
    """BUILD.json: 这批资源包由什么生成 (不含任何原版内容, 只有哈希前缀与版本 id)。"""
    info = dict(BUILD_INFO)
    if "original_version" not in info and os.path.isfile(os.path.join(orig, "index.json")):
        fp = fingerprint(orig)
        vid, note = identify_version(fp)
        info["original_version"] = {"id": vid, "note": note, "files": {k: (v or {}).get("sha256", "")[:12] for k, v in fp["files"].items()}}
    info.setdefault("built", datetime.datetime.now().isoformat(timespec="seconds"))
    info.setdefault("git_head", git_head())
    return json.dumps(info, ensure_ascii=False, indent=1) + "\n"


# ---------------- 打包 (build_windows.py 也用) ----------------
def original_files(orig):
    """原版资源: index.json 登记的、运行时会读的文件。"""
    items = [(os.path.join(orig, "index.json"), "res://common/index.json")]
    ogg, n = audio_pack.convert_all(orig)   # 音效 wav (130MB) 转 Ogg Vorbis 放进包 (约 30%); 原版目录里的 wav 不动, 引擎先找 wav 再找 ogg
    if n:
        print("  音效转 ogg: 本次转了 %d 个" % n, flush=True)
    with open(os.path.join(orig, "index.json"), encoding="utf-8") as f:
        for rel in json.load(f):
            if rel.lower().endswith(NOT_RUNTIME):
                continue
            if rel in ogg:
                items.append((ogg[rel], "res://common/" + rel[:-4] + ".ogg"))
            else:
                items.append((os.path.join(orig, rel), "res://common/" + rel))
    missing = [r for s, r in items if not os.path.isfile(s)]
    if missing:  # 索引登记了但磁盘上没有 (导出不完整/被删): 打包前就报, 不等 PCKPacker 中途失败
        die("原图目录缺 %d 个文件 (index.json 登记了): %s%s (重跑 export 阶段)" % (len(missing), ", ".join(missing[:3]), " ..." if len(missing) > 3 else ""))
    return items


def tree_files(src, prefix, only_ext=None):
    """目录树 -> [(源文件, res:// 路径)]。"""
    src = os.path.realpath(src)
    items = []
    for dp, _, fns in os.walk(src):
        for fn in sorted(fns):
            if only_ext and not fn.endswith(only_ext):
                continue
            rel = os.path.relpath(os.path.join(dp, fn), src).replace(os.sep, "/")
            items.append((os.path.join(dp, fn), prefix + "/" + rel))
    return items


def face_hk_dir():
    """港漫头像目录 (含 Face/<目录>/tN.webp): 环境变量 TDJ_FACE_HK, 否则 <仓库>/.work/face_hk; 没有返回 ""。素材是 AI 重绘的衍生物, 不进仓库。"""
    d = os.environ.get("TDJ_FACE_HK") or os.path.join(REPO, ".work", "face_hk")
    return d if os.path.isdir(os.path.join(d, "Face")) else ""


# 发布目录: resource/ 必备资源 (公用 + hd 或 classic 二选一), mod/ 可选叠加包。名字与 game/engine/core/res_packs.gd 的 RESOURCE 一致
RESOURCE_PACKS = ["resource/%s.pck" % n for n in ("common_assets", "common_story", "classic_images", "classic_movies", "hd_images", "hd_movies")]
# 旧版本用过的包名/平铺位置: 重新打包时顺手清掉, 免得发布目录里留着过期的包
OLD_PACK_NAMES = ["original.pck", "original_img.pck", "content.pck", "movie.pck", "hd.pck", "hd_movie.pck", "face_e2.pck"]


def pack_lists(orig, hd=True):
    """资源包 (相对发布目录的路径, 如 resource/hd_images.pck) -> 文件清单; 与 game/engine/core/res_packs.gd 的包名/挂载路径一一对应。hd=False 不出 hd_images / hd_movies。"""
    content = [it for it in tree_files(os.path.join(REPO, "game", "content", "tdj"), "res://content/tdj")
               if not it[0].endswith((".import", ".uid"))]
    orig_items = original_files(orig)
    lists = {
        "resource/common_assets.pck": orig_items,
        "resource/common_story.pck": content,
        "resource/classic_movies.pck": tree_files(os.path.join(REPO, "game", "classic", "movies"), "res://classic/movies", only_ext=".ogv"),
    }
    if hd:
        hd_items = [it for it in tree_files(paths.hd4x_dir(), "res://hd")
                    if it[0].endswith((".webp", ".png", ".ogv", "hd4x.json")) and "/_test/" not in it[1]]  # 只收运行时读的贴图、AI 高清过场与清单, 不带实验目录/杂物
        lists["resource/hd_images.pck"] = [it for it in hd_items if not it[0].endswith(".ogv")]        # AI 高清贴图 + 清单
        movies = [it for it in hd_items if it[0].endswith(".ogv")]
        if movies:
            lists["resource/hd_movies.pck"] = movies                                      # AI 高清过场/法术视频 (1280x800), 单独一个包: 没有它就播 classic_movies 的原版
    rep = original_split.replaceable(orig, os.path.join(paths.hd4x_dir(), "hd4x.json")) if hd else set()
    if rep:   # 有 AI 高清: 高清包里有高清版的原版 PNG 拆成 classic_images.pck (装了 hd_images 可不放), common_assets 里放预算好的 used_rects.json
        core, img = original_split.split(orig_items, rep)
        side = os.path.join(REPO, ".work", "used_rects.json")
        os.makedirs(os.path.dirname(side), exist_ok=True)
        with open(side, "w", encoding="utf-8", newline="\n") as f:
            json.dump(original_split.used_rects(orig, rep), f, ensure_ascii=False, separators=(",", ":"))
        lists["resource/common_assets.pck"] = core + [(side, "res://common/used_rects.json")]
        lists["resource/classic_images.pck"] = img
    fhk = face_hk_dir()
    if fhk:   # 可选 mod: 港漫头像, 路径 res://mod/face_hk/ (与 hd_images 的 hd4x 互不覆盖; 设定里选「港漫」才读)
        lists["mod/face_hk.pck"] = [it for it in tree_files(os.path.join(fhk, "Face"), "res://mod/face_hk/Face") if it[0].endswith(".webp")]
    return lists


def pack_label(out):
    """打印用的包名: resource/xxx.pck、mod/xxx.pck (带上一级目录)"""
    parent = os.path.basename(os.path.dirname(out))
    return (parent + "/" if parent in ("resource", "mod") else "") + os.path.basename(out)


def pack(godot, out, items):
    """用 tools/release/pack_pck.gd (PCKPacker) 把 items 原样打成 out。"""
    lst = out + ".list"
    with open(lst, "w", encoding="utf-8", newline="\n") as f:
        for src, res in items:
            f.write("%s\t%s\n" % (os.path.abspath(src).replace("\\", "/"), res))
    tmp = out + ".tmp"  # 先写临时文件, 成功再替换: 失败不留半个包, 也不覆盖上一次的好包
    r = subprocess.run([godot, "--headless", "--path", os.path.join(REPO, "game").replace("\\", "/"), "--script",
                        os.path.join(HERE, "release", "pack_pck.gd").replace("\\", "/"), "--", "--list=" + lst, "--out=" + tmp],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", env=paths.env_for_godot())
    os.remove(lst)
    if r.returncode or not os.path.isfile(tmp):
        if os.path.isfile(tmp):
            os.remove(tmp)
        die("打包失败 %s:\n%s" % (out, r.stdout + r.stderr))
    os.replace(tmp, out)
    print("  %-26s %6d 个文件  %5.0f MB" % (pack_label(out), len(items), os.path.getsize(out) / 1048576), flush=True)


def pack_all(out_dir, orig=None, hd=None):
    """把现有产物打成 out_dir 下的资源包; 返回 {包名: 清单}。缺关键文件时报错。
    hd: None = 有 AI 高清产物 (hd4x/ 下有文件) 就打 hd_images.pck; False = 不打 (并删掉 out_dir 里旧的)。"""
    godot = paths.godot_exe()
    if not os.path.isfile(godot):
        die(paths.missing_godot_hint())
    orig = orig or paths.original_dir()
    if not os.path.isfile(os.path.join(orig, "index.json")):
        die("原图目录没有 index.json: %s (先跑 export 阶段)" % orig)
    if hd is None:
        hd = bool(tree_files(paths.hd4x_dir(), "res://hd")) if os.path.isdir(paths.hd4x_dir()) else False
    lists = pack_lists(orig, hd)
    must = {"resource/common_assets.pck": "res://common/index.json", "resource/common_story.pck": "res://content/tdj/textures.json",
            "resource/classic_movies.pck": "res://classic/movies/Movie/Logo.ogv"}
    miss = [res for name, res in must.items() if name in lists and res not in {r for _, r in lists[name]}]
    if hd and "resource/hd_movies.pck" not in lists and any(f.endswith(".ogv") for _, _, fs in os.walk(paths.hd4x_dir()) for f in fs):
        miss.append("hd_movies.pck 里没有 AI 高清过场 (hd4x/ 下有 .ogv, 打包白名单漏了?)")
    if miss:
        die("缺少: %s (对应阶段没跑?)" % ", ".join(miss))
    os.makedirs(out_dir, exist_ok=True)
    bj = os.path.join(out_dir, "BUILD.json")  # 生成信息 (版本哈希前缀/git/时间), 同时进 common_story.pck, 引擎与玩家都能查
    with open(bj, "w", encoding="utf-8", newline="\n") as f:
        f.write(build_json_text(orig))
    lists["resource/common_story.pck"].append((bj, "res://content/tdj/BUILD.json"))
    # 这次不出的必备资源包要删掉旧的 (旧版本的平铺布局、旧名字也一并清掉); mod/ 里的包是可选的, 本次没生成就保留原样
    for stale in OLD_PACK_NAMES + [n for n in RESOURCE_PACKS if n not in lists]:
        if os.path.isfile(os.path.join(out_dir, stale)):
            os.remove(os.path.join(out_dir, stale))
    if not hd:
        print("  (不打 hd_images / hd_movies: 没有 AI 高清产物; 头像/地图等显示原图)")
    if "mod/face_hk.pck" not in lists and os.path.isfile(os.path.join(out_dir, "mod", "face_hk.pck")):
        print("  (保留 out_dir 里已有的 mod/face_hk.pck)")
    for name, items in lists.items():
        dst = os.path.join(out_dir, *name.split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        pack(godot, dst, items)
    return lists


# ---------------- 各阶段 ----------------
EXPORT_STAMP = ".export_stamp.json"  # 导出完成戳: 写在原图目录里, 内容 = 导出时原版关键文件的指纹


def export_done(a):
    """export 是否已完整完成: index.json 在 (make_index 是最后一步, 半截导出没有它)、登记的文件都在磁盘、
    导出戳 (若有) 与当前 --game 的指纹一致。返回 (是否, 说明)。"""
    idx = os.path.join(a.original, "index.json")
    if not os.path.isfile(idx):
        return False, "原图目录没有 index.json (没导出过, 或上次导出中途失败)"
    try:
        with open(idx, encoding="utf-8") as f:
            files = json.load(f)
    except ValueError:
        return False, "index.json 损坏"
    miss = [r for r in files if not os.path.isfile(os.path.join(a.original, r))]
    if miss:
        return False, "索引登记的 %d 个文件不在磁盘上 (如 %s)" % (len(miss), miss[0])
    stamp = os.path.join(a.original, EXPORT_STAMP)
    if os.path.isfile(stamp):
        try:
            with open(stamp, encoding="utf-8") as f:
                old = json.load(f)
        except ValueError:
            return False, "导出戳损坏"
        if a.game and os.path.isdir(a.game):
            now = {k: (v or {}).get("sha256") for k, v in fingerprint(a.game)["files"].items()}
            if now != old.get("files"):
                return False, "当前原版游戏与上次导出时的关键文件不一致"
        return True, "%d 个文件齐全, 导出戳 %s" % (len(files), old.get("time", "?"))
    return True, "%d 个文件齐全 (没有导出戳, 按索引完整性视为已完成)" % len(files)


def stage_export(a, env):
    if not a.game:
        die("export 阶段需要 --game <原版游戏目录>")
    if not os.path.isdir(os.path.join(a.game, "Sprite")):
        die("%s 不像原版游戏目录 (没有 Sprite/)" % a.game)
    done, why = export_done(a)
    if done and not a.force:
        print("  export 已完成 (%s), 跳过; 要重导加 --force" % why)
        return "skipped"
    print("  export 需要运行: %s" % why)
    os.makedirs(a.original, exist_ok=True)
    for f in (os.path.join(a.original, "index.json"), os.path.join(a.original, EXPORT_STAMP)):
        if os.path.isfile(f):
            os.remove(f)  # 先去掉完成标志: 中途失败后 export_done 一定判为未完成
    py("assets/original/export_original.py", "--game", a.game, "-o", a.original, env=env)
    py("assets/original/make_index.py", a.original, env=env)
    with open(os.path.join(a.original, EXPORT_STAMP), "w", encoding="utf-8", newline="\n") as f:
        json.dump({"time": datetime.datetime.now().isoformat(timespec="seconds"), "git_head": git_head(),
                   "files": {k: (v or {}).get("sha256") for k, v in fingerprint(a.game)["files"].items()}}, f, ensure_ascii=False, indent=1)


def stage_data(a, env):
    py("assets/parse_data.py", "--root", REPO, env=env)
    py("assets/export_text.py", a.original, os.path.join(REPO, "data", "emsg"), env=env)  # 目标显式给绝对路径 (默认值是相对当前目录, 不在仓库根运行会写到别处)


def stage_content(a, env):
    py("assets/decompile_events.py", env=env)
    py("assets/import_content.py", env=env)
    py("assets/make_locale.py", env=env)       # 繁体叠加层 game/content/tdj/locale/hant (原版 Big5 原文与简体逐字段比对)
    py("assets/make_hant_text.py", env=env)    # 手写文字 (界面文案/枚举显示名) 转繁体叠加层
    py("assets/texture_classes.py", env=env)


def stage_hd(a, env):
    py("assets/hd_pipeline.py", "--src", a.original, "--out", paths.hd4x_dir(), env=env)


def stage_movie(a, env):
    py("assets/make_godot_movies.py", env=env)


def stage_hdmovie(a, env):
    py("assets/movie_hd.py", "--out", paths.hd4x_dir(), *(["--game", a.game] if a.game else []), env=env)


def stage_icon(a, env):
    exe = ""
    for name in ("Swordman.exe", "SWORDMAN.EXE"):
        if a.game and os.path.isfile(os.path.join(a.game, name)):
            exe = os.path.join(a.game, name)
    if not exe:
        print("  没有 --game 或找不到 Swordman.exe, 跳过 (导出时用标题图占位)")
        return
    py("assets/make_icon.py", exe, os.path.join(REPO, "game", "assets", "icon.ico"), env=env)


def stage_pack(a, env):
    paths.ensure_godot_imported()
    pack_all(a.out, a.original, hd=False if a.no_ai else None)
    if getattr(a, "manifest", None):
        a.manifest.save()
        shutil.copy2(a.manifest.path, os.path.join(a.out, "build_manifest.json"))  # 随资源包留一份 (此刻 pack 阶段还是 running 状态)


def stage_verify(a, env):
    """产物校验: 任何一项失败都退出非 0 (check_* 缺产物时会自己 SKIP 并返回 0, 所以这里先确认产物在, 不让缺东西的 verify 假通过)。"""
    paths.ensure_godot_imported()
    miss = paths.missing("original", "data", "content")
    if miss:
        die("verify 需要先有: " + "; ".join(miss))
    py("checks/content_schema.py", env=env)
    py("checks/check_content.py", env=env)
    py("checks/check_items.py", env=env)
    need = [n for n in ("common_assets.pck", "common_story.pck") if not os.path.isfile(os.path.join(a.out, "resource", n))]
    if need:
        die("verify 的冒烟测试要用资源包: %s 里缺 %s (先跑 pack 阶段, 或 --out 指向包目录)" % (a.out, ", ".join(need)))
    tmp = os.path.join(a.logdir, "verify_smoke")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(os.path.join(tmp, "home"))
    rec = os.path.join(tmp, "smoke.jsonl")
    genv = paths.env_for_godot()
    genv.update(XDG_DATA_HOME=os.path.join(tmp, "home"), APPDATA=os.path.join(tmp, "home"), XDG_CONFIG_HOME=os.path.join(tmp, "home"))
    cmd = [paths.godot_exe(), "--headless", "--fixed-fps", "25", "--path", os.path.join(REPO, "game").replace("\\", "/"), "--", "--packs=" + a.out,
           "--scene=stage0", "--fast", "--autoplay", "--god", "--gfx=orig", "--skip-movies", "--auto-exit", "--seed=20260403",
           "--regress-out=" + rec, "--regress-stop=stage_end:1", "--regress-max-frames=200000"]
    print("  冒烟: 用资源包 %s 无头跑第 0 关到过关" % a.out, flush=True)
    try:
        r = subprocess.run(cmd, env=genv, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
    except subprocess.TimeoutExpired:
        die("冒烟超时 (900 秒)")
    with open(os.path.join(a.logdir, "verify_smoke.log"), "w", encoding="utf-8") as f:
        f.write(r.stdout + r.stderr)
    last = ""
    if os.path.isfile(rec):
        with open(rec, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    last = line
    errs = [l for l in (r.stdout + r.stderr).splitlines() if l.startswith(("SCRIPT ERROR", "启动失败"))]
    if "stage_end" not in last or errs:
        die("冒烟失败: 最后一条记录 %s; 错误 %s (日志 %s)" % (last.strip()[:120] or "(无)", errs[:3], os.path.join(a.logdir, "verify_smoke.log")))
    print("  冒烟通过: 第 0 关到达 stage_end")


def describe(a, todo):
    out = []
    for st in todo:
        if st == "export":
            if not a.game:
                out.append("export: 需要 --game")
            else:
                done, why = export_done(a)
                out.append("export: %s" % ("跳过 (%s)" % why if done and not a.force else "将运行 (%s)" % why))
        else:
            out.append("%s: 将运行 (估算磁盘 %.1f GB)" % (st, STAGE_NEEDS.get(st, {}).get("gb", 0)))
    return out


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--game", help="原版游戏目录 (含 Sprite/ Stage/ Swordman.exe 等)")
    ap.add_argument("--original", help="原图目录 (默认 tools/paths.py 的配置, 未配置则 <仓库>/original)")
    ap.add_argument("--out", default=os.path.join(REPO, "dist", "assets"), help="资源包输出目录")
    ap.add_argument("--only", nargs="+", choices=STAGES, help="只跑这些阶段")
    ap.add_argument("--skip", nargs="+", choices=STAGES, default=[], help="跳过这些阶段")
    ap.add_argument("--no-ai", action="store_true", help="不跑 AI 高清 (= --skip hd hdmovie), 不出 hd_images.pck")
    ap.add_argument("--check", action="store_true", help="只做环境预检 (退出码 0 = 通过)")
    ap.add_argument("--dry-run", action="store_true", help="预检并打印各阶段将做什么, 不执行")
    ap.add_argument("--force", action="store_true", help="export 阶段即使已完成也重导")
    ap.add_argument("--allow-unknown-version", action="store_true", help="原版关键文件与 known_versions.json 对不上时仍继续 (数据解析可能错位)")
    ap.add_argument("--skip-check", action="store_true", help="不做开跑前的自动预检")
    ap.add_argument("--log", help="日志目录 (默认 <仓库>/.work/build_assets/<时间戳>)")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--fingerprint", metavar="目录", help="打印该原版目录的关键文件哈希 (往 tools/assets/original/known_versions.json 加新版本时用), 然后退出")
    a = ap.parse_args(argv)
    if a.list:
        print("\n".join(STAGES))
        return 0
    if a.fingerprint:
        print(json.dumps(fingerprint(a.fingerprint), ensure_ascii=False, indent=1))
        return 0
    if not a.original:  # 有配置 (TDJ_ORIGINAL / dev_env.json) 或已有目录就用它, 否则新建 <仓库>/original
        cfg = paths.original_dir()
        a.original = cfg if os.path.isdir(cfg) else os.path.join(REPO, "original")
    a.original = os.path.abspath(a.original)
    a.out = os.path.abspath(a.out)
    if a.game:
        a.game = os.path.abspath(a.game)
    env = dict(os.environ, TDJ_ORIGINAL=a.original)  # 各阶段工具经 paths.original_dir() 读到同一个原图目录
    if a.no_ai:
        a.skip += AI_STAGES
    todo = [s for s in (a.only or STAGES) if s not in a.skip]

    # 预检 (--check / --dry-run / 默认开跑前)
    if a.check or a.dry_run or not a.skip_check:
        errs, warns, info = preflight(a, todo)
        print("预检 (阶段 %s):" % " ".join(todo))
        for k in ("godot", "disk"):
            if k in info:
                print("  %s: %s" % (k, info[k]))
        if "original_version" in info:
            print("  原版版本: %s (%s)" % (info["original_version"]["id"] or "未识别", info["original_version"]["note"]))
        for w in warns:
            print("  警告: " + w)
        for e in errs:
            print("  错误: " + e)
        if errs:
            print("预检未通过 (%d 项)" % len(errs), file=sys.stderr)
            return 1
        print("预检通过")
    else:
        info = {}
    if a.check:
        return 0
    if a.dry_run:
        print("\n".join("  " + l for l in describe(a, todo)))
        return 0

    # 日志与清单
    a.logdir = os.path.abspath(a.log or os.path.join(REPO, ".work", "build_assets", time.strftime("%Y%m%d-%H%M%S")))
    os.makedirs(a.logdir, exist_ok=True)
    main_log = open(os.path.join(a.logdir, "build.log"), "w", encoding="utf-8", newline="\n")
    _extra_files.append(main_log)
    sys.stdout, sys.stderr = Tee(sys.__stdout__, _extra_files), Tee(sys.__stderr__, _extra_files)
    a.manifest = Manifest(a.logdir, argv, todo)
    a.manifest.d["info"] = info
    BUILD_INFO.update({"git_head": a.manifest.d["git_head"], "built": a.manifest.d["started"], "original_version": {k: v for k, v in (info.get("original_version") or {}).items() if k != "checked"},  # checked 是本机路径, 不进包
                       "godot": info.get("godot"), "stages": todo})
    a.manifest.save()
    print("日志目录 %s" % a.logdir)
    print("原图目录 %s, 阶段 %s" % (a.original, " ".join(todo)), flush=True)
    rc = 0
    for s in todo:
        t0 = time.time()
        print("== %s" % s, flush=True)
        stage_log = open(os.path.join(a.logdir, s + ".log"), "w", encoding="utf-8", newline="\n")
        _extra_files.append(stage_log)
        a.manifest.stage(s, status="running", started=datetime.datetime.now().isoformat(timespec="seconds"))
        status = "done"
        try:
            r = globals()["stage_" + s](a, env)
            if r == "skipped":
                status = "skipped"
        except SystemExit as e:  # die(): 记入清单再退出
            status = "failed"
            rc = e.code if isinstance(e.code, int) and e.code else 1
        finally:
            _extra_files.remove(stage_log)
            stage_log.close()
        dt = time.time() - t0
        a.manifest.stage(s, status=status, seconds=round(dt, 1), log=s + ".log")
        print("   %s %s %.0fs" % (s, {"done": "完成", "skipped": "跳过", "failed": "失败"}[status], dt), flush=True)
        if status == "failed":
            a.manifest.d["finished"] = "failed at " + s
            a.manifest.save()
            print("构建失败于 %s; 日志 %s; 清单 %s" % (s, os.path.join(a.logdir, s + ".log"), a.manifest.path), file=sys.stderr)
            return rc
    a.manifest.d["finished"] = datetime.datetime.now().isoformat(timespec="seconds")
    a.manifest.save()
    print("全部完成; 清单 %s" % a.manifest.path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
