---
name: fpe-ovs-tool-thinking
description: Use when analyzing network forwarding in this FPE project via MCP tools. Follow an OVS-first reasoning process, choose the right tool sequence, and turn broad collected data into path conclusions and flow graphs instead of querying tools in an ad hoc order.
---

# OVS-First 转发路径分析思维框架

**技能目标**：使用 OVS 优先的结构化思维，通过 MCP 工具进行系统的网络转发路径分析。

**适用场景**：诊断复杂网络中的流量转发问题、跨 namespace 转移、混合 OVS-VRF 架构。

---

## 核心原则

### 1. OVS-First 决策流

任何网络流量都需要先问：**OVS 是否接管了这个物理接口？**

```
流量到达物理接口
    ↓
[决策点1] OVS 接管吗？
    ├─ YES → OVS 处理（bridge → VLAN/流表 → 端口）
    │         ├─ 可能转发到 kernel（veth/内部端口）
    │         └─ 可能转发到另一个 OVS 端口（patch/物理）
    └─ NO  → kernel 直接处理
             ├─ 可能进入 VRF
             ├─ 可能进入主机网络栈
             └─ 可能进入其他处理路径
```

### 2. 混合转发架构（关键发现）

**在 DPDK + OVS + VRF 的现代网络中，转发链可能是：**

```
物理 DPDK 接口（被 OVS 接管）
    ↓ OVS 第一层处理（br-int）
    ├─ VLAN 学习和转发
    ├─ 路由到内部端口或 veth
    ↓ 进入 kernel namespace/VRF
    ├─ L3 路由和规则链
    ├─ 可能返回 veth
    ↓ OVS 第二层处理（br-wan1 等）
    ├─ 流表链转发
    ↓ 物理输出或其他处理
```

**关键特征**：
- 流量可能进入 OVS → VRF → OVS 的链式处理
- OVS 桥中的 VLAN 配置驱动初级转发（不一定是流表规则）
- 内部端口（`type: internal`）和 veth 是跨越 OVS 和 kernel 的桥梁

### 3. 分层分析方法（5 层）

#### 第 1 层：包定义与上下文确定
定义完整的数据包上下文：
```
packet_context = {
    src_ip, dst_ip, protocol, ports,
    ingress_interface,
    namespace, vrf,
    MAC addresses
}
```

#### 第 2 层：主分析器（OVS-First 流）
按以下顺序调用 MCP 工具：

```bash
# 工具 1: analyze_flow (一体化)
#   问题：是否存在完整路径？
#   返回：path[], decision_chain, risks
#   注意：可能因 bug 返回不完整结果

# 降级策略：使用特化工具
→ get_interface_context (确定入接口所有权)
→ get_ovs_bridges (确定 OVS 是否接管)
```

#### 第 3 层：OVS 侧钻取（如果 OVS 接管）
```bash
# 工具 2: get_ovs_bridges
#   问题：流量在哪个桥中？
#   关键：VLAN 配置 = 初级转发逻辑

# 工具 3: get_ovs_flows  
#   问题：流表是否匹配？
#   返回：matched_flows (精确) vs candidate_flows (候选)
```

#### 第 4 层：L3 侧钻取（如果转向 kernel/VRF）
```bash
# 工具 4: get_rule
#   问题：策略路由规则链？
#   获取：rule_walk (完整链) + effective_rule (终止规则)

# 工具 5: get_route
#   问题：最终路由表是什么？
#   验证：下一跳设备 + 网关可达性
```

#### 第 5 层：综合路径构建
整合所有工具输出，生成完整的决策链和置信度评分。

Treat raw tool outputs as evidence, not as the answer. The answer should be a path conclusion.

---

## 具体分析流程

### 决策树 1：确定 OVS 入点

```
Q: 入接口是什么？
├─ 获取：get_interface_context(iface=<name>, namespace=<ns>)
├─ 检查：type = ? (physical, veth, internal, bridge, etc.)
└─ 决策：
    ├─ type=physical && iface 在某个 OVS 桥中
    │   → OVS 直接接管（例：DPDK 口）
    ├─ type=veth && bridge=null
    │   → kernel 直接处理
    └─ type=internal
        → OVS 内部端口，连接 kernel namespace
```

### 决策树 2：OVS 转发决策

