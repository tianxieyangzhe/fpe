"""Unit tests for link resolution and renderers."""

from fpe.collectors import resolve_link_type
from fpe.models import AnalysisResult, PathNode
from fpe.renderer import render_json, render_text


class TestResolveLinkType:
    def test_veth(self):
        raw = """3: veth0@veth1: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc noqueue state UP
    link/ether aa:bb:cc:dd:ee:ff brd ff:ff:ff:ff:ff:ff
    veth
    peer veth1"""
        lr = resolve_link_type("veth0", raw)
        assert lr.dev_type == "veth"
        assert lr.peer_if == "veth1"

    def test_physical(self):
        raw = """2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc pfifo_fast state UP
    link/ether 00:11:22:33:44:55 brd ff:ff:ff:ff:ff:ff"""
        lr = resolve_link_type("eth0", raw)
        assert lr.dev_type == "physical"
        assert lr.peer_if is None

    def test_bridge(self):
        raw = """4: br0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc noqueue state UP
    link/ether 00:11:22:33:44:55 brd ff:ff:ff:ff:ff:ff
    bridge"""
        lr = resolve_link_type("br0", raw)
        assert lr.dev_type == "bridge"
        assert lr.bridge == "br0"


class TestTextRenderer:
    def test_render(self):
        result = AnalysisResult(
            status="COMPLETED",
            path=[PathNode(hop_index=0, obj_type="interface", obj_name="eth0", reason="test")],
            decision_chain=[],
            risks=[],
            confidence=1.0,
            confidence_reasons=[],
            summary="Test summary",
        )
        output = render_text(result)
        assert "Status: COMPLETED" in output
        assert "Test summary" in output
        assert "eth0" in output


class TestJsonRenderer:
    def test_render(self):
        result = AnalysisResult(
            status="COMPLETED",
            path=[],
            decision_chain=[],
            risks=[],
            confidence=0.85,
            confidence_reasons=[],
            summary="JSON test",
        )
        output = render_json(result)
        assert '"status": "COMPLETED"' in output
        assert '"confidence": 0.85' in output
