package nodes

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/yangshuai/fpe/internal/agent"
)

func RenderReport(deps agent.Dependencies) func(ctx context.Context, state agent.AgentState) (agent.AgentState, error) {
	return func(ctx context.Context, state agent.AgentState) (agent.AgentState, error) {
		var sb strings.Builder

		sb.WriteString("# SD-WAN 诊断报告\n\n")

		renderConclusion(&sb, state)
		renderEvidence(&sb, state)
		renderPath(&sb, state)
		renderControlPlane(&sb, state)
		renderRootCause(&sb, state)
		renderActions(&sb, state)

		if state.Input.Debug {
			renderDebug(&sb, state, deps)
		}

		state.ReportMarkdown = sb.String()
		return state, nil
	}
}

func renderConclusion(sb *strings.Builder, state agent.AgentState) {
	sb.WriteString("## 1. 结论\n\n")

	analysis := state.Analysis
	if strings.HasPrefix(analysis, "PRIMARY: ") {
		idx := strings.Index(analysis, "\n")
		if idx > 0 {
			sb.WriteString(analysis[len("PRIMARY: "):idx])
			sb.WriteString("\n\n")
		}
	} else if analysis != "" {
		sb.WriteString(analysis)
		sb.WriteString("\n\n")
	}

	if state.Input.Packet == nil || (state.Input.Packet.SrcIP == "" || state.Input.Packet.DstIP == "") {
		sb.WriteString("输入缺少结构化 packet 字段，建议提供 src_ip 和 dst_ip 以获得精确路径分析。\n\n")
	}
}

func renderEvidence(sb *strings.Builder, state agent.AgentState) {
	sb.WriteString("## 2. 关键证据\n\n")

	categories := map[string]string{
		"fpe_snapshot": "FPE 现场证据",
		"path":         "路径计算证据",
		"source":       "源码证据",
	}

	for _, cat := range []string{"fpe_snapshot", "path", "source"} {
		label := categories[cat]
		found := false
		for _, e := range state.Dossier.Evidence {
			if e.Category == cat {
				if !found {
					sb.WriteString(fmt.Sprintf("- %s：%s\n", label, e.Summary))
					found = true
				}
			}
		}
		if !found {
			if cat == "path" && !state.Normalized.Capabilities.CanDoPath {
				sb.WriteString(fmt.Sprintf("- %s：未执行精确路径计算，因为输入缺少 src_ip/dst_ip\n", label))
			} else if cat == "source" && !state.Normalized.Capabilities.CanSearchSource {
				sb.WriteString(fmt.Sprintf("- %s：未执行源码检索，因为未提供 source_root\n", label))
			} else if cat == "source" && !state.Dossier.HasSourceCode {
				sb.WriteString(fmt.Sprintf("- %s：已搜索控制器源码，但未命中与当前 token 直接相关的函数或结构体\n", label))
			}
		}
	}

	if len(state.Dossier.UncertainItems) > 0 {
		sb.WriteString("- 不确定点：\n")
		for _, item := range state.Dossier.UncertainItems {
			sb.WriteString(fmt.Sprintf("  - %s\n", item))
		}
	}

	sb.WriteString("\n")
}

