package remote

import (
	"strings"

	"github.com/yangshuai/fpe/internal/collector"
)

func collectNamespaces(exec collector.Executor) ([]string, error) {
	out, err := exec.Run("ip netns list")
	if err != nil {
		return nil, err
	}
	var names []string
	for _, line := range strings.Split(out, "\n") {
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		name := strings.Fields(line)[0]
		names = append(names, name)
	}
	return names, nil
}
