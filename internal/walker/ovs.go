package walker

import (
	"fmt"
	"net/netip"
	"strings"

	"github.com/yangshuai/fpe/internal/db"
)

func walkOVS(pkt PacketTuple, d *db.DB, bridge string, seg PathSegment, prevSegs []PathSegment, depth int) []PathLeaf {
	seg.Ingress = bridge + " (bridge)"
	return walkOVSTable(pkt, d, bridge, 0, seg, prevSegs, depth)
}

func walkOVSTable(pkt PacketTuple, d *db.DB, bridge string, tableID int, seg PathSegment, prevSegs []PathSegment, depth int) []PathLeaf {
	if depth > 32 {
		seg.EgressType = "drop"
		return []PathLeaf{{Segments: append(prevSegs, seg), Outcome: "incomplete", Certainty: "uncertain"}}
	}

	flows, _ := d.GetOvsFlows(bridge, tableID)
	var matched []db.OvsFlow
	var uncertain []db.OvsFlow

	for _, f := range flows {
		c := matchFlow(f, pkt)
		if c == "certain" {
			matched = append(matched, f)
			break
		} else if c == "uncertain" {
			uncertain = append(uncertain, f)
		}
	}

	var leaves []PathLeaf

	if len(matched) > 0 {
		f := matched[0]
		seg.Hops = append(seg.Hops, Hop{
			Type: "ovs_flow", TableID: tableID,
			Match: f.Match, Action: f.Actions, Certainty: "certain",
		})
		leaves = append(leaves, processActions(f.ActionList, pkt, d, bridge, seg, prevSegs, depth)...)
	}

	for _, f := range uncertain {
		branchSeg := seg
		branchSeg.Hops = append(append([]Hop{}, seg.Hops...), Hop{
			Type: "ovs_flow", TableID: tableID,
			Match: f.Match, Action: f.Actions,
			Certainty: "uncertain", Reason: "match depends on runtime state (ct_state/register)",
		})
		bl := processActions(f.ActionList, pkt, d, bridge, branchSeg, prevSegs, depth)
		for i := range bl {
			bl[i].Certainty = "uncertain"
		}
		leaves = append(leaves, bl...)
	}

	if len(leaves) == 0 {
		seg.EgressType = "drop"
		seg.Certainty = "certain"
		leaves = []PathLeaf{{Segments: append(prevSegs, seg), Outcome: "drop", Certainty: "certain"}}
	}
	return leaves
}

func processActions(actions []string, pkt PacketTuple, d *db.DB, bridge string, seg PathSegment, prevSegs []PathSegment, depth int) []PathLeaf {
	for _, action := range actions {
		action = strings.TrimSpace(action)
		switch {
		case action == "drop":
			seg.EgressType = "drop"
			seg.Certainty = "certain"
			return []PathLeaf{{Segments: append(prevSegs, seg), Outcome: "drop", Certainty: "certain"}}

		case strings.HasPrefix(action, "goto_table:"):
			next, _ := parseIntSuffix(action, "goto_table:")
			return walkOVSTable(pkt, d, bridge, next, seg, prevSegs, depth+1)

		case strings.HasPrefix(action, "resubmit(,"):
			s := strings.TrimSuffix(strings.TrimPrefix(action, "resubmit(,"), ")")
			next := 0
			fmt.Sscanf(s, "%d", &next)
			return walkOVSTable(pkt, d, bridge, next, seg, prevSegs, depth+1)

		case strings.HasPrefix(action, "group:"):
			gid := 0
			fmt.Sscanf(strings.TrimPrefix(action, "group:"), "%d", &gid)
			return walkGroup(gid, pkt, d, bridge, seg, prevSegs, depth)

		case strings.HasPrefix(action, "output:"):
			port := strings.TrimPrefix(action, "output:")
			if port == "LOCAL" {
				seg.EgressType = "local"
				seg.Egress = "LOCAL"
				seg.Certainty = "certain"
				return []PathLeaf{{Segments: append(prevSegs, seg), Outcome: "output", Certainty: "certain"}}
			}
			ofport := 0
			fmt.Sscanf(port, "%d", &ofport)
			ovsPort, _ := d.OvsPortByOFPort(bridge, ofport)
			if ovsPort != nil {
				seg.Egress = fmt.Sprintf("%s (ofport=%d)", ovsPort.Port, ofport)
				seg.EgressType = resolvePortEgressType(ovsPort)
				seg.EgressPeer = resolvePortPeer(ovsPort)
			} else {
				seg.Egress = fmt.Sprintf("ofport=%d", ofport)
				seg.EgressType = "unknown"
			}
			seg.Certainty = "certain"
			return []PathLeaf{{Segments: append(prevSegs, seg), Outcome: "output", Certainty: "certain"}}
		}
	}
	seg.EgressType = "unknown"
	return []PathLeaf{{Segments: append(prevSegs, seg), Outcome: "uncertain", Certainty: "uncertain"}}
}

