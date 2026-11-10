# SLPI FastRPC 初始化与下一轮传感器实测

2026-11-10，Asia/Shanghai。用户要求继续，直到传感器在iPadOS内正常。sensors02
只验证七个QMI请求成功应答，实际SUID和样本均为0；没有将其当作修复通过。

## mode3 候选

候选内核：`artifacts/nabu-sensors-fastrpc-20261110-r6/kernel/kernel.native-apfs.macho`。
参数`nabu-slpi=3`，沿用已实测display01基底及原有63个对象。实际链接后9,247个
直接分支和2,850个远跳转通过，48个原组件范围保留。没有替换EFI。

启动包：`artifacts/nabu-bootstrap-fastrpc-20261110-r2/bootstrap.apfs`，84,459,520字节。
在原组合包Boot中加入`/rpc/files.bin`，298个文件和真实空目录有逐字节原生读回。
缺少的五项soc0属性已从本次Android只读补齐，归档共299条、9,880,233字节。
原始捕获保存在`log/host/sensors-fastrpc-20261109/soc0-live-20261110`。
详见[nabu-fastrpc-files-20261110.md](nabu-fastrpc-files-20261110.md)。

新增实现：

- 在同一GLINK ring上独立处理IPCRTR与`fastrpcglink-apps-dsp`，channel、intent、
  分片缓存及关闭应答分开。FastRPC使用原DT的64个100字节接收intent。
- SLPI SID0x5a1的34位IOVA从0x180000000起，独立租用SMMU上下文；8MiB真实共享
  内存及页表在PAS停止后才能释放。32位WLAN/音频实例保持原有默认参数。
- FastRPC attach、listener init2/next2、remotectl open/register与apps_mem拥有
  独立context及共享区。next2服务反向请求时，动态open/register仍能完成；正常
  保留default listener句柄，依据原版二进制修正了早期参考的提前close顺序。
- apps_std提供原机归档的只读文件/目录服务。ADD_PAGES执行真正的DSP mmap调用，
  返回DSP应答的地址，不能用IOVA冒充；未知方法及未支持的修改返回错误并记录。
- 注册成功后等待真实registry SUID事件，QMI应答本身不算就绪。registry最多15秒，
  再开始既有七类发现与8秒采样。整个mode3探测有60秒上限，正常停止GLINK和PAS。
- 前三条样本额外记录SSC/Mach/physical/virtual counter与实际频率，供同次启动的
  时钟对照，尚未凭静态19.2MHz说明发布原生时间戳。

## 已执行检查

| 检查 | 结果与保存目录 |
| --- | --- |
| 原机kernel结构与Qualcomm listener oracle | ASan/UBSan通过；`sensors-live-20261109/fastrpc-host-checks` |
| 原机文件服务method/packed请求 | ASan/UBSan通过；`sensors-live-20261109/fastrpc-files-host-final` |
| 会话并发/映射/registry | 70项0失败；`sensors-fastrpc-20261109/session-host-review-r2` |
| 两路GLINK分片和intent隔离 | 原DT与ASan/UBSan通过；`sensors-fastrpc-20261109/glink-host` |
| 34位SLPI映射与原WLAN/音频回归 | ASan/UBSan通过；`sensors-fastrpc-20261109/dma-host` |
| 内核编译 | 单栈帧上限4096；r6最大2192字节，FP/SIMD为0 |
| 最终r6加载器 | ASan/UBSan通过；`sensors-fastrpc-20261109/kernel-window-r6` |
| 持续SSC回放 | 真实Android包回放及主动停止通过；`sensors-fastrpc-20261109/continuous-census-host` |

上表检查目录均相对`log/host/`。独立审查保留四个修复前失败：附加未知ADD_PAGES
flag仍被接受、64位unmap长度截断、registry超时后及QMI失败后被迟到事件误恢复。
修正后70项通过。旧测试另有一项预期未随reply迁入DMA池更新，单独记录为测试错误。
第一次链接因262KiB reply落入静态对象而超出原__DATA余量；已移入会话拥有的DMA
工作区，r2起链接通过，没有扩大加载器边界来绕过该失败。

## 设备与原生功能

