from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

ENGINE_VERSION = "MC-RISK-ENGINE-2.8.1A"
PACKAGE_VERSION = "MC-MODEL-RISK-GOVERNANCE-FINISHING-2.8.1A"
DEFAULT_HORIZONS: Tuple[int, ...] = (7, 30, 90)
MAX_HORIZON = max(DEFAULT_HORIZONS)
DEFAULT_CONFIDENCE = 0.95
EPS = 1e-12

LONG_HISTORY_PROVIDER = "yfinance"
LONG_HISTORY_PERIODS: Tuple[str, ...] = ("5y", "10y", "max")
DEFAULT_LONG_HISTORY_PERIOD = "10y"
DEFAULT_LONG_HISTORY_CACHE_TTL_HOURS = 12
LONG_HISTORY_PRICE_BASES: Tuple[str, ...] = ("adjusted", "raw")

SCENARIOS: Tuple[str, ...] = (
    "Historique",
    "Conservateur",
    "Neutre",
    "Stress volatilité",
)

# Models are simulation engines. Stress is intentionally kept in SCENARIOS rather
# than represented as a separate model.
MODELS: Tuple[str, ...] = (
    "GBM normal",
    "GBM Student-t calibré",
    "Historical bootstrap",
    "Stationary bootstrap",
    "Filtered historical simulation",
    "GARCH(1,1) normal",
    "GARCH(1,1) Student-t",
    "GJR-GARCH Student-t",
    "Filtered historical GARCH-t",
)

MODEL_ALIASES = {
    "GBM fat-tail": "GBM Student-t calibré",
    "Stress volatility": "GBM normal",  # deprecated V2.1 alias
    "FHS EWMA": "Filtered historical simulation",
    "FHS GARCH-t": "Filtered historical GARCH-t",
}

MODEL_SEED_OFFSETS = {
    "GBM normal": 10_001,
    "GBM Student-t calibré": 20_003,
    "Historical bootstrap": 30_007,
    "Stationary bootstrap": 40_009,
    "Filtered historical simulation": 50_021,
    "GARCH(1,1) normal": 60_037,
    "GARCH(1,1) Student-t": 70_049,
    "GJR-GARCH Student-t": 80_063,
    "Filtered historical GARCH-t": 90_079,
}

CONDITIONAL_MODEL_NAMES: Tuple[str, ...] = (
    "GARCH(1,1) normal",
    "GARCH(1,1) Student-t",
    "GJR-GARCH Student-t",
)

BRIDGE_COMPATIBLE_MODELS: Tuple[str, ...] = ("GBM normal",)
BARRIER_MONITORING_OPTIONS: Tuple[str, ...] = (
    "Brownian bridge (GBM)",
    "Clôture de chaque pas",
)

ELIGIBILITY_STATUSES: Tuple[str, ...] = (
    "ELIGIBLE",
    "WARNING",
    "INELIGIBLE",
    "FALLBACK",
)

# Hard minimum and institutional preferred sample sizes by engine. The gate does
# not invent history: it records limitations and excludes weak models from
# aggregation while preserving research visibility.
MODEL_SAMPLE_REQUIREMENTS = {
    "GBM normal": (60, 252),
    "GBM Student-t calibré": (120, 500),
    "Historical bootstrap": (120, 500),
    "Stationary bootstrap": (252, 750),
    "Filtered historical simulation": (252, 750),
    "GARCH(1,1) normal": (252, 750),
    "GARCH(1,1) Student-t": (252, 750),
    "GJR-GARCH Student-t": (500, 1_000),
    "Filtered historical GARCH-t": (500, 1_000),
}


VALIDATION_HORIZONS: Tuple[int, ...] = (1, 7, 30)
VALIDATION_QUANTILES: Tuple[float, ...] = (0.01, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99)
VALIDATION_MODEL_PRESETS = {
    "Eligible + warning": None,
    "Fast core": (
        "GBM normal",
        "GBM Student-t calibré",
        "Historical bootstrap",
        "Stationary bootstrap",
        "Filtered historical simulation",
    ),
    "Conditional suite": (
        "GARCH(1,1) normal",
        "GARCH(1,1) Student-t",
        "GJR-GARCH Student-t",
        "Filtered historical GARCH-t",
    ),
    "All models": MODELS,
}

PLOT_BG = "rgba(7, 12, 22, 0.55)"
GRID_COLOR = "rgba(148, 163, 184, 0.16)"
TEXT_COLOR = "#d7e0eb"
MUTED_COLOR = "#93a4b8"
BLUE = "#56a8ff"
CYAN = "#53d6e8"
GREEN = "#39c684"
ORANGE = "#f2a65a"
RED = "#ef6b73"
PURPLE = "#9c8cff"


@dataclass(frozen=True)
class MonteCarloSettings:
    simulations: int = 3_000
    matrix_simulations: int = 2_000
    scenario: str = "Conservateur"
    model: str = "GBM normal"
    seed: int = 42
    barrier_monitoring: str = "Brownian bridge (GBM)"
    effective_barrier_monitoring: str = "Brownian bridge (GBM)"
    confidence_level: float = DEFAULT_CONFIDENCE
    mean_block_length: int = 10
    ewma_lambda: float = 0.94
    ruin_threshold: float = -0.30
    calibration_window: int | None = None
    calibration_source_mode: str = "auto"
    garch_maxiter: int = 800
    garch_min_observations: int = 120
    stability_check: bool = True
    provider_name: str = LONG_HISTORY_PROVIDER
    provider_period: str = DEFAULT_LONG_HISTORY_PERIOD
    provider_cache_ttl_hours: int = DEFAULT_LONG_HISTORY_CACHE_TTL_HOURS
    provider_price_basis: str = "adjusted"
    provider_enabled: bool = True


@dataclass(frozen=True)
class ScenarioParameters:
    drift_ann: float
    vol_ann: float
    drift_multiplier: float
    volatility_multiplier: float
    note: str


@dataclass(frozen=True)
class BarrierLevels:
    current: float
    stop_short: float
    stop_structural: float
    target_1: float
    target_2: float
    source: str


@dataclass(frozen=True)
class WalkForwardSettings:
    horizon: int = 7
    forecast_origins: int = 40
    origin_stride: int = 7
    paths_per_origin: int = 500
    scenario: str = "Neutre"
    training_window: int | None = None
    minimum_training_observations: int = 120
    conditional_refit_every: int = 1
    seed: int = 42
    mean_block_length: int = 10
    ewma_lambda: float = 0.94
    garch_maxiter: int = 500
    garch_min_observations: int = 120
    stability_check: bool = False
    confidence_level: float = DEFAULT_CONFIDENCE