func renderPath(sb *strings.Builder, state agent.AgentState) {
	sb.WriteString("## 3. 转发路径\n\n")

	if state.PathResult == nil {
		sb.WriteString("未执行精确路径计算，因为输入缺少 `packet.src_ip` 或 `packet.dst_ip`。\n\n")
		return
	}

	pr := state.PathResult
	pkt := pr.Packet

	if len(pr.Leaves) == 0 {
		sb.WriteString(fmt.Sprintf("`%s` -> **无匹配路径**\n\n", pkt.SrcIP))
		return
	}

	if len(pr.Leaves) > 1 {
		sb.WriteString(fmt.Sprintf("共 %d 条可能路径：\n\n", len(pr.Leaves)))
	}

	for i, leaf := range pr.Leaves {
		if len(pr.Leaves) > 1 {
			sb.WriteString(fmt.Sprintf("**路径 %c** (outcome=%s, certainty=%s)：\n\n", 'A'+i, leaf.Outcome, leaf.Certainty))
		}

		for _, seg := range leaf.Segments {
			nsLabel := seg.Namespace
			if nsLabel == "" {
				nsLabel = "root"
			}
			sb.WriteString(fmt.Sprintf("`%s`\n", nsLabel))

			for _, hop := range seg.Hops {
				certainty := ""
				if hop.Certainty == "uncertain" {
					certainty = " [不确定]"
				}
				sb.WriteString(fmt.Sprintf("-> %s: %s -> %s%s\n", hop.Type, hop.Match, hop.Action, certainty))
			}

			egressPeer := ""
			if seg.EgressPeer != nil {
				if seg.EgressPeer.RemoteIP != "" {
					egressPeer = fmt.Sprintf(" remote=%s", seg.EgressPeer.RemoteIP)
				}
				if seg.EgressPeer.VNI != 0 {
					egressPeer += fmt.Sprintf(" vni=%d", seg.EgressPeer.VNI)
				}
			}
			sb.WriteString(fmt.Sprintf("-> egress: %s (%s)%s\n\n", seg.Egress, seg.EgressType, egressPeer))
		}
	}
}

func renderControlPlane(sb *strings.Builder, state agent.AgentState) {
	sb.WriteString("## 4. 控制面关联\n\n")

	if !state.Normalized.Capabilities.CanSearchSource {
		sb.WriteString("本次未提供 `source_root`，因此没有执行控制器源码关联。\n\n")
		return
	}

	if !state.Dossier.HasSourceCode {
		sb.WriteString("已搜索控制器源码，但未命中与当前 token 直接相关的函数或结构体；根因判断只基于 FPE 现场证据。\n\n")
		return
	}

	sb.WriteString("相关代码集中在：\n\n")
	for _, c := range state.CodeChunks {
		if c.Name != "" {
			sb.WriteString(fmt.Sprintf("- `%s:%d` `%s`", c.FilePath, c.StartLine, c.Name))
		} else {
			sb.WriteString(fmt.Sprintf("- `%s:%d-%d`", c.FilePath, c.StartLine, c.EndLine))
		}
		if c.Receiver != "" {
			sb.WriteString(fmt.Sprintf(" (receiver: %s)", c.Receiver))
		}
		if len(c.MatchedTokens) > 0 {
			vals := make([]string, len(c.MatchedTokens))
			for i, t := range c.MatchedTokens {
				vals[i] = t.Value
			}
			sb.WriteString(fmt.Sprintf(" [tokens: %s]", strings.Join(vals, ", ")))
		}
		sb.WriteString("\n")
	}
	sb.WriteString("\n")
}

func renderRootCause(sb *strings.Builder, state agent.AgentState) {
	sb.WriteString("## 5. 根因判断\n\n")

	hypotheses := buildHypotheses(state)
	if len(hypotheses) == 0 {
		sb.WriteString("未能基于当前证据形成明确根因判断，请参考建议动作进一步排查。\n\n")
		return
	}

	for i, h := range hypotheses {
		sb.WriteString(fmt.Sprintf("%d. %s。概率：%s。\n", i+1, h.Title, h.Probability))
		if len(h.Evidence) > 0 {
			for _, e := range h.Evidence {
				sb.WriteString(fmt.Sprintf("   证据：%s\n", e))
			}
		}
		if len(h.CounterEvidence) > 0 {
			for _, ce := range h.CounterEvidence {
				sb.WriteString(fmt.Sprintf("   反证/不确定点：%s\n", ce))
			}
		}
		sb.WriteString("\n")
	}
}

