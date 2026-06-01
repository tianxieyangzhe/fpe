package collector

import (
	"encoding/json"
	"fmt"
	"strings"

	"github.com/yangshuai/fpe/internal/db"
	"github.com/yangshuai/fpe/internal/logs"
)

// jsonVrfLink matches VRF master devices from "ip -json link show type vrf"
type jsonVrfLink struct {
	IfName string `json:"ifname"`
}

// CollectVRFs discovers VRF L3 master devices in a namespace.
func CollectVRFs(exec Executor, namespace string) ([]string, error) {
	// Primary: ip -json link show type vrf
	out, err := exec.Run(buildNSCmd(namespace, "ip -json link show type vrf"))
	if err == nil && out != "" {
		var links []jsonVrfLink
		if err := json.Unmarshal([]byte(out), &links); err == nil {
			vrfs := make([]string, 0, len(links))
			for _, l := range links {
				if l.IfName != "" {
					vrfs = append(vrfs, l.IfName)
				}
			}
			if len(vrfs) > 0 {
				return vrfs, nil
			}
		}
	}

	// Fallback: ip vrf show (text output, no JSON flag support)
	out, err = exec.Run(buildNSCmd(namespace, "ip vrf show"))
	if err != nil {
		return nil, err
	}
	var vrfs []string
	for _, line := range strings.Split(out, "\n") {
		line = strings.TrimSpace(line)
		if line == "" || strings.HasPrefix(line, "Name") {
			continue
		}
		name := strings.Fields(line)[0]
		if name != "" {
			vrfs = append(vrfs, name)
		}
	}
	return vrfs, nil
}

// CollectVRFRoutes collects routes for a specific VRF.
func CollectVRFRoutes(exec Executor, namespace, vrf string) ([]db.Route, error) {
	out, err := exec.Run(buildNSCmd(namespace, "ip -json route show vrf "+vrf))
	if err != nil {
		return nil, err
	}

	var jr []jsonRoute
	if err := json.Unmarshal([]byte(out), &jr); err != nil {
		return nil, fmt.Errorf("parse ip route json vrf %s: %w", vrf, err)
	}

	var routes []db.Route
	for _, r := range jr {
		rt := db.Route{
			Namespace:    namespace,
			VRF:          vrf,
			TableID:      vrfTableID(vrf),
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

// CollectVRFNeighbors collects neighbors for a specific VRF.
func CollectVRFNeighbors(exec Executor, namespace, vrf string) ([]db.Neighbor, error) {
	out, err := exec.Run(buildNSCmd(namespace, "ip -json neigh show vrf "+vrf))
	if err != nil {
		logs.Debugf("ip neigh show vrf failed: %v", err)
		return nil, err
	}

	var jn []jsonNeigh
	if err := json.Unmarshal([]byte(out), &jn); err != nil {
		return nil, fmt.Errorf("parse ip neigh json vrf %s: %w", vrf, err)
	}

	neighbors := make([]db.Neighbor, 0, len(jn))
	for _, n := range jn {
		neighbors = append(neighbors, db.Neighbor{
			Namespace: namespace,
			VRF:       vrf,
			IP:        n.Dst,
			Dev:       n.Dev,
			MAC:       n.LLAddr,
			State:     db.JoinStates(n.State),
			Reachable: db.IsReachable(n.State),
		})
	}
	return neighbors, nil
}

// CollectVRFRules collects ip rules that reference a specific VRF.
func CollectVRFRules(exec Executor, namespace, vrf string) ([]db.Rule, error) {
	allRules, err := CollectRules(exec, namespace)
	if err != nil {
		return nil, err
	}
	var rules []db.Rule
	for _, r := range allRules {
		if strings.Contains(r.TableID, vrf) || strings.Contains(r.FromPrefix, vrf) {
			r.VRF = vrf
			rules = append(rules, r)
		}
	}
	return rules, nil
}

func vrfTableID(vrf string) string { return vrf }
