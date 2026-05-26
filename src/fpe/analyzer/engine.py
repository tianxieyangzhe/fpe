"""OVS-first flow-path analyzer with graph output."""

from __future__ import annotations

import ipaddress
import logging
import re
import uuid
from collections import defaultdict

from fpe.collectors import (
    find_best_route,
    get_interface_context,
    get_neighbors,
    get_ovs_bridges,
    get_ovs_flows,
    get_route,
    get_rules,
)
from fpe.command.executor import RemoteExecutor, _env_exec_ctx
from fpe.models import (
    AnalysisResult,
    AnalysisState,
    DecisionEvent,
    ExecContext,
    FlowGraph,
    GraphEdge,
    GraphNode,
    InterfaceContext,
    NeighborInfo,
    OvsBridge,
    OvsFlow,
    OvsPortInfo,
    PacketContext,
    PathNode,
    RiskItem,
    RouteResult,
    RuleInfo,
)

logger = logging.getLogger(__name__)

STATE_INIT = "INIT"
STATE_DISCOVERING = "DISCOVERING"
STATE_ANALYZING_OVS = "ANALYZING_OVS"
STATE_ANALYZING_L3 = "ANALYZING_L3"
STATE_COMPLETED = "COMPLETED"
STATE_INCOMPLETE = "INCOMPLETE"
STATE_FAILED = "FAILED"


def _generate_trace_id() -> str:
    return uuid.uuid4().hex[:12]


