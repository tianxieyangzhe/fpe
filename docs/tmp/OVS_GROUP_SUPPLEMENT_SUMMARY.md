# OVS Group 表补充分析 - 工作总结

**补充时间**：2026-05-26  
**相关文档**：3 份补充分析  
**技能更新**：V2.1（新增 Group 决策树）  

---

## 补充内容清单

### 1. **OVS_GROUP_TABLE_ANALYSIS.md** - Group 表诊断指南

**内容**：
- OVS Group 的 4 种类型详解（select/all/ff/indirect）
- Group 表与流表的交互原理
- 13 个诊断命令参考
- 3 个常见故障排查场景
- 建议补充 `get_ovs_groups` MCP 工具

**关键信息**：
```
当前客户端分析：
├─ br-int：✓ 无 Group（VLAN 处理）
├─ br-wan1：✓ 无 Group（直接输出）
└─ 转发方式：直接流表控制 ✓
```

---

### 2. **fpe-ovs-tool-thinking-SKILL-V2.1-IMPROVED.md** - 更新的技能文档

**更新内容**：

#### 原有功能保留
- 6 层分析方法（第 1-5 层保持不变）
- 4 个决策树（1-4 保持不变）
- 置信度分类（保持不变）
- 监控验证指南（保持不变）

#### 新增功能

**第 3 层扩展为 3a + 3b：**
```
第 3a 层：OVS 流表钻取
  └─ get_ovs_flows（原有）

第 3b 层：OVS Group 钻取（新增）
  └─ get_ovs_groups（建议）
     ├─ select：负载均衡
     ├─ all：多播
     ├─ ff：快速转移
     └─ indirect：间接引用
```

**新增决策树 2.5：**
```
OVS Group 转发决策
├─ 流表是否使用 group？
├─ Group 类型是什么？
├─ Bucket 如何选择？
└─ 监控 Group 转发
```

**新增监控级别 Level 1.5：**
```
Group 转发决策（若存在）
├─ 检查流表中是否有 "group:" 动作
├─ 获取 Group 定义和类型
├─ 验证 Bucket 计数器递增
└─ 确认最终输出端口
```

---

### 3. **FLOW_ANALYSIS_WITH_GROUP_TABLE.md** - Group 集成分析

**内容**：
- 当前客户端的 Group 查询结果（无 Group）
- 假设场景 A：多 WAN 口负载均衡（select Group）
- 假设场景 B：主备快速转移（ff Group）
- 完整的 Group 诊断脚本（Bash）
- 故障排查 3 大问题
- 集成监控检查清单

**核心转发路径**：
```
192.168.2.56 → lan1 (OVS br-int)
    ↓ VLAN 2000 转发
    ↓ ll3_vnet_1 → VRF
    ↓ rule_walk (3 steps) → main 表
    ↓ route: 0.0.0.0/0 via wan1-r
    ↓ veth 转移 → wan1-k (root)
    ↓ OVS br-wan1 (无 Group)
    ↓ T50: output:1 (直接转发)
    ↓ wan1 DPDK → 8.8.8.8
```

---

## 主要发现

### 1. OVS Group 在混合转发中的作用

```
br-int (第一层)：
  └─ 通常无 Group（VLAN/MAC 学习为主）

br-wan1 (第二层)：
  └─ 可能使用 Group：
     ├─ 负载均衡：多 WAN 口分流
     ├─ 故障转移：主链路故障切换
     ├─ 多播：流量复制
     └─ 间接转发：Group 链式引用
```

### 2. 当前客户端的转发确定性

| 组件 | 确定性 | 理由 |
|------|--------|------|
| OVS br-int | HIGH | VLAN 配置明确 |
| VRF 规则 | HIGH | rule_walk 完整 |
| 路由查询 | HIGH | 通配符路由存在 |
| OVS br-wan1 | HIGH | 流表直接输出 |
| **整体** | **HIGH (90%)** | **无 Group 间接** |

### 3. Group 在不同场景的应用

#### 场景 A：负载均衡（select Group）
```
特征：多 bucket，权重分布，哈希转移
监控：bucket 计数器应接近 50:50
故障：某 bucket 流量突增 → 链路故障
```

#### 场景 B：快速转移（ff Group）
```
特征：主备 bucket，watch_port 监控
监控：bucket 切换时间 < 100ms（通常）
故障：故障时 bucket 未切换 → ff Group 配置错误
```

#### 场景 C：多播（all Group）
```
特征：所有 bucket 都转发，复制包
监控：所有 bucket 计数相同
故障：某 bucket 计数为 0 → 链路问题
```

---

## 建议补充工具

### 新 MCP 工具：`get_ovs_groups`

**目的**：补充 OVS Group 表查询能力

**参数**：
```json
{
  "bridge": "br-wan1",           // 必选
  "group_id": 100,               // 可选（查特定 group）
  "include_buckets": true,       // 可选（返回 bucket 详情）
  "include_stats": true          // 可选（返回流量统计）
}
```

