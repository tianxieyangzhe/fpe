package flow

import (
	"context"

	"github.com/cloudwego/eino/compose"
	"github.com/yangshuai/fpe/internal/agent"
	"github.com/yangshuai/fpe/internal/agent/nodes"
)

// Build compiles the diagnostic pipeline into an Eino Runnable.
// Graph: normalize -> snapshot -> path -> tokens -> source_search -> dossier -> reasoning -> report
func Build(ctx context.Context, deps agent.Dependencies) (compose.Runnable[agent.AgentState, agent.AgentState], error) {
	g := compose.NewGraph[agent.AgentState, agent.AgentState]()

	_ = g.AddLambdaNode("normalize_request", compose.InvokableLambda(nodes.NormalizeRequest(deps)))
	_ = g.AddLambdaNode("snapshot_collector", compose.InvokableLambda(nodes.CollectSnapshot(deps)))
	_ = g.AddLambdaNode("path_analyzer", compose.InvokableLambda(nodes.AnalyzePath(deps)))
	_ = g.AddLambdaNode("token_extractor", compose.InvokableLambda(nodes.ExtractTokens(deps)))
	_ = g.AddLambdaNode("source_search", compose.InvokableLambda(nodes.SearchSource(deps)))
	_ = g.AddLambdaNode("dossier_builder", compose.InvokableLambda(nodes.BuildDossier(deps)))
	_ = g.AddLambdaNode("reasoning", compose.InvokableLambda(nodes.Reason(deps)))
	_ = g.AddLambdaNode("report_renderer", compose.InvokableLambda(nodes.RenderReport(deps)))

	_ = g.AddEdge(compose.START, "normalize_request")
	_ = g.AddEdge("normalize_request", "snapshot_collector")
	_ = g.AddEdge("snapshot_collector", "path_analyzer")
	_ = g.AddEdge("path_analyzer", "token_extractor")
	_ = g.AddEdge("token_extractor", "source_search")
	_ = g.AddEdge("source_search", "dossier_builder")
	_ = g.AddEdge("dossier_builder", "reasoning")
	_ = g.AddEdge("reasoning", "report_renderer")
	_ = g.AddEdge("report_renderer", compose.END)

	return g.Compile(ctx)
}
