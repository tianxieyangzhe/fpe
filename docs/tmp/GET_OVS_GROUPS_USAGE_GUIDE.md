# get_ovs_groups 工具使用指南

**工具文件**：get_ovs_groups.py  
**版本**：1.0  
**依赖**：Python 3.6+, ovs-vsctl, ovs-ofctl

---

## 1. 安装和配置

### 1.1 安装依赖

```bash
# 确保已安装 OVS 工具
apt-get install openvswitch-switch

# 验证安装
ovs-ofctl --version
ovs-vsctl --version
```

### 1.2 部署工具

```bash
# 将工具复制到 FPE MCP 目录
cp get_ovs_groups.py /path/to/fpe/mcp/tools/

# 设置执行权限
chmod +x /path/to/fpe/mcp/tools/get_ovs_groups.py
```

### 1.3 集成到 MCP 服务

在 FPE MCP 配置文件中注册工具：

```python
# fpe_mcp_server.py

from get_ovs_groups import get_ovs_groups

# 注册工具
mcp_tools.register(
    name="get_ovs_groups",
    func=get_ovs_groups,
    description="Query OVS group tables for load balancing and failover",
    params={
        "bridge": {"type": "string", "required": True, "description": "OVS bridge name"},
        "group_id": {"type": "integer", "required": False, "description": "Specific group ID"},
        "include_buckets": {"type": "boolean", "default": True},
        "include_stats": {"type": "boolean", "default": True},
        "active_only": {"type": "boolean", "default": False}
    }
)
```

---

## 2. 使用示例

### 2.1 命令行使用

#### 查询所有 Group

```bash
python3 get_ovs_groups.py br-wan1
```

**输出**：
```json
{
  "status": "success",
  "bridge": "br-wan1",
  "group_count": 2,
  "groups": [
    {
      "group_id": 1000,
      "type": "select",
      "n_buckets": 2,
      "packet_count": 10000,
      "byte_count": 10000000,
      "buckets": [
        {
          "bucket_id": 0,
          "weight": 50,
          "actions": "output:1",
          "packet_count": 5000,
          "byte_count": 5000000,
          "watch_port": null,
          "watch_group": null
        },
        {
          "bucket_id": 1,
          "weight": 50,
          "actions": "output:2",
          "packet_count": 5000,
          "byte_count": 5000000,
          "watch_port": null,
          "watch_group": null
        }
      ]
    }
  ]
}
```

#### 查询特定 Group

```bash
python3 get_ovs_groups.py br-wan1 1000
```

### 2.2 Python API 使用

#### 基础使用

```python
from get_ovs_groups import get_ovs_groups

# 查询所有 group
result = get_ovs_groups(bridge="br-wan1")

print(f"Found {result['group_count']} groups")
for group in result['groups']:
    print(f"  Group {group['group_id']}: type={group['type']}, buckets={group['n_buckets']}")
```

#### 高级用法

```python
from get_ovs_groups import get_ovs_groups

# 查询特定 group，包含统计信息
result = get_ovs_groups(
    bridge="br-wan1",
    group_id=1000,
    include_buckets=True,
    include_stats=True
)

if result['status'] == 'success':
    group = result['groups'][0]
    print(f"Group {group['group_id']} ({group['type']}):")
    print(f"  Total packets: {group['packet_count']}")
    
    for bucket in group['buckets']:
        print(f"  Bucket {bucket['bucket_id']}: {bucket['actions']}")
        print(f"    Packets: {bucket['packet_count']}, Weight: {bucket['weight']}")
```

#### 负载均衡验证

```python
from get_ovs_groups import get_ovs_groups

def check_load_balance(bridge, group_id, tolerance=0.1):
    """检查负载是否均衡"""
    result = get_ovs_groups(
        bridge=bridge,
        group_id=group_id,
        include_stats=True
    )
    
    if result['status'] != 'success':
        return False, "Group not found"
    
    group = result['groups'][0]
    
    if group['type'] != 'select':
        return False, "Not a select group"
    
    # 计算均衡度
    total_packets = group['packet_count']
    if total_packets == 0:
        return True, "No traffic"
    
    expected_per_bucket = total_packets / group['n_buckets']
    
    for bucket in group['buckets']:
        diff = abs(bucket['packet_count'] - expected_per_bucket)
        if diff > expected_per_bucket * tolerance:
            return False, f"Bucket {bucket['bucket_id']} imbalanced: {bucket['packet_count']} packets"
    
    return True, "Load balanced"

# 使用
balanced, msg = check_load_balance("br-wan1", 1000, tolerance=0.15)
print(f"Load balance check: {msg}")
```

