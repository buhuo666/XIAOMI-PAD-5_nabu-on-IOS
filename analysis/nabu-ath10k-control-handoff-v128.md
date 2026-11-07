# v128：Nabu GLINK 到 ath10k 的控制交接

日期：2026-11-08，Asia/Shanghai。参考 Helium Raphael HEAD 57722468，与现有
Nabu/HakiOS 源码及 v127 已保存报告。本文的接入代码名称若标“拟新增”，是计划；
不代表已经接入设备。硬件启动成果不重做。

## 真实起点与最短边界

`log/host/wireless-v127/wireless-report.txt` 已有 QDSS accepted=1、两条真实
0x21 FW_READY、CFG 0x23 / MODE 0x22 成功、HTC READY(2 credits/0x888)及
WMI endpoint=1/max=0x7f8。其两次原注册状态是 0 和 0x4，发生在 FW_READY 前；
不能拿这两个历史状态代替新客户端注册后必须实际收到的 FW_READY 位。

最短完整交接是下一次正常冷启动中：Nabu 保留 PAS/QDSS/RMTFS/TFTP/服务注册/
MSA/BDF/CAL/MAC 的所有权；真实 FW_READY 后，把新的 host QMI 客户端、
CFG/MODE、CE/HTC/WMI/HTT 交给 ath10k。NabuGlink 继续是唯一读写 GLINK FIFO
的人，HakiOS QMI helpers 通过一个消息队列 adapter 使用它。
不用 Raphael 的整份 hakios.wifi.c 再启动第二套 SMEM/GLINK/ICNSS。

不能在当前已消费 HTC READY、建立 endpoint 的 v127 CE 实例上直接启动新的
ath10k：驱动假设自己拥有 CE rings 和 HTC 会话。完整候选应在 Nabu FW_READY
后、NabuWlanConfig::begin 和 nabu_wlan_runtime_start 之前分流；v127 成功
路径保留为独立基线。准备中的 DMA/SMMU 资源由统一所有者交接，不能让两套
allocator 同时占同一 SID/bank，也不能将现有 8MiB 直接冒充参考 44MiB 池。

## 1. icnss_ready 实际并不跳过 ath10k QMI

参考 `wifi/lx/ath10k/host.c:39`：platform_driver_register 先检查
lx_os_radio_powered；`xnu/files/bsd/dev/hakios.lx.c:234` 将它接到
hakios_wifi_icnss_ready。这只是 probe 的启动条件，qmi.c 不直接调用该函数。

实际函数链为：

```text
独立 host worker: hakios_lx_start -> lx_start
 -> ath10k_snoc_host_register -> platform_driver_register -> ath10k_snoc_probe
 -> ath10k_qmi_init
 -> qmi_handle_init -> transport.open
 -> qmi_add_lookup(0x45, 1, 0) -> transport.lookup
owner callback: qmi_server -> ath10k_qmi_new_server
 -> kernel_connect / hakios_qmi_connect
 -> ath10k_qmi_driver_event_post(SERVER_ARRIVE)
ath10k event worker: ath10k_qmi_event_server_arrive
 -> ath10k_qmi_ind_register_send_sync_msg
 -> qmi_txn_init -> qmi_send_request -> transport.send
 -> qmi_txn_wait（owner pump 独立接收并唤醒）
```

保存的 Nabu Linux `log/host/wireless-v76/source/drivers/net/wireless/ath/ath10k/qmi.c`
:750/:808 与参考 `wifi/lx/ath10k/patches/icnss-bootstrap.patch` 对应此分支：

| 阶段 | 真实请求/动作 | 是否重复初始化 |
| --- | --- | --- |
| 新 KNEL 客户端 | IND_REGISTER 0x20，client_id=0x4b4e454c；fw_ready_enable=1、msa_ready_enable=1，xo_cal 仅硬件支持时 | 是新的订阅/状态查询，不能伪造回复 |
| 注册回复 fw_status_valid 且 FW_READY 位为真 | 参考 patch 加 `ath10k_qmi_cap_send_sync_msg`，发送 CAP 0x24，再 `ath10k_snoc_fw_indication(FW_READY)` | 不发送 HOST_CAP/MSA/BDF |
| 没有 ready 位 | 原代码继续 HOST_CAP 0x34、MSA_INFO 0x2d、permission setup、MSA_READY 0x2e、CAP 0x24 | 这会与 Nabu 初始化重叠，必须禁止该回退 |
| MSA_READY indication | event_msa_ready 会 fetch_board_file、BDF 0x25、CAL 0x26 | preboot 交接模式必须不执行此分支 |
| 真正 host power_up | snoc_wlan_enable -> ath10k_qmi_wlan_enable -> CFG 0x23，然后 MODE 0x22(MISSION=0) | 应由 ath10k 唯一执行 |
| core 启动后日志配置 | core.c:3238 -> hif_set_target_log_mode -> ath10k_qmi_set_fw_log_mode -> QMI_WLFW_INI_REQ_V01 | 非 MSA/BDF；需透传真实结果 |
| host power_down | ath10k_qmi_wlan_disable -> MODE 0x22(OFF) | 仅停 WLAN 模式，不代替 PAS6 |

