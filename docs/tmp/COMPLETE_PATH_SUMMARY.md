# FPE V4 改进方案 — 完整路径（OVS-First）

**生成时间**：2026-05-26  
**方法论**：OVS-First Thinking + 结构化路径分析  
**版本**：V4 完整改进方案  
**状态**：✅ 设计完成 → 📍 进入实施

---

## 📋 项目交付物

### 核心文档（按阅读顺序）

#### 1. **IMPROVEMENT_V4_OVS_FIRST.md** ← 🔍 你在这里
本文档（最新）使用 OVS-First 思维方法，按照 fpe-ovs-tool-thinking 技能的结构化分析方式：
- **第一层**：缺口定义（将每个缺口视为"包"定义）
- **第二层**：工具流 Drill Down（主分析器优先）
- **第三层**：针对性 Drill Down（每个缺口的深度分析）
- **第四层**：综合改进路由图（全局工具调用流）
- **第五层**：监控和验证指南（Level 1-3 优先级）

**特点**：
- 严格区分 Confirmed / Inferred / Unconfirmed
- OVS-first 的分层分析
- 明确的工具调用顺序
- 详细的验证和监控点

#### 2. **IMPROVEMENT_PLAN_V4.md**
高层改进方案，包含：
- 执行摘要
- 4 项改进的商业级介绍
- 实施计划和风险评估

#### 3. **IMPLEMENTATION_CHECKLIST.md**
实施细节清单，包含：
- 代码变更示例
- 单元测试框架
- 集成验证脚本

#### 4. **PROJECT_COMPLETION_SUMMARY.md**
项目总结报告。

---

## 🎯 核心改进概览（OVS-First 视角）

### 缺口 #1：ROUTE_NOT_FOUND 矛盾（P0）

```
问题路径：
  User → analyze_flow(namespace=ANPOSNS, vrf=Vrf262147Ns)
           ↓ 内部路由查找
           ✗ ROUTE_NOT_FOUND

正确路径（get_route 证实）：
  ANPOSNS/Vrf262147Ns
    → policy rule:32766(main) ✓
    → route: 0.0.0.0/0 via wan1-r ✓

根本原因：
  _resolve_route() 未传递 exec_ctx
  → 默认查询 root namespace
  → 查不到 VRF 中的路由

修复：
  async def _resolve_route_with_context(state, dst_ip):
      routes = get_route(
          namespace=state.exec_ctx.namespace,      # ✓ 正确
          vrf=state.exec_ctx.vrf,                  # ✓ 正确
      )
      return find_best_route(routes, dst_ip)
```

**验证**：analyze_flow 输出 == get_route 输出 ✓

---

### 缺口 #2：rule_walk 不完整（P1）

```
问题路径：
  decision_chain: [
    { event: "rule_lookup", selected_rule: {priority: 0} }  # ❌ 仅 1 step
  ]

正确路径（get_rule 证实）：
  rule_walk: [
    { priority: 0, table: "local", fallthrough },
    { priority: 1000, table: "l3mdev", fallthrough },
    { priority: 32766, table: "main", TERMINATE } ✓
  ]

根本原因：
  analyze_flow 仅查找 selected_rule
  未调用 build_rule_walk() 获取完整链

修复：
  async def _analyze_l3_rules(state):
      rule_walk = await build_rule_walk(...)  # ✓ 完整链
      state.rule_walk = rule_walk
      # 转换为 decision_chain
      for step, rule in enumerate(rule_walk):
          decision_chain.append(DecisionEvent(...))
```

**验证**：analyze_flow.decision_chain length = 3 ✓

---

### 缺口 #3：OVS 候选流表无可视化（P2）

```
问题：
  get_ovs_flows(packet=UDP/53)
    → matched_flows: []
    → 用户无法了解转发路径

根本原因：
  UDP/53 无精确流表匹配
  但通过通配链转发（候选）
  工具未输出表链和置信度

修复（工具链）：
  [OVS 数据平面]
  入: in_port=LOCAL
  → T0(通配) → T1 → ... → T10(精确 "ip")
  → T19 → ... → T30(精确 "in_port=LOCAL")
  → T50(精确 "reg11=0x1") → output:1
  
  输出：
  {
    table_walk: [T0→T10(精确)→T30(候选)→T50(候选)],
    confidence_level: "CANDIDATE",
    non_match_reasons: [T11(tcp mismatch), T14(port mismatch), ...],
    explanation: "通配流表链..."
  }
```

