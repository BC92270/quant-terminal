"""Monte Carlo Risk & Scenario Engine — model-risk and numerical governance V2.8.1A."""

from .config import DEFAULT_HORIZONS, ENGINE_VERSION, MODELS, PACKAGE_VERSION, SCENARIOS, VALIDATION_HORIZONS
from .data_bridge import fetch_long_history, normalize_provider_history
from .engine import build_monte_carlo_lab
from .ensemble import ENSEMBLE_WEIGHTING_METHODS, build_validated_ensemble, derive_ensemble_weights
from .walk_forward import build_walk_forward_validation
from .uncertainty import (
    UNCERTAINTY_VERSION,
    UNCERTAINTY_WEIGHTING_METHODS,
    build_parameter_model_uncertainty,
    resolve_uncertainty_model_weights,
)
from .options_risk_neutral import (
    OPTIONS_RISK_NEUTRAL_VERSION,
    OptionsRiskNeutralSettings,
    black_scholes_price,
    implied_volatility,
    list_option_expirations,
    fetch_option_chain,
    normalize_option_chain,
    parse_option_chain_csv,
    project_arbitrage_free_call_curve,
    estimate_forward_from_parity,
    build_options_risk_neutral_lab,
)
from .options_surface import (
    OPTIONS_SURFACE_VERSION,
    OptionsSurfaceSettings,
    SURFACE_TARGET_DAYS,
    select_surface_expirations,
    fetch_option_surface_chains,
    fit_svi_slice,
    build_governed_carry_curve,
    diagnose_atm_term_structure_events,
    build_multi_expiry_surface,
)
from .calibration_dataset import (
    CALIBRATION_DATASET_VERSION,
    CalibrationDatasetSettings,
    EVENT_POLICIES,
    HOLDOUT_POLICIES,
    WEIGHTING_METHODS,
    estimate_event_variance_adjustments,
    build_calibration_dataset,
)

from .heston_calibration import (
    HESTON_CALIBRATION_VERSION,
    HESTON_OBJECTIVES,
    FELLER_POLICIES,
    HestonParameters,
    HestonCalibrationSettings,
    heston_characteristic_function,
    heston_call_prices,
    heston_option_prices,
    calibrate_heston,
)

from .heston_simulation import (
    HESTON_SIMULATION_VERSION,
    HESTON_SIMULATION_SCHEMES,
    HestonSimulationSettings,
    build_heston_q_simulation,
)

from .bates_calibration import (
    BATES_CALIBRATION_VERSION,
    BATES_CHAMPION_STATUSES,
    BatesParameters,
    BatesCalibrationSettings,
    bates_characteristic_function,
    bates_call_prices,
    bates_option_prices,
    calibrate_bates,
)


from .bates_simulation import (
    BATES_SIMULATION_VERSION,
    BATES_SIMULATION_SCHEMES,
    BatesSimulationSettings,
    build_bates_q_simulation,
)


from .model_risk import (
    MODEL_RISK_VERSION,
    MODEL_RISK_STATUSES,
    ModelRiskSettings,
    build_model_risk_governance,
)

from .tail_event import (
    TAIL_EVENT_STRESS_TYPES,
    TAIL_EVENT_VERSION,
    build_tail_event_stress,
    fit_evt_tail,
    calibrate_merton_jumps,
    historical_event_library,
    assess_evt_threshold_stability,
)


def render_monte_carlo_advanced_lab(*args, **kwargs):
    """Lazy UI entry point; Streamlit is imported only when rendering."""
    from .ui.app import render_monte_carlo_advanced_lab as _render

    return _render(*args, **kwargs)


__all__ = [
    "build_monte_carlo_lab",
    "render_monte_carlo_advanced_lab",
    "build_walk_forward_validation",
    "build_validated_ensemble",
    "derive_ensemble_weights",
    "ENSEMBLE_WEIGHTING_METHODS",
    "fetch_long_history",
    "normalize_provider_history",
    "ENGINE_VERSION",
    "PACKAGE_VERSION",
    "DEFAULT_HORIZONS",
    "SCENARIOS",
    "MODELS",
    "VALIDATION_HORIZONS",
    "TAIL_EVENT_VERSION",
    "TAIL_EVENT_STRESS_TYPES",
    "build_tail_event_stress",
    "fit_evt_tail",
    "calibrate_merton_jumps",
    "historical_event_library",
    "assess_evt_threshold_stability",
    "OPTIONS_RISK_NEUTRAL_VERSION",
    "OptionsRiskNeutralSettings",
    "black_scholes_price",
    "implied_volatility",
    "list_option_expirations",
    "fetch_option_chain",
    "normalize_option_chain",
    "parse_option_chain_csv",
    "project_arbitrage_free_call_curve",
    "estimate_forward_from_parity",
    "build_options_risk_neutral_lab",
    "OPTIONS_SURFACE_VERSION",
    "OptionsSurfaceSettings",
    "SURFACE_TARGET_DAYS",
    "select_surface_expirations",
    "fetch_option_surface_chains",
    "fit_svi_slice",
    "build_governed_carry_curve",
    "diagnose_atm_term_structure_events",
    "build_multi_expiry_surface",
    "CALIBRATION_DATASET_VERSION",
    "CalibrationDatasetSettings",
    "EVENT_POLICIES",
    "HOLDOUT_POLICIES",
    "WEIGHTING_METHODS",
    "estimate_event_variance_adjustments",
    "build_calibration_dataset",
    "HESTON_CALIBRATION_VERSION",
    "HESTON_OBJECTIVES",
    "FELLER_POLICIES",
    "HestonParameters",
    "HestonCalibrationSettings",
    "heston_characteristic_function",
    "heston_call_prices",
    "heston_option_prices",
    "calibrate_heston",
    "HESTON_SIMULATION_VERSION",
    "HESTON_SIMULATION_SCHEMES",
    "HestonSimulationSettings",
    "build_heston_q_simulation",
    "BATES_CALIBRATION_VERSION",
    "BATES_CHAMPION_STATUSES",
    "BatesParameters",
    "BatesCalibrationSettings",
    "bates_characteristic_function",
    "bates_call_prices",
    "bates_option_prices",
    "calibrate_bates",
    "BATES_SIMULATION_VERSION",
    "BATES_SIMULATION_SCHEMES",
    "BatesSimulationSettings",
    "build_bates_q_simulation",
    "MODEL_RISK_VERSION",
    "MODEL_RISK_STATUSES",
    "ModelRiskSettings",
    "build_model_risk_governance",
    "UNCERTAINTY_VERSION",
    "UNCERTAINTY_WEIGHTING_METHODS",
    "build_parameter_model_uncertainty",
    "resolve_uncertainty_model_weights",
]
