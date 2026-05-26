"""All system information collection functions.

Each function accepts a ``RemoteExecutor`` and host,
runs the appropriate remote command, and returns parsed structured data.
"""

from fpe.collectors.interface import (
    get_interface_context,
    get_interface_ips,
    parse_interface,
)
from fpe.collectors.rules import (
    get_ip_rules,
    get_rules,
    match_ip_rules,
    parse_rules,
)
from fpe.collectors.routes import (
    find_best_route,
    get_route,
    parse_routes,
)
from fpe.collectors.link import (
    resolve_link_type,
    resolve_next_hop,
)
from fpe.collectors.ovs import (
    get_ovs_bridges,
    get_ovs_flows,
    get_ovs_info,
    parse_ovs,
    parse_ovs_flows,
)
from fpe.collectors.neighbor import (
    check_neighbor,
    get_neighbors,
    parse_neighbors,
)

__all__ = [
    "check_neighbor",
    "find_best_route",
    "get_interface_context",
    "get_interface_ips",
    "get_ip_rules",
    "get_neighbors",
    "get_ovs_bridges",
    "get_ovs_flows",
    "get_ovs_info",
    "get_route",
    "get_rules",
    "match_ip_rules",
    "parse_interface",
    "parse_neighbors",
    "parse_ovs",
    "parse_ovs_flows",
    "parse_routes",
    "parse_rules",
    "resolve_link_type",
    "resolve_next_hop",
]
