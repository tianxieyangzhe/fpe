package mcp

import (
	"context"
	"testing"
	"time"

	"github.com/yangshuai/fpe/internal/agent"
	"github.com/yangshuai/fpe/internal/agent/flow"
	"github.com/yangshuai/fpe/internal/db"
)

func TestDiagnoseFlow(t *testing.T) {
	d, err := db.Open(":memory:")
	if err != nil {
		t.Fatal(err)
	}
	defer d.Close()

	deps := agent.Dependencies{
		DB:  d,
		Now: time.Now,
	}

	graph, err := flow.Build(context.Background(), deps)
	if err != nil {
		t.Fatalf("Build failed: %v", err)
	}

	input := agent.DiagnoseInput{
		Query: "test FPE diagnostic",
		Debug: true,
	}

	state := agent.AgentState{Input: input}
	result, err := graph.Invoke(context.Background(), state)
	if err != nil {
		t.Fatalf("Invoke failed: %v", err)
	}

	if result.ReportMarkdown == "" {
		t.Error("Report is empty")
	}

	t.Logf("Report:\n%s", result.ReportMarkdown)

	if result.Normalized.Query != "test FPE diagnostic" {
		t.Error("Normalize didn't preserve query")
	}
}
