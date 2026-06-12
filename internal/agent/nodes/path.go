package nodes

import (
	"context"

	"github.com/yangshuai/fpe/internal/agent"
	"github.com/yangshuai/fpe/internal/logs"
	"github.com/yangshuai/fpe/internal/walker"
)

func AnalyzePath(deps agent.Dependencies) func(ctx context.Context, state agent.AgentState) (agent.AgentState, error) {
	return func(ctx context.Context, state agent.AgentState) (agent.AgentState, error) {
		if !state.Normalized.Capabilities.CanDoPath {
			state.Warnings = append(state.Warnings, "path: skipped, src_ip or dst_ip missing")
			return state, nil
		}

		pkt := state.Normalized.Packet.Tuple
		logs.Infof("path_analyzer: src=%s dst=%s ns=%s", pkt.SrcIP, pkt.DstIP, pkt.Namespace)

		resolved := walker.ResolvePacket(pkt, deps.DB)
		result := walker.Walk(resolved, deps.DB)

		state.PathResult = &result

		if result.Status == "incomplete" {
			state.Warnings = append(state.Warnings, "path: forwarding path incomplete, cross-host or missing data")
		} else if result.Status == "uncertain" {
			state.Warnings = append(state.Warnings, "path: forwarding path has uncertain branches")
		} else if result.Status == "drop" {
			state.Warnings = append(state.Warnings, "path: packet dropped")
		}

		return state, nil
	}
}
