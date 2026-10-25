// SPDX-License-Identifier: GPL-3.0-only
//go:build windows

package main

import (
	"syscall"
	"unsafe"
)

// Windows 版是窗口程序 (没有黑色控制台), 启动失败时用系统消息框告诉用户
func showError(msg string) {
	u16 := func(s string) *uint16 { p, _ := syscall.UTF16PtrFromString(s); return p }
	proc := syscall.NewLazyDLL("user32.dll").NewProc("MessageBoxW")
	proc.Call(0, uintptr(unsafe.Pointer(u16(msg))), uintptr(unsafe.Pointer(u16("SwordmanHD 资源获取器"))), 0x10)
}
