"""Unit tests for collectors using sample data."""

from fpe.collectors import (
    find_best_route,
    match_ip_rules,
    parse_interface,
    parse_neighbors,
    parse_ovs,
    parse_ovs_flows,
    parse_routes,
    parse_rules,
    resolve_link_type,
)
from tests.fixtures.sample_outputs import (
    IP_LINK_SHOW_ETH0,
    IP_LINK_SHOW_VETH0,
    IP_LINK_SHOW_BRIDGE,
    IP_RULE_SHOW,
    IP_ROUTE_SHOW,
    IP_ROUTE_SHOW_TABLE_100,
    IP_NEIGH_SHOW,
    OVS_OFCTL_DUMP_FLOWS_BR_INT,
    OVS_VSCTL_SHOW,
)


class TestParseInterface:
    def test_parse_ethernet(self):
        result = parse_interface("eth0", IP_LINK_SHOW_ETH0, None)
        assert result.iface == "eth0"
        assert result.kind == "ether"
        assert result.if_type == "physical"
        assert result.role == "underlay-uplink"
        assert result.state == "UP"
        assert result.mtu == 1500
        assert result.mac == "00:11:22:33:44:55"

    def test_parse_veth(self):
        result = parse_interface("veth0", IP_LINK_SHOW_VETH0, None)
        assert result.iface == "veth0"
        assert result.kind == "ether"
        assert result.if_type == "veth"
        assert result.peer == "veth1"
        assert result.peer_type == "veth"
        assert result.peer_scope == "same-namespace-or-unknown"
        assert result.role == "veth-endpoint"

    def test_parse_bridge(self):
        result = parse_interface("br0", IP_LINK_SHOW_BRIDGE, None)
        assert result.iface == "br0"
        assert result.kind == "ether"
        assert result.if_type == "bridge"
        assert result.role == "bridge-device"
        assert result.state == "UP"


class TestParseRules:
    def test_parse_rules(self):
        rules = parse_rules(IP_RULE_SHOW)
        assert len(rules) == 5
        assert rules[0].priority == 0
        assert rules[0].table == "local"
        assert rules[1].priority == 100
        assert rules[1].table == "100"

    def test_match_against_packet(self):
        rules = parse_rules(IP_RULE_SHOW)
        packet = {"src_ip": "10.0.0.2", "dst_ip": "8.8.8.8", "ingress_if": "eth0"}
        result = match_ip_rules(rules, packet)
        assert len(result.matches) == 5
        # Rule with "from 10.0.0.2" should have src matched
        assert any("src=10.0.0.2" in m.matched_fields for m in result.matches)


class TestParseRoutes:
    def test_parse_routes(self):
        routes = parse_routes(IP_ROUTE_SHOW, "main")
        assert len(routes) >= 2
        defaults = [r for r in routes if r.prefix == "0.0.0.0/0"]
        assert len(defaults) == 1
        assert defaults[0].next_hops[0].via == "192.168.1.1"

    def test_parse_specific_table(self):
        routes = parse_routes(IP_ROUTE_SHOW_TABLE_100, "100")
        assert len(routes) == 1
        assert routes[0].next_hops[0].via == "10.0.1.1"
        assert routes[0].next_hops[0].dev == "veth0"

    def test_find_best_route(self):
        routes = parse_routes(IP_ROUTE_SHOW, "main")
        best = find_best_route(routes, "192.168.1.50")
        assert best is not None
        assert best.prefix == "192.168.1.0/24"


class TestParseNeighbors:
    def test_parse(self):
        neighbors = parse_neighbors(IP_NEIGH_SHOW)
        assert len(neighbors) == 3
        assert neighbors[0].ip == "192.168.1.1"
        assert neighbors[0].reachable is True
        assert neighbors[0].state == "REACHABLE"
        assert neighbors[1].reachable is False
        assert neighbors[2].reachable is False


class TestParseOvs:
    def test_parse_bridge(self):
        bridges = parse_ovs(OVS_VSCTL_SHOW)
        assert len(bridges) == 1
        assert bridges[0]["bridge"] == "br-int"
        assert len(bridges[0]["ports"]) == 4

    def test_parse_internal_port(self):
        bridges = parse_ovs(OVS_VSCTL_SHOW)
        br_int_port = bridges[0]["ports"][0]
        assert br_int_port["port"] == "br-int"
        assert br_int_port["port_type"] == "internal"
        assert br_int_port["interface"] == "br-int"

    def test_parse_veth_port(self):
        bridges = parse_ovs(OVS_VSCTL_SHOW)
        veth_port = bridges[0]["ports"][1]
        assert veth_port["port"] == "veth0"
        assert veth_port["interface"] == "veth0"

    def test_parse_access_vlan_port(self):
        bridges = parse_ovs(OVS_VSCTL_SHOW)
        tap_port = bridges[0]["ports"][2]
        assert tap_port["port"] == "tap10"
        assert tap_port["vlan_tag"] == 10
        assert tap_port.get("trunk_vlans", []) == []

    def test_parse_trunk_port(self):
        bridges = parse_ovs(OVS_VSCTL_SHOW)
        trunk_port = bridges[0]["ports"][3]
        assert trunk_port["port"] == "trunk-port"
        assert trunk_port["trunk_vlans"] == [10, 20, 30]


class TestParseOvsFlows:
    def test_parse(self):
        flows = parse_ovs_flows(OVS_OFCTL_DUMP_FLOWS_BR_INT, "br-int")
        assert len(flows) == 3

    def test_flow_basic_fields(self):
        flows = parse_ovs_flows(OVS_OFCTL_DUMP_FLOWS_BR_INT, "br-int")
        flow0 = flows[0]
        assert flow0.bridge == "br-int"
        assert flow0.table == 0
        assert flow0.priority == 100
        assert flow0.cookie == "0x0"
        assert flow0.duration_sec == 12345.678
        assert flow0.n_packets == 1000
        assert flow0.n_bytes == 100000
        assert flow0.idle_age_sec == 5.0

    def test_flow_match_ip_actions(self):
        flows = parse_ovs_flows(OVS_OFCTL_DUMP_FLOWS_BR_INT, "br-int")
        flow1 = flows[1]
        assert flow1.priority == 50
        assert "ip" in flow1.match
        assert "nw_dst=10.0.0.0/24" in flow1.match
        assert flow1.actions == "output:2"
        assert flow1.match_fields["ip"] == "true"
        assert flow1.match_fields["nw_dst"] == "10.0.0.0/24"
        assert flow1.action_list == ["output:2"]

    def test_flow_drop_action(self):
        flows = parse_ovs_flows(OVS_OFCTL_DUMP_FLOWS_BR_INT, "br-int")
        flow2 = flows[2]
        assert flow2.priority == 10
        assert flow2.actions == "drop"
        assert flow2.n_packets == 0


class TestResolveLinkType:
    def test_parse_ether(self):
        resolution = resolve_link_type("eth0", IP_LINK_SHOW_ETH0)
        assert resolution.dev_type == "physical"

    def test_parse_veth(self):
        resolution = resolve_link_type("veth0", IP_LINK_SHOW_VETH0)
        assert resolution.dev_type == "veth"
        assert resolution.peer_if == "veth1"
