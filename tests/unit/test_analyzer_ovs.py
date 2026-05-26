"""OVS-first analyzer tests."""

import pytest

from fpe.analyzer import Analyzer
from fpe.models import ExecContext, PacketContext


HOST_LINKS = """
1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 state UNKNOWN
    link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00
2: lan1: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 master br-int state UP
    link/ether 00:11:22:33:44:10 brd ff:ff:ff:ff:ff:ff
3: wan0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 state UP
    link/ether 00:11:22:33:44:20 brd ff:ff:ff:ff:ff:ff
4: br-int: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 state UP
    link/ether 00:11:22:33:44:30 brd ff:ff:ff:ff:ff:ff
    openvswitch
"""

HOST_ADDR = """
1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 state UNKNOWN
    inet 127.0.0.1/8 scope host lo
2: lan1: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 state UP
    inet 10.0.0.2/24 scope global lan1
3: wan0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 state UP
    inet 192.168.1.10/24 scope global wan0
4: br-int: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 state UP
"""

OVS_SHOW = """
0a1b2c3d-4e5f-6789-abcd-ef0123456789
    Bridge "br-int"
        Port "br-int"
            Interface "br-int"
                type: internal
        Port "lan1"
            Interface "lan1"
        Port "wan0"
            Interface "wan0"
"""

OVS_OFCTL_SHOW = """
OFPT_FEATURES_REPLY (xid=0x2): dpid:0000aabbccddeeff
 1(lan1): addr:aa:bb:cc:dd:ee:01
 2(wan0): addr:aa:bb:cc:dd:ee:02
 LOCAL(br-int): addr:aa:bb:cc:dd:ee:ff
"""

OVS_FLOWS = """
 cookie=0x1, duration=1000.500s, table=0, n_packets=50, n_bytes=5000, idle_age=10, priority=100,in_port=1,ip,nw_dst=8.8.8.8 actions=LOCAL
"""

IP_RULES = """
100:    from 10.0.0.0/24 lookup 100
32766:    from all lookup main
"""

IP_ROUTES = """
default via 192.168.1.1 dev wan0 metric 100
"""

IP_ROUTES_100 = """
8.8.8.8/32 via 192.168.1.1 dev wan0 metric 10
"""

IP_NEIGH = """
192.168.1.1 dev wan0 lladdr 00:11:22:33:44:55 REACHABLE
"""


class FakeExecutor:
    def run(self, cmd: str) -> str:
        if cmd == "ovs-vsctl show":
            return OVS_SHOW
        if cmd == "ovs-ofctl show br-int":
            return OVS_OFCTL_SHOW
        if cmd == "ovs-ofctl dump-flows br-int":
            return OVS_FLOWS
        raise AssertionError(f"Unexpected run command: {cmd}")

    def run_in_context(self, cmd: str, namespace: str | None = None, vrf: str | None = None) -> str:
        if cmd == "ip -d link show":
            return HOST_LINKS
        if cmd == "ip addr":
            return HOST_ADDR
        if cmd == "ip rule show":
            return IP_RULES
        if cmd == "ip route show":
            return IP_ROUTES
        if cmd == "ip route show table 100":
            return IP_ROUTES_100
        if cmd == "ip neigh show":
            return IP_NEIGH
        raise AssertionError(f"Unexpected contextual command: {cmd}")

    def run_raw(self, cmd: str) -> str:
        if cmd == "ip netns list":
            return ""
        raise AssertionError(f"Unexpected raw command: {cmd}")


@pytest.mark.asyncio
async def test_analyze_ovs_flow_to_kernel_then_route():
    analyzer = Analyzer(executor=FakeExecutor())
    result = await analyzer.analyze(
        packet=PacketContext(src_ip="10.0.0.2", dst_ip="8.8.8.8", ingress_if="lan1", protocol="ip"),
        exec_ctx=ExecContext(namespace=""),
    )

    assert result.status == "COMPLETED"
    assert result.graph is not None
    assert any(node.kind == "ovs_flow" for node in result.graph.nodes)
    assert any(edge.relation == "enter_kernel" for edge in result.graph.edges)
    assert any(node.obj_type == "route" for node in result.path)
    assert "flowchart LR" in (result.mermaid or "")
