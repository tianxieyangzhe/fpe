"""Rule walk and OVS flow walk analysis.

Extracted from the MCP tool handler layer so that walk-building logic
lives in the analyzer domain and can be reused across handlers,
the engine, and any future consumers.
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any

from fpe.collectors import find_best_route, get_route
from fpe.command.executor import RemoteExecutor
from fpe.models import OvsBridge, OvsFlow, OvsPortInfo, PacketContext, RouteResult, RuleInfo


# ── IP matching ────────────────────────────────────────────────────────

def _matches_ip(value: str, selector: str) -> bool:
    """Check whether *value* falls inside *selector* (exact or CIDR)."""
    if not selector:
        return True
    try:
        if "/" in selector:
            return ipaddress.ip_address(value) in ipaddress.ip_network(selector, strict=False)
        return value == selector
    except ValueError:
        return False


# ── Rule matching ──────────────────────────────────────────────────────

def _rule_matches_packet(rule: RuleInfo, packet: PacketContext) -> bool:
    """Return True when *rule* selectors match *packet* fields."""
    raw = rule.raw

    from_m = re.search(r"\bfrom\s+(\S+)", raw)
    if from_m and from_m.group(1) != "all" and not _matches_ip(packet.src_ip, from_m.group(1)):
        return False

    to_m = re.search(r"\bto\s+(\S+)", raw)
    if to_m and to_m.group(1) != "all" and not _matches_ip(packet.dst_ip, to_m.group(1)):
        return False

    iif_m = re.search(r"\biif\s+(\S+)", raw)
    if iif_m and packet.ingress_if != iif_m.group(1):
        return False

    fwmark_m = re.search(r"\bfwmark\s+(\S+)", raw)
    if fwmark_m and packet.fwmark != fwmark_m.group(1):
        return False

    return True


# ── OVS helpers ────────────────────────────────────────────────────────

def _find_bridge_port(
    bridges: list[OvsBridge],
    *,
    interface: str | None = None,
    port_name: str | None = None,
) -> tuple[OvsBridge | None, OvsPortInfo | None]:
    """Locate a bridge and its port by interface name or port name."""
    for bridge in bridges:
        for port in bridge.ports:
            if interface and (port.interface == interface or port.port == interface):
                return bridge, port
            if port_name and port.port == port_name:
                return bridge, port
    return None, None


def _allowed_in_ports(ingress_port: OvsPortInfo) -> set[str]:
    """Return the set of port identifiers valid for an in_port match."""
    allowed: set[str] = {
        str(ingress_port.ofport) if ingress_port.ofport is not None else "",
        ingress_port.port,
        ingress_port.interface or "",
    }
    if ingress_port.port == ingress_port.bridge or ingress_port.interface == ingress_port.bridge:
        allowed.add("LOCAL")
        allowed.add("65534")
    return allowed


def _analyze_flow_match(
    flow: OvsFlow,
    packet: PacketContext,
    ingress_port: OvsPortInfo,
) -> dict[str, Any]:
    """Deep-match a single OVS flow against *packet* with explanation.

    Returns a dict with:
    * ``matched`` — True when every known field matches and nothing is unknown
    * ``reasons`` — list of concrete mismatch explanations
    * ``unknown_requirements`` — fields the flow requires but the packet omits
    * ``score`` — weighted penalty (lower is better)
    """
    # Protocol name → IP protocol number mapping
    _PROTO_MAP: dict[str, int] = {
        "icmp": 1, "igmp": 2, "tcp": 6, "udp": 17,
        "gre": 47, "esp": 50, "ah": 51, "icmp6": 58,
        "ospf": 89, "sctp": 132,
    }

    fields = flow.match_fields
    if not fields:
        return {"matched": True, "reasons": [], "unknown_requirements": [], "score": 0}

    reasons: list[str] = []
    unknown_requirements: list[str] = []

    for key, value in fields.items():
        if key == "in_port":
            if value not in _allowed_in_ports(ingress_port):
                reasons.append(f"in_port expected {value}, got {ingress_port.ofport or ingress_port.port}")
        elif key in {"ip", "ipv6"}:
            expected = "ipv6" if packet.ip_version == 6 else "ip"
            if key != expected:
                reasons.append(f"protocol family expected {key}, got {expected}")
        elif key in {"tcp", "udp", "icmp", "arp", "icmp6"}:
            if not packet.protocol:
                unknown_requirements.append(f"packet protocol required: {key}")
            elif packet.protocol.lower() != key:
                reasons.append(f"protocol expected {key}, got {packet.protocol.lower()}")
        elif key == "nw_proto":
            # OVS nw_proto is the IP protocol number (e.g. 6=TCP, 17=UDP)
            if not packet.protocol:
                unknown_requirements.append(f"packet protocol required for nw_proto={value}")
            else:
                try:
                    expected_proto = int(value)
                except ValueError:
                    reasons.append(f"unparseable nw_proto {value}")
                else:
                    proto_lower = packet.protocol.lower()
                    actual_proto = _PROTO_MAP.get(proto_lower)
                    if actual_proto is None:
                        unknown_requirements.append(f"unknown protocol {proto_lower} for nw_proto={value}")
                    elif actual_proto != expected_proto:
                        reasons.append(f"nw_proto expected {expected_proto}, got {actual_proto} ({proto_lower})")
        elif key in {"nw_src", "ipv6_src"}:
            if not _matches_ip(packet.src_ip, value):
                reasons.append(f"src_ip expected {value}, got {packet.src_ip}")
        elif key in {"nw_dst", "ipv6_dst"}:
            if not _matches_ip(packet.dst_ip, value):
                reasons.append(f"dst_ip expected {value}, got {packet.dst_ip}")
        elif key in {"tp_src", "tcp_src", "udp_src"}:
            if packet.src_port is None:
                unknown_requirements.append(f"src_port required: {value}")
            elif str(packet.src_port) != value:
                reasons.append(f"src_port expected {value}, got {packet.src_port}")
        elif key in {"tp_dst", "tcp_dst", "udp_dst"}:
            if packet.dst_port is None:
                unknown_requirements.append(f"dst_port required: {value}")
            elif str(packet.dst_port) != value:
                reasons.append(f"dst_port expected {value}, got {packet.dst_port}")
        elif key in {"dl_vlan", "vlan_vid"}:
            if packet.vlan_id is None:
                unknown_requirements.append(f"vlan_id required: {value}")
            else:
                try:
                    parsed = int(value, 16) if value.startswith("0x") else int(value)
                except ValueError:
                    reasons.append(f"unparseable vlan selector {value}")
                else:
                    if parsed & 0x0FFF != packet.vlan_id:
                        reasons.append(f"vlan_id expected {parsed & 0x0FFF}, got {packet.vlan_id}")
        elif key == "tun_id":
            if packet.tunnel_id is None:
                unknown_requirements.append(f"tunnel_id required: {value}")
            elif str(packet.tunnel_id) != value:
                reasons.append(f"tunnel_id expected {value}, got {packet.tunnel_id}")
        elif key == "dl_dst":
            # Destination MAC — cannot verify without packet-level dst_mac
            unknown_requirements.append(f"dst_mac required: {value}")

    matched = not reasons and not unknown_requirements
    score = len(reasons) * 10 + len(unknown_requirements)
    return {
        "matched": matched,
        "reasons": reasons,
        "unknown_requirements": unknown_requirements,
        "score": score,
    }


def _resolve_ingress_port(
    bridges: list[OvsBridge],
    *,
    bridge_name: str | None,
    ingress_if: str | None = None,
    start_port: str | None = None,
) -> tuple[str | None, OvsPortInfo | None]:
    """Resolve the bridge and OVS port that a packet enters on."""
    if ingress_if:
        found_bridge, found_port = _find_bridge_port(bridges, interface=ingress_if)
        if found_bridge and found_port:
            return found_bridge.name, found_port
    if start_port:
        if bridge_name:
            bridge = next((item for item in bridges if item.name == bridge_name), None)
            if bridge:
                for port in bridge.ports:
                    if start_port in {port.port, port.interface, str(port.ofport), "LOCAL" if port.port == bridge.name else ""}:
                        return bridge.name, port
        found_bridge, found_port = _find_bridge_port(bridges, port_name=start_port)
        if found_bridge and found_port:
            return found_bridge.name, found_port
    return bridge_name, None


# ── Flow walk (OVS table traversal) ────────────────────────────────────

def build_candidate_flow_walk(
    flows: list[OvsFlow],
    ingress_port: OvsPortInfo,
    packet: PacketContext | None = None,
    max_steps: int = 16,
) -> list[dict[str, Any]]:
    """Walk OVS flow tables starting from table 0, selecting the best
    candidate flow at each step.

    Each step records:
    * ``table`` — the flow table number
    * ``status`` — ``selected``, ``no_flow``, ``no_candidate``, or ``loop_detected``
    * ``flow`` — the selected flow (when status is ``selected``)
    * ``match_quality`` — ``confirmed``, ``candidate``, or ``weak_candidate``
    * ``non_match_reasons`` — concrete reasons the flow did NOT match
    * ``unknown_requirements`` — fields the flow requires but the packet omits
    """
    by_table: dict[int, list[OvsFlow]] = {}
    for flow in flows:
        by_table.setdefault(flow.table, []).append(flow)
    for table_flows in by_table.values():
        table_flows.sort(key=lambda item: item.priority, reverse=True)

    walk: list[dict[str, Any]] = []
    visited: set[int] = set()
    current_table = 0

    for _ in range(max_steps):
        if current_table in visited:
            walk.append({"table": current_table, "status": "loop_detected"})
            break
        visited.add(current_table)
        table_flows = by_table.get(current_table, [])
        if not table_flows:
            walk.append({"table": current_table, "status": "no_flow"})
            break

        ranked: list[tuple[int, OvsFlow, dict[str, Any]]] = []
        for flow in table_flows:
            analysis = (
                _analyze_flow_match(flow, packet, ingress_port)
                if packet
                else {"matched": False, "reasons": [], "unknown_requirements": [], "score": 0}
            )
            if flow.match_fields.get("in_port") and flow.match_fields["in_port"] not in _allowed_in_ports(ingress_port):
                continue
            score = analysis["score"] if packet else 0
            ranked.append((score, flow, analysis))
        if not ranked:
            walk.append({"table": current_table, "status": "no_candidate"})
            break

        ranked.sort(key=lambda item: (item[0], -item[1].priority, -(item[1].n_packets or 0)))
        score, selected, analysis = ranked[0]
        walk.append(
            {
                "table": current_table,
                "status": "selected",
                "flow": selected.model_dump(),
                "match_quality": (
                    "confirmed"
                    if analysis.get("matched")
                    else ("candidate" if score <= 1 else "weak_candidate")
                ),
                "non_match_reasons": analysis.get("reasons", []),
                "unknown_requirements": analysis.get("unknown_requirements", []),
            }
        )

        next_table = None
        for action in selected.action_list:
            goto = re.search(r"resubmit\([^,]*,\s*(\d+)\)", action) or re.search(r"goto_table:(\d+)", action)
            if goto:
                next_table = int(goto.group(1))
                break
        if next_table is None:
            break
        current_table = next_table

    return walk


# ── Rule walk (policy routing lookup chain) ────────────────────────────

def build_rule_walk(
    executor: RemoteExecutor,
    rules: list[RuleInfo],
    packet: PacketContext | None = None,
    namespace: str | None = None,
    vrf: str | None = None,
) -> dict[str, Any]:
    """Walk IP rules sorted by priority, trying to find a route in each
    rule's lookup table.  The first rule whose table yields a valid route
    wins ("terminates lookup").

    When *packet* is provided, only rules whose selectors match the packet
    are considered.  When *packet* is ``None`` (structural walk), all
    rules are walked and each table is checked for the presence of routes.

    Returns a dict with:
    * ``matched_rules`` — every rule whose selectors match *packet* (all rules when packet is None)
    * ``rule_walk`` — step-by-step record of each rule tried
    * ``effective_rule`` — the first terminating rule (None for structural walks)
    * ``effective_table`` — the table of that rule
    * ``effective_route`` — the route found in that table
    * ``final_table`` — alias for ``effective_table``
    """
    sorted_rules = sorted(rules, key=lambda item: item.priority)
    if packet is not None:
        candidate_rules = [rule for rule in sorted_rules if _rule_matches_packet(rule, packet)]
    else:
        candidate_rules = sorted_rules

    walk: list[dict[str, Any]] = []
    effective_rule: RuleInfo | None = None
    effective_route: RouteResult | None = None

    for rule in candidate_rules:
        routes = get_route(
            executor,
            table=rule.table if rule.table not in {"main", ""} else "",
            namespace=namespace,
            vrf=vrf,
        )
        if packet is not None:
            best_route = find_best_route(routes, packet.dst_ip)
            terminated = best_route is not None
            reason = "route_found" if terminated else f"no_route_for_{packet.dst_ip}"
        else:
            best_route = routes[0] if routes else None
            terminated = best_route is not None
            reason = "table_has_routes" if routes else "empty_table"
        walk.append(
            {
                "priority": rule.priority,
                "table": rule.table,
                "raw": rule.raw,
                "lookup_result": reason,
                "best_route": best_route.model_dump() if best_route else None,
                "terminates_lookup": terminated and packet is not None,
            }
        )
        if terminated and effective_rule is None and packet is not None:
            effective_rule = rule
            effective_route = best_route
            break

    return {
        "matched_rules": candidate_rules,
        "rule_walk": walk,
        "effective_rule": effective_rule,
        "effective_table": effective_rule.table if effective_rule else None,
        "final_table": effective_rule.table if effective_rule else None,
        "effective_route": effective_route,
    }
