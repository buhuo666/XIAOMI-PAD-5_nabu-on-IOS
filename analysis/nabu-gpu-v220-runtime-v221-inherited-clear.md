# GPU220 实测与 GPU221 真实继承事务修复

2026-11-12。用户目标为 present 返回至 DPU 入口合计不超过5ms，IPC属于嵌套阶段；仅15秒场景测试。

## 已测结果与限制

GPU220内核32ed2a5、完整CI43138438550；用户态194e69b、CI43140019560。65对象/分支/加载器、APFS/6项读回通过后临时启动。用户确认桌面与触摸正常。

- 首次正式15秒 `1794450281149969-scene0-repeat1`：900提交/900完成、无nil或command failure，应用提交60/s；drawable平均15.774ms、P95 15.899ms。GPU219对应626/626、41.733/s、drawable平均23.037ms。这是应用提交结果，尚不等于真实新画面120fps。
- 首次trace窗口102.332–147.332s，正式场景157.250–172.250s，二者不重叠。不能用该trace声称四段延时改善。
- 第二次trace为246.086–338.042s，305403记录、0 dropped、已完整导出并ACK。场景 `1794450395781077-scene0-repeat1` 在正式0.212秒后失败：4次提交/完成、2次drawable_texture_nil。nil drawable计数本身为0，因为是drawable存在而texture为空。用户报告画面卡住，不能当完整15秒结果。
- GPU统计请求f2561cf6652b49a2b68f74c92b91cbed已在完整日志配对，累计1334提交/完成、fault/timeout/poison均0。尾部256任务不是正式场景的完整分布。

## 冻结的实际顺序

1. 246.088–268.894s存在2657次真实双层拒绝，sid `[18,10,0,0]`、enabled `[1,1,0,0]`、set7/clear4，全屏1600×2560。它们发生在第二次正式采样前，不能直接当作正式场景根因。
2. swap12308/sid16在268.906s接受，12309/sid17在268.923s接受。两次退休等待gate均成功，旧swap真实退休后才通知。
3. 268.931311s，CA提交layer1空清理12310，全部surface为0、set=clear=2；驱动仅完成该无资源事务，保留当前layer0扫描。268.931444s SwapEnd返回成功。
4. CA原版finish把页索引推进：page0持swap12310，page2仍持swap12309，二者surface pointer相同，page1为空；下次从index1检查两页。
5. 268.931615s起，can_update检查空page1和仍扫描的page2，SwapWait12309得到Busy。其后8285次can全部false、没有begin；原版CA页已推进，驱动活动事务没有推进，形成等待循环。
6. 应用继续取得72个新surface，272.092819s才出现空纹理，比冻结晚约3.16秒。记录支持回收停止后持续扩容，但没有明确底层分配错误码，不能断言DeviceOOM。

原版页推进与查询依据：20F66 can_update_ `0x188236024–0x188236148`；finish_update_ `0x188264980–0x188264994`。持久日志49477行记录layer1清理并保留layer0，49489行后旧swap持续Displayed/Busy。

## GPU221 改动方向

空layer1清理继续按FIFO处理；存在活动layer0时，应继承它并提交真实新扫描事务，在硬件接受后退休旧扫描事务。当前read lease持续保留并转移所有权：不能简单标记旧swap退休，也不能普通重新acquire后等待future writer，否则writer可能已被旧read阻塞，形成另一个依赖环。独立新mapping和surface引用遵循真实扫描接受；失败时不伪造成功；初始GOP尚无活动layer0时保留无资源清理。继承相同内容的扫描不能算新的像素画面。

上述实现已完成：24组真实Display/Scanout/PageTable/Mapper、9组FIFO/SwapWait、19组生命周期及Display ARM64通过。接受前旧Held唯一持有read，新Held仅持独立surface/display-use；真实接受且旧mapping退休成功后转移read，displayUse从2到1，只有不同surface真实替换后原lease才release。覆盖连续3次clear、map prepare失败、扫描超时和退休TLBI失败。GPU220实际ImageQueue flags含0x0c000000，原版did_display在该路径检查IOSurfaceIsInUse，因此持续display-use可防止当前扫描surface过早复用。仍需实机确认CA恢复推进。

另外，NativeAdrenoScheduler已实现同完整mapping handle内连续/重叠逻辑范围的精确合并，真空隙保留，active read仍追加原新增范围。18组生产scheduler/RB树ASan/UBSan及ARM64通过，4000片物理页对应连续逻辑范围时从4000条reservation降至1条。它针对旧样本约1.11ms的acquire成本；尚无实机收益数值。

## CA CPU 区间

首次空闲trace中的一个有效样本：begin-return→finish为7.046ms，CPU7.045834ms、off-CPU约0.000166ms；其中render_update为7.034ms。运行地址按slide0x577c8000还原为EAGLServer/MetalContext，SWContext为0。它是实际Metal路径，但属于空闲样本，不能替代正式626帧分布。

用户态c53b201继续拆MetalContext::collect与make_buffer_current的两个已确认数据表槽，保留参数/64位返回值/errno与调用后对象生命周期。68 marker ASan/UBSan通过，完整安装capability应31；新构建CI43142617452。分析对嵌套调用取时间并集，避免collect位于make_buffer内部时重复扣除。

验收脚本还修正了样本选择：FrameBench的measured标记在display-link回调时决定，不是延后的GPU提交时决定。现按run marker的PID/epoch与CSV行号精确关联；GPU219实际measured626帧中625帧有完整DPU关联，最后一帧有present但无唯一DPU输出，保留缺失。旧按提交时间选出的626帧含一帧warmup跨边界，并漏掉该末帧。旧总路径约27.4ms的量级不变，但不能继续称实际measured626帧全部已匹配。

## 证据保全

5,904,778字节连续日志及完整64MiB槽已回收到 `log/device/nabu-boot-20261112-220/runtime-log/`，清空读回通过，Android引导分区未变。日志未封口，不声称覆盖复位前全部输出。设备Android/USB，GPU221尚未准备日志槽或部署。GPU/5ms目标仍未完成。
