# GPU229：iOS Metal 提交线程 QoS 遗漏

2026-11-12，Asia/Shanghai。分析已保存的 GPU228 trace、合格前端保留源码和固定版本 runtime；本子任务未操作设备、日志槽、CI、提交或推送。

## 结论与测量边界

发现一项确定的 iOS 适配遗漏：runtime 已为 macOS 实现编译线程 user-initiated、提交/完成/handler 线程 user-interactive 请求，但三个 helper 都把 iOS 编译成 no-op。补丁 `patches/nabu-metal/0030-nabu-ios-thread-qos.patch` 将现有 Apple 策略接到 iOS。**这个遗漏已由源码确认；其对延时的贡献尚无实机测量，不能把它称为所有卡顿的根因。**

GPU228 的两种耗时需要分别处理：CA begin→finish 线程 CPU 平均约 11.245 ms，而 finish 本身 wall 平均 14.231 ms、线程 CPU 仅 0.568 ms。前者有真实 CPU 工作，后者主要是该线程不运行的时间。详细边界见 `nabu-os-ca-finish-v229.md`，不可把这两类都命名为 GPU 运算。

从 `ca-finish-20f66-v229/finish-runtime-frames.json` 单独选择 `finish_wall_ms > 33.33` 的 179 次 finish；每次都有通过真实输出 read lease 关联的 writer，复算保存于 `nabu-os-metal-cpu-v229-evidence.json`：

| 指标 | 此 179 帧结果 |
|---|---:|
| finish wall 合计 | 8.492268 s |
| finish 线程 CPU 合计 | 0.142540159 s |
| finish进入→对应writer GPUAccepted | 平均 46.042162 ms，P99 85.851 ms |
| 同writer GPUAccepted→GpuIssued | 平均 0.128285 ms，P99 0.211 ms，最大 0.252 ms |

主要长等待发生在该 writer 被 GPU 驱动接受之前。GpuAccepted 之后的内核排队和该任务本身的 GPU 执行不能解释之前的 46 ms；其他用户态线程在此区间是否等锁、等编译、等调度，现有 CA 线程 CPU 记录没有回答。这里的 0.128 ms 专指所选 179 帧，不与全窗口 GPU 任务总体均值混用。

## 当前前端到 runtime 的真实路径

合格保留输入为 CI43148373620 的 `nabu-family-cache/frontend-source/`；其 build-report 固定 runtime 源码为 `624bab3918de5b978e1101517abca2b4fa426565`、Rust 1.98.1，runtime patch 为 0001–0028。现有 patch 不修改 QoS helper。

原版 CA 的 finish 经 `0x188249f78`、Display+0x658 的 EAGLServer `flush_command_stream` 调到 MetalContext+0x170，即 `flush(true)`。其中 `0x18825f324` 调 `commitAndWaitUntilSubmitted`，必要时 `0x18825f3c0` 再调 `waitUntilScheduled`。原版虚表、汇编和这一调用连接的证据归档在 `ca-finish-20f66-v229/`。

当前 `NativeBridgeMetalFrontend.mm`：

- 第 972 行的 `commitAndWaitUntilSubmitted` 执行 `commit` 后 `waitUntilScheduled`。
- 第 1118 行起的 `commit` 执行 `flushSurfaces`，注册 scheduled/completed 回调，再调 Rust `nmb_command_buffer_commit`。
- 第 1151 行起的 `waitUntilScheduled` 先等 runtime scheduled，再等 `_schedulingHandlers` 的 dispatch group。
- `NativeMetalObjects.rs` 的 bridge 将 commit/wait 直接交给 runtime。runtime commit 将批次交给独立 scheduler，并不等价于同步内核提交。

runtime `command_buffer/mod.rs:3346` 的 `wait_until_scheduled` 调用 `waits_for_scheduling` 后通过 condvar 等状态。`command_buffer/group.rs` 的等待者帮助提交路径进入 `Scheduler::submit_before_waiting`；`scheduler/mod.rs:1560` 的 `plain_ready` 要求 `submits_without_the_program()`。有 scheduled callback 时不满足该条件。前端始终注册自己的 scheduled callback，因此通常不能靠这条等待线程路径立即提交。这是可见的结构约束，不是 46 ms 的独立实测归因；本补丁不删除回调、不提前宣告 scheduled、不改变 fence。

普通 draw 和许多属性调用都是本地 Objective-C→Rust C ABI→runtime：例如前端第 812/827 行的 draw/indexed draw 对应 `NativeMetalObjects.rs:2316/2327`，不是每次 draw 都发一个内核 RPC。设备无参数能力回答在安装时预计算，supportsFamily 也已有缓存；本轮非空 bind 均值只有约 0.053 ms，不能再次把旧 family 查询问题当作现有已证热点。

## QoS 修正范围与 ABI 证据

原版 `src/metal2vulkan/crates/metal2vulkan-runtime/src/exit_guard.rs`：

| helper | 原 iOS 行为 | 修正后 |
|---|---|---|
| `raise_to_user_initiated` | no-op | 当前 requested class 较低或未指定时请求 user-initiated；不降低 interactive，也保留已有高等级的 relative priority |
| `run_at_user_interactive` | no-op | 请求 user-interactive、relative priority 0 |
| `at_least_user_initiated` | 无条件 true | 使用真实 pthread getter 判断 requested class |

