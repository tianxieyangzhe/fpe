"""Routing table collection and prefix matching."""

from __future__ import annotations

import logging

from fpe.command.executor import RemoteExecutor, list_network_namespaces, list_network_vrfs
from fpe.models import NextHop, RouteResult

logger = logging.getLogger(__name__)


def get_route(
    executor: RemoteExecutor,
    table: str = "",
    namespace: str | None = None,
    vrf: str | None = None,
) -> list[RouteResult]:
    """Collect routing table entries from one or all network scopes.

    When *namespace* is ``None``, auto-discovers all namespaces (root +
    named) and collects routes from each.  When *namespace* is given
    (including ``""`` for root), collects only from that scope.

    When *table* is non-empty, only that routing table is queried.
    """
    if namespace is None:
        return _collect_routes_all_scopes(executor, table, vrf)
    return _collect_routes_single_scope(executor, table, namespace, vrf)


def _collect_routes_all_scopes(
    executor: RemoteExecutor,
    table: str,
    vrf: str | None,
) -> list[RouteResult]:
    results: list[RouteResult] = []
    ns_scopes = ["", *list_network_namespaces(executor)]
    for ns in ns_scopes:
        if vrf is not None:
            results.extend(_collect_routes_single_scope(executor, table, ns, vrf))
        else:
            # Auto-discover VRFs within this namespace
            results.extend(_collect_routes_single_scope(executor, table, ns, None))
            for discovered_vrf in list_network_vrfs(executor, ns):
                results.extend(_collect_routes_single_scope(executor, table, ns, discovered_vrf))
    return results


def _collect_routes_single_scope(
    executor: RemoteExecutor,
    table: str,
    namespace: str | None,
    vrf: str | None,
) -> list[RouteResult]:
    ns_for_route = namespace if namespace else None
    cmd = f"ip route show table {table}" if table else "ip route show"
    raw = executor.run_in_context(cmd, namespace=namespace, vrf=vrf)
    routes = parse_routes(raw, table or "main")
    for r in routes:
        r.namespace = ns_for_route
        r.vrf = vrf
    return routes


def find_best_route(
    routes: list[RouteResult],
    dst_ip: str,
) -> RouteResult | None:
    """Find the most specific prefix match for *dst_ip*."""
    best: RouteResult | None = None
    best_prefix_len = -1

    for route in routes:
        prefix = route.prefix
        if "/" in prefix:
            _, length_str = prefix.split("/", 1)
            try:
                length = int(length_str)
            except ValueError:
                continue
        else:
            length = 32 if "." in prefix else 128

        if _ip_in_prefix(dst_ip, prefix):
            if length > best_prefix_len:
                best_prefix_len = length
                best = route

    return best


def _ip_in_prefix(ip: str, prefix: str) -> bool:
    import ipaddress

    try:
        network = ipaddress.ip_network(prefix, strict=False)
        addr = ipaddress.ip_address(ip)
        return addr in network
    except ValueError:
        return False


def parse_routes(raw: str, default_table: str) -> list[RouteResult]:
    routes: list[RouteResult] = []

    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue

        parts = line.split()
        if not parts:
            continue

        route_type = "unicast"
        prefix = parts[0]

        if prefix in ("default",):
            prefix = "0.0.0.0/0"
            parts = parts[1:]
        else:
            parts = parts[1:]

        preferred_src = None
        metric = None
        scope = None
        next_hops: list[NextHop] = []

        i = 0
        while i < len(parts):
            if parts[i] == "via" and i + 1 < len(parts):
                next_hops.append(NextHop(via=parts[i + 1]))
                i += 2
            elif parts[i] == "dev" and i + 1 < len(parts):
                if next_hops:
                    next_hops[-1].dev = parts[i + 1]
                else:
                    next_hops.append(NextHop(dev=parts[i + 1]))
                i += 2
            elif parts[i] == "src" and i + 1 < len(parts):
                preferred_src = parts[i + 1]
                i += 2
            elif parts[i] == "metric" and i + 1 < len(parts):
                try:
                    metric = int(parts[i + 1])
                except ValueError:
                    pass
                i += 2
            elif parts[i] == "scope" and i + 1 < len(parts):
                scope = parts[i + 1]
                i += 2
            elif parts[i] == "weight" and i + 1 < len(parts):
                if next_hops:
                    try:
                        next_hops[-1].weight = int(parts[i + 1])
                    except ValueError:
                        pass
                i += 2
            else:
                i += 1

        routes.append(
            RouteResult(
                table=default_table,
                route_type=route_type,
                prefix=prefix,
                preferred_src=preferred_src,
                metric=metric,
                scope=scope,
                next_hops=next_hops,
                raw=line,
            )
        )

    return routes