#### 故障转移验证

```python
from get_ovs_groups import get_ovs_groups
import time

def check_failover(bridge, group_id, primary_port, backup_port):
    """检查故障转移是否工作"""
    result = get_ovs_groups(
        bridge=bridge,
        group_id=group_id,
        include_stats=True
    )
    
    if result['status'] != 'success':
        return False, "Group not found"
    
    group = result['groups'][0]
    
    if group['type'] != 'ff':
        return False, "Not a fast failover group"
    
    # 检查活跃 bucket
    active_buckets = [b for b in group['buckets'] if b.get('active')]
    
    if len(active_buckets) != 1:
        return False, f"Expected 1 active bucket, found {len(active_buckets)}"
    
    active_bucket = active_buckets[0]
    
    # 检查是否指向主端口
    if primary_port not in active_bucket['actions']:
        return False, f"Active bucket not pointing to primary port {primary_port}"
    
    return True, f"Failover working: active bucket={active_bucket['bucket_id']}"

# 使用
ok, msg = check_failover("br-wan1", 2000, "1", "2")
print(f"Failover check: {msg}")
```

---

## 3. 与 OVS-First 技能集成

### 3.1 决策树 2.5 中的使用

```python
# 在技能实现中调用 get_ovs_groups

def analyze_group_forwarding(packet_context, bridge):
    """分析 Group 转发决策"""
    
    # 步骤 1：检查流表是否使用 group
    flows = get_ovs_flows(bridge=bridge, table=50)
    
    group_ids = extract_group_ids(flows)
    if not group_ids:
        return {
            "uses_group": False,
            "forwarding_type": "direct_output",
            "confidence": "HIGH"
        }
    
    # 步骤 2：查询 group 详情
    result = get_ovs_groups(
        bridge=bridge,
        include_buckets=True,
        include_stats=True
    )
    
    if result['status'] != 'success':
        return {
            "error": "Failed to query groups",
            "groups_attempted": group_ids
        }
    
    # 步骤 3：分析每个 group
    analysis = []
    for group in result['groups']:
        analysis.append({
            "group_id": group['group_id'],
            "type": group['type'],
            "n_buckets": group['n_buckets'],
            "forwarding_decision": analyze_group_type(group),
            "traffic_distribution": compute_distribution(group),
            "confidence": "CANDIDATE" if group['packet_count'] > 0 else "UNCONFIRMED"
        })
    
    return {
        "uses_group": True,
        "forwarding_type": "group_based",
        "groups": analysis,
        "confidence": "CANDIDATE"
    }

def analyze_group_type(group):
    """分析 Group 类型的转发行为"""
    group_type = group['type']
    
    if group_type == 'select':
        return "load_balance_hash_based"
    elif group_type == 'ff':
        return "failover_first_active"
    elif group_type == 'all':
        return "multicast_all_buckets"
    elif group_type == 'indirect':
        return "indirect_reference"
    
    return "unknown"

def compute_distribution(group):
    """计算流量分布"""
    total = group['packet_count']
    if total == 0:
        return None
    
    return [
        {
            "bucket_id": b['bucket_id'],
            "percentage": (b['packet_count'] / total) * 100,
            "packets": b['packet_count']
        }
        for b in group['buckets']
    ]
```

### 3.2 监控 Level 1.5 中的使用

