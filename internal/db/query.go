package db

import (
	"database/sql"
	"encoding/json"
	"net/netip"
)

func (d *DB) GetInterfaces(namespace string) ([]Interface, error) {
	rows, err := d.sql.Query(`SELECT name,namespace,vrf,ifindex,kind,state,flags,mac,mtu,master,peer,peer_index,ips
		FROM interfaces WHERE namespace=?`, namespace)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []Interface
	for rows.Next() {
		var iface Interface
		var flagsJSON, ipsJSON string
		if err := rows.Scan(&iface.Name, &iface.Namespace, &iface.VRF, &iface.IfIndex, &iface.Kind, &iface.State,
			&flagsJSON, &iface.MAC, &iface.MTU, &iface.Master, &iface.Peer, &iface.PeerIndex, &ipsJSON); err != nil {
			return nil, err
		}
		json.Unmarshal([]byte(flagsJSON), &iface.Flags)
		json.Unmarshal([]byte(ipsJSON), &iface.IPs)
		out = append(out, iface)
	}
	return out, rows.Err()
}

// InterfaceByIP returns the interface that owns the given IP (any namespace).
func (d *DB) InterfaceByIP(ip string) (*Interface, error) {
	rows, err := d.sql.Query(`SELECT name,namespace,vrf,ifindex,kind,state,flags,mac,mtu,master,peer,peer_index,ips FROM interfaces`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	target, _ := netip.ParseAddr(ip)
	for rows.Next() {
		var iface Interface
		var flagsJSON, ipsJSON string
		if err := rows.Scan(&iface.Name, &iface.Namespace, &iface.VRF, &iface.IfIndex, &iface.Kind, &iface.State,
			&flagsJSON, &iface.MAC, &iface.MTU, &iface.Master, &iface.Peer, &iface.PeerIndex, &ipsJSON); err != nil {
			return nil, err
		}
		json.Unmarshal([]byte(ipsJSON), &iface.IPs)
		for _, cidr := range iface.IPs {
			if prefix, err := netip.ParsePrefix(cidr); err == nil && prefix.Contains(target) {
				return &iface, nil
			}
		}
	}
	return nil, rows.Err()
}

func (d *DB) GetRules(namespace string) ([]Rule, error) {
	rows, err := d.sql.Query(`SELECT namespace,vrf,priority,from_prefix,table_id,fwmark,action
		FROM rules WHERE namespace=? ORDER BY priority ASC`, namespace)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []Rule
	for rows.Next() {
		var r Rule
		if err := rows.Scan(&r.Namespace, &r.VRF, &r.Priority, &r.FromPrefix, &r.TableID, &r.FWMark, &r.Action); err != nil {
			return nil, err
		}
		out = append(out, r)
	}
	return out, rows.Err()
}

func (d *DB) GetRoutes(namespace, tableID string) ([]Route, error) {
	rows, err := d.sql.Query(`SELECT namespace,vrf,table_id,prefix,preferred_src,metric,protocol,scope,route_type,flags,next_hops
		FROM routes WHERE namespace=? AND table_id=?
		ORDER BY length(prefix) DESC, metric ASC`, namespace, tableID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []Route
	for rows.Next() {
		var r Route
		var flagsJSON, nhJSON string
		if err := rows.Scan(&r.Namespace, &r.VRF, &r.TableID, &r.Prefix, &r.PreferredSrc,
			&r.Metric, &r.Protocol, &r.Scope, &r.RouteType, &flagsJSON, &nhJSON); err != nil {
			return nil, err
		}
		json.Unmarshal([]byte(flagsJSON), &r.Flags)
		json.Unmarshal([]byte(nhJSON), &r.NextHops)
		out = append(out, r)
	}
	return out, rows.Err()
}

func (d *DB) GetNeighbor(ip string) (*Neighbor, error) {
	var n Neighbor
	err := d.sql.QueryRow(`SELECT namespace,vrf,ip,dev,mac,state,reachable
		FROM neighbors WHERE ip=? LIMIT 1`, ip).
		Scan(&n.Namespace, &n.VRF, &n.IP, &n.Dev, &n.MAC, &n.State, &n.Reachable)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	return &n, err
}

func (d *DB) IsOvsBridge(name string) bool {
	var id int64
	err := d.sql.QueryRow(`SELECT id FROM ovs_bridges WHERE name=?`, name).Scan(&id)
	return err == nil
}

func (d *DB) OvsPortByName(name string) (*OvsPort, error) {
	var p OvsPort
	var tvJSON, optJSON string
	err := d.sql.QueryRow(`SELECT bridge,port,interface,port_type,ofport,vlan_tag,trunk_vlans,mac,options
		FROM ovs_ports WHERE (port=? OR interface=?) LIMIT 1`, name, name).
		Scan(&p.Bridge, &p.Port, &p.Interface, &p.PortType, &p.OFPort,
			&p.VlanTag, &tvJSON, &p.MAC, &optJSON)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	json.Unmarshal([]byte(tvJSON), &p.TrunkVlans)
	json.Unmarshal([]byte(optJSON), &p.Options)
	return &p, nil
}

func (d *DB) OvsPortByOFPort(bridge string, ofport int) (*OvsPort, error) {
	var p OvsPort
	var tvJSON, optJSON string
	err := d.sql.QueryRow(`SELECT bridge,port,interface,port_type,ofport,vlan_tag,trunk_vlans,mac,options
		FROM ovs_ports WHERE bridge=? AND ofport=? LIMIT 1`, bridge, ofport).
		Scan(&p.Bridge, &p.Port, &p.Interface, &p.PortType, &p.OFPort,
			&p.VlanTag, &tvJSON, &p.MAC, &optJSON)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	json.Unmarshal([]byte(tvJSON), &p.TrunkVlans)
	json.Unmarshal([]byte(optJSON), &p.Options)
	return &p, nil
}

func (d *DB) GetOvsFlows(bridge string, tableID int) ([]OvsFlow, error) {
	rows, err := d.sql.Query(`SELECT bridge,table_id,priority,cookie,match,actions,match_fields,action_list,n_packets,n_bytes
		FROM ovs_flows WHERE bridge=? AND table_id=?
		ORDER BY priority DESC`, bridge, tableID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []OvsFlow
	for rows.Next() {
		var f OvsFlow
		var mfJSON, alJSON string
		if err := rows.Scan(&f.Bridge, &f.TableID, &f.Priority, &f.Cookie,
			&f.Match, &f.Actions, &mfJSON, &alJSON, &f.NPackets, &f.NBytes); err != nil {
			return nil, err
		}
		json.Unmarshal([]byte(mfJSON), &f.MatchFields)
		json.Unmarshal([]byte(alJSON), &f.ActionList)
		out = append(out, f)
	}
	return out, rows.Err()
}

func (d *DB) GetOvsGroup(bridge string, groupID int) (*OvsGroup, error) {
	var g OvsGroup
	var gfk int64
	err := d.sql.QueryRow(`SELECT id,bridge,group_id,group_type,packet_count,byte_count
		FROM ovs_groups WHERE bridge=? AND group_id=?`, bridge, groupID).
		Scan(&gfk, &g.Bridge, &g.GroupID, &g.GroupType, &g.PacketCount, &g.ByteCount)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	rows, err := d.sql.Query(`SELECT bucket_id,weight,actions,action_list,watch_port,watch_group,active,packet_count,byte_count
		FROM ovs_group_buckets WHERE group_fk=? ORDER BY bucket_id`, gfk)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		var b OvsGroupBucket
		var alJSON string
		if err := rows.Scan(&b.BucketID, &b.Weight, &b.Actions, &alJSON,
			&b.WatchPort, &b.WatchGroup, &b.Active, &b.PacketCount, &b.ByteCount); err != nil {
			return nil, err
		}
		json.Unmarshal([]byte(alJSON), &b.ActionList)
		g.Buckets = append(g.Buckets, b)
	}
	return &g, rows.Err()
}

func (d *DB) GetOvsFDB(bridge string) ([]OvsFDBEntry, error) {
	rows, err := d.sql.Query(`SELECT bridge,port,vlan,mac,age_sec
		FROM ovs_fdb WHERE bridge=?`, bridge)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []OvsFDBEntry
	for rows.Next() {
		var e OvsFDBEntry
		if err := rows.Scan(&e.Bridge, &e.Port, &e.VLAN, &e.MAC, &e.AgeSec); err != nil {
			return nil, err
		}
		out = append(out, e)
	}
	return out, rows.Err()
}

func (d *DB) GetOvsTnlARP(bridge, ip string) (*OvsTnlARP, error) {
	var a OvsTnlARP
	err := d.sql.QueryRow(`SELECT bridge,ip,mac,port FROM ovs_tnl_arp
		WHERE bridge=? AND ip=? LIMIT 1`, bridge, ip).
		Scan(&a.Bridge, &a.IP, &a.MAC, &a.Port)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	return &a, err
}

func (d *DB) GetOvsBridges() ([]OvsBridge, error) {
	rows, err := d.sql.Query(`SELECT name,datapath_id,datapath_type FROM ovs_bridges`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []OvsBridge
	for rows.Next() {
		var b OvsBridge
		rows.Scan(&b.Name, &b.DatapathID, &b.DatapathType)
		out = append(out, b)
	}
	return out, rows.Err()
}

func (d *DB) GetFrrInfo(command string) ([]FrrInfo, error) {
	var rows *sql.Rows
	var err error
	if command != "" {
		rows, err = d.sql.Query(`SELECT command, output, status FROM frr_info WHERE command=?`, command)
	} else {
		rows, err = d.sql.Query(`SELECT command, output, status FROM frr_info ORDER BY command`)
	}
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []FrrInfo
	for rows.Next() {
		var f FrrInfo
		if err := rows.Scan(&f.Command, &f.Output, &f.Status); err != nil {
			return nil, err
		}
		out = append(out, f)
	}
	return out, rows.Err()
}

func (d *DB) GetOvsPorts(bridge string) ([]OvsPort, error) {
	rows, err := d.sql.Query(`SELECT bridge,port,interface,port_type,ofport,vlan_tag,trunk_vlans,mac,options
		FROM ovs_ports WHERE bridge=?`, bridge)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []OvsPort
	for rows.Next() {
		var p OvsPort
		var tvJSON, optJSON string
		rows.Scan(&p.Bridge, &p.Port, &p.Interface, &p.PortType, &p.OFPort,
			&p.VlanTag, &tvJSON, &p.MAC, &optJSON)
		json.Unmarshal([]byte(tvJSON), &p.TrunkVlans)
		json.Unmarshal([]byte(optJSON), &p.Options)
		out = append(out, p)
	}
	return out, rows.Err()
}
