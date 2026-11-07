# 2026-11-07：主CI失败原因与实机内核来源

用户指出GitHub主构建连续失败后，读取最新实际run/attempt/job以及完整失败日志。
最新失败为42342588947、提交1a532bd；修复后完整构建42343348954、提交5ed580b
已成功。此前未及时处理主流程红灯，不能用专题CI或本地模块测试代替完整CI结论。

## 失败不是一次成功的当前提交全量构建

失败步骤名称为“Compile 8796 reference”，实际停止在其编译前检查：
`tools/check_nabu_display.py:137`的`trees[0][1] == trees[1][1]`。
当次没有执行后面的XNU构建和原生链接检查。

该断言最初只允许根model变化。17b87b00加入iPad7,11专用的20字节
`/product/product-id`后，旧测试仍要求全部子节点逐字节相同，因此持续失败。
实际生成树的差异只有`/model`和`/product/product-id`。

5ed580b修复为：原生模式必须不含该product-id，iPad模式必须具有已核实的精确
20字节值；随后只从比较副本中移除此字段，继续要求其余节点和属性全部一致。
没有删除显示配置检查或将任意product属性加入忽略范围。

## 验证结果

- 本地实际显示配置方法的17项正常/非法/旧路径用例通过ASan/UBSan。
- 完整CI 42343348954：XNU参考内核编译、APFS Data设备编译、导出合同、原生
  LLDB接口分析、SMP/容量、返回诊断、存储策略、显示几何及消费者检查全部成功。
- 本次修复只修改测试脚本；第112轮已部署内核没有因这一测试修复而被更换。

本地证据：`log/host/wireless-v112/ci-audit/`；完整Actions状态为
`log/ci/github/42343348954/attempt-1/status.json`，原失败日志为
`log/ci/github/42342588947/attempt-1/logs/xnu8796-reference/5_Compile 8796 reference.txt`。

## 第112轮实际运行的构建来源

1. 核心基底来自成功的完整Actions 42160433518，提交5009ad4。其原始构建报告
   `build_exit_code=0`，所有原生检查均成功。
2. `artifacts/nabu-services-prelink-v79/prelink-report.json`记录该基底、原版组件
   路径和预链接来源。第112轮沿用这些输入。
3. 新无线模块在Windows/WSL以arm64目标编译；第112轮重新编译NabuGlink，
   其余未变化对象复用第111轮，再完成本地原生预链接及return-trace检查。
4. 对5009ad4到1a532bd的核心patches/8796、输入/存储/APFS补丁、核心准备脚本和
   锁定构建输入作差异核对，只有外部模块NabuDataKmod.cpp变化；该模块在本地
   重新编译对象列表中。此说明限定于这些实际检查路径。
5. 第112轮用户确认桌面/USB正常，日志证明APFS计数81→82及fullfsync成功，
   蓝牙单广告偏好保留、原生2005/200b/200c成功；Wi-Fi仍PFR，未就绪或联网。

因此目前只能称为已验证部分功能的开发测试内核。当前主CI恢复成功解决了构建
验证缺口，不能据此宣称Wi-Fi、音频或系统整体稳定性已完成。
