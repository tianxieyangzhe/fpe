# FPE Go 重构设计

## 1. 背景与目标

FPE 当前正在从旧的 Python 实现重构为 Go 实现。旧架构偏向 MCP 实时采集，每次分析都需要实时 SSH 执行命令，大模型也承担了过多确定性计算。

新架构目标：

```text
采集器 -> SQLite 知识库 -> MCP Server 查询 -> 大模型理解和表达
```

职责边界：

| 职责 | 执行方 |
|------|--------|
| 命令采集、本地/SSH 执行 | Go 程序 |
| 结构化写入 SQLite | Go 程序 |
| IP rules、路由 LPM、OVS flow/group walk | Go 程序 |
| 报文字段补全、路径段计算 | Go 程序 |
| uncertain 分支解释、诊断报告、Mermaid 拓扑图 | 大模型 |
| 对端未采集或线索不足时的跨机器推理 | 大模型 |

## 2. 当前架构

```text
fpe collect                         本机采集 -> <hostname>.db
fpe collect node1.db                本机采集 -> node1.db
fpe collect --ssh 192.168.1.10      SSH 采集 -> 192_168_1_10.db
fpe serve --db node1.db             启动 stdio MCP Server
fpe serve --db node1.db --transport sse --addr :8080
fpe serve --db node1.db --transport mcp --addr :8080
```

每次采集生成一个 SQLite 文件。当前 `serve` 命令一次加载一个 DB；多机器分析时可以为不同 DB 启动多个 MCP Server，由大模型分别查询并串联路径段。

## 3. 项目结构

```text
fpe/
├── main.go
├── go.mod
├── cmd/
│   ├── collect/collect.go          # collect 子命令
│   └── serve/serve.go              # serve 子命令
├── internal/
│   ├── collector/
│   │   ├── executor.go             # Local/SSH 命令执行接口
│   │   ├── helpers.go              # 采集辅助函数
│   │   ├── interfaces.go           # 接口采集
│   │   ├── namespaces.go           # netns 发现
│   │   ├── rules.go                # IP rule 采集
│   │   ├── routes.go               # 路由采集
│   │   ├── neighbors.go            # ARP/NDP 邻居采集
│   │   ├── vrf.go                  # VRF 发现与采集
│   │   ├── ovs.go                  # OVS bridge/port/flow/group/fdb/tunnel ARP
│   │   └── frr.go                  # FRR vtysh 输出采集
│   ├── db/
│   │   ├── schema.go               # SQLite DDL
│   │   ├── writer.go               # 写入接口
│   │   └── query.go                # 查询接口
│   ├── walker/
│   │   ├── packet.go               # PacketTuple 与字段补全
│   │   ├── rules.go                # IP rules 匹配
│   │   ├── routes.go               # 路由 LPM 匹配
│   │   ├── ovs.go                  # OVS flow/group walk
│   │   ├── chain.go                # 路径段串联
│   │   └── types.go                # 核心数据类型
│   ├── mcp/
│   │   ├── server.go               # MCP server 入口
│   │   └── tools.go                # MCP tools 注册
│   └── logs/
│       └── logs.go                 # 日志封装
├── USE.md
└── docs/
    └── FPE_Go_重构设计.md
```

## 4. 采集范围

`collect` 当前会采集：

| 类型 | 说明 |
|------|------|
| root namespace | 接口、IP rules、路由、邻居 |
| `ANPOSNS` namespace | 如果存在，采集接口、IP rules、路由、邻居 |
| VRF | 在 namespace 内发现 VRF 设备后，采集 VRF 维度的路由、规则、邻居，并回写接口 VRF 字段 |
| OVS | bridge、port、flow、group、group bucket、FDB、tunnel ARP |
| FRR | 在 `ANPOSNS` 里采集常用 `vtysh` 命令输出 |

FRR 当前采集命令：

```text
show ip route
show bfd peers
show running-config
show bgp summary
show bgp ipv4 unicast
show ip ospf neighbor
```

FRR 输出会记录状态：

| 状态 | 含义 |
|------|------|
| `ok` | 命令执行成功且有有效输出 |
| `empty` | 协议未启用或输出为空 |
| `error` | 命令执行失败 |

## 5. SQLite 表结构

当前 schema 不使用 `snapshots` 表；一个 DB 文件表示一次采集结果。

核心表：

| 表 | 内容 |
|----|------|
| `interfaces` | 接口、namespace、VRF、MAC、MTU、master、peer、IP 列表 |
| `rules` | namespace/VRF 下的 IP policy rules |
| `routes` | namespace/VRF/table 下的路由和 next hops |
| `neighbors` | ARP/NDP 邻居 |
| `ovs_bridges` | OVS bridge |
| `ovs_ports` | OVS port/interface、ofport、VLAN、options |
| `ovs_flows` | OVS flow，包含原始 match/actions 和解析后的 JSON 字段 |
| `ovs_groups` | OVS group 元信息 |
| `ovs_group_buckets` | group bucket 和 action list |
| `ovs_fdb` | OVS MAC 学习表 |
| `ovs_tnl_arp` | OVS tunnel ARP 缓存 |
| `frr_info` | FRR 命令原始输出和状态 |

