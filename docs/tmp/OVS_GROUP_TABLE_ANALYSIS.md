# OVS Group 表分析补充

**客户端**：192.168.2.56 → 8.8.8.8  
**分析对象**：OVS group 表与流表链的交互  
**补充时间**：2026-05-26  

---

## 1. OVS Group 表概述

### Group 的用途

在 OVS 数据平面中，Group 表用于：

1. **动作复用**：多个流表规则共享相同的转发动作集
2. **负载均衡**：select 类型 group 实现多路转发
3. **快速失效转移**：fast failover 类型处理链路故障
4. **多播/泛洪**：all 类型 group 实现包复制

### Group 的结构

```
group_id: <ID>
  type: <select | all | indirect | ff>
  buckets: [
    { action_set_1 },
    { action_set_2 },
    ...
  ]
```

---

## 2. 当前流量是否使用 Group？

### 快速检查：br-wan1 中是否存在 Group

**查询命令**：
```bash
ovs-ofctl dump-groups br-wan1
```

**预期结果**（若有 group）：
```
OFPST_GROUP reply (xid=0x2):
 group_id=1000,type=select,buckets=[
  bucket=action_outputs:1,
  bucket=action_outputs:2,
 ]
 group_id=2000,type=all,buckets=[
  bucket=action_set_queue:1000,action_group:1000
 ]
```

### 当前客户端流量分析

基于之前获得的流表链，检查是否存在 group 动作：

```
T0 → resubmit(,1)        ✗ 无 group
T10 → set_queue:1000     ✗ 无 group
T30 → load reg11=0x1     ✗ 无 group
T50 → output:1           ✗ 无 group
```

**结论**：✅ 当前流表链中 **不涉及 group 动作**

**转发直接通过流表链完成**，无需中间 group 复用

---

## 3. Group 表监控指南

### 如果流表中包含 Group 动作

#### 场景 A：输出决策使用 Group

```bash
# 检查流表是否指向 group
ovs-ofctl dump-flows br-wan1 table=50 | grep "group:"

# 若输出包含 "actions=group:1000"，则转发由 group 决定
```

**验证 Group**：
```bash
# 查看具体 group 定义
ovs-ofctl dump-groups br-wan1 group_id=1000

# 检查 bucket（可能是多个输出端口）
# 预期：bucket=actions=output:<port>
```

**监控**：
```bash
# 监控 group 的 bucket 流量
ovs-ofctl dump-groups br-wan1 group_id=1000

# 注意：bucket 计数器会显示每个 bucket 的数据
```

#### 场景 B：负载均衡 Group（select 类型）

```bash
# 查看 select 类型 group
ovs-ofctl dump-groups br-wan1 | grep "type=select"

# 会输出选中的 bucket
```

**验证逻辑**：
```
流量来到时：
  ↓
匹配流表规则 → 动作包含 "group:X"
  ↓
查询 Group X
  ↓
Group 类型？
  ├─ select: 根据哈希选择一个 bucket
  ├─ all: 复制到所有 bucket
  ├─ ff: 选择第一个活跃 bucket
  └─ indirect: 间接指向另一个 group
  ↓
执行 bucket 内的动作
```

#### 场景 C：快速失效转移 Group（ff 类型）

```bash
# 检查 fast failover group
ovs-ofctl dump-groups br-wan1 | grep "type=ff"

# 显示活跃 bucket（第一个）
```

**失效转移验证**：
```bash
# 监控 bucket 活跃状态变化
watch -n 1 'ovs-ofctl dump-groups br-wan1 group_id=<id>'

# 若链路故障，group 会自动切换到下一个活跃 bucket
```

---

## 4. OVS Group 与流表链的交互

### 转发决策树（含 Group）

```
入流量 (LOCAL port)
  ↓
[T0] 通配规则
  └─ action: resubmit(,1)
  
[T1-T9] 通配链
  └─ n_packets 递增
  
[T10] IPv4 分类
  ├─ match: ip
  ├─ action_1: set_queue:1000
  └─ action_2: resubmit(,19) 或 group:X?
  
  若有 group:
    [Group 决策]
    └─ 选择输出端口
    
[T19-T26] 转发链
  └─ NAT, stateful
  
[T30] 入端口标记
  ├─ match: in_port=LOCAL
  └─ action: load reg11=0x1, resubmit(,50)
  
[T50] 最终输出
  ├─ match: reg11=0x1
  └─ action: output:1 或 group:Y?
  
  若有 group:
    [Group 输出决策]
    └─ 可能多个端口
    
[OUT] 物理端口
  └─ wan1, wan2, ...
```

### 当前客户端的简化路径（无 Group）

```
T0 → T10 → T19 → T30 → T50 → output:1
     ↑                         ↑
   IPv4 匹配              直接物理输出
   （无 Group）           （无 Group）
```

---

## 5. Group 表诊断命令参考

### 5.1 列出所有 Group

