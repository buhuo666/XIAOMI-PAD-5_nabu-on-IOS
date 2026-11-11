# GPU218 后续：CA IPC 分段采集实现

日期：2026-11-12，Asia/Shanghai。用户将下一步收敛为直接拆分 GPU217 约 28 ms 的 CA 等待；本实现属于主任务后续诊断，未部署设备。此次仅新增 IPC 诊断 helper、安装器、host fixture 和本说明，没有修改 GPU/DPU 实现、操作设备或提交 Git。

**最小实现已完成，六个实际 XNU 函数的 ASan/UBSan host 检查通过。** 事件用已有默认关闭的 NabuGpuTrace 窗口记录；核心桥接与全内核构建由主任务整合。host 检查不等同于完整 ARM64 内核链接或实机验证。

## 消息形状与身份

原版 20F66 的 `_CAImageQueuePing_` 在 `0x1882ff2e0` 发送 ID `0x9d0d` / 40205；用户消息总长 `0x30`，options=1。它是 send-only，没有请求等待回复，但未启用 send-timeout，队列满时可以等待空间。`_CACImageQueueCollectable` 在 `0x1882e6864` 发送 ID `0x9dd2` / 40402，总长 `0x24`，options=`0x11`（SEND_MSG | SEND_TIMEOUT），timeout 来自参数。常见的 `CAShmemImageQueueCollectable` 直接调用传 timeout=0。

| 用户态消息偏移 | 40205 | 40402 |
|---:|---|---|
| `0x00–0x17` | Mach user header，simple | Mach user header，simple |
| `0x18–0x1f` | NDR 8 字节 | NDR 8 字节 |
| `0x20–0x23` | CA 路由/context identifier | queue identifier |
| `0x24–0x27` | ping flags | 无 |
| `0x28–0x2f` | input time 的原始 double bits | 无 |

40205 的 identifier 取 queue shared `+0x3c`；为 0 时取所属 CA Context 的方法结果。此字段不是 IOSurface ID、drawable ID 或 insert seed，不与 collectable queueID 直接等同。发送端先由 queue `+0xc0` 找 Context，再取得其 server port。`__XPing` (`0x1884c150c`) 是另一个仅 `0x18` 长的消息处理函数，不能因名字相同就把它当成 40205 的接收实现。

40402 的 `__XImageQueueCollectable` (`0x1882e7be8`) 明确检查 non-complex 和 `0x24` 大小，读取 `+0x20` 调 `CAImageQueueCollectable`。后者将此 ID 与进程中各 queue 对象 `+0x1c` 比较。`CAShmemImageQueueCollectable` 的 seed 参数只用于 shared `+0x24` 去重，**没有进消息**。IPC 记录因此不伪造 seed；精确关联 drawable/insert seed 需要 CA 侧记录。

XNU 的 `mach_msg_header_t` 在本 64 位内核中长 32 字节，user header 长 24 字节，copyin 将消息长度增加 8。helper 检查 `sizeof(mach_msg_header_t)+24/12`，从 `ikm_udata(kmsg,0,false)` 读取 body；支持线性和分离 user data 的 kmsg，绝不将用户态偏移直接加到 kernel header 上。只接受两个 ID、精确长度、simple 消息以及本机 NDR 形式。读取全部使用复制完成的内核内存，无额外 copyin。

发送 PID 在 trap 的 copyin rights 之前取当前 task；此时 trailer 尚未初始化。其余 hook 从 `ipc_kmsg_get_trailer(kmsg,false)->msgh_audit.val[5]` 读取发送 PID，这一值由 XNU `ipc_kmsg_init_trailer` 写入。接收 PID 取实际接收 thread/task。没有把进程私有的 Mach port name 当作跨进程身份。

## 实际 hook 与所有权

下面行号为原始 `src/xnu-8796`，安装后会顺延。

