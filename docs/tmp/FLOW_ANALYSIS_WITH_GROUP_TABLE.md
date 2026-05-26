# 补充路径分析：OVS Group 表集成

**客户端**：192.168.2.56 (MAC: 00:e0:53:17:e6:b7) **→** 8.8.8.8  
**分析对象**：流表-Group 交互的完整诊断  
**补充日期**：2026-05-26  
**基于技能**：V2.1（包含 Group 分析）  

---

## 当前状态：Group 表查询结果

### 查询命令

```bash
# 查询 br-wan1 中的所有 group 表
ovs-ofctl dump-groups br-wan1

# 查询 br-int 中的 group 表
ovs-ofctl dump-groups br-int
```

### 当前结果

| 桥接 | Group 数量 | 状态 | 转发类型 |
|------|-----------|------|---------|
| **br-int** | 0 | ✓ 无 | VLAN MAC 学习 |
| **br-wan1** | 0 | ✓ 无 | 直接流表输出 |

**结论**：✅ 当前客户端转发 **不使用 Group 表**

---

## 转发路径确认（无 Group）

### br-wan1 中的关键流表

```bash
# T50（最终输出）
ovs-ofctl dump-flows br-wan1 table=50
```

**预期输出**：
```
table=50, priority=10, reg11=0x1 actions=output:1
```

**关键属性**：
- ✓ match: `reg11=0x1` （标记匹配）
- ✓ action: `output:1` （直接输出）
- ✗ 无 `group:` 动作

**转发确定性**：✓ **直接单端口转发，无 Group 间接**

---

## 假设场景 A：如果存在负载均衡 Group

### 场景描述

假设需要在两个 WAN 口（wan1, wan2）之间进行负载均衡

### 流表配置（假设）

```bash
# T50 使用 group 替代直接 output
table=50, priority=10, reg11=0x1 actions=group:1000
```

### Group 配置（假设）

```bash
# Group 定义
group_id=1000,type=select,buckets=[
  bucket=weight:50,actions=output:1,
  bucket=weight:50,actions=output:2
]
```

### 诊断步骤

#### 步骤 1：识别 Group 使用

```bash
# 查看 T50 是否引用 group
ovs-ofctl dump-flows br-wan1 table=50 | grep "group:"

# 输出：table=50, ... actions=group:1000
# 结论：✓ 检测到 group 引用
```

#### 步骤 2：查询 Group 定义

```bash
# 获取 group 1000 的详细信息
ovs-ofctl dump-groups br-wan1 group_id=1000

# 预期输出：
# group_id=1000,type=select,buckets=[
#   bucket=weight:50, actions=output:1, packet_count=5000, byte_count=...
#   bucket=weight:50, actions=output:2, packet_count=4950, byte_count=...
# ]
```

#### 步骤 3：验证转发分布

```bash
# 监控 bucket 计数器
BUCKET_1=$(ovs-ofctl dump-groups br-wan1 group_id=1000 | grep "bucket=" | head -1 | grep -o "packet_count=[0-9]*" | cut -d= -f2)
BUCKET_2=$(ovs-ofctl dump-groups br-wan1 group_id=1000 | grep "bucket=" | tail -1 | grep -o "packet_count=[0-9]*" | cut -d= -f2)

echo "Bucket 1 (wan1): $BUCKET_1"
echo "Bucket 2 (wan2): $BUCKET_2"

# 预期：接近 50:50 的分布
```

#### 步骤 4：验证物理端口输出

```bash
# 监控 wan1 和 wan2 的输出计数
WAN1_TX=$(ovs-vsctl get-port-stats br-wan1 | grep "^wan1" | grep "tx_packets" | awk '{print $2}')
WAN2_TX=$(ovs-vsctl get-port-stats br-wan1 | grep "^wan2" | grep "tx_packets" | awk '{print $2}')

echo "wan1 TX packets: $WAN1_TX"
echo "wan2 TX packets: $WAN2_TX"

# 预期：两个端口都有可观的流量
```

### 转发验证结果

| 检查点 | 预期 | 验证方式 |
|--------|------|---------|
| Group 类型 | select | `ovs-ofctl dump-groups \| grep type=select` |
| Bucket 数 | 2 | `ovs-ofctl dump-groups \| grep bucket \| wc -l` |
| 负载分布 | ~50:50 | `packet_count` 对比 |
| 物理输出 | 2 个端口 | `wan1` 和 `wan2` 都有流量 |

---

## 假设场景 B：如果存在快速转移 Group

### 场景描述

主 WAN1 故障时自动切换到备 WAN2

### Group 配置（假设）

```bash
# Fast Failover Group
group_id=2000,type=ff,buckets=[
  bucket=watch_port:1,actions=output:1,
  bucket=watch_port:2,actions=output:2
]
```

### 诊断步骤

#### 步骤 1：检查 Group 类型

```bash
ovs-ofctl dump-groups br-wan1 group_id=2000
```

**关键字段**：
- `type=ff` （快速转移）
- `watch_port:1` （监控 port 1）
- `watch_port:2` （监控 port 2）

#### 步骤 2：监控 Bucket 活跃状态

