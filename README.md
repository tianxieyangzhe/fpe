# FPE — Flow Path Explorer

  基于厂商模型 API 的网络链路分析 AI 应用。

## 概述

FPE 对网络报文进行逐跳路径分析，采集 interface / rule / route / link / neighbor / OVS 信息，构建结构化路径骨架，为 AI 解释和诊断提供基座。

### 能力边界（首版）

- **输入建模**: 报文上下文（源/目的 IP、协议、端口、入口接口）
- **运行上下文**: namespace / VRF 切换
- **信息采集**: interface / ip rule / ip route / ip link / neighbor / OVS
- **链路骨架**: 多跳路径追踪 + 循环/截断检测
- **结构化输出**: PathNode / DecisionChain / RiskItem

## 快速开始

### 环境要求

- `python3.12`（必须）

### 安装

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

### CLI

```bash
fpe analyze --src-ip 10.0.0.2 --dst-ip 8.8.8.8 --ingress-if eth0
```

参数：

| 参数 | 必填 | 说明 |
|------|------|------|
| `--src-ip` | 是 | 源 IP 地址 |
| `--dst-ip` | 是 | 目的 IP 地址 |
| `--protocol` | 否 | 协议 (icmp/tcp/udp) |
| `--ingress-if` | 否 | 入接口名 |
| `--namespace` | 否 | 分析命名空间 |
| `--vrf` | 否 | VRF 名称 |
| `--host` | 否 | 目标主机（SSH，默认本地执行）|
| `--max-hops` | 否 | 最大跳数（默认 16）|
| `--output` | 否 | 输出格式: text / json |

### HTTP API

```bash
uvicorn fpe.api.app:app --reload
```

```http
POST /api/v1/analyze
{
  "packet": {
    "src_ip": "10.0.0.2",
    "dst_ip": "8.8.8.8",
    "protocol": "icmp",
    "ingress_if": "eth0"
  },
  "exec_ctx": {
    "namespace": "ns_app"
  },
  "options": {
    "max_hops": 16
  }
}
```

```http
GET /api/v1/healthz
→ {"ok": true}
```

### MCP Server

MCP Server 支持两种传输模式：`stdio` 和 `SSE`。

#### stdio 模式（默认）

```bash
python -m fpe.mcp.server
# 等价于
python -m fpe.mcp.server --mode stdio
```

通过 stdin/stdout 以标准 MCP JSON-RPC 2.0 协议通信：

```json
{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
→ {"jsonrpc": "2.0", "id": 1, "result": {"tools": [...]}}

{"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "fpe_analyze_flow", "arguments": {"packet": {"src_ip": "10.0.0.2", "dst_ip": "8.8.8.8", "ingress_if": "lan1"}}}}
→ {"jsonrpc": "2.0", "id": 2, "result": {"content": [{"type": "text", "text": "..."}]}}
```

#### SSE 模式（标准 MCP 协议）

```bash
python -m fpe.mcp.server --mode sse --port 8000
```

启动后提供两种消息模式：

| 模式 | 端点 | 说明 |
|------|------|------|
| SSE 建连 | `GET /sse` | 建立 SSE 事件流（标准协议） |
| **标准模式** | `POST /message?session_id=xxx` | 接收 JSON-RPC 2.0，响应通过 SSE 推送 |
| **简化模式** | `POST /message` | 无需 session_id，同步返回 HTTP 响应 |

### 标准模式（需先建 SSE 连）

```bash
# 1. 打开 SSE 流 — 收到 endpoint 事件后得到 message URL
curl -N http://localhost:8000/sse
# → event: endpoint
#   data: /message?session_id=<uuid>

# 2. 在另一终端发送 JSON-RPC 请求
curl -X POST http://localhost:8000/message?session_id=<uuid> \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "fpe_analyze_flow",
      "arguments": {
        "packet": {"src_ip": "10.0.0.2", "dst_ip": "8.8.8.8", "ingress_if": "lan1"}
      }
    }
  }'
# → 结果通过步骤 1 的 SSE 流推送
```

### 简化模式（无需 SSE 连，同步返回）

```bash
curl -X POST http://localhost:8000/message \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list"
  }'
# → 同步响应: {"jsonrpc":"2.0","id":1,"result":{"tools":[...]}}
```

兼容任何遵循 MCP 协议的客户端（如 Claude Desktop、MCP Inspector 等）。

#### 支持的工具

| 工具 | 说明 |
|------|------|
| `fpe_analyze_flow` | OVS 优先的完整链路分析，输出结构化路径、风险和 Mermaid 图 |
| `fpe_get_interface_context` | 接口信息 |
| `fpe_get_rule` | IP 策略路由规则，可按报文筛选匹配规则 |
| `fpe_get_route` | 路由表 |
| `fpe_get_neighbor` | 邻居表 |
| `fpe_get_ovs_bridges` | OVS 网桥/端口信息，可附带每桥 flows |
| `fpe_get_ovs_flows` | OVS flows 信息，可按 ingress/报文筛选候选 flow |

#### 工具使用说明

##### `fpe_analyze_flow`

目的：

1. 作为主分析入口，回答“这条流量为什么这样走”。
2. 优先按 OVS `bridge -> port -> flow -> action` 推断路径。
3. 当 OVS 将流量送入内核时，再继续做 `rule -> route -> neighbor` 分析。
4. 直接产出结构化图和 Mermaid 链路图。

