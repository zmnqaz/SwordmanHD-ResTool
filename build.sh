#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# 编译资源获取器 (纯 Go, 无 cgo: 在 Linux 上就能交叉编译所有平台), 产物在 out/:
#   win64 / linux-x64 / macos-arm64 / macos-x64 的单个可执行文件 (只有程序; 加上运行环境见 bundle/bundle.py 与 package.sh)
# 内嵌的「流水线工具包」= upstream/ (从游戏仓库同步来的提取脚本, 见 pipeline/sync_upstream.py) + pipeline/:
#   ./build.sh [win64|linux-x64|macos-arm64|macos-x64|host|all]
set -euo pipefail
cd "$(dirname "$0")"
GO="${GO:-go}"
WHAT="${1:-all}"
command -v "$GO" >/dev/null || { echo "错误: 找不到 go (https://go.dev/dl/)" >&2; exit 1; }
VER="$(git describe --tags --always 2>/dev/null || echo dev)"

python3 pipeline/make_payload.py --out payload/tools.zip
mkdir -p out

build() {  # GOOS GOARCH 输出 [额外 ldflags]
  CGO_ENABLED=0 GOOS="$1" GOARCH="$2" "$GO" build -trimpath -ldflags "-s -w -X main.version=$VER ${4:-}" -o "$3" .
}
want() { [ "$WHAT" = all ] || [ "$WHAT" = "$1" ]; }

want win64       && build windows amd64 "out/SwordmanHD-ResTool-win64.exe" "-H=windowsgui"   # 窗口程序: 不弹黑色控制台
want linux-x64   && build linux   amd64 "out/SwordmanHD-ResTool-linux-x64"
want macos-arm64 && build darwin  arm64 "out/SwordmanHD-ResTool-macos-arm64"
want macos-x64   && build darwin  amd64 "out/SwordmanHD-ResTool-macos-x64"
[ "$WHAT" = host ] && build "$("$GO" env GOOS)" "$("$GO" env GOARCH)" "out/SwordmanHD-ResTool-host"
ls -la out