```python
# 在监控指南中使用

def monitor_group_steering(bridge, group_ids=None):
    """Level 1.5: Group 转发决策监控"""
    
    result = get_ovs_groups(
        bridge=bridge,
        group_id=group_ids[0] if group_ids and len(group_ids) == 1 else None,
        include_stats=True
    )
    
    if result['status'] != 'success':
        return {"status": "error", "message": "No groups found"}
    
    monitoring_report = {
        "bridge": bridge,
        "timestamp": time.time(),
        "groups": []
    }
    
    for group in result['groups']:
        group_monitor = {
            "group_id": group['group_id'],
            "type": group['type'],
            "status": "ACTIVE" if group['packet_count'] > 0 else "IDLE",
            "total_packets": group['packet_count'],
            "buckets": []
        }
        
        if group['type'] == 'select':
            # 负载均衡监控
            total = group['packet_count']
            expected = total / group['n_buckets']
            
            for bucket in group['buckets']:
                imbalance = abs(bucket['packet_count'] - expected)
                bucket_monitor = {
                    "bucket_id": bucket['bucket_id'],
                    "packets": bucket['packet_count'],
                    "percentage": (bucket['packet_count'] / total * 100) if total > 0 else 0,
                    "imbalanced": imbalance > expected * 0.1,
                    "actions": bucket['actions']
                }
                group_monitor['buckets'].append(bucket_monitor)
        
        elif group['type'] == 'ff':
            # 快速转移监控
            for bucket in group['buckets']:
                bucket_monitor = {
                    "bucket_id": bucket['bucket_id'],
                    "packets": bucket['packet_count'],
                    "active": bucket.get('active', False),
                    "watch_port": bucket['watch_port'],
                    "actions": bucket['actions']
                }
                group_monitor['buckets'].append(bucket_monitor)
        
        monitoring_report['groups'].append(group_monitor)
    
    return monitoring_report
```

---

## 4. 测试用例

### 4.1 单元测试

```python
# test_get_ovs_groups.py

import unittest
from unittest.mock import patch, MagicMock
from get_ovs_groups import get_ovs_groups, OVSGroupQuery, Bucket, Group


class TestGetOVSGroups(unittest.TestCase):
    
    def test_invalid_bridge(self):
        """测试无效桥接"""
        result = get_ovs_groups(bridge=None)
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['error_code'], 'INVALID_PARAMS')
    
    @patch('get_ovs_groups.subprocess.run')
    def test_bridge_not_found(self, mock_run):
        """测试桥接不存在"""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="br-int\nbr-tun\n",
            text=""
        )
        
        result = get_ovs_groups(bridge="br-nonexistent")
        self.assertEqual(result['status'], 'error')
    
    @patch('get_ovs_groups.OVSGroupQuery.get_all_groups')
    @patch('get_ovs_groups.OVSGroupQuery._validate_bridge')
    def test_no_groups(self, mock_validate, mock_get_all):
        """测试无 Group 情况"""
        mock_validate.return_value = None
        mock_get_all.return_value = []
        
        result = get_ovs_groups(bridge="br-wan1")
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['group_count'], 0)
    
    def test_parse_select_group(self):
        """测试解析 select group"""
        output = """OFPST_GROUP reply (xid=0x2):
group_id=1000,type=select,buckets=[bucket=weight:50,actions=output:1,packet_count=5000,byte_count=5000000, bucket=weight:50,actions=output:2,packet_count=5000,byte_count=5000000]"""
        
        query = OVSGroupQuery.__new__(OVSGroupQuery)
        groups = query._parse_groups(output)
        
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].group_id, 1000)
        self.assertEqual(groups[0].group_type, 'select')
        self.assertEqual(groups[0].n_buckets, 2)
        self.assertEqual(groups[0].packet_count, 10000)
    
    def test_parse_ff_group(self):
        """测试解析 ff group"""
        output = """OFPST_GROUP reply (xid=0x2):
group_id=2000,type=ff,buckets=[bucket=watch_port:1,actions=output:1,packet_count=8500, bucket=watch_port:2,actions=output:2,packet_count=0]"""
        
        query = OVSGroupQuery.__new__(OVSGroupQuery)
        groups = query._parse_groups(output)
        
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].group_type, 'ff')
        self.assertEqual(groups[0].buckets[0].watch_port, 1)
        self.assertEqual(groups[0].buckets[1].watch_port, 2)


if __name__ == '__main__':
    unittest.main()
```

### 4.2 集成测试