关键参数：

1. `packet.src_ip`：源 IP，必填。
2. `packet.dst_ip`：目的 IP，必填。
3. `packet.ingress_if`：入口接口，OVS-first 分析必填。
4. `packet.protocol` / `src_port` / `dst_port`：提高 flow 和规则命中精度。
5. `packet.vlan_id`：入口 VLAN，适合桥内转发场景。
6. `packet.tunnel_id`：VNI / tunnel id，适合 overlay 场景。
7. `packet.fwmark`：策略路由辅助字段。
8. `exec_ctx.namespace` / `exec_ctx.vrf`：指定分析所在网络空间。
9. `options.max_hops`：控制分析深度。

输出重点：

1. `path`：人类可读路径。
2. `decision_chain`：关键判断过程。
3. `risks`：高价值风险点。
4. `graph`：前端可直接消费的图结构。
5. `mermaid`：可直接渲染的链路图文本。

##### `fpe_get_interface_context`

目的：

1. 查询接口属性、角色和所属 namespace / VRF。
2. 为拓扑确认和画图提供基础节点。

关键参数：

1. `iface`：接口名；省略时返回全部接口。
2. `namespace` / `vrf`：限定作用域。
3. `if_type`：按 `physical`、`veth`、`bridge`、`vrf`、`tun` 等过滤。
4. `role`：按 `underlay-uplink`、`bridge-port`、`vrf-member` 等过滤。
5. `state`：按 `UP` / `DOWN` 过滤。

##### `fpe_get_rule`

目的：

1. 查询策略路由规则。
2. 判断某条报文命中哪些规则，以及首条生效规则是什么。

关键参数：

1. `namespace` / `vrf`：限定规则所在作用域。
2. `priority`：只看某个优先级。
3. `table`：只看某个路由表对应的规则。
4. `packet`：传入报文后，返回 `matched_rules` 与 `selected_rule`。

##### `fpe_get_route`

目的：

1. 查询路由表。
2. 对指定目标地址返回最优匹配路由。
3. 过滤某个出接口相关的路由。

关键参数：

1. `namespace` / `vrf`：限定作用域。
2. `table`：指定路由表。
3. `dst_ip`：计算最优路由。
4. `device`：只看通过某个设备转发的路由。
5. `best_only`：只返回最优路由。

##### `fpe_get_neighbor`

目的：

1. 查询 ARP/NDP 邻居。
2. 验证下一跳是否存在以及是否可达。

关键参数：

1. `namespace` / `vrf`：限定作用域。
2. `device`：只看某个设备。
3. `target_ip`：只看某个邻居 IP。
4. `state`：按 `REACHABLE`、`FAILED` 等过滤。
5. `reachable_only`：只返回可达邻居。

##### `fpe_get_ovs_bridges`

目的：

1. 查询 OVS bridge、port、ofport、VLAN、trunk 信息。
2. 确认某个接口属于哪个桥。
3. 为链路图生成 bridge/port 拓扑。

关键参数：

1. `bridge`：只看单个桥。
2. `port`：只返回包含该端口的桥。
3. `interface`：只返回包含该接口的桥。
4. `include_flows`：一并附带每个桥上的 flows。

##### `fpe_get_ovs_flows`

目的：

1. 查询 OVS flow 表项。
2. 按入口接口缩小到相关桥。
3. 按报文字段筛选候选命中 flow。

关键参数：

1. `bridge`：指定桥。
2. `table`：指定 table。
3. `ingress_if`：自动定位所在桥和入口 port。
4. `packet`：按报文计算 `matched_flows`。
5. `match_contains`：按原始 match 文本做子串过滤。
6. `active_only`：只返回命中计数大于 0 的 flow。

## 项目结构

```
src/fpe/
  settings.py   环境配置（保留在顶层）
  models/       数据模型（Pydantic）
  collectors/   系统信息采集（interface/rule/route/link/OVS/neighbor）
  command/      公共命令执行（RemoteExecutor）
  analyzer/     分析编排（状态机）
  renderer/     输出渲染（text / JSON）
  mcp/          MCP Server 入口 + 工具注册
  api/          FastAPI 入口
  cli/          Typer CLI 入口
```

## 设计

- **设计模式**: Facade / Strategy / State
- **分层**: App → Analyzer → Collectors → RemoteExecutor
- **状态机**: INIT → NORMALIZING_INPUT → RESOLVING_CONTEXT → COLLECTING → BUILDING_PATH → COMPLETED / INCOMPLETE / FAILED

详细设计文档见 [docs/](docs/)。

## 测试

```bash
.venv/bin/python -m pytest tests/ -v
```

## 环境变量

通过 `.env` 文件或环境变量配置，全部以 `FPE_` 为前缀：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `FPE_MODEL_BASE_URL` | `https://api.example.com/v1` | 模型 API 地址 |
| `FPE_MODEL_API_KEY` | `""` | API Key |
| `FPE_MODEL_NAME` | `claude-sonnet-4-6` | 模型名 |
| `FPE_MODEL_TIMEOUT` | `30` | API 超时秒数 |
| `FPE_ENABLE_OVS` | `true` | 是否采集 OVS |
| `FPE_DEFAULT_MAX_HOPS` | `16` | 默认最大跳数 |
