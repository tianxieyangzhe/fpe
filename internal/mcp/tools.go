package mcp

import (
	"context"
	"encoding/json"

	"github.com/modelcontextprotocol/go-sdk/mcp"
	"github.com/yangshuai/fpe/internal/db"
	"github.com/yangshuai/fpe/internal/walker"
)

func jsonContent(v any) (*mcp.CallToolResult, error) {
	b, err := json.MarshalIndent(v, "", "  ")
	if err != nil {
		return nil, err
	}
	return &mcp.CallToolResult{
		Content: []mcp.Content{&mcp.TextContent{Text: string(b)}},
	}, nil
}

// Tool input types

type namespaceInput struct {
	Namespace string `json:"namespace" jsonschema:"network namespace, empty for default"`
}

type routesInput struct {
	Namespace string `json:"namespace" jsonschema:"network namespace"`
	Table     string `json:"table" jsonschema:"routing table id, default main"`
}

type neighborInput struct {
	Namespace string `json:"namespace" jsonschema:"network namespace"`
	IP        string `json:"ip" jsonschema:"filter by IP"`
}

type ovsBridgeInput struct{}

type ovsFlowsInput struct {
	Bridge string  `json:"bridge" jsonschema:"bridge name,required"`
	Table  float64 `json:"table" jsonschema:"table id"`
}

type ovsGroupsInput struct {
	Bridge  string  `json:"bridge" jsonschema:"bridge name,required"`
	GroupID float64 `json:"group_id" jsonschema:"filter by group id"`
}

type ovsFDBInput struct {
	Bridge string `json:"bridge" jsonschema:"bridge name,required"`
}

type ovsTnlARPInput struct {
	Bridge string `json:"bridge" jsonschema:"bridge name,required"`
	IP     string `json:"ip" jsonschema:"filter by IP"`
}

type frrInput struct {
	Command string `json:"command" jsonschema:"FRR command name, e.g. show ip route. empty returns all"`
}

type resolvePacketInput struct {
	SrcIP     string  `json:"src_ip" jsonschema:"source IP address,required"`
	DstIP     string  `json:"dst_ip" jsonschema:"destination IP address,required"`
	Proto     string  `json:"proto" jsonschema:"tcp/udp/icmp"`
	DstPort   float64 `json:"dst_port" jsonschema:"destination port"`
	SrcPort   float64 `json:"src_port" jsonschema:"source port"`
	Namespace string  `json:"namespace" jsonschema:"network namespace"`
}

func (in resolvePacketInput) toPacketTuple() walker.PacketTuple {
	pkt := walker.PacketTuple{
		SrcIP:     in.SrcIP,
		DstIP:     in.DstIP,
		Proto:     in.Proto,
		Namespace: in.Namespace,
	}
	if in.DstPort != 0 {
		p := int(in.DstPort)
		pkt.DstPort = &p
	}
	if in.SrcPort != 0 {
		p := int(in.SrcPort)
		pkt.SrcPort = &p
	}
	return pkt
}

func addGetInterfaces(s *mcp.Server, d *db.DB) {
	mcp.AddTool(s, &mcp.Tool{
		Name:        "get_interfaces",
		Description: "List network interfaces",
	}, func(ctx context.Context, req *mcp.CallToolRequest, in namespaceInput) (*mcp.CallToolResult, any, error) {
		ifaces, err := d.GetInterfaces(in.Namespace)
		if err != nil {
			return nil, nil, err
		}
		res, err := jsonContent(ifaces)
		return res, nil, err
	})
}

func addGetRoutes(s *mcp.Server, d *db.DB) {
	mcp.AddTool(s, &mcp.Tool{
		Name:        "get_routes",
		Description: "List routes, optionally filter by namespace and table",
	}, func(ctx context.Context, req *mcp.CallToolRequest, in routesInput) (*mcp.CallToolResult, any, error) {
		if in.Table == "" {
			in.Table = "main"
		}
		routes, err := d.GetRoutes(in.Namespace, in.Table)
		if err != nil {
			return nil, nil, err
		}
		res, err := jsonContent(routes)
		return res, nil, err
	})
}

func addGetNeighbors(s *mcp.Server, d *db.DB) {
	mcp.AddTool(s, &mcp.Tool{
		Name:        "get_neighbors",
		Description: "List ARP/NDP neighbors",
	}, func(ctx context.Context, req *mcp.CallToolRequest, in neighborInput) (*mcp.CallToolResult, any, error) {
		if in.IP != "" {
			n, err := d.GetNeighbor(in.IP)
			if err != nil {
				return nil, nil, err
			}
			res, err := jsonContent(n)
			return res, nil, err
		}
		res, err := jsonContent(map[string]string{"note": "use ip parameter to filter"})
		return res, nil, err
	})
}

