from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

ENGINE_VERSION = "MC-RISK-ENGINE-2.1.1"
PACKAGE_VERSION = "MC-MODULAR-PARITY-2.1.2"
DEFAULT_HORIZONS: Tuple[int, ...] = (7, 30, 90)
MAX_HORIZON = max(DEFAULT_HORIZONS)
DEFAULT_CONFIDENCE = 0.95
EPS = 1e-12

SCENARIOS: Tuple[str, ...] = (
    "Historique",
    "Conservateur",
    "Neutre",
    "Stress volatilité",
)

MODELS: Tuple[str, ...] = (
    "GBM normal",
    "GBM Student-t calibré",
    "Historical bootstrap",
    "Stationary bootstrap",
    "Filtered historical simulation",
    "Stress volatility",
)

MODEL_ALIASES = {"GBM fat-tail": "GBM Student-t calibré"}
MODEL_SEED_OFFSETS = {
    "GBM normal": 10_001,
    "GBM Student-t calibré": 20_003,
    "Historical bootstrap": 30_007,
    "Stationary bootstrap": 40_009,
    "Filtered historical simulation": 50_021,
    "Stress volatility": 60_037,
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
    confidence_level: float = DEFAULT_CONFIDENCE
    mean_block_length: int = 10
    ewma_lambda: float = 0.94
    ruin_threshold: float = -0.30


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
