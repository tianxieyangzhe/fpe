//go:build linux

package netlink

import (
	nl "github.com/vishvananda/netlink"
	"github.com/yangshuai/fpe/internal/db"
)

func collectNeighbors(namespace string) ([]db.Neighbor, error) {
	restore, err := enterNS(namespace)
	if err != nil {
		return nil, err
	}
	defer restore()

	nlneighs, err := nl.NeighList(0, 0)
	if err != nil {
		return nil, err
	}

	links, _ := nl.LinkList()
	linkNames := make(map[int]string, len(links))
	for _, l := range links {
		linkNames[l.Attrs().Index] = l.Attrs().Name
	}

	neighbors := make([]db.Neighbor, 0, len(nlneighs))
	for _, n := range nlneighs {
		state := nudStateString(n.State)
		neighbors = append(neighbors, db.Neighbor{
			Namespace: namespace,
			IP:        n.IP.String(),
			Dev:       linkNames[n.LinkIndex],
			MAC:       n.HardwareAddr.String(),
			State:     state,
			Reachable: isNudReachable(n.State),
		})
	}
	return neighbors, nil
}

func nudStateString(state int) string {
	switch state {
	case 0x01:
		return "INCOMPLETE"
	case 0x02:
		return "REACHABLE"
	case 0x04:
		return "STALE"
	case 0x08:
		return "DELAY"
	case 0x10:
		return "PROBE"
	case 0x20:
		return "FAILED"
	case 0x40:
		return "NOARP"
	case 0x80:
		return "PERMANENT"
	default:
		return "NONE"
	}
}

func isNudReachable(state int) bool {
	return state&(0x02|0x04|0x08|0x10) != 0
}
