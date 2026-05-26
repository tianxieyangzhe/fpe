# FPE 接口与数据模型

## 1. MCP 设计目标

FPE 需要以 MCP Server 方式暴露核心能力，使 Agent 不直接拼命令，而是调用标准化工具。

MCP 接口设计要求：

1. 输入稳定
2. 输出稳定
3. 全部结构化
4. 执行上下文支持通过 `exec_ctx` 显式传入，并由环境变量兜底
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

目的：

1. 作为主分析入口，对单条业务流量进行 OVS 优先的完整分析。
2. 优先解释 OVS `bridge -> port -> flow -> action`。
3. 在 OVS 将流量送入内核时，继续分析 `rule -> route -> neighbor`。
4. 输出结构化路径、风险、图结构和 Mermaid。

输入：

```json
{
  "packet": {
    "src_ip": "10.0.0.2",
    "dst_ip": "8.8.8.8",
    "protocol": "icmp",
    "ingress_if": "lan0",
    "vlan_id": 10,
    "tunnel_id": "1001",
    "ip_version": 4
  },
  "exec_ctx": {
    "namespace": "ns_app",
    "vrf": "vrf-app",
    "host": "192.0.2.10"
  },
  "options": {
    "max_hops": 16
  }
}
```

参数说明：

1. `packet.src_ip` / `packet.dst_ip`：源和目的地址，必填。
2. `packet.ingress_if`：入口接口，OVS-first 分析必填。
3. `packet.protocol` / `src_port` / `dst_port`：提高 flow 和规则命中精度。
4. `packet.vlan_id`：用于 VLAN 相关 flow 命中。
5. `packet.tunnel_id`：用于 tunnel / VNI 相关 flow 命中。
6. `packet.fwmark`：用于策略路由命中。
7. `exec_ctx.namespace` / `exec_ctx.vrf`：指定分析视角。
8. `options.max_hops`：控制分析深度。

输出重点：

1. `path`：人类可读路径。
2. `decision_chain`：关键判断过程。
3. `risks`：高价值异常点。
4. `graph`：前端可直接消费的图结构。
5. `mermaid`：可直接渲染的链路图。

### 2.2 `fpe.get_interface_context`

目的：

1. 查询接口属性、角色和所属 namespace / VRF。
2. 为路径推断和链路图构图提供基础节点。

输入：

```json
{
  "iface": "lan0",
  "namespace": "ns_app",
  "vrf": "vrf-app",
  "if_type": "veth",
  "role": "bridge-port",
  "state": "UP"
}
```

参数说明：

1. `iface`：接口名；省略时返回全部接口。
2. `namespace` / `vrf`：限定查询作用域。
3. `if_type`：按接口类型过滤。
4. `role`：按接口角色过滤。
5. `state`：按接口状态过滤。

### 2.3 `fpe.get_rule`

目的：

1. 查询策略路由规则。
2. 针对特定报文返回命中规则和首条生效规则。

输入：

```json
{
  "namespace": "ns_app",
  "vrf": "vrf-app",
  "packet": {
    "src_ip": "10.0.0.2",
    "dst_ip": "8.8.8.8",
    "ingress_if": "lan0",
    "fwmark": "0x10",
    "ip_version": 4
  }
}
```

参数说明：

1. `priority`：只查某个优先级。
2. `table`：只查某张表的规则。
3. `packet`：返回 `matched_rules` 和 `selected_rule`。

### 2.4 `fpe.get_route`

目的：

1. 查询路由表。
2. 对目标地址返回最优匹配路由。
3. 过滤某个出接口相关的路由。

输入：

```json
{
  "namespace": "ns_app",
  "vrf": "vrf-app",
  "table": "100",
  "dst_ip": "8.8.8.8",
  "device": "wan0",
  "best_only": true
}
```

参数说明：

1. `table`：指定路由表。
2. `dst_ip`：用于最优匹配。
3. `device`：只看通过某个设备的路由。
4. `best_only`：只返回最优路由。

### 2.5 `fpe.get_neighbor`

目的：

1. 查询 ARP/NDP 邻居。
2. 验证下一跳是否存在以及是否可达。

输入：

```json
{
  "namespace": "ns_app",
  "vrf": "vrf-app",
  "device": "wan0",
  "target_ip": "192.168.1.1",
  "state": "REACHABLE",
  "reachable_only": true
}
```

参数说明：

1. `device`：只看某个设备上的邻居。
2. `target_ip`：只看某个 IP。
3. `state`：按状态过滤。
4. `reachable_only`：只返回可达邻居。

### 2.6 `fpe.get_ovs_bridges`

目的：

1. 查询 OVS bridge、port、ofport、VLAN 和 trunk 结构。
2. 确认某个接口属于哪个桥。
3. 为链路图生成 bridge/port 拓扑。

输入：

```json
{
  "bridge": "br-int",
  "interface": "lan1",
  "include_flows": true
}
```

参数说明：