```
Q: 流量在 OVS 中如何转发？
├─ 获取：get_ovs_bridges(bridge=<name>, include_flows=true)
├─ 检查：
│   ├─ 端口所属 VLAN 配置
│   ├─ 内部流表规则
│   └─ 是否有 patch 端口
└─ 输出：
    ├─ 转发到内部端口 (veth/vrf 侧)
    ├─ 转发到 patch 端口 (另一个桥)
    ├─ 转发到物理端口 (泛洪/学习)
    └─ 丢弃 (drop 规则)
```

### 决策树 3：Kernel/VRF 转发决策

```
Q: 流量在 VRF 中如何路由？
├─ 获取：get_rule(packet=<def>, include_rule_walk=true)
├─ 遍历：rule_walk[] 直到 terminates=true
└─ 获取：get_route(dst_ip=<ip>, vrf=<vrf>, best_only=true)
    ├─ 下一跳是什么？
    ├─ 出设备是什么？
    └─ 是否可达？
```

### 决策树 4：veth 转移验证（新增）

```
Q: 跨 namespace 转移是否有效？
├─ 检查：
│   ├─ 源端 (wan1-r) 状态 = UP?
│   ├─ 目标端 (wan1-k) 可访问?
│   ├─ MAC 地址一致?
│   ├─ link_netnsid 指向正确 namespace?
│   └─ MTU 一致?
├─ 验证命令：
│   ip link show <src>
│   ip -n <dst_ns> link show <dst>
│   ip -s link show <src> <dst>
└─ 置信度评分：
    ├─ 全部通过 → "Verified" (HIGH)
    ├─ 部分通过 → "Inferred" (MEDIUM)
    └─ 有失败 → "Failed" (LOW)
```

---

## 工具调用顺序（优化）

### 首选路径（完整诊断）
```
1. analyze_flow(packet, exec_ctx)
   ├─ 返回：complete path + decision_chain
   └─ 风险：可能 bug（缺口 #1）

2. if analyze_flow fails:
   ├─ get_interface_context(ingress_if, namespace)
   ├─ get_ovs_bridges(include_flows=true)
   ├─ get_rule(packet, include_rule_walk=true)
   ├─ get_route(dst_ip, namespace, vrf)
   ├─ get_neighbor(target_ip)
   └─ 组合输出 = 完整路径
```

### 降级路径（快速诊断）
```
1. get_interface_context(ingress_if)
2. if OVS: get_ovs_bridges(bridge)
3. if kernel: get_route(dst_ip)
4. get_neighbor(next_hop)
```

---

## 置信度分类（详细）

### Confirmed（已确认）
- 直接由 MCP 工具返回的数据
- 例：get_route 返回的路由、get_neighbor 返回的 ARP 状态
- 标记：✓ Confirmed

### Verified（已验证）
- 通过多工具交叉验证的数据
- 例：veth 对两端都 UP，MAC 一致，计数器同步
- 标记：✓ Verified

### Inferred（推断）
- 基于逻辑推断，但缺乏直接证据
- 例：根据 link_netnsid 推断 veth 对有效
- 标记：◇ Inferred

### Candidate（候选）
- 通配流表链，无精确匹配
- 但根据计数器递增验证流量转移
- 标记：▢ Candidate

### Failed（失败）
- 工具返回错误或无结果
- 例：ROUTE_NOT_FOUND、流量丢弃
- 标记：✗ Failed

---

## 监控验证指南（3 级优先级）

### Level 1：转向决策点（必须验证）

**Kernel L3 决策**：
```bash
# 规则链
ip netns exec <ns> ip rule show | grep <priority>

# 最终路由
ip netns exec <ns> ip route show table main | grep <dst>
```

**OVS 最终输出**：
```bash
# 表 50（或最终表）
ovs-ofctl dump-flows <bridge> table=<last> | grep <criteria>

# 物理端口
ovs-vsctl get-port-stats <bridge> | grep <port>
```

**验证指标**：n_packets 应 > 0 且递增

### Level 2：路径连续性（推荐验证）

```bash
# VRF 入口计数
ip netns exec <ns> ip -s link show <iface> | grep RX

# veth 对同步
ip -s link show <src>
ip -n <ns> -s link show <dst>
→ TX/RX 应对应

# OVS 中间表
ovs-ofctl dump-flows <bridge> table=<mid> | grep <match>
→ n_packets 应连贯
```

### Level 3：可达性（外部依赖）

```bash
# 下一跳 ARP
ip neighbor show to <gw>

# 物理端口状态
ovs-vsctl get-interface <port> admin-state
→ up
```

---

## 常见场景案例

### 场景 1：DPDK + OVS + VRF + 互联网

