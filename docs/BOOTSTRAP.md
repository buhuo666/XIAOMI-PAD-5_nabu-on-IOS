# 首轮开发与构建

开发分支：`nabu16-bootstrap`。仓库既有主分支属于用户已放弃的旧项目，本工程从新的源码锁和脚本开始。

## 获取源码

```powershell
python -X utf8 tools/fetch_sources.py --proxy http://127.0.0.1:19999
```

Windows 下载脚本默认使用 `http://127.0.0.1:19999`，也可通过 `--proxy` 或 `NABU_PROXY` 指定。项目 Git remote 的本机访问同样使用该代理。GitHub Actions 使用远端网络拉取构建输入，不连接 Windows 的本地代理。

`configs/sources.lock.json` 记录精确提交。`src` 是独立上游仓库，项目 Git 只保存自己的脚本、补丁和配置；设备信息、固件、原始镜像、备份及运行日志保存在本地。

## 读取设备信息

设备需已授权 ADB 和 root：

```powershell
python -X utf8 tools/collect_device.py --adb D:/platform-tools/adb.exe
python -X utf8 tools/backup_gpt.py
```

结果分别写入 `device/inventory-<时间>` 和 `backup/gpt/<时间>`。GPT 备份读取原始块设备并保存至电脑，不写入设备。

## 提取固件成员

```powershell
python -X utf8 tools/fetch_ipsw_members.py --proxy http://127.0.0.1:19999
```

默认只取三个小成员和 BuildManifest。完整系统包使用并发续传工具，避免对大 OS 成员逐个小块请求：

```powershell
python -X utf8 tools/fetch_full_ipsw.py --proxy http://127.0.0.1:19999 --jobs 4
```

该工具可接续已经停止的单连接 `.ipsw.part`；运行时不得有其他下载进程写同一个文件。完成后验证 BuildManifest、完整 ZIP CRC 并记录 SHA-256。来源和预期 BuildManifest 哈希位于 `configs/firmware.json`。

下载完成后，从本地归档提取 BuildManifest 指定的 OS 镜像：

```powershell
python -X utf8 tools/extract_os_image.py
python -X utf8 tools/extract_os_image.py --component Cryptex1,SystemOS
python -X utf8 tools/extract_os_image.py --component Cryptex1,SystemTrustCache
python -X utf8 tools/extract_userland.py
python -X utf8 tools/inspect_userland.py
```

后两步使用现有 Windows 7-Zip 和 WSL Ubuntu-22.04，完成选定入口、共享缓存的提取、ZBM 解压与原始代码哈希核对。结果与提取范围见 [USERLAND-20F66](USERLAND-20F66.md)。

## GitHub Actions

推送本分支的 `tools`、`configs`、`patches/8796` 或构建工作流会运行 `.github/workflows/bootstrap.yml`，也定义了手动触发入口。

构建阶段为：固定 HakiOS／XNU → 固定 16.5 SDK → 选择原生 IIG → 应用 HakiOS 及项目补丁 → 准备 host 工具与依赖库 → 编译 8796 → 原版与候选的静态 LLDB 分析 → 保存日志、Mach-O 和构建报告。

工作流使用 macOS 15、Xcode 16.4；Actions 和 Theos SDK 固定提交，MacOSX 13.3 SDK 固定归档 SHA-256。原生分析阶段从固定 Apple 固件取小成员、核对 KernelCache 的预期 SHA-256、解码原版，再创建静态 LLDB target。工作流归档分析记录和源码构建的内核，不归档原版系统镜像；没有在 runner 上启动内核。

`probe_iig.py` 在头文件生成之前探测系统 Xcode 工具。找到原生 IIG 后，通过 `iig_8796.py` 选择生成实现中与旧版四字段 `IORPC` 相符的消息布局分支，并保存变换前后文件和布局断言。未找到原生工具时仍会明确记录回退模式；不能把 shim 模式与原生实现等同。实验结果和限制见 [IIG-COMPATIBILITY](IIG-COMPATIBILITY.md)。

HakiOS 记录了末尾导出检查可能失败。构建报告保留 make 的真实退出码和已经生成的有效 Mach-O，不能仅靠存在产物文件将失败改成成功。

这个参考构建用来建立 8796 编译基础。nabu 的 DarwinBoot、CPU／UFS 和原版组件预链接将在独立适配中加入。

实际首轮结果见 [FIRST-BUILD](FIRST-BUILD.md)。查询状态并下载已完成的日志、产物：

```powershell
python -X utf8 tools/github_ci.py --download
```

工具复用本机 Git credential helper，在进程内使用凭证；代理下载后的日志位于 `log/ci/github`，产物位于 `artifacts/ci`。

当前已完成的构建为 `41659076371 / attempt 1`，提交 `1e53b512c839d8e334391147457069598ddd1d0c`。全部 17 份 IIG 实现编译通过，三个空 reply 分支与 11 个平台查询入口已核对；缺失导出累计从 131 降至 24，完整构建仍为失败，原生分析步骤成功。以该 run 的实际候选复测：

```powershell
python -X utf8 tools/github_ci.py --run 41659076371 --download
python -X utf8 tools/compare_kernel_symbols.py OS/ipados/16.5-20F66-iPad7_11/extracted/kernelcache.arm64.macho artifacts/ci/41659076371-attempt-1/xnu8796-reference-9/artifacts/8796-reference/mach.development.bcm2837.unstripped --output log/ci/github/41659076371/attempt-1/symbol-comparison.json
python -X utf8 tools/inspect_kext_symbols.py --candidate artifacts/ci/41659076371-attempt-1/xnu8796-reference-9/artifacts/8796-reference/mach.development.bcm2837.unstripped --output log/ci/github/41659076371/attempt-1/kext-symbols.json
python -X utf8 tools/inspect_platform_consumers.py --candidate artifacts/ci/41659076371-attempt-1/xnu8796-reference-9/artifacts/8796-reference/mach.development.bcm2837.unstripped --output log/ci/github/41659076371/attempt-1/platform-consumers.json --validate-with-llvm-mc
```

新 run 的 artifact 名称取自下载结果，不从 run ID 猜测。`inspect_platform_consumers.py` 要求明确的候选和输出路径；LLVM 校验使用本机已有 WSL 工具。原生分析命令及证据边界见 [NATIVE-ANALYSIS-20F66](NATIVE-ANALYSIS-20F66.md)。仅更新文档或离线分析工具时可以提交 `[skip ci]`；这不能代替构建代码变更所需的实际验证。
