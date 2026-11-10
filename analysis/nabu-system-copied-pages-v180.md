# 第180轮：复制源映射生命周期

## 第179轮已回收证据

第179轮仅用已合格GPU178前端和CI42738127355的故障诊断工厂复现桌面退出，没有装入
资源alias新实现。47,326,534字节连续有效日志前缀、完整64MiB槽1及31,071,999字节
syslog均已保全；槽已清空读回，APFS151→152 fullfsync=ok，Android引导分区未变。
捕获未封口，不能将有效前缀称为完整运行日志。设备已恢复Android。

31次backboardd SIGSEGV均发生在运行地址0x20f330fe4。原版libsystem_platform
映像slide=0x3f014000，未滑动地址0x1d031cfe4，指令是`ldr x6, [x1], #8`。
前端返回地址统一为映像内0x971840，位于`CopiedBuffers::copy_in`；调用前将目标设为
sp+0x38，源设为x26+x20，长度设为x21。31次均x20=0、x21=8，FAR=x1=x26；因此
故障发生在源缓冲区首8字节读取，尚未写目标。故障时x2=0是系统memmove已减掉8，
不能解释为请求零长度复制。ESR均0x92000007，是读取方向的L3 translation fault。

首轮源地址0x10774c000，注册比较长度0x160000；之后多数长度0x4000。现有证据没有
记录源VA被撤销/保护或提供者释放的确切时点。首轮长度也不能与日志中的IOSurface
创建直接对应，不能断言全部都是IOSurface表面问题。

原始寄存器、镜像地址及符号化结果在log/host/gpu-v179/fault-contexts.json和
fault-lr-symbolication.txt。QuartzCore Mach事务fence超时是独立观察，不等同GPU硬件fence。

## 资源接口修复

专项CI42738127415完整成功，普通ARM64/iOS16.5新前端18,126,704字节完成一次下载审查。
四个资源alias C ABI导出存在，macOS上的68项生产Objective-C分派测试通过；尚未真机运行。
第180轮保留该修复和原有uchar3、pipelineLibrary兼容、IOSurface复制与统计实现。

## 源映射修复方案与验证范围

现有CopiedBuffers.add首次通过Mach读取源页，但copy_in和merge_back随后直接使用
调用者原VA。第180轮在macOS/iOS的每个复制登记项中持有同任务mach_vm_remap产生的
共享映射，copy=false，保持原访问权限；VM_FLAGS_RETURN_DATA_ADDR保留源子页偏移。
两个同步方向都使用此自有映射；登记项移除后只销毁该映射。原MTLBuffer.contents、
原始导入地址键、重映射身份检查、去重和回调仍按原接口工作。

这不是启用cached imports，也不是将复制路径改称零复制。目标是确保复制登记项的
读写地址与其生命周期一致；更上层为何释放/保护原VA仍需保留为未知。构建前需以真实
Mach测试验证双向共享、原地址撤销/保护、同址新对象隔离和映射释放，并验证实际
CopiedBuffers同步行为。实机桌面及像素结果仍待后续验证。

## 真实macOS主机验证

源码42adccb的CI42756846244已通过8组真实Mach与生产CopiedBuffers测试：共享的双向
写入、子页偏移、原VA保护变化、撤销与同址新对象隔离、自有映射释放、初始不可读拒绝，
以及实际copy_in/merge_back的CPU冲突优先规则和移除后停止比较。没有调用GPU。
构建随后在Rust编译前因脚本未将新0028项登记到允许的补丁尾部而停止；20faac2已修复
这项构建清单，专项CI42757503932继续构建。不能将主机通过称为iPadOS桌面通过。
原始报告在artifacts/ci/42756846244-attempt-1/nabu-owned-copy-pages-1/copied-pages-host-check。
