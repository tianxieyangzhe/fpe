"""OVS bridge, port, and flow table collection."""

from __future__ import annotations

import re
import logging
from typing import Any

from fpe.command.executor import RemoteExecutor
from fpe.models import OvsBridge, OvsFlow, OvsPortInfo

logger = logging.getLogger(__name__)


def get_ovs_info(
    executor: RemoteExecutor,
) -> list[dict[str, Any]]:
    """Collect OVS bridge and port information (legacy, returns raw dicts)."""
    raw = executor.run("ovs-vsctl show")
    if not raw.strip():
        return []
    return parse_ovs(raw)


def get_ovs_bridges(
    executor: RemoteExecutor,
) -> list[OvsBridge]:
    """Collect all OVS bridges with their ports and datapath metadata."""
    raw = executor.run("ovs-vsctl show")
    if not raw.strip():
        return []

    port_map = parse_ovs(raw)
    bridges: list[OvsBridge] = []

    for br_data in port_map:
        bridge_name = br_data["bridge"]
        bridge = OvsBridge(name=bridge_name)

        bridge = _enrich_from_ofctl_show(executor, bridge)

        ports: list[OvsPortInfo] = []
        for p in br_data.get("ports", []):
            port_info = OvsPortInfo(
                bridge=bridge_name,
                port=p["port"],
                interface=p.get("interface"),
                port_type=p.get("port_type", "internal"),
                ofport=p.get("ofport"),
                vlan_tag=p.get("vlan_tag"),
                trunk_vlans=p.get("trunk_vlans", []),
            )
            ports.append(port_info)

        bridge.ports = ports
        bridges.append(bridge)

    return bridges


def _enrich_from_ofctl_show(
    executor: RemoteExecutor,
    bridge: OvsBridge,
) -> OvsBridge:
    """Run ``ovs-ofctl show <bridge>`` to fill datapath_id and port MACs."""
    try:
        raw = executor.run(f"ovs-ofctl show {bridge.name}")
    except Exception:
        logger.debug("ovs-ofctl show failed for bridge %s, skipping enrichment", bridge.name)
        return bridge

    if not raw.strip():
        return bridge

    dpid_match = re.search(r"dpid:([0-9a-fA-F]+)", raw)
    if dpid_match:
        bridge.datapath_id = dpid_match.group(1)

    port_pattern = re.compile(r"^\s*(\d+)\((\S+)\):\s+addr:(\S+)", re.MULTILINE)
    local_pattern = re.compile(r"^\s*LOCAL\((\S+)\):\s+addr:(\S+)", re.MULTILINE)

    ofport_map: dict[int, tuple[str, str]] = {}

    for m in port_pattern.finditer(raw):
        ofport = int(m.group(1))
        iface_name = m.group(2)
        mac = m.group(3)
        ofport_map[ofport] = (iface_name, mac)

    for m in local_pattern.finditer(raw):
        iface_name = m.group(1)
        mac = m.group(2)
        ofport_map[65534] = (iface_name, mac)

    for port_info in bridge.ports:
        if port_info.ofport is not None and port_info.ofport in ofport_map:
            iface_name, mac = ofport_map[port_info.ofport]
            if not port_info.interface:
                port_info.interface = iface_name
            port_info.mac = mac
        elif port_info.interface is not None:
            for ofport, (iface_name, mac) in ofport_map.items():
                if iface_name == port_info.interface:
                    if port_info.ofport is None:
                        port_info.ofport = ofport
                    port_info.mac = mac
                    break

    return bridge


def get_ovs_flows(
    executor: RemoteExecutor,
    bridge: str | None = None,
    table: int | None = None,
) -> list[OvsFlow]:
    """Collect OpenFlow flow entries from one or all OVS bridges."""
    if bridge is not None:
        return _collect_flows_for_bridge(executor, bridge, table)

    bridges = get_ovs_bridges(executor)
    flows: list[OvsFlow] = []
    for br in bridges:
        flows.extend(_collect_flows_for_bridge(executor, br.name, table))
    return flows


def _collect_flows_for_bridge(
    executor: RemoteExecutor,
    bridge: str,
    table: int | None = None,
) -> list[OvsFlow]:
    cmd = f"ovs-ofctl dump-flows {bridge}"
    if table is not None:
        cmd = f"ovs-ofctl dump-flows {bridge} table={table}"

    try:
        raw = executor.run(cmd)
    except Exception:
        logger.debug("ovs-ofctl dump-flows failed for bridge %s", bridge)
        return []

    if not raw.strip():
        return []

    return parse_ovs_flows(raw, bridge)


