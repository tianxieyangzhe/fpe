package walker

import (
	"net/netip"

	"github.com/yangshuai/fpe/internal/db"
	"github.com/yangshuai/fpe/internal/logs"
)

func lpmRoute(dstIP string, d *db.DB, namespace, tableID string) *db.Route {
	routes, _ := d.GetRoutes(namespace, tableID)
	dst, _ := netip.ParseAddr(dstIP)
	for _, r := range routes {
		pfx, err := netip.ParsePrefix(r.Prefix)
		if err != nil {
			logs.Warnf("invalid route prefix %q: %v", r.Prefix, err)
			continue
		}
		if pfx.Contains(dst) && len(r.NextHops) > 0 {
			return &r
		}
	}
	return nil
}
