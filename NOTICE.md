# 第三方组件

获取器本身按 GPL-3.0-only 授权 (见 LICENSE)。发布包的 `runtime/` 文件夹里原样带着下面这些组件, 各按自己的许可分发,
完整清单与源码出处见发布包里的 `runtime/LICENSES.txt`, 各依赖库的许可文本在 `site-packages/<包名>-<版本>.dist-info/`。

| 组件 | 许可 |
|---|---|
| Python (CPython 3.12) | PSF License |
| numpy | BSD-3-Clause |
| Pillow | MIT-CMU (HPND) |
| opencv-python-headless | Apache-2.0 (OpenCV; wheel 里含 FFmpeg 的 LGPL 部分) |
| fonttools | MIT |
| customtkinter (窗口界面) / darkdetect / packaging | MIT / BSD-3-Clause / Apache-2.0 或 BSD-2-Clause |
| Tcl/Tk (tkinter 的底层) | Tcl/Tk License (BSD 类) |
| opencc-python-reimplemented | Apache-2.0 |
| FFmpeg (ffmpeg / ffprobe, GPL 构建) | GPL-2.0-or-later; 源码出处 https://ffmpeg.org/ 与构建来源 https://github.com/BtbN/FFmpeg-Builds (Windows / Linux)、https://www.osxexperts.net/ (macOS) |

获取器内嵌的资源包生成脚本来自项目主仓库 SwordmanHD (GPL-3.0-only)。
本工具不含《天地劫：神魔至尊传》的任何资源; 它只在使用者自己的电脑上、对使用者自己合法拥有的原版游戏做转换。
