"""Flow-path analyzer — state machine orchestrating multi-hop collection."""

from __future__ import annotations

import logging
import uuid

from fpe.collectors import (
    check_neighbor,
    get_interface_context,
    get_ip_rules,
    get_ovs_bridges,
    get_route,
    resolve_next_hop,
)
from fpe.command.executor import RemoteExecutor
from fpe.models import (
    AnalysisResult,
    AnalysisState,
    DecisionEvent,
    PacketContext,
    PathNode,
    RiskItem,
)

logger = logging.getLogger(__name__)

# ── State constants ───────────────────────────────────────────────────

STATE_INIT = "INIT"
STATE_NORMALIZING_INPUT = "NORMALIZING_INPUT"
STATE_RESOLVING_CONTEXT = "RESOLVING_CONTEXT"
STATE_COLLECTING = "COLLECTING"
STATE_BUILDING_PATH = "BUILDING_PATH"
STATE_COMPLETED = "COMPLETED"
STATE_INCOMPLETE = "INCOMPLETE"
STATE_FAILED = "FAILED"


def _generate_trace_id() -> str:
    return uuid.uuid4().hex[:12]


class Analyzer:
    """Flow-path analyzer with state-machine orchestration.

    Call ``analyze()`` to run a complete analysis.  The state machine
    progresses through INIT → NORMALIZING_INPUT → RESOLVING_CONTEXT →
    COLLECTING → BUILDING_PATH (→ COLLECTING …) → COMPLETED / INCOMPLETE
    / FAILED.
    """

    def __init__(self, executor: RemoteExecutor | None = None) -> None:
        self._executor = executor or RemoteExecutor()

    async def analyze(
        self,
        packet: PacketContext | None = None,
        options: dict | None = None,
    ) -> AnalysisResult:
        """Run the full analysis state machine to completion."""
        from fpe.command.executor import _env_exec_ctx

        opts = options or {}

        state = AnalysisState(
            trace_id=_generate_trace_id(),
            flow_state=STATE_INIT,
            packet=packet or PacketContext(src_ip="", dst_ip=""),
            exec_ctx=_env_exec_ctx(),
            max_hops=opts.get("max_hops", 16),
        )

        state = self._transition(state, STATE_INIT, "state_machine", "Analysis started")

        # ── NORMALIZING_INPUT ────────────────────────────────────────
        state = self._transition(state, STATE_NORMALIZING_INPUT, "state_machine", "Normalizing input")

        if not state.packet.src_ip or not state.packet.dst_ip:
            state = self._transition(state, STATE_FAILED, "validation", "Missing src_ip or dst_ip")
            return self._build_result(state)

        if not state.packet.dst_ip.strip():
            state = self._transition(state, STATE_FAILED, "validation", "dst_ip is empty")
            return self._build_result(state)

        # ── RESOLVING_CONTEXT ────────────────────────────────────────
        state = self._transition(state, STATE_RESOLVING_CONTEXT, "state_machine", "Resolving execution context")

        ingress_if = state.packet.ingress_if or state.exec_ctx.ingress_if
        if ingress_if:
            ifaces = get_interface_context(self._executor, ingress_if)
            if ifaces:
                iface = ifaces[0]
                state.path.append(
                    PathNode(
                        hop_index=state.current_hop,
                        namespace=iface.namespace,
                        vrf=iface.vrf,
                        obj_type="interface",
                        obj_name=iface.iface,
                        reason="Ingress interface",
                        evidence_level="confirmed",
                    )
                )

        if state.exec_ctx.namespace:
            state.decision_chain.append(
                DecisionEvent(
                    state=state.flow_state,
                    source="context",
                    message=f"Running in namespace {state.exec_ctx.namespace}",
                    evidence_level="confirmed",
                )
            )

        if state.exec_ctx.vrf:
            state.decision_chain.append(
                DecisionEvent(
                    state=state.flow_state,
                    source="context",
                    message=f"Running in VRF {state.exec_ctx.vrf}",
                    evidence_level="confirmed",
                )
            )

        # ── Main collect / build loop ────────────────────────────────
        while state.flow_state not in (STATE_COMPLETED, STATE_INCOMPLETE, STATE_FAILED):
            if state.current_hop >= state.max_hops:
                state = self._transition(
                    state, STATE_INCOMPLETE, "state_machine",
                    f"Max hops ({state.max_hops}) reached",
                )
                break

            # COLLECTING
            state = self._transition(
                state, STATE_COLLECTING, "state_machine",
                f"Collecting info at hop {state.current_hop}",
            )
            state = self._collect_hop(state)

            # BUILDING_PATH
            state = self._transition(
                state, STATE_BUILDING_PATH, "state_machine",
                "Building path to next hop",
            )
            state = self._build_next_hop(state)

        return self._build_result(state)

    # ── Internal helpers ──────────────────────────────────────────────

    @staticmethod
    def _transition(state: AnalysisState, next_state: str, source: str, message: str) -> AnalysisState:
        state.flow_state = next_state
        state.decision_chain.append(
            DecisionEvent(state=next_state, source=source, message=message),
        )
        return state

    def _collect_hop(self, state: AnalysisState) -> AnalysisState:
        """Collect all relevant data for the current hop."""

        # IP rules
        try:
            rules = get_ip_rules(self._executor)
            for rule in rules:
                state.path.append(
                    PathNode(
                        hop_index=state.current_hop,
                        namespace=state.exec_ctx.namespace,
                        vrf=state.exec_ctx.vrf,
                        obj_type="rule",
                        obj_name=f"priority={rule.priority}",
                        reason=f"IP rule table={rule.table}",
                    )
                )
        except Exception as e:
            logger.warning("Failed to collect IP rules at hop %d: %s", state.current_hop, e)
            state.risks.append(
                RiskItem(code="RULE_COLLECT_FAILED", severity="low", message=str(e))
            )

        # Route
        try:
            routes = get_route(self._executor)
            for route in routes:
                if route.next_hops:
                    nh = route.next_hops[0]
                    via = nh.via or "(direct)"
                    dev = nh.dev or "(unknown)"
                    state.path.append(
                        PathNode(
                            hop_index=state.current_hop,
                            namespace=state.exec_ctx.namespace,
                            vrf=state.exec_ctx.vrf,
                            obj_type="route",
                            obj_name=f"{route.prefix} via {via} dev {dev}",
                            reason=f"Route table={route.table} metric={route.metric}",
                        )
                    )
        except Exception as e:
            logger.warning("Failed to collect routes at hop %d: %s", state.current_hop, e)
            state.risks.append(
                RiskItem(code="ROUTE_COLLECT_FAILED", severity="low", message=str(e))
            )

        # OVS
        try:
            bridges = get_ovs_bridges(self._executor)
            for br in bridges:
                state.path.append(
                    PathNode(
                        hop_index=state.current_hop,
                        obj_type="ovs_bridge",
                        obj_name=br.name,
                        reason=f"OVS bridge dpid={br.datapath_id}" if br.datapath_id else "OVS bridge",
                    )
                )
                for port in br.ports:
                    state.path.append(
                        PathNode(
                            hop_index=state.current_hop,
                            obj_type="ovs_port",
                            obj_name=f"{br.name}:{port.port}",
                            reason=f"OVS port type={port.port_type} ofport={port.ofport}",
                        )
                    )
        except Exception as e:
            logger.warning("Failed to collect OVS info at hop %d: %s", state.current_hop, e)
            state.risks.append(
                RiskItem(code="OVS_COLLECT_FAILED", severity="low", message=str(e))
            )

        # Neighbor
        try:
            neighbors = check_neighbor(self._executor)
            for neighbor in neighbors:
                state.path.append(
                    PathNode(
                        hop_index=state.current_hop,
                        obj_type="neighbor",
                        obj_name=f"{neighbor.ip} dev {neighbor.dev}",
                        reason=f"Neighbor state={neighbor.state}",
                    )
                )
        except Exception as e:
            logger.warning("Failed to collect neighbors at hop %d: %s", state.current_hop, e)
            state.risks.append(
                RiskItem(code="NEIGHBOR_COLLECT_FAILED", severity="low", message=str(e))
            )

        return state

    def _build_next_hop(self, state: AnalysisState) -> AnalysisState:
        """Determine the next hop and advance."""

        # Try to find the egress interface from the last route entry
        egress_dev = None
        for node in reversed(state.path):
            if node.obj_type == "route" and node.hop_index == state.current_hop:
                route = node.obj_name
                # Extract dev from route string like "10.0.0.0/8 via 10.0.1.1 dev eth0"
                import re
                m = re.search(r"dev\s+(\S+)", route)
                if m:
                    egress_dev = m.group(1)
                break

        if egress_dev:
            state.path.append(
                PathNode(
                    hop_index=state.current_hop,
                    obj_type="hop",
                    obj_name=f"egress={egress_dev}",
                    reason="Egress interface from route",
                    evidence_level="confirmed",
                )
            )

            # Resolve next hop via link
            try:
                resolution = resolve_next_hop(self._executor, egress_dev)
                if resolution:
                    state.path.append(
                        PathNode(
                            hop_index=state.current_hop,
                            obj_type="link",
                            obj_name=f"{egress_dev} type={resolution.dev_type}",
                            reason=f"Link resolution: {resolution.dev_type}",
                            evidence_level="confirmed",
                        )
                    )

                    if resolution.dev_type in ("veth",) and resolution.peer_if:
                        # Move to next hop
                        state = self._advance_hop(state, resolution.peer_if, resolution)
                    elif resolution.dev_type in ("bridge", "openvswitch"):
                        # Stay on same hop, bridge/switch
                        state = self._advance_hop(state, egress_dev, resolution)
                    else:
                        # Physical — end of path
                        state = self._transition(
                            state, STATE_COMPLETED, "topology",
                            f"Physical link {egress_dev} — end of traced path",
                        )
                else:
                    state = self._transition(
                        state, STATE_COMPLETED, "topology",
                        f"No further link resolution for {egress_dev}",
                    )
            except Exception as e:
                logger.warning("Failed to resolve next hop: %s", e)
                state = self._transition(
                    state, STATE_INCOMPLETE, "error",
                    f"Next-hop resolution failed: {e}",
                )
        else:
            state = self._transition(
                state, STATE_COMPLETED, "topology",
                "No egress interface found — path complete",
            )

        return state

    def _advance_hop(
        self,
        state: AnalysisState,
        peer_if: str,
        resolution: object,
    ) -> AnalysisState:
        """Advance to the next hop and log the transition."""
        # Track visited to detect loops
        visited_key = f"{state.exec_ctx.namespace}/{peer_if}"
        if visited_key in state.visited:
            state.risks.append(
                RiskItem(
                    code="LOOP_DETECTED",
                    severity="high",
                    message=f"Loop detected at {visited_key}",
                )
            )
            return self._transition(
                state, STATE_INCOMPLETE, "loop_detection",
                f"Loop detected at {visited_key}",
            )

        state.visited.append(visited_key)
        state.current_hop += 1

        return self._transition(
            state, STATE_RESOLVING_CONTEXT, "next_hop",
            f"Advancing to hop {state.current_hop} via {peer_if}",
        )

    @staticmethod
    def _build_result(state: AnalysisState) -> AnalysisResult:
        """Build the final AnalysisResult from the completed state."""
        return AnalysisResult(
            status=state.flow_state,
            path=state.path,
            decision_chain=state.decision_chain,
            risks=state.risks,
            confidence=state.confidence,
            confidence_reasons=state.confidence_reasons,
            summary=_build_summary(state),
        )


def _build_summary(state: AnalysisState) -> str:
    """Generate a human-readable summary of the analysis."""
    parts = [
        f"Analyzed flow from {state.packet.src_ip} to {state.packet.dst_ip}",
        f"Status: {state.flow_state}",
    ]
    if state.path:
        parts.append(f"Path contains {len(state.path)} nodes across {state.current_hop + 1} hop(s)")
    if state.risks:
        parts.append(f"Detected {len(state.risks)} risk(s)")
    return ". ".join(parts)