**验证**：analyze_flow.ovs_flow_walk.confidence_level == "CANDIDATE" ✓

---

### 缺口 #4：veth 转发缺乏验证（P3）

```
问题：
  跨 namespace 转移标记为 "Inferred"
  缺乏完整验证

根本原因：
  仅基于 MAC + netnsid 推断
  未检查两端 UP、MTU 一致等

修复：
  async def verify_veth_pair(executor, source_iface, source_ns):
      checks = [
          ("source_up", src.state == "UP"),
          ("target_up", dst.state == "UP"),
          ("mac_match", src.mac == dst.mac),
          ("bidirectional_netnsid", ...),
      ]
      
      return {
          "is_valid": all(checks),
          "checks": detailed_checks,
          "confidence": "HIGH" if all_pass else "MEDIUM"
      }
  
  输出路径节点：
  {
    hop: wan1-r → wan1-k,
    confidence: "Verified" (从 Inferred 升级),
    veth_info: { checks: [...], confidence: "HIGH" }
  }
```

**验证**：path[hop].confidence == "Verified" ✓

---

## 🔄 工具调用流（OVS-First 顺序）

```
第 1 阶段：包定义
  ├─ src_ip, dst_ip, ingress_if
  ├─ protocol, src_port, dst_port
  ├─ namespace, vrf
  └─ 完整 packet context ✓

第 2 阶段：主分析器（OVS-First）
  analyze_flow()
    ├─ 入接口是什么？
    ├─ OVS 接管吗？
    ├─ OVS 内的决策（bridge → port → flow）
    └─ 交给 kernel L3 吗？

第 3 阶段：if OVS involved
  get_ovs_bridges + get_ovs_flows
    ├─ 入桥是哪个？
    ├─ ingress port 是什么？
    ├─ 流表链如何转移？
    └─ matched_flows vs candidate_flows

第 4 阶段：if kernel L3 involved
  get_rule + get_route
    ├─ 规则链（rule_walk）
    ├─ 最终路由表
    ├─ 最终路由
    └─ 下一跳可达性

第 5 阶段：综合路径
  构建完整决策链
    ├─ OVS 侧的确定性
    ├─ L3 侧的确定性
    ├─ veth 转移的验证
    └─ 最终 risk 标记
```

---

## 📊 改进指标对比

| 指标 | 当前（v3） | 改进后（v4） | 预期收益 |
|------|-----------|-----------|---------|
| **工具一致性** | ⚠️ 部分（VRF bug） | ✅ 100% | 消除矛盾 |
| **诊断完整性** | ⚠️ ~60% | ✅ ~95% | 完整链路 |
| **置信度标记** | ❌ 无 | ✅ 有 | 判断可靠性 |
| **rule_walk** | ❌ 1 step | ✅ N steps | 完整规则链 |
| **OVS 候选链** | ⚠️ 无标记 | ✅ 标记清晰 | 理解转发 |
| **veth 验证** | ⚠️ Inferred | ✅ Verified | 可靠跨域 |
| **容器化支持** | ⚠️ 有限 | ✅ 完整 | 支持复杂网络 |

---

## 🚀 分阶段实施计划

### Phase 1：P0 改进（第 1-2 周）

**目标**：消除 ROUTE_NOT_FOUND 矛盾

```
Week 1：
  ├─ 编码：_resolve_route_with_context()
  ├─ 测试：test_analyzer_vrf_routes.py
  └─ 验证：analyze_flow vs get_route 一致性

Week 2：
  ├─ 集成测试
  ├─ 回归测试（root namespace）
  └─ 发布：v4.0-beta
```

### Phase 2：P1 改进（第 2-3 周）

**目标**：完整 rule_walk 输出

```
实施：
  ├─ AnalysisResult 扩展（新增字段）
  ├─ _analyze_l3_rules() 实现
  ├─ decision_chain N-step 转换
  └─ Mermaid 图增强

测试：
  └─ test_analyzer_rule_walk.py
```

