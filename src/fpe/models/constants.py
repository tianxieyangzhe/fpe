"""Constants and enumerations."""


class EvidenceLevel:
    CONFIRMED = "confirmed"
    INFERRED = "inferred"
    UNKNOWN = "unknown"


class ObjectType:
    INTERFACE = "interface"
    RULE = "rule"
    ROUTE = "route"
    LINK = "link"
    NEIGHBOR = "neighbor"
    OVS_BRIDGE = "ovs_bridge"
    OVS_PORT = "ovs_port"
    NAMESPACE = "namespace"
    VRF = "vrf"
    HOP = "hop"


class RiskSeverity:
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"
