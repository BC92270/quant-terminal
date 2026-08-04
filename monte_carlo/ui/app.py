from __future__ import annotations

from typing import Any, Dict, Mapping

import pandas as pd
import streamlit as st

from ..config import DEFAULT_CONFIDENCE, DEFAULT_HORIZONS, MODELS, SCENARIOS
from ..data_quality import _analysis_live_price, _normalize_price_data
from ..engine import build_monte_carlo_lab
from .common import (_build_form_defaults, _render_executive_strip, _ui_segmented_control, _ui_toggle)
from .views import (_render_models_calibration, _render_overview, _render_path_barriers,
                    _render_tail_risk, _render_validation_audit)

def render_monte_carlo_advanced_lab(
    ticker: str,
    price_data: pd.DataFrame,
    analysis: Dict[str, Any] | None = None,
) -> None:
    """Institutional Streamlit renderer. Public signature preserved."""
    st.subheader(f"Monte Carlo Risk & Scenario Engine — {ticker}")
    st.caption(
        "Forward-risk distributions under explicit model, scenario, calibration and barrier assumptions. "
        "This module does not infer alpha from simulation alone."
    )

    defaults_key = f"mc_v21_defaults_{ticker}"
    result_key = f"mc_v21_result_{ticker}"
    config_key = f"mc_v21_config_{ticker}"

    if defaults_key not in st.session_state:
        st.session_state[defaults_key] = _build_form_defaults(ticker)
    defaults = st.session_state[defaults_key]

    with st.form(key=f"mc_v21_form_{ticker}", border=True):
        row1 = st.columns([1.15, 1.15, 1.40, 0.75])
        with row1[0]:
            simulations = st.selectbox(
                "Primary paths",
                [1_000, 3_000, 5_000, 10_000, 25_000],
                index=[1_000, 3_000, 5_000, 10_000, 25_000].index(defaults["simulations"]),
            )
        with row1[1]:
            scenario = st.selectbox("Scenario", list(SCENARIOS), index=list(SCENARIOS).index(defaults["scenario"]))
        with row1[2]:
            model = st.selectbox("Simulation engine", list(MODELS), index=list(MODELS).index(defaults["model"]))
        with row1[3]:
            seed = st.number_input("Seed", min_value=1, max_value=999_999, value=int(defaults["seed"]), step=1)

        row2 = st.columns([1.35, 1.0, 1.0, 1.0])
        with row2[0]:
            barrier_monitoring = st.selectbox(
                "Barrier monitoring",
                ["Brownian bridge (GBM)", "Clôture de chaque pas"],
                index=["Brownian bridge (GBM)", "Clôture de chaque pas"].index(defaults["barrier_monitoring"]),
            )
        with row2[1]:
            confidence_level = st.selectbox("Confidence", [0.90, 0.95, 0.99], index=[0.90, 0.95, 0.99].index(defaults["confidence_level"]), format_func=lambda x: f"{x:.0%}")
        with row2[2]:
            matrix_simulations = st.selectbox(
                "Matrix paths",
                [500, 1_000, 2_000, 3_000, 5_000],
                index=[500, 1_000, 2_000, 3_000, 5_000].index(defaults["matrix_simulations"]),
            )
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
            ruin_threshold_pct = advanced_cols[2].number_input(
                "Ruin threshold (%)",
                min_value=-95.0,
                max_value=-1.0,
                value=float(defaults["ruin_threshold"] * 100.0),
                step=1.0,
            )

        submitted = st.form_submit_button("Run institutional simulation", use_container_width=True, type="primary")

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
        "level_mode": level_mode,
        "custom_levels": custom_levels,
    }

    should_run = submitted or result_key not in st.session_state
    if should_run:
        with st.spinner("Calibrating models and simulating nested horizons…"):
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
        st.info("Controls were modified. Press ‘Run institutional simulation’ to apply the new configuration.")

    header_cols = st.columns([0.8, 0.8, 0.8, 1.6])
    with header_cols[0]:
        horizon = _ui_segmented_control(
            "Horizon",
            options=list(DEFAULT_HORIZONS),
            default=30,
            format_func=lambda value: f"{value}D",
            key=f"mc_v21_horizon_{ticker}",
        )
        if horizon is None:
            horizon = 30
    with header_cols[1]:
        show_paths = _ui_toggle("Sample paths", value=False, key=f"mc_v21_show_paths_{ticker}")
    with header_cols[2]:
        visible_paths = st.selectbox("Visible paths", [0, 5, 10, 20], index=1, key=f"mc_v21_visible_paths_{ticker}")
    with header_cols[3]:
        st.caption(
            f"Engine {lab['engine_version']} · Config {lab['configuration_signature']} · "
            f"Primary {lab['settings']['simulations']:,} paths · Matrix {lab['settings']['matrix_simulations']:,} paths · "
            f"Price source {lab['base']['price_source']}"
        )

    _render_executive_strip(lab, int(horizon))

    overview_tab, models_tab, paths_tab, tail_tab, validation_tab = st.tabs(
        [
            "Overview",
            "Models & Calibration",
            "Path & Barriers",
            "Tail Risk",
            "Validation & Audit",
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
    with validation_tab:
        _render_validation_audit(lab, int(horizon))