func walkGroup(groupID int, pkt PacketTuple, d *db.DB, bridge string, seg PathSegment, prevSegs []PathSegment, depth int) []PathLeaf {
	g, _ := d.GetOvsGroup(bridge, groupID)
	if g == nil {
		seg.EgressType = "unknown"
		return []PathLeaf{{Segments: append(prevSegs, seg), Outcome: "uncertain", Certainty: "uncertain"}}
	}

	seg.Hops = append(seg.Hops, Hop{
		Type:      "ovs_group",
		Match:     fmt.Sprintf("group_id=%d type=%s", groupID, g.GroupType),
		Action:    fmt.Sprintf("%d buckets", len(g.Buckets)),
		Certainty: "certain",
	})

	var leaves []PathLeaf
	for _, b := range g.Buckets {
		if g.GroupType == "ff" && b.Active != nil && !*b.Active {
			continue
		}
		branchSeg := seg
		branchSeg.Hops = append([]Hop{}, seg.Hops...)
		bl := processActions(b.ActionList, pkt, d, bridge, branchSeg, prevSegs, depth+1)
		if g.GroupType == "select" {
			for i := range bl {
				bl[i].Certainty = "uncertain"
			}
		}
		leaves = append(leaves, bl...)
	}
	return leaves
}

func matchFlow(f db.OvsFlow, pkt PacketTuple) string {
	certainty := "certain"
	for key, val := range f.MatchFields {
		c := matchField(key, val, pkt)
		if c == "no" {
			return "no"
		}
		if c == "uncertain" {
			certainty = "uncertain"
		}
	}
	return certainty
}

func matchField(key, val string, pkt PacketTuple) string {
	switch key {
	case "proto":
		if pkt.Proto == "" {
			return "uncertain"
		}
		return boolMatch(val == pkt.Proto || val == "ip")
	case "ip", "tcp", "udp", "icmp", "arp", "ipv6", "icmp6":
		if pkt.Proto == "" {
			return "uncertain"
		}
		return boolMatch(key == pkt.Proto || key == "ip")
	case "ip_src", "nw_src":
		return matchCIDR(val, pkt.SrcIP)
	case "ip_dst", "nw_dst":
		return matchCIDR(val, pkt.DstIP)
	case "tp_src":
		if pkt.SrcPort == nil {
			return "uncertain"
		}
		return boolMatch(fmt.Sprintf("%d", *pkt.SrcPort) == val)
	case "tp_dst":
		if pkt.DstPort == nil {
			return "uncertain"
		}
		return boolMatch(fmt.Sprintf("%d", *pkt.DstPort) == val)
	case "in_port":
		if pkt.InPort == nil {
			return "uncertain"
		}
		return boolMatch(fmt.Sprintf("%d", *pkt.InPort) == val)
	case "dl_src":
		if pkt.SrcMac == "" {
			return "uncertain"
		}
		return boolMatch(strings.EqualFold(pkt.SrcMac, val))
	case "dl_dst":
		if pkt.DstMac == "" {
			return "uncertain"
		}
		return boolMatch(strings.EqualFold(pkt.DstMac, val))
	case "dl_vlan":
		if pkt.VlanID == nil {
			return "uncertain"
		}
		return boolMatch(fmt.Sprintf("%d", *pkt.VlanID) == val)
	case "tun_id":
		if pkt.TunnelID == nil {
			return "uncertain"
		}
		return boolMatch(fmt.Sprintf("%d", *pkt.TunnelID) == val)
	case "ct_state", "ct_mark", "ct_label":
		return "uncertain"
	default:
		if strings.HasPrefix(key, "reg") || strings.HasPrefix(key, "metadata") {
			return "uncertain"
		}
		return "certain"
	}
}

func matchCIDR(cidr, ip string) string {
	if ip == "" {
		return "uncertain"
	}
	addr, err := netip.ParseAddr(ip)
	if err != nil {
		return "uncertain"
	}
	if !strings.Contains(cidr, "/") {
		cidr += "/32"
	}
	pfx, err := netip.ParsePrefix(cidr)
	if err != nil {
		return "uncertain"
	}
	return boolMatch(pfx.Contains(addr))
}

func boolMatch(b bool) string {
	if b {
		return "certain"
	}
	return "no"
}

func resolvePortEgressType(p *db.OvsPort) string {
	switch p.PortType {
	case "vxlan":
		return "vxlan"
	case "geneve":
		return "geneve"
	case "patch":
		return "patch"
	case "internal":
		return "local"
	default:
		return "physical"
	}
}

func resolvePortPeer(p *db.OvsPort) *PeerHint {
	switch p.PortType {
	case "vxlan", "geneve":
		hint := &PeerHint{}
		if r, ok := p.Options["remote_ip"]; ok {
			hint.RemoteIP = r
		}
		if k, ok := p.Options["key"]; ok {
			fmt.Sscanf(k, "%d", &hint.VNI)
		}
		return hint
	case "patch":
		if peer, ok := p.Options["peer"]; ok {
			return &PeerHint{PeerIface: peer}
		}
	}
	return nil
}

func parseIntSuffix(s, prefix string) (int, error) {
	v := 0
	_, err := fmt.Sscanf(strings.TrimPrefix(s, prefix), "%d", &v)
	return v, err
}
