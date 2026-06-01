# v1 实施计划

## 1. 阶段划分

v1 分四个阶段落地。

```text
Phase 1: 类型和 MCP 契约
Phase 2: FPE 现场摘要和路径接入
Phase 3: 源码 token 检索和 AST 分块
Phase 4: Eino 编排和报告输出
```

## 2. Phase 1: 类型和 MCP 契约

目标：

```text
新增 sdwan_diagnose tool
完成输入解析、默认值、错误处理
先返回占位报告
```

建议文件：

```text
internal/agent/state.go
internal/agent/mcp/diagnose.go
internal/agent/nodes/normalize.go
```

验收：

```text
query 为空时返回 tool error
query 非空时返回 Markdown 占位报告
debug=true 时能输出归一化输入
不破坏现有 MCP tools
```

## 3. Phase 2: FPE 现场摘要和路径接入

目标：

```text
复用现有 db 查询能力生成 SnapshotSummary
复用 walker.ResolvePacket 和 walker.Walk 生成路径结果
无 src_ip/dst_ip 时优雅跳过路径计算
```

建议文件：

```text
internal/agent/nodes/snapshot.go
internal/agent/nodes/path.go
```

SnapshotSummary 建议包含：

```go
type SnapshotSummary struct {
	Interfaces []db.Interface
	Routes     []db.Route
	Neighbors  []db.Neighbor
	OvsBridges []db.OvsBridge
	OvsFlows   []db.OvsFlow
	FrrInfo    []db.FrrInfo
	Warnings   []string
}
```

验收：

```text
能读取 interfaces/routes/neighbors/ovs/frr 摘要
能计算 src_ip/dst_ip 路径
walker incomplete 不导致 tool 失败
```

## 4. Phase 3: 源码检索和 AST 分块

目标：

```text
从 query/snapshot/path 提取 token
用 rg 在 source_root 查 Go 源码
用 AST 扩展命中行到完整函数/结构体
按 score 选出 max_code_chunks
```

建议文件：

```text
internal/agent/nodes/tokens.go
internal/agent/nodes/source_search.go
internal/agent/source/rg.go
internal/agent/source/ast.go
internal/agent/source/chunk.go
```

验收：

```text
source_root 为空时跳过源码检索
rg 不存在时有降级策略
命中函数任意一行时返回完整 FuncDecl
debug=true 能看到 token 和 chunk 排序
```

## 5. Phase 4: Eino 编排和报告输出

目标：

```text
引入 Eino
将节点编排到固定流程
输出六段式 Markdown 诊断报告
保持 Eino 独立封装
```

建议文件：

```text
internal/agent/flow/eino.go
internal/agent/nodes/dossier.go
internal/agent/nodes/reasoning.go
internal/agent/nodes/report.go
```

验收：

```text
除 flow/eino.go 外没有 Eino import
sdwan_diagnose 端到端返回完整报告
debug=true 追加调试附录
无 source_root 时仍能生成 FPE 现场报告
```

## 6. 第一版测试建议

单元测试：

```text
NormalizeRequest
ExtractTokens
ScoreCodeChunks
AST chunk extraction
RenderReport
```

集成测试：

```text
使用 fixtures SQLite DB
使用 fixtures/controller Go 源码
调用 sdwan_diagnose
断言报告包含结论、路径、源码关联和建议动作
```

## 7. 风险和约束

| 风险 | 处理 |
|------|------|
| Eino API 变化 | 只封装在 `flow` 层 |
| LLM 输出不稳定 | 固定 dossier 和 report schema，必要时先用模板报告 |
| 源码无 token 命中 | 明确降级为现场诊断，不强行关联源码 |
| token 太多 | 按权重去重和截断 |
| 代码片段太长 | 限制单 chunk 行数和总字符数 |
| DB 数据量大 | SnapshotSummary 按 focus 和 packet 做裁剪 |

## 8. Definition of Done

v1 完成标准：

```text
1. `sdwan_diagnose` MCP tool 可用
2. 输入自然语言 query 能生成诊断报告
3. 输入 src_ip/dst_ip 能触发路径分析
4. 输入 source_root 能关联控制器源码
5. Eino 只存在于独立 flow 封装层
6. 不引入向量检索依赖
7. debug=true 可追踪 token、路径、源码命中和证据摘要
8. README 或 USE.md 能链接到 docs/v1
```
