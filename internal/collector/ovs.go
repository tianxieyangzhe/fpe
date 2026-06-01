package collector

import (
	"regexp"
	"strconv"
	"strings"

	"github.com/yangshuai/fpe/internal/db"
	"github.com/yangshuai/fpe/internal/logs"
)

func runOvsOfctl(e Executor, cmd string) (string, error) {
	out, err := e.Run(cmd)
	if err != nil {
		logs.Warnf("ovs-ofctl failed, retrying with -Oopenflow13: %v", err)
		out, err = e.Run(cmd + " -Oopenflow13")
	}
	return out, err
}

func CollectOVS(e Executor) ([]db.OvsBridge, []db.OvsPort, []db.OvsFlow, []db.OvsGroup, []db.OvsFDBEntry, []db.OvsTnlARP, error) {
	bridgeOut, err := e.Run("ovs-vsctl list-br")
	if err != nil {
		// exit 127 = command not found, OVS not installed
		if strings.Contains(err.Error(), "status 127") || strings.Contains(err.Error(), "not found") {
			return nil, nil, nil, nil, nil, nil, nil
		}
		return nil, nil, nil, nil, nil, nil, err
	}

	var bridges []db.OvsBridge
	var ports []db.OvsPort
	var flows []db.OvsFlow
	var groups []db.OvsGroup
	var fdbs []db.OvsFDBEntry
	var tnlArps []db.OvsTnlARP

	for _, br := range strings.Split(bridgeOut, "\n") {
		br = strings.TrimSpace(br)
		if br == "" {
			continue
		}

		dpid, err := e.Run("ovs-vsctl get bridge " + br + " datapath_id")
		if err != nil {
			logs.Warnf("get bridge datapath_id failed bridge=%s: %v", br, err)
		}
		dptype, err := e.Run("ovs-vsctl get bridge " + br + " datapath_type")
		if err != nil {
			logs.Warnf("get bridge datapath_type failed bridge=%s: %v", br, err)
		}
		bridges = append(bridges, db.OvsBridge{
			Name:         br,
			DatapathID:   strings.Trim(dpid, `"`),
			DatapathType: strings.Trim(dptype, `"`),
		})

		brPorts, err := collectOvsPorts(e, br)
		if err != nil {
			logs.Errorf("ovs ports collection failed bridge=%s: %v", br, err)
		}
		ports = append(ports, brPorts...)

		brFlows, err := collectOvsFlows(e, br)
		if err != nil {
			logs.Errorf("ovs flows collection failed bridge=%s: %v", br, err)
		}
		flows = append(flows, brFlows...)

		brGroups, err := collectOvsGroups(e, br)
		if err != nil {
			logs.Errorf("ovs groups collection failed bridge=%s: %v", br, err)
		}
		groups = append(groups, brGroups...)

		brFDB, err := collectOvsFDB(e, br)
		if err != nil {
			logs.Errorf("ovs fdb collection failed bridge=%s: %v", br, err)
		}
		fdbs = append(fdbs, brFDB...)

		brTnlARP, err := collectOvsTnlARP(e, br)
		if err != nil {
			logs.Errorf("ovs tnl-arp collection failed bridge=%s: %v", br, err)
		}
		tnlArps = append(tnlArps, brTnlARP...)
	}
	return bridges, ports, flows, groups, fdbs, tnlArps, nil
}

var reOvsPort = regexp.MustCompile(`^\s+Port\s+(\S+)`)
var reOvsIface = regexp.MustCompile(`^\s+Interface\s+(\S+)`)
var reOvsPortType = regexp.MustCompile(`type:\s+(\S+)`)
var reOvsOFPort = regexp.MustCompile(`ofport:\s+(-?\d+)`)
var reOvsVlanTag = regexp.MustCompile(`tag:\s+(\d+)`)
var reOvsMAC = regexp.MustCompile(`mac_in_use\s*:\s*"([^"]+)"`)
var reOvsOptions = regexp.MustCompile(`options\s*:\s*\{([^}]*)\}`)

