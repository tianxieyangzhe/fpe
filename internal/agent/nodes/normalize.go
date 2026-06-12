package nodes

import (
	"context"
	"fmt"
	"os"

	"github.com/yangshuai/fpe/internal/agent"
)

func NormalizeRequest(deps agent.Dependencies) func(ctx context.Context, state agent.AgentState) (agent.AgentState, error) {
	return func(ctx context.Context, state agent.AgentState) (agent.AgentState, error) {
		if state.Input.Query == "" {
			return state, fmt.Errorf("query is required")
		}

		norm := agent.NormalizedRequest{
			Query:  state.Input.Query,
			Debug:  state.Input.Debug,
		}

		if state.Input.Context != nil {
			norm.SourceRoot = state.Input.Context.SourceRoot
			norm.Focus = state.Input.Context.Focus
			norm.MaxCodeChunks = state.Input.Context.MaxCodeChunks
		}
		if norm.SourceRoot == "" {
			norm.SourceRoot = os.Getenv("FPE_SOURCE_ROOT")
		}
		if norm.MaxCodeChunks <= 0 {
			norm.MaxCodeChunks = 12
		}

		norm.Capabilities.CanSearchSource = norm.SourceRoot != ""

		if state.Input.Packet != nil {
			tuple := agent.PacketInputToTuple(state.Input.Packet)
			norm.Packet = &agent.WalkerTuple{Resolved: true, Tuple: tuple}
			if tuple.SrcIP != "" && tuple.DstIP != "" {
				norm.Capabilities.CanDoPath = true
			}
		}

		if !norm.Capabilities.CanDoPath {
			norm.Capabilities.MissingFields = append(norm.Capabilities.MissingFields, "packet.src_ip or packet.dst_ip")
		}
		if !norm.Capabilities.CanSearchSource {
			norm.Capabilities.MissingFields = append(norm.Capabilities.MissingFields, "context.source_root")
		}

		state.Normalized = norm

		if state.Input.Debug {
			state.DebugInfo.NormalizedInput = norm
		}

		return state, nil
	}
}
