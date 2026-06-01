# v1 诊断报告模板

## 1. 报告原则

报告要面向排障现场，先给结论，再给证据。

要求：

```text
结论必须有置信度
每个根因必须绑定证据
源码判断必须带文件、函数、行号或摘要
不确定点必须单独列出
建议动作必须可执行
不能把猜测写成事实
```

## 2. 固定结构

```md
# SD-WAN 诊断报告

## 1. 结论

## 2. 关键证据

## 3. 转发路径

## 4. 控制面关联

## 5. 根因判断

## 6. 建议动作
```

debug 为 `true` 时追加：

```md
## 调试附录
```

## 3. 各段要求

### 3.1 结论

必须包含：

```text
最可能原因
影响范围
置信度: 高/中高/中/低
是否需要补充信息
```

示例：

```md
当前更像是 `ANPOSNS` 内 VRF 路由没有刷新到目标 table，导致下一跳邻居解析失败；暂未看到 OVS flow 明确 drop。置信度：中高。
```

### 3.2 关键证据

分为三类：

```md
- FPE 现场证据：...
- 路径计算证据：...
- 源码证据：...
- 不确定点：...
```

不允许只写泛泛描述，例如“可能是路由问题”。必须写成：

```md
- FPE 现场证据：`ANPOSNS` 中目标前缀命中 `table 1001`，但 next hop 邻居状态为 `FAILED`。
```

### 3.3 转发路径

有路径结果时：

```md
`ANPOSNS`
-> `ip rule priority 100`
-> `table 1001`
-> `vxlan100`
-> neighbor unresolved
-> incomplete
```

多路径时：

```md
路径 A：...
路径 B：...
```

没有 `src_ip/dst_ip` 时：

```md
未执行精确路径计算，因为输入缺少 `packet.src_ip` 或 `packet.dst_ip`。
```

### 3.4 控制面关联

必须包含源码定位。

```md
相关代码集中在：

- `controller/tunnel.go:120` `RebuildVxlan`
- `controller/route.go:88` `SyncVRFRoute`
- `controller/events.go:45` `OnInterfaceUp`
```

如果无源码：

```md
本次未提供 `source_root`，因此没有执行控制器源码关联。
```

如果源码未命中：

```md
已搜索控制器源码，但未命中与当前 token 直接相关的函数或结构体；根因判断只基于 FPE 现场证据。
```

### 3.5 根因判断

最多 3 条，按概率排序。

每条格式：

```md
1. 根因标题。概率：高/中/低。
   证据：...
   反证/不确定点：...
```

注意：Markdown 最终输出尽量保持单层列表；实现时可以用短段落替代嵌套列表。

### 3.6 建议动作

建议动作分三类：

```md
- 立即验证：可以直接执行的命令或观察项。
- 临时恢复：如果适合，给出低风险恢复动作。
- 代码修复方向：如果疑似代码 Bug，给出修改位置和测试建议。
```

命令示例：

```bash
ip netns exec ANPOSNS ip route show table 1001
ip netns exec ANPOSNS ip neigh show
ip netns exec ANPOSNS /anpos/frr/bin/vtysh -c "show bgp ipv4 unicast"
ovs-ofctl dump-flows br-int table=102
```

## 4. 完整示例

```md
# SD-WAN 诊断报告

## 1. 结论

当前更像是 `ANPOSNS` 内 BGP/FRR 路由未正确刷新到目标 VRF 路由表，导致下一跳邻居解析失败；暂未看到 OVS flow 明确 drop。置信度：中高。

## 2. 关键证据

- FPE 现场证据：目标前缀命中 `table 1001`，但 next hop 邻居状态为 `FAILED`。
- 路径计算证据：路径在 `vxlan100` 出口后进入 `neighbor unresolved`，结果为 `incomplete`。
- OVS 证据：`br-int table=102` 命中后动作为 `output:7`，未观察到 `drop`。
- 源码证据：`controller/tunnel.go:120` 的 `RebuildVxlan` 会重建 tunnel；`controller/route.go:88` 的 `SyncVRFRoute` 负责刷新 VRF 路由。
- 不确定点：当前未确认 FRR 是否已经学习到目标前缀，也未确认 tunnel 重建与 route refresh 的事件顺序。

## 3. 转发路径

`ANPOSNS`
-> `ip rule priority 100`
-> `table 1001`
-> `vxlan100`
-> neighbor unresolved
-> incomplete

## 4. 控制面关联

相关代码集中在：

- `controller/tunnel.go:120` `RebuildVxlan`
- `controller/route.go:88` `SyncVRFRoute`
- `controller/events.go:45` `OnInterfaceUp`

源码显示 tunnel 重建和 VRF 路由刷新是两个独立动作。如果事件顺序是先重建 tunnel、后刷新路由，但后者没有被触发，现场就可能出现 tunnel 存在但目标 VRF 路由或邻居未完成的状态。

## 5. 根因判断

1. VRF 路由刷新晚于 tunnel 重建，或 route refresh 未被触发。概率：高。证据是路径停在 VRF 路由下一跳邻居解析，且源码中 tunnel rebuild 与 route sync 分离。
2. FRR 已学习目标前缀但未同步到目标 VRF table。概率：中。证据是 `frr_info` 需要进一步确认 BGP route 与 kernel route 是否一致。
3. OVS tunnel port 异常。概率：低。当前 OVS flow 没有显示 drop，且路径已经能走到 tunnel 出口。

## 6. 建议动作

- 立即验证：执行 `ip netns exec ANPOSNS ip route show table 1001`，确认目标前缀和下一跳。
- 立即验证：执行 `ip netns exec ANPOSNS ip neigh show`，确认 next hop 是否 `FAILED` 或缺失。
- 立即验证：执行 FRR `show bgp ipv4 unicast 10.220.21.236/32`，确认控制面是否学习到目标前缀。
- 代码修复方向：检查 `OnInterfaceUp -> RebuildVxlan -> SyncVRFRoute` 的调用顺序，必要时在 tunnel 重建成功后触发 VRF route refresh。
```

## 5. Debug 附录格式

~~~md
## 调试附录

### 输入归一化

```json
{}
```

### 提取 Token

| Token | Type | Source | Weight |
|-------|------|--------|--------|
| `ANPOSNS` | vrf/namespace | query | 90 |

### 命中源码片段

| File | Symbol | Lines | Score |
|------|--------|-------|-------|
| `controller/tunnel.go` | `RebuildVxlan` | `120-188` | `210` |

### FPE 证据摘要

```json
{}
```
~~~
