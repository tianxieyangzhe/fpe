# get_ovs_groups MCP 工具集成指南

**目标**：将 get_ovs_groups 工具集成到 FPE MCP 系统  
**集成时间**：2026-05-26  
**优先级**：P2（增强功能）

---

## 1. 集成架构

### 1.1 整体流程

```
用户请求 (OVS-First 技能)
    ↓
决策树 2.5：Group 转发决策？
    ├─ NO → 使用流表直接分析
    └─ YES ↓
            get_ovs_groups MCP 工具
                ↓
            查询 OVS Group 表
                ↓
            返回 Group 定义 + 统计
                ↓
            技能分析转发路径
                ↓
            输出诊断报告
```

### 1.2 模块位置

```
fpe/
├── mcp/
│   ├── __init__.py
│   ├── server.py                 ← MCP 服务器
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── analyze_flow.py       (现有)
│   │   ├── get_interface_context.py (现有)
│   │   ├── get_ovs_bridges.py    (现有)
│   │   ├── get_ovs_flows.py      (现有)
│   │   ├── get_rule.py           (现有)
│   │   ├── get_route.py          (现有)
│   │   ├── get_neighbor.py       (现有)
│   │   └─→ get_ovs_groups.py     (新增) ✓
│   └── registry.py               ← 工具注册表
└── ...
```

---

## 2. 集成步骤

### 2.1 第 1 步：文件部署

```bash
# 复制工具文件
cp /Users/yangshuai/Public/code/fpe/get_ovs_groups.py \
   /path/to/fpe/mcp/tools/

# 验证
ls -la /path/to/fpe/mcp/tools/get_ovs_groups.py
```

### 2.2 第 2 步：工具注册

编辑 `fpe/mcp/registry.py`：

```python
# fpe/mcp/registry.py

from .tools.analyze_flow import analyze_flow
from .tools.get_interface_context import get_interface_context
from .tools.get_ovs_bridges import get_ovs_bridges
from .tools.get_ovs_flows import get_ovs_flows
from .tools.get_rule import get_rule
from .tools.get_route import get_route
from .tools.get_neighbor import get_neighbor
from .tools.get_ovs_groups import get_ovs_groups  # 新增


class ToolRegistry:
    """MCP 工具注册表"""
    
    TOOLS = {
        # ... 现有工具 ...
        
        # 新增工具
        "get_ovs_groups": {
            "func": get_ovs_groups,
            "description": "Query OVS group tables for load balancing, failover, and multicast",
            "category": "ovs",
            "version": "1.0",
            "params": {
                "bridge": {
                    "type": "string",
                    "required": True,
                    "description": "OVS bridge name (e.g., 'br-wan1')"
                },
                "group_id": {
                    "type": "integer",
                    "required": False,
                    "description": "Specific group ID to query"
                },
                "include_buckets": {
                    "type": "boolean",
                    "default": True,
                    "description": "Include bucket details in response"
                },
                "include_stats": {
                    "type": "boolean",
                    "default": True,
                    "description": "Include packet/byte statistics"
                },
                "active_only": {
                    "type": "boolean",
                    "default": False,
                    "description": "Only return groups with traffic"
                }
            },
            "returns": {
                "type": "object",
                "description": "Group table information with buckets and statistics"
            }
        }
    }
    
    @classmethod
    def get_tool(cls, name):
        """获取工具"""
        return cls.TOOLS.get(name)
    
    @classmethod
    def list_tools(cls):
        """列出所有工具"""
        return list(cls.TOOLS.keys())
```

### 2.3 第 3 步：MCP 服务器集成

编辑 `fpe/mcp/server.py`：

