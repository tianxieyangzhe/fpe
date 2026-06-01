package collect

import (
	"os"
	"strings"

	"github.com/spf13/cobra"
	"github.com/yangshuai/fpe/internal/collector"
	"github.com/yangshuai/fpe/internal/db"
	"github.com/yangshuai/fpe/internal/logs"
)

const anposns = "ANPOSNS"

func NewCommand() *cobra.Command {
	var sshHost, sshUser, sshKey, dbOutput string

	cmd := &cobra.Command{
		Use:   "collect [db-file]",
		Short: "Collect network info into SQLite knowledge base",
		Args:  cobra.MaximumNArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			var exec collector.Executor
			var host string

			if sshHost != "" {
				e, err := collector.NewSSHExecutor(sshHost, sshUser, sshKey)
				if err != nil {
					return err
				}
				defer e.Close()
				exec = e
				host = sshHost
			} else {
				exec = &collector.LocalExecutor{}
				h, _ := os.Hostname()
				host = h
			}

			if len(args) > 0 {
				dbOutput = args[0]
			}
			if dbOutput == "" {
				dbOutput = strings.ReplaceAll(host, ".", "_") + ".db"
			}

			d, err := db.Open(dbOutput)
			if err != nil {
				return err
			}
			defer d.Close()

			logs.Infof("collecting host=%s db=%s", host, dbOutput)

			// Collect root namespace
			collectNamespace(exec, d, "", "")

			// Discover all network namespaces from root
			allNS, err := collector.CollectNetNS(exec)
			if err != nil {
				logs.Warnf("netns list failed: %v", err)
			}

			// Check if ANPOSNS exists
			anposnsFound := false
			for _, ns := range allNS {
				if ns == anposns {
					anposnsFound = true
					break
				}
			}

			if anposnsFound {
				logs.Infof("collecting namespace=%s", anposns)
				collectNamespace(exec, d, anposns, "")
			} else {
				logs.Warnf("namespace %s not found, skipping", anposns)
			}

			// Collect OVS (not namespace-scoped)
			bridges, ports, flows, groups, fdbs, tnlArps, err := collector.CollectOVS(exec)
			if err != nil {
				logs.Errorf("ovs collection failed: %v", err)
			}
			for _, v := range bridges {
				d.InsertOvsBridge(v)
			}
			for _, v := range ports {
				d.InsertOvsPort(v)
			}
			for _, v := range flows {
				d.InsertOvsFlow(v)
			}
			for _, v := range groups {
				d.InsertOvsGroup(v)
			}
			for _, v := range fdbs {
				d.InsertOvsFDB(v)
			}
			for _, v := range tnlArps {
				d.InsertOvsTnlARP(v)
			}
			logs.Infof("collected ovs bridges=%d ports=%d flows=%d groups=%d", len(bridges), len(ports), len(flows), len(groups))

			// Collect FRR (only in ANPOSNS namespace)
			if anposnsFound {
				frrInfos, err := collector.CollectFRR(exec)
				if err != nil {
					logs.Errorf("frr collection failed: %v", err)
				}
				for _, v := range frrInfos {
					d.InsertFrrInfo(v)
				}
				logs.Infof("collected frr info count=%d", len(frrInfos))
			}

			logs.Info("done")
			return nil
		},
	}

	cmd.Flags().StringVar(&sshHost, "ssh", "", "SSH host")
	cmd.Flags().StringVar(&sshUser, "user", "root", "SSH user")
	cmd.Flags().StringVar(&sshKey, "key", os.Getenv("HOME")+"/.ssh/id_ed25519", "SSH private key")
	cmd.Flags().StringVar(&dbOutput, "output", "", "output db path (default: <host>.db)")
	return cmd
}

// collectNamespace collects all four categories of network data for a namespace,
// then discovers VRF L3 master devices within the namespace and collects
// VRF-specific routes, rules, and neighbors.
func collectNamespace(exec collector.Executor, d *db.DB, namespace, vrf string) {
	ns := namespace
	if ns == "" {
		ns = "root"
	}

	// 1. Interfaces
	ifaces, err := collector.CollectInterfaces(exec, namespace)
	if err != nil {
		logs.Warnf("interfaces collection failed ns=%s: %v", ns, err)
	}
	for _, v := range ifaces {
		v.VRF = vrf
		d.InsertInterface(v)
	}
	logs.Infof("collected interfaces ns=%s count=%d", ns, len(ifaces))

	// 2. Rules
	rules, err := collector.CollectRules(exec, namespace)
	if err != nil {
		logs.Warnf("rules collection failed ns=%s: %v", ns, err)
	}
	for _, v := range rules {
		v.VRF = vrf
		d.InsertRule(v)
	}
	logs.Infof("collected rules ns=%s count=%d", ns, len(rules))

	// 3. Routes
	routes, err := collector.CollectRoutes(exec, namespace)
	if err != nil {
		logs.Warnf("routes collection failed ns=%s: %v", ns, err)
	}
	for _, v := range routes {
		v.VRF = vrf
		d.InsertRoute(v)
	}
	logs.Infof("collected routes ns=%s count=%d", ns, len(routes))

	// 4. Neighbors
	neighbors, err := collector.CollectNeighbors(exec, namespace)
	if err != nil {
		logs.Warnf("neighbors collection failed ns=%s: %v", ns, err)
	}
	for _, v := range neighbors {
		v.VRF = vrf
		d.InsertNeighbor(v)
	}
	logs.Infof("collected neighbors ns=%s count=%d", ns, len(neighbors))

	// 5. Discover VRF L3 master devices and collect VRF-specific data
	vrfs, err := collector.CollectVRFs(exec, namespace)
	if err != nil {
		logs.Warnf("vrf discovery failed ns=%s: %v", ns, err)
		return
	}
	if len(vrfs) == 0 {
		return
	}
	logs.Infof("discovered vrfs ns=%s count=%d names=%v", ns, len(vrfs), vrfs)

	for _, vrfName := range vrfs {
		// Update VRF field on interfaces enslaved to this VRF
		for _, iface := range ifaces {
			if iface.Master == vrfName {
				d.UpdateInterfaceVRF(iface.Name, iface.Namespace, vrfName)
			}
		}

		// VRF-specific routes
		vrfRoutes, err := collector.CollectVRFRoutes(exec, namespace, vrfName)
		if err != nil {
			logs.Warnf("vrf routes collection failed ns=%s vrf=%s: %v", ns, vrfName, err)
		}
		for _, v := range vrfRoutes {
			d.InsertRoute(v)
		}
		logs.Infof("collected vrf routes ns=%s vrf=%s count=%d", ns, vrfName, len(vrfRoutes))

		// VRF-specific rules
		vrfRules, err := collector.CollectVRFRules(exec, namespace, vrfName)
		if err != nil {
			logs.Warnf("vrf rules collection failed ns=%s vrf=%s: %v", ns, vrfName, err)
		}
		for _, v := range vrfRules {
			d.InsertRule(v)
		}
		logs.Infof("collected vrf rules ns=%s vrf=%s count=%d", ns, vrfName, len(vrfRules))

		// VRF-specific neighbors
		vrfNeighbors, err := collector.CollectVRFNeighbors(exec, namespace, vrfName)
		if err != nil {
			logs.Warnf("vrf neighbors collection failed ns=%s vrf=%s: %v", ns, vrfName, err)
		}
		for _, v := range vrfNeighbors {
			d.InsertNeighbor(v)
		}
		logs.Infof("collected vrf neighbors ns=%s vrf=%s count=%d", ns, vrfName, len(vrfNeighbors))
	}
}