type hypothesis struct {
	Title           string
	Probability     string
	Evidence        []string
	CounterEvidence []string
}

func buildHypotheses(state agent.AgentState) []hypothesis {
	var hyps []hypothesis

	if state.PathResult != nil {
		pr := state.PathResult
		switch pr.Status {
		case "incomplete":
			hyps = append(hyps, hypothesis{
				Title:       "转发路径存在断点，可能因对端隧道信息缺失或跨主机数据不完整",
				Probability: "中",
				Evidence: []string{
					fmt.Sprintf("路径状态为 %s，存在未解析的 hop", pr.Status),
					fmt.Sprintf("报文 %s -> %s 未到达最终 destination", pr.Packet.SrcIP, pr.Packet.DstIP),
				},
				CounterEvidence: []string{"未确认对端主机的网络状态，需补充采集"},
			})
		case "drop":
			hyps = append(hyps, hypothesis{
				Title:       "OVS flow 或路由配置导致报文被丢弃",
				Probability: "中高",
				Evidence: []string{
					"路径结果中存在 drop 节点",
					"需要检查对应 OVS flow table 和路由条目",
				},
				CounterEvidence: []string{"drop 可能为预期行为（如 ACL 规则）"},
			})
		}
	}

	if len(state.CodeChunks) > 0 {
		for _, c := range state.CodeChunks {
			if c.Score >= 100 {
				hyps = append(hyps, hypothesis{
					Title:       fmt.Sprintf("控制器代码 `%s` 可能与当前网络状态相关", c.Name),
					Probability: "中",
					Evidence: []string{
						fmt.Sprintf("源码 %s:%d 匹配 token，score=%d", c.FilePath, c.StartLine, c.Score),
					},
					CounterEvidence: []string{"需要进一步确认代码逻辑与网络事件的时序关系"},
				})
				break
			}
		}
	}

	if len(hyps) == 0 {
		hyps = append(hyps, hypothesis{
			Title:       "信息不足，建议提供更多数据后重新分析",
			Probability: "低",
			Evidence:    []string{"当前采集数据不足以形成明确根因判断"},
			CounterEvidence: []string{},
		})
	}

	return hyps
}

func renderActions(sb *strings.Builder, state agent.AgentState) {
	sb.WriteString("## 6. 建议动作\n\n")

	sb.WriteString("- 立即验证：\n")

	ns := ""
	if state.Normalized.Packet != nil {
		ns = state.Normalized.Packet.Tuple.Namespace
	}

	// Generate commands based on namespace and detected issues
	if ns != "" {
		nsCmd := fmt.Sprintf("ip netns exec %s", ns)
		sb.WriteString(fmt.Sprintf("  ```bash\n  %s ip route show table all\n  ```\n", nsCmd))
		sb.WriteString(fmt.Sprintf("  ```bash\n  %s ip neigh show\n  ```\n", nsCmd))
	} else {
		sb.WriteString("  ```bash\n  ip route show table all\n  ```\n")
		sb.WriteString("  ```bash\n  ip neigh show\n  ```\n")
	}

	// OVS commands
	if len(state.Snapshot.OvsBridges) > 0 {
		for _, b := range state.Snapshot.OvsBridges {
			sb.WriteString(fmt.Sprintf("  ```bash\n  ovs-ofctl dump-flows %s\n  ```\n", b.Name))
		}
	}

	// FRR commands (always in ANPOSNS)
	if ns == "ANPOSNS" || ns == "" {
		sb.WriteString(fmt.Sprintf("  ```bash\n  %s /anpos/frr/bin/vtysh -c \"show bgp ipv4 unicast\"\n  ```\n", func() string {
			if ns == "ANPOSNS" {
				return "ip netns exec ANPOSNS"
			}
			return "ip netns exec ANPOSNS"
		}()))
	}

	sb.WriteString("\n")

	// Code fix direction
	if len(state.CodeChunks) > 0 {
		sb.WriteString("- 代码修复方向：\n")
		for i, c := range state.CodeChunks {
			if i >= 3 {
				break
			}
			if c.Name != "" {
				sb.WriteString(fmt.Sprintf("  检查 `%s:%d` `%s` 的调用逻辑，", c.FilePath, c.StartLine, c.Name))
				if len(c.Callees) > 0 {
					sb.WriteString(fmt.Sprintf("特别关注其对 `%s` 的调用。", strings.Join(c.Callees[:minInt(3, len(c.Callees))], "`, `")))
				} else {
					sb.WriteString("确认其触发条件和错误处理。")
				}
				sb.WriteString("\n")
			}
		}
		sb.WriteString("\n")
	}

	if state.PathResult != nil && state.PathResult.Status == "incomplete" {
		sb.WriteString("- 临时恢复：建议先在目标机器上执行 `fpe collect` 补充对端现场数据后重新分析。\n\n")
	}
}

