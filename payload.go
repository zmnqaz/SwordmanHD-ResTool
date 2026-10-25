// SPDX-License-Identifier: GPL-3.0-only
package main

import (
	"archive/zip"
	"bytes"
	"crypto/sha256"
	_ "embed"
	"encoding/hex"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
)

// payload/tools.zip 由 build.sh 用 tools/release/make_tools_zip.py 生成: 生成资源包要用的脚本 (make_packs.py、tools/ 的流水线、game/ 工程)。
// 内嵌进程序, 所以玩家只下载一个文件。
//
//go:embed payload/tools.zip
var payloadZip []byte

// extractPayload 把内嵌的工具解到 dst (去掉 zip 里的顶层目录); 内容没变就跳过。
// 只覆盖 zip 里有的文件, 之前下载的 Python / Godot / ffmpeg、生成的中间文件不动。
func extractPayload(dst string) error {
	sum := sha256.Sum256(payloadZip)
	want := hex.EncodeToString(sum[:])
	stamp := filepath.Join(dst, ".payload_sha")
	if b, err := os.ReadFile(stamp); err == nil && strings.TrimSpace(string(b)) == want {
		return nil
	}
	zr, err := zip.NewReader(bytes.NewReader(payloadZip), int64(len(payloadZip)))
	if err != nil {
		return fmt.Errorf("内嵌工具包损坏: %w", err)
	}
	root := filepath.Clean(dst) + string(os.PathSeparator)
	for _, f := range zr.File {
		name := f.Name
		if i := strings.IndexByte(name, '/'); i >= 0 {
			name = name[i+1:]
		} else {
			continue
		}
		if name == "" {
			continue
		}
		target := filepath.Join(dst, filepath.FromSlash(name))
		if !strings.HasPrefix(target+string(os.PathSeparator), root) {
			return fmt.Errorf("工具包里有不安全的路径: %s", f.Name)
		}
		if f.FileInfo().IsDir() {
			if err := os.MkdirAll(target, 0o755); err != nil {
				return err
			}
			continue
		}
		if err := os.MkdirAll(filepath.Dir(target), 0o755); err != nil {
			return err
		}
		rc, err := f.Open()
		if err != nil {
			return err
		}
		mode := f.Mode().Perm()
		if mode == 0 {
			mode = 0o644
		}
		out, err := os.OpenFile(target, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, mode)
		if err != nil {
			rc.Close()
			return err
		}
		_, err = io.Copy(out, rc)
		rc.Close()
		if cerr := out.Close(); err == nil {
			err = cerr
		}
		if err != nil {
			return err
		}
	}
	return os.WriteFile(stamp, []byte(want+"\n"), 0o644)
}
