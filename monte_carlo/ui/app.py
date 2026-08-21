from __future__ import annotations

from typing import Any, Dict, Mapping

import pandas as pd
import streamlit as st

from ..barriers import barrier_monitoring_capabilities
from ..calibration_sources import parse_uploaded_calibration_file
from ..data_bridge import fetch_long_history
from ..config import (
    DEFAULT_HORIZONS,
    DEFAULT_LONG_HISTORY_CACHE_TTL_HOURS,
    DEFAULT_LONG_HISTORY_PERIOD,
    LONG_HISTORY_PERIODS,
    LONG_HISTORY_PRICE_BASES,
    LONG_HISTORY_PROVIDER,
    MODELS,
    SCENARIOS,
    ENGINE_VERSION,
    PACKAGE_VERSION,
)
from ..data_quality import _analysis_live_price, _normalize_price_data
from ..engine import build_monte_carlo_lab
from .common import _build_form_defaults, _render_executive_strip, _ui_segmented_control, _ui_toggle
from .views import (
    _render_models_calibration,
    _render_overview,
    _render_path_barriers,
    _render_tail_risk,
    _render_options_risk_neutral,
    _render_options_volatility_surface,
    _render_calibration_dataset_governance,
    _render_heston_calibration,
    _render_bates_calibration,
    _render_heston_q_simulation,
    _render_bates_q_simulation,
    _render_model_risk_numerical_governance,
    _render_tail_event_stress,
    _render_parameter_model_uncertainty,
    _render_governance_audit,
    _render_walk_forward_validation,
    _render_validated_ensemble,
)


def _calibration_window_label(value: int | None) -> str:
    if value is None:
        return "Maximum available"
    mapping = {
        126: "6M / 126 returns",
        252: "1Y / 252 returns",
        756: "3Y / 756 returns",
        1260: "5Y / 1,260 returns",
        2520: "10Y / 2,520 returns",
    }
    return mapping.get(value, f"Last {value:,} returns")


def _source_mode_label(value: str) -> str:
    return {
        "auto": "Automatic priority",
        "display": "Display sample only",
        "explicit": "Application-supplied history",
        "uploaded": "Uploaded file override",
        "provider": "Automatic provider history",
    }.get(value, value)




def _invalidate_versioned_session_state(ticker: str) -> None:
    """Discard cached analytical results created by an older package version."""
    signature_key = f"mc_runtime_signature_{ticker}"
    current = f"{PACKAGE_VERSION}|{ENGINE_VERSION}"
    previous = st.session_state.get(signature_key)
    if previous == current:
        return
    result_prefixes = (
        "mc_v221c_result_",
        "mc_v221c_config_",
        "mc_v221c_walk_forward_result_",
        "mc_v222_ensemble_result_",
        "mc_v231_tail_event_result_",
        "mc_v240_uncertainty_result_",
        "mc_v251_options_result_",
        "mc_v252_surface_result_",
        "mc_v254_surface_result_",
        "mc_v255_calibration_dataset_result_",
        "mc_v260_heston_result_",
        "mc_v260a_heston_result_",
        "mc_v261_heston_sim_result_",
        "mc_v261a_heston_sim_result_",
        "mc_v270_bates_result_",
        "mc_v270a_bates_result_",
        "mc_v271_bates_sim_result_",
        "mc_v280_model_risk_result_",
        "mc_v280_model_risk_history_",
    )
    suffix = f"_{ticker}"
    for key in list(st.session_state.keys()):
        text = str(key)
        if text.endswith(suffix) and text.startswith(result_prefixes):
            del st.session_state[key]
    st.session_state[signature_key] = current

