"""Network data models — interface, route, rule, link, OVS, neighbor."""

from __future__ import annotations

from pydantic import BaseModel


# ── Interface model ──────────────────────────────────────────────────

class InterfaceContext(BaseModel):
    """Describes a network interface's attributes."""

    iface: str
    namespace: str | None = None
    vrf: str | None = None
    kind: str
    if_type: str = "physical"
    role: str | None = None
    state: str | None = None
    mtu: int | None = None
    mac: str | None = None
    ips: list[str] = []
    master: str | None = None
    peer: str | None = None
    peer_type: str | None = None
    peer_scope: str | None = None
    link_netnsid: int | None = None


# ── Route / Rule models ──────────────────────────────────────────────

class RuleInfo(BaseModel):
    """IP policy routing rule with network scope context."""

    priority: int
    table: str
    raw: str
    namespace: str | None = None
    vrf: str | None = None


class RuleMatch(BaseModel):
    """Describes a matched IP rule entry."""

    priority: int
    table: str
    matched_fields: list[str] = []
    unresolved_fields: list[str] = []
    raw: str


class RuleMatchResult(BaseModel):
    """Result of IP rule matching against a packet."""

    matches: list[RuleMatch] = []
    has_unresolved_rules: bool = False
    warnings: list[str] = []


class NextHop(BaseModel):
    """Describes a single next hop in a route."""

    via: str | None = None
    dev: str | None = None
    weight: int | None = None


class RouteResult(BaseModel):
    """Describes a matched routing table entry with network scope context."""

    table: str
    route_type: str
    prefix: str
    preferred_src: str | None = None
    metric: int | None = None
    scope: str | None = None
    next_hops: list[NextHop] = []
    raw: str
    namespace: str | None = None
    vrf: str | None = None


# ── Link model ───────────────────────────────────────────────────────

class LinkResolution(BaseModel):
    """Describes how a link resolves to the next hop."""

    dev_type: str
    peer_if: str | None = None
    next_namespace: str | None = None
    next_vrf: str | None = None
    bridge: str | None = None
    requires_ovs: bool = False


# ── OVS models ───────────────────────────────────────────────────────

class OvsPortInfo(BaseModel):
    """Describes an OVS port's attributes."""

    bridge: str
    port: str
    interface: str | None = None
    port_type: str
    ofport: int | None = None
    vlan_tag: int | None = None
    trunk_vlans: list[int] = []
    mac: str | None = None
    internal_path_known: bool = False


class OvsBridge(BaseModel):
    """Describes an OVS bridge with its ports."""

    name: str
    datapath_id: str | None = None
    datapath_type: str | None = None
    ports: list[OvsPortInfo] = []


class OvsFlow(BaseModel):
    """Describes an OpenFlow flow table entry."""

    bridge: str
    table: int
    priority: int
    match: str
    actions: str
    match_fields: dict[str, str] = {}
    action_list: list[str] = []
    cookie: str | None = None
    duration_sec: float | None = None
    n_packets: int | None = None
    n_bytes: int | None = None
    idle_age_sec: float | None = None


# ── Neighbor model ───────────────────────────────────────────────────

class NeighborInfo(BaseModel):
    """Describes a neighbor table entry with network scope context."""

    ip: str
    dev: str
    mac: str | None = None
    state: str
    reachable: bool
    namespace: str | None = None
    vrf: str | None = None


# ── OVS Group models ────────────────────────────────────────────────

class OvsGroupBucket(BaseModel):
    """Describes an OVS group bucket (action set within a group)."""

    bucket_id: int
    weight: int
    actions: str
    packet_count: int = 0
    byte_count: int = 0
    watch_port: int | None = None
    watch_group: int | None = None
    active: bool | None = None


class OvsGroup(BaseModel):
    """Describes an OVS group definition with buckets and statistics."""

    group_id: int
    group_type: str  # "select", "all", "ff", "indirect"
    n_buckets: int
    packet_count: int = 0
    byte_count: int = 0
    buckets: list[OvsGroupBucket] = []