func collectOvsPorts(exec Executor, bridge string) ([]db.OvsPort, error) {
	out, err := exec.Run("ovs-vsctl show")
	if err != nil {
		return nil, err
	}
	// parse per-bridge section
	var ports []db.OvsPort
	inBridge := false
	var cur *db.OvsPort
	for _, line := range strings.Split(out, "\n") {
		if strings.Contains(line, "Bridge "+bridge) {
			inBridge = true
			continue
		}
		if inBridge && strings.HasPrefix(strings.TrimSpace(line), "Bridge ") {
			break
		}
		if !inBridge {
			continue
		}
		if m := reOvsPort.FindStringSubmatch(line); m != nil {
			if cur != nil {
				ports = append(ports, *cur)
			}
			name := strings.Trim(m[1], `"`)
			cur = &db.OvsPort{Bridge: bridge, Port: name, Options: map[string]string{}}
		}
		if cur == nil {
			continue
		}
		if m := reOvsIface.FindStringSubmatch(line); m != nil {
			cur.Interface = strings.Trim(m[1], `"`)
		}
		if m := reOvsPortType.FindStringSubmatch(line); m != nil {
			cur.PortType = m[1]
			if cur.PortType == "" {
				cur.PortType = "system"
			}
		}
		if m := reOvsOFPort.FindStringSubmatch(line); m != nil {
			cur.OFPort, _ = strconv.Atoi(m[1])
		}
		if m := reOvsVlanTag.FindStringSubmatch(line); m != nil {
			cur.VlanTag, _ = strconv.Atoi(m[1])
		}
		if m := reOvsMAC.FindStringSubmatch(line); m != nil {
			cur.MAC = m[1]
		}
		if m := reOvsOptions.FindStringSubmatch(line); m != nil {
			cur.Options = parseKVPairs(m[1])
		}
	}
	if cur != nil {
		ports = append(ports, *cur)
	}

	// get ofport for each port via ovs-vsctl
	for i := range ports {
		if ports[i].OFPort == 0 {
			ofp, err := exec.Run("ovs-vsctl get Interface " + ports[i].Port + " ofport")
			if err != nil {
				logs.Warnf("get ofport failed port=%s: %v", ports[i].Port, err)
			}
			ports[i].OFPort, _ = strconv.Atoi(strings.TrimSpace(ofp))
		}
	}
	return ports, nil
}

var reFlowLine = regexp.MustCompile(`table=(\d+).*priority=(\d+)`)
var reCookie = regexp.MustCompile(`cookie=(\S+?)(?:,|$)`)
var reNPackets = regexp.MustCompile(`n_packets=(\d+)`)
var reNBytes = regexp.MustCompile(`n_bytes=(\d+)`)

func collectOvsFlows(exec Executor, bridge string) ([]db.OvsFlow, error) {
	out, err := runOvsOfctl(exec, "ovs-ofctl dump-flows "+bridge+" --no-names --stats")
	if err != nil {
		return nil, err
	}
	var flows []db.OvsFlow
	for _, line := range strings.Split(out, "\n") {
		line = strings.TrimSpace(line)
		if line == "" || strings.HasPrefix(line, "NXST_FLOW") || strings.HasPrefix(line, "OFPST_FLOW") {
			continue
		}
		f := parseOvsFlow(bridge, line)
		if f != nil {
			flows = append(flows, *f)
		}
	}
	return flows, nil
}

func parseOvsFlow(bridge, line string) *db.OvsFlow {
	m := reFlowLine.FindStringSubmatch(line)
	if m == nil {
		return nil
	}
	f := db.OvsFlow{Bridge: bridge}
	f.TableID, _ = strconv.Atoi(m[1])
	f.Priority, _ = strconv.Atoi(m[2])

	if cm := reCookie.FindStringSubmatch(line); cm != nil {
		f.Cookie = cm[1]
	}
	if pm := reNPackets.FindStringSubmatch(line); pm != nil {
		n, _ := strconv.ParseInt(pm[1], 10, 64)
		f.NPackets = &n
	}
	if bm := reNBytes.FindStringSubmatch(line); bm != nil {
		n, _ := strconv.ParseInt(bm[1], 10, 64)
		f.NBytes = &n
	}

	// split match and actions
	parts := strings.SplitN(line, " actions=", 2)
	if len(parts) == 2 {
		f.Actions = parts[1]
		f.ActionList = parseActionList(parts[1])
		// match is everything after the stats fields
		matchPart := parts[0]
		if idx := strings.Index(matchPart, " "); idx >= 0 {
			// strip leading stats (cookie=..., duration=..., etc.)
			matchPart = extractMatch(matchPart)
		}
		f.Match = matchPart
		f.MatchFields = parseMatchFields(matchPart)
	}
	return &f
}