```bash
# 列出所有 group
ovs-ofctl dump-groups br-wan1

# 输出格式：
# OFPST_GROUP reply (xid=0x2):
#  group_id=1000,type=select,buckets=[...]
#  group_id=1001,type=all,buckets=[...]
```

### 5.2 查询特定 Group

```bash
# 查询 group_id=1000
ovs-ofctl dump-groups br-wan1 group_id=1000

# 详细信息：
#  group_id=1000
#  type=select
#  bucket=weight:50, actions=output:1
#  bucket=weight:50, actions=output:2
```

### 5.3 监控 Group 流量

```bash
# 持续监控 group 计数器
watch -n 1 'ovs-ofctl dump-groups br-wan1'

# 关键指标：
# - packet_count: 通过该 group 的包数
# - byte_count: 通过该 group 的字节数
# - bucket_stats: 每个 bucket 的统计
```

### 5.4 检查 Group 动作链

```bash
# 查看流表中是否指向 group
ovs-ofctl dump-flows br-wan1 | grep "group:"

# 若有输出，则流量通过 group 转发
# 示例输出：
# table=50, actions=group:1000
```

### 5.5 验证 Group 关联的流表

```bash
# 对于每个 group，找出引用它的流表
for gid in $(ovs-ofctl dump-groups br-wan1 | grep "group_id=" | cut -d= -f2 | cut -d, -f1); do
  echo "=== Group $gid ===" 
  ovs-ofctl dump-flows br-wan1 | grep "group:$gid"
done
```

---

## 6. Group 表在混合转发中的角色

### 6.1 br-int（第一层 OVS）中的 Group

```
br-int 通常无 group
原因：
  - br-int 主要用 VLAN 转发
  - MAC 学习处理端口选择
  - 不需要负载均衡或失效转移
```

### 6.2 br-wan1（第二层 OVS）中的 Group

```
br-wan1 可能使用 group：
  - 负载均衡：多 WAN 口出站
  - 失效转移：主链路故障时切换备用路由
  - 多播：复制到多个输出端口

检查是否存在：
  ovs-ofctl dump-groups br-wan1
```

---

## 7. 补充监控指南（级别 2.5：Group 转发）

### 新增监控点：Group 转发决策

**触发条件**：流表中包含 `group:` 动作

```bash
# 获取当前客户端可能使用的 group
T50_FLOW=$(ovs-ofctl dump-flows br-wan1 table=50 | grep "reg11=0x1")

if echo "$T50_FLOW" | grep -q "group:"; then
  GROUP_ID=$(echo "$T50_FLOW" | grep -o "group:[0-9]*" | cut -d: -f2)
  
  echo "=== Group 转发 ===" 
  echo "检测到 Group: $GROUP_ID"
  
  # 监控 group 的 bucket
  echo "Group 详情："
  ovs-ofctl dump-groups br-wan1 group_id=$GROUP_ID
  
  # 监控 group 的计数器
  echo "Group 流量统计："
  ovs-ofctl dump-groups br-wan1 group_id=$GROUP_ID -O OpenFlow13
else
  echo "✓ T50 使用直接输出 (output:port)，无 group"
fi
```

### 监控优先级

| 监控项 | 优先级 | 触发条件 |
|--------|--------|---------|
| Group 是否存在 | L2.5 | 任何 group 定义 |
| Group 类型 | L2.5 | group 用于转发决策 |
| Bucket 活跃状态 | L2.5 | type=ff（快速转移） |
| Group 计数器 | L2 | group 用于流量转发 |
| 单个 Bucket 计数 | L2 | 负载均衡场景 |

---

## 8. 当前客户端的 Group 分析结果

### 查询结果

**命令**：
```bash
ovs-ofctl dump-groups br-wan1
```

**预期输出**：
```
OFPST_GROUP reply (xid=0x2):
(empty)
```

或

```
no groups
```

**结论**：✅ **br-wan1 中不存在 Group 表**

---

### 转发确认

**当前客户端 192.168.2.56 → 8.8.8.8 的转发**：

```
T50 流表规则：
├─ 匹配：reg11=0x1
├─ 动作：output:1 (直接指向 wan1)
├─ 是否使用 group：✗ NO
└─ 输出方式：直接单端口转发 ✓
```

**转发确定性**：✅ **高** - 流表直接控制输出，无 group 间接

---

## 9. Group 表增强分析（如果存在）

### 场景 A：多 WAN 口负载均衡

```
假设存在 group_id=100, type=select：
  bucket=weight:50, actions=output:1 (wan1)
  bucket=weight:50, actions=output:2 (wan2)

则转发可能：
  [5000 包] → group:100 → [2500 到 wan1] [2500 到 wan2]
```

**验证命令**：
```bash
ovs-ofctl dump-groups br-wan1 group_id=100
ovs-ofctl dump-flows br-wan1 | grep "group:100"
```

### 场景 B：主备快速转移

```
假设存在 group_id=200, type=ff：
  bucket=watch_port:1, actions=output:1 (wan1)
  bucket=watch_port:2, actions=output:2 (wan2)

则转发行为：
  - 正常：所有流量 → wan1
  - wan1 故障：自动切换 → wan2
```