func addGetOvsBridges(s *mcp.Server, d *db.DB) {
	mcp.AddTool(s, &mcp.Tool{
		Name:        "get_ovs_bridges",
		Description: "List OVS bridges",
	}, func(ctx context.Context, req *mcp.CallToolRequest, in ovsBridgeInput) (*mcp.CallToolResult, any, error) {
		bridges, err := d.GetOvsBridges()
		if err != nil {
			return nil, nil, err
		}
		res, err := jsonContent(bridges)
		return res, nil, err
	})
}

func addGetOvsFlows(s *mcp.Server, d *db.DB) {
	mcp.AddTool(s, &mcp.Tool{
		Name:        "get_ovs_flows",
		Description: "List OVS flows for a bridge and table",
	}, func(ctx context.Context, req *mcp.CallToolRequest, in ovsFlowsInput) (*mcp.CallToolResult, any, error) {
		flows, err := d.GetOvsFlows(in.Bridge, int(in.Table))
		if err != nil {
			return nil, nil, err
		}
		res, err := jsonContent(flows)
		return res, nil, err
	})
}

func addGetOvsGroups(s *mcp.Server, d *db.DB) {
	mcp.AddTool(s, &mcp.Tool{
		Name:        "get_ovs_groups",
		Description: "List OVS groups for a bridge",
	}, func(ctx context.Context, req *mcp.CallToolRequest, in ovsGroupsInput) (*mcp.CallToolResult, any, error) {
		if in.GroupID != 0 {
			g, err := d.GetOvsGroup(in.Bridge, int(in.GroupID))
			if err != nil {
				return nil, nil, err
			}
			res, err := jsonContent(g)
			return res, nil, err
		}
		res, err := jsonContent(map[string]string{"note": "use group_id to filter"})
		return res, nil, err
	})
}

func addGetOvsFDB(s *mcp.Server, d *db.DB) {
	mcp.AddTool(s, &mcp.Tool{
		Name:        "get_ovs_fdb",
		Description: "List OVS MAC learning table (fdb)",
	}, func(ctx context.Context, req *mcp.CallToolRequest, in ovsFDBInput) (*mcp.CallToolResult, any, error) {
		entries, err := d.GetOvsFDB(in.Bridge)
		if err != nil {
			return nil, nil, err
		}
		res, err := jsonContent(entries)
		return res, nil, err
	})
}

func addGetOvsTnlARP(s *mcp.Server, d *db.DB) {
	mcp.AddTool(s, &mcp.Tool{
		Name:        "get_ovs_tnl_arp",
		Description: "List OVS tunnel ARP cache",
	}, func(ctx context.Context, req *mcp.CallToolRequest, in ovsTnlARPInput) (*mcp.CallToolResult, any, error) {
		if in.IP != "" {
			a, err := d.GetOvsTnlARP(in.Bridge, in.IP)
			if err != nil {
				return nil, nil, err
			}
			res, err := jsonContent(a)
			return res, nil, err
		}
		res, err := jsonContent(map[string]string{"note": "use ip parameter to filter"})
		return res, nil, err
	})
}

func addResolvePacket(s *mcp.Server, d *db.DB) {
	mcp.AddTool(s, &mcp.Tool{
		Name:        "resolve_packet",
		Description: "Resolve and complete packet fields from knowledge base",
	}, func(ctx context.Context, req *mcp.CallToolRequest, in resolvePacketInput) (*mcp.CallToolResult, any, error) {
		pkt := in.toPacketTuple()
		resolved := walker.ResolvePacket(pkt, d)
		res, err := jsonContent(resolved)
		return res, nil, err
	})
}

func addGetPathSegments(s *mcp.Server, d *db.DB) {
	mcp.AddTool(s, &mcp.Tool{
		Name:        "get_path_segments",
		Description: "Compute all possible path leaves for a packet. Returns WalkResult with path segments and outcomes.",
	}, func(ctx context.Context, req *mcp.CallToolRequest, in resolvePacketInput) (*mcp.CallToolResult, any, error) {
		pkt := in.toPacketTuple()
		pkt = walker.ResolvePacket(pkt, d)
		result := walker.Walk(pkt, d)
		res, err := jsonContent(result)
		return res, nil, err
	})
}

func addGetFrrInfo(s *mcp.Server, d *db.DB) {
	mcp.AddTool(s, &mcp.Tool{
		Name: "get_frr_info",
		Description: "Retrieve FRR routing protocol info. FRR runs exclusively in the ANPOSNS network namespace. " +
			"Supported commands: show ip route (routing table), show bfd peers (BFD peers), " +
			"show running-config (running config), show bgp summary (BGP summary), " +
			"show bgp ipv4 unicast (BGP routes), show ip ospf neighbor (OSPF neighbors). " +
			"Status field: ok=valid data, empty=protocol not enabled, error=execution failed",
	}, func(ctx context.Context, req *mcp.CallToolRequest, in frrInput) (*mcp.CallToolResult, any, error) {
		info, err := d.GetFrrInfo(in.Command)
		if err != nil {
			return nil, nil, err
		}
		res, err := jsonContent(info)
		return res, nil, err
	})
}
