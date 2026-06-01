package collector

import (
	"encoding/json"
	"fmt"

	"github.com/yangshuai/fpe/internal/db"
)

// --- JSON structs for unmarshaling ip -json neigh show output ---

type jsonNeigh struct {
	Dst    string   `json:"dst"`
	Dev    string   `json:"dev"`
	LLAddr string   `json:"lladdr,omitempty"`
	State  []string `json:"state"`
}

func CollectNeighbors(exec Executor, namespace string) ([]db.Neighbor, error) {
	out, err := exec.Run(buildNSCmd(namespace, "ip -json neigh show"))
	if err != nil {
		return nil, err
	}

	var jn []jsonNeigh
	if err := json.Unmarshal([]byte(out), &jn); err != nil {
		return nil, fmt.Errorf("parse ip neigh json: %w", err)
	}

	neighbors := make([]db.Neighbor, 0, len(jn))
	for _, n := range jn {
		neighbors = append(neighbors, db.Neighbor{
			Namespace: namespace,
			IP:        n.Dst,
			Dev:       n.Dev,
			MAC:       n.LLAddr,
			State:     db.JoinStates(n.State),
			Reachable: db.IsReachable(n.State),
		})
	}
	return neighbors, nil
}
