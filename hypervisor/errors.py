"""
hypervisor/errors.py

Arca exception hierarchy. Raise these instead of bare Exception so the
main loop can distinguish recoverable from fatal failures.

Recoverable (log + continue cycle with cached/fallback data):
  ExternalAPIError, WorkerUnreachableError

Non-recoverable (halt cycle, keep previous regime):
  RegimeClassificationError

Fatal (bubble up to orchestration_loop, log, skip to next cycle):
  ArcaError (base)
"""


class ArcaError(Exception):
    """Base for all Arca system errors."""


class WorkerUnreachableError(ArcaError):
    """A worker failed its health check or HTTP call timed out."""


class ExternalAPIError(ArcaError):
    """An external data source (yfinance, FRED, GDELT, OKX, etc.) failed."""


class RiskLimitBreachedError(ArcaError):
    """The RiskManager rejected an allocation or action."""


class RegimeClassificationError(ArcaError):
    """HMM classifier failed; previous regime is held until next cycle."""


class ConfigurationError(ArcaError):
    """Missing or invalid configuration (env var, YAML file, etc.)."""
