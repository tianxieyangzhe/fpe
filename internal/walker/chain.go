package walker

import "github.com/yangshuai/fpe/internal/db"

// Walk computes all possible path leaves for the given packet.
func Walk(pkt PacketTuple, d *db.DB) WalkResult {
	leaves := walkNamespace(pkt, d, nil, 0)
	status := "complete"
	for _, l := range leaves {
		if l.Outcome == "uncertain" {
			status = "uncertain"
		} else if l.Outcome == "incomplete" && status != "uncertain" {
			status = "incomplete"
		} else if l.Outcome == "drop" && status == "complete" {
			status = "drop"
		}
	}
	return WalkResult{Packet: pkt, Leaves: leaves, Status: status}
}

func walkNamespace(pkt PacketTuple, d *db.DB, prevSegs []PathSegment, depth int) []PathLeaf {
	if depth > 16 {
		return []PathLeaf{{Segments: prevSegs, Outcome: "incomplete", Certainty: "uncertain"}}
	}

	var hops []Hop

	tableID := matchRules(pkt, d)
	hops = append(hops, Hop{
		Type:      "rule",
		Match:     "src=" + pkt.SrcIP,
		Action:    "lookup table " + tableID,
		Certainty: "certain",
	})

	route := lpmRoute(pkt.DstIP, d, pkt.Namespace, tableID)
	if route == nil {
		seg := PathSegment{Namespace: pkt.Namespace, Hops: hops, EgressType: "drop", Certainty: "certain"}
		return []PathLeaf{{Segments: append(prevSegs, seg), Outcome: "drop", Certainty: "certain"}}
	}
	nh := route.NextHops[0]
	hops = append(hops, Hop{
		Type:      "route",
		Match:     "dst=" + pkt.DstIP + " prefix=" + route.Prefix,
		Action:    "via " + nh.Via + " dev " + nh.Dev,
		Certainty: "certain",
	})

	dev := nh.Dev

	if d.IsOvsBridge(dev) {
		seg := PathSegment{Namespace: pkt.Namespace, Hops: hops}
		return walkOVS(pkt, d, dev, seg, prevSegs, depth)
	}

	if ovsPort, _ := d.OvsPortByName(dev); ovsPort != nil {
		seg := PathSegment{Namespace: pkt.Namespace, Hops: hops}
		return walkOVS(pkt, d, ovsPort.Bridge, seg, prevSegs, depth)
	}

	iface, _ := d.InterfaceByIP(pkt.SrcIP)
	if iface != nil && iface.Kind == "veth" && iface.Peer != "" {
		peerIface, _ := d.InterfaceByIP(pkt.DstIP)
		peerNS := ""
		if peerIface != nil {
			peerNS = peerIface.Namespace
		}
		seg := PathSegment{
			Namespace:  pkt.Namespace,
			Hops:       hops,
			Egress:     dev,
			EgressType: "veth",
			EgressPeer: &PeerHint{PeerIface: iface.Peer, PeerNS: peerNS},
			Certainty:  "certain",
		}
		newPkt := pkt
		newPkt.Namespace = peerNS
		return walkNamespace(newPkt, d, append(prevSegs, seg), depth+1)
	}

	seg := PathSegment{
		Namespace:  pkt.Namespace,
		Hops:       hops,
		Egress:     dev,
		EgressType: "physical",
		Certainty:  "certain",
	}
	if nh.Via != "" {
		seg.EgressPeer = &PeerHint{RemoteIP: nh.Via}
	}
	return []PathLeaf{{Segments: append(prevSegs, seg), Outcome: "output", Certainty: "certain"}}
}