CAP 写入 qmi 的 chip_id/family、board_id、soc_id、fw_version/timestamp/build_id；
不能只手工设置 qmi->fw_ready 而跳过它。原件 patch 的这一行正是为了 ready
捷径仍具备真实 capability。

`host.c:48` 发布 qcom,msa-fixed-perm，使 qmi 的 setup/remove_msa_permissions
直接返回；这只阻止第二套 hyp assign/reclaim，不能自动阻止 MSA_INFO/BDF/CAL。
Nabu 应以“MSA 已由当前实例真实授予且仍持有”为该属性/接入门槛，不是常量成功。
同时保留无 wifi-firmware child、use_tz=true，不加额外 identity mapping。

最小 ath10k patch 应添加明确的 preboot/ready-only 属性或参数：

1. 保留实际 0x20 注册与 CAP；注册后不 ready 则本次 host 接入失败，不走冷启动。
2. 该模式不订阅 MSA_READY，且即便收到晚到 MSA_READY 也不触发 BDF 分支；
   不设置 no_msa_ready_indicator，因为 event worker 的该开关会直接执行 BDF。
3. 同一实例只交付一次 core-ready。现有 snoc_fw_indication 在 REGISTERED 后
   再收到 ready 会启动 recovery；不能把 Nabu 两个旧客户端的 ready 都送进去。
4. CAP 失败或 DEL_SERVER/PFR 后不再发 core-ready；禁止旧实例自动重新初始化。

这属于明确所有权交接，不应靠 adapter 假造 QMI success 或改响应位实现。

## 2. 端口交接：保留一个 owner，退订旧 KNEL

Nabu 当前端口为：0x4000 TFTP、0x4001 RMTFS、0x4002 SERVREG、0x4003 KNEL、
0x4004 DMON、0x4005/6/7 DIAG、0x4010/11 TFTP 数据。新 adapter 从未占用区
（例如 0x4020 起）单调分配编号，不复用旧端口以免迟到回复命中新事务。

参考 `hakios.wifi.c:4688` 在 icnss_bootstrap 后 qrtr_close 原 KNEL port，
然后才启动 host。qrtr_close:3198 会发 QRTR_DEL_CLIENT(6)，payload 为五个
u32：`{6, local_node=1, local_port, 0, 0}`，header type=6/from_port=被关端口/
to_port=0xfffffffe。Nabu 对应交接应在无旧请求 outstanding、MSA/BDF/MAC 完成且
真实 FW_READY 后，由 owner 排队旧 KNEL 的 DEL_CLIENT，再允许新端口 0x20。
DMON 初始化也应结束且不再发请求；保留其被动诊断或同样退订须明确，不能由它
重复启动。不要同时让 NabuWlanConfig 和 ath10k 发 CFG/MODE。

保留 Nabu SERVREG/PFR、TFTP、RMTFS、DIAG。端点变化/撤销或 wlan_process PFR
由原 owner 判定，然后撤销 adapter 当前实例并通知 host 下线；不是把新端点
公告当旧实例重新 ready。QRTR 本身没有“转交硬件”指令，以上是本机所有权状态。

## 3. 可直接复用的 ABI 与准确数据边界

本次比较：两树 hakios.qrtr.h 文本相同；hakios.qmi.h 只有说明中的文件路径
差异，结构/原型一致。实际 v79 prelink 基核导出了：

```text
_hakios_qmi_set_transport          0xfffffff0074f2e88
_hakios_qmi_handle_init_transport  0xfffffff0074f2e94
_qmi_handle_init                  0xfffffff0074f33ac
_qmi_handle_release               0xfffffff0074f33b8
_qmi_add_lookup                   0xfffffff0074f3454
_qmi_txn_init                     0xfffffff0074f34e4
_qmi_send_request                 0xfffffff0074f35b8
_qmi_txn_cancel                   0xfffffff0074f3714
_hakios_qmi_txn_wait_ms            0xfffffff0074f378c
_hakios_qmi_connect               0xfffffff0074f348c
```

