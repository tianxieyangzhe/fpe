# FPE v1 SD-WAN Agent 设计总览

## 1. 目标

v1 的目标是在现有 FPE Go 采集、SQLite 知识库和 MCP Server 基础上，新增一个面向 SD-WAN 排障的专家智能体能力。

它不是替代 FPE 的底层采集和路径计算，而是在 FPE 已经能够回答“现场是什么样”的基础上，进一步回答：

```text
为什么现场会变成这样？
控制器源码里的哪段逻辑可能导致这个现场？
下一步应该如何验证、修复或定位？
```

v1 交付形态：

```text
单仓库
单 Go 二进制
MCP tool: sdwan_diagnose
Eino 负责流程编排
FPE 负责确定性网络分析
Go AST + rg 负责源码证据检索
```

## 2. v1 明确决策

| 决策 | 结论 |
|------|------|
| 是否引入 Eino | 引入 |
| Eino 依赖方式 | 独立封装，只作为流程编排层 |
| 是否引入向量检索 | v1 不引入 |
| 源码检索方式 | token 提取 + `rg` 字面匹配 + Go AST 边界扩展 |
| 对外 MCP 工具 | 第一版只暴露 `sdwan_diagnose` 一个超级工具 |
| 报告格式 | 固定 Markdown 六段式报告 |
| 调试输出 | 通过 `debug=true` 返回 token、证据摘要和命中代码片段 |

## 3. 总体链路

```text
用户问题
  -> sdwan_diagnose
  -> normalize_request
  -> snapshot_collector
  -> path_analyzer
  -> token_extractor
  -> source_search
  -> dossier_builder
  -> reasoning
  -> report_renderer
  -> Markdown 诊断报告
```

## 4. 核心输入

`sdwan_diagnose` 支持自然语言输入，也支持结构化报文字段。

最小输入：

```json
{
  "query": "10.220.21.241 到 10.220.21.236 不通，帮我分析是不是 OVS 或 FRR 路由问题"
}
```

推荐输入：

```json
{
  "query": "10.220.21.241 到 10.220.21.236 不通，帮我分析是不是 OVS 或 FRR 路由问题",
  "packet": {
    "src_ip": "10.220.21.241",
    "dst_ip": "10.220.21.236",
    "proto": "tcp",
    "dst_port": 443,
    "namespace": "ANPOSNS"
  },
  "context": {
    "source_root": "/path/to/controller",
    "focus": ["ovs", "frr", "route", "vrf"],
    "max_code_chunks": 12
  },
  "debug": false
}
```

## 5. 证据来源

v1 只使用确定性证据，不做本地向量或云端向量检索。

| 证据 | 来源 |
|------|------|
| 网络接口 | SQLite `interfaces` |
| IP rule | SQLite `rules` |
| 路由 | SQLite `routes` |
| 邻居 | SQLite `neighbors` |
| OVS bridge/port/flow/group/FDB/tunnel ARP | SQLite OVS 表 |
| FRR 输出 | SQLite `frr_info` |
| 转发路径 | `walker.ResolvePacket` + `walker.Walk` |
| 控制器源码 | `source_root` 下 Go 文件 |
| 源码结构 | Go AST 分块 |
| 源码命中 | `rg` token 字面匹配 |

## 6. 模块边界

建议新增目录：

```text
internal/agent/
├── state.go                 # AgentState、DiagnoseInput、Dossier、Report 等类型
├── nodes/
│   ├── normalize.go         # 输入归一化
│   ├── snapshot.go          # FPE DB 现场摘要
│   ├── path.go              # resolve_packet + get_path_segments 等价逻辑
│   ├── tokens.go            # token 提取
│   ├── source_search.go     # rg + AST 代码检索
│   ├── dossier.go           # 诊断卷宗组装
│   ├── reasoning.go         # LLM 推理或 prompt 生成
│   └── report.go            # Markdown 报告渲染
├── flow/
│   └── eino.go              # 唯一直接依赖 Eino 的流程编排层
├── source/
│   ├── ast.go               # Go AST 分块
│   ├── rg.go                # rg 执行与结果解析
│   └── chunk.go             # CodeChunk 类型与排序
└── mcp/
    └── diagnose.go          # sdwan_diagnose MCP tool 注册
```

依赖原则：

```text
nodes/source/mcp 可以被 Eino 调用
nodes/source/mcp 不直接依赖 Eino
flow/eino.go 是唯一引入 github.com/cloudwego/eino 的地方
```

## 7. v1 不做的事

| 能力 | v1 状态 | 原因 |
|------|---------|------|
| 向量检索 | 不做 | 降低依赖、性能和模型变量，先验证确定性检索价值 |
| 自动修改控制器源码 | 不做 | 第一版只给出修复建议，避免误改生产逻辑 |
| 完整跨包调用图 | 不做 | 先提直接调用关系，够用后再扩展 |
| 多轮自主行动 | 不做 | 第一版一次请求生成一份诊断报告 |
| 独立前端 UI | 不做 | 通过 MCP 接入 OpenCode Desktop/Cursor 等客户端 |

## 8. 文档索引

| 文档 | 内容 |
|------|------|
| [sdwan_diagnose_contract.md](./sdwan_diagnose_contract.md) | MCP 工具输入、输出、错误和 debug 契约 |
| [agent_flow.md](./agent_flow.md) | Eino 编排方式和节点职责 |
| [source_search.md](./source_search.md) | token 提取、rg 检索、AST 分块和排序 |
| [report_template.md](./report_template.md) | 最终 Markdown 报告结构和示例 |
| [implementation_plan.md](./implementation_plan.md) | 分阶段落地计划和验收标准 |