| 文件 / 函数 | 位置和记录 | 所有权与限制 |
|---|---|---|
| `osfmk/ipc/mach_msg.c` / `mach_msg_trap_send` | 原 844 行之前：SendBegin + SendPayload；copyin 失败、`ipc_kmsg_send` 返回后记录原始结果；最终 return 记录实际 trap 结果 | 完整 body 已复制，调用方独占 kmsg。begin 保存 token、cookie、payload；成功 send 可能已使接收方释放 kmsg，之后仅用栈快照 |
| `osfmk/ipc/ipc_mqueue.c` / `ipc_mqueue_post` | enqueue 完成后 Queued，peek 也是 queued；将 `ith_kmsg/ith_seqno` 交给 waiter 后、resume 之前 Direct；未取走的 LARGE 为 ReceiveNotTaken；失效端口导致销毁为 Dropped | queue port/waitq 锁内记录已发生的入队或交接；不改变原锁操作。正常 enqueue 的 QoS 返回值仍只决定是否 KNOTE |
| 同文件 / `ipc_mqueue_select_on_thread_locked` | 原 1173–1182：真正 remove/assign 后 Dequeued；LARGE 保留消息时只记录 ReceiveNotTaken | 持 queue 锁。不能将 peek 或 LARGE 未出队当成收到消息 |
| `osfmk/ipc/mach_msg.c` / `mach_msg_receive_results_kevent` | 原 230 行之后且 copyout 之前：ReceiveBegin + ReceivePayload；原 306/381 的返回处：ReceiveResult | 仅 SUCCESS 或不带 LARGE 的 TOO_LARGE 才拥有 kmsg。最后可能已释放/变换 header，结果只用开始时保存的 token/cookie。普通 receive 与 kevent 共用此路径 |
| `osfmk/ipc/ipc_kmsg.c` / `ipc_kmsg_send` | 原 2903、2940、3067 的 circular、inactive、等待期间端口死亡销毁分支 | 独立标记 Dropped，保留 XNU 原样返回 SUCCESS 的语义，不能把 SUCCESS 都算成消息交付 |

最早的 SendBegin 在完整 body copyin 成功之后，所以尚未成功复制消息体的错误不被冒充为“完整形状匹配的 CA 消息”。SendResult phase=1 表示 rights/filter copyin 失败，phase=2 表示 `ipc_kmsg_send` 原始结果；SendReturn 包含原来的 pseudo-copyout 错误位叠加。接收侧包含 header/body/用户地址拷出失败的真实最终状态。

`ipc_mqueue_send_locked` 的容量等待语义完全保留：没有 timeout option 时 deadline=0，可阻塞等待；带 timeout=0 时队列满直接 TIMED_OUT；kernel limit、interrupted、restart 各保留原始分支。该函数本身未增加 hook，但 host 测试执行其真实函数体验证发送阶段记录覆盖这些结果。

## 连接 ABI 与事件字段

文件：`patches/nabu-diagnostics/NabuCaIpcTrace.h`。主任务的 XNU-owned bridge 提供：

```c
uint32_t nabu_ca_ipc_trace_window(void);
void nabu_ca_ipc_trace_record(uint32_t window, uint32_t event,
    uint64_t identity, uint64_t a, uint64_t b, uint64_t c);
```

window=0 时 helper 不解引用 kmsg，不取 trailer、不读取 payload、不分配 token。bridge 的 record 必须遵守 expected-window 检查，直接进入现有 `recordWindow`；不能在 callback 中分配、日志、发 Mach 消息或取得 IPC 锁。

| 事件 | identity | a | b | c |
|---|---|---|---|---|
| 64 SendBegin / 71 ReceiveBegin | begin token | kmsg cookie | senderPID:messageID | flags:bodyID |
| 65 SendPayload | send token | inputTime 原始 bits | options64（copyin 前原值） | send timeout ms |
| 66 SendResult | send token | cookie | 原始 status | phase 1/2 |
| 67 SendReturn | send token | cookie | 最终 trap status | 0 |
| 68 Queued | cookie | senderPID:messageID | flags:bodyID | msgcount:queueHeadSeqno |
| 69 Direct / 70 Dequeued | cookie | senderPID:messageID | flags:bodyID | receiverPID:assignedSeqno |
| 72 ReceivePayload | receive token | inputTime bits | receiverPID:assignedSeqno | 初始 receive status |
| 73 ReceiveResult | receive token | cookie | 最终 receive status | copiedAuxBytes:copiedMsgBytes |
| 74 Dropped | cookie | senderPID:messageID | reason | 原始原因值 |
| 75 ReceiveNotTaken | cookie | senderPID:messageID | flags:bodyID | receiverPID:status |

`high:low` 是两个 32 位整数打包。40402 的 flags/inputTime 为 0，表示 wire 没有该字段。queueHeadSeqno 只是入队时队头序号，不是该消息已分配的 seqno，不用于单独建立身份。drop reason 为 1 circular、2 inactive、3 等待期间端口死亡、4 post 阶段销毁。事件 76–79 暂未使用。