这些仅为此次符号观察；链接按符号，不使用地址常量。qmi_handle 只有 sock 指针；
它指向 helper 自己的状态，不是 Darwin BSD socket，不能给它套系统 socket API。

`hakios_qrtr_ops` 是四个函数指针，arm64 大小 32 字节：

```c
struct hakios_qrtr_port *open(receive_fn, server_fn, void *context);
int send(struct hakios_qrtr_port *, uint32_t node, uint32_t to_port,
         const void *data, size_t length);
int lookup(struct hakios_qrtr_port *, uint32_t service, uint32_t version,
           uint32_t instance);
void close(struct hakios_qrtr_port *);
```

receive 回调为 `(void *,u32 node,u32 port,const void *,size_t)`；server 回调为
`(void *,bool arrived,u32 service,u32 version,u32 instance,u32 node,u32 port)`。
它们由同一 owner delivery 线程串行调用，可以睡眠，且在本地队列锁外调用。
close 返回后不得再调用该 port 的任何回调。send/lookup 返回 0 或 errno；
QMI helper 会把正 errno 转成负数，不能把 enqueue 的 bool 直接当返回码。

线格式是 QMI 7 字节头 `{u8 type,u16 transaction,u16 message,u16 payload_len}`，
全为 little-endian，不能用有填充的 C struct 直接序列化。QRTR v1 头为连续
8×u32，共 32 字节；v3 按现有 parser 的 16 字节+扩展读取。服务公告 instance
字段打包为 `version | (instance << 8)`，callback 拆开。instance=0 的 lookup
按现有接口意图表示通配；至少 service/version 必须与真实公告一致。
sockaddr_qrtr 的 family 在 offset0，node在4，port在8，arm64大小12。

CFG 输入 `ath10k_tgt_pipe_cfg` 为 6×u32（24字节，含reserved）；QMI目标项只
发前5字段（20字节）。svc项3×u32=12字节，shadow项2×u16=4字节，enable_cfg
为三个 count+指针对，不是线报文。现有 Nabu 配置为12 target/21 service/
12 shadow，含服务终止项；接入时用 ath10k 自己构造的表，不指针强转成
NabuWlanConfig::Pipe（后者没有reserved，只有20字节）。

## 4. NabuGlink adapter 的最小原生接点

拟新增纯消息状态对象及 native wrapper；不引入第二个 SMEM polling loop。
四个 ports、每 datagram 最大8192字节，固定有界队列；核心不拥有硬件资源。

| 接点 | 实际动作 |
| --- | --- |
| open | 保存两个兼容回调和context，分配未占用local port；不宣告FW_READY |
| send | 校验该实例/endpoint，复制完整QMI bytes到队列，返回入队结果；owner稍后发 |
| lookup | 保存选择条件；owner用已收到的真实NEW_SERVER公告回放当前endpoint一次，以后跟踪真实撤销 |
| owner发送 | 在 pump/tftp_flush 的同一owner线程调用 datagram；remote intent不足保留队首，不能伪报已发 |
| owner接收 | qrtr解头并处理confirm后，把动态local port数据交给adapter；核对当前remote node/port/实例再回调 |
| close | 禁止新发送/回调，取消未发队列；等待已领取的回调完成，由owner发DEL_CLIENT并最终回收port |
| PFR/DEL/BYE | 撤销当前实例，取消队列与旧RX，通知del_server；新公告不能自动复活旧handle |

`qmi_send_request` 在 transport.send 返回后立即 free 编码缓冲
（`drivers/modem/hakios.qmi.c:913..920`），因此不能存调用者指针。
当前 `NabuGlink::transmit[8192]` 包含32字节 QRTR 头，datagram 的实际最大载荷
只有8160。实现8192契约需要将owner暂存扩为32+8192，并保留填充；现有16KiB
GLINK FIFO足够。内部 `responses[8][1024]` 是其他服务回复，不能拿来放这批
QMI消息。所需长度必须按完整报文计算，不能截断到1024或8160。

callback只由owner领取，在队列锁外调用；close不是简单清指针。native层需
有回调/发送lease和等待机制：外部线程close等lease结束，owner回调内close则
标记关闭并在该回调返回后回收。不能从owner线程同步等待自己，也不能调用
ath10k lx_start/qmi_txn_wait 等待同一个owner提供响应。

