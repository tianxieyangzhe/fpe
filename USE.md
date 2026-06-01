# FPE 使用指南

## 开发调试（无需编译）

```bash
go run . collect
go run . collect --ssh 10.220.21.237 --user root --key ~/.ssh/id_ed25519
go run . serve --db node1.db
go run . serve --db node1.db --transport sse --addr :8000
go run . serve --db node1.db --transport mcp --addr :8000
```

`serve --transport` 当前支持：

| 值 | 说明 |
|----|------|
| `stdio` | 默认值，适合 Claude Desktop 等通过标准输入输出连接的 MCP 客户端 |
| `sse` | SSE HTTP 模式 |
| `mcp` | Streamable HTTP 模式，推荐用于 2025 MCP 规范 |

## 安装

```bash
go build -o fpe .
```

## 采集

### 本地采集

```bash
./fpe collect
# 输出：<hostname>.db

./fpe collect mynode.db
# 输出：mynode.db
```

### SSH 远程采集

```bash
./fpe collect --ssh 192.168.1.10 --user root --key ~/.ssh/id_rsa
# 输出：192_168_1_10.db

# 指定 db 文件名（位置参数）
./fpe collect --ssh 192.168.1.10 node1.db

# 或用 flag
./fpe collect --ssh 192.168.1.10 --output /data/node1.db
```

采集内容：

- root namespace 的网络接口、IP 策略路由规则、路由表、ARP/NDP 邻居。
- `ANPOSNS` namespace 的网络接口、规则、路由和邻居；如果该 namespace 不存在则跳过。
- namespace 内发现到的 VRF 设备及其 VRF 维度的路由、规则和邻居。
- OVS bridge、port、flow、group、FDB、tunnel ARP。
- `ANPOSNS` 下 FRR 信息：`show ip route`、`show bfd peers`、`show running-config`、`show bgp summary`、`show bgp ipv4 unicast`、`show ip ospf neighbor`。

## 启动 MCP Server

### stdio 模式（用于 Claude Desktop 等 MCP 客户端）

```bash
./fpe serve --db node1.db
```

### SSE 模式（2024-11-05 规范）

```bash
./fpe serve --db node1.db --transport sse
# 默认监听 :8080

./fpe serve --db node1.db --transport sse --addr :9090
```

### Streamable HTTP 模式（2025 规范，推荐）

```bash
./fpe serve --db node1.db --transport mcp
# 默认监听 :8080，单端口处理 POST/GET/DELETE

./fpe serve --db node1.db --transport mcp --addr :9090
```

## MCP Tools

| Tool | 说明 |
|------|------|
| `get_interfaces` | 查询网络接口列表 |
| `get_routes` | 查询路由表，支持按 namespace/table 过滤 |
| `get_neighbors` | 查询 ARP/NDP 邻居 |
| `get_ovs_bridges` | 查询 OVS bridge 列表 |
| `get_ovs_flows` | 查询 OVS flow 表 |
| `get_ovs_groups` | 查询 OVS group 及 buckets |
| `get_ovs_fdb` | 查询 OVS MAC 学习表 |
| `get_ovs_tnl_arp` | 查询 OVS tunnel ARP 缓存 |
| `get_frr_info` | 查询采集到的 FRR 原始输出，支持按 command 过滤 |
| `resolve_packet` | 补全报文字段（推导 in_port/mac 等） |
| `get_path_segments` | 计算报文完整路径树，返回所有可能链路 |

## 典型使用流程

1. 在目标机器上采集：

```bash
./fpe collect
```

2. 将 `.db` 文件拷贝到分析机器，启动 MCP Server：

```bash
./fpe serve --db node1.db --transport mcp --addr :8080
```

3. 在 Claude 中调用：

```
分析 192.168.2.56 访问 8.8.8.8 的链路
```

Claude 会依次调用 `resolve_packet` 补全报文信息，再调用 `get_path_segments` 获取完整路径树，最后生成诊断报告和 Mermaid 拓扑图。

## 多机器场景

每台机器独立采集，分别启动 MCP Server 或合并分析：

```bash
./fpe collect --ssh node1 node1.db
./fpe collect --ssh node2 node2.db

# 分别启动（不同端口）
./fpe serve --db node1.db --transport mcp --addr :8081
./fpe serve --db node2.db --transport mcp --addr :8082
```

Claude 通过两个 MCP Server 分别查询各机器的知识库，串联跨机器路径段。
