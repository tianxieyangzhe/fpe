//go:build linux

package netlink

import (
	"strconv"

	nl "github.com/vishvananda/netlink"
	"github.com/yangshuai/fpe/internal/db"
	"github.com/yangshuai/fpe/internal/logs"
)

type vrfInfo struct {
	Name  string
	Index int
	Table int
}

var vrfCache map[string]vrfInfo

func collectVRFs(namespace string) ([]string, error) {
	restore, err := enterNS(namespace)
	if err != nil {
		return nil, err
	}
	defer restore()

	links, err := nl.LinkList()
	if err != nil {
		return nil, err
	}

	vrfs := make([]string, 0)
	vrfData := make(map[string]vrfInfo)
	for _, link := range links {
		if link.Type() != "vrf" {
			continue
		}
		name := link.Attrs().Name
		info := vrfInfoFromLink(link)
		if info.Table == 0 {
			logs.Warnf("vrf table discovery failed ns=%s vrf=%s", namespace, name)
		}
		vrfData[name] = info
		vrfs = append(vrfs, name)
	}

	vrfCache = vrfData
	return vrfs, nil
}

func collectVRFNeighbors(namespace string, vrfName string) ([]db.Neighbor, error) {
	restore, err := enterNS(namespace)
	if err != nil {
		return nil, err
	}
	defer restore()

	info, ok := vrfCache[vrfName]
	if !ok {
		info, err = getVRFInfo(vrfName)
		if err != nil {
			return nil, err
		}
	}

	nlneighs, err := nl.NeighList(0, 0)
	if err != nil {
		return nil, err
	}

	links, _ := nl.LinkList()
	linkNames := make(map[int]string, len(links))
	for _, l := range links {
		linkNames[l.Attrs().Index] = l.Attrs().Name
	}

	neighbors := make([]db.Neighbor, 0)
	for _, n := range nlneighs {
		if n.MasterIndex != info.Index {
			continue
		}
		state := nudStateString(n.State)
		neighbors = append(neighbors, db.Neighbor{
			Namespace: namespace,
			VRF:       vrfName,
			IP:        n.IP.String(),
			Dev:       linkNames[n.LinkIndex],
			MAC:       n.HardwareAddr.String(),
			State:     state,
			Reachable: isNudReachable(n.State),
		})
	}
	return neighbors, nil
}

func collectVRFRules(namespace string, vrfName string) ([]db.Rule, error) {
	info, ok := vrfCache[vrfName]
	if !ok {
		restore, err := enterNS(namespace)
		if err != nil {
			return nil, err
		}
		info, err = getVRFInfo(vrfName)
		restore()
		if err != nil {
			return nil, err
		}
	}
	if info.Table == 0 {
		return nil, nil
	}

	allRules, err := collectRules(namespace)
	if err != nil {
		return nil, err
	}

	vrfTableStr := strconv.Itoa(info.Table)
	var rules []db.Rule
	for _, r := range allRules {
		if r.TableID == vrfTableStr {
			r.VRF = vrfName
			rules = append(rules, r)
		}
	}
	return rules, nil
}

func findVRFTable(vrfName string) int {
	if info, ok := vrfCache[vrfName]; ok {
		return info.Table
	}
	return 0
}

func getVRFInfo(vrfName string) (vrfInfo, error) {
	link, err := nl.LinkByName(vrfName)
	if err != nil {
		return vrfInfo{}, err
	}
	return vrfInfoFromLink(link), nil
}

func vrfInfoFromLink(link nl.Link) vrfInfo {
	attrs := link.Attrs()
	vrf, ok := link.(*nl.Vrf)
	if !ok || vrf.Table == 0 {
		return vrfInfo{Name: attrs.Name, Index: attrs.Index, Table: 0}
	}
	return vrfInfo{Name: attrs.Name, Index: attrs.Index, Table: int(vrf.Table)}
}