def render_monte_carlo_advanced_lab(
    ticker: str,
    price_data: pd.DataFrame,
    analysis: Dict[str, Any] | None = None,
    calibration_data: pd.DataFrame | None = None,
) -> None:
    """Institutional Streamlit renderer. The original three-argument call remains valid."""
    _invalidate_versioned_session_state(str(ticker))
    st.subheader(f"Monte Carlo Risk & Scenario Engine — {ticker}")
    st.caption(
        "Forward-risk distributions under explicit drift, volatility, conditional-model and barrier assumptions. "
        "Simulation propagates assumptions; it does not infer alpha by itself."
    )

    defaults_key = f"mc_v221c_defaults_{ticker}"
    result_key = f"mc_v221c_result_{ticker}"
    config_key = f"mc_v221c_config_{ticker}"

    if defaults_key not in st.session_state:
        st.session_state[defaults_key] = _build_form_defaults(ticker)
    defaults = st.session_state[defaults_key]
    if defaults.get("model") not in MODELS:
        defaults["model"] = "GBM normal"

    uploaded_file = None
    with st.form(key=f"mc_v221c_form_{ticker}", border=True):
        row1 = st.columns([1.05, 1.05, 1.45, 0.65])
        with row1[0]:
            simulations_options = [1_000, 3_000, 5_000, 10_000, 25_000]
            default_sims = defaults["simulations"] if defaults["simulations"] in simulations_options else 3_000
            simulations = st.selectbox("Primary paths", simulations_options, index=simulations_options.index(default_sims))
        with row1[1]:
            scenario = st.selectbox("Scenario overlay", list(SCENARIOS), index=list(SCENARIOS).index(defaults["scenario"]))
        with row1[2]:
            model = st.selectbox("Simulation engine", list(MODELS), index=list(MODELS).index(defaults["model"]))
        with row1[3]:
            seed = st.number_input("Seed", min_value=1, max_value=999_999, value=int(defaults["seed"]), step=1)

        barrier_capabilities = barrier_monitoring_capabilities(model)
        row2 = st.columns([1.25, 0.85, 0.9, 1.0])
        with row2[0]:
            barrier_options = list(barrier_capabilities["options"])
            default_barrier = defaults.get("barrier_monitoring", barrier_capabilities["default"])
            if default_barrier not in barrier_options:
                default_barrier = barrier_capabilities["default"]
            barrier_monitoring = st.selectbox(
                "Barrier monitoring",
                barrier_options,
                index=barrier_options.index(default_barrier),
            )
            st.caption(barrier_capabilities["explanation"])
        with row2[1]:
            confidence_options = [0.90, 0.95, 0.99]
            confidence_level = st.selectbox(
                "Confidence",
                confidence_options,
                index=confidence_options.index(defaults["confidence_level"]),
                format_func=lambda x: f"{x:.0%}",
            )
        with row2[2]:
            matrix_options = [500, 1_000, 2_000, 3_000, 5_000]
            default_matrix = defaults["matrix_simulations"] if defaults["matrix_simulations"] in matrix_options else 2_000
            matrix_simulations = st.selectbox("Matrix paths", matrix_options, index=matrix_options.index(default_matrix))
        with row2[3]:
            level_mode = st.selectbox("Barrier levels", ["Automatique ATR/structure", "Personnalisé"], index=0)

        custom_levels: Dict[str, float] | None = None
        if level_mode == "Personnalisé":
            normalized, _ = _normalize_price_data(price_data)
            fallback_price = float(normalized["close"].iloc[-1]) if not normalized.empty else 100.0
            live_price, _ = _analysis_live_price(analysis or {}, fallback_price)
            level_cols = st.columns(4)
            stop_structural = level_cols[0].number_input("Structural stop", min_value=0.01, value=float(live_price * 0.88), step=0.01)
            stop_short = level_cols[1].number_input("Short stop", min_value=0.01, value=float(live_price * 0.94), step=0.01)
            target_1 = level_cols[2].number_input("Target 1", min_value=0.01, value=float(live_price * 1.06), step=0.01)
            target_2 = level_cols[3].number_input("Target 2", min_value=0.01, value=float(live_price * 1.15), step=0.01)
            custom_levels = {
                "stop_structural": stop_structural,
                "stop_short": stop_short,
                "target_1": target_1,
                "target_2": target_2,
            }

        with st.expander("Advanced calibration controls", expanded=False):
            source_cols = st.columns([1.0, 1.0, 1.4])
            source_modes = ["auto", "provider", "display", "explicit", "uploaded"]
            default_source = defaults.get("calibration_source_mode", "auto")
            if default_source not in source_modes:
                default_source = "auto"
            calibration_source_mode = source_cols[0].selectbox(
                "Calibration source",
                source_modes,
                index=source_modes.index(default_source),
                format_func=_source_mode_label,
            )
            calibration_options: list[int | None] = [None, 126, 252, 756, 1260, 2520]
            default_window = defaults.get("calibration_window")
            if default_window not in calibration_options:
                default_window = None
            calibration_window = source_cols[1].selectbox(
                "Calibration window",
                calibration_options,
                index=calibration_options.index(default_window),
                format_func=_calibration_window_label,
            )
            uploader = getattr(st, "file_uploader", None)
            if callable(uploader):
                uploaded_file = source_cols[2].file_uploader(
                    "Calibration CSV override",
                    type=["csv"],
                    accept_multiple_files=False,
                    help="Expected columns: date and close. OHLCV columns are also accepted.",
                )
            else:
                source_cols[2].caption("CSV upload unavailable in this Streamlit runtime.")

            provider_cols = st.columns([0.9, 0.9, 0.9, 0.9, 0.8])
            provider_enabled = provider_cols[0].checkbox(
                "Automatic long history",
                value=bool(defaults.get("provider_enabled", True)),
                help="Fetches a cached long daily history only when upload/application history has not already won the source priority.",
            )
            provider_period = provider_cols[1].selectbox(
                "Provider history",
                list(LONG_HISTORY_PERIODS),
                index=list(LONG_HISTORY_PERIODS).index(defaults.get("provider_period", DEFAULT_LONG_HISTORY_PERIOD))
                if defaults.get("provider_period", DEFAULT_LONG_HISTORY_PERIOD) in LONG_HISTORY_PERIODS else 1,
                format_func=lambda value: {"5y": "5 years", "10y": "10 years", "max": "Maximum"}.get(value, value),
            )
            provider_price_basis = provider_cols[2].selectbox(
                "Corporate-action basis",
                list(LONG_HISTORY_PRICE_BASES),
                index=list(LONG_HISTORY_PRICE_BASES).index(defaults.get("provider_price_basis", "adjusted"))
                if defaults.get("provider_price_basis", "adjusted") in LONG_HISTORY_PRICE_BASES else 0,
                format_func=lambda value: "Adjusted OHLC" if value == "adjusted" else "Raw OHLC",
            )
            ttl_options = [1, 6, 12, 24, 72]
            default_ttl = int(defaults.get("provider_cache_ttl_hours", DEFAULT_LONG_HISTORY_CACHE_TTL_HOURS))
            if default_ttl not in ttl_options:
                default_ttl = DEFAULT_LONG_HISTORY_CACHE_TTL_HOURS
            provider_cache_ttl_hours = provider_cols[3].selectbox(
                "Cache TTL", ttl_options, index=ttl_options.index(default_ttl), format_func=lambda value: f"{value}h"
            )
            provider_force_refresh = provider_cols[4].checkbox(
                "Refresh now", value=False, help="Bypasses a fresh cache for this run only."
            )

            advanced_cols = st.columns(3)
            mean_block_length = advanced_cols[0].number_input(
                "Stationary bootstrap mean block length",
                min_value=2,
                max_value=60,
                value=int(defaults["mean_block_length"]),
                step=1,
            )
            ewma_lambda = advanced_cols[1].number_input(
                "EWMA lambda",
                min_value=0.50,
                max_value=0.999,
                value=float(defaults["ewma_lambda"]),
                step=0.005,
                format="%.3f",
            )
            stability_check = advanced_cols[2].checkbox(
                "Conditional parameter stability check",
                value=bool(defaults.get("stability_check", True)),
            )

            garch_cols = st.columns(3)
            garch_maxiter_options = [300, 500, 800, 1_200, 2_000]
            garch_maxiter = garch_cols[0].selectbox(
                "GARCH optimizer max iterations",
                garch_maxiter_options,
                index=garch_maxiter_options.index(defaults.get("garch_maxiter", 800)),
            )
            garch_min_options = [80, 120, 180, 252, 500]
            garch_min_observations = garch_cols[1].selectbox(
                "Minimum GARCH observations",
                garch_min_options,
                index=garch_min_options.index(defaults.get("garch_min_observations", 120)),
            )
            ruin_threshold_pct = garch_cols[2].number_input(
                "Ruin threshold (%)",
                min_value=-95.0,
                max_value=-1.0,
                value=float(defaults["ruin_threshold"] * 100.0),
                step=1.0,
            )

            explicit_rows = len(calibration_data) if isinstance(calibration_data, pd.DataFrame) else 0
            st.caption(
                f"Display rows: {len(price_data):,} · application-supplied calibration rows: {explicit_rows:,}. "
                "Automatic mode prefers upload, application history, cached/provider history, recognized analysis history, then display data."
            )

        submitted = st.form_submit_button("Run long-history calibration & eligibility simulation", use_container_width=True, type="primary")

    uploaded_calibration_data = None
    upload_error = None
    if uploaded_file is not None:
        uploaded_calibration_data, upload_error = parse_uploaded_calibration_file(uploaded_file)
        if upload_error:
            st.warning(upload_error)

    requested_config = {
        "simulations": int(simulations),
        "matrix_simulations": int(min(matrix_simulations, simulations)),
        "scenario": scenario,
        "model": model,
        "seed": int(seed),
        "barrier_monitoring": barrier_monitoring,
        "confidence_level": float(confidence_level),
        "mean_block_length": int(mean_block_length),
        "ewma_lambda": float(ewma_lambda),
        "ruin_threshold": float(ruin_threshold_pct / 100.0),
        "calibration_window": calibration_window,
        "calibration_source_mode": calibration_source_mode,
        "garch_maxiter": int(garch_maxiter),
        "garch_min_observations": int(garch_min_observations),
        "stability_check": bool(stability_check),
        "provider_enabled": bool(provider_enabled),
        "provider_name": LONG_HISTORY_PROVIDER,
        "provider_period": str(provider_period),
        "provider_price_basis": str(provider_price_basis),
        "provider_cache_ttl_hours": int(provider_cache_ttl_hours),
        "provider_force_refresh": bool(provider_force_refresh),
        "level_mode": level_mode,
        "custom_levels": custom_levels,
        "upload_name": str(getattr(uploaded_file, "name", "")) if uploaded_file is not None else "",
    }

    should_run = submitted or result_key not in st.session_state
    if should_run and not upload_error:
        provider_calibration_data = None
        provider_report: Dict[str, Any] = {
            "provider": requested_config["provider_name"],
            "status": "DISABLED",
            "ok": False,
            "warnings": [],
        }
        higher_priority_available = uploaded_calibration_data is not None or (
            isinstance(calibration_data, pd.DataFrame) and not calibration_data.empty
        )
        should_fetch_provider = (
            requested_config["provider_enabled"]
            and requested_config["calibration_source_mode"] in {"auto", "provider"}
            and not (requested_config["calibration_source_mode"] == "auto" and higher_priority_available)
        )
        if should_fetch_provider:
            with st.spinner("Fetching or resolving cached long-history provider data…"):
                provider_calibration_data, provider_report = fetch_long_history(
                    ticker=ticker,
                    period=requested_config["provider_period"],
                    provider=requested_config["provider_name"],
                    price_basis=requested_config["provider_price_basis"],
                    cache_ttl_hours=requested_config["provider_cache_ttl_hours"],
                    force_refresh=requested_config["provider_force_refresh"],
                )
        elif requested_config["provider_enabled"] and higher_priority_available:
            provider_report.update({"status": "SKIPPED_HIGHER_PRIORITY", "ok": True})

        with st.spinner("Resolving calibration/validation histories, fitting eligibility diagnostics and simulating nested horizons…"):
            lab = build_monte_carlo_lab(
                ticker=ticker,
                price_data=price_data,
                analysis=analysis or {},
                simulations=requested_config["simulations"],
                scenario=requested_config["scenario"],
                model=requested_config["model"],
                seed=requested_config["seed"],
                matrix_simulations=requested_config["matrix_simulations"],
                barrier_monitoring=requested_config["barrier_monitoring"],
                confidence_level=requested_config["confidence_level"],
                mean_block_length=requested_config["mean_block_length"],
                ewma_lambda=requested_config["ewma_lambda"],
                ruin_threshold=requested_config["ruin_threshold"],
                custom_levels=requested_config["custom_levels"],
                calibration_data=calibration_data,
                calibration_window=requested_config["calibration_window"],
                calibration_source_mode=requested_config["calibration_source_mode"],
                uploaded_calibration_data=uploaded_calibration_data,
                provider_calibration_data=provider_calibration_data,
                provider_report=provider_report,
                provider_name=requested_config["provider_name"],
                provider_period=requested_config["provider_period"],
                provider_cache_ttl_hours=requested_config["provider_cache_ttl_hours"],
                provider_price_basis=requested_config["provider_price_basis"],
                provider_enabled=requested_config["provider_enabled"],
                garch_maxiter=requested_config["garch_maxiter"],
                garch_min_observations=requested_config["garch_min_observations"],
                stability_check=requested_config["stability_check"],
            )
        st.session_state[result_key] = lab
        st.session_state[config_key] = requested_config
        defaults.update({key: value for key, value in requested_config.items() if key in defaults})
        st.session_state[defaults_key] = defaults

    lab = st.session_state.get(result_key)
    if not isinstance(lab, Mapping) or not lab.get("ok"):
        reason = lab.get("reason", "Monte Carlo engine unavailable.") if isinstance(lab, Mapping) else "Monte Carlo engine unavailable."
        st.error(reason)
        return

    active_config = st.session_state.get(config_key, requested_config)
    if active_config != requested_config and not submitted:
        st.info("Controls were modified. Press ‘Run long-history calibration & eligibility simulation’ to apply the new configuration.")

    header_cols = st.columns([0.8, 0.8, 0.8, 1.8])
    with header_cols[0]:
        horizon = _ui_segmented_control(
            "Horizon",
            options=list(DEFAULT_HORIZONS),
            default=30,
            format_func=lambda value: f"{value}D",
            key=f"mc_v221c_horizon_{ticker}",
        )
        if horizon is None:
            horizon = 30
    with header_cols[1]:
        show_paths = _ui_toggle("Sample paths", value=False, key=f"mc_v221c_show_paths_{ticker}")
    with header_cols[2]:
        visible_paths = st.selectbox("Visible paths", [0, 5, 10, 20], index=1, key=f"mc_v221c_visible_paths_{ticker}")
    with header_cols[3]:
        st.caption(
            f"Engine {lab['engine_version']} · Config {lab['configuration_signature']} · "
            f"Primary {lab['settings']['simulations']:,} paths · Matrix {lab['settings']['matrix_simulations']:,} paths · "
            f"Calibration {lab['base']['calibration_observations']:,} returns from {lab['base']['calibration_source']} · "
            f"Validation {lab['base'].get('validation_observations', lab['base']['calibration_observations']):,} returns · "
            f"Provider {lab.get('provider_report', {}).get('status', 'NOT_RUN')} · "
            f"Barrier {lab['settings']['effective_barrier_monitoring']}"
        )

    _render_executive_strip(lab, int(horizon))

    overview_tab, models_tab, paths_tab, tail_tab, options_tab, surface_tab, dataset_tab, heston_tab, bates_tab, heston_sim_tab, bates_sim_tab, model_risk_tab, tail_event_tab, uncertainty_tab, validation_tab, ensemble_tab, governance_tab = st.tabs(
        [
            "Overview",
            "Models & Calibration",
            "Path & Barriers",
            "Tail Risk",
            "Options-Implied / Risk-Neutral",
            "Volatility Surface",
            "Calibration Dataset",
            "Heston Calibration",
            "Bates Calibration",
            "Heston Q Simulation",
            "Bates Q Simulation",
            "Model Risk & Numerical Governance",
            "Tail & Event Stress",
            "Parameter & Model Uncertainty",
            "Walk-Forward Validation",
            "Validated Ensemble",
            "Governance & Audit",
        ]
    )
    with overview_tab:
        _render_overview(lab, int(horizon), bool(show_paths), int(visible_paths))
    with models_tab:
        _render_models_calibration(lab, int(horizon))
    with paths_tab:
        _render_path_barriers(lab, int(horizon), bool(show_paths), int(visible_paths))
    with tail_tab:
        _render_tail_risk(lab, int(horizon))
    with options_tab:
        _render_options_risk_neutral(lab, int(horizon))
    with surface_tab:
        _render_options_volatility_surface(lab, int(horizon))
    with dataset_tab:
        _render_calibration_dataset_governance(lab, int(horizon))
    with heston_tab:
        _render_heston_calibration(lab, int(horizon))
    with bates_tab:
        _render_bates_calibration(lab, int(horizon))
    with heston_sim_tab:
        _render_heston_q_simulation(lab, int(horizon))
    with bates_sim_tab:
        _render_bates_q_simulation(lab, int(horizon))
    with model_risk_tab:
        _render_model_risk_numerical_governance(lab, int(horizon))
    with tail_event_tab:
        _render_tail_event_stress(lab, int(horizon))
    with uncertainty_tab:
        _render_parameter_model_uncertainty(lab, int(horizon))
    with validation_tab:
        _render_walk_forward_validation(lab, int(horizon))
    with ensemble_tab:
        _render_validated_ensemble(lab, int(horizon))
    with governance_tab:
        _render_governance_audit(lab, int(horizon))
