"""Unit tests for data models."""

import pytest
from pydantic import ValidationError

from fpe.models import (
    AnalysisResult,
    AnalysisState,
    DecisionEvent,
    ExecContext,
    FlowGraph,
    GraphEdge,
    GraphNode,
    InterfaceContext,
    LinkResolution,
    NeighborInfo,
    NextHop,
    OvsPortInfo,
    PacketContext,
    PathNode,
    RiskItem,
    RouteResult,
    RuleMatch,
    RuleMatchResult,
    ToolResult,
)


class TestPacketContext:
    def test_valid_minimal(self):
        p = PacketContext(src_ip="10.0.0.2", dst_ip="8.8.8.8")
        assert p.src_ip == "10.0.0.2"
        assert p.dst_ip == "8.8.8.8"
        assert p.ip_version == 4

    def test_valid_full(self):
        p = PacketContext(
            src_ip="10.0.0.2",
            dst_ip="8.8.8.8",
            protocol="icmp",
            ingress_if="eth0",
            ip_version=4,
        )
        assert p.protocol == "icmp"
        assert p.ingress_if == "eth0"

    def test_invalid_ip_version(self):
        with pytest.raises(ValidationError):
            PacketContext(src_ip="10.0.0.2", dst_ip="8.8.8.8", ip_version=7)


class TestExecContext:
    def test_defaults(self):
        ctx = ExecContext()
        assert ctx.namespace is None
        assert ctx.vrf is None
        assert ctx.ip_version == 4

    def test_valid(self):
        ctx = ExecContext(namespace="ns1", vrf="vrf1")
        assert ctx.namespace == "ns1"
        assert ctx.vrf == "vrf1"


class TestInterfaceContext:
    def test_minimal(self):
        iface = InterfaceContext(iface="eth0", kind="ether")
        assert iface.iface == "eth0"
        assert iface.ips == []
        assert iface.if_type == "physical"

    def test_full(self):
        iface = InterfaceContext(
            iface="eth0",
            kind="ether",
            if_type="physical",
            role="underlay-uplink",
            state="UP",
            mtu=1500,
            mac="00:11:22:33:44:55",
            ips=["192.168.1.10/24"],
        )
        assert iface.state == "UP"
        assert iface.mtu == 1500
        assert iface.role == "underlay-uplink"


class TestRouteModels:
    def test_next_hop(self):
        nh = NextHop(via="192.168.1.1", dev="eth0")
        assert nh.via == "192.168.1.1"
        assert nh.dev == "eth0"

    def test_rule_match(self):
        r = RuleMatch(priority=100, table="100", raw="100: from 10.0.0.2 lookup 100")
        assert r.priority == 100
        assert r.table == "100"

    def test_route_result(self):
        nh = NextHop(via="192.168.1.1", dev="eth0")
        r = RouteResult(
            table="main",
            route_type="unicast",
            prefix="0.0.0.0/0",
            next_hops=[nh],
            raw="default via 192.168.1.1 dev eth0",
        )
        assert r.table == "main"
        assert r.next_hops[0].via == "192.168.1.1"


class TestLinkResolution:
    def test_veth(self):
        lr = LinkResolution(
            dev_type="veth",
            peer_if="veth1",
            next_namespace="ns1",
        )
        assert lr.dev_type == "veth"
        assert lr.peer_if == "veth1"
        assert lr.next_namespace == "ns1"

    def test_physical(self):
        lr = LinkResolution(dev_type="physical")
        assert lr.dev_type == "physical"
        assert lr.requires_ovs is False


class TestOvsPortInfo:
    def test_minimal(self):
        p = OvsPortInfo(bridge="br-int", port="veth0", port_type="internal")
        assert p.bridge == "br-int"
        assert p.ofport is None


class TestNeighborInfo:
    def test_reachable(self):
        n = NeighborInfo(
            ip="192.168.1.1", dev="eth0", mac="00:11:22:33:44:55", state="REACHABLE", reachable=True
        )
        assert n.reachable is True

    def test_unreachable(self):
        n = NeighborInfo(ip="192.168.1.3", dev="eth0", state="FAILED", reachable=False)
        assert n.reachable is False


class TestAnalysisState:
    def test_defaults(self):
        p = PacketContext(src_ip="10.0.0.2", dst_ip="8.8.8.8")
        ctx = ExecContext()
        state = AnalysisState(trace_id="test-1", packet=p, exec_ctx=ctx)
        assert state.flow_state == "INIT"
        assert state.current_hop == 0
        assert state.max_hops == 16
        assert state.confidence == 1.0
        assert state.graph.nodes == []

    def test_path_node(self):
        n = PathNode(
            hop_index=0,
            obj_type="interface",
            obj_name="eth0",
            reason="Initial interface",
        )
        assert n.hop_index == 0

    def test_decision_event(self):
        d = DecisionEvent(
            state="INIT", source="test", message="starting"
        )
        assert d.state == "INIT"

    def test_risk_item(self):
        r = RiskItem(code="NO_NEIGHBOR", severity="high", message="Neighbor not found")
        assert r.severity == "high"


class TestToolResult:
    def test_success(self):
        tr = ToolResult(ok=True, tool="fpe.analyze_flow")
        assert tr.ok is True
        assert tr.error is None

    def test_error(self):
        tr = ToolResult(ok=False, tool="fpe.analyze_flow", error="something went wrong")
        assert tr.ok is False
        assert tr.error == "something went wrong"


class TestGraphModels:
    def test_graph_node(self):
        node = GraphNode(id="n1", kind="interface", label="lan1")
        assert node.kind == "interface"

    def test_flow_graph(self):
        graph = FlowGraph(
            nodes=[GraphNode(id="n1", kind="interface", label="lan1")],
            edges=[GraphEdge(src="n1", dst="n2", relation="ingress_to_port", reason="test")],
        )
        assert len(graph.nodes) == 1
        assert graph.edges[0].relation == "ingress_to_port"
