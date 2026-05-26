# FPE V4 改进 — 实施清单

基于 `IMPROVEMENT_PLAN_V4.md` 的详细实施指南。

> 生成日期：2026-05-26  
> 当前任务编号：2-5（见下方）

---

## 任务映射表

| 任务 ID | 改进项 | 优先级 | 预计工作量 | 状态 |
|--------|--------|--------|-----------|------|
| #2 | 修复 analyze_flow ROUTE_NOT_FOUND bug | P0 | 2-3 天 | pending |
| #3 | 增强 rule_walk 输出 | P1 | 2-3 天 | pending |
| #4 | OVS 流表候选链优化 | P2 | 2 天 | pending |
| #5 | veth 转发验证支持 | P3 | 1-2 天 | pending |

---

## 任务 #2：修复 analyze_flow ROUTE_NOT_FOUND Bug

### 症状检查

**测试命令**：
```bash
# 在 ANPOSNS namespace 中测试跨 VRF 路由查找
fpe analyze \
  --src-ip 192.168.2.56 \
  --dst-ip 8.8.8.8 \
  --ingress-if rl3_vnet_1 \
  --namespace ANPOSNS \
  --vrf Vrf262147Ns \
  --protocol udp \
  --src-port 12345 \
  --dst-port 53
```

**当前错误表现**：
```json
{
  "risks": [
    {
      "code": "ROUTE_NOT_FOUND",
      "message": "No route found for destination 8.8.8.8"
    }
  ]
}
```

**预期修复后**：
```json
{
  "path": [...],  // 应包含 wan1-r 和 0.0.0.0/0 路由
  "risks": []     // 不应报告 ROUTE_NOT_FOUND
}
```

### 代码变更清单

#### 1. 修改 `src/fpe/analyzer/engine.py`

**新增方法**（在 `Analyzer` 类中添加）：

```python
async def _resolve_route_with_context(
    self,
    state: AnalysisState,
    dst_ip: str,
) -> RouteResult | None:
    """Find best route using the analysis context's namespace/VRF.
    
    This method ensures that route lookup respects the execution context's
    namespace and VRF settings, unlike the previous implementation which
    defaulted to root namespace.
    """
    logger.debug(
        f"Resolving route for {dst_ip} in "
        f"namespace={state.exec_ctx.namespace}, vrf={state.exec_ctx.vrf}"
    )
    
    # Collect all routes in the target namespace/VRF
    routes = get_route(
        executor=self._executor,
        namespace=state.exec_ctx.namespace,
        vrf=state.exec_ctx.vrf,
        table="",  # Query all tables (will be filtered by policy routing)
    )
    
    if not routes:
        logger.warning(f"No routes found in {state.exec_ctx.namespace}/{state.exec_ctx.vrf}")
        return None
    
    # Find the best matching prefix
    best = find_best_route(routes, dst_ip)
    
    if best:
        logger.debug(f"Found route: {best.prefix} via {best.next_hops}")
    else:
        logger.warning(f"No matching route for {dst_ip}")
    
    return best
```

**修改现有方法** — 查找并替换所有内部路由查找调用。

搜索 `find_best_route(` 或 `get_route(` 在分析阶段中的调用，替换为 `_resolve_route_with_context()`。

**在 `STATE_ANALYZING_L3` 阶段中修改**（大约在 L200-250）：

```python
# 旧代码（待替换）：
# routes = get_route(executor=self._executor)  # 默认 root namespace！
# best = find_best_route(routes, pkt.dst_ip)

# 新代码：
best = await self._resolve_route_with_context(state, pkt.dst_ip)
if not best:
    self._transition(state, STATE_INCOMPLETE, "route_analysis", f"No route for {pkt.dst_ip}")
    state.risks.append(
        RiskItem(
            code="ROUTE_NOT_FOUND",
            severity="high",
            message=f"No route found for destination {pkt.dst_ip} in {state.exec_ctx.namespace}/{state.exec_ctx.vrf}",
        )
    )
```

#### 2. 验证 `src/fpe/collectors/routes.py` 中的 namespace 传递

检查 `_collect_routes_single_scope()` 函数确保 namespace/vrf 参数正确传递到 `executor.run_in_context()`。

**预期**（应该已正确实现）：
```python
def _collect_routes_single_scope(
    executor: RemoteExecutor,
    table: str,
    namespace: str | None,
    vrf: str | None,
) -> list[RouteResult]:
    ns_for_route = namespace if namespace else None
    cmd = f"ip route show table {table}" if table else "ip route show"
    raw = executor.run_in_context(cmd, namespace=namespace, vrf=vrf)
    # ✓ namespace 和 vrf 都被正确传递
    ...
```

