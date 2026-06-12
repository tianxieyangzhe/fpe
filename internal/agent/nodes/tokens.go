package nodes

import (
	"context"
	"regexp"
	"sort"
	"strconv"
	"strings"

	"github.com/yangshuai/fpe/internal/agent"
	"github.com/yangshuai/fpe/internal/agent/source"
	"github.com/yangshuai/fpe/internal/db"
	"github.com/yangshuai/fpe/internal/logs"
	"github.com/yangshuai/fpe/internal/walker"
)

var ipRegex = regexp.MustCompile(`\b(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?\b`)

var chineseKeywordMap = map[string]string{
	"隧道":   "tunnel",
	"重建":   "rebuild",
	"路由刷新": "route sync",
	"邻居":   "neighbor",
	"策略路由": "policy route",
	"断流":   "drop unreachable",
}

var sdwanKeywords = []string{
	"vrf", "vni", "vxlan", "geneve", "tunnel", "overlay", "underlay",
	"frr", "bgp", "ospf", "bfd", "route-map", "neighbor", "policy",
	"rebuild", "sync", "reconcile", "table", "cookie", "flow",
	"namespace", "ANPOSNS",
}

// cookieRegex matches OVS cookie patterns like cookie=0xabc123
var cookieRegex = regexp.MustCompile(`cookie=0x[0-9a-fA-F]+`)

func ExtractTokens(deps agent.Dependencies) func(ctx context.Context, state agent.AgentState) (agent.AgentState, error) {
	return func(ctx context.Context, state agent.AgentState) (agent.AgentState, error) {
		tokenMap := make(map[string]*agent.SearchToken)

		addToken := func(value string, typ, src string, weight int) {
			if value == "" {
				return
			}
			value = strings.TrimSpace(value)
			if existing, ok := tokenMap[value]; ok {
				if weight > existing.Weight {
					existing.Weight = weight
					existing.Source = src
					existing.Type = typ
				}
				return
			}
			tokenMap[value] = &agent.SearchToken{
				Value:  value,
				Type:   typ,
				Source: src,
				Weight: weight,
			}
		}

		// From query text
		extractFromQuery(state.Input.Query, addToken)

		// From snapshot
		extractFromSnapshot(&state.Snapshot, addToken)

		// From path result
		extractFromPath(state.PathResult, addToken)

		// From FRR
		extractFromFRR(state.Snapshot.FrrInfo, addToken)

		// Convert map to sorted slice
		var tokens []agent.SearchToken
		for _, t := range tokenMap {
			tokens = append(tokens, *t)
		}
		sort.Slice(tokens, func(i, j int) bool {
			return tokens[i].Weight > tokens[j].Weight
		})

		tokens = source.TruncateTokens(tokens, 50)
		state.Tokens = tokens

		if state.Input.Debug {
			state.DebugInfo.Tokens = tokens
		}

		logs.Debugf("extracted %d tokens", len(tokens))
		return state, nil
	}
}

func extractFromQuery(query string, addToken func(string, string, string, int)) {
	for _, match := range ipRegex.FindAllString(query, -1) {
		addToken(match, "ip", "query", agent.TokenWeightIP)
	}

	for _, kw := range sdwanKeywords {
		if strings.Contains(strings.ToLower(query), kw) {
			addToken(kw, "keyword", "query", agent.TokenWeightKeyword)
		}
	}

	for cn, en := range chineseKeywordMap {
		if strings.Contains(query, cn) {
			for _, kw := range strings.Fields(en) {
				addToken(kw, "keyword", "query", agent.TokenWeightKeyword)
			}
		}
	}
}

func extractFromSnapshot(snap *agent.SnapshotSummary, addToken func(string, string, string, int)) {
	for _, iface := range snap.Interfaces {
		addToken(iface.VRF, "vrf", "snapshot", agent.TokenWeightVRF)
		addToken(iface.Name, "interface", "snapshot", agent.TokenWeightInterface)
	}

	for _, route := range snap.Routes {
		addToken(route.Prefix, "prefix", "snapshot", agent.TokenWeightPrefix)
		addToken(route.TableID, "ovs_table", "snapshot", agent.TokenWeightOVSTable)
	}

	for _, bridge := range snap.OvsBridges {
		addToken(bridge.Name, "interface", "snapshot", agent.TokenWeightInterface)
	}
}

func extractFromPath(pathResult *walker.WalkResult, addToken func(string, string, string, int)) {
	if pathResult == nil {
		return
	}
	for _, leaf := range pathResult.Leaves {
		for _, seg := range leaf.Segments {
			for _, hop := range seg.Hops {
				addToken(strconv.Itoa(hop.TableID), "ovs_table", "path", agent.TokenWeightOVSTable)

				// Extract cookie from match string
				for _, m := range cookieRegex.FindAllString(hop.Match, -1) {
					addToken(m, "ovs_cookie", "path", agent.TokenWeightOVSCookie)
				}
				// Extract cookie from action string
				for _, m := range cookieRegex.FindAllString(hop.Action, -1) {
					addToken(m, "ovs_cookie", "path", agent.TokenWeightOVSCookie)
				}

				// Extract group references from action
				if strings.Contains(hop.Action, "group:") {
					parts := strings.Fields(hop.Action)
					for _, p := range parts {
						if strings.HasPrefix(p, "group:") {
							addToken(p, "ovs_group", "path", agent.TokenWeightOVSGroup)
						}
					}
				}
			}

			if seg.Egress != "" {
				addToken(seg.Egress, "interface", "path", agent.TokenWeightInterface)
			}
			if seg.EgressPeer != nil {
				addToken(seg.EgressPeer.RemoteIP, "ip", "path", agent.TokenWeightIP)
				if seg.EgressPeer.VNI != 0 {
					addToken(strconv.Itoa(seg.EgressPeer.VNI), "vni", "path", agent.TokenWeightVNI)
				}
			}
			addToken(seg.Namespace, "vrf", "path", agent.TokenWeightVRF)
		}
	}
}

func extractFromFRR(frrInfos []db.FrrInfo, addToken func(string, string, string, int)) {
	if frrInfos == nil {
		return
	}
	for _, f := range frrInfos {
		for _, match := range ipRegex.FindAllString(f.Output, -1) {
			addToken(match, "ip", "frr", agent.TokenWeightIP)
		}
	}
}
