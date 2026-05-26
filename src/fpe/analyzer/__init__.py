"""Analysis orchestration — state machine, walks, and main entry point."""

from fpe.analyzer.engine import Analyzer, STATE_COMPLETED, STATE_INCOMPLETE, STATE_FAILED
from fpe.analyzer.walks import (
    build_candidate_flow_walk,
    build_rule_walk,
    _analyze_flow_match,
    _find_bridge_port,
    _resolve_ingress_port,
)

__all__ = [
    "Analyzer",
    "STATE_COMPLETED",
    "STATE_FAILED",
    "STATE_INCOMPLETE",
    "build_candidate_flow_walk",
    "build_rule_walk",
    "_analyze_flow_match",
    "_find_bridge_port",
    "_resolve_ingress_port",
]
