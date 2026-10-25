# SPDX-License-Identifier: GPL-3.0-only
"""开发环境路径的统一来源 (Python 工具与 Godot 的 Assets 读同一套规则)。

每一项按优先级解析: 环境变量 > tools/dev_env.json (不入库, 模板 tools/dev_env.example.json) > 默认位置。
  original   原版资源 (含 index.json)      TDJ_ORIGINAL   默认 <仓库>/original, 其次并列的 ../tdj-original
  hd4x       4 倍高清贴图                  TDJ_HD4X       默认 <仓库>/hd4x
  godot      Godot 4.7.2 可执行文件        TDJ_GODOT      默认 <仓库>/tools/godot/godot[.exe], 其次 PATH 里的 godot
  python     给 Godot 测试调 Python 用     TDJ_PYTHON     默认当前解释器
dev_env.json 里的相对路径相对仓库根。不依赖符号链接, Windows 无需管理员权限。
命令行: python tools/paths.py      打印解析结果并检查是否存在 (排查环境用)
"""
import json
import os
import shutil
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(REPO, "tools", "dev_env.json")
IS_WINDOWS = os.name == "nt"
EXPECT_GODOT = "4.7.2"

_ENV_NAMES = {"original": "TDJ_ORIGINAL", "hd4x": "TDJ_HD4X", "godot": "TDJ_GODOT", "python": "TDJ_PYTHON"}


def _config():
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        print("警告: 读不了 %s (%s), 已忽略" % (CONFIG_FILE, e), file=sys.stderr)
        return {}


def _configured(key):
    """环境变量或 dev_env.json 里显式配置的值 (绝对路径), 没配返回 None。"""
    v = os.environ.get(_ENV_NAMES[key]) or _config().get(key)
    if not v:
        return None
    return os.path.normpath(os.path.join(REPO, os.path.expanduser(str(v))))


def relpath(p, base=None):
    """打印用的相对路径; Windows 跨盘符 (临时目录在 C:, 仓库在 G: 之类) os.path.relpath 会抛
    ValueError: path is on mount ..., 此时原样返回绝对路径。"""
    try:
        return os.path.relpath(p, REPO if base is None else base)
    except ValueError:
        return p


def original_dir():
    c = _configured("original")
    if c:
        return c
    local = os.path.join(REPO, "original")
    return local if os.path.isdir(local) else os.path.normpath(os.path.join(REPO, "..", "tdj-original"))


def hd4x_dir():
    return _configured("hd4x") or os.path.join(REPO, "hd4x")


def godot_exe():
    """Godot 可执行文件; 找不到返回默认位置 (调用方用 missing_godot_hint() 提示)。
    Windows 上跑无头测试/回归要用 *_console.exe (GUI 版不把输出写到管道)。"""
    c = _configured("godot") or os.environ.get("CI_GODOT")
    if c:
        return os.path.normpath(c)
    local = os.path.join(REPO, "tools", "godot", "godot.exe" if IS_WINDOWS else "godot")
    if os.path.isfile(local):
        return local
    return shutil.which("godot") or local


def python_exe():
    return _configured("python") or sys.executable or "python"


def has_original():
    return os.path.isfile(os.path.join(original_dir(), "index.json"))


def data_dir():
    """data/*.json (原版数值表与对白的解出物, build_assets 的 data 阶段生成)"""
    return os.path.join(REPO, "data")


def content_dir():
    """原版内容包 game/content/tdj (build_assets 的 content 阶段生成)"""
    return os.path.join(REPO, "game", "content", "tdj")


def has_data():
    return os.path.isfile(os.path.join(data_dir(), "items.json"))


def has_content():
    return os.path.isfile(os.path.join(content_dir(), "manifest.json"))


def has_hd4x():
    return os.path.isfile(os.path.join(hd4x_dir(), "hd4x.json"))


_KIND = {"original": (has_original, "原版资源 (original/index.json)", "build_assets 的 export 阶段"),
         "data": (has_data, "data/*.json", "build_assets 的 data 阶段"),
         "content": (has_content, "内容包 game/content/tdj", "build_assets 的 content 阶段"),
         "hd4x": (has_hd4x, "高清贴图 hd4x/", "build_assets 的 hd 阶段")}