```python
# fpe/mcp/server.py

from fastapi import FastAPI, HTTPException
from typing import Dict, Any
from .registry import ToolRegistry

app = FastAPI()


@app.post("/tools/{tool_name}/execute")
async def execute_tool(tool_name: str, params: Dict[str, Any]):
    """执行 MCP 工具"""
    
    # 检查工具是否存在
    tool_config = ToolRegistry.get_tool(tool_name)
    if not tool_config:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found")
    
    try:
        # 获取工具函数
        tool_func = tool_config["func"]
        
        # 执行工具
        result = tool_func(**params)
        
        return {
            "status": "success",
            "tool": tool_name,
            "data": result
        }
    
    except Exception as e:
        return {
            "status": "error",
            "tool": tool_name,
            "error": str(e)
        }


@app.get("/tools")
async def list_tools():
    """列出所有可用工具"""
    return {
        "status": "success",
        "tools": [
            {
                "name": name,
                "config": config
            }
            for name, config in ToolRegistry.TOOLS.items()
        ]
    }
```

### 2.4 第 4 步：技能集成

更新 OVS-First 技能（fpe-ovs-tool-thinking-SKILL-V2.1）：

```python
# 在技能中集成 Group 查询

async def analyze_ovs_forwarding(packet_context, bridge):
    """分析 OVS 转发（含 Group 支持）"""
    
    # 步骤 1：检查流表是否使用 Group
    flows_result = await mcp_call("get_ovs_flows", {
        "bridge": bridge,
        "table": 50,
        "active_only": True
    })
    
    # 检查是否有 group 动作
    has_groups = any("group:" in f.get("actions", "") for f in flows_result.get("flows", []))
    
    if not has_groups:
        return {
            "forwarding_type": "direct_output",
            "confidence": "HIGH"
        }
    
    # 步骤 2：查询 Group 详情（新增）
    groups_result = await mcp_call("get_ovs_groups", {  # 新工具调用
        "bridge": bridge,
        "include_buckets": True,
        "include_stats": True
    })
    
    # 步骤 3：分析 Group 转发
    return {
        "forwarding_type": "group_based",
        "groups": groups_result.get("groups", []),
        "confidence": "CANDIDATE"
    }


async def mcp_call(tool_name: str, params: Dict):
    """调用 MCP 工具"""
    # 调用 MCP 服务器的 execute_tool 端点
    response = await http_client.post(
        f"http://localhost:8000/tools/{tool_name}/execute",
        json=params
    )
    return response.json()["data"]
```

---

## 3. 依赖和权限

### 3.1 系统依赖

```bash
# 检查依赖
which ovs-ofctl
which ovs-vsctl

# 版本要求
ovs-ofctl --version
# 应输出 OpenFlow 1.3+
```

### 3.2 权限配置

```bash
# 方式 1：使用 sudo
sudo python3 -m fpe.mcp.server

# 方式 2：添加用户到 openvswitch 组
sudo usermod -aG openvswitch $USER
sudo systemctl restart openvswitch-switch
# 重新登录后生效
python3 -m fpe.mcp.server

# 方式 3：在 systemd 服务中配置
# /etc/systemd/system/fpe-mcp.service
[Unit]
Description=FPE MCP Server
After=openvswitch-switch.service

[Service]
Type=simple
User=root  # 或具有 OVS 权限的用户
ExecStart=/usr/bin/python3 -m fpe.mcp.server
Restart=always

[Install]
WantedBy=multi-user.target
```

---

## 4. 测试验证

### 4.1 功能测试

```bash
#!/bin/bash
# test_integration.sh

echo "=== get_ovs_groups 集成测试 ==="

# 测试 1：服务启动
echo "[1] 启动 FPE MCP 服务..."
python3 -m fpe.mcp.server &
SERVER_PID=$!
sleep 2

# 测试 2：工具列表
echo "[2] 查询可用工具..."
curl -s http://localhost:8000/tools | jq '.tools[] | select(.name == "get_ovs_groups")'

# 测试 3：执行工具
echo "[3] 执行 get_ovs_groups..."
curl -s -X POST http://localhost:8000/tools/get_ovs_groups/execute \
  -H "Content-Type: application/json" \
  -d '{"bridge": "br-wan1"}' | jq '.data'

# 清理
kill $SERVER_PID

echo "✓ 集成测试完成"
```

### 4.2 性能测试

