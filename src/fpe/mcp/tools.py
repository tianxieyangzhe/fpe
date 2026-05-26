"""MCP tool handler definitions and registry.

Every tool handler follows the ``ToolHandler`` protocol and returns
a ``ToolResult`` envelope.
"""

from __future__ import annotations

from typing import Any, Protocol

from fpe.analyzer import (
    Analyzer,
)
from fpe.analyzer.walks import (
    build_candidate_flow_walk,
    build_rule_walk,
    _analyze_flow_match,
    _find_bridge_port,
    _resolve_ingress_port,
)
from fpe.collectors import (
    find_best_route,
    get_interface_context,
    get_neighbors,
    get_ovs_bridges,
    get_ovs_flows,
    get_ovs_groups,
    get_route,
    get_rules,
)
from fpe.command.executor import RemoteExecutor
from fpe.models import (
    ExecContext,
    FpeError,
    OvsBridge,
    OvsFlow,
    OvsGroup,
    OvsGroupBucket,
    OvsPortInfo,
    PacketContext,
    RuleInfo,
    ToolResult,
)


# ── Protocol ─────────────────────────────────────────────────────────

class ToolHandler(Protocol):
    """Protocol for MCP tool handlers."""

    name: str
    description: str = ""

    async def handle(self, payload: dict[str, Any]) -> ToolResult:
        """Handle an MCP tool invocation."""
        ...

    def input_schema(self) -> dict[str, Any]:
        """Return the JSON Schema for this tool's input parameters."""
        return {"type": "object", "properties": {}, "required": []}


# ── Registry ─────────────────────────────────────────────────────────

class ToolRegistry:
    """Registry for MCP tool handlers."""

    def __init__(self) -> None:
        self._handlers: dict[str, ToolHandler] = {}

    def register(self, handler: ToolHandler) -> None:
        """Register a tool handler."""
        self._handlers[handler.name] = handler

    def get(self, name: str) -> ToolHandler:
        """Get a registered tool handler by name."""
        handler = self._handlers.get(name)
        if handler is None:
            raise FpeError(f"Unknown tool: {name}")
        return handler

    def list_tools(self) -> list[dict[str, Any]]:
        """List all registered tools (for MCP capability advertisement)."""
        return [
            {
                "name": name,
                "description": handler.description,
                "inputSchema": handler.input_schema(),
            }
            for name, handler in self._handlers.items()
        ]


# ── Tool handlers ────────────────────────────────────────────────────

class AnalyzeFlowHandler:
    """Handler for ``fpe.analyze_flow`` — complete flow analysis."""

    name = "fpe.analyze_flow"
    description = "Complete flow analysis for a given packet"

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "packet": {
                    "type": "object",
                    "description": "Packet context (src_ip, dst_ip, protocol, ports, etc.)",
                    "properties": {
                        "src_ip": {"type": "string", "description": "Source IP address"},
                        "dst_ip": {"type": "string", "description": "Destination IP address"},
                        "protocol": {"type": "string", "description": "IP protocol (tcp, udp, icmp, etc.)"},
                        "src_port": {"type": "integer", "description": "Source port"},
                        "dst_port": {"type": "integer", "description": "Destination port"},
                        "ingress_if": {"type": "string", "description": "Ingress interface"},
                        "egress_if": {"type": "string", "description": "Egress interface"},
                        "fwmark": {"type": "string", "description": "Firewall mark"},
                        "tos": {"type": "integer", "description": "Type of service value"},
                        "vlan_id": {"type": "integer", "description": "Ingress VLAN ID used for OVS flow matching"},
                        "tunnel_id": {"type": "string", "description": "Tunnel ID / VNI used for OVS flow matching"},
                        "ip_version": {"type": "integer", "description": "IP version (4 or 6)", "default": 4},
                    },
                    "required": ["src_ip", "dst_ip"],
                },
                "exec_ctx": {
                    "type": "object",
                    "description": "Execution context for namespace / VRF selection",
                    "properties": {
                        "namespace": {"type": "string"},
                        "vrf": {"type": "string"},
                        "host": {"type": "string"},
                    },
                },
                "options": {
                    "type": "object",
                    "description": "Optional analysis options",
                },
            },
            "required": ["packet"],
        }

    async def handle(self, payload: dict[str, Any]) -> ToolResult:
        try:
            packet = PacketContext(**payload.get("packet", {}))
            exec_ctx = ExecContext(**payload.get("exec_ctx", {}))
            options = payload.get("options", {})

            analyzer = Analyzer()
            result = await analyzer.analyze(
                packet=packet,
                exec_ctx=exec_ctx,
                options=options,
                host=exec_ctx.host,
            )

            return ToolResult(
                ok=True,
                tool=self.name,
                data=result.model_dump(),
            )
        except Exception as e:
            return ToolResult(ok=False, tool=self.name, error=str(e))