qmi_receive 当前只按 transaction 找响应，没有额外核对remote身份；因此adapter
必须钉住公告的endpoint，并让已失效实例的回复无法到新handle。不要把不相关
服务的数据广播给全部ports。新端口不能覆盖仍活动的0x4003/0x4004路由。

`hakios_qmi_set_transport` 改全局默认，新handle才采用它，旧handle保留原指针。
最小方案在本机唯一Wi-Fi qmi_handle创建前设置一次；更明确的隔离方案是在
ath10k_qmi_init使用已导出的 hakios_qmi_handle_init_transport 指定adapter，
无需改变其它处理器的QMI默认值。

## 5. 最短可编译的分层切片与文件依赖

第一切片只编译消息adapter，不要求LinuxKPI或完整ath10k树：

- 新纯头 `patches/nabu-wireless/NabuAth10kQrtr.h`：端口、复制发送、lookup、
  实际公告/撤销、实例失效、回调领取/完成；仅C标准类型/内存操作。
- 新 `tools/check_nabu_ath10k_qrtr.py`：像现有check_nabu_glink一样构建生产
  状态机回放，ASan/UBSan覆盖8192、背压、端口隔离、公告迟到、关闭中的回调、
  PFR后晚到数据。测试只能证明消息契约，不是ready或硬件测试。
- native wrapper（后续拟新增NabuAth10kQrtr.cpp）包含本地
  `xnu/files/bsd/sys/hakios.qrtr.h`，用`extern "C"`接QMI函数；将不透明
  hakios_qrtr_port包装成状态机handle。锁、线程身份、睡眠/唤醒由它实现。
- NabuGlink.cpp 只增加owner侧发送/接收/公告钩子。先用
  hakios_qmi_handle_init_transport + lookup + connect +真实CAP0x24做控制面
  连通性验证；CAP可用新端口，不需要抢KNEL、改MODE或重做MSA。这一阶段仍不是
  完整host交接。CAP最小table可只解QMI通用result TLV，更多capability字段
  由已有IDL/实际qmi.c继续接，不合成响应。

完整ath10k目标随后才需要：参考`tools/mk-ath10k.py`固定Linux7.0.14与
FreeBSD15.1头、wifi/lx/patches、ath10k/include、lx_prelude、host.c、
lx_base/lx_80211/lx_wpa，及驱动
core/ce/hw/htc/htt/htt_rx/htt_tx/mac/wmi/wmi-tlv/bmi/p2p/swap/txrx/snoc/
qmi/qmi_wlfw_v01/debug、regd.c与生成crc表。默认脚本还强制LX_HAVE_SAE并编译
hostap/mbedtls/sae；若要WPA2优先减依赖，需一致关闭宏并核对所有调用，不是
仅省略SAE对象。此任务未下载或运行该构建脚本。

本次已有保存qmi.c/snoc.c与参考patch可确定上述控制流程，但所查目录中没有
完整Linux7.0.14解包树及qmi_wlfw_v01.c/h，不能声称完整ath10k已可本地链接。
先做纯adapter切片不受这一依赖阻塞；完整驱动构建应复用已缓存依赖，缺项由
主线程单独处理。

当前基核已有qmi helpers，但`lx_os_radio_powered`尚未导出，`lx_start`存在
不证明有驱动（hakios.lx.c提供weak ENXIO版本）。Nabu的xnu-build.sh第7行
写死ath11k.o，Raphael支持WIFI_OBJECT；完整接入需受控patch让其选择ath10k.o，
补lx_os_radio_powered并把radio_memory/address/firmware映射到Nabu真实资源，
通过`tools/build_8796_reference.sh`重建基核。不要重复定义全套lx_os或只把
ath10k.o追加到已经链接旧driver的内核。

## 6. 最小交接验收与停止顺序

控制面最小成功证据是：bootstrap的MSA/BDF计数不增加；原KNEL DEL_CLIENT后
新port实际0x20回复ready、实际CAP成功；只有ath10k发CFG/MODE，Nabu试验CE不启。
ready-only失败场景必须证明没有0x34/0x2d/0x2e/0x25/0x26请求；两条旧ready
不能触发两次core注册/恢复。之后才继续真实CE/HTC/WMI/HTT验收。

停止时保持router pump活着，先令ath10k停止工作、取消CE/IRQ，完成MODE OFF和
qmi handle释放，再由Nabu执行PAS停止/QDSS off/MSA回收。PFR时先撤当前host
资格并禁止新请求，host teardown放独立worker；不要在owner callback内
cancel_work_sync一个正等待QMI响应的worker。现有QMI没有“abort整个handle”
API，已等待事务可能要等待30秒timeout；新增即时取消若需要，应在helper层
按真实错误结束事务，不能伪造成功QMI包来唤醒。