class Analyzer:
    """Flow analyzer that treats OVS as the primary forwarding plane."""

    def __init__(self, executor: RemoteExecutor | None = None) -> None:
        self._executor = executor or RemoteExecutor()

    async def analyze(
        self,
        packet: PacketContext | None = None,
        exec_ctx: ExecContext | None = None,
        options: dict | None = None,
        host: str | None = None,
    ) -> AnalysisResult:
        pkt = packet or PacketContext(src_ip="", dst_ip="")
        ctx = exec_ctx or _env_exec_ctx()
        if host and not ctx.host:
            ctx.host = host
        opts = options or {}

        state = AnalysisState(
            trace_id=_generate_trace_id(),
            flow_state=STATE_INIT,
            packet=pkt,
            exec_ctx=ctx,
            max_hops=opts.get("max_hops", 16),
        )
        self._transition(state, STATE_INIT, "state_machine", "Analysis started")

        if state.max_hops <= 0 and pkt.src_ip and pkt.dst_ip:
            self._transition(state, STATE_INCOMPLETE, "state_machine", "Max hops reached before analysis started")
            state.risks.append(
                RiskItem(
                    code="MAX_HOPS_REACHED",
                    severity="medium",
                    message="Analysis stopped because max_hops was configured to 0",
                )
            )
            return self._build_result(state)

        if not pkt.src_ip or not pkt.dst_ip or not pkt.ingress_if:
            self._transition(
                state,
                STATE_FAILED,
                "validation",
                "src_ip, dst_ip, and ingress_if are required for OVS-first analysis",
            )
            state.risks.append(
                RiskItem(
                    code="MISSING_PACKET_FIELDS",
                    severity="high",
                    message="Packet is missing src_ip, dst_ip, or ingress_if",
                )
            )
            return self._build_result(state)

        self._transition(state, STATE_DISCOVERING, "state_machine", "Collecting topology and forwarding data")

        interfaces = get_interface_context(
            self._executor,
            iface="",
            namespace=ctx.namespace,
            vrf=ctx.vrf,
        )
        rules = get_rules(self._executor, namespace=ctx.namespace, vrf=ctx.vrf)
        routes = self._collect_candidate_routes(ctx, rules)
        neighbors = get_neighbors(self._executor, namespace=ctx.namespace, vrf=ctx.vrf)
        bridges = get_ovs_bridges(self._executor)
        flows = get_ovs_flows(self._executor)

        ingress = self._find_ingress_interface(interfaces, pkt.ingress_if)
        if not ingress:
            # DPDK ports are purely OVS userspace ports and do not appear in
            # ``ip link`` output.  If the interface is known to OVS (already
            # collected in *bridges*), synthesise a minimal InterfaceContext so
            # the OVS analysis phase can proceed normally.
            _br, _port = self._find_ovs_attachment(bridges, pkt.ingress_if)
            if _br and _port:
                ingress = InterfaceContext(
                    iface=pkt.ingress_if,
                    namespace=ctx.namespace,
                    vrf=ctx.vrf,
                    kind="ether",
                    if_type=_port.port_type or "dpdk",
                    role="bridge-port",
                    state="UP",
                    mac=_port.mac,
                )
                logger.debug(
                    "Ingress interface %s not found in kernel interfaces; "
                    "synthesised from OVS port (bridge=%s, ofport=%s, type=%s)",
                    pkt.ingress_if,
                    _br.name,
                    _port.ofport,
                    _port.port_type,
                )
            else:
                self._transition(
                    state, STATE_FAILED, "inventory",
                    f"Ingress interface {pkt.ingress_if} not found"
                )
                state.risks.append(
                    RiskItem(
                        code="INGRESS_NOT_FOUND",
                        severity="high",
                        message=(
                            f"Ingress interface {pkt.ingress_if} not found in collected data "
                            "(checked both kernel interfaces and OVS bridges)"
                        ),
                    )
                )
                return self._build_result(state)

        ingress_id = self._add_entity_node(
            state,
            kind="interface",
            label=ingress.iface,
            namespace=ingress.namespace,
            vrf=ingress.vrf,
            attrs={"if_type": ingress.if_type, "role": ingress.role},
        )
        self._append_path(
            state,
            obj_type="interface",
            obj_name=ingress.iface,
            reason="Ingress interface",
            namespace=ingress.namespace,
            vrf=ingress.vrf,
            evidence_level="confirmed",
        )

        bridge, port = self._find_ovs_attachment(bridges, pkt.ingress_if)
        if bridge and port:
            self._transition(
                state,
                STATE_ANALYZING_OVS,
                "ovs",
                f"Ingress interface {pkt.ingress_if} enters OVS bridge {bridge.name}",
            )
            self._analyze_ovs(state, ingress_id, bridge, port, bridges, flows, rules, routes, neighbors)
        else:
            state.risks.append(
                RiskItem(
                    code="OVS_ATTACHMENT_NOT_FOUND",
                    severity="medium",
                    message=f"Ingress interface {pkt.ingress_if} is not attached to an OVS bridge; falling back to L3 analysis",
                )
            )
            self._transition(
                state,
                STATE_ANALYZING_L3,
                "fallback",
                f"No OVS attachment found for {pkt.ingress_if}; using L3 path inference",
            )
            self._analyze_l3(state, ingress_id, interfaces, rules, routes, neighbors)

        if state.flow_state not in (STATE_FAILED, STATE_INCOMPLETE):
            self._transition(state, STATE_COMPLETED, "state_machine", "Analysis complete")
        return self._build_result(state)

    @staticmethod
    def _transition(state: AnalysisState, next_state: str, source: str, message: str) -> None:
        state.flow_state = next_state
        state.decision_chain.append(DecisionEvent(state=next_state, source=source, message=message))

    def _append_path(
        self,
        state: AnalysisState,
        *,
        obj_type: str,
        obj_name: str,
        reason: str,
        namespace: str | None = None,
        vrf: str | None = None,
        evidence_level: str = "inferred",
    ) -> None:
        state.path.append(
            PathNode(
                hop_index=state.current_hop,
                namespace=namespace,
                vrf=vrf,
                obj_type=obj_type,
                obj_name=obj_name,
                reason=reason,
                evidence_level=evidence_level,
            )
        )

    def _add_entity_node(
        self,
        state: AnalysisState,
        *,
        kind: str,
        label: str,
        namespace: str | None = None,
        vrf: str | None = None,
        attrs: dict | None = None,
    ) -> str:
        node_id = f"{kind}:{label}:{namespace or 'root'}:{vrf or 'default'}"
        if not any(node.id == node_id for node in state.graph.nodes):
            state.graph.nodes.append(
                GraphNode(
                    id=node_id,
                    kind=kind,
                    label=label,
                    namespace=namespace,
                    vrf=vrf,
                    attrs=attrs or {},
                )
            )
        return node_id

    def _add_graph_edge(
        self,
        state: AnalysisState,
        src: str,
        dst: str,
        relation: str,
        reason: str,
        evidence_level: str = "inferred",
        attrs: dict | None = None,
    ) -> None:
        state.graph.edges.append(
            GraphEdge(
                src=src,
                dst=dst,
                relation=relation,
                reason=reason,
                evidence_level=evidence_level,
                attrs=attrs or {},
            )
        )

    @staticmethod
    def _find_ingress_interface(interfaces: list[InterfaceContext], ingress_if: str) -> InterfaceContext | None:
        for iface in interfaces:
            if iface.iface == ingress_if:
                return iface
        return None

    def _collect_candidate_routes(self, ctx: ExecContext, rules: list[RuleInfo]) -> list[RouteResult]:
        routes = get_route(self._executor, namespace=ctx.namespace, vrf=ctx.vrf)
        seen = {(route.table, route.raw) for route in routes}
        for table in sorted({rule.table for rule in rules if rule.table not in {"local", "main", "default"}}):
            extra = get_route(self._executor, table=table, namespace=ctx.namespace, vrf=ctx.vrf)
            for route in extra:
                key = (route.table, route.raw)
                if key not in seen:
                    routes.append(route)
                    seen.add(key)
        return routes

    @staticmethod
    def _find_ovs_attachment(
        bridges: list[OvsBridge],
        ingress_if: str,
    ) -> tuple[OvsBridge | None, OvsPortInfo | None]:
        for bridge in bridges:
            for port in bridge.ports:
                if port.interface == ingress_if or port.port == ingress_if:
                    return bridge, port
        return None, None

    def _analyze_ovs(
        self,
        state: AnalysisState,
        ingress_node_id: str,
        bridge: OvsBridge,
        port: OvsPortInfo,
        bridges: list[OvsBridge],
        flows: list[OvsFlow],
        rules: list[RuleInfo],
        routes: list[RouteResult],
        neighbors: list[NeighborInfo],
    ) -> None:
        bridge_id = self._add_entity_node(state, kind="ovs_bridge", label=bridge.name)
        ingress_port_id = self._add_entity_node(
            state,
            kind="ovs_port",
            label=f"{bridge.name}:{port.port}",
            attrs={"ofport": port.ofport, "port_type": port.port_type},
        )
        self._add_graph_edge(state, ingress_node_id, ingress_port_id, "ingress_to_port", "Ingress enters OVS port", "confirmed")
        self._add_graph_edge(state, ingress_port_id, bridge_id, "member_of", "Port belongs to bridge", "confirmed")
        self._append_path(
            state,
            obj_type="ovs_bridge",
            obj_name=bridge.name,
            reason=f"OVS bridge attached to {state.packet.ingress_if}",
            evidence_level="confirmed",
        )
        self._append_path(
            state,
            obj_type="ovs_port",
            obj_name=f"{bridge.name}:{port.port}",
            reason=f"OVS ingress port ofport={port.ofport}",
            evidence_level="confirmed",
        )

        bridge_flows = [flow for flow in flows if flow.bridge == bridge.name]
        by_table: dict[int, list[OvsFlow]] = defaultdict(list)
        for flow in bridge_flows:
            by_table[flow.table].append(flow)
        for table_flows in by_table.values():
            table_flows.sort(key=lambda item: item.priority, reverse=True)

        visited_tables: set[tuple[int, str]] = set()
        current_table = 0
        current_node = ingress_port_id
        while True:
            matched = self._select_matching_flow(state.packet, by_table.get(current_table, []), port)
            if not matched:
                state.risks.append(
                    RiskItem(
                        code="OVS_FLOW_MISS",
                        severity="high",
                        message=f"No matching OVS flow found on bridge {bridge.name} table {current_table}",
                    )
                )
                self._transition(
                    state,
                    STATE_INCOMPLETE,
                    "ovs",
                    f"No matching flow in bridge {bridge.name} table {current_table}",
                )
                break

            flow_label = f"{bridge.name}:table{matched.table}:prio{matched.priority}"
            flow_id = self._add_entity_node(
                state,
                kind="ovs_flow",
                label=flow_label,
                attrs={
                    "match": matched.match,
                    "actions": matched.actions,
                    "n_packets": matched.n_packets,
                    "cookie": matched.cookie,
                },
            )
            self._add_graph_edge(state, current_node, flow_id, "matched_flow", "Packet matched OVS flow", "confirmed")
            self._append_path(
                state,
                obj_type="ovs_flow",
                obj_name=flow_label,
                reason=f"match={matched.match or 'all'} actions={matched.actions}",
                evidence_level="confirmed",
            )
            if matched.n_packets == 0:
                state.risks.append(
                    RiskItem(
                        code="OVS_COLD_FLOW",
                        severity="medium",
                        message=f"Matched OVS flow {flow_label} has zero packet hits",
                    )
                )

            action_result = self._follow_flow_actions(
                state,
                flow_id,
                bridge,
                matched,
                bridges,
                visited_tables,
            )

            if action_result["kind"] == "resubmit":
                current_table = action_result["table"]
                current_node = flow_id
                continue

            if action_result["kind"] == "drop":
                state.risks.append(
                    RiskItem(
                        code="OVS_DROP",
                        severity="high",
                        message=f"Matched OVS flow {flow_label} drops the packet",
                    )
                )
                self._transition(state, STATE_INCOMPLETE, "ovs", f"Flow {flow_label} drops traffic")
                break

            if action_result["kind"] == "kernel":
                self._transition(state, STATE_ANALYZING_L3, "ovs", "OVS handed packet to kernel L3 forwarding")
                self._analyze_l3(
                    state,
                    action_result["node_id"],
                    get_interface_context(self._executor, namespace=state.exec_ctx.namespace, vrf=state.exec_ctx.vrf),
                    rules,
                    routes,
                    neighbors,
                )
                break

            if action_result["kind"] == "output":
                out_port: OvsPortInfo = action_result["port"]
                self._append_path(
                    state,
                    obj_type="egress",
                    obj_name=out_port.interface or out_port.port,
                    reason=f"OVS outputs to {out_port.port}",
                    evidence_level="confirmed",
                )
                if out_port.port_type in {"vxlan", "geneve", "gre"} or "tun" in (out_port.interface or out_port.port):
                    state.risks.append(
                        RiskItem(
                            code="TUNNEL_PATH",
                            severity="low",
                            message=f"Traffic exits OVS via tunnel port {out_port.port}",
                        )
                    )
                break

            if action_result["kind"] == "normal":
                state.risks.append(
                    RiskItem(
                        code="OVS_NORMAL_ACTION",
                        severity="medium",
                        message="Encountered OVS NORMAL action; exact datapath learning behavior is not fully modeled",
                    )
                )
                self._transition(state, STATE_INCOMPLETE, "ovs", "OVS NORMAL action requires learned datapath state")
                break

            self._transition(state, STATE_INCOMPLETE, "ovs", "OVS action chain could not be fully resolved")
            break

    def _follow_flow_actions(
        self,
        state: AnalysisState,
        flow_id: str,
        bridge: OvsBridge,
        flow: OvsFlow,
        bridges: list[OvsBridge],
        visited_tables: set[tuple[int, str]],
    ) -> dict:
        for action in flow.action_list or [flow.actions]:
            stripped = action.strip()
            if not stripped:
                continue

            if stripped == "drop":
                return {"kind": "drop"}

            if stripped == "NORMAL":
                return {"kind": "normal"}

            if stripped in {"LOCAL", "output:LOCAL"}:
                kernel_id = self._add_entity_node(state, kind="kernel", label="kernel-l3")
                self._add_graph_edge(state, flow_id, kernel_id, "enter_kernel", "OVS sends traffic to kernel", "confirmed")
                self._append_path(state, obj_type="kernel", obj_name="kernel-l3", reason="OVS action LOCAL", evidence_level="confirmed")
                return {"kind": "kernel", "node_id": kernel_id}

            if stripped.startswith("resubmit("):
                table = self._extract_resubmit_table(stripped)
                if table is not None:
                    marker = (table, flow_id)
                    if marker in visited_tables:
                        state.risks.append(
                            RiskItem(
                                code="OVS_TABLE_LOOP",
                                severity="high",
                                message=f"Detected OVS resubmit loop to table {table}",
                            )
                        )
                        return {"kind": "loop"}
                    visited_tables.add(marker)
                    return {"kind": "resubmit", "table": table}

            if stripped.startswith("goto_table:"):
                try:
                    return {"kind": "resubmit", "table": int(stripped.split(":", 1)[1])}
                except ValueError:
                    continue

            if stripped.startswith("output:"):
                target = stripped.split(":", 1)[1]
                out_port = self._resolve_output_port(bridge, target)
                if out_port:
                    port_id = self._add_entity_node(
                        state,
                        kind="ovs_port",
                        label=f"{bridge.name}:{out_port.port}",
                        attrs={"ofport": out_port.ofport, "port_type": out_port.port_type},
                    )
                    self._add_graph_edge(state, flow_id, port_id, "output_to_port", f"OVS action {stripped}", "confirmed")
                    if self._port_enters_kernel(bridge, out_port):
                        kernel_id = self._add_entity_node(state, kind="kernel", label="kernel-l3")
                        self._add_graph_edge(state, port_id, kernel_id, "enter_kernel", "Output reaches kernel forwarding", "inferred")
                        self._append_path(
                            state,
                            obj_type="ovs_port",
                            obj_name=f"{bridge.name}:{out_port.port}",
                            reason=f"OVS output {stripped}",
                            evidence_level="confirmed",
                        )
                        return {"kind": "kernel", "node_id": kernel_id}
                    return {"kind": "output", "port": out_port}
                state.risks.append(
                    RiskItem(
                        code="OVS_UNKNOWN_OUTPUT",
                        severity="medium",
                        message=f"OVS action outputs to unknown port target {target}",
                    )
                )

        return {"kind": "unknown"}

    @staticmethod
    def _extract_resubmit_table(action: str) -> int | None:
        match = re.search(r"resubmit\([^,]*,\s*(\d+)\)", action)
        if match:
            return int(match.group(1))
        return None

    @staticmethod
    def _resolve_output_port(bridge: OvsBridge, target: str) -> OvsPortInfo | None:
        for port in bridge.ports:
            if str(port.ofport) == target or port.port == target or port.interface == target:
                return port
        if target == "LOCAL":
            for port in bridge.ports:
                if port.port == bridge.name or port.interface == bridge.name:
                    return port
        return None

    @staticmethod
    def _port_enters_kernel(bridge: OvsBridge, port: OvsPortInfo) -> bool:
        if port.port == bridge.name or port.interface == bridge.name:
            return True
        return port.port_type == "internal"

    def _select_matching_flow(
        self,
        packet: PacketContext,
        flows: list[OvsFlow],
        ingress_port: OvsPortInfo,
    ) -> OvsFlow | None:
        for flow in flows:
            if self._flow_matches_packet(flow, packet, ingress_port):
                return flow
        return None

    def _flow_matches_packet(self, flow: OvsFlow, packet: PacketContext, ingress_port: OvsPortInfo) -> bool:
        fields = flow.match_fields
        if not fields:
            return True

        for key, value in fields.items():
            if key == "in_port":
                allowed = {
                    str(ingress_port.ofport) if ingress_port.ofport is not None else "",
                    ingress_port.port,
                    ingress_port.interface or "",
                    "LOCAL" if (ingress_port.port == ingress_port.bridge) else "",
                }
                if value not in allowed:
                    return False
            elif key in {"ip", "ipv6"}:
                expected = "ipv6" if packet.ip_version == 6 else "ip"
                if key != expected:
                    return False
            elif key == "arp":
                if (packet.protocol or "").lower() != "arp":
                    return False
            elif key in {"tcp", "udp", "icmp"}:
                if (packet.protocol or "").lower() != key:
                    return False
            elif key in {"nw_src", "ipv6_src"}:
                if not self._ip_matches(packet.src_ip, value):
                    return False
            elif key in {"nw_dst", "ipv6_dst"}:
                if not self._ip_matches(packet.dst_ip, value):
                    return False
            elif key in {"tp_src", "tcp_src", "udp_src"}:
                if packet.src_port is None or str(packet.src_port) != value:
                    return False
            elif key in {"tp_dst", "tcp_dst", "udp_dst"}:
                if packet.dst_port is None or str(packet.dst_port) != value:
                    return False
            elif key in {"dl_vlan", "vlan_vid"}:
                if packet.vlan_id is None or not self._vlan_matches(packet.vlan_id, value):
                    return False
            elif key == "tun_id":
                if packet.tunnel_id is None or str(packet.tunnel_id) != value:
                    return False
            elif key == "ct_state":
                continue
        return True

    @staticmethod
    def _ip_matches(ip: str, selector: str) -> bool:
        if selector in {"0.0.0.0/0", "::/0"}:
            return True
        try:
            if "/" in selector:
                return ipaddress.ip_address(ip) in ipaddress.ip_network(selector, strict=False)
            return ip == selector
        except ValueError:
            return False

    @staticmethod
    def _vlan_matches(vlan_id: int, raw_value: str) -> bool:
        try:
            if raw_value.startswith("0x"):
                return int(raw_value, 16) & 0x0FFF == vlan_id
            return int(raw_value) == vlan_id
        except ValueError:
            return False

    def _analyze_l3(
        self,
        state: AnalysisState,
        from_node_id: str,
        interfaces: list[InterfaceContext],
        rules: list[RuleInfo],
        routes: list[RouteResult],
        neighbors: list[NeighborInfo],
    ) -> None:
        matched_rules = self._match_rules(rules, state.packet)
        best_route = None
        selected_rule: RuleInfo | None = None

        if matched_rules:
            # Walk matched rules in priority order, trying each rule's table
            # until we find a route (matching kernel fallthrough semantics)
            for rule in matched_rules:
                rule_scope = [route for route in routes if route.table == rule.table]
                best_route = find_best_route(rule_scope, state.packet.dst_ip)
                rule_id = self._add_entity_node(
                    state,
                    kind="rule",
                    label=f"rule:{rule.priority}->{rule.table}",
                    namespace=rule.namespace,
                    vrf=rule.vrf,
                    attrs={"raw": rule.raw},
                )
                relation = "selected_rule" if best_route else "rule_fallthrough"
                evidence = "confirmed" if best_route else "inferred"
                reason = f"rule walk: table={rule.table}"
                if best_route:
                    reason += " → route_found"
                else:
                    reason += " → no_route, fallthrough"
                self._add_graph_edge(state, from_node_id, rule_id, relation, reason, evidence)
                self._append_path(
                    state,
                    obj_type="rule",
                    obj_name=f"priority={rule.priority} table={rule.table}",
                    reason=reason,
                    namespace=rule.namespace,
                    vrf=rule.vrf,
                    evidence_level=evidence,
                )
                if best_route:
                    selected_rule = rule
                    break

        if not best_route:
            # No matched rule found a route; try all routes as last resort
            if not matched_rules:
                state.risks.append(
                    RiskItem(
                        code="RULE_FALLBACK",
                        severity="medium",
                        message="No precise IP rule match found; falling back to available routes",
                    )
                )
            best_route = find_best_route(routes, state.packet.dst_ip)

        if not best_route:
            state.risks.append(
                RiskItem(
                    code="ROUTE_NOT_FOUND",
                    severity="high",
                    message=f"No route matched destination {state.packet.dst_ip}",
                )
            )
            self._transition(state, STATE_INCOMPLETE, "l3", f"No route found for {state.packet.dst_ip}")
            return

        route_label = f"{best_route.prefix} via {(best_route.next_hops[0].via if best_route.next_hops else '(direct)')} dev {(best_route.next_hops[0].dev if best_route.next_hops else '(unknown)')}"
        route_id = self._add_entity_node(
            state,
            kind="route",
            label=route_label,
            namespace=best_route.namespace,
            vrf=best_route.vrf,
            attrs={"table": best_route.table, "raw": best_route.raw},
        )
        self._add_graph_edge(state, from_node_id, route_id, "selected_route", "Packet matched route", "confirmed")
        self._append_path(
            state,
            obj_type="route",
            obj_name=route_label,
            reason=f"Route table={best_route.table}",
            namespace=best_route.namespace,
            vrf=best_route.vrf,
            evidence_level="confirmed",
        )

        next_hop = best_route.next_hops[0] if best_route.next_hops else None
        if next_hop and next_hop.dev:
            egress_iface = next((iface for iface in interfaces if iface.iface == next_hop.dev), None)
            egress_label = next_hop.dev
            egress_id = self._add_entity_node(
                state,
                kind="interface",
                label=egress_label,
                attrs={"if_type": egress_iface.if_type if egress_iface else "unknown"},
            )
            self._add_graph_edge(state, route_id, egress_id, "route_to_egress", "Route uses egress interface", "confirmed")
            self._append_path(
                state,
                obj_type="egress",
                obj_name=egress_label,
                reason="Kernel L3 selected egress device",
                evidence_level="confirmed",
            )

            # Cross-namespace veth tracking:
            # If egress is a veth with link_netnsid, follow it to the peer
            # namespace and continue L3 (or OVS) analysis there.
            if egress_iface and egress_iface.if_type == "veth" and egress_iface.link_netnsid is not None:
                target_ns = "" if egress_iface.link_netnsid == 0 else None
                if target_ns is not None:
                    peer_interfaces = get_interface_context(
                        self._executor,
                        namespace=target_ns,
                    )
                    # Find the peer veth — look for a veth in the target
                    # namespace that has the same MAC or pairs by naming convention.
                    peer_iface: InterfaceContext | None = None
                    base_name = egress_iface.iface.rstrip("-r")
                    for iface in peer_interfaces:
                        if iface.if_type == "veth" and iface.mac == egress_iface.mac:
                            peer_iface = iface
                            break
                    if not peer_iface:
                        # Fallback: try naming convention X-r → X-k
                        for iface in peer_interfaces:
                            if iface.if_type == "veth" and iface.iface in {
                                base_name + "-k",
                                base_name + "-peer",
                                egress_iface.iface + "-peer",
                            }:
                                peer_iface = iface
                                break

                    if peer_iface:
                        peer_id = self._add_entity_node(
                            state,
                            kind="interface",
                            label=peer_iface.iface,
                            namespace=peer_iface.namespace,
                            attrs={"if_type": peer_iface.if_type, "role": peer_iface.role, "link_netnsid": peer_iface.link_netnsid},
                        )
                        self._add_graph_edge(
                            state,
                            egress_id,
                            peer_id,
                            "veth_cross_ns",
                            f"veth pair crosses from {egress_iface.namespace or 'root'} to {peer_iface.namespace or 'root'}",
                            "inferred",
                        )
                        self._append_path(
                            state,
                            obj_type="interface",
                            obj_name=peer_iface.iface,
                            reason=f"veth peer in {peer_iface.namespace or 'root'} namespace",
                            namespace=peer_iface.namespace,
                            evidence_level="inferred",
                        )

                        # Check routing in the target namespace
                        peer_routes = get_route(
                            self._executor,
                            namespace=target_ns,
                        )
                        peer_best = find_best_route(peer_routes, state.packet.dst_ip)
                        if peer_best:
                            peer_route_label = f"{peer_best.prefix} via {(peer_best.next_hops[0].via if peer_best.next_hops else '(direct)')} dev {(peer_best.next_hops[0].dev if peer_best.next_hops else '(unknown)')}"
                            peer_route_id = self._add_entity_node(
                                state,
                                kind="route",
                                label=peer_route_label,
                                namespace=peer_best.namespace,
                                attrs={"table": peer_best.table},
                            )
                            self._add_graph_edge(
                                state,
                                peer_id,
                                peer_route_id,
                                "peer_route",
                                f"Route in {peer_iface.namespace or 'root'} namespace",
                                "confirmed",
                            )
                            self._append_path(
                                state,
                                obj_type="route",
                                obj_name=peer_route_label,
                                reason=f"Route in {peer_iface.namespace or 'root'} namespace",
                                namespace=peer_best.namespace,
                                evidence_level="confirmed",
                            )

                            # If the peer route uses an OVS bridge, analyze OVS
                            peer_dev = peer_best.next_hops[0].dev if peer_best.next_hops else None
                            if peer_dev:
                                peer_bridge, peer_port = self._find_ovs_attachment(bridges, peer_dev)
                                if not peer_bridge:
                                    # Also try matching by bridge name
                                    for br in bridges:
                                        if br.name == peer_dev:
                                            peer_bridge = br
                                            break
                                if peer_bridge:
                                    # Traffic enters OVS bridge from kernel LOCAL port
                                    local_port = next(
                                        (p for p in peer_bridge.ports if p.port == peer_bridge.name),
                                        None,
                                    )
                                    if local_port:
                                        self._transition(
                                            state,
                                            STATE_ANALYZING_OVS,
                                            "cross-ns",
                                            f"Route in {peer_iface.namespace or 'root'} ns points to OVS bridge {peer_bridge.name}",
                                        )
                                        peer_flows = [f for f in flows if f.bridge == peer_bridge.name]
                                        self._analyze_ovs(
                                            state,
                                            peer_route_id,
                                            peer_bridge,
                                            local_port,
                                            bridges,
                                            peer_flows,
                                            rules,
                                            routes,
                                            neighbors,
                                        )
                                        return

                            # No OVS: just note the egress
                            peer_egress_iface = next(
                                (iface for iface in peer_interfaces if iface.iface == peer_dev),
                                None,
                            )
                            if peer_egress_iface:
                                peer_egress_id = self._add_entity_node(
                                    state,
                                    kind="interface",
                                    label=peer_egress_iface.iface,
                                    namespace=peer_egress_iface.namespace,
                                    attrs={"if_type": peer_egress_iface.if_type},
                                )
                                self._add_graph_edge(
                                    state,
                                    peer_route_id,
                                    peer_egress_id,
                                    "peer_egress",
                                    "Route in peer namespace selects egress",
                                    "confirmed",
                                )
                                self._append_path(
                                    state,
                                    obj_type="egress",
                                    obj_name=peer_egress_iface.iface,
                                    reason=f"Kernel L3 egress in {peer_egress_iface.namespace or 'root'} namespace",
                                    namespace=peer_egress_iface.namespace,
                                    evidence_level="confirmed",
                                )
                                # Check peer-side neighbor
                                if peer_best.next_hops[0].via:
                                    peer_neighbors = get_neighbors(
                                        self._executor,
                                        device=peer_dev,
                                        target_ip=peer_best.next_hops[0].via,
                                        namespace=target_ns,
                                    )
                                    for pn in peer_neighbors:
                                        if pn.ip == peer_best.next_hops[0].via:
                                            pn_id = self._add_entity_node(
                                                state,
                                                kind="neighbor",
                                                label=f"{pn.ip}@{pn.dev}",
                                                namespace=pn.namespace,
                                                attrs={"state": pn.state, "mac": pn.mac},
                                            )
                                            self._add_graph_edge(state, peer_egress_id, pn_id, "next_hop", "Resolved next-hop neighbor in peer namespace", "confirmed")
                                            self._append_path(
                                                state,
                                                obj_type="neighbor",
                                                obj_name=f"{pn.ip} dev {pn.dev}",
                                                reason=f"Neighbor state={pn.state}",
                                                namespace=pn.namespace,
                                                evidence_level="confirmed",
                                            )
                                            if not pn.reachable:
                                                state.risks.append(
                                                    RiskItem(
                                                        code="NEIGH_UNREACHABLE",
                                                        severity="high",
                                                        message=f"Next-hop neighbor {pn.ip} on {pn.dev} in {pn.namespace or 'root'} is {pn.state}",
                                                    )
                                                )
                            return

            if next_hop.via:
                neighbor = next(
                    (item for item in neighbors if item.dev == next_hop.dev and item.ip == next_hop.via),
                    None,
                )
                if neighbor:
                    neighbor_id = self._add_entity_node(
                        state,
                        kind="neighbor",
                        label=f"{neighbor.ip}@{neighbor.dev}",
                        namespace=neighbor.namespace,
                        vrf=neighbor.vrf,
                        attrs={"state": neighbor.state, "mac": neighbor.mac},
                    )
                    self._add_graph_edge(state, egress_id, neighbor_id, "next_hop", "Resolved next-hop neighbor", "confirmed")
                    self._append_path(
                        state,
                        obj_type="neighbor",
                        obj_name=f"{neighbor.ip} dev {neighbor.dev}",
                        reason=f"Neighbor state={neighbor.state}",
                        namespace=neighbor.namespace,
                        vrf=neighbor.vrf,
                        evidence_level="confirmed",
                    )
                    if not neighbor.reachable:
                        state.risks.append(
                            RiskItem(
                                code="NEIGH_UNREACHABLE",
                                severity="high",
                                message=f"Next-hop neighbor {neighbor.ip} on {neighbor.dev} is {neighbor.state}",
                            )
                        )
                else:
                    state.risks.append(
                        RiskItem(
                            code="NEIGHBOR_MISSING",
                            severity="medium",
                            message=f"Next-hop neighbor {next_hop.via} on {next_hop.dev} not found",
                        )
                    )

        if selected_rule and selected_rule.table != best_route.table:
            state.risks.append(
                RiskItem(
                    code="RULE_ROUTE_TABLE_MISMATCH",
                    severity="medium",
                    message=f"Selected rule points to table {selected_rule.table} but chosen route is in table {best_route.table}",
                )
            )

    @staticmethod
    def _match_rules(rules: list[RuleInfo], packet: PacketContext) -> list[RuleInfo]:
        matches: list[RuleInfo] = []
        for rule in sorted(rules, key=lambda item: item.priority):
            raw = rule.raw
            if not Analyzer._rule_matches_prefix(raw, "from", packet.src_ip):
                continue
            if not Analyzer._rule_matches_prefix(raw, "to", packet.dst_ip):
                continue
            if not Analyzer._rule_matches_exact(raw, "iif", packet.ingress_if or ""):
                continue
            if not Analyzer._rule_matches_exact(raw, "fwmark", packet.fwmark or ""):
                continue
            matches.append(rule)
        return matches

    @staticmethod
    def _rule_matches_prefix(raw: str, keyword: str, ip: str) -> bool:
        match = re.search(rf"\b{keyword}\s+(\S+)", raw)
        if not match:
            return True
        selector = match.group(1)
        if selector == "all":
            return True
        try:
            if "/" in selector:
                return ipaddress.ip_address(ip) in ipaddress.ip_network(selector, strict=False)
            return ip == selector
        except ValueError:
            return False

    @staticmethod
    def _rule_matches_exact(raw: str, keyword: str, value: str) -> bool:
        match = re.search(rf"\b{keyword}\s+(\S+)", raw)
        if not match:
            return True
        if not value:
            return False
        return match.group(1) == value

    def _build_result(self, state: AnalysisState) -> AnalysisResult:
        graph = state.graph if state.graph.nodes or state.graph.edges else FlowGraph()
        summary = self._build_summary(state)
        mermaid = self._build_mermaid(graph)
        return AnalysisResult(
            status=state.flow_state,
            path=state.path,
            decision_chain=state.decision_chain,
            risks=state.risks,
            confidence=max(0.1, 1.0 - min(0.8, 0.1 * len(state.risks))),
            confidence_reasons=[risk.code for risk in state.risks] or ["Path inferred from OVS and L3 data"],
            summary=summary,
            graph=graph,
            mermaid=mermaid,
        )

    @staticmethod
    def _build_summary(state: AnalysisState) -> str:
        if not state.path:
            return "No path could be inferred."
        important = [node.obj_name for node in state.path if node.obj_type in {"interface", "ovs_bridge", "ovs_flow", "egress", "neighbor"}]
        summary = " -> ".join(important[:8])
        if state.risks:
            summary += f" | risks={', '.join(risk.code for risk in state.risks[:3])}"
        return summary

    @staticmethod
    def _build_mermaid(graph: FlowGraph) -> str:
        lines = ["flowchart LR"]
        for node in graph.nodes:
            safe_id = re.sub(r"[^A-Za-z0-9_]", "_", node.id)
            label = node.label.replace('"', "'")
            lines.append(f'    {safe_id}["{label}"]')
        for edge in graph.edges:
            src = re.sub(r"[^A-Za-z0-9_]", "_", edge.src)
            dst = re.sub(r"[^A-Za-z0-9_]", "_", edge.dst)
            rel = edge.relation.replace('"', "'")
            lines.append(f"    {src} -->|{rel}| {dst}")
        return "\n".join(lines)
