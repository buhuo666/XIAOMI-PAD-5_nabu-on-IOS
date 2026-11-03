# nabu 临时启动入口与 8796 EFI 构建

更新：2026-11-04，Asia/Shanghai。本文区分当前设备、固定源码和待验证候选。

用户要求启动只能临时进行。因此唯一计划中的设备启动命令是核对设备与镜像后执行 `fastboot boot <verified-nabu-image.img>`。不得执行 `fastboot flash`、`erase`、`set_active`，不得写入 boot、recovery、xbl、abl 或修改活动槽。本轮工具没有 ADB、fastboot 或分区写入操作。

## 当前设备入口

2026-11-03 23:57 的只读检查发现：4 GiB `nabu_esp` 上只有 `EFI/NabuDiag/NabuProbe.efi` 与两个 JSON。`probe-deployment.json` 自述 `firmware_executed=false`、`kernel_executed=false`，且没有默认启动路径或 startup 脚本。文件级备份保存在本地 `backup/esp/20261103-235736/`。

当前 ESP 没有 rEFInd、UniXNU.efi 或 DarwinBoot.efi；Android A/B 的首块都是 Android boot 头。这些观察不能证明本机已经存在能够执行外部 EFI 应用的菜单。

固定参考 `src/nabu` 的 `board.toml` 和 `README.md` 声称原厂 Xiaomi UEFI → rEFInd → UniXNU → DarwinBoot，但 `[firmware] dsc` 和 `fd` 均为空。该仓库不生成板级固件或可供 `fastboot boot` 使用的 Android 启动镜像。其已有设备记录属于参考项目，不能转换成本机已经启动过的证据。

## 独立 EFI 构建

新增 `.github/workflows/efi.yml`，与内核编译工作流独立运行：

1. 验证 `configs/sources.lock.json` 固定的 UniXNU `245aca1a9ec5b730b1cad80fade295800d2981f1`、DarwinBoot `d099354d0eab34df5088ca1ba89c9c88bc3260bb` 和 XNU 8796。
2. 在生成树应用项目 8796 boot_args／容量补丁，执行实际结构、命令行和容量边界的 host 检查。
3. 使用 UniXNU `feeds.toml` 已固定的 Mu_Basecore `cfb93724a06ff86ff5ba971413368a7809ee42a5`，额外核对 libfdt、mipisyst、Brotli 三个 gitlink。输入保存在 `configs/efi-build-inputs.json`。
4. Ubuntu 24.04、LLVM 18、EDK II `CLANGPDB` 构建 DEBUG 应用和驱动。记录实际编译器版本；包版本由 runner 安装环境决定，尚未声称逐字节可复现。
5. 检查两个产物的 PE 签名、AArch64 machine、PE32+ 和 EFI subsystem，保存头部、日志、源与补丁身份、大小及 SHA-256。

入口：`bash tools/build_8796_efi.sh`。输出是 `artifacts/efi8796/UniXNU.efi` 和 `DarwinBoot.efi`；前者是 EFI 应用，后者是 EFI boot-service 驱动。**它们不是 Android boot.img，也不包含板级固件、nabu ADT 或可启动内核。不能把 `.efi` 直接传给 `fastboot boot`。**

脚本拒绝重用已有 EDK II 生成目录；源码 checkout 不作编译写入。此文记录提交前的语法检查，完整构建结果须以 Actions 的实际报告为准。

## 可继续核查的临时固件来源

已通过 GitHub API 将 Project-Aloha `mu_aloha_platforms` 的调查快照固定为 `d8aab0e2c272caeef5329716ff554c08cfebd6bd`。仅下载了用于调查的源码与树清单，没有获取或执行成品启动镜像。来源和 SHA 收据在本地 `log/analysis/nabu-boot-entry/sources-receipt.json`。

该快照包含 `Platforms/SurfaceDuo1Pkg/Device/xiaomi-nabu/`，其产品 PCD 是 nabu／SM8150-AC。`build_cfg/sm8150.json` 规定 UEFI 基址 `0x9fc00000`、大小 `0x300000`、Android header v0、4096 字节页和压缩 payload。`PythonLibs/PostBuild.py` 实际将 BootShim 与固件卷拼接、gzip 压缩、追加 Android DTB，再用 mkbootimg 打包。参考构建入口为 `build_uefi.py -d xiaomi-nabu -t DEBUG`，README 指定输出 `Build/SurfaceDuo1Pkg/xiaomi-nabu.img`。

这提供了一条可调查的板级镜像构建路径，尚未闭合以下项目：完整固定嵌套依赖、厂商二进制身份与来源、实际构建、打包结果逐段检查、本机启动与日志回读。上游 `--init`／Stuart 更新流程仍需审查后再用于项目的可重复构建；不直接运行未经审查的上游设备安装脚本。

## 12 GiB 相关的固件约束

该快照的 nabu `PlatformMemoryMapLib.c` 注释包含 12 GiB 对应低洞 `[0xb9900000,0xc0000000)`，并由 `RamPartitionDxe` 通过 `EFI_RAMPARTITION_PROTOCOL` 获取高段，再补充超过 `0x180000000` 的 RAM。**注释与路径存在不证明本机映射成功。**

其固件内存表还保留了 `[0xc0000000,0xc0300000)` 的 MPSS_EFS。启用 `USE_MEMORY_FOR_SERIAL_OUTPUT=1` 时，又将 `[0x17fe00000,0x180000000)` 划作 PStore。因此 Android 下无固定洞的 11 GiB 高段不能直接被当作这个固件下连续可分配窗口。最终窗口必须来自所用固件的真实 descriptors 与整段分配成功记录。

另外，调查快照的 `SpiltAndAddRamPartitions()` 会覆盖前面 `AddRamPartition()` 的错误状态；对于整 2 GiB 倍数还会尝试零长度尾段，调用者也未传播其返回值。这是需要进一步修复和测试的源码问题，不能因初始化函数返回成功就认定所有高内存都已映射。

## 真机测试的剩余前提

完整内核 `make` 成功、独立 EFI 构建成功、板级临时 boot.img 验证成功是不同检查。还需本机八核 ADT、服务归属与预链接闭合、实际 UEFI 窗口、启动参数和可回收日志。满足这些条件后临时启动；失败时读取可用日志并返回原有 Android，不以刷写引导分区作为排障捷径。