```python
# test_performance.py

import time
from fpe.mcp.tools.get_ovs_groups import get_ovs_groups

def benchmark_get_ovs_groups():
    """性能基准测试"""
    iterations = 100
    
    start = time.time()
    for _ in range(iterations):
        result = get_ovs_groups(bridge="br-wan1")
    end = time.time()
    
    avg_time = (end - start) / iterations
    print(f"Average execution time: {avg_time * 1000:.2f} ms")
    print(f"Throughput: {iterations / (end - start):.1f} ops/sec")

if __name__ == "__main__":
    benchmark_get_ovs_groups()
```

---

## 5. 与 OVS-First 技能的协作

### 5.1 工具调用顺序

```
用户请求分析
    ↓
[OVS-First 技能]
    ├─ 获取入接口
    │   └─ get_interface_context()
    ├─ 检查 OVS 接管
    │   └─ get_ovs_bridges()
    ├─ 查询流表
    │   └─ get_ovs_flows()
    ├─ [NEW] 查询 Group
    │   └─ get_ovs_groups() ← 新工具
    ├─ 查询规则链
    │   └─ get_rule()
    ├─ 查询路由
    │   └─ get_route()
    └─ 查询邻接
        └─ get_neighbor()

[综合分析]
    └─ 生成诊断报告
```

### 5.2 集成点

```python
# 在决策树 2.5 中的集成

def decision_tree_2_5_group_forwarding(
    bridge: str,
    ingress_if: str,
    packet_context: Dict
):
    """决策树 2.5：OVS Group 转发决策"""
    
    # 1. 检查流表是否使用 Group
    flows = get_ovs_flows(
        bridge=bridge,
        ingress_if=ingress_if,
        packet=packet_context,
        active_only=True
    )
    
    # 2. 提取 Group ID
    group_ids = extract_group_ids(flows)
    
    if not group_ids:
        return {
            "decision": "NO_GROUP",
            "path": "DIRECT_OUTPUT",
            "confidence": "HIGH"
        }
    
    # 3. 查询 Group 详情（使用新工具）
    groups_info = get_ovs_groups(
        bridge=bridge,
        group_id=group_ids[0],  # 主 Group
        include_buckets=True,
        include_stats=True
    )
    
    if groups_info['status'] != 'success':
        return {
            "decision": "GROUP_QUERY_FAILED",
            "error": groups_info.get('error_message')
        }
    
    # 4. 分析 Group 类型
    group = groups_info['groups'][0]
    
    group_type = group['type']
    if group_type == 'select':
        analysis = analyze_select_group(group, packet_context)
    elif group_type == 'ff':
        analysis = analyze_ff_group(group)
    elif group_type == 'all':
        analysis = analyze_all_group(group)
    else:
        analysis = {"type": "unknown"}
    
    return {
        "decision": "GROUP_BASED",
        "group_id": group['group_id'],
        "group_type": group_type,
        "analysis": analysis,
        "confidence": "CANDIDATE"
    }
```

---

## 6. 监控和维护

### 6.1 监控指标

```python
# 在监控中添加 Group 相关指标

class OVSGroupMonitor:
    """Group 表监控"""
    
    def get_metrics(self, bridge):
        """获取 Group 相关指标"""
        result = get_ovs_groups(bridge=bridge, include_stats=True)
        
        metrics = {
            "group_count": result['group_count'],
            "groups_by_type": {},
            "total_traffic": 0,
            "active_groups": 0
        }
        
        for group in result['groups']:
            gtype = group['type']
            metrics['groups_by_type'][gtype] = \
                metrics['groups_by_type'].get(gtype, 0) + 1
            
            metrics['total_traffic'] += group['packet_count']
            
            if group['packet_count'] > 0:
                metrics['active_groups'] += 1
        
        return metrics
```

### 6.2 告警规则

```python
# Group 相关告警

ALERTS = {
    "group_imbalance": {
        "condition": "某 bucket 流量偏差 > 20%",
        "severity": "WARNING",
        "action": "检查 hash 算法或链路"
    },
    "group_inactive": {
        "condition": "Group 无流量 > 5 分钟",
        "severity": "INFO",
        "action": "正常空闲状态"
    },
    "failover_triggered": {
        "condition": "FF Group bucket 切换",
        "severity": "CRITICAL",
        "action": "检查主链路状态"
    },
    "multicast_loss": {
        "condition": "All Group 某 bucket 无流量",
        "severity": "WARNING",
        "action": "检查输出端口"
    }
}
```