class GetInterfaceContextHandler:
    """Handler for ``fpe.get_interface_context``."""

    name = "fpe.get_interface_context"
    description = "Get network interface context and attributes from one or all namespaces"

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "iface": {"type": "string", "description": "Interface name (optional, omit to get all interfaces)"},
                "namespace": {"type": "string", "description": "Namespace to query. Omit to auto-discover all namespaces. Pass empty string for root namespace."},
                "vrf": {"type": "string", "description": "VRF name to filter by. Omit to include all VRFs. Pass empty string for default VRF."},
                "if_type": {"type": "string", "description": "Filter by interface type such as physical, veth, bridge, vrf, tun."},
                "role": {"type": "string", "description": "Filter by inferred role such as underlay-uplink, bridge-port, vrf-member."},
                "state": {"type": "string", "description": "Filter by operational state such as UP or DOWN."},
            },
            "required": [],
        }

    async def handle(self, payload: dict[str, Any]) -> ToolResult:
        try:
            iface = payload.get("iface", "")
            namespace = payload.get("namespace")
            vrf = payload.get("vrf")
            if_type = payload.get("if_type")
            role = payload.get("role")
            state = payload.get("state")

            executor = RemoteExecutor()
            results = get_interface_context(executor, iface=iface, namespace=namespace, vrf=vrf)
            if if_type:
                results = [r for r in results if r.if_type == if_type]
            if role:
                results = [r for r in results if r.role == role]
            if state:
                results = [r for r in results if r.state == state]

            return ToolResult(
                ok=True,
                tool=self.name,
                data={
                    "interfaces": [r.model_dump() for r in results],
                    "count": len(results),
                },
            )
        except Exception as e:
            return ToolResult(ok=False, tool=self.name, error=str(e))


