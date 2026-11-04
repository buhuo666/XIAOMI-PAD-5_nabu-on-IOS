# nabu 临时启动入口与 8796 EFI 构建

更新：2026-11-04，Asia/Shanghai。本文区分当前设备、固定源码和待验证候选。

接手验收更新：`f77e851` 对应内核 Actions `41671552454`、独立 EFI Actions `41671552536` 均成功。2026-11-04 又在本地 WSL 完成板级固件、两个 EFI 程序、八核 ADT，并部署现有 ESP。第三轮照片证明 XNU 执行至启用 MMU 后的检查点 5，第四轮用户确认 CPU 拓扑解析后的检查点 12；副核启动、内存初始化与 UFS／Data 挂载仍待验证。系统区安装见 [设备安装记录](DEVICE-INSTALLATION-20F66.md)。

用户要求启动只能临时进行。核对设备与镜像后执行 `adb reboot bootloader`、`fastboot boot <verified-nabu-image.img>`。不得执行 `fastboot flash`、`erase`、`set_active`，不得写入 boot、recovery、xbl、abl 或修改活动槽。设备操作已获本会话授权。

## 本地构建与部署结果

工具链：WSL Ubuntu 22.04，LLVM／Clang／LLD 18.1.8，Python 3.12.16。Mu 固件固定上游提交 `d8aab0e2c272caeef5329716ff554c08cfebd6bd`；应用补丁 `patches/firmware/nabu-temporary-boot.patch`。直接依赖通过固定 Git gitlink 或上游 descriptor 中的版本、SHA-256 校验，离线导入的 Stuart 依赖收据在 `log/ci/nabu-firmware/local-cache-import.json`。

以下是首次实机所用产物，新诊断 EFI 另列于后文。

| 产物 | bytes | SHA-256 |
|---|---:|---|
| boot.img | 3,616,768 | `bca20de2c74522394c1b0005ca82ae5b03daeefb22a2f1cb7b221a40eecf1adc` |
| SM8150_EFI.fd | 3,145,728 | `7b621be1272b1f88c0331b5e467cb95d932238f4eed24ebde154f7d94cd2808e` |
| UniXNU.efi | 95,232 | `3913c4f62bed440e3e1408e255d08e2e9149c3cebbb50db89814f0676f52797a` |
| DarwinBoot.efi | 28,160 | `949c648544ecb1df2d2121c6bbd84088ba49d3637afb7141741f42b08e25b2a5` |

`boot.img` 使用 Android v0、4096 字节页，payload 为 `gzip(BootShim + FD) + Android DTB`。7 字节 ramdisk 是固定上游的占位文件，BootShim 不使用它；不是可启动 Android ramdisk。`tools/verify_nabu_boot_image.py` 检查组件长度、逐字节内容、gzip 边界、FD 大小、DTB 和 Android SHA-1 id，输出 `artifacts/nabu-firmware/boot-image-report.json`。

固件仅补充 `0x180000000` 以上经 RAM protocol 声明的内存，使用 ConventionalMemory 属性；避免重复登记 PEI 已拥有的低地址段。低地址 XBL／AOP 和 MLVM 段保留，防止覆盖当前设备 FDT 标为 no-map 的协处理器范围。`[0x17fe00000,0x180000000)` 保留为 PStore。实际 split loop 和初始化函数通过 16 项 ASan／UBSan 检查。

DarwinBoot 从实际 UEFI map 选择最大连续可分配窗口，2 MiB 对齐，上限 12 GiB；成功 AllocatePages 后回填 ADT。PStore 会分开高低两段，本机不应预先宣称获得完整 12 GiB。ADT 包含 8 个 affinity `0x000..0x700`、PSCI SMC、19.2 MHz counter、GICv3 和虚拟 timer INTID 19。ABI 与 ADT／分配器检查均通过，包括 13,604 个截断输入。

