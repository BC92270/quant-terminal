"""Universal, event-ordered research backtesting primitives.

The package is intentionally independent from Streamlit.  It provides the
portable contracts used by the Backtest Lab for multi-asset simulations while
the existing :mod:`backtest_institutional` package remains the authority for
statistical validation and promotion gates.
"""

from .engine import UniversalBacktestEngine, UniversalEngineConfig, UniversalRunResult
from .events import EventQueue
from .fx import FXMatrix, MissingFXRate
from .margin import MarginSnapshot, UniversalMarginModel
from .orders import (
    Fill,
    InvalidOrderTransition,
    MarketSnapshot,
    Order,
    OrderEvent,
    OrderEventKind,
    OrderKernel,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)
from .portfolio import CashBook, PortfolioLedger, Position
from .security import SecurityMaster
from .strategy import (
    DEFAULT_STRATEGY_TEMPLATE,
    SandboxAttestation,
    SandboxRequiredError,
    StrategyJobV1,
    StrategyPolicyReport,
    build_strategy_job,
    validate_strategy_source,
)
from .types import (
    AssetClass,
    CorporateActionKind,
    Event,
    EventKind,
    Instrument,
    OptionRight,
    SettlementType,
)

__all__ = [
    "AssetClass",
    "CashBook",
    "CorporateActionKind",
    "Event",
    "EventKind",
    "EventQueue",
    "FXMatrix",
    "Instrument",
    "InvalidOrderTransition",
    "MarginSnapshot",
    "MarketSnapshot",
    "MissingFXRate",
    "OptionRight",
    "Order",
    "OrderEvent",
    "OrderEventKind",
    "OrderKernel",
    "OrderRequest",
    "OrderSide",
    "OrderStatus",
    "OrderType",
    "PortfolioLedger",
    "Position",
    "SecurityMaster",
    "SandboxAttestation",
    "SandboxRequiredError",
    "SettlementType",
    "StrategyJobV1",
    "StrategyPolicyReport",
    "TimeInForce",
    "UniversalBacktestEngine",
    "UniversalEngineConfig",
    "UniversalMarginModel",
    "UniversalRunResult",
    "DEFAULT_STRATEGY_TEMPLATE",
    "build_strategy_job",
    "validate_strategy_source",
    "Fill",
]

__version__ = "0.2.0"
