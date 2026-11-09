# 第168轮：系统发现服务通过，插件挂载受权限阻塞

2026-11-09。用户确认桌面、触摸正常并恢复Android。3,339,280字节连续内核日志及
完整64MiB槽已备份，槽14清空读回通过；APFS记录137→138、fullfsync=ok。

源码为`6ffb65ce137eaeabbfd0997165d9fcfe6854bbde`；系统Metal用户态CI42601686196、
完整内核CI42601686128均成功。本轮实际使用本地已检查的
`artifacts/nabu-gpu-trace-v168/kernel.native-apfs.macho`及
`artifacts/nabu-bootstrap-gpu-v168/bootstrap.apfs`，通过临时fastboot boot启动。

## 实际结果

- 115.265秒发布`AGXAccelerator`和`NativeAdrenoGpuPublished`，真实CP写回
  `0x6401cafe`、fence1/1，GMU应答7次，启动状态0。
- AGX匹配事件启动新的mobile测试进程；运行时`_MTLDevice`为528字节，
  NativeAdreno ABI1、chip06040001查询通过。
- root挂载助手在`mount("bindfs", ..., MNT_RDONLY|MNT_UNION, ...)`返回EPERM。
  probe等待30秒仍无本次启动ready标志，停在`plugin_mount_ready`并退出。
- 本轮没有调用`MTLCreateSystemDefaultDevice()`，没有提交Metal命令。
  AFC中的RGBA/JSON仍来自第167轮，不计作第168轮新渲染成果。

## 修复方向

当前hakios补丁保留bindfs的`com.apple.private.bindfs-allow`权限检查，仅额外豁免
PID1。普通root挂载助手未签入该键，符合本次EPERM。下一轮只给助手签入此项专用
权限并检查实际签名内容，复用本轮内核及已验证前端，重试同一标准工厂测试。
系统工厂、IOSurface和呈现仍待实际验收。

证据：`log/host/gpu-v168/metal-runtime/probe-result.json`、
`log/host/gpu-v168/metal-runtime/nabu-system-metal-mount.stderr.log`、
`log/device/nabu-boot-20261109-168/runtime-log/runtime.log`、
`log/host/gpu-v168/result-summary.json`。首次syslog连接早于Lockdown就绪而超时；
后续原生USB会话及1,627,125字节syslog回收成功，完整内核证据来自Android日志槽。
