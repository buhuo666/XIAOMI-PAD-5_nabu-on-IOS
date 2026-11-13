# GPU242 三色条停止：屏幕检查点诊断（2026-11-13）

若 cp01 已试过且仍只有三色条、找不到 handoff，请先看 [云端反编译后的补充说明](reference/gpu224-history/回复-cp01与handoff缺失-20261112.md)，检查实际 ESP 文件后再继续后续检查点。

早期检查点更新让 `tools/prepare_chain.py` 接受 `--checkpoint`，使用 GPU242 内核和 DarwinBoot 已包含的屏幕报告功能。当前完整部署包还包含动态容量内核，保留这套屏幕报告功能；容量更新不表示三色条启动故障已经修复。`inspect_early_boot.py` 只检查电脑上的链文件及已回收 handoff，不访问设备。

本完整包已包含诊断工具；已有设备更新方式见 README-GPU242测试包.md。保留目标电脑自己的 `device`、`backup`、`target-inputs/personalized` 和全部部署收据。无需重新分区、重新下载系统或重装 OS/Data。

下面命令适用于本 GPU242 完整测试包。前期三色条与 handoff 反馈来自 GPU224；相关加载器诊断入口继续保留。已安装设备继续保留自己的布局和 Data，切换检查点不需要重新格式化。

## 照片已经说明什么

照片中绿、蓝、橙三条色带分别由加载器画出：进入汇编交接代码、完成缓存清理、关闭 MMU/cache 后到达跳转前标记。照片仍显示 UniXNU 背景，这是 framebuffer 原有内容残留，不代表菜单仍在处理按键。

没有第四条品红色带，只能说还没看到内核调用屏幕报告。原包选择检查点 0，本来就不会主动停下。不能据此断言内核没执行、GPU 故障或系统没安装成功。对方已确认照片使用工具生成的约 13.9MB ADT。

反馈中的 `window 0x40000000` 表示本次窗口 1GiB，不是平板物理内存只有 1GiB。这个数值需要与**同次启动**的 `handoff-*.txt`、其中的 `allocated_pa/allocated_bytes/kernel_checkpoint/callback_pa` 核对。目前没有足够证据把它判为故障原因。

## 对三个问题的回答

1. **内存日志不依赖 UFS；持久化日志依赖。** `loader_log_putc/loader_log_line` 可以先在 RAM 中记录。磁盘日志则要经过 `hostBringUp()`、系统布局/OS/SystemOS（以及启用时 Data）检查，再调用 `nabuLogBeginConfigured()`。`prepared-not-started / no committed record header` 的准确含义是没有找到有效的已提交磁盘记录，不能推出 RAM 内从未有日志。
2. **不能仅凭 Android 17 / DerpFest 判定不兼容。** XNU 不运行 Android 用户态；但 bootloader/UEFI 提供的内存与硬件初始状态、板级固件和目标数据仍影响启动。先定位检查点，再决定是否需要比对固件。当前没有要求刷回 MIUI 的证据。
3. **已有早期屏幕通道可以立即使用。** 检查点 1–5 在汇编阶段，后续在 C 初始化阶段；命中后直接画第四条品红色带和报告并故意停机。它不需要 UFS、USB 或完整 GPU 驱动。这是分阶段停点报告，不是持续滚动的 framebuffer kprintf 控制台。

USB CDC 实现在 `bsd_init` 之后启动普通线程，还依赖映射、时钟、PHY/SMMU 等。原 `prepare_chain.py` 使用 `--native-usb`，打包时会删除 CDC 参数并选择 `nabu-usb-native=1`；此时不能以没有 COM 串口判断 USB 初始化是否执行。不要把几组 CDC 开关当作最早期日志开关。

## 第一次只测试检查点 1

在**另一台电脑的原部署包根目录**打开 PowerShell。以下变量需要填为该目标机真实路径；不要使用原作者平板的收据。

