from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DependencyConfig:
    """Configuration for the multi-force dependency attribution layer.

    V4.0.2 keeps the frozen V3.1.1 correlation core untouched and strengthens the
    *inference* around lead/lag, extreme-day and higher-comoment diagnostics.  The
    layer remains deliberately conservative: it attributes association and covariance,
    but never upgrades an association to a causal statement unless the caller supplies
    a credible structural identification label from an upstream research design.
    """

    min_pair_obs: int = 80
    max_factors: int = 12
    max_factors_per_family: int = 3
    collinearity_threshold: float = 0.92
    min_factor_std: float = 1e-10
    exact_shapley_max_groups: int = 7
    shapley_permutations: int = 256

    # Lead/lag diagnostics.  Non-zero lag selection is explicitly post-selection aware.
    lead_lag_max_days: int = 5
    lead_lag_bootstrap_samples: int = 399
    lead_lag_ci_level: float = 0.95
    lead_lag_block_length: int = 5
    lead_lag_support_alpha: float = 0.05
    lead_lag_weak_alpha: float = 0.10

    # Daily extreme-move proxy (not an intraday jump test).
    extreme_z_threshold: float = 3.0
    extreme_bootstrap_samples: int = 599
    extreme_ci_level: float = 0.95
    # Deprecated compatibility alias. The daily statistic is an extreme-move proxy,
    # not an intraday jump test.
    jump_z_threshold: float = 3.0

    # Higher-order joint moments are noisy; use moving-block uncertainty by default.
    higher_moment_bootstrap_samples: int = 499
    higher_moment_ci_level: float = 0.95
    higher_moment_block_length: int = 5

    factor_stability_windows: tuple[int, ...] = (63, 126, 252)
    factor_stability_min_windows: int = 2
    factor_min_relevance: float = 0.015
    event_side_window: int = 20
    event_min_obs_side: int = 12
    event_min_events: int = 2
    event_bootstrap_samples: int = 500
    liquidity_min_obs: int = 40
    currency_min_obs: int = 40
    factor_lookback_days: int = 504
    residual_lookback_days: int = 504
    random_seed: int = 42
