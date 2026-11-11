# GPU206 接管通过与 GPU207 翻帧证据

2026-11-11，Asia/Shanghai。GPU206 内核源码 `003b4456ecc601a4342ddb4644b64a4e67d45925`，
完整内核 CI42966618530。启动参数保持 `nabu-dpu=0 nabu-dpu-diag=1
nabu-dpu-live-identity=1 nabu-dpu-trace=0`，Hall 和 120Hz 配置保留。

## 已观察到的结果

| 独立操作 | 硬件/软件记录 | 用户画面反馈 |
| --- | --- | --- |
| 普通 HaltResume | halt13us/resume11us；IRQ/双vsync各新增6；underrun0；未启用halt-audit | 此后接管/恢复IRQ画面正常 |
| ActivateGopPolled | live identity5477us、XIN暂停0；4000页/上下文/路由匹配；8000个GOP样本一致；最终frozen0 | 桌面和触摸正常 |
| ResumeIrq | IRQ/双vsync各新增7；underrun0；页表配置保持 | 桌面和触摸正常 |
| 首次 FlipGop | 原始表面sid27，IOVA0x20000000；sequence1→2返回GOP；停留3000433us；IRQ/双vsync各363；释放成功/frozen0 | 只闪了一瞬间黑屏，无红蓝；返回桌面、触摸正常 |
| 第二次 FlipGop请求 | 请求仍留在AFC目录，request-before/result和独立IORegistry均停在第一次ID | 无画面变化，桌面触摸正常 |

首次翻帧的寄存器/计数/资源释放检查通过，**红蓝画面验收未通过**。
第二次请求没有进入内核，不计为硬件翻帧。完整日志确认普通助手在
`2026-11-11 14:07:24.368` 输出 `diagnostic request window ended`，第二次请求的
主机时间为14:08:13；助手循环原来限定240×5秒，root助手另限定2400×0.5秒。

新接管路径消除了本轮的接管后持续黑屏，但尚未将原始表面扫描或持续桌面呈现验收通过。
GPU205只读长暂停也黑屏、GPU206不暂停的接管正常，支持继续避开长停取数区间；
这仍不等于证明长暂停是所有黑屏的唯一原因。

## 日志保存

- `log/device/nabu-boot-20261111-206/runtime-log/slot-01.bin`：完整67,108,864字节槽快照。
- 同目录`runtime.log`：10,492,595字节已验证连续前缀；未封口，没有完整结束标记。
- `clearing.json`确认清空和读回；`run.json`确认Android引导分区未变。
- Data启动记录183→184，设备已恢复Android/USB；没有额外Android重启。
- 主机请求及读回位于`log/host/gpu-v206/`，`after-repeat/afc-readback.json`
  与`after-repeat/display-ioregistry-class.json`确认第二次请求未消费。

## GPU207 改动

保留已通过的live identity使能、IRQ恢复和翻帧提交顺序；新增只读证据：

1. 原始CPU红蓝表面在翻帧前及停留后，每行四个位置共10,240字，记录红/蓝各5,120、
   错误数与哈希。检查对象是被扫描表面，未复制桌面。
2. 在表面保持Active期间两次逐页对照CPU实际物理地址`ml_vtophys`、已固定描述符的
   `getPhysicalSegment(..., kIOMemoryMapperNone)`及完整L1/L2/L3路径，共4000页。
   首尾物理地址、叶描述符和首个错误IOVA另存，诊断不修改页表或提交状态。
3. 停留前后读取双VIG地址、stride和CTL flush，并输出SMMU全局SCR0。
4. 红蓝图案观察时间延长到10秒；只读观察之后仍执行原有GOP返回和退休，
   主机结果检查器独立拒绝像素、映射或停留地址不匹配。
5. 两层助手在本次启动中持续处理显式请求，关闭/重启才结束；启动时仍清掉旧请求。

本地实际函数验证：Display全文ARM64、Mapper实际代码和ARM64、13组诊断隔离、
20组原始翻帧/生命周期回归，77,824,000个原始像素检查通过。新增反例包括CPU物理地址
不符、描述符偏移错误、单个叶错误、上层表错误、过期token和真实像素篡改。
这些检查不能替代后续实机画面验收；GPU207尚未启动。

下一项仍是独立原始表面翻帧。仅在图案、桌面返回、触摸及资源结果均通过后接入桌面，
系统/App Metal兼容和持续高刷新验收继续保留在完整目标中。