### Phase 3：P2 改进（第 3-4 周）

**目标**：OVS 候选链和置信度

```
实施：
  ├─ OvsFlowWalk 数据模型
  ├─ build_candidate_flow_walk() 增强
  ├─ table_walk + non_match_reasons
  ├─ confidence_level 分类
  └─ Mermaid 虚线标记

测试：
  └─ test_ovs_candidate_walk.py
```

### Phase 4：P3 改进（第 4-5 周）

**目标**：veth 转发验证

```
实施：
  ├─ VethVerification 模型
  ├─ verify_veth_pair() 函数
  ├─ PathNode.veth_info 扩展
  └─ Mermaid 验证状态显示

测试：
  └─ test_veth_verification.py
```

### Phase 5：最终化（第 5 周）

```
├─ 集成测试（完整端到端）
├─ 回归测试（所有场景）
├─ 性能验证（<10% 延迟增加）
├─ 文档完善
└─ v4.0 GA 发布
```

---

## 📍 监控验证指南（OVS-First 优先级）

### Level 1：转向决策点（最高优先级）

**Kernel L3 侧**：

```bash
# 规则链验证
ip netns exec ANPOSNS ip rule show
→ 应看到 32766: from all lookup main

# 最终路由验证
ip netns exec ANPOSNS ip route show table main | grep "^0.0.0.0"
→ 0.0.0.0/0 via 10.220.21.254 dev wan1-r
```

**OVS 侧**：

```bash
# 最终输出决策（T50）
ovs-ofctl dump-flows br-wan1 table=50 | grep "reg11=0x1"
→ n_packets > 0

# 物理端口输出
ovs-vsctl get-port-stats br-wan1 | grep "^wan1"
→ TX 包数增长
```

### Level 2：路径连续性（验证流量流动）

```bash
# VRF 入口
ip netns exec ANPOSNS ip -s link show rl3_vnet_1 | grep RX

# veth 对（双向）
ip -s link show wan1-r | grep RX
ip -s link show wan1-k | grep RX

# OVS 中间点
ovs-ofctl dump-flows br-wan1 table=30 | grep "in_port=LOCAL"
→ n_packets 应对应
```

### Level 3：可达性（外部依赖）

```bash
# 下一跳 ARP
ip neighbor show to 10.220.21.254
→ state REACHABLE

# 物理端口状态
ovs-vsctl get-interface wan1 admin-state
→ up
```

### 候选路径验证（P2 特定）

```bash
# 优先级排序
1. T10(ip 精确)    → ovs-ofctl dump-flows br-wan1 table=10 | grep "ip"
2. T30(in_port)    → ovs-ofctl dump-flows br-wan1 table=30 | grep "in_port=LOCAL"
3. T50(reg11)      → ovs-ofctl dump-flows br-wan1 table=50 | grep "reg11=0x1"
4. output:1        → ovs-vsctl get-port-stats br-wan1 | grep "^wan1"
```

### veth 验证监控（P3 特定）

```bash
# 两端都 UP？
ip link show wan1-r wan1-k | grep "state UP"

# MAC 一致？
ip link show wan1-r | grep address
ip link show wan1-k | grep address
→ 应一致

# 计数器连贯？
ip -s link show wan1-r | grep TX
ip -s link show wan1-k | grep RX
→ 应对应
```

---

## 📈 预期效果示例

### 当前（v3）输出

```json
{
  "status": "INCOMPLETE",
  "path": [],
  "risks": [
    {
      "code": "ROUTE_NOT_FOUND",
      "message": "No route found for destination 8.8.8.8"
    }
  ]
}
```

### 改进后（v4）输出

