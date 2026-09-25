"""Public API for the autonomous Market Intelligence workspace.

Quant Terminal historically shipped a large root-level ``market_intelligence.py``
used by the Macro / Central Banks hub.  Python resolves this package before that
module, so unknown attributes are delegated lazily to the legacy file.  This
preserves its frozen public API without importing 23k lines of provider/UI code
when the new workspace is merely imported.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import ModuleType
from typing import Any


__all__ = ["render_market_intelligence_lab"]

_LEGACY_MODULE_NAME = "_quant_terminal_market_intelligence_legacy"
_legacy_module: ModuleType | None = None


def render_market_intelligence_lab(
    ticker: str = "SPY",
    price_data: Any = None,
    analysis: Any = None,
) -> None:
    """Render the autonomous research workspace without import-time side effects."""

    from .controller import render_market_intelligence_lab as _render

    _render(ticker=ticker, price_data=price_data, analysis=analysis)


def _load_legacy_module() -> ModuleType:
    global _legacy_module
    if _legacy_module is not None:
        return _legacy_module
    legacy_path = Path(__file__).resolve().parent.parent / "market_intelligence.py"
    if not legacy_path.is_file():
        raise AttributeError("Legacy market_intelligence.py is unavailable")
    existing = sys.modules.get(_LEGACY_MODULE_NAME)
    if existing is not None:
        _legacy_module = existing
        return existing
    spec = importlib.util.spec_from_file_location(_LEGACY_MODULE_NAME, legacy_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load legacy Market Intelligence module at {legacy_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[_LEGACY_MODULE_NAME] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(_LEGACY_MODULE_NAME, None)
        raise
    _legacy_module = module
    return module


def __getattr__(name: str) -> Any:
    """Delegate legacy public/private bridge attributes only when requested."""

    if name.startswith("__"):
        raise AttributeError(name)
    legacy = _load_legacy_module()
    try:
        return getattr(legacy, name)
    except AttributeError as exc:
        raise AttributeError(f"module 'market_intelligence' has no attribute {name!r}") from exc


def __dir__() -> list[str]:
    return sorted(set(globals()) | {"render_market_intelligence", "_liq3_load_fred_pack"})
