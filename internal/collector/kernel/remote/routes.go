package remote

import (
	"strings"

	"github.com/yangshuai/fpe/internal/collector"
	"github.com/yangshuai/fpe/internal/db"
	"github.com/yangshuai/fpe/internal/logs"
)

// --- JSON structs for routes ---

type jsonRoute struct {
	Dst      string        `json:"dst"`
	Gateway  string        `json:"gateway,omitempty"`
	Dev      string        `json:"dev,omitempty"`
	Metric   int           `json:"metric,omitempty"`
	Protocol string        `json:"protocol,omitempty"`
	Scope    string        `json:"scope,omitempty"`
	PrefSrc  string        `json:"prefsrc,omitempty"`
	Flags    []string      `json:"flags,omitempty"`
	Type     string        `json:"type,omitempty"`
	NextHops []jsonNextHop `json:"nexthops,omitempty"`
}

type jsonNextHop struct {
	Via    string `json:"via,omitempty"`
	Dev    string `json:"dev,omitempty"`
	Weight int    `json:"weight,omitempty"`
}

// --- JSON structs for rules ---

type jsonRule struct {
	Priority int    `json:"priority"`
	Src      string `json:"src"`
	Table    string `json:"table"`
	FWMark   string `json:"fwmark,omitempty"`
	Action   string `json:"action,omitempty"`
}

func collectRules(exec collector.Executor, namespace string) ([]db.Rule, error) {
	cmd := nsCmd(namespace, "ip -json rule show")
	out, err := exec.Run(cmd)
	if err != nil {
		return nil, err
	}

	var jr []jsonRule
	if err := jsonArray(cmd, out, &jr); err != nil {
		return nil, err
	}

	rules := make([]db.Rule, 0, len(jr))
	for _, r := range jr {
		rules = append(rules, db.Rule{
			Namespace:  namespace,
			Priority:   r.Priority,
			FromPrefix: normalizeSrc(r.Src),
			TableID:    r.Table,
			FWMark:     r.FWMark,
			Action:     r.Action,
		})
	}
	return rules, nil
}

func normalizeSrc(s string) string {
	if s == "" || s == "all" {
		return ""
	}
	return s
}

func collectRoutes(exec collector.Executor, namespace string) ([]db.Route, error) {
	tables := []string{"main", "local", "default"}

	ruleCmd := nsCmd(namespace, "ip -json rule show")
	ruleOut, err := exec.Run(ruleCmd)
	if err != nil {
		logs.Warnf("ip rule show for table discovery failed: %v", err)
	} else {
		var jr []struct {
			Table string `json:"table"`
		}
		if jsonArray(ruleCmd, ruleOut, &jr) == nil {
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

func collectTableRoutes(exec collector.Executor, namespace, table string) ([]db.Route, error) {
	cmd := nsCmd(namespace, "ip -json route show table "+table)
	out, err := exec.Run(cmd)
	if err != nil {
		return nil, err
	}

	if strings.TrimSpace(out) == "" {
		return nil, nil
	}

	var jr []jsonRoute
	if err := jsonArray(cmd, out, &jr); err != nil {
		return nil, err
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