1. `bridge`：只查单个桥。
2. `port`：只返回包含该端口的桥。
3. `interface`：只返回包含该接口的桥。
4. `include_flows`：附带每个桥上的 flows。

### 2.7 `fpe.get_ovs_flows`

目的：

1. 查询 OVS flow 表项。
2. 按入口接口缩小到相关桥。
3. 按完整报文返回候选命中 flow。

输入：

```json
{
  "ingress_if": "lan1",
  "table": 0,
  "packet": {
    "src_ip": "10.0.0.2",
    "dst_ip": "8.8.8.8",
    "protocol": "icmp",
    "ingress_if": "lan1",
    "vlan_id": 10
  },
  "active_only": true
}
```

参数说明：

1. `bridge`：指定桥。
2. `table`：指定 table。
3. `ingress_if`：自动定位所属桥和入口 port。
4. `packet`：返回 `matched_flows`。
5. `match_contains`：按原始 match 文本做子串过滤。
6. `active_only`：只返回计数大于 0 的 flow。

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
    vlan_id: int | None = None
    tunnel_id: str | None = None
    ip_version: int = 4
```

### 4.2 ExecContext

执行上下文——可由工具调用方显式传入，也可由 `RemoteExecutor` 从环境变量（`FPE_HOST`/`FPE_NAMESPACE`/`FPE_VRF` 等）内部构建。

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
    if_type: str = "physical"
    role: str | None = None
    state: str | None = None
    mtu: int | None = None
    mac: str | None = None
    ips: list[str] = []
    master: str | None = None
    peer: str | None = None
```

### 4.4 RuleInfo

```python
class RuleInfo(BaseModel):
    priority: int
    table: str
    raw: str
    namespace: str | None = None
    vrf: str | None = None
```

### 4.5 RuleMatch

```python
class RuleMatch(BaseModel):
    priority: int
    table: str
    matched_fields: list[str] = []
    unresolved_fields: list[str] = []
    raw: str
```

### 4.6 RuleMatchResult

```python
class RuleMatchResult(BaseModel):
    matches: list[RuleMatch]
    has_unresolved_rules: bool = False
    warnings: list[str] = []
```

### 4.7 NextHop

```python
class NextHop(BaseModel):
    via: str | None = None
    dev: str | None = None
    weight: int | None = None
```

### 4.8 RouteResult

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
    namespace: str | None = None
    vrf: str | None = None
```

### 4.9 LinkResolution

```python
class LinkResolution(BaseModel):
    dev_type: str
    peer_if: str | None = None
    next_namespace: str | None = None
    next_vrf: str | None = None
    bridge: str | None = None
    requires_ovs: bool = False
```

### 4.10 OvsPortInfo

```python
class OvsPortInfo(BaseModel):
    bridge: str
    port: str
    interface: str | None = None
    port_type: str
    ofport: int | None = None
    vlan_tag: int | None = None
    trunk_vlans: list[int] = []
    mac: str | None = None
    internal_path_known: bool = False
```

### 4.11 OvsBridge

```python
class OvsBridge(BaseModel):
    name: str
    datapath_id: str | None = None
    datapath_type: str | None = None
    ports: list[OvsPortInfo] = []
```

### 4.12 OvsFlow

```python
class OvsFlow(BaseModel):
    bridge: str
    table: int
    priority: int
    match: str
    actions: str
    match_fields: dict[str, str] = {}
    action_list: list[str] = []
    cookie: str | None = None
    duration_sec: float | None = None
    n_packets: int | None = None
    n_bytes: int | None = None
    idle_age_sec: float | None = None
```

### 4.13 NeighborInfo

```python
class NeighborInfo(BaseModel):
    ip: str
    dev: str
    mac: str | None = None
    state: str
    reachable: bool
    namespace: str | None = None
    vrf: str | None = None
```

### 4.14 PathNode

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

### 4.15 DecisionEvent

```python
class DecisionEvent(BaseModel):
    state: str
    source: str
    message: str
    evidence_level: str
```

### 4.16 RiskItem

```python
class RiskItem(BaseModel):
    code: str
    severity: str
    message: str
```

### 4.17 GraphNode / GraphEdge / FlowGraph

```python
class GraphNode(BaseModel):
    id: str
    kind: str
    label: str
    namespace: str | None = None
    vrf: str | None = None
    attrs: dict = {}

class GraphEdge(BaseModel):
    src: str
    dst: str
    relation: str
    reason: str
    evidence_level: str = "inferred"
    attrs: dict = {}

class FlowGraph(BaseModel):
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
```

### 4.18 AnalysisState

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
    graph: FlowGraph
```

### 4.19 AnalysisResult

```python
class AnalysisResult(BaseModel):
    status: str
    path: list[PathNode]
    decision_chain: list[DecisionEvent]
    risks: list[RiskItem]
    confidence: float
    confidence_reasons: list[str]
    summary: str
    graph: FlowGraph | None = None
    mermaid: str | None = None
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
