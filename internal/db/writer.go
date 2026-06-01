package db

import (
	"database/sql"
	"encoding/json"
	"strings"

	_ "modernc.org/sqlite"
)

type DB struct {
	sql *sql.DB
}

func Open(path string) (*DB, error) {
	sqldb, err := sql.Open("sqlite", path+"?_journal=WAL&_foreign_keys=on")
	if err != nil {
		return nil, err
	}
	if _, err := sqldb.Exec(Schema); err != nil {
		return nil, err
	}
	return &DB{sql: sqldb}, nil
}

func (d *DB) Close() error { return d.sql.Close() }

func mustJSON(v any) string {
	b, _ := json.Marshal(v)
	return string(b)
}

// --- interfaces ---

// Interface is based primarily on ip -json link show output, supplemented with
// addr_info from ip -json addr show for IP addresses.
type Interface struct {
	Name      string   // ifname from link
	Namespace string   // network namespace
	VRF       string   // VRF name
	IfIndex   int      // ifindex from link
	Kind      string   // link_type: ether, loopback, veth, bridge, vlan, vxlan, gre, etc.
	State     string   // operstate: UP, DOWN, UNKNOWN
	Flags     []string // flags from link (UP, BROADCAST, MULTICAST, etc.)
	MAC       string   // address from link
	MTU       int      // mtu from link
	Master    string   // master device (bridge/VRF), from -d details
	Peer      string   // link: peer ifname for veth pairs
	PeerIndex int      // link_index: peer ifindex for cross-namespace peers
	IPs       []string // CIDR strings: local/prefixlen from addr_info
}

func (d *DB) InsertInterface(iface Interface) error {
	_, err := d.sql.Exec(`INSERT INTO interfaces(name,namespace,vrf,ifindex,kind,state,flags,mac,mtu,master,peer,peer_index,ips)
		VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)`,
		iface.Name, iface.Namespace, iface.VRF, iface.IfIndex, iface.Kind, iface.State,
		mustJSON(iface.Flags), iface.MAC, iface.MTU, iface.Master, iface.Peer, iface.PeerIndex,
		mustJSON(iface.IPs))
	return err
}

func (d *DB) UpdateInterfaceVRF(name, namespace, vrf string) error {
	_, err := d.sql.Exec(`UPDATE interfaces SET vrf=? WHERE name=? AND namespace=?`,
		vrf, name, namespace)
	return err
}

// --- rules ---

// Rule is based on ip -json rule show output.
type Rule struct {
	Namespace  string // network namespace
	VRF        string // VRF name
	Priority   int    // priority
	FromPrefix string // src: source prefix to match
	TableID    string // table: lookup table
	FWMark     string // fwmark (if present)
	Action     string // action (prohibit, unreachable, etc.)
}

func (d *DB) InsertRule(r Rule) error {
	_, err := d.sql.Exec(`INSERT INTO rules(namespace,vrf,priority,from_prefix,table_id,fwmark,action)
		VALUES(?,?,?,?,?,?,?)`,
		r.Namespace, r.VRF, r.Priority, r.FromPrefix, r.TableID, r.FWMark, r.Action)
	return err
}

// --- routes ---

// NextHop represents a single routing next hop.
type NextHop struct {
	Via    string `json:"via,omitempty"`
	Dev    string `json:"dev"`
	Weight int    `json:"weight,omitempty"`
}

// Route is based on ip -json route show output.
type Route struct {
	Namespace    string   // network namespace
	VRF          string   // VRF name
	TableID      string   // routing table
	Prefix       string   // dst prefix
	PreferredSrc string   // prefsrc
	Metric       int      // metric
	Protocol     string   // protocol: kernel, bgp, static, etc.
	Scope        string   // scope: global, link, host
	RouteType    string   // route type: unicast, local, broadcast, etc.
	Flags        []string // flags
	NextHops     []NextHop
}

func (d *DB) InsertRoute(r Route) error {
	_, err := d.sql.Exec(`INSERT INTO routes(namespace,vrf,table_id,prefix,preferred_src,metric,protocol,scope,route_type,flags,next_hops)
		VALUES(?,?,?,?,?,?,?,?,?,?,?)`,
		r.Namespace, r.VRF, r.TableID, r.Prefix, r.PreferredSrc,
		r.Metric, r.Protocol, r.Scope, r.RouteType, mustJSON(r.Flags), mustJSON(r.NextHops))
	return err
}

// --- neighbors ---

// Neighbor is based on ip -json neigh show output.
type Neighbor struct {
	Namespace string // network namespace
	VRF       string // VRF name
	IP        string // dst: neighbor IP
	Dev       string // dev: device
	MAC       string // lladdr: MAC address
	State     string // primary state (STALE, REACHABLE, etc.)
	Reachable bool   // computed from state
}

func (d *DB) InsertNeighbor(n Neighbor) error {
	_, err := d.sql.Exec(`INSERT INTO neighbors(namespace,vrf,ip,dev,mac,state,reachable)
		VALUES(?,?,?,?,?,?,?)`,
		n.Namespace, n.VRF, n.IP, n.Dev, n.MAC, n.State, n.Reachable)
	return err
}

