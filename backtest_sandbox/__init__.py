"""Attested, Docker-only strategy execution for Backtest Lab.

The package deliberately separates untrusted strategy evaluation from the
authoritative portfolio ledger.  A sandbox may emit target exposures only;
orders, fills, accounting and performance are always produced by
``backtest_universal`` on the trusted host side.
"""

from .contracts import (
    CompileResult,
    SandboxLimits,
    SandboxRunResult,
    StrategyLanguage,
)
from .docker_runner import DockerStrategyRunner, SandboxUnavailableError
from .policy import validate_source
from .templates import STRATEGY_TEMPLATES, template_for

__all__ = [
    "CompileResult",
    "DockerStrategyRunner",
    "SandboxLimits",
    "SandboxRunResult",
    "SandboxUnavailableError",
    "STRATEGY_TEMPLATES",
    "StrategyLanguage",
    "template_for",
    "validate_source",
]