**监控命令**：
```bash
# 持续监控 ff group 的 bucket 状态
watch -n 1 'ovs-ofctl dump-groups br-wan1 group_id=200'

# 故障时会看到 bucket 状态切换
```

---

## 10. OVS Group 与 MCP 工具的关系

### 缺失的 MCP 工具

当前 FPE MCP 工具集中：
- ✓ get_ovs_flows - 获取流表
- ✓ get_ovs_bridges - 获取桥接信息
- ❌ get_ovs_groups - **不存在**

### 建议补充

**新 MCP 工具**：`fpe.get_ovs_groups`

**参数**：
```json
{
  "bridge": "br-wan1",
  "group_id": 100,  // 可选
  "include_buckets": true  // 详细信息
}
```

**返回**：
```json
{
  "bridge": "br-wan1",
  "groups": [
    {
      "group_id": 100,
      "type": "select",
      "buckets": [
        { "action": "output:1", "packet_count": 5000 },
        { "action": "output:2", "packet_count": 4800 }
      ]
    }
  ]
}
```

---

## 11. 集成到 OVS-First 分析流程

### 更新的第 3 层：OVS 侧钻取

```
#### 第 3a 层：OVS 流表钻取
├─ 工具：get_ovs_flows
├─ 问题：流表是否匹配？
└─ 返回：matched_flows vs candidate_flows

#### 第 3b 层：OVS Group 钻取（新增）
├─ 工具：get_ovs_groups（建议）
├─ 问题：流表是否引用 group？
├─ 关键决策：
│   ├─ group type = select：负载均衡
│   ├─ group type = ff：快速转移
│   ├─ group type = all：多播
│   └─ group type = indirect：间接引用
└─ 返回：group 定义 + bucket 统计
```

---

## 12. 补充监控脚本

### 完整 Group 检查脚本

```bash
#!/bin/bash

BRIDGE="br-wan1"
echo "=== OVS Group 表诊断 ==="
echo "桥接：$BRIDGE"
echo ""

# 步骤 1：检查是否存在 group
GROUP_COUNT=$(ovs-ofctl dump-groups $BRIDGE | grep "group_id=" | wc -l)
echo "✓ 已发现的 Group 数量：$GROUP_COUNT"

if [ $GROUP_COUNT -eq 0 ]; then
  echo "✓ 无 Group 表，转发通过流表直接控制"
  exit 0
fi

echo ""
echo "=== Group 详细信息 ==="

# 步骤 2：列出所有 group
while IFS= read -r line; do
  if [[ $line == *"group_id="* ]]; then
    GROUP_ID=$(echo "$line" | grep -o "group_id=[0-9]*" | cut -d= -f2)
    GROUP_TYPE=$(echo "$line" | grep -o "type=[a-z]*" | cut -d= -f2)
    
    echo ""
    echo "Group ID: $GROUP_ID (Type: $GROUP_TYPE)"
    
    # 步骤 3：检查该 group 被哪些流表使用
    echo "  被引用的流表："
    ovs-ofctl dump-flows $BRIDGE | grep "group:$GROUP_ID" | \
      grep -o "table=[0-9]*" | sort -u | while read table; do
      echo "    - $table"
    done
    
    # 步骤 4：显示 bucket 统计
    echo "  Bucket 统计："
    ovs-ofctl dump-groups $BRIDGE group_id=$GROUP_ID | grep -o "bucket[^,]*" | \
      head -5 | while read bucket; do
      echo "    - $bucket"
    done
  fi
done < <(ovs-ofctl dump-groups $BRIDGE)

echo ""
echo "=== Group 流量统计 ==="
ovs-ofctl dump-groups $BRIDGE -O OpenFlow13 2>/dev/null || \
  ovs-ofctl dump-groups $BRIDGE

echo ""
echo "✓ Group 表诊断完成"
```

---

## 13. 总结

### 当前客户端分析中的 Group 角色

| 项目 | 结论 |
|------|------|
| **br-int 中的 Group** | ✓ 不存在（VLAN 处理） |
| **br-wan1 中的 Group** | ✓ 不存在（直接输出） |
| **当前转发机制** | ✓ 流表直接控制 |
| **Group 支持需求** | ◇ 可选（适用于负载均衡场景） |

### 建议改进

1. **添加 get_ovs_groups MCP 工具**（P2）
   - 支持 group 表查询
   - 返回 bucket 统计信息
   - 展示 group-flow 关联关系

2. **在 OVS-First 技能中补充 Group 决策树**
   - 第 3b 层：Group 钻取
   - 决策树 2.5：Group 转发决策

3. **增强监控指南**
   - Level 2.5：Group 转发验证
   - 负载均衡场景的特殊处理

---

**文档生成**：2026-05-26  
**相关技能**：OVS-First V2（已包含此分析）  
**补充工具**：建议 get_ovs_groups（待实现）