class GetRuleHandler:
    """Handler for ``fpe.get_rule`` — IP policy routing rules."""

    name = "fpe.get_rule"
    description = "Get IP policy routing rules from one or all namespaces"

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "namespace": {
                    "type": "string",
                    "description": "Namespace to query. Omit to auto-discover all namespaces. Pass empty string for root namespace.",
                },
                "vrf": {
                    "type": "string",
                    "description": "VRF name to filter by. Omit to include all VRFs. Pass empty string for default VRF.",
                },
                "priority": {
                    "type": "integer",
                    "description": "Filter by rule priority.",
                },
                "table": {
                    "type": "string",
                    "description": "Filter by routing table name or number.",
                },
                "packet": {
                    "type": "object",
                    "description": "Optional packet context used to identify matched and selected rules.",
                    "properties": {
                        "src_ip": {"type": "string"},
                        "dst_ip": {"type": "string"},
                        "protocol": {"type": "string"},
                        "src_port": {"type": "integer"},
                        "dst_port": {"type": "integer"},
                        "ingress_if": {"type": "string"},
                        "fwmark": {"type": "string"},
                        "ip_version": {"type": "integer", "default": 4},
                    },
                    "required": ["src_ip", "dst_ip"],
                },
                "include_rule_walk": {
                    "type": "boolean",
                    "description": "Include a priority-ordered rule walk showing each rule's lookup table and best route. When combined with packet, only packet-matching rules are shown and the first terminating rule is reported as effective_rule.",
                },
            },
            "required": [],
        }

    async def handle(self, payload: dict[str, Any]) -> ToolResult:
        try:
            namespace = payload.get("namespace")
            vrf = payload.get("vrf")
            priority = payload.get("priority")
            table = payload.get("table")
            packet_payload = payload.get("packet")
            include_rule_walk = bool(payload.get("include_rule_walk", False))

            executor = RemoteExecutor()
            results = get_rules(executor, namespace=namespace, vrf=vrf)

            # Apply client-side filters
            if priority is not None:
                results = [r for r in results if r.priority == priority]
            if table:
                results = [r for r in results if r.table == table]

            selected_rule = None
            matched_rules: list[RuleInfo] = []
            effective_rule = None
            effective_route = None
            effective_table = None
            final_table = None
            rule_walk: list[dict[str, Any]] = []

            if packet_payload:
                packet = PacketContext(**packet_payload)
                walk_result = build_rule_walk(executor, results, packet=packet, namespace=namespace, vrf=vrf)
                matched_rules = walk_result["matched_rules"]
                selected_rule = matched_rules[0] if matched_rules else None
                effective_rule = walk_result["effective_rule"]
                effective_route = walk_result["effective_route"]
                effective_table = walk_result["effective_table"]
                final_table = walk_result["final_table"]
                rule_walk = walk_result["rule_walk"]
            elif include_rule_walk:
                # Structural walk: show all rules and their table routing state
                walk_result = build_rule_walk(executor, results, packet=None, namespace=namespace, vrf=vrf)
                matched_rules = walk_result["matched_rules"]
                selected_rule = matched_rules[0] if matched_rules else None
                effective_rule = walk_result["effective_rule"]
                effective_route = walk_result["effective_route"]
                effective_table = walk_result["effective_table"]
                final_table = walk_result["final_table"]
                rule_walk = walk_result["rule_walk"]

            return ToolResult(
                ok=True,
                tool=self.name,
                data={
                    "rules": [r.model_dump() for r in results],
                    "matched_rules": [r.model_dump() for r in matched_rules],
                    "selected_rule": selected_rule.model_dump() if selected_rule else None,
                    "effective_rule": effective_rule.model_dump() if effective_rule else None,
                    "effective_table": effective_table,
                    "final_table": final_table,
                    "effective_route": effective_route.model_dump() if effective_route else None,
                    "rule_walk": rule_walk,
                    "count": len(results),
                },
            )
        except Exception as e:
            return ToolResult(ok=False, tool=self.name, error=str(e))


class GetRouteHandler:
    """Handler for ``fpe.get_route`` — routing table entries."""

    name = "fpe.get_route"
    description = "Get routing table entries from one or all namespaces"

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "namespace": {
                    "type": "string",
                    "description": "Namespace to query. Omit to auto-discover all namespaces. Pass empty string for root namespace.",
                },
                "vrf": {
                    "type": "string",
                    "description": "VRF name to filter by. Omit to include all VRFs. Pass empty string for default VRF.",
                },
                "table": {
                    "type": "string",
                    "description": "Routing table name or number (optional, defaults to all).",
                },
                "dst_ip": {
                    "type": "string",
                    "description": "Find the most specific route matching this destination IP.",
                },
                "device": {
                    "type": "string",
                    "description": "Filter routes whose next hop uses this device.",
                },
                "best_only": {
                    "type": "boolean",
                    "description": "When dst_ip is set, return only the best matched route.",
                },
            },
            "required": [],
        }

    async def handle(self, payload: dict[str, Any]) -> ToolResult:
        try:
            namespace = payload.get("namespace")
            vrf = payload.get("vrf")
            table = payload.get("table", "")
            dst_ip = payload.get("dst_ip")
            device = payload.get("device")
            best_only = bool(payload.get("best_only", False))

            executor = RemoteExecutor()
            routes = get_route(executor, table=table, namespace=namespace, vrf=vrf)
            if device:
                routes = [r for r in routes if any(nh.dev == device for nh in r.next_hops)]

            if dst_ip:
                from fpe.collectors import find_best_route
                best = find_best_route(routes, dst_ip)
                return ToolResult(
                    ok=True,
                    tool=self.name,
                    data={
                        "routes": [best.model_dump()] if best_only and best else [r.model_dump() for r in routes],
                        "best_route": best.model_dump() if best else None,
                        "dst_ip": dst_ip,
                        "count": 1 if best_only and best else len(routes),
                    },
                )

            return ToolResult(
                ok=True,
                tool=self.name,
                data={"routes": [r.model_dump() for r in routes], "count": len(routes)},
            )
        except Exception as e:
            return ToolResult(ok=False, tool=self.name, error=str(e))


