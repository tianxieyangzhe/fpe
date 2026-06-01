package walker

import (
	"net/netip"

	"github.com/yangshuai/fpe/internal/db"
)

func matchRules(pkt PacketTuple, d *db.DB) string {
	rules, _ := d.GetRules(pkt.Namespace)
	srcAddr, _ := netip.ParseAddr(pkt.SrcIP)
	for _, r := range rules {
		if r.FromPrefix != "" {
			pfx, err := netip.ParsePrefix(r.FromPrefix)
			if err != nil || !pfx.Contains(srcAddr) {
				continue
			}
		}
		if r.FWMark != "" {
			continue
		}
		return r.TableID
	}
	return "main"
}