```json
{
  "status": "COMPLETED",
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
      "rule_walk": [
        {"priority": 0, "table": "local", "result": "no_route"},
        {"priority": 1000, "table": "l3mdev", "result": "no_route"},
        {"priority": 32766, "table": "main", "result": "route_found", "terminates": true}
      ],
      "effective_rule": {"priority": 32766, "table": "main"},
      "confidence": "Confirmed"
    },
    {
      "hop": 2,
      "node_type": "route",
      "description": "0.0.0.0/0 via 10.220.21.254 dev wan1-r",
      "confidence": "Confirmed"
    },
    {
      "hop": 3,
      "node_type": "veth_transition",
      "description": "wan1-r (ANPOSNS) → wan1-k (root ns)",
      "veth_info": {
        "is_valid": true,
        "checks": [
          {"check": "source_up", "result": "PASS"},
          {"check": "target_up", "result": "PASS"},
          {"check": "mac_match", "result": "PASS"}
        ],
        "confidence": "HIGH"
      },
      "confidence": "Verified"
    },
    {
      "hop": 4,
      "node_type": "ovs_ingress",
      "description": "br-wan1 LOCAL port",
      "confidence": "Confirmed"
    },
    {
      "hop": 5,
      "node_type": "ovs_pipeline",
      "ovs_flow_walk": {
        "table_walk": [
          {"table": 0, "selected": true, "action": "resubmit(,1)"},
          {"table": 10, "selected": true, "action": "set_queue:1000,resubmit(,19)", "match_type": "exact"},
          {"table": 30, "selected": true, "action": "load:0x1→reg11,resubmit(,50)", "match_type": "candidate"},
          {"table": 50, "selected": true, "action": "output:1", "match_type": "candidate"}
        ],
        "matched_flows": [],
        "candidate_flows": [...],
        "confidence_level": "CANDIDATE",
        "explanation": "通配流表链，UDP/53 无精确匹配"
      },
      "confidence": "Candidate"
    },
    {
      "hop": 6,
      "node_type": "neighbor",
      "description": "10.220.21.254 (REACHABLE)",
      "confidence": "Confirmed"
    }
  ],
  "decision_chain": [
    {"step": 0, "event": "rule_lookup", "rule": {"priority": 0, "table": "local"}, "verdict": "PASS"},
    {"step": 1, "event": "rule_lookup", "rule": {"priority": 1000, "table": "l3mdev"}, "verdict": "PASS"},
    {"step": 2, "event": "rule_lookup", "rule": {"priority": 32766, "table": "main"}, "verdict": "TERMINATE"}
  ],
  "rule_walk": [
    {"priority": 0, "table": "local", "lookup_result": "no_route", "terminates": false},
    {"priority": 1000, "table": "l3mdev", "lookup_result": "no_route", "terminates": false},
    {"priority": 32766, "table": "main", "lookup_result": "route_found", "terminates": true}
  ],
  "final_table": "main",
  "effective_route": {
    "prefix": "0.0.0.0/0",
    "next_hops": [{"via": "10.220.21.254", "dev": "wan1-r"}]
  },
  "risks": [],
  "mermaid": "... (完整可视化)"
}
```

---

## ✅ 完成检查清单

### 设计阶段 ✓
- [x] 识别 4 个关键缺口
- [x] 用 OVS-First 思维分析根本原因
- [x] 设计改进方案（代码级）
- [x] 制定实施计划
- [x] 编写监控验证指南

### 实施阶段 📍
- [ ] #2 修复 ROUTE_NOT_FOUND bug
- [ ] #3 增强 rule_walk 输出
- [ ] #4 OVS 候选链优化
- [ ] #5 veth 转发验证

### 测试阶段 📋
- [ ] 单元测试 (4 个模块)
- [ ] 集成测试 (完整流程)
- [ ] 回归测试 (所有场景)
- [ ] 性能测试 (<10% 延迟)

### 发布阶段 🎉
- [ ] 文档完善
- [ ] v4.0 GA 发布

---

## 📚 相关文档

- **IMPROVEMENT_V4_OVS_FIRST.md** ← 你在这里（OVS-First 结构化分析）
- **IMPROVEMENT_PLAN_V4.md** ← 高层改进方案
- **IMPLEMENTATION_CHECKLIST.md** ← 实施细节
- **PROJECT_COMPLETION_SUMMARY.md** ← 项目总结
- **fpe-flow-analysis-v3.md** ← 原始问题分析
- **README.md** ← 项目概述

---

**方法论**：OVS-First Thinking (fpe-ovs-tool-thinking 技能)  
**生成时间**：2026-05-26  
**文档版本**：1.0  
**阶段**：设计完成 → 进入实施