2026-11-04 09:26（Asia/Shanghai）部署：`tools/stage_nabu_boot_chain.py --apply --gpt-backup backup/gpt/20261104-082923` 成功。5 个文件写入现有 4 GiB FAT32 ESP，替换前保存原文件，部署后逐项回读 SHA-256。部署前后 6 个 LUN 的 30 份 GPT 元数据与既有备份一致；活动槽为 A。收据：`log/device/nabu-chain-20261104-092615/deployment.json`。本次未初始化或改写现有 Data。

ESP 路径为 `EFI/Nabu16/{UniXNU.efi,DarwinBoot.efi,Payloads/kernel.macho,Payloads/kernel.macho.adt}`；UniXNU 配置固定放在 `EFI/UniXNU/unixnu.toml`。5 秒后自动选择八核内核条目，另有返回 Android 的 reset 条目。DarwinBoot 在退出 Boot Services 前写入 `EFI/Nabu16/handoff-*.txt`。这个文件或绿色条只能证明 loader 到达相应阶段，不能证明内核入口执行。

复现本地构建：

```powershell
wsl -d Ubuntu-22.04 -- env NABU_FW_TREE=/home/buhuo/nabu16-fw-v2/tree NABU_PYTHON=python3.12 NABU_FW_DEPS_READY=1 bash /mnt/d/github-IOS/XIAOMI_PAD5-NABU/tools/build_nabu_firmware.sh
wsl -d Ubuntu-22.04 -- env NABU_EFI_WORK=/home/buhuo/nabu16-efi-v2 bash /mnt/d/github-IOS/XIAOMI_PAD5-NABU/tools/build_nabu_efi_wsl.sh
```

以下章节保留前期入口调查背景，不能作为部署后的当前 ESP 清单。

## 首次实机与分阶段诊断

2026-11-04 09:28:59（Asia/Shanghai）开始的实机记录使用源码提交 `4efc8f4025a4099b4e4117517cf072bc4e982c5d`，收据在 `log/device/nabu-boot-20261104-01/run.json`。实际命令为 `adb reboot bootloader` 和 `fastboot boot D:\github-IOS\XIAOMI_PAD5-NABU\log\device\nabu-boot-20261104-01\boot.img`；发送与 Booting 均返回 OKAY。

用户照片显示 UniXNU 背景上的 DarwinBoot 交接文字，不能据此判为菜单按键故障。该文字位于 ExitBootServices 调用之前。照片没有包含物理屏幕最顶端，无法判断绿色条是否出现。返回 Android 后，回收 `EFI/Nabu16/handoff-1A7F4ABE.txt`，7264 bytes，SHA-256 `f913d266b4852efe0da84c284c3bce16455996185fd11772294941631b9a6e3c`。这份日志明确属于 pre-ExitBootServices：

| 字段 | 实际值 |
|---|---|
| EL / MPIDR / CNTFRQ | 1 / `0x81000000` / 19,200,000 Hz |
| 连续分配基址 / 长度 | `0x180004000` / `0x1F8C00000`，7.88671875 GiB |
| boot_args / 内核入口物理地址 | `0x18143C000` / `0x1804484A8` |
| framebuffer | `0x9C000000`，1600×2560，rowBytes 6400，32 bpp |

内存映射记录已证明该高地址窗口在固件中成功登记并完成整段分配；它不证明 XNU 已接管或使用这段内存。回收工具确认 6 个 LUN 的 30 份 GPT 元数据、所有受检 Android 引导分区哈希与启动前一致，Android 槽 A 正常返回。

WSL 新构建目录 `/home/buhuo/nabu16-efi-v4` 复用固定版本的 v2 EDK II。DarwinBoot 加入不调用 UEFI 服务的 framebuffer 文本与汇编阶段条，完整构建、8796 ABI 和实际 ADT／分配器检查通过：

| 新诊断产物 | bytes | SHA-256 |
|---|---:|---|
| UniXNU.efi | 95,232 | `76a0ed84ce6119d619e2499c72837225d903a1bfe5ffbdd5aa1809b7b8fbd20b` |
| DarwinBoot.efi | 28,672 | `f0cab6d9f5ebfb646ddd16a26ce3c4c4a0e85239fa03816d0402ec5ea173fd12` |

