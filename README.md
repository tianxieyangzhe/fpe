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

{"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "fpe.analyze_flow", "arguments": {"packet": {"src_ip": "10.0.0.2", "dst_ip": "8.8.8.8"}}}}
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
      "name": "fpe.analyze_flow",
      "arguments": {
        "packet": {"src_ip": "10.0.0.2", "dst_ip": "8.8.8.8"}
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
| `fpe.analyze_flow` | 完整链路分析 |
| `fpe.get_interface_context` | 接口信息 |
| `fpe.get_ip_rules` | IP 策略路由规则 |
| `fpe.get_route` | 路由表 |
| `fpe.resolve_next_hop` | 下一跳解析 |
| `fpe.get_ovs_info` | OVS 信息 |
| `fpe.check_neighbor` | 邻居表 |

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