func minInt(a, b int) int {
	if a < b {
		return a
	}
	return b
}

func renderDebug(sb *strings.Builder, state agent.AgentState, deps agent.Dependencies) {
	sb.WriteString("## 调试附录\n\n")

	sb.WriteString("### 输入归一化\n\n```json\n")
	if state.DebugInfo.NormalizedInput != nil {
		sb.WriteString(fmt.Sprintf("%+v", state.DebugInfo.NormalizedInput))
	}
	sb.WriteString("\n```\n\n")

	sb.WriteString("### 提取 Token\n\n")
	sb.WriteString("| Token | Type | Source | Weight |\n")
	sb.WriteString("|-------|------|--------|--------|\n")
	for _, t := range state.DebugInfo.Tokens {
		sb.WriteString(fmt.Sprintf("| `%s` | %s | %s | %d |\n", t.Value, t.Type, t.Source, t.Weight))
	}
	sb.WriteString("\n")

	if len(state.DebugInfo.CodeChunkSummary) > 0 {
		sb.WriteString("### 命中源码片段\n\n")
		sb.WriteString("| File | Symbol | Lines | Score |\n")
		sb.WriteString("|------|--------|-------|-------|\n")
		for _, s := range state.DebugInfo.CodeChunkSummary {
			sb.WriteString(fmt.Sprintf("| `%s` | `%s` | `%s` | `%d` |\n", s.File, s.Symbol, s.Lines, s.Score))
		}
		sb.WriteString("\n")
	}

	sb.WriteString("### FPE 证据摘要\n\n")
	sb.WriteString(fmt.Sprintf("- Interfaces: %d\n", len(state.Snapshot.Interfaces)))
	sb.WriteString(fmt.Sprintf("- Routes: %d\n", len(state.Snapshot.Routes)))
	sb.WriteString(fmt.Sprintf("- Neighbors: %d\n", len(state.Snapshot.Neighbors)))
	sb.WriteString(fmt.Sprintf("- OVS Bridges: %d\n", len(state.Snapshot.OvsBridges)))
	sb.WriteString(fmt.Sprintf("- OVS Flows: %d\n", len(state.Snapshot.OvsFlows)))
	sb.WriteString(fmt.Sprintf("- FRR Info: %d\n", len(state.Snapshot.FrrInfo)))
	if state.PathResult != nil {
		sb.WriteString(fmt.Sprintf("- Path Status: %s (%d leaves)\n", state.PathResult.Status, len(state.PathResult.Leaves)))
	}
	sb.WriteString(fmt.Sprintf("- Warnings: %d\n", len(state.Warnings)))
	for _, w := range state.Warnings {
		sb.WriteString(fmt.Sprintf("  - %s\n", w))
	}

	now := time.Now()
	if deps.Now != nil {
		now = deps.Now()
	}
	sb.WriteString(fmt.Sprintf("\n报告生成时间：%s\n", now.Format(time.RFC3339)))
}
