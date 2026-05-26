"""Context models — packet and execution context."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PacketContext(BaseModel):
    """Describes the packet being analyzed."""

    src_ip: str
    dst_ip: str
    protocol: str | None = None
    src_port: int | None = None
    dst_port: int | None = None
    ingress_if: str | None = None
    egress_if: str | None = None
    fwmark: str | None = None
    tos: int | None = None
    vlan_id: int | None = None
    tunnel_id: str | None = None
    ip_version: int = Field(default=4, ge=4, le=6)


class ExecContext(BaseModel):
    """Describes the execution context for analysis."""

    namespace: str | None = None
    vrf: str | None = None
    host: str | None = None
    ip_version: int = Field(default=4, ge=4, le=6)
    ingress_if: str | None = None