如果未传递，修改为：
```python
raw = executor.run_in_context(cmd, namespace=namespace, vrf=vrf)
```

### 单元测试

**新增文件** `tests/test_analyzer_vrf_routes.py`：

```python
"""Test cross-namespace and VRF route resolution."""

import pytest
from fpe.analyzer import Analyzer
from fpe.models import PacketContext, ExecContext, AnalysisState


@pytest.mark.asyncio
async def test_analyze_vrf_route_resolution():
    """Test that analyze_flow finds routes in VRF namespace."""
    analyzer = Analyzer(executor=mock_executor)
    
    # 模拟 ANPOSNS VRF 中的包
    result = await analyzer.analyze(
        packet=PacketContext(
            src_ip="192.168.2.56",
            dst_ip="8.8.8.8",
            ingress_if="rl3_vnet_1",
            protocol="udp",
            src_port=12345,
            dst_port=53,
        ),
        exec_ctx=ExecContext(
            namespace="ANPOSNS",
            vrf="Vrf262147Ns",
        ),
    )
    
    # 不应报告 ROUTE_NOT_FOUND
    route_not_found_risks = [r for r in result.risks if r.code == "ROUTE_NOT_FOUND"]
    assert not route_not_found_risks, "Should find routes in VRF"
    
    # 应包含 0.0.0.0/0 路由
    assert any("0.0.0.0/0" in str(node) for node in result.path), "Path should include default route"
```

**运行测试**：
```bash
cd /Users/yangshuai/Public/code/fpe
python -m pytest tests/test_analyzer_vrf_routes.py -v
```

### 集成验证

**对比测试**（analyze_flow vs get_route）：

```bash
# 终端 1：获取基准数据
curl -X POST http://localhost:8000/message \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "fpe.get_route",
      "arguments": {
        "dst_ip": "8.8.8.8",
        "namespace": "ANPOSNS",
        "vrf": "Vrf262147Ns",
        "best_only": true
      }
    }
  }' | jq '.result[0].effective_route'

# 预期输出：
# {
#   "prefix": "0.0.0.0/0",
#   "next_hops": [{"via": "10.220.21.254", "dev": "wan1-r"}]
# }

# 终端 2：测试 analyze_flow
curl -X POST http://localhost:8000/message \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {
      "name": "fpe.analyze_flow",
      "arguments": {
        "packet": {
          "src_ip": "192.168.2.56",
          "dst_ip": "8.8.8.8",
          "ingress_if": "rl3_vnet_1"
        },
        "exec_ctx": {
          "namespace": "ANPOSNS",
          "vrf": "Vrf262147Ns"
        }
      }
    }
  }' | jq '.result[0].path[] | select(.description | contains("0.0.0.0/0"))'

# 预期：不再报告 ROUTE_NOT_FOUND，且路径中包含正确的 0.0.0.0/0 路由信息
```

### 完成检查清单

- [ ] `_resolve_route_with_context()` 方法已添加到 `Analyzer` 类
- [ ] 所有内部路由查找调用已替换
- [ ] `executor.run_in_context()` 正确传递 namespace/vrf
- [ ] 单元测试编写并通过
- [ ] 集成测试确认 analyze_flow ≡ get_route
- [ ] 代码审查通过
- [ ] 回归测试：root namespace 路由查找正常工作
- [ ] 文档更新：IMPROVEMENT_PLAN_V4.md 中的说明已实现

---

## 任务 #3：增强 rule_walk 输出

### 症状检查

**测试命令**：
```bash
fpe analyze \
  --src-ip 192.168.2.56 \
  --dst-ip 8.8.8.8 \
  --ingress-if rl3_vnet_1 \
  --namespace ANPOSNS \
  --vrf Vrf262147Ns \
  --output json | jq '.decision_chain | length'
```

**当前表现**：`1`（仅一条规则）

**预期修复后**：`3`（完整 fallthrough 链）

### 代码变更清单

#### 1. 修改 `src/fpe/models/analysis.py`

**扩展 `AnalysisResult` 数据模型**：

```python
class AnalysisResult(BaseModel):
    """Complete analysis result with path, decisions, and risks."""
    
    packet: PacketContext
    path: list[PathNode] = []
    decision_chain: list[DecisionEvent] = []
    
    # ---- 新增字段（P1 改进） ----
    rule_walk: list[dict] = []
    """Complete rule walk with all fallthrough steps."""
    
    final_table: str = ""
    """The final routing table used after policy routing."""
    
    effective_route: RouteResult | None = None
    """The effective route found in final_table."""
    # ----
    
    risks: list[RiskItem] = []
    graph: FlowGraph | None = None
    mermaid: str = ""
```

#### 2. 修改 `src/fpe/analyzer/engine.py`