class GetNeighborHandler:
    """Handler for ``fpe.get_neighbor`` — neighbor (ARP/NDP) table."""

    name = "fpe.get_neighbor"
    description = "Get neighbor (ARP/NDP) table entries from one or all namespaces"

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "namespace": {
                    "type": "string",
                    "description": "Namespace to query. Omit to auto-discover all namespaces. Pass empty string for root namespace.",
                },
                "vrf": {
                    "type": "string",
                    "description": "VRF name to filter by. Omit to include all VRFs. Pass empty string for default VRF.",
                },
                "device": {
                    "type": "string",
                    "description": "Device or interface name to filter by.",
                },
                "target_ip": {
                    "type": "string",
                    "description": "Target IP address to filter by.",
                },
                "state": {
                    "type": "string",
                    "description": "Filter by neighbor state such as REACHABLE, STALE, FAILED.",
                },
                "reachable_only": {
                    "type": "boolean",
                    "description": "Return only reachable neighbors.",
                },
            },
            "required": [],
        }

    async def handle(self, payload: dict[str, Any]) -> ToolResult:
        try:
            namespace = payload.get("namespace")
            vrf = payload.get("vrf")
            device = payload.get("device", "")
            target_ip = payload.get("target_ip")
            state_filter = payload.get("state")
            reachable_only = bool(payload.get("reachable_only", False))

            executor = RemoteExecutor()
            results = get_neighbors(
                executor,
                device=device,
                target_ip=target_ip,
                namespace=namespace,
                vrf=vrf,
            )
            if state_filter:
                results = [n for n in results if n.state == state_filter]
            if reachable_only:
                results = [n for n in results if n.reachable]

            return ToolResult(
                ok=True,
                tool=self.name,
                data={"neighbors": [n.model_dump() for n in results], "count": len(results)},
            )
        except Exception as e:
            return ToolResult(ok=False, tool=self.name, error=str(e))


class GetOvsBridgesHandler:
    """Handler for ``fpe.get_ovs_bridges`` — OVS bridge topology."""

    name = "fpe.get_ovs_bridges"
    description = "Get Open vSwitch (OVS) bridge topology including ports, VLAN config, and datapath metadata"

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "bridge": {
                    "type": "string",
                    "description": "Filter to a single OVS bridge.",
                },
                "port": {
                    "type": "string",
                    "description": "Return only bridges containing this port name.",
                },
                "interface": {
                    "type": "string",
                    "description": "Return only bridges containing this interface.",
                },
                "include_flows": {
                    "type": "boolean",
                    "description": "Also include per-bridge flows in the response.",
                },
            },
            "required": [],
        }

    async def handle(self, payload: dict[str, Any]) -> ToolResult:
        try:
            bridge_name = payload.get("bridge")
            port_name = payload.get("port")
            interface = payload.get("interface")
            include_flows = bool(payload.get("include_flows", False))

            executor = RemoteExecutor()
            bridges = get_ovs_bridges(executor)
            if bridge_name:
                bridges = [bridge for bridge in bridges if bridge.name == bridge_name]
            if port_name:
                bridges = [bridge for bridge in bridges if any(port.port == port_name for port in bridge.ports)]
            if interface:
                bridges = [bridge for bridge in bridges if any(port.interface == interface for port in bridge.ports)]

            data: dict[str, Any] = {
                "bridges": [b.model_dump() for b in bridges],
                "count": len(bridges),
            }
            if include_flows:
                flow_map = {
                    bridge.name: [flow.model_dump() for flow in get_ovs_flows(executor, bridge=bridge.name)]
                    for bridge in bridges
                }
                data["flows_by_bridge"] = flow_map

            return ToolResult(
                ok=True,
                tool=self.name,
                data=data,
            )
        except Exception as e:
            return ToolResult(ok=False, tool=self.name, error=str(e))