屏幕中部依次显示 P1（最终 memory map 前）、P2（即将调用 ExitBootServices）、P3（返回成功或错误）；最顶端绿色条表示进入 loader 汇编，蓝色条表示完整窗口的 cache sweep 完成，橙色条表示 MMU／cache 关闭后即将跳转。任何色条都不证明内核入口执行。此轮保持原有约 7.89 GiB cache sweep 行为，以先定位实际停点。

复现：`NABU_EFI_WORK=/home/buhuo/nabu16-efi-v4 NABU_EFI_EDK=/home/buhuo/nabu16-efi-v2/edk2 bash tools/build_nabu_efi_wsl.sh`。补丁或头文件改变时须使用新生成目录，不能把旧 loader 树的再次编译当成新修改已进入产物。

2026-11-04 09:44:46 完成新诊断链的 ESP 部署与逐文件 SHA-256 回读，收据为 `log/device/nabu-chain-20261104-094446/deployment.json`。09:45:17 的第二次启动记录绑定提交 `dbc2aaf3f4af6e0b6c98295b7948edb697b6570e`；启动前核对 30 份 GPT 元数据和 14 个实际存在的引导分区哈希。实际命令仍为 `adb reboot bootloader` 和 `fastboot boot D:\github-IOS\XIAOMI_PAD5-NABU\log\device\nabu-boot-20261104-02\boot.img`，Booting 返回 OKAY。`log/device/nabu-boot-20261104-02/` 保存确切 EFI／内核／ADT／配置、源与构建收据、汇编反汇编及 run.json。

用户报告 P1/P2/P3 均可见，P3 为 `EBS OK - ENTERING STUB`，最顶部由上到下为绿色、蓝色、橙色。它确认 ExitBootServices 返回成功、owned window 的 cache sweep 完成、MMU／cache 关闭后的分支前标记执行。该证据尚未证明内核入口执行。设备恢复 Android 后回读 `handoff-19C4F7E8.txt`（7220 bytes，SHA-256 `c32715b711b8a96c1ad69ca39a8b74eb2ab8e84d1a1d508af28df99a7be74101`），窗口仍为 `0x180004000 + 0x1F8C00000`。30 份 GPT 元数据及 14 个受检引导分区哈希全部与启动前一致。

## 内核检查点诊断候选

现有参考内核已编译进 `LOADER_CHECKPOINT 1..5` 与早期异常回调，`_loader_stub_slot` 为 `0xfffffff0074497f0`，文件偏移 `0x4457f0`；唯一的 `XNULDRST` 标记之后有三个初始为零的 64 位字段。新 loader 仅在已通过 nabu ADT 校验且 `nabu-kernel-checkpoint` 为 1..5 时绑定回调；本轮选择 5，位置在内核启用 MMU 后。磁盘内核文件保持已验证哈希，回调地址／检查点／PA-VA 差值仅写入本次分配的内存副本。

`NabuKernelReport.c`／`.S` 由本地 LLVM 18 编译为无未决符号、无运行时重定位的 2192 字节代码。loader 为它和独立物理栈保留 16 KiB，并纳入 TopOfKernelData。回调先保存 x0..x7，切换到自己的物理栈，直接绘制第四条品红色带及检查点或异常报告，然后停机。它不恢复或调用 UEFI，不写磁盘。REASON=2 时 CODE 是主动停止的检查点号，x4..x7 未被内核检查点 ABI 定义；REASON=1 时打印 ESR／ELR／FAR／LR／SP。

本地 WSL `/home/buhuo/nabu16-efi-v5` 构建结果：UniXNU.efi 为 95,232 bytes，SHA-256 `ca90d0101857bc6b2c3c96740ea2c43ce994179955aa3ab91576da0f52506c2b`；DarwinBoot.efi 为 31,744 bytes，SHA-256 `70a530626f32f4aeedd42cfbd735e32945bb5519bc63a5dd8229ac1730e52030`。EFI 中的回调 blob 与已测试 blob 逐字节一致，SHA-256 为 `d17b880b7249121bb9fa690d43e372d66c518deff6efa4632619f1793821fab2`。