def missing(*kinds):
    """缺哪些产物 (kinds: original / data / content / hd4x), 返回人读的说明列表。"""
    return ["%s (%s 生成)" % (_KIND[k][1], _KIND[k][2]) for k in kinds if not _KIND[k][0]()]


def require(tool, *kinds):
    """工具开头调用: 缺产物时打印友好的 SKIP 并返回退出码, 都在返回 None。
    缺产物默认算跳过 (退出码 0, 输出以 'SKIP:' 开头, 便于 CI/人识别); 环境变量 CI_REQUIRE_ORIGINAL=1 时算失败 (退出码 1)。
    用法:  rc = paths.require("check_content", "original", "content");  if rc is not None: return rc"""
    miss = missing(*kinds)
    if not miss:
        return None
    strict = os.environ.get("CI_REQUIRE_ORIGINAL") == "1"
    print("%s: %s 需要 %s; 没有 -- 先 python tools/build_assets.py --game <原版游戏目录> (见 README 获取游戏资源)" % ("FAIL" if strict else "SKIP", tool, ", ".join(miss)))
    return 1 if strict else 0


def missing_original_hint():
    return ("找不到原版资源 (已找 %s)。设环境变量 TDJ_ORIGINAL 或在 tools/dev_env.json 写 \"original\" 指向含 index.json 的目录, "
            "见 docs/Windows开发.md" % original_dir())


def missing_godot_hint():
    return ("找不到 Godot: %s。装 Godot %s 后设环境变量 TDJ_GODOT 或在 tools/dev_env.json 写 \"godot\" "
            "(Windows 用 *_console.exe), 见 docs/Windows开发.md" % (godot_exe(), EXPECT_GODOT))


def ensure_godot_imported(godot=None):
    """Godot 工程从没打开过 (新 clone / 资源工具包里, 没有 game/.godot/global_script_class_cache.cfg) 时先 --import 一次:
    否则 class_name 没注册, 无头运行游戏或脚本会报「Identifier ... not declared」。已导入过则什么也不做。"""
    if os.path.isfile(os.path.join(REPO, "game", ".godot", "global_script_class_cache.cfg")):
        return
    import subprocess
    print("== 首次使用: 导入 Godot 工程 (godot --import, 约半分钟)", flush=True)
    subprocess.run([godot or godot_exe(), "--headless", "--path", os.path.join(REPO, "game"), "--import"],
                   capture_output=True, env=env_for_godot())


def env_for_godot():
    """给 Godot 子进程的环境: 把解析好的路径用环境变量传下去, Assets 读同一来源 (相对路径已转绝对)。"""
    env = dict(os.environ)
    for key, fn in (("original", original_dir), ("hd4x", hd4x_dir)):
        env[_ENV_NAMES[key]] = fn()
    env["TDJ_PYTHON"] = python_exe()
    return env


# 原图仓库里的原版资源目录 (仓库里还有 tools/、Swordman/ 等, 遍历时只看这些)
TOPS = ["Camp", "Face", "Magic", "Misc", "Movie", "Music", "Rpg", "Shop", "Sprite", "Stage"]


def walk_original(src):
    """os.walk, 但只遍历原版资源目录。"""
    for top in TOPS:
        if os.path.isdir(os.path.join(src, top)):
            yield from os.walk(os.path.join(src, top))


def main():
    rows = [("original", original_dir(), os.path.join(original_dir(), "index.json")),
            ("hd4x", hd4x_dir(), os.path.join(hd4x_dir(), "hd4x.json")),
            ("godot", godot_exe(), godot_exe())]
    print("配置文件: %s (%s)" % (CONFIG_FILE, "存在" if os.path.isfile(CONFIG_FILE) else "没有, 用默认/环境变量"))
    bad = 0
    for name, path, probe in rows:
        ok = os.path.isfile(probe)
        bad += (not ok) and "可选" not in name
        print("  %-12s %-4s %s" % (name, "OK" if ok else "缺失", path))
    print("  python       OK   %s" % python_exe())
    if bad:
        if not has_original():
            print("\n" + missing_original_hint())
        if not os.path.isfile(godot_exe()):
            print("\n" + missing_godot_hint())
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
