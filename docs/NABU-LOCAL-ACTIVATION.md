# 系统级本地激活兼容

2026-11-06。目标和阶段顺序见[基本技术路线](BASIC-TECHNICAL-ROADMAP.md)。

## 原版接口证据

现有20F66的MobileActivation.framework通过NSXPCConnection连接
`com.apple.mobileactivationd`，协议为`MobileActivationProtocol`。32个方法的
完成回调均为`void (^)(NSDictionary *, NSError *)`。确认的状态回复为：

| 方法 | 回复 |
| --- | --- |
| getActivationStateWithCompletionBlock: | ActivationState: NSString |
| isDeviceBrickedWithCompletionBlock: | BrickState: NSNumber |
| getActivationBuildWithCompletionBlock: | LastActivated: NSString |
| getDCRTStateWithCompletionBlock: | DCRTState: NSString |

Lockdown的ActivationState和BrickState都调用MAEGetActivationStateWithError。
后者比较Activated/FactoryActivated，只有匹配时允许非AllowUnactivatedService的
服务继续启动。data_ark仅有ActivationState回退；改其存储键不能覆盖BrickState。
FactoryActivated还带有允许配对的独立分支，因此本地兼容选择Activated，保持
原有用户信任流程。ActivationStateAcknowledged是PurpleBuddy另一条完成路径，
不等于上述实际激活状态。

证据为本机原版组件的静态反汇编：ignored `log/host/activation-v62/lockdown/`和
`client-analysis/`。REA深度提供器本机不可用，本次通过已有Capstone脚本与原始
ObjC协议元数据恢复接口，未把静态分析当作实机运行结果。

## 候选实现

`userland/nabu/src/local_activation.m`是独立源构建服务，使用原版框架中注册的
协议对象，在全局Mach服务名com.apple.mobileactivationd提供上述四项查询。
其他协议方法按实际参数形状返回org.nabu.LocalActivation/ENOTSUP，不生成Apple
激活记录、UCRT/DCRT、设备证明或联网应答。DCRTState正常报告DCRTUnavailable。

状态保存到`/private/var/db/nabu/local-activation.plist`，包含本机gethostuuid身份、
Activated、20F66、NabuLocalCompatibility、创建时间和AppleServerValidated=false。
启动时读取既有状态；在提供服务前校验设备关联并执行chmod及F_FULLFSYNC。
新写入失败的文件在后续重试也必须完成落盘，不能仅凭文件存在认定成功。

服务在显式`nabu-local-activation=1`时启用，打包由`--local-activation`选择，暂存
工具要求nabu-data=1。原版mobileactivationd继续被排除，本地服务不启动其网络任务。
服务发布后发送原版activation_state/brick_state Darwin通知；其他消费者是否
刷新仍需实机日志证明。独立的com.apple.mobileactivationd.lockdown协议未实现。

## 验证状态

Actions 42154740900通过arm64-iOS16.5编译和macOS ASan/UBSan实际源码测试：首次
F_FULLFSYNC失败、重复失败、恢复成功、持久记录重读、设备身份不匹配、四项准确
回复及证书请求明确不支持。主机测试不执行iPadOS NSXPC跨进程通信。

第六十二轮沿用v61内核，使用新增服务的bootstrap。待实机确认：ActivationState=
Activated、BrickState=false，原生配对会话继续可用，installation_proxy和
springboardservices实际启动，原版客户端Lookup有响应；之后验证再次启动仍保留。
`tools/probe_nabu_activation.py`保存这些查询与服务结果，不把服务启动等同于IPA安装。

## 第六十二轮首启实测

用户确认桌面正常。通过上一轮保留的配对证书建立TLS会话，原版Lockdown返回
ActivationState=Activated、BrickState=false、PasswordProtected=false、BuildVersion=20F66。
ActivationStateAcknowledged仍返回MissingValue，保持与实际状态分开记录。
installation_proxy启动并完成Lookup，springboardservices启动并完成服务TLS连接。

自有无网络UIKit测试IPA由Actions42155209120构建，普通arm64/iOS16.5、ad hoc签名，
没有provisioning profile或假证书。`tools/install_nabu_test_app.py`经原版AFC上传，
原版安装代理依次返回验证、容器创建、安装、沙箱、应用映射和InstallComplete/Complete；
Lookup返回org.nabu.LocalTest的应用路径与独立Data容器。用户确认桌面图标可打开，
界面显示启动次数1，点击“累加并保存”后保存次数1。无需修改安装代理的验证返回值。

此结果验证本轮本地激活状态、原版安装服务和该测试应用安装/运行/写数据。
跨重启激活态、应用和数据保留仍需下一轮验证；不能据此宣称任意第三方IPA均可安装。
主机证据在ignored `log/host/activation-v62/host-probe/activation.json`及
`test-app-install/install.json`。
