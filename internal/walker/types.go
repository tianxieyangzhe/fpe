package walker

// PacketTuple represents a network packet. Nil pointer fields are not used in OVS match.
type PacketTuple struct {
	SrcIP     string
	DstIP     string
	Proto     string // tcp/udp/icmp/ip
	SrcPort   *int
	DstPort   *int
	InPort    *int  // OVS ofport
	SrcMac    string
	DstMac    string
	VlanID    *int
	TunnelID  *int64
	Namespace string
	Uncertain []string // fields that were inferred, not provided
}

type Hop struct {
	Type      string // rule/route/ovs_flow/ovs_group/interface
	TableID   int
	Match     string
	Action    string
	Certainty string // certain/uncertain
	Reason    string // why uncertain
}

type PeerHint struct {
	RemoteIP  string
	VNI       int
	PeerIface string
	PeerNS    string
}

type PathSegment struct {
	Host       string
	Namespace  string
	Ingress    string
	Egress     string
	EgressType string // veth/vxlan/geneve/physical/local/drop/unknown
	EgressPeer *PeerHint
	Hops       []Hop
	Certainty  string
}

type PathLeaf struct {
	Segments  []PathSegment
	Outcome   string // output/drop/uncertain/incomplete
	Certainty string
}

type WalkResult struct {
	Packet PacketTuple
	Leaves []PathLeaf
	Status string // complete/drop/uncertain/incomplete
}