class GetOvsFlowsHandler:
    """Handler for ``fpe.get_ovs_flows`` — OpenFlow flow table entries."""

    name = "fpe.get_ovs_flows"
    description = "Get OpenFlow flow table entries from OVS bridges"

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "bridge": {
                    "type": "string",
                    "description": "Bridge name to query. Omit to query all bridges.",
                },
                "table": {
                    "type": "integer",
                    "description": "Flow table number to filter by. Omit to get all tables.",
                },
                "ingress_if": {
                    "type": "string",
                    "description": "Filter flows to the bridge and port attached to this ingress interface.",
                },
                "start_port": {
                    "type": "string",
                    "description": "Explicit starting port/ofport, including LOCAL for host-side OVS entry.",
                },
                "packet": {
                    "type": "object",
                    "description": "Optional packet context used to identify matching flows.",
                    "properties": {
                        "src_ip": {"type": "string"},
                        "dst_ip": {"type": "string"},
                        "protocol": {"type": "string"},
                        "src_port": {"type": "integer"},
                        "dst_port": {"type": "integer"},
                        "ingress_if": {"type": "string"},
                        "vlan_id": {"type": "integer"},
                        "tunnel_id": {"type": "string"},
                        "ip_version": {"type": "integer", "default": 4},
                    },
                    "required": ["src_ip", "dst_ip"],
                },
                "match_contains": {
                    "type": "string",
                    "description": "Substring filter applied to the raw match expression.",
                },
                "active_only": {
                    "type": "boolean",
                    "description": "Return only flows with packet counters greater than zero.",
                },
                "include_candidate_walk": {
                    "type": "boolean",
                    "description": "Include a table-by-table candidate flow walk starting from table 0.",
                },
            },
            "required": [],
        }

    async def handle(self, payload: dict[str, Any]) -> ToolResult:
        try:
            bridge = payload.get("bridge")
            table = payload.get("table")
            ingress_if = payload.get("ingress_if")
            start_port = payload.get("start_port")
            packet_payload = payload.get("packet")
            match_contains = payload.get("match_contains")
            active_only = bool(payload.get("active_only", False))
            include_candidate_walk = bool(payload.get("include_candidate_walk", False))

            executor = RemoteExecutor()
            bridges = get_ovs_bridges(executor)
            bridge, ingress_port = _resolve_ingress_port(
                bridges,
                bridge_name=bridge,
                ingress_if=ingress_if,
                start_port=start_port,
            )
            flows = get_ovs_flows(executor, bridge=bridge, table=table)
            if match_contains:
                flows = [flow for flow in flows if match_contains in flow.match]
            if active_only:
                flows = [flow for flow in flows if (flow.n_packets or 0) > 0]

            matched_flows: list[OvsFlow] = []
            candidate_matches: list[dict[str, Any]] = []
            non_match_reasons: list[dict[str, Any]] = []
            table_walk: list[dict[str, Any]] = []
            if packet_payload:
                packet = PacketContext(**packet_payload)
                if packet.ingress_if and not ingress_port:
                    _, ingress_port = _resolve_ingress_port(
                        bridges,
                        bridge_name=bridge,
                        ingress_if=packet.ingress_if,
                    )
                if ingress_port:
                    analyzed: list[tuple[OvsFlow, dict[str, Any]]] = [
                        (flow, _analyze_flow_match(flow, packet, ingress_port)) for flow in flows
                    ]
                    matched_flows = [flow for flow, analysis in analyzed if analysis["matched"]]
                    matched_flows.sort(key=lambda item: (item.table, -item.priority))
                    candidates = [
                        (flow, analysis)
                        for flow, analysis in analyzed
                        if not analysis["matched"] and not analysis["reasons"]
                    ]
                    candidate_matches = [
                        {
                            "flow": flow.model_dump(),
                            "unknown_requirements": analysis["unknown_requirements"],
                        }
                        for flow, analysis in sorted(
                            candidates,
                            key=lambda item: (item[0].table, -item[0].priority, len(item[1]["unknown_requirements"])),
                        )
                    ]
                    mismatches = [
                        (flow, analysis)
                        for flow, analysis in analyzed
                        if analysis["reasons"]
                    ]
                    non_match_reasons = [
                        {
                            "flow": flow.model_dump(),
                            "reasons": analysis["reasons"],
                            "unknown_requirements": analysis["unknown_requirements"],
                        }
                        for flow, analysis in sorted(
                            mismatches,
                            key=lambda item: (len(item[1]["reasons"]), len(item[1]["unknown_requirements"]), item[0].table, -item[0].priority),
                        )[:20]
                    ]
                    if include_candidate_walk or not matched_flows:
                        table_walk = build_candidate_flow_walk(flows, ingress_port, packet=packet)
                elif include_candidate_walk:
                    table_walk = [{"status": "missing_ingress_port", "reason": "Could not resolve starting OVS port"}]
            elif include_candidate_walk and ingress_port:
                table_walk = build_candidate_flow_walk(flows, ingress_port, packet=None)

            return ToolResult(
                ok=True,
                tool=self.name,
                data={
                    "flows": [f.model_dump() for f in flows],
                    "matched_flows": [f.model_dump() for f in matched_flows],
                    "candidate_matches": candidate_matches,
                    "non_match_reasons": non_match_reasons,
                    "table_walk": table_walk,
                    "bridge": bridge,
                    "starting_port": ingress_port.model_dump() if ingress_port else None,
                    "count": len(flows),
                },
            )
        except Exception as e:
            return ToolResult(ok=False, tool=self.name, error=str(e))


