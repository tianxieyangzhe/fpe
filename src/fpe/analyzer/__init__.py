"""Analysis orchestration — state machine and main entry point."""

from fpe.analyzer.engine import Analyzer, STATE_COMPLETED, STATE_INCOMPLETE, STATE_FAILED

__all__ = ["Analyzer", "STATE_COMPLETED", "STATE_FAILED", "STATE_INCOMPLETE"]
