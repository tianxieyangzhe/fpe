package remote

import (
	"github.com/yangshuai/fpe/internal/collector"
	"github.com/yangshuai/fpe/internal/db"
)

// Collector collects kernel networking state by running commands through an
// Executor, typically an SSHExecutor for remote hosts.
type Collector struct {
	exec collector.Executor
}

func New(exec collector.Executor) *Collector {
	return &Collector{exec: exec}
}

func (c *Collector) Interfaces(namespace string) ([]db.Interface, error) {
	return collectInterfaces(c.exec, namespace)
}

func (c *Collector) Namespaces() ([]string, error) {
	return collectNamespaces(c.exec)
}

func (c *Collector) Neighbors(namespace string) ([]db.Neighbor, error) {
	return collectNeighbors(c.exec, namespace)
}

func (c *Collector) Routes(namespace string) ([]db.Route, error) {
	return collectRoutes(c.exec, namespace)
}

func (c *Collector) Rules(namespace string) ([]db.Rule, error) {
	return collectRules(c.exec, namespace)
}

func (c *Collector) VRFs(namespace string) ([]string, error) {
	return collectVRFs(c.exec, namespace)
}

func (c *Collector) VRFNeighbors(namespace, vrf string) ([]db.Neighbor, error) {
	return collectVRFNeighbors(c.exec, namespace, vrf)
}

func (c *Collector) VRFRoutes(namespace, vrf string) ([]db.Route, error) {
	return collectVRFRoutes(c.exec, namespace, vrf)
}

func (c *Collector) VRFRules(namespace, vrf string) ([]db.Rule, error) {
	return collectVRFRules(c.exec, namespace, vrf)
}
