//go:build linux

package netlink

import (
	"fmt"
	"net"
	"strconv"

	nl "github.com/vishvananda/netlink"
	"github.com/yangshuai/fpe/internal/db"
	"github.com/yangshuai/fpe/internal/logs"
)

func collectRoutes(namespace string) ([]db.Route, error) {
	restore, err := enterNS(namespace)
	if err != nil {
		return nil, err
	}
	defer restore()

	tables := map[int]string{255: "local", 254: "main", 253: "default"}

	rules, err := nl.RuleList(0)
	if err == nil {
		for _, r := range rules {
			if r.Table != 0 && r.Table != 255 && r.Table != 254 && r.Table != 253 {
				key := strconv.Itoa(r.Table)
				tables[r.Table] = key
			}
		}
	} else {
		logs.Debugf("rule list for table discovery failed: %v", err)
	}

	var routes []db.Route
	for tableID, tableName := range tables {
		tableRoutes, err := collectTableRoutes(tableID, tableName, namespace, nil)
		if err != nil {
			logs.Warnf("route table %s collection failed: %v", tableName, err)
			continue
		}
		routes = append(routes, tableRoutes...)
	}
	return routes, nil
}

func collectTableRoutes(tableID int, tableName, namespace string, linkNames map[int]string) ([]db.Route, error) {
	filter := &nl.Route{Table: tableID}
	nlroutes, err := nl.RouteListFiltered(0, filter, nl.RT_FILTER_TABLE)
	if err != nil {
		return nil, err
	}
	if linkNames == nil {
		linkNames = collectLinkNames()
	}

	routes := make([]db.Route, 0, len(nlroutes))
	for _, r := range nlroutes {
		rt := db.Route{
			Namespace:    namespace,
			TableID:      tableName,
			Prefix:       routePrefixString(r.Dst),
			PreferredSrc: ipString(r.Src),
			Metric:       r.Priority,
			Protocol:     routeProtocolString(r.Protocol),
			Scope:        scopeString(r.Scope),
			RouteType:    routeTypeString(r.Type),
			Flags:        routeFlagsToStrings(r.Flags),
		}

		if len(r.MultiPath) > 0 {
			for _, nh := range r.MultiPath {
				w := nh.Hops
				if w == 0 {
					w = 1
				}
				rt.NextHops = append(rt.NextHops, db.NextHop{
					Via:    nh.Gw.String(),
					Dev:    linkNames[nh.LinkIndex],
					Weight: w,
				})
			}
		} else {
			rt.NextHops = []db.NextHop{{
				Via:    ipString(r.Gw),
				Dev:    linkNames[r.LinkIndex],
				Weight: 1,
			}}
		}
		routes = append(routes, rt)
	}
	return routes, nil
}

func collectVRFRoutes(namespace string, vrfName string, vrfTable int) ([]db.Route, error) {
	restore, err := enterNS(namespace)
	if err != nil {
		return nil, err
	}
	defer restore()
	if vrfTable == 0 {
		info, err := getVRFInfo(vrfName)
		if err != nil {
			return nil, err
		}
		vrfTable = info.Table
	}
	if vrfTable == 0 {
		return nil, nil
	}

	filter := &nl.Route{Table: vrfTable}
	nlroutes, err := nl.RouteListFiltered(0, filter, nl.RT_FILTER_TABLE)
	if err != nil {
		return nil, err
	}

	tableName := strconv.Itoa(vrfTable)
	linkNames := collectLinkNames()
	routes := make([]db.Route, 0, len(nlroutes))
	for _, r := range nlroutes {
		rt := db.Route{
			Namespace:    namespace,
			VRF:          vrfName,
			TableID:      tableName,
			Prefix:       routePrefixString(r.Dst),
			PreferredSrc: ipString(r.Src),
			Metric:       r.Priority,
			Protocol:     routeProtocolString(r.Protocol),
			Scope:        scopeString(r.Scope),
			RouteType:    routeTypeString(r.Type),
			Flags:        routeFlagsToStrings(r.Flags),
		}
		if len(r.MultiPath) > 0 {
			for _, nh := range r.MultiPath {
				w := nh.Hops
				if w == 0 {
					w = 1
				}
				rt.NextHops = append(rt.NextHops, db.NextHop{
					Via:    nh.Gw.String(),
					Dev:    linkNames[nh.LinkIndex],
					Weight: w,
				})
			}
		} else {
			rt.NextHops = []db.NextHop{{
				Via:    ipString(r.Gw),
				Dev:    linkNames[r.LinkIndex],
				Weight: 1,
			}}
		}
		routes = append(routes, rt)
	}
	return routes, nil
}

func collectLinkNames() map[int]string {
	links, err := nl.LinkList()
	if err != nil {
		return nil
	}
	linkNames := make(map[int]string, len(links))
	for _, l := range links {
		linkNames[l.Attrs().Index] = l.Attrs().Name
	}
	return linkNames
}

func routePrefixString(dst *net.IPNet) string {
	if dst == nil {
		return "default"
	}
	return dst.String()
}

func ipString(ip net.IP) string {
	if ip == nil || ip.IsUnspecified() {
		return ""
	}
	return ip.String()
}

func routeProtocolString(p nl.RouteProtocol) string {
	switch p {
	case 0:
		return "kernel"
	case 2:
		return "kernel"
	case 3:
		return "boot"
	case 4:
		return "static"
	case 5:
		return "redirect"
	case 6:
		return "dhcp"
	case 186:
		return "bgp"
	case 188:
		return "ospf"
	case 189:
		return "rip"
	case 191:
		return "isis"
	case 192:
		return "eigrp"
	default:
		return fmt.Sprintf("proto_%d", p)
	}
}

func scopeString(s nl.Scope) string {
	switch s {
	case 0:
		return "global"
	case 200:
		return "site"
	case 253:
		return "link"
	case 254:
		return "host"
	case 255:
		return "nowhere"
	default:
		return fmt.Sprintf("scope_%d", s)
	}
}

func routeTypeString(t int) string {
	switch t {
	case 1:
		return "unicast"
	case 2:
		return "local"
	case 3:
		return "broadcast"
	case 5:
		return "multicast"
	case 6:
		return "blackhole"
	case 7:
		return "unreachable"
	case 8:
		return "prohibit"
	case 9:
		return "throw"
	default:
		return "unicast"
	}
}

func routeFlagsToStrings(flags int) []string {
	if flags == 0 {
		return nil
	}
	var out []string
	flagNames := map[int]string{
		0x0001: "notify",
		0x0002: "cloned",
		0x0004: "equalize",
		0x0008: "prefix",
		0x0010: "lookup",
		0x0200: "onlink",
	}
	for mask, name := range flagNames {
		if flags&mask != 0 {
			out = append(out, name)
		}
	}
	return out
}