```bash
# 持续监控 group 状态
watch -n 1 'ovs-ofctl dump-groups br-wan1 group_id=2000'

# 输出中会显示活跃的 bucket（通常是第一个）
```

**正常状态**：
```
bucket=watch_port:1, actions=output:1 (LIVE ✓)
bucket=watch_port:2, actions=output:2 (STANDBY)
→ 流量转发到 wan1
```

**故障状态**：
```
bucket=watch_port:1, actions=output:1 (DOWN ✗)
bucket=watch_port:2, actions=output:2 (LIVE ✓)
→ 流量自动转发到 wan2
```

#### 步骤 3：故障转移验证

```bash
# 模拟 wan1 故障
ip link set wan1 down

# 观察 group 状态变化
watch -n 1 'ovs-ofctl dump-groups br-wan1 group_id=2000'

# 预期：bucket 2 变为活跃
```

#### 步骤 4：恢复验证

```bash
# 恢复 wan1
ip link set wan1 up

# 观察 group 自动恢复
watch -n 1 'ovs-ofctl dump-groups br-wan1 group_id=2000'

# 预期：bucket 1 恢复活跃
```

---

## 监控脚本（Group 场景）

### 完整 Group 诊断脚本

```bash
#!/bin/bash

BRIDGE="br-wan1"
TOLERANCE=0.1  # 10% 容差

echo "=== OVS Group 综合诊断 ==="
echo ""

# 步骤 1：检查是否使用 Group
echo "[1] 检查流表是否使用 Group..."
GROUP_FLOWS=$(ovs-ofctl dump-flows $BRIDGE | grep -c "group:")

if [ $GROUP_FLOWS -eq 0 ]; then
  echo "✓ 无 Group 使用，转发通过流表直接控制"
  echo ""
  echo "T50 规则："
  ovs-ofctl dump-flows $BRIDGE table=50 | grep "reg11"
  exit 0
fi

echo "✓ 检测到 $GROUP_FLOWS 条流表使用 Group"
echo ""

# 步骤 2：提取 group ID
echo "[2] 提取 Group ID..."
GROUP_IDS=$(ovs-ofctl dump-flows $BRIDGE | grep -o "group:[0-9]*" | cut -d: -f2 | sort -u)

for GID in $GROUP_IDS; do
  echo ""
  echo "=== Group $GID ==="
  
  # 获取 group 信息
  GROUP_INFO=$(ovs-ofctl dump-groups $BRIDGE group_id=$GID)
  GROUP_TYPE=$(echo "$GROUP_INFO" | grep -o "type=[a-z]*" | cut -d= -f2)
  
  echo "Group 类型：$GROUP_TYPE"
  
  case $GROUP_TYPE in
    select)
      echo "模式：负载均衡"
      
      # 提取 bucket 计数器
      BUCKET_COUNT=$(echo "$GROUP_INFO" | grep -c "bucket=")
      echo "Bucket 数量：$BUCKET_COUNT"
      
      # 计算分布
      TOTAL=0
      declare -a BUCKETS
      
      i=0
      while IFS= read -r line; do
        if [[ $line == *"packet_count="* ]]; then
          COUNT=$(echo "$line" | grep -o "packet_count=[0-9]*" | cut -d= -f2)
          BUCKETS[$i]=$COUNT
          TOTAL=$((TOTAL + COUNT))
          ((i++))
        fi
      done < <(echo "$GROUP_INFO")
      
      # 显示分布
      echo "负载分布："
      for ((j=0; j<i; j++)); do
        PERCENT=$((BUCKETS[$j] * 100 / TOTAL))
        echo "  Bucket $j: ${BUCKETS[$j]} packets ($PERCENT%)"
      done
      
      # 检查是否均衡
      if [ $i -gt 1 ]; then
        AVG=$((TOTAL / i))
        IMBALANCE=0
        for ((j=0; j<i; j++)); do
          DIFF=$((${BUCKETS[$j]} - AVG))
          [ $DIFF -lt 0 ] && DIFF=$((-DIFF))
          if (( $(echo "$DIFF > $AVG * $TOLERANCE" | bc -l) )); then
            IMBALANCE=1
          fi
        done
        
        if [ $IMBALANCE -eq 1 ]; then
          echo "  ⚠️ 负载分布不均"
        else
          echo "  ✓ 负载分布均衡"
        fi
      fi
      ;;
      
    ff)
      echo "模式：快速转移"
      
      # 检查活跃 bucket
      ACTIVE=$(echo "$GROUP_INFO" | grep "bucket=" | head -1 | grep -o "watch_port:[0-9]*" | cut -d: -f2)
      echo "活跃 Bucket 监控端口：$ACTIVE"
      
      # 检查端口状态
      PORT_STATE=$(ovs-vsctl get-interface $ACTIVE admin-state 2>/dev/null || echo "unknown")
      echo "端口状态：$PORT_STATE"
      
      if [ "$PORT_STATE" = "up" ]; then
        echo "✓ 主链路活跃"
      else
        echo "⚠️ 主链路故障，应切换到备 Bucket"
      fi
      ;;
      
    all)
      echo "模式：多播"
      BUCKET_COUNT=$(echo "$GROUP_INFO" | grep -c "bucket=")
      echo "复制到 $BUCKET_COUNT 个 Bucket"
      ;;
      
    indirect)
      echo "模式：间接引用"
      INDIRECT_ID=$(echo "$GROUP_INFO" | grep -o "group:[0-9]*" | cut -d: -f2)
      echo "间接指向 Group：$INDIRECT_ID"
      ;;
  esac
done

echo ""
echo "✓ Group 诊断完成"
```

