package kernel

import "github.com/yangshuai/fpe/internal/db"

// Collector collects kernel networking state for one host. Local implementations
// can use netlink directly; remote implementations can execute commands over SSH.
type Collector interface {
	Interfaces(namespace string) ([]db.Interface, error)
	Namespaces() ([]string, error)
	Neighbors(namespace string) ([]db.Neighbor, error)
	Routes(namespace string) ([]db.Route, error)
	Rules(namespace string) ([]db.Rule, error)
	VRFs(namespace string) ([]string, error)
	VRFNeighbors(namespace, vrf string) ([]db.Neighbor, error)
	VRFRoutes(namespace, vrf string) ([]db.Route, error)
	VRFRules(namespace, vrf string) ([]db.Rule, error)
}
