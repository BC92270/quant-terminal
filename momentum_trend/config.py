from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum


class Profile(str, Enum):
    TACTICAL = "Tactical"
    BALANCED = "Balanced"
    POSITION = "Position"


@dataclass(frozen=True)
class EngineConfig:
    """Immutable assumptions used by every engine layer.

    Periods are expressed in observations. The defaults target daily bars. A
    caller using intraday data should pass an explicit annualisation factor.
    """

    profile: Profile = Profile.BALANCED
    forecast_horizon: int = 5
    annualisation: int = 252
    min_history: int = 160
    risk_budget: float = 0.005
    max_position_weight: float = 0.20
    transaction_cost_bps: float = 8.0
    regime_stickiness: float = 0.92
    random_state: int = 17
    enable_neural_model: bool = True
    primary_benchmark: str = "SPY"

    @classmethod
    def for_profile(cls, profile: Profile | str, **overrides) -> "EngineConfig":
        selected = Profile(profile)
        presets = {
            Profile.TACTICAL: dict(
                profile=selected,
                forecast_horizon=3,
                min_history=140,
                risk_budget=0.0035,
                max_position_weight=0.14,
                regime_stickiness=0.88,
            ),
            Profile.BALANCED: dict(profile=selected),
            Profile.POSITION: dict(
                profile=selected,
                forecast_horizon=20,
                min_history=220,
                risk_budget=0.006,
                max_position_weight=0.24,
                regime_stickiness=0.96,
            ),
        }
        return cls(**(presets[selected] | overrides))

    def with_horizon(self, horizon: int) -> "EngineConfig":
        return replace(self, forecast_horizon=max(1, int(horizon)))

