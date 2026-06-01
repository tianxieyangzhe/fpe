package walker

import "github.com/yangshuai/fpe/internal/db"

// ResolvePacket fills in inferred fields from the DB.
func ResolvePacket(pkt PacketTuple, d *db.DB) PacketTuple {
	if pkt.Proto == "" {
		pkt.Proto = "tcp"
		pkt.Uncertain = append(pkt.Uncertain, "proto=tcp (default)")
	}

	iface, _ := d.InterfaceByIP(pkt.SrcIP)
	if iface != nil {
		if pkt.SrcMac == "" {
			pkt.SrcMac = iface.MAC
			pkt.Uncertain = append(pkt.Uncertain, "src_mac inferred from interface")
		}
		if pkt.InPort == nil {
			port, _ := d.OvsPortByName(iface.Name)
			if port != nil && port.OFPort > 0 {
				pkt.InPort = &port.OFPort
				pkt.Uncertain = append(pkt.Uncertain, "in_port inferred from interface")
			}
		}
		if pkt.Namespace == "" {
			pkt.Namespace = iface.Namespace
		}
	}

	if pkt.DstMac == "" {
		if n, _ := d.GetNeighbor(pkt.DstIP); n != nil && n.MAC != "" {
			pkt.DstMac = n.MAC
			pkt.Uncertain = append(pkt.Uncertain, "dst_mac inferred from neighbor table")
		}
	}
	return pkt
}