**返回格式**：
```json
{
  "bridge": "br-wan1",
  "groups": [
    {
      "group_id": 100,
      "type": "select",
      "n_buckets": 2,
      "buckets": [
        {
          "bucket_id": 0,
          "weight": 50,
          "actions": "output:1",
          "packet_count": 5000,
          "byte_count": 5000000
        },
        {
          "bucket_id": 1,
          "weight": 50,
          "actions": "output:2",
          "packet_count": 4950,
          "byte_count": 4950000
        }
      ]
    }
  ]
}
```

**使用流程**：
```
1. get_ovs_flows(bridge, table)
   → 检查是否包含 "group:" 动作

2. 若有 group:
   get_ovs_groups(bridge, include_stats=true)
   → 获取所有 group 定义

3. 关联分析：
   流表 group_id → Group bucket → 物理端口
```

---

## 技能更新影响

### V2 → V2.1 的变更

| 方面 | V2 | V2.1 | 影响 |
|------|-----|------|------|
| **层数** | 5 层 | 6 层 | ✓ 更细粒度 |
| **决策树** | 4 个 | 5 个 | ✓ 新增 Group 决策 |
| **工具** | 6 个 | 7 个（建议） | ✓ 补充 get_ovs_groups |
| **监控级别** | 3 级 | 3.5 级 | ✓ 新增 Level 1.5 |
| **向后兼容** | - | ✓ 完全 | ✓ 无 Group 场景不变 |

---

## 使用指南

### 何时使用 Group 分析

**触发条件**：
```bash
# 检查是否需要进行 Group 分析
if ovs-ofctl dump-flows <bridge> | grep -q "group:"; then
  echo "需要进行 Group 分析"
  # 使用 V2.1 技能的决策树 2.5
fi
```

**场景**：
1. ✓ 多 WAN 口部署
2. ✓ 故障转移配置
3. ✓ 负载均衡需求
4. ✓ 流量复制场景
5. ✗ 单链路部署（无需）

### 监控命令速查

```bash
# 快速检查是否使用 Group
ovs-ofctl dump-flows br-wan1 | grep "group:"

# 查看所有 Group
ovs-ofctl dump-groups br-wan1

# 监控特定 Group 的 Bucket 分布
ovs-ofctl dump-groups br-wan1 group_id=1000

# 持续监控 Group 转移（快速转移 ff Group）
watch -n 1 'ovs-ofctl dump-groups br-wan1 group_id=2000'

# 验证物理端口流量分布
ovs-vsctl get-port-stats br-wan1 | grep "^wan[1-2]"
```

---

## 文档关系图

```
OVS-First 技能框架
│
├─ V2.0（原始）
│  └─ 5 层分析
│     └─ 4 个决策树
│        └─ 3 级监控
│
└─ V2.1（本次更新）✓
   ├─ 6 层分析
   ├─ 5 个决策树 ← 新增决策树 2.5
   ├─ 3.5 级监控 ← 新增 Level 1.5
   └─ 建议补充工具 ← get_ovs_groups

支撑文档：
├─ OVS_GROUP_TABLE_ANALYSIS.md
│  └─ 详细的 Group 诊断指南
├─ FLOW_ANALYSIS_WITH_GROUP_TABLE.md
│  └─ 集成分析 + 故障排查
└─ 现有分析报告
   └─ 客户端 192.168.2.56 → 8.8.8.8（无 Group）
```

---

## 验证检查清单

### ✓ 已完成

- [x] OVS Group 原理分析
- [x] 4 种 Group 类型详解
- [x] 决策树 2.5 设计
- [x] 新增监控 Level 1.5
- [x] 诊断脚本编写
- [x] 故障排查文档
- [x] 建议工具设计
- [x] 技能文档 V2.1
- [x] 集成分析示例
- [x] 向后兼容性确认

### ◇ 建议后续

- [ ] 实现 `get_ovs_groups` MCP 工具
- [ ] 补充 Group 相关的单元测试
- [ ] 在真实多 WAN 环境验证
- [ ] 补充故障转移场景的端到端测试
- [ ] 更新项目文档引用 V2.1 技能

---

## 总结

通过补充 OVS Group 表分析，我们：

1. **扩展了 OVS-First 分析框架**
   - 从 5 层升级到 6 层
   - 新增决策树 2.5（Group 转发）
   - 新增监控 Level 1.5（Group 决策）

2. **提升了诊断完整性**
   - 覆盖负载均衡场景
   - 支持故障转移验证
   - 支持多播场景分析

3. **保持了向后兼容**
   - 无 Group 场景不受影响
   - 所有原有工具保持不变
   - Group 为可选分析路径

4. **提供了实用工具**
   - 完整的诊断脚本
   - 故障排查指南
   - 监控命令速查

**当前客户端分析结论**：
```
✓ 不使用 Group 表
✓ 转发通过流表直接控制
✓ 确定性高（90%）
✓ 路径转发正常
```

---

**补充完成时间**：2026-05-26  
**涉及文档**：3 份（诊断 + 技能 + 分析）  
**技能版本**：V2.1  
**向后兼容**：✓ 完全兼容