`check_nabu_kernel_report.py` 对实际编译 blob 执行 3 个 Unicorn 场景：高／低物理地址、检查点／异常原因、无效显示参数，并检查输入寄存器保留、栈切换与内存边界哨兵；实际 slot binder 通过 7 项 ASan／UBSan 场景。8796 ABI 和 13,644 个截断 ADT／5 个分配场景通过。这些是主机检查，不证明真实 MMU 行为或内核执行；第三轮须单独记录屏幕结果。

2026-11-04 10:10:15 完成检查点 5 版本部署，收据为 `log/device/nabu-chain-20261104-101015/deployment.json`。10:10:58 开始第三次临时启动，源码提交 `9540428e1dbb1968315bb0af2374658608f95ccc`；实际命令为 `adb reboot bootloader` 和 `fastboot boot D:\github-IOS\XIAOMI_PAD5-NABU\log\device\nabu-boot-20261104-03\boot.img`。发送与 Booting 返回 OKAY，确切启动链、回调构建／主机检查和运行收据冻结在 `log/device/nabu-boot-20261104-03/`。

用户照片确认第四条品红色带、`XNU CALLBACK REACHED`、`KERNEL CHECKPOINT - INTENTIONAL STOP`、REASON=2、CODE=5。此处 X4..X7 是未定义为异常状态的寄存器；LOG PA／BYTES 为零，符合汇编检查点 ABI。它证明启动 CPU 实际执行内核，并到达 `common_start` 中写 SCTLR_EL1 启用 MMU、ISB 之后的检查点。它不是异常或完整系统启动，也不证明副核运行、C 初始化或存储挂载。

照片保存在本地 run 目录的 `screen-checkpoint5.jpg`，哈希及解释在 `screen-observation.json`，`run.json` 已按该证据标记 `kernel_execution_validated=true` 并限定证据范围。返回 Android 后回读 `handoff-19E557B6.txt`（7298 bytes，SHA-256 `ee289058cc490524fa797f0072f34f8caf8c7d96f8b8d40d71f16a233303ccb1`），它记录 checkpoint=5、callback PA=`0x181444000`；30 份 GPT 元数据和 14 个受检引导分区哈希全部一致。

### C 初始化诊断候选

后续 loader 支持已核对的检查点 1..5、10..21、30..35、40..44，0 保留为关闭诊断。默认选择 12，实际内核 `0xfffffff00743f2b8` 调用 `ml_parse_cpu_topology`，随后 `0xfffffff00743f2bc` 把 12 放入 w0、`0xfffffff00743f2c0` 调用 `loader_checkpoint`。因此到达 12 可证明经过 C 入口、boot_args 复制、PE_init_platform(FALSE)、早期 boot-arg 处理和 CPU 拓扑解析，但副核还没有启动。C 回调入口保持物理地址的恒等映射，报告 stub 在切换自己的物理栈前关闭 MMU。

`stage_nabu_boot_chain.py --checkpoint N` 将选定值写入 ADT 并记录在部署收据中，重复输出目录必须匹配原 ADT，防止意外改变已冻结的候选。WSL v6 构建通过；ADT 的 46 个检查点接受／拒绝用例、13,644 个截断输入、5 个分配场景、9 个实际 binder 场景和 3 个报告 blob 仿真场景均通过。报告 blob 与第三轮相同；UniXNU.efi SHA-256 为 `bb23ca127907b8b90359c479b25c84f6c5e67ba724c6cf49547bf21bac1f8c06`（95,232 bytes），DarwinBoot.efi 为 `25727a0474692c527b0ac6115a66cfacd5683996ea5281acdba06f1b04c0b214`（32,256 bytes）。