```powershell
$gpu242Python = '.\host\python\python.exe'
$gpu242Kernel = 'artifacts/nabu-gpu242-dynamic/kernel.native-apfs.macho'
$gpu242Gpt = 'backup/gpt/替换为目标机分区后备份目录'
$gpu242OldPreparation = 'log/device/替换为上次准备目录/preparation.json'
```

当前完整包使用上面的动态容量内核。仅在旧固定 64GiB 布局需要与原 GPU242 实测内核对照时，将 `$gpu242Kernel` 改为 `artifacts/nabu-gpu-ready-v238/kernel.native-apfs.macho`。通过 `configs/selected-layout.json` 选择的新布局必须使用动态容量内核，包括选择 64GiB 的新布局。日志准备、链生成和部署始终使用同一个 `$gpu242Kernel`；内核变化后先回收上轮日志，再准备绑定本轮内核的新收据。

先将目标机手动恢复 Android。上次日志若尚未完整回收并清槽，使用上次 preparation 收据回收（即使预期日志 0 字节也保留原始槽证据）：

```powershell
& $gpu242Python -X utf8 tools/nabu_runtime_logs.py --collect --receipt $gpu242OldPreparation --gpt-backup $gpu242Gpt --output log/device/collect-before-cp01
```

只有工具报告回收及清槽成功后继续。已成功清槽的不重复这一步；既有输出目录保留，重复试验使用新目录。若之前用 `run_nabu_temporary_boot.py` 启动过，可按原 README 用它的 `--collect` 回收，以同时取得 ESP handoff；直接执行 fastboot 的那一轮没有对应 `run.json`，不能给它伪造收据。

为 cp01 准备新槽（下面使用原配置的槽 1），再生成候选：

```powershell
& $gpu242Python -X utf8 tools/nabu_runtime_logs.py --prepare --slot 1 --kernel $gpu242Kernel --inventory device/target --gpt-backup $gpu242Gpt --installation-receipt log/device/install-target/installation-receipt.json --output log/device/prepare-cp01
& $gpu242Python -X utf8 tools/prepare_chain.py --kernel $gpu242Kernel --checkpoint 1 --gpt-backup $gpu242Gpt --log-preparation log/device/prepare-cp01/preparation.json --output artifacts/target-chain-cp01
& $gpu242Python -X utf8 tools/inspect_early_boot.py --chain artifacts/target-chain-cp01 --output log/device/cp01-host-check.json
```

每条命令成功后再执行下一条。检查 `cp01-host-check.json`：`nabu_handoff_inputs_valid` 应为 true，`nabu-kernel-checkpoint` 应为 1，`marker_count` 应为 1，`unset_on_disk` 应为 true。这些仅确认电脑上的候选，不能证明平板实际加载了它。

部署同一候选：

```powershell
& $gpu242Python -X utf8 tools/prepare_chain.py --kernel $gpu242Kernel --checkpoint 1 --gpt-backup $gpu242Gpt --log-preparation log/device/prepare-cp01/preparation.json --output artifacts/target-chain-cp01 --apply
```

把部署命令输出的真实 `deployment.json` 路径填入下列变量，然后临时启动：

```powershell
$gpu242Deployment = 'log/device/替换为本次nabu-chain目录/deployment.json'
& $gpu242Python -X utf8 tools/run_nabu_temporary_boot.py --boot --gpt-backup $gpu242Gpt --deployment $gpu242Deployment --output log/device/boot-cp01
```

命中应显示第四条品红色带、`XNU CALLBACK REACHED`、`KERNEL CHECKPOINT - INTENTIONAL STOP`、`REASON=2`、`CODE=1`。这是预定停止，不会继续进入桌面。保留完整屏幕照片。

手动返回 Android 后，用本轮目录回收：

```powershell
& $gpu242Python -X utf8 tools/run_nabu_temporary_boot.py --collect --gpt-backup $gpu242Gpt --output log/device/boot-cp01
```

