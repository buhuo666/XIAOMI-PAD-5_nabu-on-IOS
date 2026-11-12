# Nabu 显示刷新率核对：硬件、OS 与不同画面

2026-11-12。本报告只使用已收集的GPU185/GPU226证据和现有源码，未操作设备、未新增CI或驱动改动。`v228`为调查编号，不代表已部署GPU228。

## 结论

**已有证据支持DPU的双DSI视频输出时序约120Hz，不能把当前问题解释为“两个60Hz中断被相加成120”。** `fb_hz=120`、`fb_ca_hz=120`、`UIScreen.maximumFramesPerSecond=120`分别是配置/发布或客户端能力读数，本身不证明物理刷新；但本项目另有独立MMIO帧计数和真实IRQ证据。

**120Hz输出时序、120次OS回调、120个被接受的App事务，仍不是“肉眼每秒看到120幅不同且及时的画面”的同义词。** 缺少全帧内容唯一性与面板内部扫描/光学逐帧证据；系统桌面/多层合成体验也不能由单一全屏不透明基准替代。

## 三层证据分开

| 项目 | 来源和实际含义 | 本轮可下结论 |
|---|---|---|
| `fb_hz=120` | `log/host/gpu-v218/unixnu.toml`，被226沿用；配置模式/周期及非DPU软件后备的节奏 | 是请求/发布值，不是MMIO测得的面板模式 |
| `fb_ca_hz=120` | `MiniIOMobileFramebuffer::publishRefresh`形成32.32格式min/max/step interval，另发MachTime step | CA获知120Hz能力；它不会在此处写DSI/面板时序 |
| `screen_maximum_fps=120` | GPU226 FrameBench JSON | UIKit报告的最大能力，不是实际每秒独立画面统计 |
| `display_link_callbacks=1800` | GPU226正式15秒 | 基准收到120次/s回调；单独看此数字无法排除重复内容 |
| 硬件VBlank/双INTF计数 | GPU226原trace event39 | 正式15秒1800个master边界，三组计数每次均+1，约120Hz真实接口时序 |
| App→真实DPU接受 | GPU226完整1800帧关联，event32/36/37/43 | 所有App帧对应真实翻帧接受，相邻接受双INTF各+1；不是每帧像素不同的证明 |

生产接入由`tools/prepare_nabu_display_sync.py`完成：DPU启用后`armVSync()`立即返回，软件timer不再生成VSync；`hardwareVsync()`采用`sample.masterTimestamp/masterSequence`。实际226日志383/386行分别记录hardware vblank start=0及120Hz hardware vblank selected。源码目录里未经该准备脚本改写的旧MiniIOMFB，不能被误当作当前已编译内核的完整行为。

## 硬件120Hz不是双路相加

`patches/nabu-display/NabuDpuVBlank.cpp`直接读取：

- MDSS物理基址`0x0ae00000`；INTF1=`+0x6b800`，INTF2=`+0x6c000`。
- 每个INTF的`TIMING_ENGINE_EN +0x000`、`FRAME_COUNT +0x0ac`、`LINE_COUNT +0x0b0`。
- IRQ115；MDSS master VSYNC bit27、slave VSYNC bit29。只有master事件且master帧计数实际增加，才按其差值推进`masterSequence`。slave-only事件不推进；同一master计数的重复IRQ不推进；合并IRQ不虚构漏失回调。
- `NabuDpuDisplay::vblank`还要求sequence实际变化且无fault，才向OS通知。多个IOMFB客户端各自的event44投递次数不可相加为刷新帧数。

重新读取GPU226已保存`trace-default/records.bin`，正式区间134896093.073–149896093.073 us内：

| 指标 | 值 |
|---|---:|
| master VBlank记录 | 1800 |
| 首/末master sequence | 13262 / 15061 |
| 首/末INTF1帧计数 | 15957 / 17756 |
| 首/末INTF2帧计数 | 15957 / 17756 |
| 相邻三个计数是否全部各+1 | 是，1799组全部成立 |
| master IRQ时间间隔均值 | 8.333451 ms |
| 最小/最大间隔 | 8.296 / 8.370 ms |
| App接受间隔均值 | 8.333447 ms |

