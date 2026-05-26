"""Interface information collection — ``ip -d link show`` and ``ip addr``."""

from __future__ import annotations

import re
import logging

from fpe.command.executor import RemoteExecutor, _env_exec_ctx, list_network_namespaces, list_network_vrfs
from fpe.models import ExecContext, InterfaceContext

logger = logging.getLogger(__name__)

# Regex matching ``N: ifname:`` — the start of each interface block.
_RE_IFACE_HEAD = re.compile(r"^(\d+):\s+(\S+?)(?:@\S+)?:\s")


def _detect_interface_type(raw: str, kind: str, peer: str | None) -> str:
    raw_lower = raw.lower()

    if kind == "loopback":
        return "loopback"
    if " veth" in raw_lower or "\nveth" in raw_lower or peer:
        return "veth"
    if "\n    bridge" in raw_lower:
        return "bridge"
    if "\n    vrf" in raw_lower:
        return "vrf"
    if "openvswitch" in raw_lower or "\n    ovs" in raw_lower:
        return "openvswitch"
    if "\n    vlan" in raw_lower or " vlan id " in raw_lower:
        return "vlan"
    if "\n    bond" in raw_lower:
        return "bond"
    if "\n    dummy" in raw_lower:
        return "dummy"
    if "\n    tun" in raw_lower or "\n    tuntap" in raw_lower:
        return "tun"
    return "physical" if kind == "ether" else kind


def _infer_interface_role(
    *,
    if_type: str,
    master: str | None,
    peer: str | None,
    namespace: str | None,
    vrf: str | None,
) -> str:
    if if_type == "loopback":
        return "loopback"
    if if_type == "bridge":
        return "bridge-device"
    if if_type == "vrf":
        return "vrf-device"
    if peer:
        if namespace and vrf:
            return "namespace-vrf-edge"
        if namespace:
            return "namespace-edge"
        if vrf:
            return "vrf-edge"
        return "veth-endpoint"
    if master:
        if vrf and master == vrf:
            return "vrf-member"
        if master.startswith("vrf"):
            return "vrf-member"
        if master.startswith(("br", "ovs")):
            return "bridge-port"
        return "member"
    if if_type == "physical":
        return "underlay-uplink"
    return if_type


def get_interface_context(
    executor: RemoteExecutor,
    iface: str = "",
    namespace: str | None = None,
    vrf: str | None = None,
) -> list[InterfaceContext]:
    """Collect interface attributes from one or all network scopes.

    When *namespace* is ``None``, auto-discovers all namespaces (root +
    named) and collects interfaces from each — useful for full topology
    discovery.  When *namespace* is given (including ``""`` for root),
    collects only from that scope.

    *vrf* optionally narrows to a specific VRF within each collected scope.
    """
    if namespace is None:
        return _collect_all_scopes(executor, iface, vrf)
    return _collect_single_scope(executor, iface, namespace, vrf)


def _collect_all_scopes(
    executor: RemoteExecutor,
    iface: str,
    vrf: str | None,
) -> list[InterfaceContext]:
    """Collect interfaces from root namespace and every named namespace."""
    results: list[InterfaceContext] = []
    ns_scopes = ["", *list_network_namespaces(executor)]
    for ns in ns_scopes:
        if vrf is not None:
            results.extend(_collect_single_scope(executor, iface, ns, vrf))
        else:
            # Auto-discover VRFs within this namespace
            results.extend(_collect_single_scope(executor, iface, ns, None))
            for discovered_vrf in list_network_vrfs(executor, ns):
                results.extend(_collect_single_scope(executor, iface, ns, discovered_vrf))
    return results


def _collect_single_scope(
    executor: RemoteExecutor,
    iface: str,
    namespace: str | None,
    vrf: str | None,
) -> list[InterfaceContext]:
    """Collect interfaces for a single namespace scope."""
    ns_for_ctx = namespace if namespace else None
    exec_ctx = ExecContext(namespace=ns_for_ctx, vrf=vrf)

    cmd = f"ip -d link show {iface}" if iface else "ip -d link show"
    raw = executor.run_in_context(cmd, namespace=namespace, vrf=vrf)
    if not raw.strip():
        return []

    if iface:
        parsed = parse_interface(iface, raw, executor=executor, exec_ctx=exec_ctx)
        return [parsed] if parsed else []

    # Bulk-fetch IPs once instead of one SSH round-trip per interface.
    ip_map = _get_all_interface_ips(executor, namespace=namespace, vrf=vrf)
    return _decorate_vrf_members(_parse_all_interfaces(raw, ip_map, exec_ctx=exec_ctx))


