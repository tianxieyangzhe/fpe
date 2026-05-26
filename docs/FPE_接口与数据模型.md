# FPE 接口与数据模型

## 1. MCP 设计目标

FPE 需要以 MCP Server 方式暴露核心能力，使 Agent 不直接拼命令，而是调用标准化工具。

MCP 接口设计要求：

1. 输入稳定
2. 输出稳定
3. 全部结构化
4. 执行上下文通过环境变量隐式传递，不侵入工具入参
5. 错误可归类
6. 同时支持 `stdio` 和 `SSE` 两种传输形式
7. `SSE` 模式支持通过 `POST` 建立连接

## 1.1 MCP 传输形式

FPE MCP Server 必须支持以下两种形式：

1. `stdio`
2. `SSE`

### `stdio`

适合：

1. 本地 Agent 进程拉起
2. 命令行工具集成
3. 桌面型或沙箱型运行环境

### `SSE`

适合：

1. 远程服务化部署
2. 跨进程或跨主机调用
3. 网关和平台统一接入

约束：

1. `SSE` 模式必须支持通过 `POST` 建立连接或会话
2. 建连完成后返回连接标识或进入流式事件阶段
3. 工具调用消息和结果消息保持统一结构

## 2. MCP Tool 列表

### 2.1 `fpe.analyze_flow`

功能：

1. 执行完整链路分析
2. 返回路径骨架与结构化状态

输入：

```json
{
  "packet": {
    "src_ip": "10.0.0.2",
    "dst_ip": "8.8.8.8",
    "protocol": "icmp",
    "ingress_if": "lan0",
    "ip_version": 4
  },
  "options": {
    "max_hops": 16,
    "include_ovs": true,
    "include_neighbor": true
  }
}
```

输出：

```json
{
  "ok": true,
  "tool": "fpe.analyze_flow",
  "data": {
    "status": "COMPLETED",
    "path": [],
    "decision_chain": [],
    "warnings": []
  },
  "error": null
}
```

### 2.2 `fpe.get_interface_context`

输入：

```json
{
  "iface": "lan0"
}
```

### 2.3 `fpe.get_ip_rules`

输入：

```json
{
  "packet": {
    "src_ip": "10.0.0.2",
    "dst_ip": "8.8.8.8",
    "ingress_if": "lan0",
    "protocol": "icmp",
    "ip_version": 4
  }
}
```

### 2.4 `fpe.get_route`

输入：

```json
{
  "table": "100",
  "dst_ip": "8.8.8.8"
}
```

### 2.5 `fpe.resolve_next_hop`

输入：

```json
{
  "device": "veth0",
  "next_hop_ip": "192.168.1.1"
}
```

### 2.6 `fpe.get_ovs_info`

输入：

```json
{
  "port": "patch-wan"
}
```

### 2.7 `fpe.check_neighbor`

输入：

```json
{
  "device": "wan0",
  "target_ip": "192.168.1.1"
}
```

## 3. 通用返回结构

```python
class ToolResult(BaseModel):
    ok: bool
    tool: str
    context: dict
    data: dict | None = None
    warnings: list[str] = []
    error: str | None = None
```

## 4. 结构体定义

### 4.1 PacketContext

```python
class PacketContext(BaseModel):
    src_ip: str
    dst_ip: str
    protocol: str | None = None
    src_port: int | None = None
    dst_port: int | None = None
    ingress_if: str | None = None
    egress_if: str | None = None
    fwmark: str | None = None
    tos: int | None = None
    ip_version: int = 4
```

### 4.2 ExecContext

执行上下文——由 `RemoteExecutor` 从环境变量（`FPE_HOST`/`FPE_NAMESPACE`/`FPE_VRF` 等）内部构建，无需工具调用方传入。

```python
class ExecContext(BaseModel):
    namespace: str | None = None
    vrf: str | None = None
    host: str | None = None
    ip_version: int = 4
    ingress_if: str | None = None
```

### 4.3 InterfaceContext

```python
class InterfaceContext(BaseModel):
    iface: str
    namespace: str | None = None
    vrf: str | None = None
    kind: str
    state: str | None = None
    mtu: int | None = None
    mac: str | None = None
    ips: list[str] = []
    master: str | None = None
    peer: str | None = None
```

### 4.4 RuleMatch

```python
class RuleMatch(BaseModel):
    priority: int
    table: str
    matched_fields: list[str] = []
    unresolved_fields: list[str] = []
    raw: str
```

### 4.5 RuleMatchResult