### 快速检查命令

```bash
# 1. 检查是否使用 Group
ovs-ofctl dump-flows br-wan1 | grep "group:"

# 2. 列出所有 Group
ovs-ofctl dump-groups br-wan1

# 3. 查看特定 Group 的 Bucket 分布
ovs-ofctl dump-groups br-wan1 group_id=1000

# 4. 实时监控 Group 流量
watch -n 1 'ovs-ofctl dump-groups br-wan1'

# 5. 比较两个物理端口的输出
paste <(ovs-vsctl get-port-stats br-wan1 | grep "^wan[1-2].*tx_packets") \
      <(ovs-vsctl get-port-stats br-wan1 | grep "^wan[1-2].*tx_bytes")
```

---

## 故障排查（Group 相关）

### 问题 1：流量不均衡（负载均衡 Group）

**症状**：
```
Bucket 1: 9000 packets (90%)
Bucket 2: 1000 packets (10%)
```

**原因分析**：
1. 哈希算法倾斜 ✗
2. 某个 Bucket 处理能力低 ✗
3. Group 配置不对称 ✓

**诊断**：
```bash
# 检查 bucket 权重
ovs-ofctl dump-groups br-wan1 group_id=1000 | grep "weight"

# 若权重不同，则分布应该不同
# 若权重相同但分布不均，则可能是哈希问题
```

### 问题 2：故障转移不工作（ff Group）

**症状**：
```
wan1 down，但流量仍转发到 wan1（失败）
```

**原因分析**：
1. Group 类型不是 ff ✗
2. watch_port 配置错误 ✗
3. OVS 故障检测延迟 ✓

**诊断**：
```bash
# 检查 group 类型
ovs-ofctl dump-groups br-wan1 group_id=2000 | grep "type="

# 检查 watch_port
ovs-ofctl dump-groups br-wan1 group_id=2000 | grep "watch_port"

# 手动测试转移
ip link set wan1 down
sleep 2
ovs-ofctl dump-groups br-wan1 group_id=2000
# 应该看到 bucket 切换
```

### 问题 3：Group 计数器不增长

**症状**：
```
packet_count: 0 (不增长)
```

**原因分析**：
1. 没有流量通过该 Group ✓
2. 流表规则不匹配 ✗
3. Group 在另一个表中 ✗

**诊断**：
```bash
# 检查引用该 group 的流表是否被匹配
ovs-ofctl dump-flows br-wan1 | grep "group:<id>" -B1

# 检查前置表是否有 n_packets > 0
TABLE_NUM=$(echo "规则所在表")
ovs-ofctl dump-flows br-wan1 table=$TABLE_NUM | grep "n_packets"
```

---

## 集成监控检查清单

### 基础检查（所有场景）

- [ ] `ovs-ofctl dump-flows` 中是否包含 `group:` 动作？
- [ ] `ovs-ofctl dump-groups` 是否返回 Group 定义？
- [ ] Group 计数器是否 > 0？

### 负载均衡检查（type=select）

- [ ] Bucket 数量是否正确？
- [ ] 每个 Bucket 的 packet_count 是否相近（容差范围内）？
- [ ] 权重配置是否与观察分布一致？
- [ ] 物理端口流量是否分散？

### 快速转移检查（type=ff）

- [ ] watch_port 配置正确？
- [ ] 主端口故障时，Bucket 是否切换？
- [ ] 主端口恢复时，Bucket 是否自动切回？
- [ ] 故障转移时间是否可接受？

### 多播检查（type=all）

- [ ] 所有 Bucket 的 packet_count 是否相同？
- [ ] 复制是否发生在所有目标端口？

---

## 最终结论

### 当前客户端 192.168.2.56 → 8.8.8.8

| 组件 | 是否使用 Group | 转发类型 |
|------|--------|---------|
| **br-int** | ✓ 否 | VLAN MAC 学习 |
| **br-wan1** | ✓ 否 | 直接流表输出（output:1） |
| **最终转发** | ✓ 否 | 单端口 DPDK（wan1） |

### 关键发现

1. **当前客户端转发不涉及 Group**
2. **转发通过流表规则直接控制**
3. **确定性高，无间接决策**

### 如果需要引入 Group

考虑以下场景：

1. **多 WAN 口场景**：使用 select Group 实现负载均衡
2. **主备保护**：使用 ff Group 实现快速转移
3. **多播应用**：使用 all Group 实现流量复制

---

**文档生成**：2026-05-26  
**技能版本**：V2.1（含 Group 分析）  
**补充工具**：建议 get_ovs_groups（待实现）  
**当前状态**：✓ 无 Group 使用，直接流表转发
