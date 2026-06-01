package collector

import (
	"strings"
)

// CollectNetNS returns all network namespace names visible from the current context.
// It runs "ip netns list" and returns the name portion of each line.
func CollectNetNS(exec Executor) ([]string, error) {
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
		// "ip netns list" output: "<name> (id: N)" or just "<name>"
		name := strings.Fields(line)[0]
		names = append(names, name)
	}
	return names, nil
}