```python
class RuleMatchResult(BaseModel):
    matches: list[RuleMatch]
    has_unresolved_rules: bool = False
    warnings: list[str] = []
```

### 4.6 NextHop

```python
class NextHop(BaseModel):
    via: str | None = None
    dev: str | None = None
    weight: int | None = None
```

### 4.7 RouteResult

```python
class RouteResult(BaseModel):
    table: str
    route_type: str
    prefix: str
    preferred_src: str | None = None
    metric: int | None = None
    scope: str | None = None
    next_hops: list[NextHop] = []
    raw: str
```

### 4.8 LinkResolution

```python
class LinkResolution(BaseModel):
    dev_type: str
    peer_if: str | None = None
    next_namespace: str | None = None
    next_vrf: str | None = None
    bridge: str | None = None
    requires_ovs: bool = False
```

### 4.9 OvsPortInfo

```python
class OvsPortInfo(BaseModel):
    bridge: str
    port: str
    port_type: str
    ofport: int | None = None
    vlan_tag: int | None = None
    trunk_vlans: list[int] = []
    internal_path_known: bool = False
```

### 4.10 NeighborInfo

```python
class NeighborInfo(BaseModel):
    ip: str
    dev: str
    mac: str | None = None
    state: str
    reachable: bool
```

### 4.11 PathNode

```python
class PathNode(BaseModel):
    hop_index: int
    namespace: str | None = None
    vrf: str | None = None
    obj_type: str
    obj_name: str
    reason: str
    evidence_level: str
```

### 4.12 DecisionEvent

```python
class DecisionEvent(BaseModel):
    state: str
    source: str
    message: str
    evidence_level: str
```

### 4.13 RiskItem

```python
class RiskItem(BaseModel):
    code: str
    severity: str
    message: str
```

### 4.14 AnalysisState

```python
class AnalysisState(BaseModel):
    trace_id: str
    flow_state: str
    packet: PacketContext
    exec_ctx: ExecContext
    current_hop: int = 0
    max_hops: int = 16
    path: list[PathNode] = []
    decision_chain: list[DecisionEvent] = []
    risks: list[RiskItem] = []
    confidence: float = 1.0
    confidence_reasons: list[str] = []
    visited: list[str] = []
```

### 4.15 AnalysisResult

```python
class AnalysisResult(BaseModel):
    status: str
    path: list[PathNode]
    decision_chain: list[DecisionEvent]
    risks: list[RiskItem]
    confidence: float
    confidence_reasons: list[str]
    summary: str
```

## 5. HTTP API 定义

### 5.1 `POST /api/v1/analyze`

输入：

```json
{
  "query": "10.0.0.2 到 8.8.8.8 的链路信息是什么？",
  "packet": null,
  "exec_ctx": null,
  "options": {
    "max_hops": 16
  }
}
```

输出：

`AnalysisResult`

### 5.2 `GET /api/v1/healthz`

输出：

```json
{
  "ok": true
}
```

## 6. CLI 定义

### 6.1 命令

```bash
fpe analyze --src-ip 10.0.0.2 --dst-ip 8.8.8.8 --ingress-if lan0
```

### 6.2 参数

1. `--src-ip`
2. `--dst-ip`
3. `--protocol`
4. `--ingress-if`
5. `--namespace`
6. `--vrf`
7. `--max-hops`
8. `--output json|text`

## 7. MCP Handler 设计

每个 MCP tool handler 应实现统一协议：

```python
class ToolHandler(Protocol):
    name: str

    async def handle(self, payload: dict) -> ToolResult:
        ...
```

注册中心：

```python
class ToolRegistry:
    def register(self, handler: ToolHandler) -> None: ...
    def get(self, name: str) -> ToolHandler: ...
```

## 8. MCP Server 传输接口设计

## 8.1 `stdio` 模式

实现要求：

1. 通过标准输入接收 MCP 请求
2. 通过标准输出返回 MCP 响应
3. handler、registry、service 与传输层解耦

## 8.2 `SSE` 模式

实现要求：

1. 提供基于 HTTP 的 `POST` 建连入口
2. 建连成功后支持服务端事件流输出
3. 工具请求、工具响应、错误事件使用统一 envelope

推荐接口：

1. `POST /mcp/sse/connect`
2. `POST /mcp/sse/message`
3. `GET /mcp/sse/events/{connection_id}`

说明：

1. 这里保留 `POST` 建连能力作为硬要求
2. 后续可根据所选 MCP SDK 或网关协议细化字段
