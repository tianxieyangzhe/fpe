package nodes

import (
	"context"
	"fmt"

	"github.com/yangshuai/fpe/internal/agent"
	"github.com/yangshuai/fpe/internal/db"
	"github.com/yangshuai/fpe/internal/walker"
)

func BuildDossier(deps agent.Dependencies) func(ctx context.Context, state agent.AgentState) (agent.AgentState, error) {
	return func(ctx context.Context, state agent.AgentState) (agent.AgentState, error) {
		dossier := agent.InvestigationDossier{
			Query:      state.Input.Query,
			Snapshot:   state.Snapshot,
			PathResult: state.PathResult,
		}

		for _, c := range state.CodeChunks {
			dossier.CodeChunks = append(dossier.CodeChunks, c)
		}
		dossier.HasSourceCode = len(state.CodeChunks) > 0

		dossier.Evidence = buildEvidence(&state)
		dossier.UncertainItems = buildUncertainItems(&state)

		state.Dossier = dossier

		if state.Input.Debug {
			state.DebugInfo.DossierSummary = map[string]any{
				"evidence_count":   len(dossier.Evidence),
				"uncertain_count":  len(dossier.UncertainItems),
				"code_chunks":      len(dossier.CodeChunks),
				"has_source":       dossier.HasSourceCode,
			}
		}

		return state, nil
	}
}

func buildEvidence(state *agent.AgentState) []agent.EvidenceItem {
	var items []agent.EvidenceItem

	snap := state.Snapshot
	if len(snap.Interfaces) > 0 {
		items = append(items, agent.EvidenceItem{
			Category: "fpe_snapshot",
			Summary:  fmt.Sprintf("采集到 %d 个网络接口", len(snap.Interfaces)),
			Detail:   formatInterfaceSummary(snap.Interfaces),
		})
	}
	if len(snap.Routes) > 0 {
		items = append(items, agent.EvidenceItem{
			Category: "fpe_snapshot",
			Summary:  fmt.Sprintf("采集到 %d 条路由", len(snap.Routes)),
			Detail:   formatRouteSummary(snap.Routes),
		})
	}
	if len(snap.OvsBridges) > 0 {
		items = append(items, agent.EvidenceItem{
			Category: "fpe_snapshot",
			Summary:  fmt.Sprintf("采集到 %d 个 OVS bridge", len(snap.OvsBridges)),
			Detail:   formatOvsBridgeSummary(snap.OvsBridges),
		})
	}
	if len(snap.FrrInfo) > 0 {
		items = append(items, agent.EvidenceItem{
			Category: "fpe_snapshot",
			Summary:  fmt.Sprintf("采集到 %d 条 FRR 信息", len(snap.FrrInfo)),
			Detail:   "FRR 命令输出：show ip route, show bgp summary 等",
		})
	}

	if state.PathResult != nil {
		pr := state.PathResult
		items = append(items, agent.EvidenceItem{
			Category: "path",
			Summary:  fmt.Sprintf("转发路径计算：%d 条路径，状态 %s", len(pr.Leaves), pr.Status),
			Detail:   formatPathSummary(pr),
		})
	}

	if len(state.CodeChunks) > 0 {
		for i, c := range state.CodeChunks {
			if i >= 5 {
				break
			}
			items = append(items, agent.EvidenceItem{
				Category: "source",
				Summary:  fmt.Sprintf("源码命中：%s:%d %s", c.FilePath, c.StartLine, c.Name),
				Detail:   fmt.Sprintf("函数 %s，匹配 token: %v", c.Name, tokenValues(c.MatchedTokens)),
			})
		}
	}

	return items
}

func buildUncertainItems(state *agent.AgentState) []string {
	var items []string

	if !state.Normalized.Capabilities.CanDoPath {
		items = append(items, "路径分析未执行：缺少 packet.src_ip 或 packet.dst_ip")
	} else if state.PathResult != nil && state.PathResult.Status == "incomplete" {
		items = append(items, "转发路径不完整：可能存在跨主机或缺失的对端数据")
	}

	if !state.Normalized.Capabilities.CanSearchSource {
		items = append(items, "源码检索未执行：未提供 context.source_root")
	} else if !state.Dossier.HasSourceCode {
		items = append(items, "源码检索无命中：控制器源码中未找到相关 token")
	}

	items = append(items, state.Warnings...)
	items = append(items, state.Normalized.Capabilities.MissingFields...)
	return items
}

func formatInterfaceSummary(ifaces []db.Interface) string {
	if len(ifaces) == 0 {
		return ""
	}
	var names []string
	for i, iface := range ifaces {
		if i >= 5 {
			names = append(names, "...")
			break
		}
		names = append(names, iface.Name)
	}
	return fmt.Sprintf("接口列表：%v", names)
}

func formatRouteSummary(routes []db.Route) string {
	if len(routes) == 0 {
		return ""
	}
	var prefs []string
	for i, r := range routes {
		if i >= 5 {
			prefs = append(prefs, "...")
			break
		}
		prefs = append(prefs, r.Prefix)
	}
	return fmt.Sprintf("前缀列表：%v", prefs)
}

func formatOvsBridgeSummary(bridges []db.OvsBridge) string {
	if len(bridges) == 0 {
		return ""
	}
	var names []string
	for _, b := range bridges {
		names = append(names, b.Name)
	}
	return fmt.Sprintf("bridge 列表：%v", names)
}

func formatPathSummary(pr *walker.WalkResult) string {
	if pr == nil {
		return ""
	}
	return fmt.Sprintf("报文 %s -> %s，状态 %s，共 %d 条路径", pr.Packet.SrcIP, pr.Packet.DstIP, pr.Status, len(pr.Leaves))
}

func tokenValues(tokens []agent.SearchToken) []string {
	var vals []string
	for _, t := range tokens {
		vals = append(vals, t.Value)
	}
	return vals
}