**新增方法**：

```python
async def _analyze_l3_rules(
    self,
    state: AnalysisState,
) -> list[dict]:
    """Perform complete policy routing rule walk.
    
    Returns the full rule_walk with all fallthrough steps and the
    final effective rule/table.
    """
    from fpe.analyzer.walks import build_rule_walk
    
    logger.debug(
        f"Analyzing L3 policy rules in "
        f"namespace={state.exec_ctx.namespace}, vrf={state.exec_ctx.vrf}"
    )
    
    rule_walk = await build_rule_walk(
        executor=self._executor,
        namespace=state.exec_ctx.namespace,
        vrf=state.exec_ctx.vrf,
        packet=state.packet,
    )
    
    if not rule_walk:
        logger.warning("Empty rule_walk returned")
        return []
    
    # Determine final table from last rule
    final_rule = rule_walk[-1] if rule_walk else {}
    final_table = final_rule.get("table", "main")
    
    logger.debug(f"Final table after rule walk: {final_table}")
    
    # Find the effective route in final table
    effective_route = await self._resolve_route_with_context(state, state.packet.dst_ip)
    
    return {
        "rule_walk": rule_walk,
        "final_table": final_table,
        "effective_route": effective_route,
    }
```

**在分析状态机中调用**（在 `STATE_ANALYZING_L3` 阶段）：

```python
# 新增代码块
elif state.flow_state == STATE_ANALYZING_L3:
    logger.debug("Entering L3 analysis phase")
    
    # 执行完整的规则链分析
    l3_result = await self._analyze_l3_rules(state)
    state.rule_walk = l3_result.get("rule_walk", [])
    state.final_table = l3_result.get("final_table", "main")
    state.effective_route = l3_result.get("effective_route")
    
    # 构建决策链
    for i, rule_entry in enumerate(state.rule_walk):
        decision = DecisionEvent(
            event_type="rule_lookup",
            step=i,
            rule_info=rule_entry,
            verdict="PASS" if not rule_entry.get("terminates_lookup") else "TERMINATE",
        )
        state.decision_chain.append(decision)
    
    self._transition(state, STATE_COMPLETED, "l3_analysis", "L3 rules analyzed")
```

**在 `_build_result()` 方法中**：

```python
def _build_result(self, state: AnalysisState) -> AnalysisResult:
    """Build final analysis result with all collected information."""
    return AnalysisResult(
        packet=state.packet,
        path=state.path,
        decision_chain=state.decision_chain,
        
        # 新增字段
        rule_walk=state.rule_walk,
        final_table=state.final_table,
        effective_route=state.effective_route,
        
        risks=state.risks,
        graph=state.flow_graph,
        mermaid=self._render_mermaid(state),
    )
```

#### 3. 修改 `src/fpe/renderer/output.py`

**增强 Mermaid 图生成**以包含规则链：

```python
def _render_rule_walk_chain(self, rule_walk: list[dict]) -> str:
    """Render policy routing rule walk as Mermaid flowchart."""
    
    if not rule_walk:
        return ""
    
    nodes = []
    edges = []
    
    for i, rule in enumerate(rule_walk):
        priority = rule.get("priority", "?")
        table = rule.get("table", "?")
        result = rule.get("lookup_result", "?")
        terminates = rule.get("terminates_lookup", False)
        
        node_id = f"rule_{i}"
        label = f"rule:{priority}→{table}\n{result}"
        
        if terminates:
            label += " ✓"
        
        nodes.append(f'{node_id}["{label}"]')
        
        if i > 0:
            edges.append(f"rule_{i-1} -->|fallthrough| {node_id}")
    
    return "\n    ".join(nodes + edges)
```

在完整的 Mermaid 图中集成规则链：

```python
def render_mermaid(self, state: AnalysisState) -> str:
    """Render complete analysis path as Mermaid diagram."""
    
    chart = "flowchart LR\n"
    
    # ... 现有的入口、OVS、出口节点 ...
    
    # 添加规则链部分
    if state.rule_walk:
        chart += "    %% Policy Routing Rule Walk\n"
        chart += self._render_rule_walk_chain(state.rule_walk)
    
    # ... 连接规则链到路由选择 ...
    
    return chart
```

### 单元测试

**新增文件** `tests/test_analyzer_rule_walk.py`：

