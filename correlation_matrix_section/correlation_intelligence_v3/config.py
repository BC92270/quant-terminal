from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CorrelationConfig:
    """Central configuration for Correlation Intelligence V3.1.1 final hotfix."""

    selected_days_default: int = 90
    available_windows: tuple[int, ...] = (20, 30, 60, 90, 180, 252)
    term_structure_windows: tuple[int, ...] = (20, 60, 90, 180, 252)
    hedge_windows: tuple[int, ...] = (30, 90, 180, 252)
    min_pair_obs: int = 30
    min_matrix_obs: int = 40
    min_regime_compute_obs: int = 12
    reliable_regime_obs: int = 30

    # Covariance forecasting / model validation.
    covariance_model_options: tuple[str, ...] = (
        "Sample", "Ledoit-Wolf", "OAS", "EWMA", "POET-style", "Factor-GLasso", "RMT spectral", "Nonlinear Shrinkage"
    )
    covariance_validation_models: tuple[str, ...] = (
        "Ledoit-Wolf", "OAS", "EWMA", "POET-style", "Factor-GLasso", "RMT spectral"
    )
    covariance_train_days: int = 252
    covariance_forecast_horizon: int = 5
    covariance_validation_max_folds: int = 20
    covariance_min_train: int = 126
    covariance_champion_bootstrap_samples: int = 2000

    # Dedicated tail engine. Tail estimation is intentionally decoupled from the central correlation horizon.
    tail_quantile: float = 0.10
    tail_target_obs: int = 30
    tail_max_days: int = 756
    tail_mode_default: str = "Adaptive"
    tail_mode_options: tuple[str, ...] = ("Adaptive", "Central", "1Y", "2Y", "3Y")
    tail_bootstrap_samples: int = 300
    tail_bootstrap_block: int = 5
    tail_surface_quantiles: tuple[float, ...] = (0.05, 0.10, 0.25, 0.75, 0.90, 0.95)
    tail_surface_days: int = 504

    ewma_lambda: float = 0.94
    bootstrap_samples: int = 400
    random_seed: int = 42
    high_corr_threshold: float = 0.70
    inverse_corr_threshold: float = -0.30
    dcc_maxiter: int = 250
    rmt_cleaning: str = "constant_residual_eigenvalue"
    max_heatmap_assets: int = 45
    max_network_edges: int = 80
    hac_maxlags: int = 5
    collinearity_pair_threshold: float = 0.92
    vif_warning: float = 5.0
    vif_severe: float = 10.0
    condition_warning: float = 15.0
    condition_severe: float = 30.0

    # Directional connectedness (generalized FEVD / Diebold-Yilmaz style).
    connectedness_window: int = 252
    connectedness_horizon: int = 10
    connectedness_maxlags: int = 3
    connectedness_min_obs: int = 100
    connectedness_max_assets: int = 8
    partial_network_threshold: float = 0.12
    partial_network_max_edges: int = 50
    network_bootstrap_samples: int = 500
    network_selection_threshold: float = 0.65
    frequency_connectedness_days: int = 504
    frequency_connectedness_min_obs: int = 120

    # Structural break diagnostics.
    break_detection_days: int = 504
    break_side_window: int = 60
    break_step: int = 5
    break_bootstrap_samples: int = 249

    # Portfolio dependency layer.
    correlation_shock_levels: tuple[float, ...] = (0.10, 0.20, 0.35)
    eigen_risk_days: int = 252
    incremental_add_weight: float = 0.05
    forward_realized_days: int = 63

    data_period_options: tuple[str, ...] = ("6mo", "1y", "2y", "5y")
    default_data_period: str = "2y"
    default_estimator: str = "Ledoit-Wolf"
    estimator_options: tuple[str, ...] = (
        "Pearson",
        "Spearman",
        "Kendall",
        "Ledoit-Wolf",
        "OAS",
        "Partial",
    )
    regime_market_candidates: tuple[str, ...] = ("SPY", "QQQ", "IWM", "DIA")
    factor_candidates: tuple[str, ...] = (
        "SPY", "QQQ", "IWM", "SMH", "SOXX", "XLK", "XLF", "XLE", "XLV",
        "TLT", "IEF", "HYG", "LQD", "GLD", "USO", "UUP", "BTC-USD", "^VIX",
    )
    default_cross_asset_proxies: tuple[str, ...] = (
        "SPY", "QQQ", "IWM", "TLT", "HYG", "GLD", "USO", "UUP", "BTC-USD", "^VIX"
    )
    pair_bootstrap_block: int = 5
    ui_card_count: int = 6
    metadata: dict[str, str] = field(default_factory=lambda: {"engine_version": "3.1.1"})
