#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# 把「程序 + 随包运行环境」打成发布压缩包 (玩家下载解压就能用), 产物在 dist/:
#   SwordmanHD-ResTool-win64.zip  -linux-x64.tar.gz  -macos-arm64.zip  -macos-x64.zip
# 用法: ./package.sh <win64|linux-x64|macos-arm64|macos-x64> [运行环境所在目录, 缺省 build/<平台>]
#   缺什么补什么: 没有程序 (out/) 就先 ./build.sh, 没有运行环境 (build/<平台>/runtime) 就先 python3 bundle/bundle.py, 再打包。
set -euo pipefail
cd "$(dirname "$0")"
P="${1:?用法: package.sh <win64|linux-x64|macos-arm64|macos-x64> [运行环境目录]}"
RT_PARENT="${2:-build/$P}"
NAME="SwordmanHD-ResTool-$P"
STAGE="$(mktemp -d)/SwordmanHD-ResTool"
mkdir -p "$STAGE" dist
case "$P" in win64) EXE="out/SwordmanHD-ResTool-win64.exe" ;; *) EXE="out/SwordmanHD-ResTool-$P" ;; esac
[ -f "$EXE" ] || ./build.sh "$P"
[ -d "$RT_PARENT/runtime" ] || python3 bundle/bundle.py --platform "$P" --out "$RT_PARENT"

case "$P" in
  win64)
    cp "out/$NAME.exe" "$STAGE/SwordmanHD-ResTool.exe"
    cat > "$STAGE/README.txt" <<'TXT'
SwordmanHD 资源获取器

1. 双击「SwordmanHD-ResTool.exe」(不用安装任何东西; 要保持整个文件夹在一起, 不要只拿走 exe)。
2. 在打开的窗口里选你的原版游戏文件夹, 点「开始生成」。
3. 完成后点「打开资源包文件夹」, 把里面的 resource 文件夹放到 SwordmanHD 游戏旁边。

如果 Windows 提示「已保护你的电脑」(因为程序没有付费的数字签名): 点「更多信息」→「仍要运行」。
生成的资源包是对你自己拥有的原版的演绎, 仅供个人使用, 请勿分享。
许可与第三方组件见 licenses 文件夹和 runtime\LICENSES.txt。
TXT
    ;;
  linux-x64)
    cp "out/$NAME" "$STAGE/SwordmanHD-ResTool"
    cat > "$STAGE/README.txt" <<'TXT'
SwordmanHD 资源获取器 (Linux x86_64)

1. 在这个文件夹里运行: ./SwordmanHD-ResTool   (不用安装任何东西; 需要桌面环境)
2. 在打开的窗口里选你的原版游戏文件夹, 点「开始生成」。
3. 完成后把生成的 resource 文件夹放到 SwordmanHD 游戏旁边。
TXT
    ;;
  macos-arm64|macos-x64)
    cp "out/$NAME" "$STAGE/SwordmanHD-ResTool"
    cat > "$STAGE/README.txt" <<'TXT'
SwordmanHD 资源获取器 (macOS)

程序没有 Apple 签名, 第一次要放行。在「终端」里进到这个文件夹, 运行一次:
    xattr -dr com.apple.quarantine . && chmod +x SwordmanHD-ResTool
然后运行: ./SwordmanHD-ResTool    (不用安装任何东西)
在打开的窗口里选你的原版游戏文件夹, 点「开始生成」; 完成后把生成的 resource 文件夹放到 SwordmanHD 游戏旁边。
TXT
    ;;
  *) echo "未知平台 $P" >&2; exit 1 ;;
esac
chmod +x "$STAGE"/SwordmanHD-ResTool* 2>/dev/null || true
mkdir -p "$STAGE/licenses"
cp LICENSE NOTICE.md "$STAGE/licenses/"
cp -a "$RT_PARENT/runtime" "$STAGE/runtime"

OUT="$PWD/dist"
case "$P" in
  linux-x64) rm -f "$OUT/$NAME.tar.gz"; tar -C "$(dirname "$STAGE")" -czf "$OUT/$NAME.tar.gz" SwordmanHD-ResTool; ls -la "$OUT/$NAME.tar.gz" ;;
  *)         rm -f "$OUT/$NAME.zip"; (cd "$(dirname "$STAGE")" && zip -qry "$OUT/$NAME.zip" SwordmanHD-ResTool); ls -la "$OUT/$NAME.zip" ;;
esac
rm -rf "$(dirname "$STAGE")"
