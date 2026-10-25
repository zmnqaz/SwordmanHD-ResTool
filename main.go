// SPDX-License-Identifier: GPL-3.0-only

// SwordmanHD 资源获取器的启动器: 一个很小的 Go 程序, 双击它就打开资源获取器的窗口。
// 窗口与流水线都是 Python (pipeline/gui.py 用 tkinter + customtkinter, 原生桌面窗口), 用发布包里的 runtime/ (便携 Python + 依赖库 + ffmpeg) 运行,
// 所以玩家不用装任何东西。这个启动器只做三件事: 把内嵌的流水线工具包展开到程序旁边的「restool-data」、找到 runtime、用它启动窗口。
// 纯 Go 标准库、没有 cgo, 在 Linux 上就能交叉编译 Windows / macOS / Linux。
package main

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
)

var version = "dev"

// guiPython: Windows 用没有控制台的 pythonw.exe 启动窗口 (不弹黑窗口); 其他系统就是 python3
func guiPython(py string) string {
	if runtime.GOOS == "windows" && strings.HasSuffix(strings.ToLower(py), "python.exe") {
		w := py[:len(py)-len("python.exe")] + "pythonw.exe"
		if fileExists(w) {
			return w
		}
	}
	return py
}

// splitArgs 取出启动器自己的参数 -data / -runtime (单双横线都行, 值可以写成 -data=x 或 -data x), 其余的原样返回
func splitArgs(args []string) (data, rt string, rest []string) {
	for i := 0; i < len(args); i++ {
		name := strings.TrimLeft(args[i], "-")
		val, hasVal := "", false
		if k := strings.IndexByte(name, '='); k >= 0 {
			name, val, hasVal = name[:k], name[k+1:], true
		}
		if (name == "data" || name == "runtime") && strings.HasPrefix(args[i], "-") {
			if !hasVal && i+1 < len(args) {
				i++
				val = args[i]
			}
			if name == "data" {
				data = val
			} else {
				rt = val
			}
			continue
		}
		rest = append(rest, args[i])
	}
	return
}

func main() {
	dataFlag, rtFlag, rest := splitArgs(os.Args[1:]) // 其余参数 (如 --game <目录> --start --selftest) 原样交给窗口程序

	exe, _ := os.Executable()
	exeDir := filepath.Dir(exe)
	data := dataFlag
	if data == "" {
		data = filepath.Join(exeDir, "restool-data")
	}
	if err := os.MkdirAll(data, 0o755); err != nil {
		home, _ := os.UserHomeDir()
		alt := filepath.Join(home, "SwordmanHD-restool-data")
		if err2 := os.MkdirAll(alt, 0o755); err2 != nil {
			fatal("不能创建工作目录 %s: %v", data, err)
		}
		data = alt
	}
	if err := extractPayload(data); err != nil {
		fatal("展开内置工具失败: %v", err)
	}
	rtDir := rtFlag
	if rtDir == "" {
		rtDir = defaultRuntimeDir(exeDir)
	}
	rt := findRuntime(rtDir)
	if rt == nil {
		fatal("没有找到 runtime 文件夹 (它应该和本程序在同一个文件夹里, 里面有 Python 和 ffmpeg)。\n请把发布压缩包完整解压后再运行, 不要只拿走这个 exe。")
	}

	args := append([]string{filepath.Join(data, "restool", "gui.py")}, rest...)
	cmd := exec.Command(guiPython(rt.Python), args...)
	cmd.Dir = data
	env := append(os.Environ(), "PYTHONUTF8=1", "PYTHONIOENCODING=utf-8", "PYTHONDONTWRITEBYTECODE=1", "TDJ_NO_PAUSE=1")
	if rt.FFmpegDir != "" {
		env = append(env, "PATH="+rt.FFmpegDir+string(os.PathListSeparator)+os.Getenv("PATH")) // 随包的 ffmpeg 放在 PATH 最前面
	}
	cmd.Env = env
	logPath := filepath.Join(data, "restool.log")
	if f, err := os.OpenFile(logPath, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644); err == nil {
		defer f.Close()
		cmd.Stdout, cmd.Stderr = f, f
	}
	if err := cmd.Run(); err != nil {
		fatal("窗口程序异常退出: %v\n详情见 %s", err, logPath)
	}
}

func fatal(format string, a ...any) {
	showError(fmt.Sprintf(format, a...))
	os.Exit(1)
}
