//go:build linux

package netlink

import (
	"fmt"
	"net"
	"strconv"

	nl "github.com/vishvananda/netlink"
	"github.com/yangshuai/fpe/internal/db"
)

func collectRules(namespace string) ([]db.Rule, error) {
	restore, err := enterNS(namespace)
	if err != nil {
		return nil, err
	}
	defer restore()

	nlrules, err := nl.RuleList(0)
	if err != nil {
		return nil, err
	}

	rules := make([]db.Rule, 0, len(nlrules))
	for _, r := range nlrules {
		rl := db.Rule{
			Namespace:  namespace,
			Priority:   r.Priority,
			FromPrefix: ipNetToString(r.Src),
			TableID:    tableIntToString(r.Table),
			FWMark:     ruleMarkToString(r.Mark, r.Mask),
			Action:     ruleActionString(r.Type, r.Goto),
		}
		rules = append(rules, rl)
	}
	return rules, nil
}

func ipNetToString(n *net.IPNet) string {
	if n == nil {
		return ""
	}
	return n.String()
}

func tableIntToString(t int) string {
	switch t {
	case 255:
		return "local"
	case 254:
		return "main"
	case 253:
		return "default"
	case 0:
		return "unspec"
	default:
		return strconv.Itoa(t)
	}
}

func ruleMarkToString(mark uint32, mask *uint32) string {
	if mark == 0 && mask == nil {
		return ""
	}
	if mask != nil {
		return fmt.Sprintf("0x%x/0x%x", mark, *mask)
	}
	return fmt.Sprintf("0x%x", mark)
}

func ruleActionString(typ uint8, gotoPriority int) string {
	switch typ {
	case 0:
		return ""
	case 1:
		return fmt.Sprintf("goto %d", gotoPriority)
	case 2:
		return "nop"
	case 5:
		return "blackhole"
	case 6:
		return "unreachable"
	case 7:
		return "prohibit"
	default:
		return ""
	}
}