主要索引：

```sql
idx_interfaces_ns(namespace, vrf, name)
idx_rules_ns(namespace, vrf, priority)
idx_routes_ns_table(namespace, vrf, table_id)
idx_neighbors_ip(ip)
idx_ovs_ports_bridge(bridge, port)
idx_flows_table(bridge, table_id, priority DESC)
idx_groups_id(bridge, group_id)
idx_ovs_fdb_mac(bridge, mac)
idx_ovs_tnl_arp_ip(bridge, ip)
```

## 6. 核心数据类型

### PacketTuple

```go
type PacketTuple struct {
    SrcIP     string
    DstIP     string
    Proto     string
    SrcPort   *int
    DstPort   *int
    InPort    *int
    SrcMac    string
    DstMac    string
    VlanID    *int
    TunnelID  *int64
    Namespace string
    Uncertain []string
}
```

### WalkResult

```go
type Hop struct {
    Type      string
    TableID   int
    Match     string
    Action    string
    Certainty string
    Reason    string
}

type PathSegment struct {
    Host       string
    Namespace  string
    Ingress    string
    Egress     string
    EgressType string
    EgressPeer *PeerHint
    Hops       []Hop
    Certainty  string
}

type PathLeaf struct {
    Segments  []PathSegment
    Outcome   string
    Certainty string
}

type WalkResult struct {
    Packet PacketTuple
    Leaves []PathLeaf
    Status string
}
```

## 7. Walker 匹配逻辑

### 7.1 入口判断

设备类型判断优先级：

```text
1. 查 ovs_bridges，命中则进入 OVS pipeline
2. 查 ovs_ports，命中则按 OVS port/ofport 处理
3. 查 interfaces，命中则按内核接口处理
```

OVS 接管的物理口可能同时出现在 `interfaces` 和 `ovs_ports` 中，walker 应优先使用 OVS 视角。

### 7.2 IP Rules

```text
按 priority 升序遍历
from_prefix 非空时匹配 src_ip
fwmark 非空时匹配报文 fwmark
命中后得到 table_id
```

### 7.3 路由

```text
按 namespace + vrf + table_id 过滤
按 prefix 长度 DESC、metric ASC 排序
选择第一个覆盖 dst_ip 的路由
输出 next hop、dev、preferred_src
```

### 7.4 OVS Flow

```text
按 bridge + table_id 过滤
按 priority DESC 遍历
match_fields 全字段匹配
ip_src/ip_dst 使用 CIDR 包含判断
ct_state/reg/metadata 等无法完全确定的字段标记 uncertain
```

### 7.5 OVS Action

```text
goto_table:N      继续 walk table N
resubmit(,N)      继续 walk table N
group:G           展开 group buckets
output:N          输出到 ofport
output:LOCAL      进入本机协议栈
drop              终止并标记丢弃
load:V->regX      记录寄存器值用于后续匹配
ct(...)           标记连接跟踪相关分支为 uncertain
```

## 8. MCP Tools

| Tool | 参数 | 说明 |
|------|------|------|
| `get_interfaces` | `namespace?` | 查询网络接口 |
| `get_routes` | `namespace?`, `table?` | 查询路由，`table` 默认 `main` |
| `get_neighbors` | `namespace?`, `ip` | 按 IP 查询邻居 |
| `get_ovs_bridges` | 无 | 查询 OVS bridge |
| `get_ovs_flows` | `bridge`, `table?` | 查询 OVS flow |
| `get_ovs_groups` | `bridge`, `group_id?` | 查询 OVS group |
| `get_ovs_fdb` | `bridge` | 查询 OVS FDB |
| `get_ovs_tnl_arp` | `bridge`, `ip?` | 查询 OVS tunnel ARP |
| `get_frr_info` | `command?` | 查询 FRR 原始输出 |
| `resolve_packet` | `src_ip`, `dst_ip`, `proto?`, `dst_port?`, `src_port?`, `namespace?` | 补全报文字段 |
| `get_path_segments` | `src_ip`, `dst_ip`, `proto?`, `dst_port?`, `src_port?`, `namespace?` | 计算路径树 |

主要分析入口是：

```text
resolve_packet -> get_path_segments
```

## 9. 使用建议

单机分析：

```bash
go run . collect
go run . serve --db <hostname>.db --transport mcp --addr :8080
```

多机分析：

```bash
go run . collect --ssh node1 node1.db
go run . collect --ssh node2 node2.db
go run . serve --db node1.db --transport mcp --addr :8081
go run . serve --db node2.db --transport mcp --addr :8082
```

大模型分别查询多个 MCP Server，依据 tunnel remote IP、下一跳 IP、veth peer、namespace/VRF 信息串联跨机器路径。

## 10. 技术选型

| 组件 | 选型 |
|------|------|
| 语言 | Go |
| CLI | `spf13/cobra` |
| SQLite | `modernc.org/sqlite`，纯 Go，无 CGO |
| SSH | `golang.org/x/crypto/ssh` |
| MCP | `github.com/modelcontextprotocol/go-sdk` |
| IP/CIDR | Go 标准库 `net/netip` |
