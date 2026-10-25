// SPDX-License-Identifier: GPL-3.0-only
//go:build !windows

package main

import (
	"fmt"
	"os"
)

func showError(msg string) { fmt.Fprintln(os.Stderr, "错误:", msg) }
