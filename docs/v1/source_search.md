# v1 源码检索设计

## 1. 目标

v1 源码检索只做确定性检索：

```text
token 提取 -> rg 字面匹配 -> Go AST 边界扩展 -> 排序截断 -> 注入诊断卷宗
```

v1 不做：

```text
向量检索
embedding 模型
云端 RAG
完整跨包静态调用图
自动修复代码
```

## 2. Token 来源

Token 从三类输入提取：

| 来源 | 示例 |
|------|------|
| 用户 query | `10.220.21.241`、`ANPOSNS`、`FRR`、`tunnel` |
| FPE snapshot | interface、VRF、BGP neighbor、route prefix、OVS bridge |
| path result | `table=102`、`cookie=0xabc`、`group:12`、`output:5`、`remote_ip`、`vni` |

## 3. Token 类型

```go
type SearchToken struct {
	Value      string
	Type       string // ip/interface/vrf/ovs_table/ovs_cookie/ovs_group/vni/frr/prefix/keyword
	Source     string // query/snapshot/path/frr/ovs
	Weight     int
	ExactMatch bool
}
```

建议权重：

| 类型 | 权重 | 说明 |
|------|------|------|
| OVS cookie | 100 | 精确定位控制器下发逻辑 |
| VRF 名称 | 90 | SD-WAN 隔离域强特征 |
| VNI/tunnel_id | 90 | Overlay 强特征 |
| route prefix | 80 | 路由逻辑强特征 |
| interface/bridge | 70 | 拓扑强特征 |
| table/group/ofport | 65 | OVS pipeline 特征 |
| IP | 60 | 现场强特征，但源码中可能较少出现 |
| FRR/BGP 关键词 | 50 | 方向性特征 |
| 普通 keyword | 20 | 弱特征 |

## 4. Token 提取规则

### 4.1 IP 和 Prefix

正则：

```text
\b(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?\b
```

处理：

```text
过滤非法 IP
保留 query 中出现的 IP
从 route/FRR 输出中保留目标相关 prefix
```

### 4.2 OVS Token

规则：

```text
cookie=0x...      -> ovs_cookie
table=N           -> ovs_table
group:N           -> ovs_group
output:N          -> ovs_output
tun_id=N          -> vni/tunnel_id
metadata=...      -> ovs_metadata
reg0=...          -> ovs_register
```

### 4.3 SD-WAN 语义 Token

关键词：

```text
vrf
vni
vxlan
geneve
tunnel
overlay
underlay
frr
bgp
ospf
bfd
route-map
neighbor
policy
rebuild
sync
reconcile
```

中文关键词也要映射：

```text
隧道 -> tunnel/vxlan
重建 -> rebuild/reconcile
路由刷新 -> route/sync
邻居 -> neighbor
策略路由 -> policy/rule
断流 -> drop/unreachable/failed
```

## 5. rg 检索

每个 token 执行字面匹配。

建议命令形态：

```bash
rg --json --fixed-strings --line-number --context 2 <token> <source_root>
```

过滤范围：

```text
包含: *.go
排除: vendor/
排除: .git/
排除: testdata/
排除: *_test.go 可配置，默认先排除
```

结果字段：

```go
type RawMatch struct {
	Token      SearchToken
	FilePath   string
	Line       int
	LineText   string
	Context    []string
}
```

## 6. AST 边界扩展

rg 命中后，不直接把上下文几行塞给模型，而是用 Go AST 找到完整逻辑单元。

Chunk 类型：

| AST 节点 | Chunk 类型 | 说明 |
|----------|------------|------|
| `FuncDecl` | `function` | 函数或方法 |
| `TypeSpec` | `type` | struct/interface/type alias |
| `GenDecl` | `const`/`var` | 常量和变量块 |

CodeChunk：

```go
type CodeChunk struct {
	FilePath      string
	PackageName   string
	Kind          string
	Name          string
	Receiver      string
	StartLine     int
	EndLine       int
	DocComment   string
	Lines         string
	MatchedTokens []SearchToken
	Callers       []string
	Callees       []string
	Score         int
}
```

v1 的调用关系只做直接提取：

```text
在 FuncDecl body 内提取 CallExpr
记录 selector 名称，例如 route.Sync、RebuildVxlan、vtysh.Run
不强求跨包解析准确
```

## 7. 排序策略

Chunk 得分建议：

```text
score = token_weight_sum
      + exact_match_bonus
      + focus_bonus
      + function_name_bonus
      + doc_comment_bonus
      - oversized_penalty
```

规则：

| 项 | 分值 |
|----|------|
| token 权重累加 | `sum(token.Weight)` |
| 同一 chunk 命中多个 token | `+10 * token_count` |
| 函数名包含 focus | `+30` |
| 文件路径包含 focus | `+20` |
| 注释包含 focus | `+10` |
| chunk 超过 300 行 | `-40` |
| vendor/test 文件 | 默认排除 |

最终取：

```text
max_code_chunks，默认 12
单个 chunk 最多 250-300 行
总注入源码字符数建议限制在 40k-60k 字符
```

## 8. 降级行为

| 场景 | 降级 |
|------|------|
| `source_root` 为空 | 跳过源码检索，只做 FPE 现场报告 |
| `source_root` 不存在 | 加 warning，跳过源码检索 |
| `rg` 不存在 | 使用 Go 文件遍历 + strings.Contains |
| AST parse 失败 | 使用 rg 上下文片段作为 fallback chunk |
| token 为空 | 用 focus 和 query 关键词做弱检索 |
| 无命中 | 报告明确写“未命中源码证据” |

## 9. 诊断卷宗注入格式

源码片段进入 dossier 时使用固定格式：

~~~md
### Code Chunk 1

- File: controller/tunnel.go:120
- Kind: function
- Name: RebuildVxlan
- Receiver: *Controller
- Matched tokens: vxlan, vni, ANPOSNS
- Direct callees: SyncRoute, ApplyOVSFlow

```go
func (c *Controller) RebuildVxlan(...) {
    ...
}
```
~~~

## 10. 验收标准

| 项 | 标准 |
|----|------|
| 精确 token | `cookie=0x...` 能直接命中相关代码 |
| AST 完整性 | 命中函数中任意一行时，返回完整函数 |
| 截断稳定 | 超长函数不会撑爆 prompt |
| 无源码也可运行 | `source_root` 为空时仍输出现场诊断 |
| debug 透明 | 能看到 token、rg 命中、最终 chunk 排序 |
