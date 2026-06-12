//go:build linux

package netlink

import (
	"github.com/yangshuai/fpe/internal/db"
)

// Collector collects local kernel networking state using netlink/netns.
type Collector struct{}

func New() *Collector { return &Collector{} }

func (c *Collector) Interfaces(namespace string) ([]db.Interface, error) {
	return collectInterfaces(namespace)
}

func (c *Collector) Namespaces() ([]string, error) {
	return collectNamespaces()
}

func (c *Collector) Neighbors(namespace string) ([]db.Neighbor, error) {
	return collectNeighbors(namespace)
}

func (c *Collector) Routes(namespace string) ([]db.Route, error) {
	return collectRoutes(namespace)
}

func (c *Collector) Rules(namespace string) ([]db.Rule, error) {
	return collectRules(namespace)
}

func (c *Collector) VRFs(namespace string) ([]string, error) {
	return collectVRFs(namespace)
}

func (c *Collector) VRFNeighbors(namespace, vrf string) ([]db.Neighbor, error) {
	return collectVRFNeighbors(namespace, vrf)
}

func (c *Collector) VRFRoutes(namespace, vrf string) ([]db.Route, error) {
	table := findVRFTable(vrf)
	return collectVRFRoutes(namespace, vrf, table)
}

func (c *Collector) VRFRules(namespace, vrf string) ([]db.Rule, error) {
	return collectVRFRules(namespace, vrf)
}
