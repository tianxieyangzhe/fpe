# sdwan_diagnose MCP 工具契约

## 1. 定位

`sdwan_diagnose` 是 v1 唯一对外暴露的专家诊断入口。

它接收一个自然语言问题，并可选接收报文字段、源码目录和调试开关。内部会联动 FPE SQLite 快照、walker 路径计算和控制器源码检索，最终返回 Markdown 诊断报告。

## 2. 输入 Schema

```json
{
  "query": "string, required",
  "packet": {
    "src_ip": "string, optional",
    "dst_ip": "string, optional",
    "proto": "string, optional",
    "src_port": "number, optional",
    "dst_port": "number, optional",
    "namespace": "string, optional"
  },
  "context": {
    "db": "string, optional",
    "source_root": "string, optional",
    "focus": ["string, optional"],
    "max_code_chunks": "number, optional"
  },
  "debug": "boolean, optional"
}
```

## 3. 字段说明

| 字段 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `query` | 是 | 无 | 用户自然语言排障诉求 |
| `packet.src_ip` | 否 | 空 | 源 IP；与 `dst_ip` 同时存在时触发路径分析 |
| `packet.dst_ip` | 否 | 空 | 目的 IP；与 `src_ip` 同时存在时触发路径分析 |
| `packet.proto` | 否 | 空 | `tcp`、`udp`、`icmp` 等；为空时不强制猜测 |
| `packet.src_port` | 否 | 空 | 源端口，用于提高 OVS flow 匹配精度 |
| `packet.dst_port` | 否 | 空 | 目的端口，用于提高 OVS flow 匹配精度 |
| `packet.namespace` | 否 | 空 | 起始 namespace，例如 `ANPOSNS` |
| `context.db` | 否 | 服务启动 DB | 指定使用的 SQLite DB；v1 可先不开放动态切 DB |
| `context.source_root` | 否 | 空 | 控制器源码根目录；为空时只做 FPE 现场诊断 |
| `context.focus` | 否 | 空 | 诊断关注方向，例如 `ovs`、`frr`、`route`、`vrf`、`bgp`、`tunnel` |
| `context.max_code_chunks` | 否 | `12` | 最多注入多少个源码片段 |
| `debug` | 否 | `false` | 是否返回调试信息 |

## 4. 输入策略

### 4.1 最小输入

```json
{
  "query": "业务从 10.220.21.241 到 10.220.21.236 不通，帮我判断方向"
}
```

行为：

```text
不保证触发精确 path_analyzer
会从 query 里提取 IP、接口、VRF、OVS/FRR 关键词
会生成现场摘要和源码检索结果
报告中必须标记缺少结构化 packet 字段
```

### 4.2 推荐输入

```json
{
  "query": "10.220.21.241 到 10.220.21.236 不通，怀疑 OVS 或 FRR 路由异常",
  "packet": {
    "src_ip": "10.220.21.241",
    "dst_ip": "10.220.21.236",
    "proto": "tcp",
    "dst_port": 443,
    "namespace": "ANPOSNS"
  },
  "context": {
    "source_root": "/Users/example/controller",
    "focus": ["ovs", "frr", "route", "vrf"],
    "max_code_chunks": 12
  }
}
```

行为：

```text
触发 resolve_packet
触发 get_path_segments 等价路径计算
从路径结果和现场摘要中提取 token
使用 token 检索控制器源码
生成包含转发面和控制面证据的报告
```

## 5. 输出 Schema

MCP 返回文本内容，正文为 Markdown。

debug 为 `false`：

```json
{
  "content": [
    {
      "type": "text",
      "text": "# SD-WAN 诊断报告\n..."
    }
  ]
}
```

debug 为 `true` 时，Markdown 末尾追加调试附录：

```md
## 调试附录

### 输入归一化
...

### 提取 Token
...

### 命中源码片段
...

### FPE 证据摘要
...
```

## 6. 错误处理

| 场景 | 行为 |
|------|------|
| `query` 为空 | 返回 MCP tool error，提示必须提供 query |
| DB 不可读 | 返回 MCP tool error，包含 DB 路径和打开失败原因 |
| `source_root` 不存在 | 不阻断 FPE 现场诊断，在报告中标记源码检索跳过 |
| `rg` 不存在 | 降级为 AST 文件扫描或普通字符串扫描；报告 debug 中标记降级 |
| `src_ip/dst_ip` 缺一 | 不触发路径分析，在报告中列为不确定点 |
| walker 返回 incomplete | 报告中保留已知路径段，并把缺失对端/邻居/路由列入待确认 |
| 源码无命中 | 报告中明确写“未命中控制器源码证据”，不能强行猜测文件 |

## 7. 输出要求

报告必须满足：

```text
先给结论，再给证据
所有根因判断必须对应证据
源码判断必须带文件、函数、行号或代码片段摘要
不确定项必须单独列出
建议动作必须可执行
不能把推理过程伪装成事实
```

## 8. 示例

输入：

```json
{
  "query": "ANPOSNS 内 10.220.21.241 到 10.220.21.236 断流，怀疑 tunnel 重建后路由没有刷新",
  "packet": {
    "src_ip": "10.220.21.241",
    "dst_ip": "10.220.21.236",
    "proto": "tcp",
    "dst_port": 443,
    "namespace": "ANPOSNS"
  },
  "context": {
    "source_root": "/repo/controller",
    "focus": ["tunnel", "route", "vrf"],
    "max_code_chunks": 8
  },
  "debug": true
}
```

预期行为：

```text
1. 读取 ANPOSNS 相关接口、路由、规则、邻居、FRR、OVS 信息
2. 计算 10.220.21.241 -> 10.220.21.236 路径
3. 从路径中提取 table、vrf、接口、remote_ip、vni、flow/group 等 token
4. 在 /repo/controller 内检索 token
5. 通过 AST 扩展命中结果到完整函数/结构体
6. 生成六段式 Markdown 报告和 debug 附录
```
