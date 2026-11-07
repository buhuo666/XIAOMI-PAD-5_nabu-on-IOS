# v128 ath10k 冷启动接入候选

日期：2026-11-08，Asia/Shanghai。第127轮证据已回收，APFS97，设备在Android。
本候选尚未部署；编译和主机测试不等于设备DMA、中断、扫描成功。

保留第127轮已经启动成功的本机固件、四路供电、QDSS、MSA、BDF/CAL及SMMU
所有权。`build_nabu_aes.py --wireless --ath10k`选择新的runtime和QRTR桥，默认
不带`--ath10k`仍选择原runtime。新驱动不接管第127轮已消费HTC READY的通道。

## 交接与退出

GLINK只有一个轮询owner。真实FW_READY且本机bootstrap complete后，先在同一
FIFO发出旧KNEL0x4003和DMON0x4004的DEL_CLIENT；两个请求实际入队后才启动
ath10k worker。若没有TX intent，保留状态下轮重试。退休端口的迟到回包被丢弃，
旧CFG/MODE和rejuvenate ACK不再主动发送。新KNEL使用动态端口0x4020起，必须
通过其真实0x20注册响应中的FW_READY位，然后查询CAP，由ath10k独占CFG/MODE/CE。

QRTR adapter缓存实际服务公告，只转送同一实例、同一端点的数据。回调在队列锁外
执行；同步close等待已领取回调和发送完成。PFR、服务移除/替换或运行失败使实例
失效，仍由GLINK轮询派发removal并等待worker注销完成，再关闭通道和执行PAS停止。
未完成worker/IRQ注销或PAS停止时不释放DMA。成功扫描后worker保持等待，固件和
QMI通道常驻；本轮没有实现用户开关或同次启动中的重启。

## DMA 与中断

可选44MiB连续分配通过不带32位physical输出限制的IOMallocContiguous取得，
映射到IOVA0xa0000000；页表128KiB，实际使用24个4KiB页。CPU使用WCOMB别名，
缓存原视图在初始清零后清理，不再用于radio访问。旧8MiB分块方式保留。
连续分配能否在实机成功仍未知。SMMU沿用原已验证bank/ACTLR/流槽选择及停止门槛。

CE向量0至11对应GIC INTID446至457，level-high。IRQ只mask并唤醒专用线程，
该线程执行LinuxKPI handler；detach先禁止新callback再等待正在运行的callback。
LinuxKPI host.c保留enabled检查，disable后积压的调度不会调用实际driver handler。

## 构建与首轮验证范围

固定Helium57722468、Linux7.0.14、FreeBSD15.1、wpa2.11、mbedtls3.6.7。
后端入口及板级lx_os回调显式重命名到nabu_ath10k，复用基核通用线程、锁、内存
及QMI ABI；不假定替换新对象符号会改变旧基核已经链接的调用。

接口描述firmware-5.bin使用参考WCN399x的WMI TLV/HTT TLV配置，不是执行固件。
实际WLAN程序、BDF和CAL继续来自本机。首轮wifi_scan=1、wifi_join=wifi_keep=0，
运行真实被动扫描和station_down，结果以driver事件/BSS及返回码确认。原生网络和
station callbacks目前不可达，不发布en0或把Wi-Fi按钮可点作为验收。

完整后端47对象本地编译通过；macOS ld -r合并为一个ath10k.o后再进入本地prelink。
CI加入该后端构建、原生桥编译及所有新主机测试。完整CI精确提交成功后才可部署。

主机证据在`log/host/wireless-v128/`：

- dma-check：原8MiB及44MiB共11264页面翻译、精确free大小、异常保留/TLB停止门槛。
- ath10k-qrtr-test：生产router/native wrapper，线程并发close与回调/DEL_CLIENT lease。
- ath10k-glink-test：生产GLINK，真实ready门槛、旧端口退出、新端口路由、8192负载及背压。
- ath10k-runtime-test：生产runtime，线程/driver失败、启动中实例失效、SMMU fault、12路IRQ注销。
- ath10k-handoff：生产QMI六函数22场景，禁止重复HOST_CAP/MSA/BDF/CAL和通知绕过。
- glink-default：旧路径生产GLINK回归通过。

第127轮未执行PAS停止/QDSS off，v128也尚无实机清理证据；不得由主机测试倒推实机成功。
