"""OVS bridge, port, and flow table collection."""

from __future__ import annotations

import re
import logging
from typing import Any

from fpe.command.executor import RemoteExecutor
from fpe.models import OvsBridge, OvsFlow, OvsPortInfo, OvsGroup, OvsGroupBucket

logger = logging.getLogger(__name__)


def _split_ovs_csv(value: str) -> list[str]:
    """Split an OVS comma-separated string while preserving nested groups."""
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    for ch in value:
        if ch == "," and depth == 0:
            piece = "".join(current).strip()
            if piece:
                parts.append(piece)
            current = []
            continue
        if ch in "([":
            depth += 1
        elif ch in ")]" and depth > 0:
            depth -= 1
        current.append(ch)

    tail = "".join(current).strip()
    if tail:
        parts.append(tail)
    return parts


def _parse_match_fields(match: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for part in _split_ovs_csv(match):
        if "=" in part:
            key, value = part.split("=", 1)
            fields[key.strip()] = value.strip()
        else:
            fields[part.strip()] = "true"
    return fields


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
        bridge = _enrich_from_ofctl_show(executor, bridge)
        bridges.append(bridge)

    return bridges


def _enrich_from_ofctl_show(
    executor: RemoteExecutor,
    bridge: OvsBridge,
) -> OvsBridge:
    """Run ``ovs-ofctl show <bridge>`` to fill datapath_id and port MACs.

    Tries OpenFlow 1.3 first (required for DPDK / netdev bridges), then
    falls back to OpenFlow 1.5 and finally the protocol-agnostic default.
    Port entries without an ``addr:`` field (common for DPDK ports) are
    still parsed so that the ofport → interface mapping is populated.
    """
    raw = ""
    for proto_flag in ("-O OpenFlow13 ", "-O OpenFlow15 ", ""):
        try:
            raw = executor.run(f"ovs-ofctl {proto_flag}show {bridge.name}")
            if raw.strip():
                break
        except Exception:
            logger.debug(
                "ovs-ofctl %sshow failed for bridge %s", proto_flag, bridge.name
            )

    if not raw.strip():
        logger.debug("ovs-ofctl show returned empty for bridge %s", bridge.name)
        return bridge

    dpid_match = re.search(r"dpid:([0-9a-fA-F]+)", raw)
    if dpid_match:
        bridge.datapath_id = dpid_match.group(1)

    # Match numbered ports with optional addr — DPDK ports may omit addr entirely.
    # Example lines:
    #   " 1(wan1): addr:8c:a6:82:4f:fe:d8"
    #   " 3(lan1):"                          ← no addr
    port_pattern = re.compile(
        r"^\s*(\d+)\((\S+)\):\s*(?:addr:(\S+))?", re.MULTILINE
    )
    local_pattern = re.compile(
        r"^\s*LOCAL\((\S+)\):\s*(?:addr:(\S+))?", re.MULTILINE
    )

    # ofport_map: ofport → (iface_name, mac_or_None)
    ofport_map: dict[int, tuple[str, str | None]] = {}

    for m in port_pattern.finditer(raw):
        ofport = int(m.group(1))
        iface_name = m.group(2)
        mac = m.group(3)  # may be None if addr field absent
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
            if mac and not port_info.mac:
                port_info.mac = mac
        elif port_info.interface is not None:
            for ofport, (iface_name, mac) in ofport_map.items():
                if iface_name == port_info.interface:
                    if port_info.ofport is None:
                        port_info.ofport = ofport
                    if mac and not port_info.mac:
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
    """Dump OpenFlow flows from *bridge*, retrying with newer protocol versions.

    ``ovs-ofctl dump-flows`` defaults to OpenFlow 1.0.  DPDK / netdev bridges
    (such as ``br-int``) are often configured with OpenFlow 1.3 or 1.5 and
    return empty output when queried with the default protocol.  We therefore
    try OpenFlow 1.3 first, then 1.5, then the protocol-agnostic default so
    that all bridge types are covered without needing per-bridge configuration.
    """
    table_suffix = f" table={table}" if table is not None else ""

    for proto_flag in ("-O OpenFlow13 ", "-O OpenFlow15 ", ""):
        cmd = f"ovs-ofctl {proto_flag}dump-flows {bridge}{table_suffix}"
        try:
            raw = executor.run(cmd)
        except Exception:
            logger.debug("ovs-ofctl %sdump-flows failed for bridge %s", proto_flag, bridge)
            continue

        if raw.strip():
            return parse_ovs_flows(raw, bridge)

    logger.debug("ovs-ofctl dump-flows returned empty for bridge %s (all protocols tried)", bridge)
    return []


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

        m = re.match(r"ofport\s*:\s*(\d+)", stripped)
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
        if len(actions_split) != 2:
            # Skip header lines like "NXST_FLOW reply ..." that lack an
            # actions= field and are not actual flow entries.
            continue
        before_actions = actions_split[0]
        actions = actions_split[1]

        known_keys = {"cookie", "duration", "table", "n_packets", "n_bytes", "idle_age", "priority", "send_flow_rem", "hard_timeout", "idle_timeout"}
        parts = _split_ovs_csv(before_actions)
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

        action_list = _split_ovs_csv(actions)
        match_fields = _parse_match_fields(match)

        flows.append(
            OvsFlow(
                bridge=bridge,
                table=table,
                priority=priority,
                match=match,
                actions=actions,
                match_fields=match_fields,
                action_list=action_list,
                cookie=cookie,
                duration_sec=duration_sec,
                n_packets=n_packets,
                n_bytes=n_bytes,
                idle_age_sec=idle_age_sec,
            )
        )

    return flows


def get_ovs_groups(
    executor: RemoteExecutor,
    bridge: str | None = None,
    group_id: int | None = None,
) -> list[OvsGroup]:
    """Collect OVS group table entries from one or all OVS bridges."""
    if bridge is None:
        bridges = get_ovs_bridges(executor)
        groups: list[OvsGroup] = []
        for br in bridges:
            groups.extend(_collect_groups_for_bridge(executor, br.name, group_id=group_id))
        return groups

    return _collect_groups_for_bridge(executor, bridge, group_id=group_id)


def _collect_groups_for_bridge(
    executor: RemoteExecutor,
    bridge: str,
    group_id: int | None = None,
) -> list[OvsGroup]:
    """Collect OVS groups from a specific bridge.

    Tries OpenFlow 1.3 first (required for DPDK / netdev bridges), then
    falls back to OpenFlow 1.5 and finally the protocol-agnostic default,
    mirroring the same strategy used by ``_collect_flows_for_bridge``.
    """
    group_suffix = f" group_id={group_id}" if group_id is not None else ""

    for proto_flag in ("-O OpenFlow13 ", "-O OpenFlow15 ", ""):
        cmd = f"ovs-ofctl {proto_flag}dump-groups {bridge}{group_suffix}"
        try:
            raw = executor.run(cmd)
        except Exception:
            logger.debug(
                "ovs-ofctl %sdump-groups failed for bridge %s", proto_flag, bridge
            )
            continue

        if raw.strip():
            return _parse_groups(raw)

    logger.debug(
        "ovs-ofctl dump-groups returned empty for bridge %s (all protocols tried)", bridge
    )
    return []


def _parse_groups(output: str) -> list[OvsGroup]:
    """Parse ``ovs-ofctl -O OpenFlow13 dump-groups`` output.

    OpenFlow 1.3 format (one group per line, no ``buckets=[...]`` wrapper)::

        group_id=1,type=select,bucket=weight:100,actions=output:1,bucket=weight:100,actions=output:2

    OpenFlow 1.5 / legacy format (buckets wrapped in square brackets)::

        group_id=1,type=select,buckets=[bucket=weight:100,actions=output:1]

    Both formats are handled.
    """
    groups: list[OvsGroup] = []

    for line in output.splitlines():
        line = line.strip()
        if not line or not line.startswith("group_id="):
            continue

        gid_m = re.match(r"group_id=(\d+),type=(\w+),?(.*)", line)
        if not gid_m:
            continue

        group_id = int(gid_m.group(1))
        group_type = gid_m.group(2)
        rest = gid_m.group(3)

        # Strip legacy ``buckets=[...]`` wrapper if present
        legacy_m = re.match(r"buckets=\[(.*)\]$", rest)
        if legacy_m:
            buckets_str = legacy_m.group(1)
        else:
            buckets_str = rest

        buckets = _parse_buckets(buckets_str, group_type)

        group = OvsGroup(
            group_id=group_id,
            group_type=group_type,
            n_buckets=len(buckets),
            buckets=buckets,
        )
        group.packet_count = sum(b.packet_count for b in buckets)
        group.byte_count = sum(b.byte_count for b in buckets)

        groups.append(group)

    return groups


def _parse_buckets(buckets_str: str, group_type: str) -> list[OvsGroupBucket]:
    """Split a comma-separated bucket string into individual bucket specs.

    Each bucket starts with the literal token ``bucket=``.  Everything between
    two consecutive ``bucket=`` tokens (or between the last ``bucket=`` and the
    end of the string) belongs to that bucket.
    """
    buckets: list[OvsGroupBucket] = []
    bucket_id = 0
    for part in re.split(r",?bucket=", buckets_str):
        part = part.strip()
        if not part:
            continue
        buckets.append(_parse_single_bucket(part, bucket_id, group_type))
        bucket_id += 1
    return buckets


def _parse_single_bucket(content: str, bucket_id: int, group_type: str) -> OvsGroupBucket:
    """Parse a single bucket spec such as::

        weight:100,actions=set_field:8c:a6:82:4f:fe:d8->eth_src,set_field:60:0b:03:c5:f4:01->eth_dst,output:4

    The ``actions=`` value extends to the end of *content* because it is always
    the last field in a bucket definition.
    """
    weight = 1
    actions = ""
    packet_count = 0
    byte_count = 0
    watch_port = None
    watch_group = None
    active = None

    # Split off the actions= tail first so that MAC addresses containing ":"
    # do not confuse the key=value parsing that follows.
    actions_split = content.split("actions=", 1)
    pre_actions = actions_split[0]
    if len(actions_split) == 2:
        actions = actions_split[1].rstrip(",")

    # Parse scalar fields from the pre-actions portion
    weight_m = re.search(r"weight:(\d+)", pre_actions)
    if weight_m:
        weight = int(weight_m.group(1))

    pkt_m = re.search(r"packet_count=(\d+)", pre_actions)
    if pkt_m:
        packet_count = int(pkt_m.group(1))

    byte_m = re.search(r"byte_count=(\d+)", pre_actions)
    if byte_m:
        byte_count = int(byte_m.group(1))

    port_m = re.search(r"watch_port:(\d+)", pre_actions)
    if port_m:
        watch_port = int(port_m.group(1))

    group_m = re.search(r"watch_group:(\d+)", pre_actions)
    if group_m:
        watch_group = int(group_m.group(1))

    if group_type == "ff":
        active = (bucket_id == 0)

    return OvsGroupBucket(
        bucket_id=bucket_id,
        weight=weight,
        actions=actions,
        packet_count=packet_count,
        byte_count=byte_count,
        watch_port=watch_port,
        watch_group=watch_group,
        active=active,
    )