// ReachableStates are the ARP/NDP states considered reachable.
var ReachableStates = map[string]bool{
	"REACHABLE": true,
	"STALE":     true,
	"DELAY":     true,
	"PROBE":     true,
}

func IsReachable(states []string) bool {
	for _, s := range states {
		if ReachableStates[s] {
			return true
		}
	}
	return false
}

func JoinStates(states []string) string { return strings.Join(states, ",") }

// --- ovs bridge ---

type OvsBridge struct {
	Name         string
	DatapathID   string
	DatapathType string
}

func (d *DB) InsertOvsBridge(b OvsBridge) error {
	_, err := d.sql.Exec(`INSERT INTO ovs_bridges(name,datapath_id,datapath_type)
		VALUES(?,?,?)`, b.Name, b.DatapathID, b.DatapathType)
	return err
}

// --- ovs port ---

type OvsPort struct {
	Bridge     string
	Port       string
	Interface  string
	PortType   string
	OFPort     int
	VlanTag    int
	TrunkVlans []int
	MAC        string
	Options    map[string]string
}

func (d *DB) InsertOvsPort(p OvsPort) error {
	_, err := d.sql.Exec(`INSERT INTO ovs_ports(bridge,port,interface,port_type,ofport,vlan_tag,trunk_vlans,mac,options)
		VALUES(?,?,?,?,?,?,?,?,?)`,
		p.Bridge, p.Port, p.Interface, p.PortType, p.OFPort,
		p.VlanTag, mustJSON(p.TrunkVlans), p.MAC, mustJSON(p.Options))
	return err
}

// --- ovs flow ---

type OvsFlow struct {
	Bridge      string
	TableID     int
	Priority    int
	Cookie      string
	Match       string
	Actions     string
	MatchFields map[string]string
	ActionList  []string
	NPackets    *int64
	NBytes      *int64
}

func (d *DB) InsertOvsFlow(f OvsFlow) error {
	_, err := d.sql.Exec(`INSERT INTO ovs_flows(bridge,table_id,priority,cookie,match,actions,match_fields,action_list,n_packets,n_bytes)
		VALUES(?,?,?,?,?,?,?,?,?,?)`,
		f.Bridge, f.TableID, f.Priority, f.Cookie,
		f.Match, f.Actions, mustJSON(f.MatchFields), mustJSON(f.ActionList),
		f.NPackets, f.NBytes)
	return err
}

// --- ovs group ---

type OvsGroupBucket struct {
	BucketID    int
	Weight      int
	Actions     string
	ActionList  []string
	WatchPort   *int
	WatchGroup  *int
	Active      *bool
	PacketCount int64
	ByteCount   int64
}

type OvsGroup struct {
	Bridge      string
	GroupID     int
	GroupType   string
	PacketCount int64
	ByteCount   int64
	Buckets     []OvsGroupBucket
}

func (d *DB) InsertOvsGroup(g OvsGroup) error {
	r, err := d.sql.Exec(`INSERT INTO ovs_groups(bridge,group_id,group_type,packet_count,byte_count)
		VALUES(?,?,?,?,?)`,
		g.Bridge, g.GroupID, g.GroupType, g.PacketCount, g.ByteCount)
	if err != nil {
		return err
	}
	gfk, _ := r.LastInsertId()
	for _, b := range g.Buckets {
		_, err = d.sql.Exec(`INSERT INTO ovs_group_buckets(group_fk,bucket_id,weight,actions,action_list,watch_port,watch_group,active,packet_count,byte_count)
			VALUES(?,?,?,?,?,?,?,?,?,?)`,
			gfk, b.BucketID, b.Weight, b.Actions, mustJSON(b.ActionList),
			b.WatchPort, b.WatchGroup, b.Active, b.PacketCount, b.ByteCount)
		if err != nil {
			return err
		}
	}
	return nil
}

// --- ovs fdb ---

type OvsFDBEntry struct {
	Bridge string
	Port   string
	VLAN   int
	MAC    string
	AgeSec *int
}

func (d *DB) InsertOvsFDB(e OvsFDBEntry) error {
	_, err := d.sql.Exec(`INSERT INTO ovs_fdb(bridge,port,vlan,mac,age_sec)
		VALUES(?,?,?,?,?)`, e.Bridge, e.Port, e.VLAN, e.MAC, e.AgeSec)
	return err
}

// --- ovs tunnel arp ---

type OvsTnlARP struct {
	Bridge string
	IP     string
	MAC    string
	Port   string
}

func (d *DB) InsertOvsTnlARP(a OvsTnlARP) error {
	_, err := d.sql.Exec(`INSERT INTO ovs_tnl_arp(bridge,ip,mac,port)
		VALUES(?,?,?,?)`, a.Bridge, a.IP, a.MAC, a.Port)
	return err
}

// --- frr info ---

type FrrInfo struct {
	Command string
	Output  string
	Status  string // "ok", "empty", "error"
}

func (d *DB) InsertFrrInfo(f FrrInfo) error {
	_, err := d.sql.Exec(
		`INSERT OR REPLACE INTO frr_info(command, output, status) VALUES(?,?,?)`,
		f.Command, f.Output, f.Status)
	return err
}
