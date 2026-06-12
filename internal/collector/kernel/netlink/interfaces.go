//go:build linux

package netlink

import (
	"fmt"
	"net"
	"strings"

	nl "github.com/vishvananda/netlink"
	"github.com/yangshuai/fpe/internal/db"
	"github.com/yangshuai/fpe/internal/logs"
)

func collectInterfaces(namespace string) ([]db.Interface, error) {
	restore, err := enterNS(namespace)
	if err != nil {
		return nil, err
	}
	defer restore()

	links, err := nl.LinkList()
	if err != nil {
		return nil, err
	}

	ifaceMap := make(map[int]*db.Interface, len(links))
	for _, link := range links {
		attrs := link.Attrs()
		ifaceMap[attrs.Index] = &db.Interface{
			Name:      attrs.Name,
			Namespace: namespace,
			IfIndex:   attrs.Index,
			Kind:      linkTypeToKind(link.Type()),
			State:     operStateString(attrs.OperState),
			Flags:     linkFlagsToStrings(attrs.Flags),
			MAC:       attrs.HardwareAddr.String(),
			MTU:       attrs.MTU,
			Master:    linkIndexToName(links, attrs.MasterIndex),
			Peer:      linkIndexToName(links, attrs.ParentIndex),
			PeerIndex: attrs.ParentIndex,
		}
	}

	addrs, err := nl.AddrList(nil, 0)
	if err != nil {
		logs.Warnf("addr collection failed ns=%s: %v", namespace, err)
	} else {
		for _, a := range addrs {
			iface, ok := ifaceMap[a.LinkIndex]
			if !ok {
				continue
			}
			if a.IPNet != nil {
				cidr := a.IPNet.String()
				iface.IPs = append(iface.IPs, cidr)
			}
		}
	}

	out := make([]db.Interface, 0, len(ifaceMap))
	for _, v := range ifaceMap {
		out = append(out, *v)
	}
	return out, nil
}

func linkTypeToKind(t string) string {
	if t == "device" {
		return "ether"
	}
	return t
}

func operStateString(s nl.LinkOperState) string {
	switch s {
	case nl.OperUp:
		return "UP"
	case nl.OperDown:
		return "DOWN"
	case nl.OperUnknown:
		return "UNKNOWN"
	case nl.OperLowerLayerDown:
		return "LOWERLAYERDOWN"
	case nl.OperNotPresent:
		return "NOTPRESENT"
	case nl.OperTesting:
		return "TESTING"
	case nl.OperDormant:
		return "DORMANT"
	default:
		return fmt.Sprintf("UNKNOWN(%d)", s)
	}
}

func linkFlagsToStrings(flags net.Flags) []string {
	if flags == 0 {
		return nil
	}
	s := flags.String()
	return strings.Fields(s)
}

func linkIndexToName(links []nl.Link, idx int) string {
	if idx == 0 {
		return ""
	}
	for _, l := range links {
		if l.Attrs().Index == idx {
			return l.Attrs().Name
		}
	}
	return ""
}