候选尚未部署或启动。当前设备按共享AGENTS.md由“33”继续GPU179测试；本对话已
请求协调下一轮，等待其日志回收及设备交接，不复用其他轮次日志槽清单。

原生验证工具已通过CI42738268575编译、签名和下载审查：
`artifacts/ci/42738268575-attempt-1/nabu-sensor-probe-4/NabuSensorProbe.ipa`。
它新增/chosen报告和真实source注册表快照；33d6d7e的启动即刷新latest修订也已通过该CI及下载审查。
它读取真正的CoreMotion/光线HID及旋转结果，当前没有传感器运行成功数据。

真实NabuSensorSource及共享队列已在6410735提交，arm64编译、全部223个导入
解析及无FP/SIMD检查通过，尚未链接入mode3或实机发布。

后续先完成mode3实际FastRPC/registry/样本检查，再连接连续后端、真实
NabuSensorSource服务和用户态HID桥；验证时钟、坐标、CoreMotion、旋转和自动亮度。
原内核没有IOHIDEventService类，不能通过伪装类名或返回成功代替完整接入。

状态：`log/host/sensors-fastrpc-20261109/continuation.json`。

## 后续原生接入候选（尚未实测）

`artifacts/nabu-sensors-native-20261110-r3/kernel/kernel.native-apfs.macho`已链接真实
NabuSensorSource，mode4在独立内核线程持续泵送SLPI，保留原有启动/关闭超时；失去
SLPI/SSC或采样停止时撤销源状态。四路真实Android包回放已贯穿Census到原生传输
边界，保留SI rawbits和原始SSC时间；主机使用受控时间映射，不作为iPadOS证据。

时钟domain由显式`nabu-ssc-clock`选择，默认0不发布。候选domain有原件/硬件依据后，
同boot连续四个加速度样本还须满足100ms跨度、稳定本地时钟bracket及非负有界age。
只有这些检查成立才确认epoch；不能用收到样本的时刻拟合采样偏移。发现时间跳变
立即撤销已有源，自动休眠后重启采样尚未完成实测。

采样/批处理间隔由IOUserClient mailbox交给SSC同端点、同client、同SUID，独立高位
transaction响应经过真实成功字段核对后才向调用者返回成功。超时不重发已发送请求。
实际重配频率、是否存在重复流和HID/CoreMotion消费仍需真机确认。

第一次native对象指令审查发现主SLPI编译器生成321条FP/SIMD寄存器操作（含结构
清零/复制），尽管代码不做采样浮点运算。已对SLPI和源对象统一加入
`-mgeneral-regs-only`并在构建中强制检查实际指令；r6 mode3和r3 mode4均为0条。
此发现未被归因为sensors02零样本的已证实原因。mode4最大栈2192字节，源对象176。

两个最终候选的正式loader检查均通过。下一次设备仍先执行mode3，以真实FastRPC
应答、registry/SUID和当前boot时钟记录闭合，再选择原生mode4的domain配置。

## 已打包的原生HID owner

独立daemon提交`f578358`，CI`42741490056`编译、签名和下载审查通过。20F66原版
服务器确认type4的虚拟服务注册检查event-dispatch entitlement bit3，已选唯一
`com.apple.private.hid.client.event-dispatch=true`；真实注册/open/dispatch尚未运行。
详见[nabu-sensor-daemon-20261110.md](nabu-sensor-daemon-20261110.md)。

`artifacts/nabu-bootstrap-native-sensors-20261110/bootstrap.apfs`为84,586,496字节，
保留完整r2 FastRPC Boot和既有App，仅重建NabuInit：加入122,512字节daemon及
246字节root RunAtLoad任务。APFS检查、daemon和任务文件的原生逐字节读回通过。
任务参数显式为`--axes 1,2,3`，持续运行并将诊断写入控制台；只在有真实源/样本后
创建虚拟HID。轴变换仍为候选，不表示已通过六面、旋转或自动亮度。

此原生启动包只配合mode4使用；下一次sensors03仍先使用mode3 r6与无daemon的
完整FastRPC r2启动包。尚未准备新的设备日志槽，所有新候选均未部署/启动。
当前GPU179仍待Android回收日志及设备交接。
