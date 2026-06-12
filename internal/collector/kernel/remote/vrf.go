package remote

import (
	"fmt"
	"strconv"
	"strings"

	"github.com/yangshuai/fpe/internal/collector"
	"github.com/yangshuai/fpe/internal/db"
	"github.com/yangshuai/fpe/internal/logs"
)

type jsonVrfLink struct {
	IfName   string          `json:"ifname"`
	LinkInfo jsonVrfLinkInfo `json:"linkinfo"`
}

type jsonVrfLinkInfo struct {
	InfoData jsonVrfInfoData `json:"info_data"`
}

type jsonVrfInfoData struct {
	Table int `json:"table"`
}

func collectVRFs(exec collector.Executor, namespace string) ([]string, error) {
	vrfCmd := nsCmd(namespace, "ip -json link show type vrf")
	out, err := exec.Run(vrfCmd)
	if err == nil && out != "" {
		var links []jsonVrfLink
		if jsonArray(vrfCmd, out, &links) == nil {
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

	out, err = exec.Run(nsCmd(namespace, "ip vrf show"))
	if err != nil {
		return nil, err
	}
	var vrfs []string
	for _, line := range strings.Split(out, "\n") {
		line = strings.TrimSpace(line)
		if line == "" || strings.HasPrefix(line, "Name") || isSeparatorLine(line) {
			continue
		}
		name := strings.Fields(line)[0]
		if name != "" {
			vrfs = append(vrfs, name)
		}
	}
	return vrfs, nil
}

func collectVRFRoutes(exec collector.Executor, namespace, vrf string) ([]db.Route, error) {
	cmd := nsCmd(namespace, "ip -json route show vrf "+vrf)
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

	tableID, err := findVRFTableID(exec, namespace, vrf)
	if err != nil {
		logs.Debugf("vrf table discovery failed ns=%s vrf=%s: %v", namespace, vrf, err)
		tableID = vrf
	}

	var routes []db.Route
	for _, r := range jr {
		rt := db.Route{
			Namespace:    namespace,
			VRF:          vrf,
			TableID:      tableID,
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

func collectVRFNeighbors(exec collector.Executor, namespace, vrf string) ([]db.Neighbor, error) {
	cmd := nsCmd(namespace, "ip -json neigh show vrf "+vrf)
	out, err := exec.Run(cmd)
	if err != nil {
		logs.Debugf("ip neigh show vrf failed: %v", err)
		return nil, err
	}

	if strings.TrimSpace(out) == "" {
		return nil, nil
	}

	var jn []jsonNeigh
	if err := jsonArray(cmd, out, &jn); err != nil {
		return nil, err
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

func collectVRFRules(exec collector.Executor, namespace, vrf string) ([]db.Rule, error) {
	tableID, err := findVRFTableID(exec, namespace, vrf)
	if err != nil {
		return nil, err
	}

	allRules, err := collectRules(exec, namespace)
	if err != nil {
		return nil, err
	}
	var rules []db.Rule
	for _, r := range allRules {
		if r.TableID == tableID {
			r.VRF = vrf
			rules = append(rules, r)
		}
	}
	return rules, nil
}

func findVRFTableID(exec collector.Executor, namespace, vrf string) (string, error) {
	cmd := nsCmd(namespace, "ip -d -json link show type vrf")
	out, err := exec.Run(cmd)
	if err == nil && strings.TrimSpace(out) != "" {
		var links []jsonVrfLink
		if jsonArray(cmd, out, &links) == nil {
			for _, l := range links {
				if l.IfName == vrf && l.LinkInfo.InfoData.Table != 0 {
					return strconv.Itoa(l.LinkInfo.InfoData.Table), nil
				}
			}
		}
	}

	out, err = exec.Run(nsCmd(namespace, "ip vrf show"))
	if err != nil {
		return "", err
	}
	for _, line := range strings.Split(out, "\n") {
		line = strings.TrimSpace(line)
		if line == "" || strings.HasPrefix(line, "Name") || isSeparatorLine(line) {
			continue
		}
		fields := strings.Fields(line)
		if len(fields) >= 2 && fields[0] == vrf {
			return fields[1], nil
		}
	}
	return "", fmt.Errorf("vrf table not found: %s", vrf)
}

func isSeparatorLine(line string) bool {
	dashes := 0
	for _, c := range line {
		if c == '-' {
			dashes++
		}
	}
	return dashes >= 5 && dashes >= len(strings.TrimSpace(line))-1
}