回收会保存 ESP 中的 `handoff-*.txt`。从 `log/device/boot-cp01/esp/EFI/Nabu16/` 选择本轮的新文件；目录中可能有旧轮次记录。可以加入本地检查：

```powershell
& $gpu242Python -X utf8 tools/inspect_early_boot.py --chain artifacts/target-chain-cp01 --handoff 'log/device/boot-cp01/esp/EFI/Nabu16/替换为本次handoff文件.txt' --output log/device/cp01-handoff-check.json
```

## 根据结果选下一步

| 屏幕结果 | 下一步 |
|---|---|
| cp01 仍只有三色条 | 核对本轮 handoff 是否 `kernel_checkpoint=1`、`callback_pa` 非零。若字段不符或无新 handoff，优先核对实际 ESP、ADT/EFI 路径；若相符，范围缩到进入 cp1 之前或回调/显示路径，仍不能单凭屏幕区分二者 |
| REASON=1，KERNEL EARLY EXCEPTION | 保存 CODE/ESR、ELR、FAR、LR、SP 和完整屏幕，不再靠换精简 ADT 猜原因 |
| REASON=2，CODE=1 | 改测试检查点 5；若 5 不到，依次用 2、3、4 缩小范围 |
| CODE=5 | 继续 12，再 17，再 21；若其中失败，按下面阶段表细分 |
| CODE=0x15（21） | 已到 machine_startup 之前；再排查调度、存储、USB 和用户态，不能再笼统叫“没进入内核” |

每次测试都走“上轮回收 → 新 preparation → 新 chain → 部署 → 临时启动”，将上例中的 cp01 和 `--checkpoint 1` 改为本次名称/数字。不要复用已启动过的日志准备收据。没有必要重装系统来切换检查点。

| 检查点（命令输入十进制） | CODE 屏幕十六进制 | 已经过的阶段 |
|---|---|---|
| 1 | 1 | 进入 start_first_cpu，保存 boot_args，尚未安装低地址异常向量 |
| 2 | 2 | 安装低地址异常向量并执行 OS lock 寄存器写入 |
| 3 | 3 | 初始页表准备完成，进入 common_start 之前 |
| 4 | 4 | common_start 中即将启用 MMU/cache |
| 5 | 5 | 启用 MMU 并执行 ISB 之后 |
| 10 / 11 | A / B | C 入口复制 boot_args / PE_init_platform(FALSE) 返回 |
| 12 | C | CPU 拓扑解析完成，尚非所有 CPU 已启动 |
| 13 / 14 / 15 / 16 | D / E / F / 10 | cpu_bootstrap / early clock / kernel_startup_bootstrap / cpu_init 返回 |
| 17 | 11 | arm_vm_init 返回 |
| 18 / 19 / 20 | 12 / 13 / 14 | serial_init / KPRINTF 启动阶段 / PE_create_console 返回 |
| 21 | 15 | arm_init 末尾，machine_startup 之前 |

30–35、40–44 是 11→12、12→13 之间的细分点；编号不是整体执行顺序。`REASON=2` 时 X4–X7 不是有效异常寄存器；汇编停点 `LOG BYTES=0` 是正常现象。

全部早期检查点通过后，恢复 `--checkpoint 0`。如需定时 RAM 日志报告，可以复制原 TOML，在 nabu8796 的 args 加 `loader_return_after=30`，再通过新增 `--config` 传入；它依赖内核调度/定时及返回路径能运行，不能用于证明硬死锁必然可回报。

## 回传的最小结果

完整检查点屏幕照片、`cp01-host-check.json`、本轮新 `handoff-*.txt`、部署/启动收据。不要回传 nonce key、个性化 NVM 或整份 personalized 目录。检查工具输出省略设备身份和固件原始值。

更新已在主机验证参数转发、ADT 身份/固件内容保留、现有 GPU242 回调槽和 handoff 字段解析；尚未在第二台平板验证。当前结论是补齐可见诊断入口，实际停点和根因仍待本轮屏幕证据。