def _get_all_interface_ips(
    executor: RemoteExecutor,
    namespace: str | None = None,
    vrf: str | None = None,
) -> dict[str, list[str]]:
    """Run ``ip addr`` once and map interface name → IP list."""
    raw = executor.run_in_context("ip addr", namespace=namespace, vrf=vrf)
    ip_map: dict[str, list[str]] = {}
    current: str | None = None
    for line in raw.splitlines():
        m = re.match(r"^\d+:\s+(\S+?)(?:@\S+)?:\s", line)
        if m:
            current = m.group(1)
            ip_map.setdefault(current, [])
            continue
        if current:
            m = re.match(r"\s+inet6?\s+(\S+)", line)
            if m:
                ip_map[current].append(m.group(1))
    return ip_map


def _parse_all_interfaces(
    raw: str,
    ip_map: dict[str, list[str]],
    exec_ctx: ExecContext | None = None,
) -> list[InterfaceContext]:
    """Parse all interface blocks from ``ip -d link show`` output."""
    lines = raw.splitlines()
    blocks: list[list[str]] = []
    current: list[str] | None = None

    for line in lines:
        if _RE_IFACE_HEAD.match(line):
            if current:
                blocks.append(current)
            current = [line]
        elif current is not None:
            current.append(line)
    if current:
        blocks.append(current)

    results: list[InterfaceContext] = []
    for block in blocks:
        m = _RE_IFACE_HEAD.match(block[0])
        if not m:
            continue
        name = m.group(2)
        parsed = parse_interface(name, "\n".join(block), ip_map=ip_map, exec_ctx=exec_ctx)
        if parsed:
            results.append(parsed)
    return results


def _decorate_vrf_members(interfaces: list[InterfaceContext]) -> list[InterfaceContext]:
    """Propagate VRF names to member interfaces within the same scope."""
    vrf_devices = {iface.iface for iface in interfaces if iface.if_type == "vrf"}
    for iface in interfaces:
        if iface.if_type == "vrf" and not iface.vrf:
            iface.vrf = iface.iface
        elif iface.master in vrf_devices:
            iface.vrf = iface.master
            if iface.role not in {"namespace-vrf-edge", "vrf-edge"}:
                iface.role = "vrf-member"
    return interfaces


def parse_interface(
    iface: str,
    raw: str,
    executor: RemoteExecutor | None = None,
    ip_map: dict[str, list[str]] | None = None,
    exec_ctx: ExecContext | None = None,
) -> InterfaceContext:
    kind = "ether"
    state = None
    mtu = None
    mac = None
    master = None
    peer = None
    link_netnsid = None

    m = re.search(r"link/(\w+)", raw)
    if m:
        kind = m.group(1)

    m = re.search(r"state\s+(\S+)", raw)
    if m:
        state = m.group(1)

    m = re.search(r"mtu\s+(\d+)", raw)
    if m:
        mtu = int(m.group(1))

    m = re.search(r"link/\w+\s+([0-9a-fA-F:]{17})", raw)
    if m:
        mac = m.group(1)

    m = re.search(r"master\s+(\S+)", raw)
    if m:
        master = m.group(1)

    m = re.search(r"peer\s+(\S+)", raw)
    if m:
        peer = m.group(1)

    m = re.search(r"link-netnsid\s+(-?\d+)", raw)
    if m:
        link_netnsid = int(m.group(1))

    if ip_map is not None:
        ips = ip_map.get(iface, [])
    elif executor is not None:
        ips = get_interface_ips(executor, iface)
    else:
        ips = []

    ctx = exec_ctx or _env_exec_ctx()
    if_type = _detect_interface_type(raw, kind, peer)
    role = _infer_interface_role(
        if_type=if_type,
        master=master,
        peer=peer,
        namespace=ctx.namespace,
        vrf=ctx.vrf,
    )
    peer_scope = None
    peer_type = None
    if peer:
        peer_type = if_type if if_type == "veth" else "paired"
        peer_scope = "cross-namespace" if link_netnsid is not None else "same-namespace-or-unknown"

    return InterfaceContext(
        iface=iface,
        namespace=ctx.namespace,
        vrf=ctx.vrf,
        kind=kind,
        if_type=if_type,
        role=role,
        state=state,
        mtu=mtu,
        mac=mac,
        ips=ips,
        master=master,
        peer=peer,
        peer_type=peer_type,
        peer_scope=peer_scope,
        link_netnsid=link_netnsid,
    )


def get_interface_ips(
    executor: RemoteExecutor,
    iface: str,
) -> list[str]:
    raw = executor.run( f"ip addr show {iface}")
    ips: list[str] = []
    for line in raw.splitlines():
        m = re.match(r"\s+inet6?\s+(\S+)", line)
        if m:
            ips.append(m.group(1))
    return ips
