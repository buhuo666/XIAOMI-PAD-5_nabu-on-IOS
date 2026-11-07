# 第115轮：补齐 modem XO 代理时钟

本轮目标是推进真实WLAN启动，完成后仍需扫描、关联和数据收发验收。

## 已发现的缺口

本机FDT `/soc/qcom,mss@4080000` 的 proxy-clock-names 为 xo，clocks 指向
qcom,rpmhclk 的索引0。固定MiCode 71b6effd2dfa8f703dd1ea17acd1323b2fd3cf6c
`clk-rpmh.c` 的 RPMH_CXO_CLK 对应 sm8150_bi_tcxo：资源 xo.lvl，ARC offset0，
开启值3。`subsys-pil-tz.c` 的 pil_make_proxy_vote 在proxy regulator之后开启
proxy clocks；peripheral-loader在加载/认证阶段管理这些投票。

现有NabuModem::proxy_power只显式投票cx.lvl和mss.lvl，未请求此XO。这是modem
的必需代理时钟，区别于ICNSS节点缺少的可选cxo_ref_clk_pin或rfclka2。
固件能够启动部分服务不能证明这个前提已由本机代码满足；另一方面，bootloader
可能保留了该资源投票，因此缺少代码不等于已经证明首次PFR的唯一根因。

## 修改及验证

从本机command-db查找xo.lvl，在原有CX/MSS批次中加入第三条active请求，offset0、
data3；三个完成状态全部成功才继续PAS。CX/MSS仍按原有384级查表，XO不误用OPP
索引。沿用当前proxy资源保留到重启的行为；未新增sleep/wake TCS改写或时钟关闭。
长期共享消费者和休眠管理仍需随常驻驱动完善。

生产proxy_power提取回放已通过ASan/UBSan：验证确切三条命令、缺XO时禁止启动、
XO无完成时失败、TCS忙和超时。arm64全部无线对象编译、内核链接和return-trace
检查已通过。尚待完整CI与实机；不把命令完成当作物理晶振或WLAN ready读回。

## 实机判据

1. 日志确认xo.lvl资源与值3，第三条RPMh请求完成。
2. 比较首次b019b9bc异常是否消失，是否收到FW_READY/INIT_DONE。
3. 读回新版WirelessInventory软件接口观察及BluetoothInventory原生初始化基线。
4. 若同址异常仍存在，将结果作为排除实验保留，继续定位首次MMIO上下文和其他
   上电条件；不重复部署只有诊断变化的轮次来替代数据通路实现。

原件和参考源码：log/host/wireless-v76/android/device.dtb；
log/host/wireless-v115/prerequisites/{clk-rpmh.c,subsys-pil-tz.c,peripheral-loader.c}。
候选内核artifacts/nabu-wireless-v115，bootstrap使用已通过CI42382217973的
artifacts/nabu-bootstrap-recheck-v114。第114轮完整槽已备份清空，设备Android且
蓝牙设置读回0。首次WLAN异常未宣告解决。
