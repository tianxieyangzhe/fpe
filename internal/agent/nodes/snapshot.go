package nodes

import (
	"context"

	"github.com/yangshuai/fpe/internal/agent"
	"github.com/yangshuai/fpe/internal/logs"
)

func CollectSnapshot(deps agent.Dependencies) func(ctx context.Context, state agent.AgentState) (agent.AgentState, error) {
	return func(ctx context.Context, state agent.AgentState) (agent.AgentState, error) {
		var snap agent.SnapshotSummary

		namespace := ""
		if state.Normalized.Packet != nil {
			namespace = state.Normalized.Packet.Tuple.Namespace
		}

		ifaces, err := deps.DB.GetInterfaces(namespace)
		if err != nil {
			snap.Warnings = append(snap.Warnings, "interfaces query failed: "+err.Error())
			logs.Warnf("snapshot interfaces failed: %v", err)
		}
		snap.Interfaces = ifaces

		routes, err := deps.DB.GetRoutes(namespace, "main")
		if err != nil {
			snap.Warnings = append(snap.Warnings, "routes query failed: "+err.Error())
			logs.Warnf("snapshot routes failed: %v", err)
		}
		snap.Routes = routes

		if state.Normalized.Packet != nil {
			tuple := state.Normalized.Packet.Tuple
			if tuple.SrcIP != "" {
				if n, err := deps.DB.GetNeighbor(tuple.SrcIP); err == nil && n != nil {
					snap.Neighbors = append(snap.Neighbors, *n)
				}
			}
			if tuple.DstIP != "" {
				if n, err := deps.DB.GetNeighbor(tuple.DstIP); err == nil && n != nil {
					snap.Neighbors = append(snap.Neighbors, *n)
				}
			}
		}

		bridges, err := deps.DB.GetOvsBridges()
		if err != nil {
			snap.Warnings = append(snap.Warnings, "ovs bridges query failed: "+err.Error())
			logs.Warnf("snapshot ovs bridges failed: %v", err)
		}
		snap.OvsBridges = bridges

		for _, b := range bridges {
			flows, err := deps.DB.GetOvsFlows(b.Name, 0)
			if err != nil {
				snap.Warnings = append(snap.Warnings, "ovs flows query failed for "+b.Name+": "+err.Error())
				continue
			}
			if len(flows) > 20 {
				flows = flows[:20]
			}
			snap.OvsFlows = append(snap.OvsFlows, flows...)
		}

		frr, err := deps.DB.GetFrrInfo("")
		if err != nil {
			snap.Warnings = append(snap.Warnings, "frr info query failed: "+err.Error())
			logs.Warnf("snapshot frr failed: %v", err)
		}
		snap.FrrInfo = frr

		state.Snapshot = snap

		for _, w := range snap.Warnings {
			state.Warnings = append(state.Warnings, "snapshot: "+w)
		}

		return state, nil
	}
}