// extractMatch strips OVS stats prefix and returns the match portion.
func extractMatch(s string) string {
	// stats fields end before the actual match; match starts after last comma-separated stat
	statFields := []string{"cookie=", "duration=", "table=", "n_packets=", "n_bytes=",
		"idle_age=", "hard_age=", "idle_timeout=", "hard_timeout=", "importance=", "send_flow_rem"}
	parts := strings.Split(s, ",")
	var matchParts []string
	for _, p := range parts {
		isStat := false
		for _, sf := range statFields {
			if strings.HasPrefix(strings.TrimSpace(p), sf) {
				isStat = true
				break
			}
		}
		if !isStat {
			matchParts = append(matchParts, p)
		}
	}
	return strings.Join(matchParts, ",")
}

func parseMatchFields(match string) map[string]string {
	fields := map[string]string{}
	for _, part := range strings.Split(match, ",") {
		part = strings.TrimSpace(part)
		if part == "" {
			continue
		}
		if strings.Contains(part, "=") {
			kv := strings.SplitN(part, "=", 2)
			fields[kv[0]] = kv[1]
		} else {
			// protocol keywords: ip, tcp, udp, icmp, arp, ipv6, etc.
			fields["proto"] = part
		}
	}
	return fields
}

func parseActionList(actions string) []string {
	var list []string
	// handle nested parens (e.g. learn(...), ct(...))
	depth := 0
	cur := strings.Builder{}
	for _, ch := range actions {
		switch ch {
		case '(':
			depth++
			cur.WriteRune(ch)
		case ')':
			depth--
			cur.WriteRune(ch)
		case ',':
			if depth == 0 {
				if s := strings.TrimSpace(cur.String()); s != "" {
					list = append(list, s)
				}
				cur.Reset()
			} else {
				cur.WriteRune(ch)
			}
		default:
			cur.WriteRune(ch)
		}
	}
	if s := strings.TrimSpace(cur.String()); s != "" {
		list = append(list, s)
	}
	return list
}

var reGroupLine = regexp.MustCompile(`group_id=(\d+),type=(\S+?)(?:,|$)`)
var reBucket = regexp.MustCompile(`bucket=(?:bucket_id=(\d+),)?(?:weight:(\d+),)?(?:watch_port:(\d+),)?(?:watch_group:(\d+),)?actions=(.+?)(?:$|bucket=)`)
var reGroupStats = regexp.MustCompile(`packet_count=(\d+),byte_count=(\d+)`)

func collectOvsGroups(exec Executor, bridge string) ([]db.OvsGroup, error) {
	out, err := runOvsOfctl(exec, "ovs-ofctl dump-groups "+bridge+" --no-names")
	if err != nil {
		return nil, err
	}
	statsOut, err := runOvsOfctl(exec, "ovs-ofctl dump-group-stats "+bridge)
	if err != nil {
		logs.Warnf("dump-group-stats failed bridge=%s: %v", bridge, err)
	}

	statsMap := parseGroupStats(statsOut)
	var groups []db.OvsGroup
	for _, line := range strings.Split(out, "\n") {
		line = strings.TrimSpace(line)
		if line == "" || strings.HasPrefix(line, "NXST") || strings.HasPrefix(line, "OFPST") {
			continue
		}
		m := reGroupLine.FindStringSubmatch(line)
		if m == nil {
			continue
		}
		gid, _ := strconv.Atoi(m[1])
		g := db.OvsGroup{
			Bridge:    bridge,
			GroupID:   gid,
			GroupType: m[2],
		}
		if s, ok := statsMap[gid]; ok {
			g.PacketCount = s[0]
			g.ByteCount = s[1]
		}
		g.Buckets = parseBuckets(line)
		groups = append(groups, g)
	}
	return groups, nil
}

