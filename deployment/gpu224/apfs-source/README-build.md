# 从随包源码重建 Windows APFS 工具

本目录提供 `mkapfs.exe` 和 `apfsck.exe` 的完整对应源码：

- `apfsprogs/`：上游提交 `1bd1c1c2140d13d1b6d2e03379316572bee70aa3`，许可证见 `apfsprogs/LICENSE`。
- `windows-adapter/`：Windows 普通镜像文件接口适配，不改变 APFS 文件系统算法。
- `rebuild.py`：从以上两个目录交叉编译，不需要 `.git`、重新下载上游源码或整个项目目录。
- `build_apfsprogs_windows.py`：原项目的 CI 构建脚本，保留作为构建来源；解压后的本目录请使用 `rebuild.py`。

Windows 部署直接运行随包 EXE，无需安装 Linux、WSL 或编译器。下面的 Linux/WSL 环境仅用于自行重建工具。

## Python 构建入口

在 Ubuntu 或 Ubuntu WSL 中安装 MinGW-w64 和 Python：

```bash
sudo apt-get update
sudo apt-get install -y gcc-mingw-w64-x86-64 python3
```

进入解压后的 `host/apfs/source` 目录。例如 Windows 包目录为 `C:\Nabu224`，WSL 路径如下：

```bash
cd /mnt/c/Nabu224/host/apfs/source
python3 rebuild.py --output ../rebuilt-apfs
```

输出目录需要尚不存在，生成 `mkapfs.exe`、`apfsck.exe`、两份构建日志和 `build-report.json`。构建脚本会将两个 `version.h` 写为 `GIT_COMMIT "1bd1c1c2"`；完整来源提交仍记录在构建报告中。短版本字段适合 APFS 格式化器的标识字段。

## 等价 GCC 命令

也可在同一源码目录使用下面的 Bash 循环。它与 Python 入口使用相同的源码、链接库和编译选项：

```bash
set -e
mkdir ../rebuilt-apfs
for tool in mkapfs apfsck; do
    printf '#define GIT_COMMIT "1bd1c1c2"\n' > "apfsprogs/$tool/version.h"
    x86_64-w64-mingw32-gcc -O2 -static -D_FILE_OFFSET_BITS=64 \
        -Wno-address-of-packed-member -fno-strict-aliasing \
        -include windows-adapter/compat.h -Iwindows-adapter -Iapfsprogs/include \
        apfsprogs/"$tool"/*.c apfsprogs/lib/*.c apfsprogs/lib/zlib_inflate/*.c \
        -o "../rebuilt-apfs/$tool.exe" -lwinpthread \
        > "../rebuilt-apfs/$tool-build.log" 2>&1
done
```

两种方式均生成 Windows x64 程序，只操作主机上的普通镜像文件。自行重建成功仅说明编译成功，`build-report.json` 中的 `windows_runtime_tested` 为 false；在 Windows 上运行格式化和只读检查后才能记录运行验证。不同编译器版本可能生成不同 EXE 字节，不影响上述源码和算法对应关系。