2026-11-04 10:22:05 部署检查点 12 链，收据 `log/device/nabu-chain-20261104-102205/deployment.json`。10:22:42 的第四次临时启动绑定源码提交 `db9c8ea9df2bb025c83383656b59740dc0da6eba`，实际执行 `adb reboot bootloader`、`fastboot boot D:\github-IOS\XIAOMI_PAD5-NABU\log\device\nabu-boot-20261104-04\boot.img`，发送与 Booting 均为 OKAY。冻结产物、主机报告和反汇编在 `log/device/nabu-boot-20261104-04/`。

用户确认第四轮出现 `XNU CALLBACK REACHED`、REASON=2、CODE=`000000000000000C`，即检查点 12。此轮证据为用户文字确认，未收到新照片；确认早期 C 平台初始化与 CPU 拓扑解析完成，不证明副核启动或解析出的核心数量。返回 Android 后回收 `handoff-19E81857.txt`（7299 bytes，SHA-256 `277293c2012bc87a9524a172d3313a9ce1f2ff729356cd4d739e2284ad29e81d`），GPT 30 份元数据和 14 个受检引导分区哈希一致。`screen-observation.json` 与 `run.json` 已记录该证据及范围。

下一候选通过 `stage_nabu_boot_chain.py --checkpoint 17` 选择 `arm_vm_init()` 之后的停止点，复用 v6 EFI 与原内核。实际机器码在 `0xfffffff00743f438` 调用 `_arm_vm_init`，`0xfffffff00743f43c` 将 17 放入 w0，`0xfffffff00743f440` 调用 `_loader_checkpoint`。成功报告应为 REASON=2、CODE=`0x11`；到达它表示该初始化例程返回，仍不能单独证明整段 RAM 已完成读写测试、八核已启动或 Data 已挂载。

## 当前设备入口

2026-11-03 23:57 的只读检查发现：4 GiB `nabu_esp` 上只有 `EFI/NabuDiag/NabuProbe.efi` 与两个 JSON。`probe-deployment.json` 自述 `firmware_executed=false`、`kernel_executed=false`，且没有默认启动路径或 startup 脚本。文件级备份保存在本地 `backup/esp/20261103-235736/`。

该次检查的 ESP 没有 rEFInd、UniXNU.efi 或 DarwinBoot.efi；Android A/B 的首块都是 Android boot 头。此历史观察已由上面的 ESP 文件部署更新。

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

上述调查已推进到本地构建、逐段检查与首次本机 loader 运行，具体输入收据和实机结果见上文。

## 12 GiB 相关的固件约束

该快照的 nabu `PlatformMemoryMapLib.c` 注释包含 12 GiB 对应低洞 `[0xb9900000,0xc0000000)`，并由 `RamPartitionDxe` 通过 `EFI_RAMPARTITION_PROTOCOL` 获取高段，再补充超过 `0x180000000` 的 RAM。**注释与路径存在不证明本机映射成功。**

其固件内存表还保留了 `[0xc0000000,0xc0300000)` 的 MPSS_EFS。启用 `USE_MEMORY_FOR_SERIAL_OUTPUT=1` 时，又将 `[0x17fe00000,0x180000000)` 划作 PStore。因此 Android 下无固定洞的 11 GiB 高段不能直接被当作这个固件下连续可分配窗口。最终窗口必须来自所用固件的真实 descriptors 与整段分配成功记录。

另外，调查快照的 `SpiltAndAddRamPartitions()` 会覆盖前面 `AddRamPartition()` 的错误状态；对于整 2 GiB 倍数还会尝试零长度尾段，调用者也未传播其返回值。本次补丁已修复并通过主机边界测试；首次交接日志已记录约 7.89 GiB 高地址窗口的实际分配。

## 真机测试的剩余前提

完整内核 `make` 成功、EFI 构建成功、板级 boot.img 校验成功是不同检查。当前链可测试固件到 loader／内核交接，但原生 UFS、原版组件预链接和 Data 挂载尚未接通。真机结果必须单独记录。`tools/run_nabu_temporary_boot.py` 在启动前核对镜像、源提交、设备、GPT 和引导分区哈希，返回 Android 后再次比较并回收 ESP 日志。