def parse_ovs(raw: str) -> list[dict[str, Any]]:
    bridges: list[dict[str, Any]] = []
    current_bridge: dict[str, Any] | None = None
    current_port: dict[str, Any] | None = None

    for line in raw.splitlines():
        stripped = line.strip()

        m = re.match(r'Bridge\s+"([^"]+)"', stripped) or re.match(r'Bridge\s+(\S+)', stripped)
        if m:
            if current_bridge:
                if current_port:
                    current_bridge.setdefault("ports", []).append(current_port)
                    current_port = None
                bridges.append(current_bridge)
            current_bridge = {"bridge": m.group(1) or m.group(2), "ports": []}
            continue

        m = re.match(r'Port\s+"([^"]+)"', stripped) or re.match(r'Port\s+(\S+)', stripped)
        if m:
            if current_port and current_bridge is not None:
                current_bridge["ports"].append(current_port)
            current_port = {"port": m.group(1) or m.group(2), "port_type": "internal"}
            continue

        m = re.match(r'Interface\s+"([^"]+)"', stripped) or re.match(r'Interface\s+(\S+)', stripped)
        if m and current_port:
            current_port["interface"] = m.group(1) or m.group(2)
            continue

        m = re.match(r"type:\s+(\S+)", stripped)
        if m and current_port:
            current_port["port_type"] = m.group(1)
            continue

        m = re.match(r"tag:\s+(\d+)", stripped)
        if m and current_port:
            current_port["vlan_tag"] = int(m.group(1))
            continue

        m = re.match(r"trunks:\s+\[([^\]]*)\]", stripped)
        if m and current_port:
            trunk_str = m.group(1).strip()
            current_port["trunk_vlans"] = [int(v.strip()) for v in trunk_str.split(",") if v.strip()]
            continue

        m = re.match(r"OpenFlow\s+port\s*:\s*(\d+)", stripped)
        if m and current_port:
            current_port["ofport"] = int(m.group(1))

    if current_port and current_bridge is not None:
        current_bridge["ports"].append(current_port)
    if current_bridge:
        bridges.append(current_bridge)

    return bridges


def parse_ovs_flows(raw: str, bridge: str) -> list[OvsFlow]:
    flows: list[OvsFlow] = []

    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue

        cookie = None
        duration_sec = None
        table = 0
        n_packets = None
        n_bytes = None
        idle_age_sec = None
        priority = 0
        match = ""
        actions = ""

        cookie_m = re.search(r"cookie=(\S+)", line)
        if cookie_m:
            cookie = cookie_m.group(1).rstrip(",")

        duration_m = re.search(r"duration=([\d.]+)s", line)
        if duration_m:
            duration_sec = float(duration_m.group(1))

        table_m = re.search(r"table=(\d+)", line)
        if table_m:
            table = int(table_m.group(1))

        n_packets_m = re.search(r"n_packets=(\d+)", line)
        if n_packets_m:
            n_packets = int(n_packets_m.group(1))

        n_bytes_m = re.search(r"n_bytes=(\d+)", line)
        if n_bytes_m:
            n_bytes = int(n_bytes_m.group(1))

        idle_age_m = re.search(r"idle_age=(\d+)", line)
        if idle_age_m:
            idle_age_sec = float(idle_age_m.group(1))

        priority_m = re.search(r"priority=(\d+)", line)
        if priority_m:
            priority = int(priority_m.group(1))

        actions_split = line.split(" actions=", 1)
        if len(actions_split) == 2:
            before_actions = actions_split[0]
            actions = actions_split[1]

            known_keys = {"cookie", "duration", "table", "n_packets", "n_bytes", "idle_age", "priority", "send_flow_rem", "hard_timeout", "idle_timeout"}
            parts = before_actions.split(",")
            match_parts: list[str] = []
            for part in parts:
                stripped_part = part.strip()
                if not stripped_part:
                    continue
                key_m = re.match(r"([a-zA-Z_]+)=", stripped_part)
                if key_m:
                    key = key_m.group(1)
                    if key in known_keys:
                        continue
                match_parts.append(stripped_part)

            match = ",".join(match_parts).strip()

        flows.append(
            OvsFlow(
                bridge=bridge,
                table=table,
                priority=priority,
                match=match,
                actions=actions,
                cookie=cookie,
                duration_sec=duration_sec,
                n_packets=n_packets,
                n_bytes=n_bytes,
                idle_age_sec=idle_age_sec,
            )
        )

    return flows