func parseBuckets(line string) []db.OvsGroupBucket {
	var buckets []db.OvsGroupBucket
	// split on "bucket=" keyword
	parts := strings.Split(line, "bucket=")
	for i, part := range parts[1:] {
		b := db.OvsGroupBucket{BucketID: i, Weight: 1}
		// bucket_id
		if m := regexp.MustCompile(`bucket_id=(\d+)`).FindStringSubmatch(part); m != nil {
			b.BucketID, _ = strconv.Atoi(m[1])
		}
		// weight
		if m := regexp.MustCompile(`weight:(\d+)`).FindStringSubmatch(part); m != nil {
			b.Weight, _ = strconv.Atoi(m[1])
		}
		// watch_port
		if m := regexp.MustCompile(`watch_port:(\d+)`).FindStringSubmatch(part); m != nil {
			wp, _ := strconv.Atoi(m[1])
			b.WatchPort = &wp
		}
		// watch_group
		if m := regexp.MustCompile(`watch_group:(\d+)`).FindStringSubmatch(part); m != nil {
			wg, _ := strconv.Atoi(m[1])
			b.WatchGroup = &wg
		}
		// actions
		if m := regexp.MustCompile(`actions=(.+)`).FindStringSubmatch(part); m != nil {
			b.Actions = m[1]
			b.ActionList = parseActionList(m[1])
		}
		buckets = append(buckets, b)
	}
	return buckets
}

func parseGroupStats(out string) map[int][2]int64 {
	m := map[int][2]int64{}
	for _, line := range strings.Split(out, "\n") {
		gm := regexp.MustCompile(`group_id=(\d+).*packet_count=(\d+),byte_count=(\d+)`).FindStringSubmatch(line)
		if gm == nil {
			continue
		}
		gid, _ := strconv.Atoi(gm[1])
		pc, _ := strconv.ParseInt(gm[2], 10, 64)
		bc, _ := strconv.ParseInt(gm[3], 10, 64)
		m[gid] = [2]int64{pc, bc}
	}
	return m
}

var reFDBLine = regexp.MustCompile(`^\s*(\d+)\s+(\S+)\s+(\S+)\s+(\d+)`)

func collectOvsFDB(exec Executor, bridge string) ([]db.OvsFDBEntry, error) {
	out, err := exec.Run("ovs-appctl fdb/show " + bridge)
	if err != nil {
		return nil, err
	}
	var entries []db.OvsFDBEntry
	for _, line := range strings.Split(out, "\n") {
		m := reFDBLine.FindStringSubmatch(line)
		if m == nil {
			continue
		}
		age, _ := strconv.Atoi(m[4])
		entries = append(entries, db.OvsFDBEntry{
			Bridge: bridge,
			Port:   m[2],
			VLAN:   func() int { v, _ := strconv.Atoi(m[1]); return v }(),
			MAC:    m[3],
			AgeSec: &age,
		})
	}
	return entries, nil
}

var reTnlARP = regexp.MustCompile(`^(\S+)\s+(\S+)\s+(\S+)`)

func collectOvsTnlARP(exec Executor, bridge string) ([]db.OvsTnlARP, error) {
	out, err := exec.Run("ovs-appctl tnl/arp/show")
	if err != nil {
		return nil, err
	}
	var entries []db.OvsTnlARP
	for _, line := range strings.Split(out, "\n") {
		line = strings.TrimSpace(line)
		if line == "" || strings.HasPrefix(line, "IP") {
			continue
		}
		m := reTnlARP.FindStringSubmatch(line)
		if m == nil {
			continue
		}
		entries = append(entries, db.OvsTnlARP{
			Bridge: bridge,
			IP:     m[1],
			MAC:    m[2],
			Port:   m[3],
		})
	}
	return entries, nil
}

func parseKVPairs(s string) map[string]string {
	m := map[string]string{}
	for _, part := range strings.Split(s, ",") {
		part = strings.TrimSpace(part)
		kv := strings.SplitN(part, "=", 2)
		if len(kv) == 2 {
			m[strings.Trim(kv[0], `"`)] = strings.Trim(kv[1], `"`)
		}
	}
	return m
}