`spawn_user_interactive` 已被 scheduler、queue completion、handler pool 等线程使用；修正这些 helper 后原调用点自动生效。普通 `spawn` 没有新增 QoS 请求，Linux uclamp 代码保持原文。编译线程继续使用现有 raise 策略。

已核对本地 iPhoneOS16.5 SDK 的 `usr/include/pthread/qos.h` 和 `sys/qos.h`：两个 API 均从 iOS 8 可用；getter 返回 int 状态码，class/relative 是两个输出参数，**不是返回 class 的两参数接口**。class 为 4 字节，USER_INITIATED=0x19，USER_INTERACTIVE=0x21。与 libc 0.2.191 源码中 `new/apple/libpthread/pthread_/qos.rs`、`sys/qos.rs` 一致。libc 对 Apple 的公共 reexport 链为 introspection→pthread→qos，因此现有 libc 声明可用于 iOS，无需另造 FFI。

默认关闭的 `NABU_METAL_QOS_PROFILE=1` 诊断只在请求 helper 运行时读取实际 set 状态、getter 状态、class 和 relative，并附线程名/pthread handle；每进程最多记录 64 条。其读回仍是 **requested QoS**，不包含 override、进程 clamp 和内核实际 CPU 安排，不能用 `set=0` 声称已解决延时。

## 验证和重建要求

新增 `tools/nabu_metal_ios_qos.py` 的 `stage_ios_qos(root, metal)` 把静态 patch 加入合格前端的 `bridge/patches/series`，并返回 JSON 元数据。

本地已运行：

```powershell
python -m py_compile tools/nabu_metal_ios_qos.py tools/check_nabu_metal_ios_qos.py
python tools/check_nabu_metal_ios_qos.py --output build/ios-qos-check-v229-final --stage-only --ios-sdk build/nabu-ath10k/sdk-source/iPhoneOS16.5.sdk
```

结果为 `staged_not_run`：实际 patch 应用、Linux/plain spawn 原文检查、真实 SDK 的 setter/getter 函数原型/常量断言及 ARM64 Mach-O 对象编译通过。Windows/WSL 没有 Rust 工具链，所以本地未执行 Rust 或 Apple pthread；报告明确保留这两个 false 字段。

`check_nabu_metal_ios_qos.py --output artifacts/ios-qos-check` 在 macOS 默认执行：从已应用 patch 的生产文件原样提取三个 helper 和两种 spawn；用真实 API 设置五种起始 class，验证阈值/不降级、interactive 请求、worker 启动和普通线程与同父原生线程一致，共 20 个场景。另验证默认无诊断、开启后 13 条成功读回及 64 条上限，随后用 Cargo 1.98.1 构建 `aarch64-apple-ios` 并核对 ARM64 Mach-O。这里没有 pthread mock，也不把 macOS 执行等同 iPadOS 上机。

本补丁进入 Rust runtime，**必须重建 `libadreno_metal_bridge.a`**。仅运行原来的 frontend relink 脚本、继续链接旧 archive 不会应用 QoS 修正。父任务新增的集成入口为：

```sh
rustup toolchain install 1.98.1 --profile minimal --target aarch64-apple-ios
python3 tools/check_nabu_metal_ios_qos.py --output artifacts/ios-qos-check
python3 tools/build_nabu_gpu_submit.py --input inputs/qualified/nabu-family-cache --work build/gpu-submit --output artifacts/nabu-gpu-submit --llvm-as "$(brew --prefix llvm@21)/bin/llvm-as"
```

使用 Xcode 16.4、qualified CI43148373620 输入、LLVM21。集成必须先 stage patch，再对固定 runtime 运行 bridge `--target ios --manifest-only`、生成 lockfile、运行 bridge `--target ios`，然后将新 archive 链接进前端。新 runtime patch identity 会改变 shader cache 标识；性能验收须明确区分冷编译与预热后的测量。

## 仍需实机分段定位

下一轮按同一个 command identity 记录 commit进入/返回、runtime waitScheduled进入/返回、scheduled callback和前端group等待；原版 flush 记录 context/bool、wall 和同线程CPU。结合已有 read lease→writer completion→GpuAccepted/Issued/Completed，先确认长等待落在哪层。若仍在 scheduler 之前，再扩展 scheduler enqueue→pass、vkQueueSubmit进入/返回，以及现有 WorkCounts 的 held-for-binary/reencode/decode/host-step/check/event/earlier-commit、batch_hold_nanos 和 first_work_order_wait_nanos。不要用跨线程 wall 相加充当总延时。

`runCore` 存在全局 IOLock，但睡眠等待使用 `IOLockSleep` 释放锁；没有配对持锁区间就不能定量宣布它造成 46 ms。回收的 `gpu-stats-after-os/kernel-stats.json` 已有成对请求标记，256 项 ring 的最早 accepted 在约 446 s，晚于 trace 的 199.702–289.702 s。其内核均值和全 boot 累计方法耗时均不能直接代替此 trace 的逐帧结果。

`nabu-os-metal-cpu-v229-oom.json` 记录的是读取时整段 syslog 前缀：180 条全部属于 com.apple.WebKit.GPU，PID216/225/237 分别 3/82/95 条，设备墙钟 15:00:25–15:02:20。尚未做设备墙钟与 trace monotonic 的精确对应，不能将其归给 backboardd 或该测量窗口。

CA 总计低于 5 ms、App 提交到 DPU 硬件接受低于 8.32 ms 两项目标均仍待完整实机验证。当前合成路径输入与输出 surface 不同，不能复用直接显示时“同 surface 即同 App 帧”的关联假设。
