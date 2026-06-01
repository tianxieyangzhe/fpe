package collector

import (
	"encoding/json"
	"fmt"

	"github.com/yangshuai/fpe/internal/db"
	"github.com/yangshuai/fpe/internal/logs"
)

// --- JSON structs for unmarshaling ip -json output ---

type jsonLink struct {
	IfIndex   int      `json:"ifindex"`
	IfName    string   `json:"ifname"`
	Flags     []string `json:"flags"`
	MTU       int      `json:"mtu"`
	OperState string   `json:"operstate"`
	LinkType  string   `json:"link_type"`
	Address   string   `json:"address"`
	Link      string   `json:"link,omitempty"`
	LinkIndex int      `json:"link_index"`
	Master    string   `json:"master,omitempty"`
}

type jsonAddrInfo struct {
	Family    string `json:"family"`
	Local     string `json:"local"`
	PrefixLen int    `json:"prefixlen"`
}

type jsonAddr struct {
	IfIndex  int            `json:"ifindex"`
	AddrInfo []jsonAddrInfo `json:"addr_info"`
}

// CollectInterfaces uses ip -json link show as the primary source,
// supplemented with ip -json addr show for IP addresses.
func CollectInterfaces(exec Executor, namespace string) ([]db.Interface, error) {
	linkJSON, err := exec.Run(buildNSCmd(namespace, "ip -json link show"))
	if err != nil {
		return nil, err
	}

	var links []jsonLink
	if err := json.Unmarshal([]byte(linkJSON), &links); err != nil {
		return nil, fmt.Errorf("parse ip link json: %w", err)
	}

	ifaceMap := make(map[int]*db.Interface, len(links))
	for i := range links {
		l := &links[i]
		ifaceMap[l.IfIndex] = &db.Interface{
			Name:      l.IfName,
			Namespace: namespace,
			IfIndex:   l.IfIndex,
			Kind:      l.LinkType,
			State:     l.OperState,
			Flags:     l.Flags,
			MAC:       l.Address,
			MTU:       l.MTU,
			Master:    l.Master,
			Peer:      l.Link,
			PeerIndex: l.LinkIndex,
		}
	}

	// Supplement with IP addresses from addr show
	addrJSON, err := exec.Run(buildNSCmd(namespace, "ip -json addr show"))
	if err != nil {
		logs.Warnf("addr collection failed ns=%s: %v", namespace, err)
	} else {
		var addrs []jsonAddr
		if err := json.Unmarshal([]byte(addrJSON), &addrs); err != nil {
			logs.Warnf("parse ip addr json ns=%s: %v", namespace, err)
		} else {
			for _, a := range addrs {
				iface, ok := ifaceMap[a.IfIndex]
				if !ok {
					continue
				}
				for _, ai := range a.AddrInfo {
					cidr := fmt.Sprintf("%s/%d", ai.Local, ai.PrefixLen)
					iface.IPs = append(iface.IPs, cidr)
				}
			}
		}
	}

	out := make([]db.Interface, 0, len(ifaceMap))
	for _, v := range ifaceMap {
		out = append(out, *v)
	}
	return out, nil
}
