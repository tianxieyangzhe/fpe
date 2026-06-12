package mcp

import (
	"context"
	"encoding/json"
	"time"

	"github.com/modelcontextprotocol/go-sdk/mcp"
	"github.com/yangshuai/fpe/internal/agent"
	"github.com/yangshuai/fpe/internal/agent/flow"
	"github.com/yangshuai/fpe/internal/db"
	"github.com/yangshuai/fpe/internal/logs"
)

func addSDWANDiagnose(s *mcp.Server, d *db.DB) {
	mcp.AddTool(s, &mcp.Tool{
		Name: "sdwan_diagnose",
		Description: "Run SD-WAN diagnostic analysis: collect FPE network state, " +
			"compute forwarding paths, search controller source code, " +
			"and produce a six-section Markdown diagnostic report.",
	}, func(ctx context.Context, req *mcp.CallToolRequest, in sdwanDiagnoseInput) (*mcp.CallToolResult, any, error) {
		if in.Query == "" {
			return nil, nil, fmtDiagnoseError("query is required")
		}

		input := convertDiagnoseInput(in)

		deps := agent.Dependencies{
			DB:  d,
			Now: time.Now,
		}

		logs.Infof("sdwan_diagnose: query=%q debug=%v", input.Query, input.Debug)

		report, err := runDiagnose(ctx, deps, input)
		if err != nil {
			logs.Errorf("sdwan_diagnose failed: %v", err)
			return nil, nil, err
		}

		return &mcp.CallToolResult{
			Content: []mcp.Content{&mcp.TextContent{Text: report}},
		}, nil, nil
	})
}

type sdwanDiagnoseInput struct {
	Query   string             `json:"query" jsonschema:"required, problem description in natural language"`
	Packet  *sdwanPacketInput  `json:"packet,omitempty"`
	Context *sdwanContextInput `json:"context,omitempty"`
	Debug   bool               `json:"debug"`
}

type sdwanPacketInput struct {
	SrcIP     string  `json:"src_ip"`
	DstIP     string  `json:"dst_ip"`
	Proto     string  `json:"proto"`
	SrcPort   float64 `json:"src_port"`
	DstPort   float64 `json:"dst_port"`
	Namespace string  `json:"namespace"`
}

type sdwanContextInput struct {
	DB            string   `json:"db"`
	SourceRoot    string   `json:"source_root"`
	Focus         []string `json:"focus"`
	MaxCodeChunks float64  `json:"max_code_chunks"`
}

func convertDiagnoseInput(in sdwanDiagnoseInput) agent.DiagnoseInput {
	out := agent.DiagnoseInput{
		Query: in.Query,
		Debug: in.Debug,
	}
	if in.Packet != nil {
		p := &agent.PacketInput{
			SrcIP:     in.Packet.SrcIP,
			DstIP:     in.Packet.DstIP,
			Proto:     in.Packet.Proto,
			Namespace: in.Packet.Namespace,
		}
		if in.Packet.SrcPort != 0 {
			v := int(in.Packet.SrcPort)
			p.SrcPort = &v
		}
		if in.Packet.DstPort != 0 {
			v := int(in.Packet.DstPort)
			p.DstPort = &v
		}
		out.Packet = p
	}
	if in.Context != nil {
		c := &agent.DiagnoseContext{
			DB:         in.Context.DB,
			SourceRoot: in.Context.SourceRoot,
			Focus:      in.Context.Focus,
		}
		if in.Context.MaxCodeChunks != 0 {
			c.MaxCodeChunks = int(in.Context.MaxCodeChunks)
		}
		out.Context = c
	}
	return out
}

func fmtDiagnoseError(msg string) error {
	b, _ := json.Marshal(map[string]string{"error": msg})
	return &diagnoseError{text: string(b)}
}

type diagnoseError struct{ text string }

func (e *diagnoseError) Error() string { return e.text }

func runDiagnose(ctx context.Context, deps agent.Dependencies, input agent.DiagnoseInput) (string, error) {
	graph, err := flow.Build(ctx, deps)
	if err != nil {
		return "", err
	}

	state := agent.AgentState{Input: input}

	result, err := graph.Invoke(ctx, state)
	if err != nil {
		return "", err
	}

	return result.ReportMarkdown, nil
}