class GetOvsGroupsHandler:
    """Handler for ``fpe.get_ovs_groups`` — OVS group table entries."""

    name = "fpe.get_ovs_groups"
    description = "Query OVS group tables for load balancing, failover, and multicast"

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "bridge": {
                    "type": "string",
                    "description": "OVS bridge name (e.g., 'br-wan1')",
                },
                "group_id": {
                    "type": "integer",
                    "description": "Specific group ID to query",
                },
                "include_buckets": {
                    "type": "boolean",
                    "description": "Include bucket details in response",
                    "default": True,
                },
                "include_stats": {
                    "type": "boolean",
                    "description": "Include packet/byte statistics",
                    "default": True,
                },
                "active_only": {
                    "type": "boolean",
                    "description": "Only return groups with traffic",
                    "default": False,
                },
            },
            "required": ["bridge"],
        }

    async def handle(self, payload: dict[str, Any]) -> ToolResult:
        try:
            bridge = payload.get("bridge")
            group_id = payload.get("group_id")
            include_buckets = bool(payload.get("include_buckets", True))
            include_stats = bool(payload.get("include_stats", True))
            active_only = bool(payload.get("active_only", False))

            if not bridge:
                return ToolResult(
                    ok=False,
                    tool=self.name,
                    error="Parameter 'bridge' is required",
                )

            executor = RemoteExecutor()
            groups = get_ovs_groups(executor, bridge=bridge, group_id=group_id)

            # Filter active groups if requested
            if active_only:
                groups = [g for g in groups if g.packet_count > 0]

            # Build response
            result_groups: list[dict[str, Any]] = []
            for group in groups:
                group_dict: dict[str, Any] = {
                    "group_id": group.group_id,
                    "type": group.group_type,
                    "n_buckets": group.n_buckets,
                }

                if include_stats:
                    group_dict["packet_count"] = group.packet_count
                    group_dict["byte_count"] = group.byte_count

                if include_buckets:
                    buckets_list: list[dict[str, Any]] = []
                    for bucket in group.buckets:
                        bucket_dict: dict[str, Any] = {
                            "bucket_id": bucket.bucket_id,
                            "weight": bucket.weight,
                            "actions": bucket.actions,
                        }
                        if include_stats:
                            bucket_dict["packet_count"] = bucket.packet_count
                            bucket_dict["byte_count"] = bucket.byte_count

                        bucket_dict["watch_port"] = bucket.watch_port
                        bucket_dict["watch_group"] = bucket.watch_group

                        if bucket.active is not None:
                            bucket_dict["active"] = bucket.active

                        buckets_list.append(bucket_dict)
                    group_dict["buckets"] = buckets_list

                result_groups.append(group_dict)

            return ToolResult(
                ok=True,
                tool=self.name,
                data={
                    "status": "success",
                    "bridge": bridge,
                    "group_count": len(result_groups),
                    "groups": result_groups,
                },
            )
        except Exception as e:
            return ToolResult(ok=False, tool=self.name, error=str(e))


# ── Factory ──────────────────────────────────────────────────────────

def create_all_handlers() -> list[ToolHandler]:
    """Create all registered MCP tool handlers."""
    return [
        AnalyzeFlowHandler(),
        GetInterfaceContextHandler(),
        GetRuleHandler(),
        GetRouteHandler(),
        GetNeighborHandler(),
        GetOvsBridgesHandler(),
        GetOvsFlowsHandler(),
        GetOvsGroupsHandler(),
    ]

