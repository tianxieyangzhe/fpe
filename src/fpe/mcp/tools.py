"""MCP tool handler definitions and registry.

Every tool handler follows the ``ToolHandler`` protocol and returns
a ``ToolResult`` envelope.
"""

from __future__ import annotations

from typing import Any, Protocol

from fpe.analyzer import Analyzer
from fpe.collectors import (
    get_interface_context,
    get_neighbors,
    get_ovs_bridges,
    get_ovs_flows,
    get_ovs_info,
    get_route,
    get_rules,
    resolve_next_hop,
)
from fpe.command.executor import RemoteExecutor
from fpe.models import (
    FpeError,
    PacketContext,
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
                        "ip_version": {"type": "integer", "description": "IP version (4 or 6)", "default": 4},
                    },
                    "required": ["src_ip", "dst_ip"],
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
            options = payload.get("options", {})

            analyzer = Analyzer()
            result = await analyzer.analyze(
                packet=packet,
                options=options,
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
            },
            "required": [],
        }

    async def handle(self, payload: dict[str, Any]) -> ToolResult:
        try:
            iface = payload.get("iface", "")
            namespace = payload.get("namespace")
            vrf = payload.get("vrf")

            executor = RemoteExecutor()
            results = get_interface_context(executor, iface=iface, namespace=namespace, vrf=vrf)

            return ToolResult(
                ok=True,
                tool=self.name,
                data={"interfaces": [r.model_dump() for r in results]},
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
            },
            "required": [],
        }

    async def handle(self, payload: dict[str, Any]) -> ToolResult:
        try:
            namespace = payload.get("namespace")
            vrf = payload.get("vrf")
            priority = payload.get("priority")
            table = payload.get("table")

            executor = RemoteExecutor()
            results = get_rules(executor, namespace=namespace, vrf=vrf)

            # Apply client-side filters
            if priority is not None:
                results = [r for r in results if r.priority == priority]
            if table:
                results = [r for r in results if r.table == table]

            return ToolResult(
                ok=True,
                tool=self.name,
                data={"rules": [r.model_dump() for r in results]},
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
            },
            "required": [],
        }

    async def handle(self, payload: dict[str, Any]) -> ToolResult:
        try:
            namespace = payload.get("namespace")
            vrf = payload.get("vrf")
            table = payload.get("table", "")
            dst_ip = payload.get("dst_ip")

            executor = RemoteExecutor()
            routes = get_route(executor, table=table, namespace=namespace, vrf=vrf)

            if dst_ip:
                from fpe.collectors import find_best_route
                best = find_best_route(routes, dst_ip)
                return ToolResult(
                    ok=True,
                    tool=self.name,
                    data={
                        "routes": [r.model_dump() for r in routes],
                        "best_route": best.model_dump() if best else None,
                        "dst_ip": dst_ip,
                    },
                )

            return ToolResult(
                ok=True,
                tool=self.name,
                data={"routes": [r.model_dump() for r in routes]},
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
            },
            "required": [],
        }

    async def handle(self, payload: dict[str, Any]) -> ToolResult:
        try:
            namespace = payload.get("namespace")
            vrf = payload.get("vrf")
            device = payload.get("device", "")
            target_ip = payload.get("target_ip")

            executor = RemoteExecutor()
            results = get_neighbors(
                executor,
                device=device,
                target_ip=target_ip,
                namespace=namespace,
                vrf=vrf,
            )

            return ToolResult(
                ok=True,
                tool=self.name,
                data={"neighbors": [n.model_dump() for n in results]},
            )
        except Exception as e:
            return ToolResult(ok=False, tool=self.name, error=str(e))


class ResolveNextHopHandler:
    """Handler for ``fpe.resolve_next_hop``."""

    name = "fpe.resolve_next_hop"
    description = "Resolve next hop for a given device/interface"

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "device": {"type": "string", "description": "Device or interface name to resolve"},
            },
            "required": ["device"],
        }

    async def handle(self, payload: dict[str, Any]) -> ToolResult:
        try:
            device = payload.get("device", "")

            if not device:
                return ToolResult(
                    ok=False, tool=self.name,
                    error="Missing required field: device",
                )

            executor = RemoteExecutor()
            resolution = resolve_next_hop(executor, device)

            return ToolResult(
                ok=True,
                tool=self.name,
                data=resolution.model_dump() if resolution else {"device": device, "found": False},
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
            "properties": {},
            "required": [],
        }

    async def handle(self, payload: dict[str, Any]) -> ToolResult:
        try:
            executor = RemoteExecutor()
            bridges = get_ovs_bridges(executor)

            return ToolResult(
                ok=True,
                tool=self.name,
                data={"bridges": [b.model_dump() for b in bridges]},
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
            },
            "required": [],
        }

    async def handle(self, payload: dict[str, Any]) -> ToolResult:
        try:
            bridge = payload.get("bridge")
            table = payload.get("table")

            executor = RemoteExecutor()
            flows = get_ovs_flows(executor, bridge=bridge, table=table)

            return ToolResult(
                ok=True,
                tool=self.name,
                data={"flows": [f.model_dump() for f in flows]},
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
        ResolveNextHopHandler(),
        GetOvsBridgesHandler(),
        GetOvsFlowsHandler(),
    ]
