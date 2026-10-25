#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# 原图下的过场 mp4 -> game/classic/movies/*.ogv: 薄封装, 实际逻辑在 tools/assets/make_godot_movies.py (跨平台; 需要 ffmpeg)。
PY=$(command -v python3 || command -v python) || { echo "找不到 python3" >&2; exit 2; }
exec "$PY" "$(dirname "$0")/make_godot_movies.py" "$@"
