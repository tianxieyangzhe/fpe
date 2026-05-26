"""Analysis models — state, path, decision, risk, result."""

from __future__ import annotations

from pydantic import BaseModel, Field

from fpe.models.context import ExecContext, PacketContext


class PathNode(BaseModel):
    """A single node in the analyzed path."""

    hop_index: int
    namespace: str | None = None
    vrf: str | None = None
    obj_type: str
    obj_name: str
    reason: str
    evidence_level: str = "inferred"


class DecisionEvent(BaseModel):
    """A decision made during analysis."""

    state: str
    source: str
    message: str
    evidence_level: str = "inferred"


class RiskItem(BaseModel):
    """A detected risk or anomaly."""

    code: str
    severity: str
    message: str


class AnalysisState(BaseModel):
    """Current state of a flow analysis."""

    trace_id: str
    flow_state: str = "INIT"
    packet: PacketContext
    exec_ctx: ExecContext
    current_hop: int = 0
    max_hops: int = 16
    path: list[PathNode] = []
    decision_chain: list[DecisionEvent] = []
    risks: list[RiskItem] = []
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    confidence_reasons: list[str] = []
    visited: list[str] = []


# ── Output / result models ───────────────────────────────────────────

class ToolResult(BaseModel):
    """Standardized return envelope for all MCP tools."""

    ok: bool
    tool: str
    context: dict | None = None
    data: dict | None = None
    warnings: list[str] = []
    error: str | None = None


class AnalysisResult(BaseModel):
    """Final result of a flow analysis."""

    status: str
    path: list[PathNode]
    decision_chain: list[DecisionEvent]
    risks: list[RiskItem]
    confidence: float
    confidence_reasons: list[str]
    summary: str
