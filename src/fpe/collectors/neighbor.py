"""Neighbor (ARP/NDP) table collection."""

from __future__ import annotations

import re
import logging

from fpe.command.executor import RemoteExecutor, list_network_namespaces, list_network_vrfs
from fpe.models import NeighborInfo

logger = logging.getLogger(__name__)


def check_neighbor(
    executor: RemoteExecutor,
    device: str = "",
    target_ip: str | None = None,
) -> list[NeighborInfo]:
    """Collect neighbor (ARP/NDP) table entries (legacy, no namespace support)."""
    if device:
        raw = executor.run(f"ip neigh show dev {device}")
    else:
        raw = executor.run("ip neigh show")
    return parse_neighbors(raw)


def get_neighbors(
    executor: RemoteExecutor,
    device: str = "",
    target_ip: str | None = None,
    namespace: str | None = None,
    vrf: str | None = None,
) -> list[NeighborInfo]:
    """Collect neighbor table entries from one or all network scopes.

    When *namespace* is ``None``, auto-discovers all namespaces (root +
    named) and collects neighbors from each.  When *namespace* is given
    (including ``""`` for root), collects only from that scope.

    *device* and *target_ip* can be used to filter results.
    """
    if namespace is None:
        neighbors = _collect_neighbors_all_scopes(executor, device, vrf)
    else:
        neighbors = _collect_neighbors_single_scope(executor, device, namespace, vrf)

    if target_ip:
        neighbors = [n for n in neighbors if n.ip == target_ip]

    return neighbors


def _collect_neighbors_all_scopes(
    executor: RemoteExecutor,
    device: str,
    vrf: str | None,
) -> list[NeighborInfo]:
    results: list[NeighborInfo] = []
    ns_scopes = ["", *list_network_namespaces(executor)]
    for ns in ns_scopes:
        if vrf is not None:
            results.extend(_collect_neighbors_single_scope(executor, device, ns, vrf))
        else:
            # Auto-discover VRFs within this namespace
            results.extend(_collect_neighbors_single_scope(executor, device, ns, None))
            for discovered_vrf in list_network_vrfs(executor, ns):
                results.extend(_collect_neighbors_single_scope(executor, device, ns, discovered_vrf))
    return results


def _collect_neighbors_single_scope(
    executor: RemoteExecutor,
    device: str,
    namespace: str | None,
    vrf: str | None,
) -> list[NeighborInfo]:
    ns_for_neigh = namespace if namespace else None
    if device:
        cmd = f"ip neigh show dev {device}"
    else:
        cmd = "ip neigh show"
    raw = executor.run_in_context(cmd, namespace=namespace, vrf=vrf)
    neighbors = parse_neighbors(raw)
    for n in neighbors:
        n.namespace = ns_for_neigh
        n.vrf = vrf
    return neighbors


def parse_neighbors(raw: str) -> list[NeighborInfo]:
    neighbors: list[NeighborInfo] = []

    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue

        parts = line.split()
        if len(parts) < 3:
            continue

        ip = parts[0]
        dev = parts[2] if len(parts) > 2 else ""
        mac = None
        state = "unknown"

        for part in parts[3:]:
            if re.match(r"^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$", part):
                mac = part
            elif part in (
                "REACHABLE", "STALE", "DELAY", "PROBE",
                "FAILED", "INCOMPLETE", "PERMANENT", "NOARP",
            ):
                state = part

        neighbors.append(
            NeighborInfo(
                ip=ip,
                dev=dev,
                mac=mac,
                state=state,
                reachable=state == "REACHABLE",
            )
        )

    return neighbors