**拓扑**：
```
物理客户端 → lan1(DPDK) → OVS br-int(VLAN 2000)
                           ↓ ll3_vnet_1 (internal)
                           ↓ rl3_vnet_1 (vrf-member)
                           ↓ ANPOSNS/Vrf262147Ns (VRF)
                           ↓ wan1-r → veth → wan1-k (root)
                           ↓ kernel route → br-wan1(OVS)
                           ↓ T10→T30→T50 (流表链)
                           ↓ wan1(DPDK) → Gateway → Internet
```

**分析步骤**：
1. get_interface_context(lan1) → type=dpdk, bridge=br-int ✓
2. get_ovs_bridges(br-int) → port lan1: VLAN 2000 ✓
3. get_ovs_bridges(br-int) → port ll3_vnet_1: VLAN 2000 ✓
4. get_rule(vrf=Vrf262147Ns) → rule_walk 3 steps ✓
5. get_route(vrf=Vrf262147Ns) → 0.0.0.0/0 via wan1-r ✓
6. get_ovs_bridges(br-wan1, include_flows=true) → T50 output:1 ✓
7. get_neighbor(10.220.21.254) → PERMANENT ✓

**置信度**：HIGH (85-90%)

### 场景 2：纯 Kernel VRF（无 OVS）

**拓扑**：
```
客户端 → eth0 (kernel) → VRF-A (kernel)
                         ↓ route lookup
                         ↓ veth → eth1 (root)
                         ↓ Internet
```

**分析步骤**：
1. get_interface_context(eth0) → type=physical, bridge=null ✓
2. get_rule(vrf=VRF-A) → rule_walk ✓
3. get_route(vrf=VRF-A) → ... ✓
4. get_neighbor(...) → ... ✓

**置信度**：HIGH

### 场景 3：跨多个 OVS 桥

**拓扑**：
```
br-int → patch-port → br-wan1 → wan1
  ↓ VLAN 1999
```

**分析步骤**：
1. get_ovs_bridges(br-int) → patch-port ...
2. get_ovs_bridges(br-wan1) → ...
3. 追踪 patch 端口连接

---

## 错误处理与降级

### 错误 #1：analyze_flow 返回 'bridges' not defined

**原因**：内部 bug（缺口 #1）

**降级**：
```python
try:
    result = analyze_flow(packet, exec_ctx)
except Exception as e:
    if "bridges not defined" in str(e):
        # 降级到特化工具
        result = manual_path_analysis(packet, exec_ctx)
```

### 错误 #2：ROUTE_NOT_FOUND（VRF 查询）

**原因**：exec_ctx 未正确传递

**验证**：
```bash
ip netns exec <ns> ip route show table main | grep <dst>
```

**修复**：确保 analyze_flow 传递 namespace 和 vrf 参数

### 错误 #3：OVS 流表为空

**原因**：
- 流表使用 NORMAL 动作（MAC 学习）
- 流表使用控制器管理
- 流表在另一个表中

**诊断**：
```bash
ovs-ofctl show <bridge>
ovs-ofctl dump-flows <bridge> | head -20
```

---

## 输出格式（标准化）

```json
{
  "status": "COMPLETED",
  "packet_context": {...},
  "path": [
    {
      "hop": 0,
      "node_type": "interface",
      "description": "rl3_vnet_1 (ANPOSNS/Vrf262147Ns)",
      "confidence": "Confirmed"
    },
    {
      "hop": 1,
      "node_type": "policy_routing",
      "rule_walk": [...],
      "effective_rule": {...},
      "confidence": "Confirmed"
    },
    {
      "hop": 2,
      "node_type": "ovs_pipeline",
      "table_walk": [...],
      "confidence_level": "CANDIDATE",
      "confidence": "Candidate"
    }
  ],
  "decision_chain": [...],
  "risks": [...],
  "mermaid": "..."
}
```

---

## 快速检查清单

- [ ] 流量入接口是否被 OVS 接管？
- [ ] OVS 中的 VLAN 配置是什么？
- [ ] 是否存在跨 namespace 转移（veth）？
- [ ] 是否存在多层 OVS 桥链？
- [ ] VRF 策略路由规则链是什么？
- [ ] 最终路由表是什么？
- [ ] 下一跳是否可达？
- [ ] 所有决策点的置信度是什么？

---

**方法论**：OVS-First 优先转发分析  
**版本**：V2 改进版（包含混合转发架构）  
**最后更新**：2026-05-26  
**基于发现**：DPDK + OVS + VRF 三层混合架构分析