NabuGlink的keep_running也要区分bootstrap、host attaching/active/lost；不能
继续要求旧NabuWlanConfig::Enabled才持有链接，否则交接后可能在30k ticks
自动收尾。这属于控制所有权接点，不改变已经验证的QDSS、MSA、供电参数。

## 接续实现：纯消息切片和原生 wrapper

主线程明确分配后，本子任务已新增生产文件
`NabuAth10kQrtr.h`、`NabuAth10kQrtr.cpp`、`NabuAth10kQrtr.api.h` 与
`tools/check_nabu_ath10k_qrtr.py`；没有修改 NabuGlink 或硬件启动代码。

纯核心仅管理一个当前 WLFW endpoint、4 个端口、各4槽 TX/RX（每槽8192字节），
新端口从0x4020单调分配。start_instance 必须等旧handles关闭，不静默复活旧
端口。announce/withdraw 接受真实0x45/version1公告；lookup只回放这项已知事实。
没有任何方法设置FW_READY或生成QMI响应。endpoint变化及PFR取消排队数据，
仅给已收到arrival的observer安排removal。

队列方法都要求调用者持锁。begin_send/begin_callback领取稳定lease，使用期间
报文槽不复用；finish归还。begin_close只禁止新工作，不是同步close成功。
finish_close在该port还有send/callback lease时返回Busy。此设计可回放交错，
但不自称线程安全；IOLock与等待由原生wrapper提供。

原生API供唯一GLINK owner使用：

- prepare分配并原地构造heap状态，不把约66KiB聚合对象放内核栈。
- start_instance绑定当前owner线程并注册hakios_qrtr_ops；transport()亦返回
  该表供显式handle-init使用。prepare须在客户端发布前单次调用。
- poll的send callback为
  `bool(cookie,type,from,node,to,data,bytes)`，type=1是DATA，type=6是
  DEL_CLIENT；true表示已复制到真实GLINK FIFO，false保留队列/退订重试。
- receive返回bool表示local port属于本adapter，包括已关闭/旧编号；即使来源
  不符或迟到而被丢弃，也返回true，防止旧服务路由再次处理这包数据。
- poll在IOLock外发送与执行回调，保护send/callback以及DEL_CLIENT lease；
  非owner调用返回EPERM，重入poll返回EBUSY。
- 非owner的同步close等待lease归还，然后保留native槽直到owner发出DEL_CLIENT。
  close返回后不会再调用其context。真实ath10k回调只post work；若调用者在
  正执行的owner回调内同步释放自身QMI handle，将触发显式契约错误，不能
  假装等待完成。需要由外部worker执行qmi_handle_release。
- invalidate使旧实例失效但继续允许owner poll发removal；shutdown停止delivery，
  等待所有lease和poll退出，不替客户端释放QMI handle。旧handle未close时
  start_instance仍失败，避免悬空callback context。

`log/host/wireless-v128/ath10k-qrtr-test/report.json` 已记录纯核心和完整native
wrapper源码通过ASan/UBSan；native测试将IOLock替换成host mutex/condition
variable，真实起线程验证close等待callback、shutdown等待DEL_CLIENT以及
停止后旧handle退休。已确认的数据包括8192完整复制、背压重试、真实公告回放、
wrong-source拒绝、实例替换、端口隔离、callback锁外执行。它不是设备测试。

本子任务还新增`tools/check_nabu_ath10k_runtime.py`供主线程验证其新runtime：
使用完整runtime生产源码和host DMA/GIC/thread peers，分别覆盖线程创建失败、
driver失败、启动中失效、SMMU fault及12路level IRQ的detach等待。runtime的
start()是被信任的FW_READY交接调用，不读取GLINK协议状态；因此测试仅验证
调用前powered=0与资源门槛，真实ready以前不得调用start须由GLINK集成测试
证明。PAS已停也是stop的调用前提，host测试不伪称执行了PAS。

主线程随后运行上述runtime测试，
`log/host/wireless-v128/ath10k-runtime-test/report.json` 已记录五项全部通过：
thread-failure、start-failure、lost-during-start、irq、smmu-fault。IRQ场景以
真实runtime的12个向量注册到GIC INTID446–457、edge=false；阻塞正在运行的
回调时detach确实等待，清除attached后旧pending不再进入handler。驱动worker
未停止时release与unmap计数均为0；DMA release失败也不解除别名映射。
这些仍是host peers，原生GIC/设备DMA效果需要实机证据。
