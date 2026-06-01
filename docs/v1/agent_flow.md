# v1 Agent Flow 与 Eino 封装

## 1. 原则

v1 引入 Eino，但必须保持独立封装。

核心原则：

```text
业务节点是普通 Go 函数
Eino 只负责编排节点顺序
flow/eino.go 是唯一直接依赖 Eino 的文件
任何节点都不能 import Eino
后续替换 Eino 时，只替换 flow 层
```

## 2. 建议状态类型

```go
type DiagnoseInput struct {
	Query   string          `json:"query"`
	Packet  PacketInput     `json:"packet"`
	Context DiagnoseContext `json:"context"`
	Debug   bool            `json:"debug"`
}

type PacketInput struct {
	SrcIP     string `json:"src_ip"`
	DstIP     string `json:"dst_ip"`
	Proto     string `json:"proto"`
	SrcPort   *int   `json:"src_port"`
	DstPort   *int   `json:"dst_port"`
	Namespace string `json:"namespace"`
}

type DiagnoseContext struct {
	DB            string   `json:"db"`
	SourceRoot    string   `json:"source_root"`
	Focus         []string `json:"focus"`
	MaxCodeChunks int      `json:"max_code_chunks"`
}

type AgentState struct {
	Input              DiagnoseInput
	Normalized         NormalizedRequest
	Snapshot           SnapshotSummary
	PathResult         *walker.WalkResult
	Tokens             []SearchToken
	CodeChunks         []CodeChunk
	Dossier            InvestigationDossier
	Analysis           string
	ReportMarkdown     string
	Debug              DebugInfo
	Warnings           []string
}
```

## 3. 固定流程

v1 暂不做向量分支，流程固定：

```text
START
  -> normalize_request
  -> snapshot_collector
  -> path_analyzer
  -> token_extractor
  -> source_search
  -> dossier_builder
  -> reasoning
  -> report_renderer
  -> END
```

## 4. 节点职责

| 节点 | 输入 | 输出 | 说明 |
|------|------|------|------|
| `normalize_request` | `DiagnoseInput` | `NormalizedRequest` | 校验 query、补默认值、判断是否可做路径分析 |
| `snapshot_collector` | DB + focus | `SnapshotSummary` | 从 SQLite 获取接口、路由、邻居、OVS、FRR 摘要 |
| `path_analyzer` | packet + DB | `WalkResult` | 有 `src_ip/dst_ip` 时调用 walker |
| `token_extractor` | query + snapshot + path | `[]SearchToken` | 提取 IP、接口、VRF、table、cookie、VNI 等 |
| `source_search` | source_root + tokens | `[]CodeChunk` | rg 检索源码并用 AST 扩展到完整逻辑单元 |
| `dossier_builder` | snapshot + path + code | `InvestigationDossier` | 组装诊断卷宗 |
| `reasoning` | dossier | `Analysis` | 调 LLM 或先生成推理 prompt |
| `report_renderer` | analysis + debug | `ReportMarkdown` | 输出固定 Markdown 报告 |

## 5. Eino 编排伪代码

```go
package flow

import (
    "context"

    "github.com/cloudwego/eino/compose"
    "github.com/yangshuai/fpe/internal/agent"
    "github.com/yangshuai/fpe/internal/agent/nodes"
)

func Build(ctx context.Context, deps agent.Dependencies) (compose.Runnable[agent.AgentState, agent.AgentState], error) {
    graph := compose.NewGraph[agent.AgentState, agent.AgentState]()

    _ = graph.AddElementNode("normalize_request", compose.NewMigrationNode(nodes.NormalizeRequest(deps)))
    _ = graph.AddElementNode("snapshot_collector", compose.NewMigrationNode(nodes.CollectSnapshot(deps)))
    _ = graph.AddElementNode("path_analyzer", compose.NewMigrationNode(nodes.AnalyzePath(deps)))
    _ = graph.AddElementNode("token_extractor", compose.NewMigrationNode(nodes.ExtractTokens(deps)))
    _ = graph.AddElementNode("source_search", compose.NewMigrationNode(nodes.SearchSource(deps)))
    _ = graph.AddElementNode("dossier_builder", compose.NewMigrationNode(nodes.BuildDossier(deps)))
    _ = graph.AddElementNode("reasoning", compose.NewMigrationNode(nodes.Reason(deps)))
    _ = graph.AddElementNode("report_renderer", compose.NewMigrationNode(nodes.RenderReport(deps)))

    _ = graph.AddEdge(compose.START, "normalize_request")
    _ = graph.AddEdge("normalize_request", "snapshot_collector")
    _ = graph.AddEdge("snapshot_collector", "path_analyzer")
    _ = graph.AddEdge("path_analyzer", "token_extractor")
    _ = graph.AddEdge("token_extractor", "source_search")
    _ = graph.AddEdge("source_search", "dossier_builder")
    _ = graph.AddEdge("dossier_builder", "reasoning")
    _ = graph.AddEdge("reasoning", "report_renderer")
    _ = graph.AddEdge("report_renderer", compose.END)

    return graph.Compile(ctx)
}
```

## 6. 未来可插拔分支

v1 不做向量检索，但流程要给后续留扩展位。

未来分支可以是：

```text
token_extractor
  -> tokens 足够: source_search
  -> tokens 不足: broad_ast_search
  -> 用户输入不完整: clarification_builder
```

或：

```text
source_search
  -> 命中代码: dossier_builder
  -> 未命中代码: architecture_hint_builder
```

## 7. Dependencies 注入

节点不要直接创建全局依赖，统一从 `agent.Dependencies` 注入。

```go
type Dependencies struct {
	DB             *db.DB
	SourceSearcher SourceSearcher
	Reasoner       Reasoner
	Now            func() time.Time
	MaxCodeChunks  int
}
```

这样可以让节点单元测试不依赖 Eino、不依赖真实 LLM，也不依赖真实文件系统。

## 8. 验收标准

| 项 | 标准 |
|----|------|
| Eino 封装 | 除 `internal/agent/flow` 外无 Eino import |
| 流程可测试 | 每个 node 可以直接单测 |
| 流程可替换 | 能用手写顺序执行器替代 Eino 跑通同样节点 |
| 错误不中断 | 源码检索失败不影响 FPE 现场诊断 |
| Debug 可追踪 | `debug=true` 能看到每个节点的关键输入输出摘要 |
