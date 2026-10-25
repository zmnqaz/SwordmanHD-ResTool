// SPDX-License-Identifier: GPL-3.0-only
package main

import (
	"os"
	"path/filepath"
	"runtime"
	"testing"
)

func touch(t *testing.T, p string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(p, []byte("x"), 0o755); err != nil {
		t.Fatal(err)
	}
}

func TestFindRuntime(t *testing.T) {
	d := t.TempDir()
	if findRuntime(d) != nil {
		t.Fatal("空目录不该找到 runtime")
	}
	py := filepath.Join(d, "python", "bin", "python3")
	ff := filepath.Join(d, "ffmpeg", "ffmpeg")
	if runtime.GOOS == "windows" {
		py = filepath.Join(d, "python", "python.exe")
		ff = filepath.Join(d, "ffmpeg", "ffmpeg.exe")
	}
	touch(t, py)
	rt := findRuntime(d)
	if rt == nil || rt.Python != py || rt.FFmpegDir != "" {
		t.Fatalf("只有 python: %+v", rt)
	}
	touch(t, ff)
	if rt = findRuntime(d); rt.FFmpegDir != filepath.Dir(ff) {
		t.Fatalf("应该找到 ffmpeg: %+v", rt)
	}
}

func TestGuiPythonPrefersPythonw(t *testing.T) {
	if runtime.GOOS != "windows" {
		t.Skip("只有 Windows 用 pythonw")
	}
	d := t.TempDir()
	touch(t, filepath.Join(d, "python.exe"))
	touch(t, filepath.Join(d, "pythonw.exe"))
	if got := guiPython(filepath.Join(d, "python.exe")); filepath.Base(got) != "pythonw.exe" {
		t.Fatalf("应改用 pythonw: %s", got)
	}
}

func TestExtractPayloadIsIdempotentAndKeepsOtherFiles(t *testing.T) {
	d := t.TempDir()
	if err := extractPayload(d); err != nil {
		t.Fatal(err)
	}
	for _, f := range []string{"restool/gui.py", "restool/run.py", "restool/pack.py", "tools/build_assets.py", ".payload_sha"} {
		if !fileExists(filepath.Join(d, filepath.FromSlash(f))) {
			t.Fatalf("缺 %s", f)
		}
	}
	mine := filepath.Join(d, "original", "keep.txt") // 之前生成的东西: 再展开不能动
	touch(t, mine)
	if err := os.Remove(filepath.Join(d, "restool", "gui.py")); err != nil {
		t.Fatal(err)
	}
	if err := os.Remove(filepath.Join(d, ".payload_sha")); err != nil { // 戳没了 = 视为新版本, 重新展开
		t.Fatal(err)
	}
	if err := extractPayload(d); err != nil {
		t.Fatal(err)
	}
	if !fileExists(filepath.Join(d, "restool", "gui.py")) || !fileExists(mine) {
		t.Fatal("重新展开后应补回 gui.py 且保留别的文件")
	}
}

func TestSplitArgs(t *testing.T) {
	data, rt, rest := splitArgs([]string{"-data", "/d", "--runtime=/r", "--selftest", "--game", "/g", "--start"})
	if data != "/d" || rt != "/r" || len(rest) != 4 || rest[0] != "--selftest" || rest[1] != "--game" || rest[2] != "/g" || rest[3] != "--start" {
		t.Fatalf("data=%q rt=%q rest=%q", data, rt, rest)
	}
	if d, r, rest := splitArgs(nil); d != "" || r != "" || len(rest) != 0 {
		t.Fatal("没有参数时应全空")
	}
}