begin token 由 `mach_msg.c` 中的原子计数器分配；SendBegin 和 ReceiveBegin 均在该同一翻译单元。begin/result 以 `(window, token)` 配对，不能只凭 cookie。Queued/Direct/Dequeued 使用 opaque kmsg 地址作为窗口内对象生命周期键；这不是 user port、跨窗口永久身份或帧 ID。

host 解析器按记录顺序为 cookie 建立活动 SendBegin 生命周期，收到 Direct/Dequeued、ReceiveBegin 或 Dropped 后更新所有权。消息可能已 ReceiveResult 并释放，甚至相同地址已被下一条消息使用，之前的 SendReturn 才到达；该返回仍用原 send token。窗口开始前已有消息、窗口切换、丢记录和重复 begin 边界全部保留未匹配/歧义，不能用“最近时间”跨生命周期补齐。

## 锁、时钟与热路径

没有新增 IPC 锁，也不改变现有获取、释放、等待或唤醒顺序。队列 hook 的锁顺序是已持有的 IPC port/waitq 锁 → NabuGpuTrace 的 IRQ-safe recorder 锁。既有 recorder 只做有界固定记录写入和状态更新；控制/导出路径不会在持 recorder 锁时调用 IPC。主任务桥接必须维持这个单向顺序。

快照来自已驻留的 kmsg、body 和 trailer；无用户页访问、分配、IOLog、调度或睡眠。采集使用现有 recorder 时间基准，不重新解释 inputTime double。发送/接收 hook 在 IPC 线程路径；即便 recorder 禁中断，也没有硬 IRQ 中的分配或文本输出。

一个正常排队消息约 9 条 trace（SendBegin/Payload、Queued、SendResult/Return、Dequeued、ReceiveBegin/Payload/Result）；直接交接少一条。若两方向各 120 条消息/秒，增加约 2160 条记录/秒，不把通知数视为帧数。是否足够容量仍按本轮实际 record count/dropped 验收。

可直接得到的时间段：

- SendBegin→Queued/Direct：rights/filter/importance 处理、队列容量等待和 post。
- Queued→Dequeued：消息队列驻留时间。
- Direct→ReceiveBegin：接收线程恢复与进入 receive continuation。
- Dequeued→ReceiveBegin：出队后的内核接收处理。
- ReceiveBegin→ReceiveResult：copyout 与向用户地址交付。
- collectable ReceiveResult→nextDrawable 返回：需要与 CA/App 埋点联合；内核拷出成功不代表 dispatch callback 已执行。

## 文件与验证

安装：

```text
python tools/prepare_nabu_ca_ipc_trace.py --tree <prepared-XNU-tree> --output <report.json>
```

也可直接调用 `prepare_nabu_ca_ipc_trace.install(tree)`。仅变更 prepared tree 的三个 IPC `.c`，复制 helper 到 `osfmk/kern/NabuCaIpcTrace.h`。桥接 C unit/编译清单由主任务登记。`src/xnu-8796` 原树未直接改写。安装依据精确锚点，重复执行幂等。

测试：

```text
python tools/check_nabu_ca_ipc_trace.py --output log/host/gpu-v218/ca-ipc-check
```

留存：`report.json`、`installed.patch`、编译/run 日志和提取的 `actual_ipc.cpp`。实际执行六个 patched XNU 函数：`ipc_mqueue_post`、`ipc_mqueue_send_locked`、`ipc_mqueue_select_on_thread_locked`、`ipc_kmsg_send`、`mach_msg_trap_send`、`mach_msg_receive_results_kevent`。队列、端口、waitq/turnstile 调度、用户 VM copy 和 bridge 使用明示的 host 替身；没有运行 XNU 或设备。

已覆盖：精确形状与非线性 body；window=0 不解引用；开启/关闭后相同 IPC 队列和返回行为；等待方直接收取并在发送返回前释放消息；排队及 KNOTE；满队列 timeout/interrupted/no-buffer；send-only 等待空间；copyin/pseudo-copyout 状态；API success 但消息销毁；LARGE 未出队/破坏性 too-large；peek；copyout header/body/用户地址失败；同 cookie 的不同 begin token；旧窗口迟到结果；4 线程共 400 个唯一 begin/result token；helper 的 C11 编译运行。ASan/UBSan 均通过。

静态原版消息证据在 `analysis/ca-ipc-trace-20f66-v218/`，沿用已下载缓存，没有重新下载或哈希审计。正式 CPU/IRQ 时序开销、完整 ARM64 内核链接、真实消息频率与 CA 后续阶段仍由主任务本轮验证。
