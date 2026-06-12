package nodes

import (
	"context"
	"fmt"
	"strings"

	"github.com/yangshuai/fpe/internal/agent"
)

func Reason(deps agent.Dependencies) func(ctx context.Context, state agent.AgentState) (agent.AgentState, error) {
	return func(ctx context.Context, state agent.AgentState) (agent.AgentState, error) {
		var analysis strings.Builder

		// Template-based reasoning for v1
		primary := reasonPrimary(&state)
		observations := reasonObservations(&state)
		uncertainties := reasonUncertainties(&state)

		analysis.WriteString("PRIMARY: ")
		analysis.WriteString(primary)
		analysis.WriteString("\n\nOBSERVATIONS:\n")
		for _, o := range observations {
			analysis.WriteString("- ")
			analysis.WriteString(o)
			analysis.WriteString("\n")
		}
		analysis.WriteString("\nUNCERTAINTIES:\n")
		for _, u := range uncertainties {
			analysis.WriteString("- ")
			analysis.WriteString(u)
			analysis.WriteString("\n")
		}

		state.Analysis = analysis.String()
		return state, nil
	}
}

func reasonPrimary(state *agent.AgentState) string {
	if state.PathResult != nil {
		switch state.PathResult.Status {
		case "complete":
			return fmt.Sprintf("转发路径完整，%s -> %s 通信可达。置信度：高", state.PathResult.Packet.SrcIP, state.PathResult.Packet.DstIP)
		case "drop":
			return fmt.Sprintf("转发路径存在 drop 点，%s -> %s 可能因 OVS flow drop 或路由不可达导致丢包。置信度：中高", state.PathResult.Packet.SrcIP, state.PathResult.Packet.DstIP)
		case "incomplete":
			return fmt.Sprintf("转发路径不完整，%s -> %s 在路径计算中出现断点，可能涉及跨主机隧道或对端信息缺失。置信度：中", state.PathResult.Packet.SrcIP, state.PathResult.Packet.DstIP)
		default:
			return fmt.Sprintf("转发路径存在不确定分支。置信度：低")
		}
	}

	// No path analysis done
	if len(state.Snapshot.Interfaces) > 0 || len(state.Snapshot.Routes) > 0 {
		return "未执行精确路径分析，但已采集网络现场数据用于初步诊断。如需路径分析，请提供完整的 src_ip/dst_ip。置信度：低"
	}

	return "缺少网络数据，无法形成有效诊断。请先运行 fpe collect 采集现场数据。置信度：低"
}

func reasonObservations(state *agent.AgentState) []string {
	var obs []string

	snap := state.Snapshot
	if len(snap.Interfaces) > 0 {
		obs = append(obs, fmt.Sprintf("采集到 %d 个网络接口，可用于分析拓扑结构", len(snap.Interfaces)))
	}
	if len(snap.Routes) > 0 {
		count := 0
		for _, r := range snap.Routes {
			if r.Protocol != "" {
				count++
			}
		}
		if count > 0 {
			obs = append(obs, fmt.Sprintf("存在 %d 条非 kernel 路由，可能涉及动态路由协议", count))
		}
	}
	if len(snap.OvsBridges) > 0 {
		bridgeNames := make([]string, len(snap.OvsBridges))
		for i, b := range snap.OvsBridges {
			bridgeNames[i] = b.Name
		}
		obs = append(obs, fmt.Sprintf("OVS bridge: %s，共 %d 条 flow", strings.Join(bridgeNames, ", "), len(snap.OvsFlows)))
	}

	if state.PathResult != nil {
		pr := state.PathResult
		for _, leaf := range pr.Leaves {
			for _, seg := range leaf.Segments {
				if seg.EgressType == "drop" {
					obs = append(obs, fmt.Sprintf("路径在 namespace=%s 处 drop", seg.Namespace))
				}
				if seg.EgressType == "vxlan" || seg.EgressType == "geneve" {
					if seg.EgressPeer != nil {
						obs = append(obs, fmt.Sprintf("隧道出口: %s remote=%s", seg.EgressType, seg.EgressPeer.RemoteIP))
					}
				}
			}
		}
	}

	if len(state.CodeChunks) > 0 {
		for i, c := range state.CodeChunks {
			if i >= 3 {
				break
			}
			obs = append(obs, fmt.Sprintf("控制器源码 %s:%d 函数 %s 与 token 相关", c.FilePath, c.StartLine, c.Name))
		}
	}

	return obs
}

func reasonUncertainties(state *agent.AgentState) []string {
	return state.Dossier.UncertainItems
}
