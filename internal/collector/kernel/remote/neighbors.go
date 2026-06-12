package remote

import (
	"github.com/yangshuai/fpe/internal/collector"
	"github.com/yangshuai/fpe/internal/db"
)

type jsonNeigh struct {
	Dst    string   `json:"dst"`
	Dev    string   `json:"dev"`
	LLAddr string   `json:"lladdr,omitempty"`
	State  []string `json:"state"`
}

func collectNeighbors(exec collector.Executor, namespace string) ([]db.Neighbor, error) {
	cmd := nsCmd(namespace, "ip -json neigh show")
	out, err := exec.Run(cmd)
	if err != nil {
		return nil, err
	}

	var jn []jsonNeigh
	if err := jsonArray(cmd, out, &jn); err != nil {
		return nil, err
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
