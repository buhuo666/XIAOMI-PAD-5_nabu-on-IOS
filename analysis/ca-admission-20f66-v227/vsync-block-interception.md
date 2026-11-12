# base timer block 数据拦截可行性

2026-11-12，20F66。只读原版cache，未实现新hook。

结论：**此调用链没有普通fishhook式导入数据槽，也没有可替换invoke的静态descriptor槽；当前不建议推进这个方案。** 已确认block ABI允许精确识别，但识别条件并不能提供安全插入点。

## 真实调用链排除了两个简单入口

`vsync-18831b788.asm` 的 `0x18831b800` 调用 `0x18db366d8`。`vsync-block-bindings.json` 保存的原始指令是：

```asm
0x18db366d8: adrp x16, 0x186db7000
0x18db366dc: add  x16, x16, 0xa7c
0x18db366e0: br   x16
```

这是直接定位`CFRunLoopPerformBlock(0x186db7a7c)`的shared-cache优化stub，不加载GOT/function pointer。仅rebinding某个导入数据地址无法改变这个调用。`CFRunLoopWakeUp`对应stub也是`adrp/add/br`。

原callback在 `0x18831b7e0/e4` 通过代码`adrp/add`直接形成`0x18830dec8`，随后写入栈block的`+0x10`。descriptor中没有invoke字段，修改descriptor不能改变该invoke。

## block ABI及复制边界已确认

此特定原始block为40字节：

| offset | 内容 |
|---|---|
| `+0x00` | 原 `_NSConcreteStackBlock` isa，从cache数据引用读取 |
| `+0x08` | flags=`0x40000000`，reserved word=`0` |
| `+0x10` | invoke=`0x18830dec8 + slide` |
| `+0x18` | descriptor=`0x1d57ff228 + slide` |
| `+0x20` | raw `Server*` capture |

descriptor读取结果保存在`vsync-nativecf/evidence.json`：size=40，signature=`v8@?0`，无copy/dispose helper。descriptor首个reserved原始值是`0x40000000`，并非假定的零。原server capture无retaining helper，不应自行更换其ownership模型。

原`CFRunLoopPerformBlock`已按CoreFoundation的`LC_FUNCTION_STARTS`提取为`vsync-nativecf/186db7a7c.asm`（788字节）：

- `0x186db7cc4/cc8`同步对传入block调用`_Block_copy`。
- `0x186db7cd8..ce0`随后获取runloop锁；分配24字节节点，并把复制后的block存入节点`+0x10`，链接到runloop `+0x88/+0x90`。
- 复制发生在函数返回前。这支持“若已有合法调用拦截点，则可传入完整40字节栈副本并保持原descriptor/isa/capture，仅替换invoke”的ABI推论；它并未证明这个拦截点存在。
- 本次特定block缺少copy/dispose helpers，保留同一raw server capture才能保留原生命周期假设。但这并不额外证明已经投递的块能与shutdown任意并发。

## 不能把副本方案当作已可部署

原schedule去重/取消仍依赖`0x18831b788 + server`，而CF的原runloop块在稍后执行。若能在原CF调用位置替换块，这两个原schedule键确实无需变化；但现有数据vtable安装机制只能替换经vtable间接调用的地址，此处既不是vtable调用，也不是经GOT加载的导入调用。

未发现可以仅换`Server::get_runloop`结果而正确跳过原block构造/投递的路径。返回null会触发原同步now-render fallback，不能完成精确替换；修改CF私有已排队block则存在与执行/销毁的竞争，当前没有原生同步接口证据。

本结论仅覆盖原base callback、shared-cache stub、block descriptor、`CFRunLoopPerformBlock`实际实现和现有数据vtable安装方式，不宣称所有可能的dyld/CF扩展均不存在。没有验证动态interpose是否能绕过优化stub；不能据此默认它有效，也不建议扩展成全局CF/Block runtime hook或修改代码页。

后续若227低延时仍需预测target，应先继续寻找更合适的原版数据虚调用入口或明确支持的配置路径；目前应保留本候选为未实施、入口不成立。
