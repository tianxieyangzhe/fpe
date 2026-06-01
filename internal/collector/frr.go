package collector

import (
	"fmt"
	"strings"

	"github.com/yangshuai/fpe/internal/db"
	"github.com/yangshuai/fpe/internal/logs"
)

var frrCommands = []string{
	"show ip route",
	"show bfd peers",
	"show running-config",
	"show bgp summary",
	"show bgp ipv4 unicast",
	"show ip ospf neighbor",
}

// CollectFRR runs FRR vtysh commands and returns the raw output for each command.
// It first tries vtysh directly, then falls back to ip netns exec ANPOSNS.
func CollectFRR(exec Executor) ([]db.FrrInfo, error) {
	var result []db.FrrInfo
	for _, cmd := range frrCommands {
		output, status := runFrrCmd(exec, cmd)
		result = append(result, db.FrrInfo{Command: cmd, Output: output, Status: status})
	}
	return result, nil
}

func runFrrCmd(exec Executor, cmd string) (output, status string) {
	directCmd := fmt.Sprintf("sudo /anpos/frr/bin/vtysh -N ANPOSNS -c %q", cmd)
	output, err := exec.Run(directCmd)
	if err == nil {
		if isEmptyFRROutput(output) {
			return output, "empty"
		}
		return output, "ok"
	}

	logs.Warnf("frr direct failed cmd=%q: %v, trying netns", cmd, err)
	nsCmd := fmt.Sprintf("ip netns exec ANPOSNS vtysh -c %q", cmd)
	output, err = exec.Run(nsCmd)
	if err != nil {
		logs.Warnf("frr netns failed cmd=%q: %v", cmd, err)
		return fmt.Sprintf("exec error: %v", err), "error"
	}
	if isEmptyFRROutput(output) {
		return output, "empty"
	}
	return output, "ok"
}

// isEmptyFRROutput checks if the FRR output indicates the queried
// protocol/feature is not configured (e.g. "BGP instance not found").
func isEmptyFRROutput(output string) bool {
	trimmed := strings.TrimSpace(output)
	if trimmed == "" {
		return true
	}
	lower := strings.ToLower(trimmed)
	// Single-line "not found" responses from various FRR daemons
	if strings.Contains(lower, "not found") {
		if strings.Count(trimmed, "\n") <= 1 {
			return true
		}
	}
	// "show bfd peers" returns only "BFD Peers:" when no peers exist
	if trimmed == "BFD Peers:" {
		return true
	}
	return false
}
