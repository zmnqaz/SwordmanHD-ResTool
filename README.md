# SwordmanHD-ResTool

[SwordmanHD](https://github.com/zmnqaz/SwordmanHD) (《天地劫：神魔至尊传》高清复刻) 的资源获取器。选你自己的原版游戏文件夹, 它帮你从原版**提取资源**, 并**打包成 `.pck`**。不含《天地劫》的任何资源, 生成物仅供个人使用。

## 下载

到 [Releases](../../releases) 下载你系统的压缩包, 解压, 运行, 不用装任何东西:

| 系统 | 文件 | 运行 |
|---|---|---|
| Windows | `SwordmanHD-ResTool-win64.zip` | 双击 `SwordmanHD-ResTool.exe` |
| macOS (Apple 芯片) | `SwordmanHD-ResTool-macos-arm64.zip` | 终端里 `xattr -dr com.apple.quarantine .` 后 `./SwordmanHD-ResTool` |
| macOS (Intel) | `SwordmanHD-ResTool-macos-x64.zip` | 同上 |
| Linux | `SwordmanHD-ResTool-linux-x64.tar.gz` | `./SwordmanHD-ResTool` |

## 使用

1. **准备原版游戏**: 一份你自己的《天地劫：神魔至尊传》原版游戏文件夹 (里面有 `Sprite`、`Stage` 文件夹和 `Swordman.exe`)。
2. **选择路径**: 运行程序, 选上面的原版游戏文件夹, 再选资源包保存到哪 (默认是程序旁边的 `packs`), 点「开始生成」。几分钟到十几分钟, 全程不联网。音效默认压成 OGG, 可勾选保留原版无损 WAV (资源包大约多 90 MB)。
3. **得到的资源包** (在保存位置里), 把 `resource` 文件夹放到 SwordmanHD 游戏旁边就能玩:

| 文件 | 内容 | 大小 |
|---|---|---|
| `resource/common_assets.pck` | 动画、图片、音乐音效 | 约 520 MB |
| `resource/common_story.pck` | 剧情脚本、对白、数值、关卡 | 约 8 MB |
| `resource/classic_movies.pck` | 过场动画 | 约 220 MB |
| `BUILD.json` | 生成时间与原版版本记录 | 很小 |

另外, 从原版解出来的全部原始资源 (图片、音效、数值等, 做 mod 可以直接用) 在程序旁边的 `restool-data/original/`。

## 编译

需要 Go 1.22+ 和 Python 3.10+。一条命令 (在 Linux 上就能编所有平台):

```bash
./package.sh win64        # → dist/SwordmanHD-ResTool-win64.zip   (linux-x64 / macos-arm64 / macos-x64 同理)
```

## 许可

GPL-3.0-only ([LICENSE](LICENSE)), 第三方组件见 [NOTICE.md](NOTICE.md)。
