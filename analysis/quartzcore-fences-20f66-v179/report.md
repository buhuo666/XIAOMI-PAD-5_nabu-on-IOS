# GPU179调查：20F66 QuartzCore fence来源

本报告只读本机20F66 QuartzCore原始共享缓存和已回收GPU178日志；未操作设备或修改源码。
使用现有Capstone及LC_FUNCTION_STARTS解析器；REA不可用记录复用
analysis/metal-library-20f66-v178/rea-availability.json。完整位置、字节偏移与调用记录见calls.json。

## 已确认

1. 字符串 `timed out fence %llu` 位于0x188517325和0x18852348b，实际发出函数是
   `CA::Render::Fence::ftimeout_callback(double, void*)`（0x1884972d4）。
2. `CA::Render::Fence::create_fence_port`（0x18849681c）在0x1884968ec–0x188496908
   增加全局32位非零计数，调用getpid，再用`bfi x21,x0,#32,#32`组合为
   `(PID << 32) | counter`。GPU178的五个超时编号精确对应各backboardd PID与counter2。
3. 创建流程分配Mach接收权、生成发送权，对服务器notify port注册70号
   `MACH_NOTIFY_NO_SENDERS`，并将到期时间设为当前时间加10秒。
4. `CAFenceHandle`通过`CASCreateFencePort` Mach RPC获得端口及名字，服务端
   `__XCreateFencePort`调用上面的创建函数；`invalidate`以mach_port_deallocate释放发送权。
5. 显示服务器线程收到notify port的70号消息后扫描未清理fence，查询
   `MACH_PORT_RECEIVE_STATUS`。查询失败或mps_srights为零时，将名字标为清理，再调用
   `resolve_fences`。该解析还会检查显示context/transaction的fence依赖。
6. 超时回调自身也将到期名字标为清理并进入同一解析路径；仅凭超时文字不能认定硬件GPU挂起。
7. `CA::OGL::MetalContext::set_fence/test_fence`是另一套对象内计数与完成状态比较：
   set_fence位于0x188268ebc，test_fence位于0x18823e494；与上述PID编码的端口fence不同。

## 接口要求与未知

必须保留Mach端口引用计数、send-once/no-senders通知、port-set投递、真实mps_srights状态，
以及CAFenceHandle释放和显示事务依赖顺序。不能直接伪造fence完成或修改GPU硬件等待来消除此日志。

目前不能确认counter2的具体调用者/发送权持有者，也不能在保留权、通知未送达、事务等待或
进度较慢之间确定超时根因。超时与随后SIGSEGV的因果尚未建立，应由本轮PC/LR诊断另行定位。

## 主要原始证据

- 1884972d4.asm：超时函数、精确字符串引用及清理/解析调用。
- 18849681c.asm：PID/计数组合、Mach权利、10秒期限及通知注册。
- 188243c40.asm：服务器接收通知和receive-status处理。
- 188285cc8.asm、18829423c.asm：客户端RPC与服务端创建入口。
- 188421b98.asm、1882dc0e0.asm：CAFenceHandle创建/释放。
- 188268ebc.asm、18823e494.asm：独立的MetalContext fence机制。
- calls.json：所有函数原始位置、缓存文件及偏移、静态结论和范围限制。
