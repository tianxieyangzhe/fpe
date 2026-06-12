//go:build linux

package netlink

import "os"

func collectNamespaces() ([]string, error) {
	entries, err := os.ReadDir("/var/run/netns")
	if err != nil {
		return nil, err
	}
	var names []string
	for _, e := range entries {
		if e.IsDir() {
			continue
		}
		names = append(names, e.Name())
	}
	return names, nil
}
