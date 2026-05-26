"""Exception hierarchy for FPE."""


class FpeError(Exception):
    """Base exception for all FPE errors."""


class ConfigError(FpeError):
    """Configuration related errors."""


class ToolExecutionError(FpeError):
    """Command execution failures."""


class ParseError(FpeError):
    """Parsing command output failures."""


class UnsupportedTopologyError(FpeError):
    """Topology type not yet supported."""


class ModelApiError(FpeError):
    """Vendor model API call failures."""