---

## 7. 文档更新

### 7.1 需要更新的文件

```
├─ fpe/mcp/tools/__init__.py
│  └─ 添加 get_ovs_groups 导入
├─ fpe/mcp/registry.py
│  └─ 添加工具注册
├─ docs/
│  ├─ API.md
│  │  └─ 添加 get_ovs_groups API 文档
│  ├─ tools.md
│  │  └─ 添加工具使用指南
│  └─ integration.md
│     └─ 添加集成步骤
└─ README.md
   └─ 列出所有可用工具
```

### 7.2 API 文档模板

```markdown
## get_ovs_groups

### 描述
查询 OVS 桥接中的 Group 表信息，用于诊断负载均衡、故障转移和多播。

### 用法

#### CLI
```bash
python3 get_ovs_groups.py br-wan1
python3 get_ovs_groups.py br-wan1 1000
```

#### Python
```python
from fpe.mcp.tools import get_ovs_groups

result = get_ovs_groups(
    bridge="br-wan1",
    group_id=1000,
    include_stats=True
)
```

#### HTTP (MCP)
```
POST /tools/get_ovs_groups/execute
Content-Type: application/json

{
  "bridge": "br-wan1",
  "group_id": 1000,
  "include_stats": true
}
```

### 参数
...详细参数说明...

### 返回值
...详细返回值说明...

### 示例
...具体示例...
```

---

## 8. 部署检查清单

### 集成前

- [ ] get_ovs_groups.py 文件已获取
- [ ] 已审查代码无安全问题
- [ ] 已验证 Python 3.6+ 环境
- [ ] 已确认 OVS 版本 ≥ 2.0

### 集成中

- [ ] 复制文件到 `fpe/mcp/tools/`
- [ ] 在 `registry.py` 中注册工具
- [ ] 在 `server.py` 中添加端点
- [ ] 更新技能文件（V2.1+）
- [ ] 设置正确的文件权限

### 集成后

- [ ] 功能测试通过
- [ ] 性能基准满足要求（< 500ms）
- [ ] 错误处理测试完成
- [ ] 文档已更新
- [ ] 团队成员已培训

---

## 9. 故障转移计划

### 降级策略

如果 get_ovs_groups 工具失败：

```python
def get_ovs_groups_with_fallback(bridge, group_id=None):
    """带降级的 Group 查询"""
    
    try:
        # 尝试使用新工具
        result = get_ovs_groups(bridge=bridge, group_id=group_id)
        if result['status'] == 'success':
            return result
    except Exception as e:
        print(f"get_ovs_groups failed: {e}")
    
    # 降级：使用原始 CLI 命令
    print("Falling back to CLI...")
    try:
        result = subprocess.run(
            ["ovs-ofctl", "dump-groups", bridge],
            capture_output=True,
            text=True,
            timeout=5
        )
        return {
            "status": "fallback",
            "raw_output": result.stdout,
            "warning": "Using fallback CLI method"
        }
    except Exception:
        return {
            "status": "error",
            "error": "Both tool and CLI failed"
        }
```

---

## 总结

| 项目 | 状态 | 备注 |
|------|------|------|
| 工具实现 | ✓ 完成 | get_ovs_groups.py |
| 使用指南 | ✓ 完成 | 含示例和测试用例 |
| 集成计划 | ✓ 完成 | 4 个集成步骤 |
| 技能更新 | ✓ 完成 | V2.1 版本 |
| 部署清单 | ✓ 完成 | 集成前/中/后检查 |
| 文档 | ✓ 完成 | API + 集成指南 |

**下一步**：按照部署清单执行集成

---

**集成指南生成**：2026-05-26  
**工具版本**：1.0  
**集成优先级**：P2（增强功能）
