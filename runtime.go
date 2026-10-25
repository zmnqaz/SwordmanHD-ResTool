// SPDX-License-Identifier: GPL-3.0-only
package main

import (
	"os"
	"path/filepath"
	"runtime"
)

func fileExists(p string) bool {
	st, err := os.Stat(p)
	return err == nil && !st.IsDir()
}

// Runtime 是发布包里随程序一起放的运行环境 (见 bundle/bundle.py): 便携版 Python (已装好依赖库) + ffmpeg。
// 有它就完全不用联网下载、不用装任何东西; 没有 (开发时直接 go run) 才退回到自动下载。
//
//	<程序目录>/runtime/python/python.exe        (Windows)    runtime/python/bin/python3   (macOS / Linux)
//	<程序目录>/runtime/ffmpeg/ffmpeg(.exe) ffprobe(.exe)
type Runtime struct {
	Dir       string
	Python    string
	FFmpegDir string // 空 = 包里没带 ffmpeg
}

func findRuntime(dir string) *Runtime {
	py := filepath.Join(dir, "python", "bin", "python3")
	if runtime.GOOS == "windows" {
		py = filepath.Join(dir, "python", "python.exe")
	}
	if !fileExists(py) {
		return nil
	}
	rt := &Runtime{Dir: dir, Python: py}
	ff := filepath.Join(dir, "ffmpeg")
	name := "ffmpeg"
	if runtime.GOOS == "windows" {
		name = "ffmpeg.exe"
	}
	if fileExists(filepath.Join(ff, name)) {
		rt.FFmpegDir = ff
	}
	return rt
}

// defaultRuntimeDir: 程序旁边的 runtime 文件夹; macOS 的 .app 里 (Contents/MacOS/ 旁) 也找一下
func defaultRuntimeDir(exeDir string) string {
	for _, d := range []string{filepath.Join(exeDir, "runtime"), filepath.Join(filepath.Dir(exeDir), "Resources", "runtime")} {
		if st, err := os.Stat(d); err == nil && st.IsDir() {
			return d
		}
	}
	return filepath.Join(exeDir, "runtime")
}