```bash
#!/bin/bash
# test_integration.sh

echo "=== get_ovs_groups 集成测试 ==="

BRIDGE="br-wan1"

# 测试 1：查询所有 group
echo "[1] 查询所有 group..."
python3 get_ovs_groups.py $BRIDGE > /tmp/all_groups.json
if [ $? -eq 0 ]; then
  echo "✓ 成功"
  GROUP_COUNT=$(jq '.group_count' /tmp/all_groups.json)
  echo "  Found $GROUP_COUNT groups"
else
  echo "✗ 失败"
fi

# 测试 2：查询特定 group
if [ $GROUP_COUNT -gt 0 ]; then
  echo "[2] 查询特定 group..."
  GROUP_ID=$(jq '.groups[0].group_id' /tmp/all_groups.json)
  python3 get_ovs_groups.py $BRIDGE $GROUP_ID > /tmp/specific_group.json
  
  if [ $? -eq 0 ]; then
    echo "✓ 成功: Group $GROUP_ID"
    TYPE=$(jq '.groups[0].type' /tmp/specific_group.json)
    echo "  Type: $TYPE"
  else
    echo "✗ 失败"
  fi
fi

# 测试 3：负载均衡验证
echo "[3] 检查负载均衡..."
python3 -c "
from get_ovs_groups import get_ovs_groups

result = get_ovs_groups(bridge='$BRIDGE')
for group in result.get('groups', []):
    if group['type'] == 'select':
        total = group['packet_count']
        expected = total / group['n_buckets'] if group['n_buckets'] > 0 else 0
        
        print(f'Group {group[\"group_id\"]} ({group[\"type\"]}):')
        for bucket in group['buckets']:
            diff = abs(bucket['packet_count'] - expected)
            balanced = 'OK' if diff <= expected * 0.1 else 'IMBALANCED'
            print(f'  Bucket {bucket[\"bucket_id\"]}: {bucket[\"packet_count\"]} packets [{balanced}]')
"

echo "✓ 集成测试完成"
```

---

## 5. 故障排查

### 问题 1：Permission Denied

```
Error: ovs-ofctl: error while running command: Permission denied
```

**解决**：
```bash
# 使用 sudo 或以 root 用户运行
sudo python3 get_ovs_groups.py br-wan1

# 或添加当前用户到 openvswitch 组
sudo usermod -aG openvswitch $USER
```

### 问题 2：Bridge Not Found

```
Error: Bridge 'br-wan1' not found
```

**解决**：
```bash
# 验证桥接存在
ovs-vsctl list-br

# 检查拼写
# 如果没有 br-wan1，创建它
ovs-vsctl add-br br-wan1
```

### 问题 3：No Groups Output

```
group_count: 0
```

**解决**：
- 可能没有配置 Group（正常）
- 使用命令验证：`ovs-ofctl dump-groups br-wan1`

---

## 6. 性能考虑

### 执行时间

```bash
# 平均执行时间
$ time python3 get_ovs_groups.py br-wan1

real    0m0.245s
user    0m0.150s
sys     0m0.095s
```

### 缓存建议

对于高频查询，考虑缓存：

```python
from functools import lru_cache
from datetime import datetime, timedelta

class OVSGroupCache:
    def __init__(self, ttl_seconds=5):
        self.cache = {}
        self.ttl = timedelta(seconds=ttl_seconds)
    
    def get(self, bridge, group_id=None):
        key = f"{bridge}:{group_id}"
        cached = self.cache.get(key)
        
        if cached:
            timestamp, data = cached
            if datetime.now() - timestamp < self.ttl:
                return data
        
        # 缓存过期，重新查询
        data = get_ovs_groups(bridge=bridge, group_id=group_id)
        self.cache[key] = (datetime.now(), data)
        return data
```

---

## 7. 总结

| 功能 | 支持度 | 备注 |
|------|--------|------|
| 查询所有 Group | ✓ 完全 | - |
| 查询特定 Group | ✓ 完全 | - |
| select 类型 | ✓ 完全 | 负载均衡 |
| ff 类型 | ✓ 完全 | 快速转移 |
| all 类型 | ✓ 完全 | 多播 |
| indirect 类型 | ✓ 完全 | 间接引用 |
| 流量统计 | ✓ 完全 | packet_count, byte_count |
| 关联流表 | ✓ 部分 | 可选查询 |
| 错误处理 | ✓ 完全 | 详细错误消息 |

---

**文档生成**：2026-05-26  
**工具版本**：1.0  
**支持平台**：Linux OVS（OpenFlow 1.3+）