原始汇总在`analysis/nabu-panel-refresh-v228-evidence.json`。IRQ时间是进入IRQ时观察值，不是面板第一像素时刻；几十微秒抖动不能直接等同面板扫描抖动。

更早GPU185在OS仍发布60Hz时就进行了独立250334 us的MMIO轮询：INTF1和INTF2分别从2539到2568，29次变化、每次只+1，分别估得8.330714 ms；最大采样间隔1.145ms。这与后续IRQ模式相互验证，未依赖本轮120Hz配置数字。原始`log/host/gpu-v185/dpu-snapshot.json`、解释`analysis/nabu-display-hardware-120hz-v185.md`。

## 模式来自哪里，Android遗留60Hz是否可能

当前驱动接管的是引导环境已运行的双DSI CPHY **video mode**，左右各800×2560，共1600×2560。它不在每次翻帧重配面板：`NabuDpuScanoutCore::initialize`逐项验证已观察拓扑/时序；`writable()`白名单只允许源地址、stride、CTL flush、VIG强制时钟及VBIF halt，**不允许写INTF timing、DSI PLL或panel命令**。

两种Nabu K82 XML均打包进UEFI设备配置，均包含：

- DSIRefreshRate=`0x780000`，16.16表示120。
- dual controller mapping=`00 01`；slave skew=2 lines。
- 每半边800 active +20 HSync +20 HBack +44 HFront =884 clocks。
- 2560 active +4 VSync +168 VBack +26 VFront =2758 lines。

GPU185实际寄存器为`HSYNC_CTL=0x03740014`、`VSYNC_PERIOD_F0=0x2533b8`，后者/884=2758；VStart/VEnd对应2560 active lines。两路都匹配。`NabuDpuScanoutCore.cpp`把这些值作为实际接管条件。

因此“Android选择60Hz后DPU就一直以60Hz运行”与已收的GPU185/GPU226接口计数不符。UEFI配置文件只是意图证据，不能单独证明每次厂商DisplayDxe初始化顺序；但本次接口实测已经提供独立回答。

仍未排除的范围是面板内部厂商寄存器/扫描策略与输入视频不同步的情况：本轮没有读取panel当前刷新模式寄存器、独立TE边沿或光学输出。DPU INTF帧计数和VSYNC不是TE计数，双DSI的左右半屏也不是两帧。现有数据没有指向“面板内部仍60Hz”，但不能将接口120Hz扩大为对面板内部每行每帧行为的证明。

## 需要时可复用的最小读数字段

目前判断接口120Hz已无需再跑新测试。后续同一启动如需验证模式是否变化，优先复用已有trace与只读snapshot能力，记录同一Mach时间域内的：

1. 两路INTF timing enable、frame/line count，以及HSYNC_CTL、VSYNC_PERIOD_F0、VStart/VEnd、HCTL；单独计算每路frame delta/实际elapsed。
2. master sequence和masterTimestamp、VSYNC计数、underrun与fault；只统计master帧前进，不能加总两路/多个客户端回调。
3. 对实际画面事务关联CTL flush完成、双INTF前进、SSPP源地址/stride及swap/surface/mapping/scan sequence；event56空操作交接排除在真实硬件接受之外。

现有`NabuDpuSnapshot`可读1；现有`NabuDpuVBlank::snapshot`/trace可读2；GPU链分析及event32/36/37/43可读3。此处没有启用TE或读取DSI/panel命令的实现证据，不推荐为了重复证明已有120Hz而临时写这些控制寄存器。

特别注意：旧MiniIOMFB的`fb_measure`代码仍是SM7325手机地址`0x0ae36000`，**不应在Nabu用它代替上述Nabu专用snapshot**。

## 对卡顿问题的含义

当前应继续区分“帧是否及时产生/选中/提交”“显示驱动是否接受所有实际合成形态”“接受的帧是否包含不同内容”，而不是仅把OS发布率改高。GPU226总链仍15.204ms；驱动明确只支持当前全屏单主层的直显，额外层会拒绝，不能把该基准表现推广到桌面、多窗口或普通App的流畅度。原始画面仍卡的用户反馈成立，接口120Hz不会使它自动失效。

本报告不认为显示驱动已经完成，也不把缺少面板内部/光学证据作为停止现有可验证优化的理由。
