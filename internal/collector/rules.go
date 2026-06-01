package collector

import (
	"encoding/json"
	"fmt"

	"github.com/yangshuai/fpe/internal/db"
)

// --- JSON structs for unmarshaling ip -json rule show output ---

type jsonRule struct {
	Priority int    `json:"priority"`
	Src      string `json:"src"`
	Table    string `json:"table"`
	FWMark   string `json:"fwmark,omitempty"`
	Action   string `json:"action,omitempty"`
}

func CollectRules(exec Executor, namespace string) ([]db.Rule, error) {
	out, err := exec.Run(buildNSCmd(namespace, "ip -json rule show"))
	if err != nil {
		return nil, err
	}

	var jr []jsonRule
	if err := json.Unmarshal([]byte(out), &jr); err != nil {
		return nil, fmt.Errorf("parse ip rule json: %w", err)
	}

	rules := make([]db.Rule, 0, len(jr))
	for _, r := range jr {
		rules = append(rules, db.Rule{
			Namespace:  namespace,
			Priority:   r.Priority,
			FromPrefix: normalizeSrc(r.Src),
			TableID:    r.Table,
			FWMark:     r.FWMark,
			Action:     r.Action,
		})
	}
	return rules, nil
}

func normalizeSrc(s string) string {
	if s == "" || s == "all" {
		return ""
	}
	return s
}
