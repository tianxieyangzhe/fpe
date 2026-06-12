//go:build !linux

package netlink

import "github.com/yangshuai/fpe/internal/db"

// Collector is a non-Linux stub for development builds. Runtime local
// collection is supported on Linux only.
type Collector struct{}

func New() *Collector { return &Collector{} }

func (c *Collector) Interfaces(namespace string) ([]db.Interface, error) { return nil, nil }
func (c *Collector) Namespaces() ([]string, error)                       { return nil, nil }
func (c *Collector) Neighbors(namespace string) ([]db.Neighbor, error)   { return nil, nil }
func (c *Collector) Routes(namespace string) ([]db.Route, error)         { return nil, nil }
func (c *Collector) Rules(namespace string) ([]db.Rule, error)           { return nil, nil }
func (c *Collector) VRFs(namespace string) ([]string, error)             { return nil, nil }
func (c *Collector) VRFNeighbors(namespace, vrf string) ([]db.Neighbor, error) {
	return nil, nil
}
func (c *Collector) VRFRoutes(namespace, vrf string) ([]db.Route, error) { return nil, nil }
func (c *Collector) VRFRules(namespace, vrf string) ([]db.Rule, error)   { return nil, nil }
