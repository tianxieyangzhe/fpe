"""Link / next-hop resolution — ``ip -d link show`` type detection."""

from __future__ import annotations

import re
import logging

from fpe.command.executor import RemoteExecutor, _env_exec_ctx
from fpe.models import LinkResolution

logger = logging.getLogger(__name__)


def resolve_next_hop(
    executor: RemoteExecutor,
    device: str,
    next_hop_ip: str | None = None,
) -> LinkResolution | None:
    """Resolve how a link reaches its next hop."""
    if not device:
        return None

    raw = executor.run( f"ip -d link show {device}")
    if not raw.strip():
        logger.warning("No link info for device %s", device)
        return None

    return resolve_link_type(device, raw)


def resolve_link_type(
    device: str,
    raw: str,
) -> LinkResolution:
    kind = "ether"
    peer = None

    m = re.search(r"link/(\w+)", raw)
    if m:
        kind = m.group(1)

    m = re.search(r"peer\s+(\S+)", raw)
    if m:
        peer = m.group(1)

    if "veth" in raw.lower():
        kind = "veth"
    elif "bridge" in raw.lower():
        kind = "bridge"

    exec_ctx = _env_exec_ctx()

    if kind == "veth":
        return LinkResolution(
            dev_type="veth",
            peer_if=peer,
            next_namespace=exec_ctx.namespace,
            next_vrf=exec_ctx.vrf,
        )
    elif kind == "bridge":
        return LinkResolution(
            dev_type="bridge",
            peer_if=None,
            next_namespace=exec_ctx.namespace,
            next_vrf=exec_ctx.vrf,
            bridge=device,
        )
    elif kind in ("openvswitch", "ovs"):
        return LinkResolution(
            dev_type="openvswitch",
            peer_if=None,
            next_namespace=exec_ctx.namespace,
            next_vrf=exec_ctx.vrf,
            bridge=device,
            requires_ovs=True,
        )
    else:
        return LinkResolution(
            dev_type="physical",
            peer_if=None,
            next_namespace=exec_ctx.namespace,
            next_vrf=exec_ctx.vrf,
        )
