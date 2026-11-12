# GPU218：约 28 ms CA 等待的短采样拆解

2026-11-12。用户要求取消下一次60秒基准，直接拆分GPU217不透明场景的约28.187ms完成回调→DPU入口等待。

## 本轮已实现

| 区段 | 实际记录 | 需要区分 |
|---|---|---|
| App取drawable、提交、完成 | 83–89，保留epoch/frame、surface、drawable | 23.41ms取缓冲等待及本帧生产节拍 |
| frontend实际present入口/返回 | 81/82，仅短诊断显式开启 | present同步部分，与完成后的异步等待分离 |
| CA消息投递 | 64–75，40205与40402，内核可信PID、begin token、消息生命周期 | 发送阻塞、队列驻留、交接/出队、copyout |
| CA是否能开始更新 | 96/97、108/109、102 | can_update结果、页面swap、SwapWait耗时/返回 |
| CA更新 | 98–107、114/115 | begin→finish间隔，已选surface/seed与样本时间 |
| framebuffer提交 | 110–112及已有DPU事件32–44 | CA提交到DPU、真实接受/退休的顺序 |

所有标记进入同一默认关闭的48MiB有界记录窗口。用户态四参数与可信PID/TID通过两条token配对；半条、丢记录、歧义单独计数。IPC40402不带seed，40205的context标识不能当queueID。CA没有直接CopyImageInfo/did_display钩子，finish前快照只证明当时保留的选后状态。

## 候选

- 内核源码8c078a5，完整构建43057210415；首轮43056374920因macOS测试夹具__unused重定义失败，已修复。
- 用户态源码9030626，专项构建43057539518全部通过。FrameBench1.3/revision4新增“CA等待定位（15秒）”，预热3秒、单不透明场景。
- 启动包artifacts/nabu-bootstrap-gpu-v218-ca/bootstrap.apfs，保留GPU217 CA_FORCE_TIMER=1；未启用CA_DISABLE_DETACHED。
- GPU675MHz、3drawable、原生1600×2560、120Hz、共享表面与真实退休保持现有行为。
- 动态部署/设备状态以log/host/gpu-v218/continuation.json为准；本说明不是启动成功或性能提升证明。

## 短采样后的判定

1. 先检查安装结果、事件覆盖、记录dropped以及App结束状态，覆盖缺失不得补成零耗时。
2. 分别报告present、IPC排队/交付、CA begin→finish、SwapWait/SwapEnd及完成→DPU的分位数。
3. 将CA页面swap与DPU事务、共享队列样本与App surface在唯一有效区间内关联，明确推断边界。
4. 只修复实测最长区段对应的调度、选样或回收问题，再以同一个15秒入口复测。

本轮不以短诊断结果宣称120fps或600秒持续验收完成。

## GPU218首次启动回收与GPU219修正

GPU218到锁屏，但上滑无效后息屏。4,980,641字节连续日志及64MiB原槽已保存于log/device/nabu-boot-20261112-218/runtime-log，清零读回通过，Data195→196。日志未封口，不声称覆盖复位前全部输出。

本次具体根因是组包脚本用Path.write_text写etc/inject.conf，Windows将LF转换成CRLF。原版init只把LF替换为分号，exec_inject_env只把空格和分号当分隔符；进程名尾部CR破坏精确匹配。运行证据：没有NABU INPUT启动和CA安装记录；backboardd已加载映像不含input/CA库；触摸硬件收到1107包、accepted1107、bad/bus-errors0，但backboardd仍等待主digitizer；09:20:27主动请求背光0，09:20:38 Set Blanked YES。Lockdown修复库同样未注入，HWInfo停留与会话超时吻合。没有把此次黑屏归到尚未安装的CA hooks或GPU执行故障。

改为原字节追加LF，artifacts/nabu-bootstrap-gpu-v218-ca-r2已APFS检查和10项读回。tools/check_nabu_inject_config.py执行实际configure_inject及exec_inject_env，验证旧6项库与CA均匹配，并注入CRLF复现本次失败，ASan/UBSan通过。

下一启动编号GPU219，复用同一已通过内核与用户态二进制，只修配置字节；状态log/host/gpu-v219/continuation.json。继续15秒不透明场景定位28ms，未取得新计时数据。
