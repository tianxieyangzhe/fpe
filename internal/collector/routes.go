package collector

import (
	"encoding/json"
	"fmt"

	"github.com/yangshuai/fpe/internal/db"
	"github.com/yangshuai/fpe/internal/logs"
)

// --- JSON structs for unmarshaling ip -json route show output ---

type jsonRoute struct {
	Dst        string        `json:"dst"`
	Gateway    string        `json:"gateway,omitempty"`
	Dev        string        `json:"dev,omitempty"`
	Metric     int           `json:"metric,omitempty"`
	Protocol   string        `json:"protocol,omitempty"`
	Scope      string        `json:"scope,omitempty"`
	PrefSrc    string        `json:"prefsrc,omitempty"`
	Flags      []string      `json:"flags,omitempty"`
	Type       string        `json:"type,omitempty"`
	NextHops   []jsonNextHop `json:"nexthops,omitempty"`
}

type jsonNextHop struct {
	Via    string `json:"via,omitempty"`
	Dev    string `json:"dev,omitempty"`
	Weight int    `json:"weight,omitempty"`
}

func CollectRoutes(exec Executor, namespace string) ([]db.Route, error) {
	tables := []string{"main", "local", "default"}

	// discover custom tables from rules
	ruleOut, err := exec.Run(buildNSCmd(namespace, "ip -json rule show"))
	if err != nil {
		logs.Warnf("ip rule show for table discovery failed: %v", err)
	} else {
		var jr []struct {
			Table string `json:"table"`
		}
		if json.Unmarshal([]byte(ruleOut), &jr) == nil {
			seen := map[string]bool{"main": true, "local": true, "default": true}
			for _, r := range jr {
				if r.Table != "" && !seen[r.Table] {
					seen[r.Table] = true
					tables = append(tables, r.Table)
				}
			}
		}
	}

	var routes []db.Route
	for _, table := range tables {
		tableRoutes, err := collectTableRoutes(exec, namespace, table)
		if err != nil {
			logs.Warnf("route table %s collection failed: %v", table, err)
			continue
		}
		routes = append(routes, tableRoutes...)
	}
	return routes, nil
}

func collectTableRoutes(exec Executor, namespace, table string) ([]db.Route, error) {
	out, err := exec.Run(buildNSCmd(namespace, "ip -json route show table "+table))
	if err != nil {
		return nil, err
	}

	var jr []jsonRoute
	if err := json.Unmarshal([]byte(out), &jr); err != nil {
		return nil, fmt.Errorf("parse ip route json table %s: %w", table, err)
	}

	routes := make([]db.Route, 0, len(jr))
	for _, r := range jr {
		rt := db.Route{
			Namespace:    namespace,
			TableID:      table,
			Prefix:       normalizePrefix(r.Dst),
			PreferredSrc: r.PrefSrc,
			Metric:       r.Metric,
			Protocol:     r.Protocol,
			Scope:        r.Scope,
			RouteType:    routeTypeFromJSON(r.Type, r.Flags),
			Flags:        r.Flags,
		}

		if len(r.NextHops) > 0 {
			for _, nh := range r.NextHops {
				w := nh.Weight
				if w == 0 {
					w = 1
				}
				rt.NextHops = append(rt.NextHops, db.NextHop{
					Via:    nh.Via,
					Dev:    nh.Dev,
					Weight: w,
				})
			}
		} else {
			// single-path route
			rt.NextHops = []db.NextHop{{
				Via:    r.Gateway,
				Dev:    r.Dev,
				Weight: 1,
			}}
		}
		routes = append(routes, rt)
	}
	return routes, nil
}

func normalizePrefix(dst string) string {
	if dst == "" || dst == "default" {
		return "default"
	}
	return dst
}

func routeTypeFromJSON(typ string, flags []string) string {
	if typ != "" {
		return typ
	}
	for _, f := range flags {
		switch f {
		case "local", "broadcast", "multicast", "throw", "unreachable", "prohibit", "blackhole":
			return f
		}
	}
	return "unicast"
}