```python
"""Test complete rule walk output in analyze_flow."""

import pytest
from fpe.analyzer import Analyzer
from fpe.models import PacketContext, ExecContext


@pytest.mark.asyncio
async def test_analyze_complete_rule_walk():
    """Test that analyze_flow returns complete rule_walk."""
    analyzer = Analyzer(executor=mock_executor)
    
    result = await analyzer.analyze(
        packet=PacketContext(
            src_ip="192.168.2.56",
            dst_ip="8.8.8.8",
            ingress_if="rl3_vnet_1",
        ),
        exec_ctx=ExecContext(
            namespace="ANPOSNS",
            vrf="Vrf262147Ns",
        ),
    )
    
    # 规则链应包含至少 3 步
    assert len(result.rule_walk) >= 3, "Expected at least 3 rules in fallthrough chain"
    
    # 最后一条规则应 terminate
    assert result.rule_walk[-1]["terminates_lookup"], "Last rule should terminate"
    
    # final_table 应正确设置
    assert result.final_table == "main", "Final table should be 'main'"
    
    # effective_route 应存在
    assert result.effective_route is not None, "Should find effective route"
    assert result.effective_route.prefix == "0.0.0.0/0", "Expected default route"
```

### 完成检查清单

- [ ] `AnalysisResult` 数据模型已扩展
- [ ] `_analyze_l3_rules()` 方法已添加
- [ ] 状态机中的 L3 阶段已修改以调用新方法
- [ ] `_build_result()` 方法已更新以包含新字段
- [ ] Mermaid 渲染逻辑已增强
- [ ] 单元测试编写并通过
- [ ] 集成测试确认规则链完整
- [ ] 文档更新

---

## 任务 #4：OVS 流表候选链优化

（详见 IMPROVEMENT_PLAN_V4.md 第 4 章）

### 关键代码变更

**文件**：`src/fpe/analyzer/walks.py`

增强 `build_candidate_flow_walk()` 函数，返回：
- `table_walk`：完整的表遍历链
- `non_match_reasons`：拒绝的流表和原因
- `confidence_level`：EXACT | CANDIDATE | UNKNOWN

**文件**：`src/fpe/models/analysis.py`

新增 `OvsFlowWalk` 模型，扩展 `AnalysisResult.ovs_flow_walk` 字段

---

## 任务 #5：veth 转发验证支持

（详见 IMPROVEMENT_PLAN_V4.md 第 5 章）

### 关键代码变更

**文件**：`src/fpe/collectors/link.py`

新增 `verify_veth_pair()` 函数

**文件**：`src/fpe/models/context.py`

新增 `VethTransition` 模型，扩展 `PathNode` 模型

---

## 快速参考：文件变更总结

| 文件 | 变更内容 | 任务 |
|------|--------|------|
| `src/fpe/analyzer/engine.py` | 新增 `_resolve_route_with_context()`, `_analyze_l3_rules()` | #2, #3 |
| `src/fpe/models/analysis.py` | 扩展 `AnalysisResult`, 新增 `OvsFlowWalk` | #2, #3, #4 |
| `src/fpe/models/context.py` | 扩展 `PathNode`, 新增 `VethTransition` | #5 |
| `src/fpe/analyzer/walks.py` | 增强 `build_candidate_flow_walk()` | #4 |
| `src/fpe/collectors/routes.py` | 验证 namespace/vrf 传递 | #2 |
| `src/fpe/collectors/link.py` | 新增 `verify_veth_pair()` | #5 |
| `src/fpe/renderer/output.py` | 增强 Mermaid 图生成 | #3, #4, #5 |
| `tests/test_*.py` | 新增单元测试 | #2-#5 |

---

## 故障排查指南

### 问题 1：_resolve_route_with_context() 仍返回 None

**检查**：
1. `executor.run_in_context()` 是否正确传递 namespace/vrf
2. 目标 namespace/vrf 中是否真的存在路由
3. 日志输出（启用 DEBUG 日志）

**命令**：
```bash
# 手动验证路由存在
ip netns exec ANPOSNS ip route show table main | grep 8.8.8.8
# 应该看到 0.0.0.0/0 via 10.220.21.254 dev wan1-r
```

### 问题 2：rule_walk 为空

**检查**：
1. `build_rule_walk()` 是否正确调用
2. `get_rules()` 采集器是否返回数据
3. namespace/vrf 上下文是否正确

### 问题 3：Mermaid 图不显示规则链

**检查**：
1. `_render_rule_walk_chain()` 是否正确生成节点和边
2. 完整图表是否包含规则链部分（搜索 "Policy Routing Rule Walk"）

---

## 下一步

1. 选择一项任务开始实施（推荐从 #2 开始）
2. 按照代码变更清单逐项实施
3. 编写单元测试并验证
4. 进行集成测试
5. 提交 PR/commit
6. 进行回归测试
7. 更新文档

---

## 参考链接

- 改进计划：`IMPROVEMENT_PLAN_V4.md`
- v3 分析：`fpe-flow-analysis-v3.md`
- 项目 README：`README.md`
