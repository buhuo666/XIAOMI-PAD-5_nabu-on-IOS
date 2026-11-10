# SSC 同连接采样与批量间隔控制

2026-11-10。实现和主机检查完成；未占用设备，尚无 iPadOS 真机重配结果。

`patches/nabu-sensors/NabuSscControl.h` 在原有 Census SSC 连接上重配已发现的
物理 SUID。它不修改 Census 请求数组，不建立第二个 QRTR 客户端，也不修改
`Census::Stream`。`tools/check_nabu_ssc_control.py` 负责独立协议编码、真实 Android
报文回放及内核编译检查。

## 协议依据与边界

依据均为已下载并审查的现有原始协议：

- `log/host/sensors-20261109/android/vendor-sensors/sensors/proto/sns_std.proto:47`：
  `sns_std_request.batching` 为字段 1；其 `batch_period` 为字段 1、uint32 微秒，
  0 表示不批量发送。标准请求的实际传感器 payload 为字段 2。
- 同文件 `:57`：省略 `flush_period` 时，正 batch 默认使用 batch_period，
  其余为 UINT32_MAX；本实现不发送 flush_only/max_batch。
- `sns_std_sensor.proto:20`、`:223`：msg513 的 `sample_rate` 为 float 字段 1，
  单位 Hz；ReportInterval 微秒转换为 `1,000,000 / interval`。
- 同文件 `:26`：on-change msg514 无传感器 payload，同 client 的后续请求在
  传感器层为 NOP。因此 ALS 的 ReportInterval 返回 Unsupported。
  BatchInterval 位于外层 client-manager request，可编码重配，但仍待实机核验。
- `log/host/sensors-20261109/reference/qmi-service-ssc.json`：Control msg0x20
  输入只有 protobuf Data 和 Report Type；client ID 为成功响应的输出字段。
  成功响应还应含 SSC Response。

复用 Census 的远端 node/port、QRTR 本地端口 0x100 及已获 client ID，是更新该
连接的必要设计约束。另开 0x102 不能假设会修改 0x100 的订阅。当前资料未独立证明
固件对 streaming 同 client/SUID 重配的替换行为；实际订阅数、采样速率与批量延迟
须在设备上测量。成功 QMI 响应表示请求被接受，不表示物理频率精确等于请求频率。

## 串行 worker 接口

全部 `ControlSession<IO>` 方法由 SSC owner worker 调用，不能在 IOUserClient
线程直接访问。IO 仅需已有的 `send_ssc(node,port,local,data,size)`。

1. `start(node,port,client)` 绑定 Census 已学习的连接。
2. 初始配置已成功、源确为实际采样 SUID 后，调用
   `bind(kind,suid,on_change,report_interval_us=40000,batch_interval_us=0)`。
   同 SUID 重复 bind 不覆盖后续已接受的设置；on-change 初始 report 为 0。
3. IOUserClient 通过一个锁保护的 mailbox 提交 kind/control/微秒，owner 调用
   `queue(...,now_ms,timeout_ms=1000)`。Queued 仅表示进入待发状态。
4. 每次轮询执行 `tick(now_ms)`。发送背压时在同一 deadline 内重试；成功发送后
   不重发，且始终只有一个 pending transaction。
5. 在 Census 收包前调用 `receive(node,port,local,bytes,size,now_ms)`；true 表示
   已消费该高位事务回复。低位 Census 回复及事件返回 false，继续原收包路径。
6. `take_result(completion)` 只提取终态并释放 pending 槽。Accepted 才能向
   IOUserClient 返回成功；Queued/Waiting 均不是成功，且不能被下一请求覆盖。

高位事务使用 `0x8000..0xffff` 的标准 16 位循环，Census 使用低位区域。匹配包括
远端 endpoint、本地 0x100、当前 transaction，以及成功响应中的原 client ID。
仅 QMI result/error 均为 0、client ID 存在且匹配、SSC response 存在且为 0
才能更新已接受设置。错误回复可以省略成功专属字段；缺失成功字段不能被接受。

ReportInterval=0 返回 BadArgument；所有正 uint64 微秒可编码为正常有限 float32。
转换通过整数长除法并按 ties-to-even 舍入，没有内核浮点运算。BatchInterval 超过
uint32 返回 BadArgument。每次重配都带完整已确认的另一项设置，明确发送
batch_period=0 清除以前的批量间隔。

`settings(kind)` 提供最近一次已接受的 report/batch 微秒供收样期限使用；尚未收到
响应的 proposed 值不会暴露。超时不能证明固件没有执行请求，后续完整重配仍以
匹配成功响应为准。暂时 stale/时钟失效仅使 native source inactive，不能据此丢弃
仍存在的 SSC 订阅设置；否则下一次 bind 会错误恢复 40000/0 的主机记录。
实际订阅被取消、失败或 session 结束时才调用 `unbind(kind)`/`stop()`。

IOUserClient 的有界同步等待由 `NabuSlpi.cpp` mailbox 完成。调用者超时/中断后，
mailbox 保持占用，直到 owner 丢弃尚未下发的请求或取走已下发请求的终态；不会
将迟到回复交给下一位调用者。该 header 本身不等待、不加锁、不触碰硬件。

## 验证

```powershell
python tools/check_nabu_ssc_control.py --capture log/host/sensors-20261109/android/ssc-live-back.jsonl --output artifacts/nabu-ssc-control-20261110 --kernel-compile-report artifacts/nabu-sensor-source-20261110/report.json
```

`artifacts/nabu-ssc-control-20261110/report.json`：

- 1,062 条真实 Android SSC 回复通过已有 Census 得到四路物理流和 client ID。
- 6 组独立 Python 编码逐字节验证保留 SUID、rate/batch 单位、显式清批量、ALS 无
  传感器 payload，以及 uint64 最大间隔。
- 110,192 个 interval→binary32 与独立 host long-double 结果一致。
- ASan/UBSan 覆盖同连接、单 pending、设置互相保留、背压、迟到/重复/错误回复、
  缺失任一成功字段、Queued/Waiting 超时、取消及高位事务循环。
- 使用现有真实 ARM64 内核编译参数实例化全部接口通过，浮点/SIMD 指令为 0，
  最大栈帧 416 字节；导入仅 memcpy、memcpy_chk 和测试 send 回调。

这些是编码、状态机及编译结果，不是 iPadOS 真实采样、CoreMotion 或自动亮度验收。
