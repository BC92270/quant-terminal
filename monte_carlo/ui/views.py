from __future__ import annotations

from typing import Any, Mapping

import json
import numpy as np
import pandas as pd
import streamlit as st

from ..config import MODELS, SCENARIOS, VALIDATION_HORIZONS
from ..utils import _jsonable, _number, _pct, _pp, _rate_delta_pp
from ..walk_forward import build_walk_forward_validation
from ..ensemble import ENSEMBLE_WEIGHTING_METHODS, build_validated_ensemble
from ..uncertainty import (
    UNCERTAINTY_WEIGHTING_METHODS,
    build_parameter_model_uncertainty,
)
from ..tail_event import (
    TAIL_EVENT_STRESS_TYPES,
    build_tail_event_stress,
    historical_event_library,
)
from ..options_risk_neutral import (
    OPTIONS_CACHE_TTL_HOURS,
    build_options_risk_neutral_lab,
    fetch_option_chain,
    list_option_expirations,
    normalize_option_chain,
    parse_option_chain_csv,
)
from ..options_surface import (
    OPTIONS_SURFACE_VERSION,
    SURFACE_TARGET_DAYS,
    build_multi_expiry_surface,
    fetch_option_surface_chains,
    select_surface_expirations,
)
from ..heston_calibration import (
    HESTON_CALIBRATION_VERSION,
    HESTON_OBJECTIVES,
    FELLER_POLICIES,
    calibrate_heston,
)
from ..heston_simulation import (
    HESTON_SIMULATION_VERSION,
    HESTON_SIMULATION_SCHEMES,
    build_heston_q_simulation,
)
from ..bates_calibration import (
    BATES_CALIBRATION_VERSION,
    BATES_CHAMPION_STATUSES,
    calibrate_bates,
)
from ..bates_simulation import (
    BATES_SIMULATION_VERSION,
    BATES_SIMULATION_SCHEMES,
    build_bates_q_simulation,
)
from ..model_risk import (
    MODEL_RISK_VERSION,
    build_model_risk_governance,
)
from ..calibration_dataset import (
    CALIBRATION_DATASET_VERSION,
    EVENT_POLICIES,
    HOLDOUT_POLICIES,
    WEIGHTING_METHODS,
    build_calibration_dataset,
)
from .charts import (
    _plot_barrier_race,
    _plot_convergence,
    _plot_exceedance_curve,
    _plot_fan_chart,
    _plot_matrix_heatmap,
    _plot_terminal_distribution,
    _plot_time_to_hit,
    _plot_validation_leaderboard,
    _plot_pit_histogram,
    _plot_quantile_calibration,
    _plot_var_exception_timeline,
    _plot_reliability,
    _plot_ensemble_weights,
    _plot_ensemble_member_dispersion,
    _plot_evt_threshold_stability,
    _plot_stress_distribution_comparison,
    _plot_stress_delta,
    _plot_uncertainty_decomposition,
    _plot_uncertainty_distribution,
    _plot_uncertainty_parameter_intervals,
    _plot_uncertainty_convergence,
    _plot_option_call_projection,
    _plot_risk_neutral_density,
    _plot_implied_volatility_smile,
    _plot_physical_vs_risk_neutral,
    _plot_volatility_surface,
    _plot_surface_smile_slices,
    _plot_surface_term_structure,
    _plot_surface_calendar_adjustment,
    _plot_calibration_weight_matrix,
    _plot_calibration_dataset_coverage,
    _plot_event_variance_adjustments,
    _plot_heston_fit_smiles,
    _plot_heston_residual_heatmap,
    _plot_heston_multistart,
    _plot_heston_parameter_position,
    _plot_heston_q_spot_fan,
    _plot_heston_q_variance_fan,
    _plot_heston_q_terminal_distribution,
    _plot_heston_mc_fourier_prices,
    _plot_heston_mc_iv_residuals,
    _plot_heston_simulation_convergence,
    _plot_bates_fit_smiles,
    _plot_bates_residual_heatmap,
    _plot_bates_multistart,
    _plot_bates_champion_comparison,
    _plot_bates_jump_parameter_position,
    _plot_bates_q_spot_fan,
    _plot_bates_jump_process,
    _plot_bates_terminal_comparison,
    _plot_bates_mc_fourier_prices,
    _plot_bates_mc_iv_residuals,
    _plot_bates_risk_comparison,
    _plot_bates_convergence,
    _plot_model_risk_parameter_intervals,
    _plot_model_risk_correlation,
    _plot_model_risk_cost_profiles,
    _plot_model_risk_maturity_sensitivity,
    _plot_model_risk_bootstrap_selection,
)
from .common import (
    _calibration_table,
    _conditional_calibration_display,
    _eligibility_display,
    _quality_table,
    _render_level_table,
    _render_orange_warning,
    _summary_table,
)



_BATES_COMPARISON_RATE_METRICS = {
    "mean_return",
    "median_return",
    "var_5",
    "es_5",
    "var_1",
    "es_1",
    "prob_below_spot",
}
_BATES_COMPARISON_SPOT_METRICS = {"forward", "terminal_mean", "terminal_median"}
_BATES_COMPARISON_SHAPE_METRICS = {"skewness", "excess_kurtosis"}


def _bates_role_labels(champion_status: Any) -> dict[str, str]:
    status = str(champion_status or "UNKNOWN").upper()
    if status == "BATES_CHAMPION":
        return {
            "short": "champion",
            "noun": "Bates champion",
            "comparison_title": "Heston benchmark versus Bates champion",
            "caption": "The governed Bates champion is simulated under Q",
        }
    if status == "BATES_RESEARCH_ONLY":
        return {
            "short": "research challenger",
            "noun": "Bates research challenger",
            "comparison_title": "Heston benchmark versus Bates research challenger",
            "caption": "The Bates research challenger is simulated under Q",
        }
    if status == "HESTON_CHAMPION":
        return {
            "short": "challenger",
            "noun": "Bates challenger",
            "comparison_title": "Heston champion versus Bates challenger",
            "caption": "The Bates challenger is simulated under Q",
        }
    return {
        "short": "challenger",
        "noun": "Bates challenger",
        "comparison_title": "Heston benchmark versus Bates challenger",
        "caption": "The Bates challenger is simulated under Q",
    }


def _model_risk_role_label(role: Any) -> str:
    mapping = {
        "BATES_CHAMPION": "Bates production champion",
        "BATES_CHAMPION_WITH_MODEL_RISK_RESERVES": "Bates preferred — model-risk reserves",
        "HESTON_CHAMPION": "Heston production champion",
        "NO_PRODUCTION_CHAMPION": "Research only — no production champion",
        "NO_PRODUCTION_MODEL": "Ineligible — no production model",
    }
    value = str(role or "UNKNOWN").upper()
    return mapping.get(value, value.replace("_", " ").title())


def _model_risk_status_label(status: Any) -> str:
    mapping = {
        "PRODUCTION_ELIGIBLE": "Production eligible",
        "RESEARCH_ONLY": "Research only",
        "INELIGIBLE": "Ineligible",
        "FAILED": "Failed",
    }
    value = str(status or "UNKNOWN").upper()
    return mapping.get(value, value.replace("_", " ").title())


def _comparison_metric_suffix(column: str) -> str:
    value = str(column)
    for prefix in ("bates_", "heston_", "delta_"):
        if value.startswith(prefix):
            return value[len(prefix):]
    return value


def _format_heston_bates_comparison_table(frame: pd.DataFrame) -> pd.DataFrame:
    """Apply explicit units; never infer rates from loose substrings."""
    output = frame.copy()
    for column in output.columns:
        suffix = _comparison_metric_suffix(str(column))
        if suffix in _BATES_COMPARISON_RATE_METRICS:
            output[column] = output[column].astype(object)
            output[column] = output[column].map(lambda value, signed=str(column).startswith("delta_"): _pct(value, signed=signed))
        elif suffix in _BATES_COMPARISON_SPOT_METRICS:
            output[column] = output[column].astype(object)
            output[column] = output[column].map(lambda value: _number(value, 2))
        elif suffix in _BATES_COMPARISON_SHAPE_METRICS:
            output[column] = output[column].astype(object)
            output[column] = output[column].map(lambda value: _number(value, 4))
    return output


def _bates_research_reason(result: Mapping[str, Any], calibration: Mapping[str, Any] | None) -> str:
    reason = str(result.get("bates_champion_reason", "")).strip()
    if reason:
        return reason
    if isinstance(calibration, Mapping):
        notes = calibration.get("champion_notes")
        if isinstance(notes, (list, tuple)):
            clean = [str(value).strip() for value in notes if str(value).strip()]
            if clean:
                return " ".join(clean[:3])
    return "The source champion gate did not approve Bates as the production Q model."


def _render_overview(lab: Mapping[str, Any], horizon: int, show_paths: bool, visible_paths: int) -> None:
    summary = lab["summaries_by_horizon"][horizon]
    left, right = st.columns([2.15, 1.0])
    with left:
        st.plotly_chart(
            _plot_fan_chart(lab, horizon, show_paths, visible_paths),
            use_container_width=True,
            key=f"mc_v221c_overview_fan_{lab['ticker']}_{lab['configuration_signature']}_{horizon}",
        )
    with right:
        st.markdown("#### Risk ladder")
        _render_level_table(lab)
        st.markdown("#### Distribution statistics")
        statistics = [
            {"Metric": "Expected return", "Value": _pct(summary["expected_return"], signed=True)},
            {"Metric": "Mean MCSE", "Value": _pct(summary["expected_return_mcse"])},
            {"Metric": "P(Return > 0)", "Value": f"{summary['prob_positive']:.2f}%"},
            {"Metric": "VaR 5%", "Value": _pct(summary["var_5"])},
            {"Metric": "ES 5%", "Value": _pct(summary["es_5"])},
            {"Metric": "Expected max drawdown", "Value": _pct(summary["expected_max_drawdown"])},
            {"Metric": "P(Drawdown > 20%)", "Value": f"{summary['prob_drawdown_gt_20']:.2f}%"},
            {"Metric": "P(Ruin threshold)", "Value": f"{summary['prob_ruin']:.2f}%"},
        ]
        if summary.get("initial_conditional_vol_ann") is not None:
            statistics.extend(
                [
                    {"Metric": "Initial conditional vol", "Value": _pct(summary.get("initial_conditional_vol_ann"))},
                    {"Metric": "Conditional persistence", "Value": _number(summary.get("persistence"), 4)},
                ]
            )
        st.dataframe(pd.DataFrame(statistics), use_container_width=True, hide_index=True)
        st.caption(f"Barrier monitoring: {summary['effective_monitoring']}")
        if summary.get("fallback_used"):
            st.error(f"Conditional model fallback: {summary.get('calibration_warning')}")

    left, right = st.columns(2)
    with left:
        st.plotly_chart(
            _plot_terminal_distribution(summary, lab["levels"]),
            use_container_width=True,
            key=f"mc_v221c_overview_distribution_{lab['ticker']}_{lab['configuration_signature']}_{horizon}",
        )
    with right:
        st.plotly_chart(
            _plot_barrier_race(summary),
            use_container_width=True,
            key=f"mc_v221c_overview_barrier_race_{lab['ticker']}_{lab['configuration_signature']}_{horizon}",
        )


def _render_models_calibration(lab: Mapping[str, Any], horizon: int) -> None:
    st.markdown("### Calibration and conditional-volatility diagnostics")
    st.dataframe(_calibration_table(lab), use_container_width=True, hide_index=True)

    conditional_display = _conditional_calibration_display(lab)
    st.markdown("#### GARCH / GJR calibration status")
    if conditional_display.empty:
        st.warning("Conditional-volatility calibration unavailable.")
    else:
        st.dataframe(conditional_display, use_container_width=True, hide_index=True, height=220)
        st.caption(
            "Persistence = alpha + beta for GARCH and alpha + beta + gamma/2 for GJR-GARCH. "
            "A failed fit is never silent: the simulation row is flagged as an EWMA-FHS fallback."
        )

    st.markdown("#### Model eligibility gate")
    eligibility_display = _eligibility_display(lab)
    if eligibility_display.empty:
        st.warning("Model eligibility diagnostics unavailable.")
    else:
        st.dataframe(eligibility_display, use_container_width=True, hide_index=True, height=330)
        st.caption(
            "ELIGIBLE models enter cross-model aggregation. WARNING, INELIGIBLE and FALLBACK models remain visible "
            "for research and governance but are excluded from the primary model range."
        )

    source_report = lab.get("calibration_source_report", {})
    with st.expander("Calibration source resolution", expanded=False):
        st.json(_jsonable(source_report))

    st.markdown("#### Model-risk matrix")
    control_1, control_2 = st.columns([1, 2])
    with control_1:
        metric = st.selectbox(
            "Heatmap metric",
            [
                "Expected return",
                "ES 5%",
                "Barrier asymmetry",
                "P(Target before stop)",
                "Expected max drawdown",
                "P(Ruin threshold)",
            ],
            key=f"mc_v221c_heatmap_metric_{lab['ticker']}",
        )
    with control_2:
        st.caption(
            "Rows are simulation engines; columns are scenario overlays. Common random numbers reduce "
            "comparison noise within each model. Stress volatility is no longer represented as a model. "
            "Eligibility does not hide rows; it controls aggregation and is shown in the full matrix."
        )

    st.plotly_chart(
        _plot_matrix_heatmap(lab["matrix_df"], horizon, metric),
        use_container_width=True,
        key=f"mc_v221c_model_heatmap_{lab['ticker']}_{lab['configuration_signature']}_{horizon}",
    )

    with st.expander("Full scenario matrix", expanded=False):
        st.dataframe(_summary_table(lab["matrix_df"]), use_container_width=True, hide_index=True, height=560)


def _render_path_barriers(lab: Mapping[str, Any], horizon: int, show_paths: bool, visible_paths: int) -> None:
    summary = lab["summaries_by_horizon"][horizon]
    st.plotly_chart(
        _plot_fan_chart(lab, horizon, show_paths, visible_paths),
        use_container_width=True,
        key=f"mc_v221c_path_fan_{lab['ticker']}_{lab['configuration_signature']}_{horizon}",
    )

    cols = st.columns(5)
    cols[0].metric("Barrier asymmetry", _pp(summary["barrier_asymmetry_pp"], signed=True))
    cols[1].metric("P(Touch short stop)", f"{summary['prob_hit_stop']:.2f}%")
    cols[2].metric("P(Touch target 1)", f"{summary['prob_hit_target_1']:.2f}%")
    cols[3].metric("Median stop day", _number(summary["median_stop_day"], 1))
    cols[4].metric("Median target day", _number(summary["median_target_day"], 1))

    left, right = st.columns(2)
    with left:
        st.plotly_chart(
            _plot_barrier_race(summary),
            use_container_width=True,
            key=f"mc_v221c_path_barrier_race_{lab['ticker']}_{lab['configuration_signature']}_{horizon}",
        )
    with right:
        st.plotly_chart(
            _plot_time_to_hit(summary),
            use_container_width=True,
            key=f"mc_v221c_path_time_to_hit_{lab['ticker']}_{lab['configuration_signature']}_{horizon}",
        )

    resolution = lab.get("barrier_monitoring_resolution", {})
    if resolution.get("forced"):
        st.warning(str(resolution.get("warning")))
    st.caption(
        f"Requested monitoring: {resolution.get('requested', summary.get('barrier_monitoring_requested'))} · "
        f"Effective monitoring: {summary.get('effective_monitoring')}"
    )


def _render_tail_risk(lab: Mapping[str, Any], horizon: int) -> None:
    summary = lab["summaries_by_horizon"][horizon]
    cols = st.columns(6)
    cols[0].metric("VaR 5%", _pct(summary["var_5"]))
    cols[1].metric("ES 5%", _pct(summary["es_5"]))
    cols[2].metric("VaR 1%", _pct(summary["var_1"]))
    cols[3].metric("ES 1%", _pct(summary["es_1"]))
    cols[4].metric("Skewness", _number(summary["skewness"]))
    cols[5].metric("Excess kurtosis", _number(summary["excess_kurtosis"]))

    left, right = st.columns(2)
    with left:
        st.plotly_chart(
            _plot_terminal_distribution(summary, lab["levels"]),
            use_container_width=True,
            key=f"mc_v221c_tail_distribution_{lab['ticker']}_{lab['configuration_signature']}_{horizon}",
        )
    with right:
        st.plotly_chart(
            _plot_exceedance_curve(summary),
            use_container_width=True,
            key=f"mc_v221c_tail_exceedance_{lab['ticker']}_{lab['configuration_signature']}_{horizon}",
        )

    tail_table = pd.DataFrame(
        [
            {
                "Metric": "ES 5%",
                "Estimate": _pct(summary["es_5"]),
                "MC interval": f"{_pct(summary['es_5_ci'][0])} → {_pct(summary['es_5_ci'][1])}",
                "Tail observations": summary["es_5_tail_count"],
            },
            {
                "Metric": "ES 1%",
                "Estimate": _pct(summary["es_1"]),
                "MC interval": f"{_pct(summary['es_1_ci'][0])} → {_pct(summary['es_1_ci'][1])}",
                "Tail observations": summary["es_1_tail_count"],
            },
            {
                "Metric": "Expected max drawdown",
                "Estimate": _pct(summary["expected_max_drawdown"]),
                "MC interval": "Path distribution",
                "Tail observations": summary["simulations"],
            },
            {
                "Metric": "95th-percentile adverse max drawdown",
                "Estimate": _pct(summary["max_drawdown_p95_loss"]),
                "MC interval": "Empirical path quantile",
                "Tail observations": summary["simulations"],
            },
        ]
    )
    st.dataframe(tail_table, use_container_width=True, hide_index=True)


def _render_governance_audit(lab: Mapping[str, Any], horizon: int) -> None:
    summary = lab["summaries_by_horizon"][horizon]
    st.markdown("### Monte Carlo convergence")
    convergence = summary["convergence"].copy()
    st.plotly_chart(
        _plot_convergence(convergence),
        use_container_width=True,
        key=f"mc_v221c_validation_convergence_{lab['ticker']}_{lab['configuration_signature']}_{horizon}",
    )

    display_convergence = convergence.copy()
    for column in ("Expected return", "Expected return MCSE", "VaR 5%", "ES 5%", "ES 5% CI low", "ES 5% CI high"):
        display_convergence[column] = display_convergence[column].map(_pct)
    for column in ("Target before stop", "Target CI low", "Target CI high"):
        display_convergence[column] = display_convergence[column].map(lambda x: f"{float(x):.2f}%")
    st.dataframe(display_convergence, use_container_width=True, hide_index=True)

    st.markdown("### Baseline VaR validation")
    validation = lab["baseline_validation"]
    if validation.get("ok"):
        validation_table = pd.DataFrame(
            [
                {"Test": "Observed exception rate", "Value": _pct(validation["exception_rate"]), "Reference": _pct(validation["expected_rate"])},
                {"Test": "Kupiec unconditional coverage", "Value": _number(validation["kupiec_p_value"], 4), "Reference": "p-value > 0.05"},
                {"Test": "Christoffersen independence", "Value": _number(validation["christoffersen_p_value"], 4), "Reference": "p-value > 0.05"},
                {"Test": "Conditional coverage", "Value": _number(validation["conditional_coverage_p_value"], 4), "Reference": "p-value > 0.05"},
                {"Test": "Backtest observations", "Value": str(validation["observations"]), "Reference": validation["method"]},
            ]
        )
        st.dataframe(validation_table, use_container_width=True, hide_index=True)
        st.caption(
            "This is retained as a simple Gaussian control benchmark. The dedicated walk-forward tab now provides model-specific distribution validation, PIT, CRPS, log-score, VaR/ES and barrier diagnostics."
        )
    else:
        st.warning(validation.get("reason", "VaR validation unavailable."))

    st.markdown("### Data and calibration quality")
    st.dataframe(_quality_table(lab), use_container_width=True, hide_index=True)

    st.markdown("### Model eligibility governance")
    st.dataframe(_eligibility_display(lab), use_container_width=True, hide_index=True, height=330)

    warnings = lab["base"]["quality"].get("warnings", [])
    if warnings:
        with st.expander("Quality warnings", expanded=True):
            for warning in warnings:
                _render_orange_warning(str(warning))

    st.markdown("### Governance record")
    governance = pd.DataFrame(
        [
            {"Field": "Engine version", "Value": lab["engine_version"]},
            {"Field": "Configuration signature", "Value": lab["configuration_signature"]},
            {"Field": "Selected simulations", "Value": str(lab["settings"]["simulations"])},
            {"Field": "Matrix simulations", "Value": str(lab["settings"]["matrix_simulations"])},
            {"Field": "Scenario", "Value": lab["settings"]["scenario"]},
            {"Field": "Model", "Value": lab["settings"]["model"]},
            {"Field": "Seed", "Value": str(lab["settings"]["seed"])},
            {"Field": "Calibration source mode", "Value": str(lab["settings"].get("calibration_source_mode"))},
            {"Field": "Calibration source", "Value": str(lab["base"].get("calibration_source"))},
            {"Field": "Calibration observations", "Value": str(lab["base"].get("calibration_observations"))},
            {"Field": "Validation source", "Value": str(lab["base"].get("validation_source"))},
            {"Field": "Validation observations", "Value": str(lab["base"].get("validation_observations"))},
            {"Field": "Provider status", "Value": str(lab.get("provider_report", {}).get("status", "NOT_RUN"))},
            {"Field": "Provider period", "Value": str(lab.get("provider_report", {}).get("period", "N/A"))},
            {"Field": "Provider last observation", "Value": str(lab.get("provider_report", {}).get("last_observation", "N/A"))},
            {"Field": "Selected eligibility", "Value": str(summary.get("eligibility_status"))},
            {"Field": "Eligible for aggregation", "Value": "YES" if summary.get("eligible_for_aggregation") else "NO"},
            {"Field": "GARCH max iterations", "Value": str(lab["settings"].get("garch_maxiter"))},
            {"Field": "Selected calibration status", "Value": str(summary.get("calibration_status"))},
            {"Field": "Fallback used", "Value": "YES" if summary.get("fallback_used") else "NO"},
            {"Field": "Barrier monitoring requested", "Value": lab["settings"]["barrier_monitoring"]},
            {"Field": "Barrier monitoring effective", "Value": lab["settings"]["effective_barrier_monitoring"]},
            {"Field": "Price source", "Value": lab["base"]["price_source"]},
            {"Field": "Measure", "Value": lab["assumptions"]["measure"]},
            {"Field": "Level source", "Value": lab["levels"]["source"]},
        ]
    )
    st.dataframe(governance, use_container_width=True, hide_index=True)

    options_state_key = f"mc_v251_options_result_{lab['ticker']}"
    options_result = st.session_state.get(options_state_key)
    if isinstance(options_result, Mapping) and options_result.get("ok"):
        st.markdown("### Options-implied / risk-neutral governance")
        rn = options_result.get("risk_neutral_metrics", {})
        options_governance = pd.DataFrame(
            [
                {"Field": "Options version", "Value": options_result.get("version")},
                {"Field": "Options signature", "Value": options_result.get("configuration_signature")},
                {"Field": "Status", "Value": options_result.get("status")},
                {"Field": "Source status", "Value": options_result.get("source_report", {}).get("status")},
                {"Field": "Valuation date", "Value": options_result.get("valuation_date")},
                {"Field": "Expiration", "Value": options_result.get("expiration")},
                {"Field": "Calendar days", "Value": options_result.get("calendar_days")},
                {"Field": "Forward", "Value": options_result.get("forward")},
                {"Field": "Contract style", "Value": options_result.get("contract_style")},
                {"Field": "Forward method", "Value": options_result.get("forward_report", {}).get("method")},
                {"Field": "Parity accepted", "Value": options_result.get("parity_accepted")},
                {"Field": "Effective carry", "Value": options_result.get("dividend_yield_effective")},
                {"Field": "Reliable OTM IV quotes", "Value": options_result.get("reliable_smile_quotes")},
                {"Field": "Model-free volatility", "Value": options_result.get("model_free_volatility")},
                {"Field": "Finite-strike density mass", "Value": options_result.get("raw_density_mass")},
                {"Field": "Projection status", "Value": options_result.get("projection_report", {}).get("status")},
                {"Field": "Q VaR 5%", "Value": rn.get("q_var_5")},
                {"Field": "Q ES 5%", "Value": rn.get("q_es_5")},
                {"Field": "Exercise-style governance", "Value": options_result.get("measure_governance", {}).get("exercise_style")},
                {"Field": "Measure prohibition", "Value": options_result.get("measure_governance", {}).get("prohibition")},
            ]
        )
        st.dataframe(options_governance, use_container_width=True, hide_index=True)
        with st.expander("Raw options/risk-neutral audit", expanded=False):
            raw_options = {
                "settings": options_result.get("settings", {}),
                "source_report": options_result.get("source_report", {}),
                "normalization_report": options_result.get("normalization_report", {}),
                "forward_report": options_result.get("forward_report", {}),
                "projection_report": options_result.get("projection_report", {}),
                "variance_report": options_result.get("variance_report", {}),
                "warnings": options_result.get("warnings", []),
                "measure_governance": options_result.get("measure_governance", {}),
            }
            st.json(_jsonable(raw_options))

    surface_state_key = f"mc_v254_surface_result_{lab['ticker']}"
    surface_result = st.session_state.get(surface_state_key)
    if isinstance(surface_result, Mapping) and surface_result.get("ok"):
        st.markdown("### Multi-expiry volatility-surface governance")
        surface_governance = pd.DataFrame(
            [
                {"Field": "Surface version", "Value": surface_result.get("version")},
                {"Field": "Surface signature", "Value": surface_result.get("configuration_signature")},
                {"Field": "Status", "Value": surface_result.get("status")},
                {"Field": "Usable expiries", "Value": surface_result.get("expiry_count")},
                {"Field": "Raw calendar violations", "Value": surface_result.get("raw_calendar_violations")},
                {"Field": "Projected calendar violations", "Value": surface_result.get("projected_calendar_violations")},
                {"Field": "Calendar adjustment RMSE", "Value": surface_result.get("calendar_adjustment_rmse")},
                {"Field": "Carry curve status", "Value": surface_result.get("carry_curve", {}).get("status")},
                {"Field": "Manual effective carry", "Value": surface_result.get("carry_curve", {}).get("manual_effective_carry")},
                {"Field": "Accepted parity anchors", "Value": surface_result.get("carry_curve", {}).get("accepted_candidates")},
                {"Field": "Potential event windows", "Value": surface_result.get("potential_event_windows")},
                {"Field": "Measure", "Value": surface_result.get("governance", {}).get("measure")},
                {"Field": "Exercise style", "Value": surface_result.get("governance", {}).get("exercise_style")},
                {"Field": "Carry curve", "Value": surface_result.get("governance", {}).get("carry_curve")},
                {"Field": "Event diagnostic", "Value": surface_result.get("governance", {}).get("event_diagnostic")},
                {"Field": "Butterfly control", "Value": surface_result.get("governance", {}).get("butterfly_control")},
                {"Field": "Measure prohibition", "Value": surface_result.get("governance", {}).get("prohibition")},
            ]
        )
        st.dataframe(surface_governance, use_container_width=True, hide_index=True)
        with st.expander("Raw volatility-surface audit", expanded=False):
            st.json(_jsonable({"settings": surface_result.get("settings"), "carry_curve": surface_result.get("carry_curve"), "source_reports": surface_result.get("source_reports"), "warnings": surface_result.get("warnings", [])}))

    dataset_state_key = f"mc_v255_calibration_dataset_result_{lab['ticker']}"
    dataset_result = st.session_state.get(dataset_state_key)
    if isinstance(dataset_result, Mapping) and dataset_result.get("ok"):
        st.markdown("### Heston/Bates calibration-dataset governance")
        dataset_governance = pd.DataFrame(
            [
                {"Field": "Dataset version", "Value": dataset_result.get("version")},
                {"Field": "Dataset signature", "Value": dataset_result.get("configuration_signature")},
                {"Field": "Status", "Value": dataset_result.get("status")},
                {"Field": "Training points", "Value": dataset_result.get("training_points")},
                {"Field": "Holdout points", "Value": dataset_result.get("holdout_points")},
                {"Field": "Training maturities", "Value": dataset_result.get("training_maturities")},
                {"Field": "Effective sample size", "Value": dataset_result.get("effective_sample_size")},
                {"Field": "Maximum quote weight", "Value": dataset_result.get("maximum_quote_weight")},
                {"Field": "Event policy", "Value": dataset_result.get("settings", {}).get("event_policy")},
                {"Field": "Event variance removed", "Value": dataset_result.get("event_variance_removed_total")},
                {"Field": "Measure", "Value": dataset_result.get("governance", {}).get("measure")},
            ]
        )
        st.dataframe(dataset_governance, use_container_width=True, hide_index=True)

    heston_state_key = f"mc_v260a_heston_result_{lab['ticker']}"
    heston_result = st.session_state.get(heston_state_key)
    if isinstance(heston_result, Mapping) and heston_result.get("parameters"):
        st.markdown("### Heston calibration governance")
        params = heston_result.get("parameters", {})
        heston_governance = pd.DataFrame(
            [
                {"Field": "Heston version", "Value": heston_result.get("version")},
                {"Field": "Calibration signature", "Value": heston_result.get("configuration_signature")},
                {"Field": "Status", "Value": heston_result.get("status")},
                {"Field": "Objective", "Value": heston_result.get("settings", {}).get("objective")},
                {"Field": "kappa", "Value": params.get("kappa")},
                {"Field": "theta", "Value": params.get("theta")},
                {"Field": "sigma_v", "Value": params.get("sigma_v")},
                {"Field": "rho", "Value": params.get("rho")},
                {"Field": "v0", "Value": params.get("v0")},
                {"Field": "Feller ratio", "Value": heston_result.get("feller_ratio")},
                {"Field": "Train IV RMSE", "Value": heston_result.get("train_metrics", {}).get("iv_rmse")},
                {"Field": "Holdout IV RMSE", "Value": heston_result.get("holdout_metrics", {}).get("iv_rmse")},
                {"Field": "Maximum numerical cross-check error", "Value": heston_result.get("maximum_crosscheck_error")},
                {"Field": "Measure prohibition", "Value": heston_result.get("governance", {}).get("prohibition")},
            ]
        )
        st.dataframe(heston_governance, use_container_width=True, hide_index=True)
        with st.expander("Raw Heston calibration audit", expanded=False):
            st.json(_jsonable({
                "settings": heston_result.get("settings", {}),
                "bounds": heston_result.get("bounds", {}),
                "parameters": heston_result.get("parameters", {}),
                "solution_stability": heston_result.get("solution_stability", {}),
                "warnings": heston_result.get("warnings", []),
                "blockers": heston_result.get("blockers", []),
                "governance": heston_result.get("governance", {}),
            }))

    bates_state_key = f"mc_v270a_bates_result_{lab['ticker']}"
    bates_result = st.session_state.get(bates_state_key)
    if isinstance(bates_result, Mapping) and bates_result.get("parameters"):
        st.markdown("### Bates champion–challenger governance")
        params = bates_result.get("parameters", {})
        comparison = bates_result.get("champion_comparison", {})
        bates_governance = pd.DataFrame(
            [
                {"Field": "Bates version", "Value": bates_result.get("version")},
                {"Field": "Calibration signature", "Value": bates_result.get("configuration_signature")},
                {"Field": "Status", "Value": bates_result.get("status")},
                {"Field": "Champion status", "Value": bates_result.get("champion_status")},
                {"Field": "Jump intensity / year", "Value": params.get("jump_intensity")},
                {"Field": "Jump mean", "Value": params.get("jump_mean")},
                {"Field": "Jump volatility", "Value": params.get("jump_volatility")},
                {"Field": "Holdout improvement", "Value": comparison.get("holdout_improvement")},
                {"Field": "Front-wing improvement", "Value": comparison.get("front_wing_improvement")},
                {"Field": "Maximum other-maturity relative degradation", "Value": comparison.get("maximum_other_maturity_relative_degradation")},
                {"Field": "Maximum other-maturity absolute degradation", "Value": comparison.get("maximum_other_maturity_absolute_degradation")},
                {"Field": "Other-maturity comparison role", "Value": comparison.get("other_maturity_comparison_role")},
                {"Field": "Pseudo-BIC delta", "Value": comparison.get("bic_delta_heston_minus_bates")},
                {"Field": "Train IV RMSE", "Value": bates_result.get("train_metrics", {}).get("iv_rmse")},
                {"Field": "Holdout IV RMSE", "Value": bates_result.get("holdout_metrics", {}).get("iv_rmse")},
                {"Field": "Measure prohibition", "Value": bates_result.get("governance", {}).get("prohibition")},
            ]
        )
        st.dataframe(bates_governance, use_container_width=True, hide_index=True)
        with st.expander("Raw Bates calibration audit", expanded=False):
            st.json(_jsonable({
                "settings": bates_result.get("settings", {}),
                "bounds": bates_result.get("bounds", {}),
                "parameters": bates_result.get("parameters", {}),
                "champion_status": bates_result.get("champion_status"),
                "champion_comparison": bates_result.get("champion_comparison", {}),
                "champion_gate_table": bates_result.get("champion_gate_table", pd.DataFrame()),
                "other_maturity_degradation": bates_result.get("other_maturity_degradation", {}),
                "solution_stability": bates_result.get("solution_stability", {}),
                "warnings": bates_result.get("warnings", []),
                "blockers": bates_result.get("blockers", []),
                "governance": bates_result.get("governance", {}),
            }))

    model_risk_state_key = f"mc_v280_model_risk_result_{lab['ticker']}"
    model_risk_result = st.session_state.get(model_risk_state_key)
    if isinstance(model_risk_result, Mapping) and model_risk_result.get("status") != "FAILED":
        st.markdown("### Final model-risk and numerical governance")
        bootstrap_summary = model_risk_result.get("bootstrap_summary", {})
        model_risk_governance = pd.DataFrame(
            [
                {"Field": "Model-risk version", "Value": model_risk_result.get("version")},
                {"Field": "Governance signature", "Value": model_risk_result.get("configuration_signature")},
                {"Field": "Final status", "Value": model_risk_result.get("status")},
                {"Field": "Recommended role", "Value": model_risk_result.get("recommended_role")},
                {"Field": "Source champion status", "Value": model_risk_result.get("source_champion_status")},
                {"Field": "Bootstrap draws", "Value": bootstrap_summary.get("draws")},
                {"Field": "Heston bootstrap success", "Value": bootstrap_summary.get("heston_success_rate")},
                {"Field": "Bates bootstrap success", "Value": bootstrap_summary.get("bates_success_rate")},
                {"Field": "Bates selection probability", "Value": bootstrap_summary.get("bates_selection_probability")},
                {"Field": "Measure prohibition", "Value": model_risk_result.get("governance", {}).get("measure")},
                {"Field": "Monitoring expectation", "Value": model_risk_result.get("governance", {}).get("monitoring")},
            ]
        )
        st.dataframe(model_risk_governance, use_container_width=True, hide_index=True)
        gate = model_risk_result.get("gate_table")
        if isinstance(gate, pd.DataFrame) and not gate.empty:
            with st.expander("Final model-risk gate", expanded=False):
                st.dataframe(gate, use_container_width=True, hide_index=True)
                st.json(_jsonable(model_risk_result.get("model_card", {})))

    tail_state_key = f"mc_v231_tail_event_result_{lab['ticker']}"
    tail_result = st.session_state.get(tail_state_key)
    if isinstance(tail_result, Mapping) and tail_result.get("ok"):
        st.markdown("### Tail & event stress governance")
        tail_governance = pd.DataFrame(
            [
                {"Field": "Tail/event version", "Value": tail_result.get("tail_event_version")},
                {"Field": "Stress signature", "Value": tail_result.get("configuration_signature")},
                {"Field": "Stress type", "Value": tail_result.get("stress_type")},
                {"Field": "Stress status", "Value": tail_result.get("status")},
                {"Field": "EVT fit status", "Value": tail_result.get("evt_fit", {}).get("status")},
                {"Field": "EVT stability status", "Value": tail_result.get("evt_stability_diagnostic", {}).get("status")},
                {"Field": "EVT governance status", "Value": tail_result.get("stress_metadata", {}).get("evt_governance_status", tail_result.get("evt_fit", {}).get("status"))},
                {"Field": "EVT exceedances", "Value": tail_result.get("evt_fit", {}).get("exceedances")},
                {"Field": "GPD shape xi", "Value": tail_result.get("evt_fit", {}).get("shape")},
                {"Field": "GPD shape range", "Value": tail_result.get("evt_stability_diagnostic", {}).get("shape_range")},
                {"Field": "Jump status", "Value": tail_result.get("jump_fit", {}).get("status")},
                {"Field": "Jump intensity / year", "Value": tail_result.get("jump_fit", {}).get("jump_intensity_ann")},
                {"Field": "Ensemble propagation", "Value": "PROHIBITED — stress only"},
            ]
        )
        st.dataframe(tail_governance, use_container_width=True, hide_index=True)
        with st.expander("Raw tail/event stress audit", expanded=False):
            raw_tail = {
                "stress_metadata": tail_result.get("stress_metadata", {}),
                "evt_fit": {k: v for k, v in tail_result.get("evt_fit", {}).items() if not isinstance(v, np.ndarray)},
                "evt_stability_diagnostic": tail_result.get("evt_stability_diagnostic", {}),
                "jump_fit": tail_result.get("jump_fit", {}),
                "gap_fit": tail_result.get("gap_fit", {}),
                "assumptions": tail_result.get("assumptions", {}),
            }
            st.json(_jsonable(raw_tail))

    uncertainty_state_key = f"mc_v240_uncertainty_result_{lab['ticker']}"
    uncertainty_result = st.session_state.get(uncertainty_state_key)
    if isinstance(uncertainty_result, Mapping) and uncertainty_result.get("ok"):
        st.markdown("### Parameter & model uncertainty governance")
        active_uncertainty = uncertainty_result.get("variance_decomposition", pd.DataFrame())
        active_row = active_uncertainty[active_uncertainty["Horizon"] == int(horizon)] if isinstance(active_uncertainty, pd.DataFrame) else pd.DataFrame()
        active = active_row.iloc[0] if not active_row.empty else pd.Series(dtype=float)
        uncertainty_governance = pd.DataFrame(
            [
                {"Field": "Uncertainty version", "Value": uncertainty_result.get("uncertainty_version")},
                {"Field": "Uncertainty signature", "Value": uncertainty_result.get("configuration_signature")},
                {"Field": "Status", "Value": uncertainty_result.get("status")},
                {"Field": "Models", "Value": ", ".join(uncertainty_result.get("models", []))},
                {"Field": "Weighting method", "Value": uncertainty_result.get("weight_resolution", {}).get("method_effective")},
                {"Field": "Successful draws", "Value": uncertainty_result.get("successful_draws")},
                {"Field": "Failed draws", "Value": uncertainty_result.get("failed_draw_count")},
                {"Field": "Total predictive paths", "Value": uncertainty_result.get("total_predictive_paths")},
                {"Field": "Aleatory share", "Value": _pct(active.get("Aleatory share"))},
                {"Field": "Parameter share", "Value": _pct(active.get("Parameter share"))},
                {"Field": "Model share", "Value": _pct(active.get("Model share"))},
                {"Field": "Barrier monitoring", "Value": uncertainty_result.get("common_barrier_monitoring")},
                {"Field": "Interpretation", "Value": "Frequentist bootstrap diagnostic; not posterior probability or alpha"},
            ]
        )
        st.dataframe(uncertainty_governance, use_container_width=True, hide_index=True)
        with st.expander("Raw parameter/model uncertainty audit", expanded=False):
            raw_uncertainty = {
                "status": uncertainty_result.get("status"),
                "weights": uncertainty_result.get("weights", {}),
                "warnings": uncertainty_result.get("warnings", []),
                "assumptions": uncertainty_result.get("assumptions", {}),
                "variance_decomposition": uncertainty_result.get("variance_decomposition", pd.DataFrame()).to_dict("records")
                if isinstance(uncertainty_result.get("variance_decomposition"), pd.DataFrame)
                else [],
            }
            st.json(_jsonable(raw_uncertainty))

    with st.expander("Long-history provider audit", expanded=False):
        st.json(_jsonable(lab.get("provider_report", {})))
    with st.expander("Raw assumptions and limitations", expanded=False):
        st.json(_jsonable(lab["assumptions"]))
    with st.expander("Raw model eligibility", expanded=False):
        st.json(_jsonable(lab.get("model_eligibility", {})))
    with st.expander("Raw conditional calibrations", expanded=False):
        raw_calibrations = {
            name: {
                key: value
                for key, value in fit.items()
                if not isinstance(value, np.ndarray)
            }
            for name, fit in lab.get("conditional_calibrations", {}).items()
        }
        st.json(_jsonable(raw_calibrations))
    with st.expander("Raw active-horizon summary", expanded=False):
        raw_summary = {key: value for key, value in summary.items() if not isinstance(value, (np.ndarray, pd.DataFrame))}
        st.json(_jsonable(raw_summary))
    with st.expander("Raw scenario matrix", expanded=False):
        st.dataframe(lab["matrix_df"], use_container_width=True, hide_index=True, height=560)



def _format_uncertainty_interval_table(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a display-only copy with interval columns formatted as strings.

    Pandas 2.2+ warns, and newer pandas releases raise, when a string is assigned
    into a float64 column. Cast only the display columns to object before writing
    formatted values so the quantitative source table remains numeric and intact.
    """
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return pd.DataFrame()

    output = frame.copy(deep=True)
    interval_columns = [
        column
        for column in ("CI low", "Median", "CI high")
        if column in output.columns
    ]
    for column in interval_columns:
        output[column] = output[column].astype("object")

    for idx, row in frame.iterrows():
        unit = str(row.get("Unit", "number"))
        for column in interval_columns:
            value = row.get(column)
            if unit == "rate":
                formatted = _pct(value, signed=True)
            elif unit == "pp":
                formatted = f"{float(value):+.2f} pp" if pd.notna(value) else "N/A"
            else:
                formatted = _number(value, 4)
            output.at[idx, column] = formatted
    return output


def _render_parameter_model_uncertainty(lab: Mapping[str, Any], horizon: int) -> None:
    st.markdown("### Parameter & model uncertainty laboratory")
    st.caption(
        "Stationary-bootstrap calibration draws separate within-path randomness from parameter and model uncertainty. "
        "The result is a frequentist resampling diagnostic, not a Bayesian posterior and not an alpha estimate."
    )

    ticker = str(lab["ticker"])
    result_key = f"mc_v240_uncertainty_result_{ticker}"
    validation_key = f"mc_v221c_walk_forward_result_{ticker}"
    validation_result = st.session_state.get(validation_key)
    eligible_models = [
        model
        for model in MODELS
        if str(lab.get("model_eligibility", {}).get(model, {}).get("status")) == "ELIGIBLE"
    ]
    selected_engine = str(lab.get("settings", {}).get("model", "GBM normal"))

    with st.form(key=f"mc_v240_uncertainty_form_{ticker}", border=True):
        row1 = st.columns([0.85, 1.35, 0.9, 0.9])
        with row1[0]:
            model_scope = st.selectbox(
                "Model scope",
                ["Selected engine", "All eligible engines", "Custom selection"],
                index=0,
            )
        with row1[1]:
            default_custom = eligible_models if eligible_models else [selected_engine]
            custom_models = st.multiselect(
                "Models in uncertainty set",
                options=list(MODELS),
                default=default_custom,
                disabled=model_scope != "Custom selection",
            )
        with row1[2]:
            weighting_method = st.selectbox(
                "Model weighting",
                list(UNCERTAINTY_WEIGHTING_METHODS),
                index=0,
                help="Validation-based weights are used only when a compatible walk-forward result is available.",
            )
        with row1[3]:
            parameter_draws = st.selectbox("Parameter draws", [25, 50, 100, 200], index=2)

        row2 = st.columns(4)
        with row2[0]:
            paths_per_draw = st.selectbox("Paths per draw", [100, 250, 500, 1_000], index=1)
        with row2[1]:
            block_length = st.selectbox("Bootstrap mean block length", [5, 10, 20, 40], index=1)
        with row2[2]:
            uncertainty_confidence = st.selectbox(
                "Bootstrap confidence",
                [0.90, 0.95, 0.99],
                index=1,
                format_func=lambda value: f"{value:.0%}",
            )
        with row2[3]:
            uncertainty_scenario = st.selectbox(
                "Scenario overlay",
                list(SCENARIOS),
                index=list(SCENARIOS).index(str(lab.get("settings", {}).get("scenario", "Conservateur"))),
            )

        row3 = st.columns([1.0, 1.0, 1.4])
        with row3[0]:
            refit_conditional = st.checkbox(
                "Refit conditional models inside draws",
                value=True,
                help="Required for full GARCH/GJR parameter uncertainty; computationally more expensive.",
            )
        with row3[1]:
            uncertainty_seed = st.number_input(
                "Uncertainty seed",
                min_value=1,
                max_value=999_999,
                value=int(lab.get("settings", {}).get("seed", 42)),
                step=1,
            )
        with row3[2]:
            st.caption(
                f"Calibration sample: {int(lab['base'].get('calibration_observations', 0)):,} returns. "
                f"Eligible engines: {len(eligible_models)}. Walk-forward weights: "
                + ("available" if isinstance(validation_result, Mapping) and validation_result.get("ok") else "unavailable")
                + "."
            )

        run_uncertainty = st.form_submit_button(
            "Run parameter & model uncertainty analysis",
            use_container_width=True,
            type="primary",
        )

    if model_scope == "Selected engine":
        models = [selected_engine]
    elif model_scope == "All eligible engines":
        models = eligible_models or [selected_engine]
    else:
        models = list(custom_models)

    if run_uncertainty:
        if not models:
            st.error("Select at least one simulation engine.")
        else:
            with st.spinner(
                "Bootstrapping calibration samples, refitting conditional models and decomposing predictive uncertainty…"
            ):
                result = build_parameter_model_uncertainty(
                    lab=lab,
                    models=models,
                    weighting_method=str(weighting_method),
                    validation_result=validation_result if isinstance(validation_result, Mapping) else None,
                    parameter_draws=int(parameter_draws),
                    paths_per_draw=int(paths_per_draw),
                    mean_block_length=int(block_length),
                    confidence_level=float(uncertainty_confidence),
                    scenario=str(uncertainty_scenario),
                    refit_conditional_models=bool(refit_conditional),
                    seed=int(uncertainty_seed),
                )
            # A complete smile collapse across every expiry usually indicates that
        # live option midpoints were inverted against an old cached chain or a
        # stale parent-lab spot.  Retry once with fresh chains; the provider
        # underlying embedded in the response is then used for IV inversion.
        auto_refresh_used = False
        if source_mode == "Automatic provider" and not bool(refresh_now) and not result.get("ok"):
            failure_table = result.get("failures")
            if isinstance(failure_table, pd.DataFrame) and not failure_table.empty:
                stages = failure_table.get("stage", pd.Series(dtype=str)).astype(str)
                all_smile_failures = len(stages) == len(selected_expirations) and bool((stages == "SMILE").all())
                if all_smile_failures:
                    auto_refresh_used = True
                    st.info("All expiry smiles failed the midpoint-IV synchronization gate. Refreshing the selected option chains once with synchronized underlying metadata…")
                    with st.spinner("Refreshing option chains and rebuilding the synchronized volatility surface…"):
                        chains, reports, fetch_warnings = fetch_option_surface_chains(
                            ticker=ticker,
                            expirations=selected_expirations,
                            cache_ttl_hours=int(cache_ttl_hours),
                            force_refresh=True,
                        )
                        if not reports.empty:
                            reports_map = {str(row["expiration"]): row.to_dict() for _, row in reports.iterrows()}
                        for warning in fetch_warnings:
                            _render_orange_warning(str(warning))
                        result = build_multi_expiry_surface(
                            lab=lab,
                            option_chains=chains,
                            expirations=selected_expirations,
                            risk_free_rate=float(risk_free_rate_pct) / 100.0,
                            dividend_yield=float(dividend_yield_pct) / 100.0,
                            borrow_cost=float(borrow_cost_pct) / 100.0,
                            contract_style=str(contract_style),
                            parity_moneyness_band=float(parity_moneyness_band),
                            max_relative_spread=float(max_relative_spread),
                            minimum_open_interest=int(minimum_open_interest),
                            minimum_volume=int(minimum_volume),
                            smoothing_penalty=float(smoothing_penalty),
                            svi_penalty=float(svi_penalty),
                            calendar_projection=bool(calendar_projection),
                            carry_max_deviation=float(carry_max_deviation),
                            carry_smoothness=float(carry_smoothness),
                            source_reports=reports_map,
                            valuation_date=valuation_date,
                        )
        if isinstance(result, dict):
            result["automatic_quote_refresh_used"] = bool(auto_refresh_used)
        st.session_state[result_key] = result

    result = st.session_state.get(result_key)
    if not isinstance(result, Mapping):
        st.info(
            "Run the uncertainty laboratory to compare fixed-parameter risk with distributions that integrate calibration and model uncertainty."
        )
        return
    if not result.get("ok"):
        _render_orange_warning("UNCERTAINTY ANALYSIS BLOCKED — " + str(result.get("reason", "unknown reason")))
        return

    decomposition = result["variance_decomposition"]
    active_row = decomposition[decomposition["Horizon"] == int(horizon)]
    active = active_row.iloc[0] if not active_row.empty else pd.Series(dtype=float)
    total_summary = result["summaries_by_horizon"][int(horizon)]
    fixed_summary = result["fixed_summaries_by_horizon"][int(horizon)]

    metrics = st.columns(7)
    metrics[0].metric("Status", str(result.get("status")))
    metrics[1].metric("Successful draws", f"{int(result.get('successful_draws', 0))}/{int(result.get('requested_draws', 0))}")
    metrics[2].metric("Failure rate", f"{float(result.get('failure_rate', 0.0)):.1%}")
    metrics[3].metric("Aleatory share", f"{float(active.get('Aleatory share', float('nan'))):.1%}")
    metrics[4].metric("Parameter share", f"{float(active.get('Parameter share', float('nan'))):.1%}")
    metrics[5].metric("Model share", f"{float(active.get('Model share', float('nan'))):.1%}")
    metrics[6].metric("Integrated ES 5%", _pct(total_summary["es_5"]))

    if result.get("status") != "ACTIVE":
        _render_orange_warning(
            "UNCERTAINTY GOVERNANCE WARNING — the analysis remains usable for research, but draw count or calibration-failure diagnostics do not satisfy the ACTIVE gate."
        )
    for warning in result.get("warnings", []):
        _render_orange_warning(str(warning))

    comparison = pd.DataFrame(
        [
            {
                "Metric": "Expected return",
                "Fixed parameters": _pct(fixed_summary["expected_return"], signed=True),
                "Uncertainty integrated": _pct(total_summary["expected_return"], signed=True),
                "Delta": _rate_delta_pp(total_summary["expected_return"] - fixed_summary["expected_return"]),
            },
            {
                "Metric": "VaR 5%",
                "Fixed parameters": _pct(fixed_summary["var_5"]),
                "Uncertainty integrated": _pct(total_summary["var_5"]),
                "Delta": _rate_delta_pp(total_summary["var_5"] - fixed_summary["var_5"]),
            },
            {
                "Metric": "ES 5%",
                "Fixed parameters": _pct(fixed_summary["es_5"]),
                "Uncertainty integrated": _pct(total_summary["es_5"]),
                "Delta": _rate_delta_pp(total_summary["es_5"] - fixed_summary["es_5"]),
            },
            {
                "Metric": "Expected max drawdown",
                "Fixed parameters": _pct(fixed_summary["expected_max_drawdown"]),
                "Uncertainty integrated": _pct(total_summary["expected_max_drawdown"]),
                "Delta": _rate_delta_pp(total_summary["expected_max_drawdown"] - fixed_summary["expected_max_drawdown"]),
            },
            {
                "Metric": "P(Ruin)",
                "Fixed parameters": f"{float(fixed_summary['prob_ruin']):.2f}%",
                "Uncertainty integrated": f"{float(total_summary['prob_ruin']):.2f}%",
                "Delta": f"{float(total_summary['prob_ruin'] - fixed_summary['prob_ruin']):+.2f} pp",
            },
        ]
    )
    st.markdown("#### Fixed-parameter versus uncertainty-integrated risk")
    st.dataframe(comparison, use_container_width=True, hide_index=True)

    left, right = st.columns(2)
    with left:
        st.plotly_chart(
            _plot_uncertainty_decomposition(decomposition, int(horizon)),
            use_container_width=True,
            key=f"mc_v240_uncertainty_decomposition_{ticker}_{result['configuration_signature']}_{horizon}",
        )
    with right:
        st.plotly_chart(
            _plot_uncertainty_distribution(result, int(horizon)),
            use_container_width=True,
            key=f"mc_v240_uncertainty_distribution_{ticker}_{result['configuration_signature']}_{horizon}",
        )

    left, right = st.columns([1.15, 0.85])
    with left:
        uncertainty_lab = {
            "paths_by_horizon": result["paths_by_horizon"],
            "levels": result["levels"],
            "base": result["base"],
        }
        st.plotly_chart(
            _plot_fan_chart(uncertainty_lab, int(horizon), False, 0),
            use_container_width=True,
            key=f"mc_v240_uncertainty_fan_{ticker}_{result['configuration_signature']}_{horizon}",
        )
    with right:
        parameter_options = list(result["parameter_interval_table"].get("Parameter", pd.Series(dtype=str)).dropna().unique())
        selected_parameter = st.selectbox(
            "Parameter interval chart",
            parameter_options or ["Drift ann"],
            index=0,
            key=f"mc_v240_uncertainty_parameter_select_{ticker}",
        )
        st.plotly_chart(
            _plot_uncertainty_parameter_intervals(result["parameter_interval_table"], str(selected_parameter)),
            use_container_width=True,
            key=f"mc_v240_uncertainty_parameter_chart_{ticker}_{result['configuration_signature']}_{selected_parameter}",
        )

    st.markdown("#### Bootstrap metric intervals")
    metric_intervals = result["metric_interval_table"]
    active_intervals = metric_intervals[metric_intervals["Horizon"] == int(horizon)].copy()
    st.dataframe(_format_uncertainty_interval_table(active_intervals), use_container_width=True, hide_index=True)

    st.markdown("#### Parameter intervals by model")
    st.dataframe(
        _format_uncertainty_interval_table(result["parameter_interval_table"]),
        use_container_width=True,
        hide_index=True,
        height=360,
    )

    left, right = st.columns([1.0, 1.0])
    with left:
        st.markdown("#### Model weights and fixed-parameter contribution")
        contribution = result["model_contribution_table"].copy()
        if not contribution.empty:
            contribution["Weight"] = contribution["Weight"].map(lambda value: f"{float(value):.2%}")
            contribution["Expected return 90D"] = contribution["Expected return 90D"].map(lambda value: _pct(value, signed=True))
            contribution["Variance 90D"] = contribution["Variance 90D"].map(lambda value: _number(value, 6))
        st.dataframe(contribution, use_container_width=True, hide_index=True)
    with right:
        st.plotly_chart(
            _plot_uncertainty_convergence(result["draw_convergence"][int(horizon)]),
            use_container_width=True,
            key=f"mc_v240_uncertainty_convergence_{ticker}_{result['configuration_signature']}_{horizon}",
        )

    with st.expander("Failed parameter draws", expanded=False):
        failed = result.get("failed_draws")
        if isinstance(failed, pd.DataFrame) and not failed.empty:
            st.dataframe(failed, use_container_width=True, hide_index=True)
        else:
            st.caption("No failed parameter draw.")

    downloads = st.columns(4)
    downloads[0].download_button(
        "Download parameter intervals CSV",
        data=result["parameter_interval_table"].to_csv(index=False).encode("utf-8"),
        file_name=f"{ticker}_parameter_uncertainty_{result['configuration_signature']}.csv",
        mime="text/csv",
        use_container_width=True,
    )
    downloads[1].download_button(
        "Download metric intervals CSV",
        data=result["metric_interval_table"].to_csv(index=False).encode("utf-8"),
        file_name=f"{ticker}_risk_metric_uncertainty_{result['configuration_signature']}.csv",
        mime="text/csv",
        use_container_width=True,
    )
    downloads[2].download_button(
        "Download variance decomposition CSV",
        data=result["variance_decomposition"].to_csv(index=False).encode("utf-8"),
        file_name=f"{ticker}_uncertainty_decomposition_{result['configuration_signature']}.csv",
        mime="text/csv",
        use_container_width=True,
    )
    downloads[3].download_button(
        "Download draw audit CSV",
        data=result["parameter_draw_table"].to_csv(index=False).encode("utf-8"),
        file_name=f"{ticker}_parameter_draw_audit_{result['configuration_signature']}.csv",
        mime="text/csv",
        use_container_width=True,
    )

    with st.expander("Uncertainty methodology and limitations", expanded=False):
        st.json(_jsonable(result.get("assumptions", {})))

def _validation_default_models(lab: Mapping[str, Any]) -> list[str]:
    eligibility = lab.get("model_eligibility", {})
    selected = [
        model
        for model in MODELS
        if str(eligibility.get(model, {}).get("status")) in {"ELIGIBLE", "WARNING"}
    ]
    if selected:
        return selected
    return ["GBM normal", "GBM Student-t calibré", "Historical bootstrap"]


def _walk_forward_leaderboard_display(leaderboard: pd.DataFrame) -> pd.DataFrame:
    if leaderboard is None or leaderboard.empty:
        return pd.DataFrame()
    columns = [
        "Validation rank",
        "Model",
        "Validation status",
        "Forecasts",
        "Mean CRPS",
        "Mean log score",
        "Mean interval score 90%",
        "PIT KS p",
        "Coverage 90%",
        "VaR 5% exception rate",
        "VaR 5% Kupiec p",
        "ES 5% severity ratio",
        "Positive-return Brier",
        "Barrier multiclass Brier",
        "Fallback rate",
        "Eligible-origin share",
    ]
    output = leaderboard[[column for column in columns if column in leaderboard.columns]].copy()
    for column in ("Coverage 90%", "VaR 5% exception rate", "Fallback rate", "Eligible-origin share"):
        if column in output:
            output[column] = output[column].map(lambda value: f"{float(value):.2%}" if pd.notna(value) else "N/A")
    for column in (
        "Mean CRPS",
        "Mean log score",
        "Mean interval score 90%",
        "PIT KS p",
        "VaR 5% Kupiec p",
        "ES 5% severity ratio",
        "Positive-return Brier",
        "Barrier multiclass Brier",
    ):
        if column in output:
            output[column] = output[column].map(lambda value: _number(value, 4))
    return output


def _render_walk_forward_validation(lab: Mapping[str, Any], horizon: int) -> None:
    st.markdown("### Leakage-safe walk-forward distribution validation")
    st.caption(
        "Each forecast origin is calibrated only with observations available at that date. "
        "The validation evaluates full predictive distributions rather than selecting the model with the most favorable current simulation."
    )

    ticker = str(lab["ticker"])
    state_key = f"mc_v221c_walk_forward_result_{ticker}"
    config_state_key = f"mc_v221c_walk_forward_config_{ticker}"
    default_models = _validation_default_models(lab)

    with st.form(key=f"mc_v221c_walk_forward_form_{ticker}", border=True):
        row1 = st.columns([1.25, 0.75, 0.8, 0.8])
        with row1[0]:
            selected_models = st.multiselect(
                "Models to validate",
                options=list(MODELS),
                default=default_models,
                help="The default set contains models currently classified ELIGIBLE or WARNING. Ineligible models can still be selected for research-only validation.",
            )
        with row1[1]:
            validation_horizon = st.selectbox(
                "Forecast horizon",
                list(VALIDATION_HORIZONS),
                index=list(VALIDATION_HORIZONS).index(7),
                format_func=lambda value: f"{value}D",
            )
        with row1[2]:
            origin_options = [8, 12, 20, 30, 40, 60, 100, 150]
            available_for_default = int(lab["base"].get("validation_observations", 0))
            default_origins = 40 if available_for_default >= 1_000 else 12
            validation_origins = st.selectbox(
                "Forecast origins",
                origin_options,
                index=origin_options.index(default_origins),
                help="At least 20 non-overlapping origins are required for a validated model recommendation; 40+ are preferred for ensemble construction.",
            )
        with row1[3]:
            paths_per_origin = st.selectbox("Paths per origin", [250, 500, 1_000, 2_000], index=1)

        row2 = st.columns(4)
        with row2[0]:
            validation_scenario = st.selectbox(
                "Validation drift policy",
                ["Neutre", "Conservateur", "Historique"],
                index=0,
                help="Neutral drift is the default so volatility/distribution quality is not conflated with a directional-return estimate.",
            )
        with row2[1]:
            stride_options = [1, 2, 5, 7, 10, 20, 30]
            default_stride = int(validation_horizon) if int(validation_horizon) in stride_options else 5
            origin_stride = st.selectbox(
                "Origin stride",
                stride_options,
                index=stride_options.index(default_stride),
                help="Using a stride at least as large as the forecast horizon avoids overlapping realized windows by default.",
            )
        with row2[2]:
            training_options: list[int | None] = [None, 252, 500, 750, 1_260]
            training_window = st.selectbox(
                "Training window",
                training_options,
                index=0,
                format_func=lambda value: "Expanding" if value is None else f"Rolling {value:,} returns",
            )
        with row2[3]:
            conditional_refit_every = st.selectbox(
                "Conditional refit cadence",
                [1, 2, 5, 10],
                index=0,
                format_func=lambda value: "Every origin" if value == 1 else f"Every {value} origins",
            )

        row3 = st.columns(3)
        available_returns = int(lab["base"].get("validation_observations", lab["base"].get("calibration_observations", 0)))
        with row3[0]:
            min_train_options = [60, 120, 180, 252, 500]
            feasible = [value for value in min_train_options if value < max(available_returns - int(validation_horizon), 61)]
            if not feasible:
                feasible = [60]
            minimum_training = st.selectbox(
                "Minimum training returns",
                feasible,
                index=min(1, len(feasible) - 1),
            )
        with row3[1]:
            validation_seed = st.number_input("Validation seed", min_value=1, max_value=999_999, value=int(lab["settings"]["seed"]), step=1)
        with row3[2]:
            st.caption(
                f"Available validation history: {available_returns:,} returns from {lab['base'].get('validation_source', lab['base'].get('calibration_source'))}. "
                "Validation power depends on the number of non-overlapping forecast origins, not only the raw history length."
            )

        run_validation = st.form_submit_button(
            "Run model-specific walk-forward validation",
            use_container_width=True,
            type="primary",
        )

    requested = {
        "models": list(selected_models),
        "horizon": int(validation_horizon),
        "forecast_origins": int(validation_origins),
        "origin_stride": int(origin_stride),
        "paths_per_origin": int(paths_per_origin),
        "scenario": validation_scenario,
        "training_window": training_window,
        "minimum_training_observations": int(minimum_training),
        "conditional_refit_every": int(conditional_refit_every),
        "seed": int(validation_seed),
    }

    if run_validation:
        if not selected_models:
            st.error("Select at least one model.")
        else:
            with st.spinner(
                "Running rolling-origin forecasts, refitting conditional models and scoring predictive distributions…"
            ):
                result = build_walk_forward_validation(
                    ticker=ticker,
                    price_data=lab["base"].get("validation_df", lab["base"]["calibration_df"]),
                    models=selected_models,
                    horizon=requested["horizon"],
                    forecast_origins=requested["forecast_origins"],
                    origin_stride=requested["origin_stride"],
                    paths_per_origin=requested["paths_per_origin"],
                    scenario=requested["scenario"],
                    training_window=requested["training_window"],
                    minimum_training_observations=requested["minimum_training_observations"],
                    conditional_refit_every=requested["conditional_refit_every"],
                    seed=requested["seed"],
                    mean_block_length=int(lab["settings"].get("mean_block_length", 10)),
                    ewma_lambda=float(lab["settings"].get("ewma_lambda", 0.94)),
                    garch_maxiter=min(int(lab["settings"].get("garch_maxiter", 500)), 800),
                    garch_min_observations=int(lab["settings"].get("garch_min_observations", 120)),
                    stability_check=False,
                    confidence_level=float(lab["settings"].get("confidence_level", 0.95)),
                )
            st.session_state[state_key] = result
            st.session_state[config_state_key] = requested

    result = st.session_state.get(state_key)
    if not isinstance(result, Mapping):
        st.info("Run the validation to populate the model leaderboard and calibration diagnostics.")
        return
    if not result.get("ok"):
        st.error(result.get("reason", "Walk-forward validation unavailable."))
        return

    active_config = st.session_state.get(config_state_key, {})
    if active_config != requested and not run_validation:
        st.info("Validation controls changed. Run the validation again to apply the new configuration.")

    for warning in result.get("warnings", []):
        _render_orange_warning(str(warning))

    leaderboard = result["leaderboard"]
    recommended = result.get("recommended_model")
    research_leader = result.get("research_leader")
    best_row = leaderboard.iloc[0] if not leaderboard.empty else None
    top = st.columns(6)
    top[0].metric("Forecast origins", str(result["forecast_origins"]))
    top[1].metric("Models scored", str(len(leaderboard)))
    top[2].metric("Validated model", recommended or "None")
    top[3].metric("Research leader", research_leader or "None")
    top[4].metric("Best CRPS", _number(best_row["Mean CRPS"], 4) if best_row is not None else "N/A")
    top[5].metric("Validation signature", result["configuration_signature"])
    if recommended is None and research_leader:
        _render_orange_warning(
            "NO VALIDATED RECOMMENDATION — The displayed research leader has not passed the minimum validation-power and status gate."
        )

    st.plotly_chart(
        _plot_validation_leaderboard(leaderboard),
        use_container_width=True,
        key=f"mc_v221c_walk_forward_leaderboard_{ticker}_{result['configuration_signature']}",
    )
    st.dataframe(
        _walk_forward_leaderboard_display(leaderboard),
        use_container_width=True,
        hide_index=True,
        height=min(520, 65 + 38 * max(len(leaderboard), 1)),
    )
    st.caption(
        "Rank = average rank across CRPS, log score, interval score, coverage error and Brier scores, plus a transparent governance penalty. "
        "It is a validation rank, not an expected-return or alpha score."
    )

    if leaderboard.empty:
        return
    model_options = leaderboard["Model"].tolist()
    default_detail = recommended if recommended in model_options else model_options[0]
    detail_model = st.selectbox(
        "Detailed validation model",
        model_options,
        index=model_options.index(default_detail),
        key=f"mc_v221c_validation_detail_model_{ticker}_{result['configuration_signature']}",
    )

    detail = leaderboard[leaderboard["Model"] == detail_model].iloc[0]
    metrics = st.columns(6)
    metrics[0].metric("Status", str(detail["Validation status"]))
    metrics[1].metric("PIT KS p", _number(detail["PIT KS p"], 4))
    metrics[2].metric("90% coverage", f"{float(detail['Coverage 90%']):.1%}")
    metrics[3].metric("VaR 5% exceptions", f"{float(detail['VaR 5% exception rate']):.1%}")
    metrics[4].metric("Kupiec p", _number(detail["VaR 5% Kupiec p"], 4))
    metrics[5].metric("Barrier Brier", _number(detail["Barrier multiclass Brier"], 4))

    left, right = st.columns(2)
    with left:
        st.plotly_chart(
            _plot_pit_histogram(result["pit_histogram"], detail_model),
            use_container_width=True,
            key=f"mc_v221c_pit_{ticker}_{result['configuration_signature']}_{detail_model}",
        )
    with right:
        st.plotly_chart(
            _plot_quantile_calibration(result["quantile_calibration"], detail_model),
            use_container_width=True,
            key=f"mc_v221c_quantile_calibration_{ticker}_{result['configuration_signature']}_{detail_model}",
        )

    left, right = st.columns(2)
    with left:
        st.plotly_chart(
            _plot_var_exception_timeline(result["forecasts"], detail_model),
            use_container_width=True,
            key=f"mc_v221c_var_timeline_{ticker}_{result['configuration_signature']}_{detail_model}",
        )
    with right:
        reliability_event = st.selectbox(
            "Reliability event",
            ["Positive return", "Target before stop"],
            key=f"mc_v221c_reliability_event_{ticker}_{result['configuration_signature']}_{detail_model}",
        )
        st.plotly_chart(
            _plot_reliability(result["reliability"], detail_model, reliability_event),
            use_container_width=True,
            key=f"mc_v221c_reliability_{ticker}_{result['configuration_signature']}_{detail_model}_{reliability_event}",
        )

    selected_forecasts = result["forecasts"][result["forecasts"]["model"] == detail_model].copy()
    display_columns = [
        "origin_date",
        "realization_date",
        "training_observations",
        "realized_return",
        "predictive_mean",
        "var_5",
        "es_5",
        "pit",
        "crps",
        "log_score",
        "actual_barrier_outcome",
        "prob_target_before_stop",
        "eligibility_status",
        "fallback_used",
    ]
    with st.expander("Forecast-level audit", expanded=False):
        st.dataframe(selected_forecasts[display_columns], use_container_width=True, hide_index=True, height=520)

    download_cols = st.columns(3)
    download_cols[0].download_button(
        "Download leaderboard CSV",
        data=leaderboard.to_csv(index=False).encode("utf-8"),
        file_name=f"{ticker}_walk_forward_leaderboard_{result['configuration_signature']}.csv",
        mime="text/csv",
        use_container_width=True,
    )
    download_cols[1].download_button(
        "Download forecasts CSV",
        data=result["forecasts"].to_csv(index=False).encode("utf-8"),
        file_name=f"{ticker}_walk_forward_forecasts_{result['configuration_signature']}.csv",
        mime="text/csv",
        use_container_width=True,
    )
    download_cols[2].download_button(
        "Download quantile calibration CSV",
        data=result["quantile_calibration"].to_csv(index=False).encode("utf-8"),
        file_name=f"{ticker}_quantile_calibration_{result['configuration_signature']}.csv",
        mime="text/csv",
        use_container_width=True,
    )

    with st.expander("Validation methodology", expanded=False):
        st.json(_jsonable(result.get("methodology", {})))


def _render_validated_ensemble(lab: Mapping[str, Any], horizon: int) -> None:
    st.markdown("### Validated model ensemble")
    st.caption(
        "The ensemble is built from leakage-safe walk-forward evidence. By default, only VALIDATED models with sufficient non-overlapping origins may receive weight."
    )

    ticker = str(lab["ticker"])
    walk_key = f"mc_v221c_walk_forward_result_{ticker}"
    validation_result = st.session_state.get(walk_key)
    if not isinstance(validation_result, Mapping) or not validation_result.get("ok"):
        st.info("Run the Walk-Forward Validation tab first. Ensemble weights cannot be inferred from the current simulation alone.")
        return

    result_key = f"mc_v222_ensemble_result_{ticker}"
    with st.form(key=f"mc_v222_ensemble_form_{ticker}", border=True):
        row1 = st.columns(4)
        with row1[0]:
            method = st.selectbox("Weighting method", list(ENSEMBLE_WEIGHTING_METHODS), index=1)
        with row1[1]:
            governance_mode = st.selectbox(
                "Governance tier",
                ["Validated only", "Include WARNING — research override"],
                index=0,
                help="The override never produces an ACTIVE ensemble; it remains RESEARCH_ONLY.",
            )
        with row1[2]:
            simulations = st.selectbox("Ensemble paths", [3_000, 5_000, 10_000, 25_000], index=1)
        with row1[3]:
            max_weight = st.selectbox("Maximum member weight", [0.25, 0.35, 0.40, 0.50, 1.00], index=2, format_func=lambda value: f"{value:.0%}")

        row2 = st.columns(4)
        with row2[0]:
            minimum_models = st.selectbox("Minimum models", [2, 3, 4], index=1)
        with row2[1]:
            minimum_forecasts = st.selectbox("Minimum forecast origins", [20, 30, 40, 60, 100], index=2)
        with row2[2]:
            correlation_penalty = st.selectbox("Error-correlation penalty", [0.0, 0.25, 0.50, 1.0], index=2)
        with row2[3]:
            bootstrap_repetitions = st.selectbox("Weight bootstrap", [0, 100, 250, 500], index=2, format_func=lambda value: "Off" if value == 0 else f"{value} resamples")

        build = st.form_submit_button("Build governed validated ensemble", use_container_width=True, type="primary")

    if build:
        with st.spinner("Deriving governed weights, bootstrapping weight uncertainty and simulating the mixture distribution…"):
            ensemble = build_validated_ensemble(
                lab=lab,
                validation_result=validation_result,
                method=method,
                simulations=int(simulations),
                max_weight=float(max_weight),
                minimum_models=int(minimum_models),
                minimum_forecasts=int(minimum_forecasts),
                include_warning=governance_mode.startswith("Include"),
                correlation_penalty=float(correlation_penalty),
                bootstrap_repetitions=int(bootstrap_repetitions),
                seed=int(lab["settings"].get("seed", 42)),
            )
        st.session_state[result_key] = ensemble

    ensemble = st.session_state.get(result_key)
    if not isinstance(ensemble, Mapping):
        st.info(
            f"Current validation: {validation_result.get('forecast_origins', 0)} origins · "
            f"validated model: {validation_result.get('recommended_model') or 'none'} · "
            f"research leader: {validation_result.get('research_leader') or 'none'}."
        )
        return

    if not ensemble.get("ok"):
        _render_orange_warning("ENSEMBLE BLOCKED — " + " ".join(ensemble.get("reasons", [])))
        candidate_table = ensemble.get("weight_result", {}).get("candidate_table")
        if isinstance(candidate_table, pd.DataFrame) and not candidate_table.empty:
            st.dataframe(candidate_table, use_container_width=True, hide_index=True)
        return

    summary = ensemble["summaries_by_horizon"][int(horizon)]
    governance = ensemble["weight_governance"]
    metrics = st.columns(6)
    metrics[0].metric("Ensemble status", ensemble["status"])
    metrics[1].metric("Members", str(governance["candidate_models"]))
    metrics[2].metric("Effective models", _number(governance["effective_model_count"], 2))
    metrics[3].metric("Maximum weight", f"{governance['maximum_weight']:.1%}")
    metrics[4].metric("ES 5%", _pct(summary["es_5"]))
    metrics[5].metric("Target before stop", f"{summary['prob_target_before_stop']:.2f}%")

    if ensemble["status"] != "ACTIVE":
        _render_orange_warning("RESEARCH-ONLY ENSEMBLE — WARNING-tier models were included by explicit override.")

    left, right = st.columns([1.0, 1.15])
    with left:
        st.plotly_chart(
            _plot_ensemble_weights(ensemble["weight_table"]),
            use_container_width=True,
            key=f"mc_v222_weights_{ticker}_{ensemble['configuration_signature']}",
        )
    with right:
        st.plotly_chart(
            _plot_ensemble_member_dispersion(ensemble["member_summaries"], int(horizon)),
            use_container_width=True,
            key=f"mc_v222_dispersion_{ticker}_{ensemble['configuration_signature']}_{horizon}",
        )

    ensemble_lab = {
        "paths_by_horizon": ensemble["paths_by_horizon"],
        "levels": ensemble["levels"],
        "base": ensemble["base"],
    }
    left, right = st.columns([1.35, 1.0])
    with left:
        st.plotly_chart(
            _plot_fan_chart(ensemble_lab, int(horizon), False, 0),
            use_container_width=True,
            key=f"mc_v222_fan_{ticker}_{ensemble['configuration_signature']}_{horizon}",
        )
    with right:
        st.plotly_chart(
            _plot_terminal_distribution(summary, ensemble["levels"]),
            use_container_width=True,
            key=f"mc_v222_distribution_{ticker}_{ensemble['configuration_signature']}_{horizon}",
        )

    weight_display = ensemble["weight_table"].copy()
    for column in ("Weight", "Weight CI low", "Weight bootstrap median", "Weight CI high", "Fallback rate", "Eligible-origin share"):
        if column in weight_display:
            weight_display[column] = weight_display[column].map(lambda value: f"{float(value):.2%}" if pd.notna(value) else "N/A")
    st.markdown("#### Weight governance")
    st.dataframe(weight_display, use_container_width=True, hide_index=True)

    st.markdown("#### Member risk decomposition")
    member_display = ensemble["member_summaries"]
    member_display = member_display[member_display["Horizon"] == int(horizon)].copy()
    for column in ("Weight", "Expected return", "Median return", "ES 5%", "VaR 5%", "Expected max drawdown"):
        member_display[column] = member_display[column].map(lambda value: f"{float(value):.2%}")
    for column in ("Target before stop", "Stop before target"):
        member_display[column] = member_display[column].map(lambda value: f"{float(value):.2f}%")
    st.dataframe(member_display, use_container_width=True, hide_index=True)

    download = st.columns(3)
    download[0].download_button(
        "Download ensemble weights CSV",
        data=ensemble["weight_table"].to_csv(index=False).encode("utf-8"),
        file_name=f"{ticker}_validated_ensemble_weights_{ensemble['configuration_signature']}.csv",
        mime="text/csv",
        use_container_width=True,
    )
    download[1].download_button(
        "Download member risk CSV",
        data=ensemble["member_summaries"].to_csv(index=False).encode("utf-8"),
        file_name=f"{ticker}_validated_ensemble_members_{ensemble['configuration_signature']}.csv",
        mime="text/csv",
        use_container_width=True,
    )
    download[2].download_button(
        "Download disagreement CSV",
        data=ensemble["disagreement"].to_csv(index=False).encode("utf-8"),
        file_name=f"{ticker}_validated_ensemble_disagreement_{ensemble['configuration_signature']}.csv",
        mime="text/csv",
        use_container_width=True,
    )

    with st.expander("Ensemble methodology and assumptions", expanded=False):
        st.json(_jsonable(ensemble.get("assumptions", {})))


def _render_tail_event_stress(lab: Mapping[str, Any], horizon: int) -> None:
    st.markdown("### Tail & event stress laboratory")
    st.caption(
        "Peaks-over-threshold EVT, jump-diffusion and deterministic event replays are kept separate from probabilistic model validation. "
        "Stress outputs never receive validated-ensemble weight automatically."
    )
    ticker = str(lab["ticker"])
    result_key = f"mc_v231_tail_event_result_{ticker}"
    library = historical_event_library(lab["base"]["calibration_df"])
    event_options = library["Event ID"].astype(str).tolist() if not library.empty else ["N/A"]

    stress_type = st.selectbox(
        "Stress engine",
        list(TAIL_EVENT_STRESS_TYPES),
        index=0,
        key=f"mc_v231_tail_event_type_{ticker}",
    )
    is_evt = stress_type == "EVT tail injection"
    is_merton = stress_type == "Merton jump-diffusion"
    is_replay = stress_type == "Historical crisis replay"
    is_gap = stress_type == "Earnings / overnight gap proxy"
    is_custom = stress_type == "Custom deterministic shock"

    with st.form(key=f"mc_v231_tail_event_form_{ticker}", border=True):
        row1 = st.columns([0.9, 0.9, 0.9])
        with row1[0]:
            simulations = st.selectbox("Stress paths", [1_000, 3_000, 5_000, 10_000, 25_000], index=2)
        with row1[1]:
            threshold_quantile = st.selectbox(
                "EVT threshold",
                [0.90, 0.925, 0.95, 0.975],
                index=2,
                format_func=lambda value: f"{value:.1%}",
                disabled=not is_evt,
                help="Applied only to EVT tail injection.",
            )
        with row1[2]:
            event_day = st.selectbox(
                "Event day / injection start",
                [1, 2, 5, 10, 20],
                index=0,
                help="For EVT this is the first eligible injection day; for replay/gap/custom stress it is the event day.",
            )

        row2 = st.columns(4)
        with row2[0]:
            intensity_multiplier = st.selectbox(
                "Tail / jump intensity",
                [0.5, 1.0, 1.5, 2.0, 3.0],
                index=2,
                format_func=lambda value: f"{value:.1f}×",
                disabled=not (is_evt or is_merton),
                help="Applied to EVT tail-event frequency or Merton jump intensity.",
            )
        with row2[1]:
            severity_multiplier = st.selectbox(
                "Event severity",
                [0.75, 1.0, 1.25, 1.5, 2.0],
                index=1,
                format_func=lambda value: f"{value:.2f}×",
            )
        with row2[2]:
            volatility_multiplier = st.selectbox(
                "Post-event volatility",
                [1.0, 1.25, 1.5, 2.0, 3.0],
                index=0,
                format_func=lambda value: f"{value:.2f}×",
            )
        with row2[3]:
            bootstrap_repetitions = st.selectbox(
                "EVT bootstrap",
                [0, 50, 100, 250, 500],
                index=2,
                format_func=lambda value: "Off" if value == 0 else f"{value} resamples",
                disabled=not is_evt,
                help="Applied only to EVT parameter uncertainty diagnostics.",
            )

        row3 = st.columns([1.2, 0.8, 0.8])
        with row3[0]:
            historical_event_id = st.selectbox(
                "Historical replay event",
                event_options,
                index=0,
                help="Worst non-overlapping adjusted-price windows extracted from the calibration history.",
                disabled=not is_replay,
            )
        with row3[1]:
            gap_quantile = st.selectbox(
                "Overnight gap quantile",
                [0.01, 0.025, 0.05],
                index=0,
                format_func=lambda value: f"{value:.1%} left tail",
                disabled=not is_gap,
            )
        with row3[2]:
            custom_shock_pct = st.number_input(
                "Custom deterministic shock (%)",
                min_value=-95.0,
                max_value=300.0,
                value=-15.0,
                step=1.0,
                disabled=not is_custom,
            )

        run = st.form_submit_button(
            "Run governed tail & event stress",
            use_container_width=True,
            type="primary",
        )

    if run:
        with st.spinner("Calibrating EVT/jumps, extracting historical events and simulating stressed paths…"):
            result = build_tail_event_stress(
                lab=lab,
                stress_type=str(stress_type),
                simulations=int(simulations),
                threshold_quantile=float(threshold_quantile),
                evt_intensity_multiplier=float(intensity_multiplier),
                severity_multiplier=float(severity_multiplier),
                volatility_multiplier=float(volatility_multiplier),
                event_day=int(event_day),
                historical_event_id=None if historical_event_id == "N/A" else str(historical_event_id),
                gap_quantile=float(gap_quantile),
                custom_shock=float(custom_shock_pct) / 100.0,
                bootstrap_repetitions=int(bootstrap_repetitions),
                seed=int(lab["settings"].get("seed", 42)),
            )
        st.session_state[result_key] = result

    result = st.session_state.get(result_key)
    if not isinstance(result, Mapping):
        st.info(
            "Run a stress to compare the selected Monte Carlo engine with an EVT tail injection, Merton jumps, an observed crisis replay, an overnight-gap proxy or a custom deterministic shock."
        )
        return
    if not result.get("ok"):
        _render_orange_warning("TAIL/EVENT STRESS BLOCKED — " + str(result.get("reason", "unknown reason")))
        return

    stressed = result["summaries_by_horizon"][int(horizon)]
    baseline = result["baseline_summaries_by_horizon"][int(horizon)]
    evt_fit = result.get("evt_fit", {})
    jump_fit = result.get("jump_fit", {})
    evt_stability = result.get("evt_stability_diagnostic", {})
    stress_meta = result.get("stress_metadata", {})
    active_label = "Active stress intensity"
    active_value = "N/A"
    if result.get("stress_type") == "EVT tail injection":
        active_label = "Tail event rate"
        active_value = _pct(stress_meta.get("tail_event_probability_per_step")) + " / step"
    elif result.get("stress_type") == "Merton jump-diffusion":
        active_label = "Jump intensity"
        active_value = _number(stress_meta.get("jump_intensity_ann"), 2) + " / yr"
    elif result.get("stress_type") == "Historical crisis replay":
        active_label = "Replay length"
        active_value = str(stress_meta.get("replay_length", "N/A")) + " step(s)"
    elif result.get("stress_type") == "Earnings / overnight gap proxy":
        active_label = "Gap shock"
        active_value = _pct(stress_meta.get("gap_simple_shock"))
    elif result.get("stress_type") == "Custom deterministic shock":
        active_label = "Custom shock"
        active_value = _pct(stress_meta.get("custom_simple_shock"))

    evt_governance = str(stress_meta.get("evt_governance_status", evt_fit.get("status", "N/A")))
    metrics = st.columns(7)
    metrics[0].metric("Stress status", str(result.get("status")))
    metrics[1].metric("Stress engine", str(result.get("stress_type")))
    metrics[2].metric("EVT governance", evt_governance)
    metrics[3].metric("GPD shape ξ", _number(evt_fit.get("shape"), 4))
    metrics[4].metric(active_label, active_value)
    metrics[5].metric("Stressed ES 5%", _pct(stressed["es_5"]))
    metrics[6].metric("Δ ES 5%", _rate_delta_pp(stressed["es_5"] - baseline["es_5"]))

    _render_orange_warning(
        "STRESS-ONLY OUTPUT — this is not an unconditional forecast probability and it is excluded from validated-ensemble weights."
    )
    if evt_stability.get("status") not in {None, "ELIGIBLE"}:
        _render_orange_warning(
            "EVT THRESHOLD-STABILITY WARNING — "
            + "; ".join(str(reason) for reason in evt_stability.get("reasons", []))
        )

    left, right = st.columns([1.05, 1.0])
    with left:
        st.plotly_chart(
            _plot_evt_threshold_stability(result["evt_threshold_stability"]),
            use_container_width=True,
            key=f"mc_v231_evt_stability_{ticker}_{result['configuration_signature']}",
        )
    with right:
        st.plotly_chart(
            _plot_stress_distribution_comparison(result, int(horizon)),
            use_container_width=True,
            key=f"mc_v231_stress_distribution_{ticker}_{result['configuration_signature']}_{horizon}",
        )

    left, right = st.columns([1.15, 0.85])
    with left:
        stress_lab = {
            "paths_by_horizon": result["paths_by_horizon"],
            "levels": result["levels"],
            "base": result["base"],
        }
        st.plotly_chart(
            _plot_fan_chart(stress_lab, int(horizon), False, 0),
            use_container_width=True,
            key=f"mc_v231_stress_fan_{ticker}_{result['configuration_signature']}_{horizon}",
        )
    with right:
        st.plotly_chart(
            _plot_stress_delta(result["delta_table"], int(horizon)),
            use_container_width=True,
            key=f"mc_v231_stress_delta_{ticker}_{result['configuration_signature']}_{horizon}",
        )

    st.markdown("#### Stress impact table")
    delta_display = result["delta_table"].copy()
    for column in ("Baseline", "Stressed", "Delta"):
        delta_display[column] = delta_display.apply(
            lambda row: (
                f"{float(row[column]):+.2%}"
                if row["Metric"] in {"Expected return", "VaR 5%", "ES 5%", "VaR 1%", "ES 1%", "Expected max drawdown"}
                else f"{float(row[column]):+.2f} pp"
            ),
            axis=1,
        )
    st.dataframe(delta_display, use_container_width=True, hide_index=True)

    diagnostic_cols = st.columns(3)
    with diagnostic_cols[0]:
        st.markdown("#### EVT calibration")
        evt_table = pd.DataFrame(
            [
                {"Field": "Status", "Value": evt_fit.get("status")},
                {"Field": "Threshold", "Value": _pct(-float(evt_fit.get("threshold_loss", 0.0)))},
                {"Field": "Exceedances", "Value": evt_fit.get("exceedances")},
                {"Field": "Shape xi", "Value": _number(evt_fit.get("shape"), 4)},
                {"Field": "Scale beta", "Value": _number(evt_fit.get("scale"), 5)},
                {"Field": "KS p-value", "Value": _number(evt_fit.get("ks_p_value"), 4)},
                {"Field": "EVT VaR 99% loss", "Value": _pct(evt_fit.get("metrics", {}).get("var_99_loss"))},
                {"Field": "EVT ES 99% loss", "Value": _pct(evt_fit.get("metrics", {}).get("es_99_loss"))},
            ]
        )
        st.dataframe(evt_table, use_container_width=True, hide_index=True)
    with diagnostic_cols[1]:
        st.markdown("#### Jump calibration")
        jump_table = pd.DataFrame(
            [
                {"Field": "Status", "Value": jump_fit.get("status")},
                {"Field": "Detected jumps", "Value": jump_fit.get("jump_count")},
                {"Field": "Annual intensity", "Value": _number(jump_fit.get("jump_intensity_ann"), 3)},
                {"Field": "Jump log mean", "Value": _pct(jump_fit.get("jump_log_mean"))},
                {"Field": "Jump log sigma", "Value": _pct(jump_fit.get("jump_log_sigma"))},
                {"Field": "Diffusion vol", "Value": _pct(jump_fit.get("diffusion_vol_ann"))},
            ]
        )
        st.dataframe(jump_table, use_container_width=True, hide_index=True)
    with diagnostic_cols[2]:
        st.markdown("#### Stress configuration")
        stress_meta = pd.DataFrame(
            [{"Field": str(key), "Value": str(value)} for key, value in result.get("stress_metadata", {}).items()]
        )
        st.dataframe(stress_meta, use_container_width=True, hide_index=True)

    if isinstance(result.get("event_library"), pd.DataFrame) and not result["event_library"].empty:
        with st.expander("Historical event library", expanded=False):
            event_display = result["event_library"].drop(columns=["Sequence"], errors="ignore").copy()
            for column in ("Cumulative return", "Realized volatility", "Max drawdown"):
                event_display[column] = event_display[column].map(_pct)
            st.dataframe(event_display, use_container_width=True, hide_index=True)

    downloads = st.columns(3)
    downloads[0].download_button(
        "Download stress deltas CSV",
        data=result["delta_table"].to_csv(index=False).encode("utf-8"),
        file_name=f"{ticker}_tail_event_stress_deltas_{result['configuration_signature']}.csv",
        mime="text/csv",
        use_container_width=True,
    )
    downloads[1].download_button(
        "Download EVT stability CSV",
        data=result["evt_threshold_stability"].to_csv(index=False).encode("utf-8"),
        file_name=f"{ticker}_evt_threshold_stability_{result['configuration_signature']}.csv",
        mime="text/csv",
        use_container_width=True,
    )
    event_export = result["event_library"].drop(columns=["Sequence"], errors="ignore") if isinstance(result.get("event_library"), pd.DataFrame) else pd.DataFrame()
    downloads[2].download_button(
        "Download event library CSV",
        data=event_export.to_csv(index=False).encode("utf-8"),
        file_name=f"{ticker}_historical_event_library_{result['configuration_signature']}.csv",
        mime="text/csv",
        use_container_width=True,
    )

    with st.expander("Tail & event methodology", expanded=False):
        st.json(_jsonable(result.get("assumptions", {})))


def _select_nearest_expiration(expirations: list[str], target_days: int, valuation_date: pd.Timestamp | None = None) -> str | None:
    valuation = (valuation_date or pd.Timestamp.utcnow().tz_localize(None)).normalize()
    candidates: list[tuple[int, str]] = []
    for value in expirations:
        expiry = pd.to_datetime(value, errors="coerce")
        if pd.isna(expiry):
            continue
        days = int((pd.Timestamp(expiry).normalize() - valuation).days)
        if days > 0:
            candidates.append((abs(days - int(target_days)), str(pd.Timestamp(expiry).date())))
    if not candidates:
        return None
    return min(candidates, key=lambda item: item[0])[1]


def _render_options_risk_neutral(lab: Mapping[str, Any], horizon: int) -> None:
    ticker = str(lab.get("ticker", "UNKNOWN"))
    result_key = f"mc_v251_options_result_{ticker}"
    st.markdown("### Options-implied & risk-neutral laboratory")
    st.caption(
        "Listed option quotes are cleaned, governed by exercise style, projected onto a monotone-convex call curve and transformed into a finite-strike risk-neutral density. "
        "US single-stock and ETF chains are American-style; their Q-density is therefore shown as an OTM European-equivalent approximation, not an exact European extraction."
    )

    uploaded_file = None
    with st.form(key=f"mc_v251_options_form_{ticker}", border=True):
        row1 = st.columns([1.0, 0.9, 0.8, 0.8])
        with row1[0]:
            source_mode = st.selectbox("Option-chain source", ["Automatic provider", "CSV upload"], index=0, key=f"mc_v251_options_source_{ticker}")
        with row1[1]:
            contract_style = st.selectbox(
                "Contract style",
                ["American equity/ETF approximation", "European"],
                index=0,
                help="Automatic US equity/ETF chains are American-style. European selection should be used only for genuinely European-exercise contracts or a corrected CSV.",
                key=f"mc_v251_options_contract_{ticker}",
            )
        with row1[2]:
            target_days = st.selectbox("Target expiry", [7, 14, 30, 45, 60, 90, 180, 365], index=2, format_func=lambda value: f"Nearest {value}D", key=f"mc_v251_options_target_{ticker}")
        with row1[3]:
            risk_free_rate_pct = st.number_input("Risk-free rate (%)", min_value=-5.0, max_value=25.0, value=4.0, step=0.10, key=f"mc_v251_options_rate_{ticker}")

        row2 = st.columns([1.0, 0.8, 0.8, 0.8])
        with row2[0]:
            forward_method = st.selectbox("Forward source", ["Governed put-call parity", "Manual dividend yield"], index=0, key=f"mc_v251_options_forward_{ticker}")
        with row2[1]:
            dividend_yield_pct = st.number_input("Dividend / borrow carry input (%)", min_value=-10.0, max_value=25.0, value=0.0, step=0.10, key=f"mc_v251_options_carry_{ticker}")
        with row2[2]:
            parity_moneyness_band = st.selectbox("Parity near-ATM band", [0.10, 0.15, 0.20, 0.30, 0.50], index=2, format_func=lambda value: f"±{value:.0%} log-moneyness", key=f"mc_v251_options_parity_band_{ticker}")
        with row2[3]:
            max_relative_spread = st.selectbox("Maximum relative spread", [0.25, 0.50, 1.00, 2.00], index=1, format_func=lambda value: f"{value:.0%}", key=f"mc_v251_options_spread_{ticker}")

        row3 = st.columns([0.8, 0.8, 0.8, 0.8])
        with row3[0]:
            minimum_open_interest = st.selectbox("Minimum open interest", [0, 1, 10, 50, 100, 500], index=1, key=f"mc_v251_options_oi_{ticker}")
        with row3[1]:
            minimum_volume = st.selectbox("Minimum volume", [0, 1, 10, 50, 100], index=0, key=f"mc_v251_options_volume_{ticker}")
        with row3[2]:
            cache_ttl_hours = st.selectbox("Options cache TTL", [1, 2, 6, 12, 24], index=1, format_func=lambda value: f"{value}h", key=f"mc_v251_options_ttl_{ticker}")
        with row3[3]:
            refresh_now = st.checkbox("Refresh option chain", value=False, key=f"mc_v251_options_refresh_{ticker}")

        row4 = st.columns([1.0])
        with row4[0]:
            uploader = getattr(st, "file_uploader", None)
            if callable(uploader):
                uploaded_file = row4[0].file_uploader(
                    "Option-chain CSV",
                    type=["csv"],
                    accept_multiple_files=False,
                    help="Expected columns include expiration, strike, option_type, bid/ask or last_price. yfinance-style columns are accepted.",
                    disabled=source_mode != "CSV upload",
                    key=f"mc_v251_options_csv_{ticker}",
                )
            else:
                row4[0].caption("CSV upload unavailable in this Streamlit runtime.")

        smoothing_penalty = st.selectbox(
            "Convex-projection smoothing penalty",
            [0.0, 1e-6, 1e-4, 1e-3, 1e-2],
            index=2,
            format_func=lambda value: f"{value:g}",
            key=f"mc_v251_options_smoothing_{ticker}",
        )
        run = st.form_submit_button("Run options-implied / risk-neutral analysis", use_container_width=True, type="primary", key=f"mc_v251_options_submit_{ticker}")

    if run:
        source_report: dict[str, Any] = {"status": "NOT_RUN", "warnings": []}
        raw_chain = pd.DataFrame()
        expiration = None
        valuation_date = pd.Timestamp.utcnow().tz_localize(None).normalize()
        if source_mode == "CSV upload":
            if uploaded_file is None:
                st.error("Upload an option-chain CSV before running the analysis.")
                return
            parsed, parse_error = parse_option_chain_csv(uploaded_file)
            if parse_error or parsed is None:
                st.error(parse_error or "Unable to parse option-chain CSV.")
                return
            normalized_preview, preview_report = normalize_option_chain(parsed)
            expirations = sorted({str(pd.Timestamp(value).date()) for value in normalized_preview.get("expiration", pd.Series(dtype="datetime64[ns]")).dropna().unique()})
            expiration = _select_nearest_expiration(expirations, int(target_days), valuation_date)
            raw_chain = parsed
            source_report = {
                "provider": "uploaded_csv",
                "status": "UPLOADED",
                "ok": True,
                "selected_rows": int(len(parsed)),
                "warnings": preview_report.get("warnings", []),
            }
        else:
            with st.spinner("Resolving option expirations and cached provider chain…"):
                expirations, expiry_report = list_option_expirations(ticker)
                expiration = _select_nearest_expiration(expirations, int(target_days), valuation_date)
                if expiration is not None:
                    raw_chain, source_report = fetch_option_chain(
                        ticker=ticker,
                        expiration=expiration,
                        cache_ttl_hours=int(cache_ttl_hours),
                        force_refresh=bool(refresh_now),
                    )
                else:
                    source_report = expiry_report
        if expiration is None:
            st.error("No future option expiration could be resolved for the requested target tenor.")
            return
        with st.spinner("Projecting option prices, extracting the Q-density and comparing P versus Q…"):
            result = build_options_risk_neutral_lab(
                lab=lab,
                option_chain=raw_chain,
                expiration=expiration,
                risk_free_rate=float(risk_free_rate_pct) / 100.0,
                dividend_yield=float(dividend_yield_pct) / 100.0,
                forward_method=str(forward_method),
                contract_style=str(contract_style),
                parity_moneyness_band=float(parity_moneyness_band),
                max_relative_spread=float(max_relative_spread),
                minimum_open_interest=int(minimum_open_interest),
                minimum_volume=int(minimum_volume),
                smoothing_penalty=float(smoothing_penalty),
                source_report=source_report,
                valuation_date=valuation_date,
            )
        st.session_state[result_key] = result

    result = st.session_state.get(result_key)
    if not isinstance(result, Mapping):
        st.info("Run the options laboratory to extract an arbitrage-controlled risk-neutral terminal density from a live or uploaded option chain.")
        return
    if not result.get("ok"):
        _render_orange_warning("OPTIONS/RISK-NEUTRAL ANALYSIS BLOCKED — " + str(result.get("reason", "unknown reason")))
        return

    metrics = result["risk_neutral_metrics"]
    cards = st.columns(8)
    cards[0].metric("Status", str(result.get("status")))
    cards[1].metric("Expiration", str(result.get("expiration")))
    cards[2].metric("DTE", str(result.get("calendar_days")))
    cards[3].metric("Effective forward", f"{float(result.get('forward')):.2f}")
    cards[4].metric("Effective carry q", _pct(result.get("dividend_yield_effective")))
    cards[5].metric("Parity gate", "ACCEPTED" if result.get("parity_accepted") else "FALLBACK")
    cards[6].metric("Model-free vol", _pct(result.get("model_free_volatility")))
    cards[7].metric("Q P(ST < spot)", f"{float(metrics.get('probability_below_spot', float('nan'))):.1%}")

    _render_orange_warning(
        "MEASURE GOVERNANCE — Q probabilities are pricing probabilities. American equity/ETF chains are shown as an OTM European-equivalent approximation and are not unbiased real-world forecasts."
    )
    for warning in result.get("warnings", []):
        _render_orange_warning(str(warning))

    left, right = st.columns(2)
    with left:
        st.plotly_chart(
            _plot_option_call_projection(result),
            use_container_width=True,
            key=f"mc_v251_option_projection_{ticker}_{result['configuration_signature']}",
        )
    with right:
        st.plotly_chart(
            _plot_risk_neutral_density(result),
            use_container_width=True,
            key=f"mc_v251_q_density_{ticker}_{result['configuration_signature']}",
        )

    left, right = st.columns(2)
    with left:
        st.plotly_chart(
            _plot_implied_volatility_smile(result),
            use_container_width=True,
            key=f"mc_v251_iv_smile_{ticker}_{result['configuration_signature']}",
        )
    with right:
        st.plotly_chart(
            _plot_physical_vs_risk_neutral(result),
            use_container_width=True,
            key=f"mc_v251_p_vs_q_{ticker}_{result['configuration_signature']}",
        )

    physical = result.get("physical_comparison", {})
    comparison_rows = [
        {
            "Metric": "Expected / mean return",
            "Physical P": _pct(physical.get("expected_return"), signed=True) if physical.get("available") else "N/A",
            "Risk-neutral Q": _pct(float(metrics.get("mean_terminal_price")) / float(result["spot"]) - 1.0, signed=True),
        },
        {
            "Metric": "Median return",
            "Physical P": _pct(physical.get("median_return"), signed=True) if physical.get("available") else "N/A",
            "Risk-neutral Q": _pct(float(metrics.get("median_terminal_price")) / float(result["spot"]) - 1.0, signed=True),
        },
        {
            "Metric": "VaR 5%",
            "Physical P": _pct(physical.get("var_5")) if physical.get("available") else "N/A",
            "Risk-neutral Q": _pct(metrics.get("q_var_5")),
        },
        {
            "Metric": "Expected Shortfall 5%",
            "Physical P": _pct(physical.get("es_5")) if physical.get("available") else "N/A",
            "Risk-neutral Q": _pct(metrics.get("q_es_5")),
        },
        {
            "Metric": "P / Q below spot",
            "Physical P": f"{float(physical.get('probability_below_spot', float('nan'))):.1%}" if physical.get("available") else "N/A",
            "Risk-neutral Q": f"{float(metrics.get('probability_below_spot', float('nan'))):.1%}",
        },
    ]
    st.markdown("#### Physical-measure versus risk-neutral comparison")
    st.dataframe(pd.DataFrame(comparison_rows), use_container_width=True, hide_index=True)

    quality = pd.DataFrame(
        [
            {"Diagnostic": "Usable midpoint quotes", "Value": len(result["clean_chain"]), "Status": result.get("status")},
            {"Diagnostic": "Reliable OTM smile quotes", "Value": result.get("reliable_smile_quotes"), "Status": "PASS" if int(result.get("reliable_smile_quotes", 0)) >= 8 else "WARNING"},
            {"Diagnostic": "Contract style", "Value": result.get("contract_style"), "Status": "APPROXIMATION" if str(result.get("contract_style", "")).lower().startswith("american") else "PASS"},
            {"Diagnostic": "Unique strikes", "Value": len(result["synthetic_call_curve"]), "Status": result.get("status")},
            {"Diagnostic": "Near-ATM parity pairs", "Value": result.get("forward_report", {}).get("paired_quotes"), "Status": "ACCEPTED" if result.get("parity_accepted") else "FALLBACK"},
            {"Diagnostic": "Parity candidate carry", "Value": _pct(result.get("forward_report", {}).get("candidate_implied_dividend_yield")), "Status": result.get("forward_report", {}).get("method")},
            {"Diagnostic": "Projection weighted RMSE", "Value": _number(result.get("projection_report", {}).get("weighted_rmse"), 6), "Status": result.get("projection_report", {}).get("status")},
            {"Diagnostic": "Raw finite-strike density mass", "Value": _number(result.get("raw_density_mass"), 4), "Status": "Renormalized to 1"},
            {"Diagnostic": "Q mean minus forward", "Value": f"{float(metrics.get('mean_consistency_error', float('nan'))):+.4f}", "Status": "Consistency check"},
            {"Diagnostic": "1σ expected move", "Value": f"{float(result.get('expected_move_1sigma', float('nan'))):.2f}", "Status": "Model-free variance"},
            {"Diagnostic": "Model-free variance quotes", "Value": result.get("variance_report", {}).get("quote_count"), "Status": "PASS" if result.get("variance_report", {}).get("ok") else "WARNING"},
        ]
    )
    st.markdown("#### Quote, arbitrage and density diagnostics")
    st.dataframe(quality, use_container_width=True, hide_index=True)

    with st.expander("Risk-neutral metrics and governance", expanded=False):
        governance_rows = [
            {"Field": "Options engine", "Value": result.get("version")},
            {"Field": "Configuration signature", "Value": result.get("configuration_signature")},
            {"Field": "Valuation date", "Value": result.get("valuation_date")},
            {"Field": "Expiration", "Value": result.get("expiration")},
            {"Field": "Contract style", "Value": result.get("contract_style")},
            {"Field": "Forward method", "Value": result.get("forward_report", {}).get("method")},
            {"Field": "Parity accepted", "Value": result.get("parity_accepted")},
            {"Field": "Parity candidate q", "Value": _pct(result.get("forward_report", {}).get("candidate_implied_dividend_yield"))},
            {"Field": "Parity dispersion / spot", "Value": _pct(result.get("forward_report", {}).get("forward_dispersion_relative"))},
            {"Field": "Reliable OTM IV quotes", "Value": result.get("reliable_smile_quotes")},
            {"Field": "Q skewness", "Value": _number(metrics.get("risk_neutral_skewness"), 4)},
            {"Field": "Q excess kurtosis", "Value": _number(metrics.get("risk_neutral_excess_kurtosis"), 4)},
            {"Field": "Q VaR 1%", "Value": _pct(metrics.get("q_var_1"))},
            {"Field": "Q ES 1%", "Value": _pct(metrics.get("q_es_1"))},
            {"Field": "Source status", "Value": result.get("source_report", {}).get("status")},
            {"Field": "Exercise-style governance", "Value": result.get("measure_governance", {}).get("exercise_style")},
            {"Field": "Measure prohibition", "Value": result.get("measure_governance", {}).get("prohibition")},
        ]
        st.dataframe(pd.DataFrame(governance_rows), use_container_width=True, hide_index=True)

    with st.expander("Clean option chain", expanded=False):
        display = result["clean_chain"].copy()
        st.dataframe(display, use_container_width=True, hide_index=True, height=360)
    with st.expander("Projected call curve and density audit", expanded=False):
        st.dataframe(result["repricing_table"], use_container_width=True, hide_index=True)
        st.dataframe(result["density_table"], use_container_width=True, hide_index=True)

    downloads = st.columns(4)
    downloads[0].download_button(
        "Download clean chain CSV",
        data=result["clean_chain"].to_csv(index=False).encode("utf-8"),
        file_name=f"{ticker}_clean_option_chain_{result['configuration_signature']}.csv",
        mime="text/csv",
        use_container_width=True,
    )
    downloads[1].download_button(
        "Download Q density CSV",
        data=result["density_table"].to_csv(index=False).encode("utf-8"),
        file_name=f"{ticker}_risk_neutral_density_{result['configuration_signature']}.csv",
        mime="text/csv",
        use_container_width=True,
    )
    downloads[2].download_button(
        "Download call projection CSV",
        data=result["repricing_table"].to_csv(index=False).encode("utf-8"),
        file_name=f"{ticker}_arbitrage_free_call_curve_{result['configuration_signature']}.csv",
        mime="text/csv",
        use_container_width=True,
    )
    downloads[3].download_button(
        "Download parity audit CSV",
        data=result["parity_table"].to_csv(index=False).encode("utf-8"),
        file_name=f"{ticker}_put_call_parity_{result['configuration_signature']}.csv",
        mime="text/csv",
        use_container_width=True,
    )


def _render_options_volatility_surface(lab: Mapping[str, Any], horizon: int) -> None:
    ticker = str(lab.get("ticker", "UNKNOWN"))
    result_key = f"mc_v254_surface_result_{ticker}"
    st.markdown("### Multi-expiry implied-volatility surface")
    st.caption(
        "Reliable OTM midpoint quotes are fitted expiry-by-expiry with governed SVI slices. "
        "A single cross-expiry dividend + borrow carry curve determines all forwards before total variance is projected non-decreasing across maturity. "
        "The result is a Q-measure pricing surface; US equity and ETF chains remain an American-style European-equivalent approximation."
    )

    uploaded_file = None
    with st.form(key=f"mc_v254_surface_form_{ticker}", border=True):
        row1 = st.columns([1.0, 0.9, 0.8, 0.8])
        with row1[0]:
            source_mode = st.selectbox("Surface source", ["Automatic provider", "Multi-expiry CSV"], index=0, key=f"mc_v254_surface_source_{ticker}")
        with row1[1]:
            contract_style = st.selectbox(
                "Contract style",
                ["American equity/ETF approximation", "European"],
                index=0,
                key=f"mc_v254_surface_contract_{ticker}",
            )
        with row1[2]:
            tenor_preset = st.selectbox("Surface tenor set", ["Front 4", "Standard 6", "Extended 8"], index=1, key=f"mc_v254_surface_tenors_{ticker}")
        with row1[3]:
            risk_free_rate_pct = st.number_input("Risk-free rate (%)", min_value=-5.0, max_value=25.0, value=4.0, step=0.10, key=f"mc_v254_surface_rate_{ticker}")

        row2 = st.columns([0.8, 0.8, 0.8, 0.8])
        with row2[0]:
            dividend_yield_pct = st.number_input("Cash dividend yield input (%)", min_value=-5.0, max_value=25.0, value=0.0, step=0.10, key=f"mc_v254_surface_dividend_{ticker}")
        with row2[1]:
            borrow_cost_pct = st.number_input(
                "Borrow / specialness input (%)",
                min_value=-10.0,
                max_value=25.0,
                value=0.0,
                step=0.10,
                help="Added to the cash-dividend yield to form the explicit manual effective-carry anchor q.",
                key=f"mc_v254_surface_borrow_{ticker}",
            )
        with row2[2]:
            parity_moneyness_band = st.selectbox("Parity near-ATM band", [0.10, 0.15, 0.20, 0.30], index=2, format_func=lambda value: f"±{value:.0%}", key=f"mc_v254_surface_parity_band_{ticker}")
        with row2[3]:
            carry_max_deviation = st.selectbox(
                "Max parity deviation from manual carry",
                [0.02, 0.03, 0.05, 0.075],
                index=2,
                format_func=lambda value: f"±{value:.1%}",
                key=f"mc_v254_surface_carry_band_{ticker}",
            )

        row3 = st.columns([0.8, 0.8, 0.8, 0.8])
        with row3[0]:
            max_relative_spread = st.selectbox("Maximum relative spread", [0.25, 0.50, 1.00], index=1, format_func=lambda value: f"{value:.0%}", key=f"mc_v254_surface_spread_{ticker}")
        with row3[1]:
            minimum_open_interest = st.selectbox("Minimum open interest", [0, 1, 10, 50, 100], index=1, key=f"mc_v254_surface_oi_{ticker}")
        with row3[2]:
            minimum_volume = st.selectbox("Minimum volume", [0, 1, 10, 50], index=0, key=f"mc_v254_surface_volume_{ticker}")
        with row3[3]:
            cache_ttl_hours = st.selectbox("Options cache TTL", [1, 2, 6, 12, 24], index=1, format_func=lambda value: f"{value}h", key=f"mc_v254_surface_ttl_{ticker}")

        row4 = st.columns([0.8, 0.8, 0.8, 0.8])
        with row4[0]:
            svi_penalty = st.selectbox("SVI arbitrage penalty", [500.0, 2_500.0, 10_000.0], index=1, format_func=lambda value: f"{value:,.0f}", key=f"mc_v254_surface_svi_penalty_{ticker}")
        with row4[1]:
            carry_smoothness = st.selectbox("Carry-curve smoothness", [5.0, 20.0, 50.0, 100.0], index=1, format_func=lambda value: f"{value:.0f}", key=f"mc_v254_surface_carry_smooth_{ticker}")
        with row4[2]:
            calendar_projection = st.checkbox("Enforce calendar monotonicity", value=True, key=f"mc_v254_surface_calendar_gate_{ticker}")
        with row4[3]:
            refresh_now = st.checkbox("Refresh all selected chains", value=False, key=f"mc_v254_surface_refresh_{ticker}")

        row5 = st.columns([1.0, 1.0])
        with row5[0]:
            smoothing_penalty = st.selectbox(
                "Single-expiry convex smoothing",
                [0.0, 1e-6, 1e-4, 1e-3],
                index=2,
                format_func=lambda value: f"{value:.4g}",
                key=f"mc_v254_surface_convex_smooth_{ticker}",
            )
        with row5[1]:
            uploader = getattr(st, "file_uploader", None)
            if callable(uploader):
                uploaded_file = uploader(
                    "Multi-expiry option-chain CSV",
                    type=["csv"],
                    accept_multiple_files=False,
                    key=f"mc_v254_surface_upload_{ticker}",
                )
            else:
                st.caption("CSV upload unavailable in this Streamlit runtime.")

        submitted = st.form_submit_button(
            "Build governed multi-expiry volatility surface",
            use_container_width=True,
            type="primary",
            key=f"mc_v254_surface_submit_{ticker}",
        )

    if submitted:
        preset_map = {
            "Front 4": ((14, 30, 60, 90), 4),
            "Standard 6": (SURFACE_TARGET_DAYS, 6),
            "Extended 8": ((7, 14, 30, 60, 90, 180, 270, 365), 8),
        }
        target_days, max_expiries = preset_map[str(tenor_preset)]
        valuation_date = pd.Timestamp(lab.get("base", {}).get("valuation_date", pd.Timestamp.utcnow().date())).normalize()
        chains: dict[str, pd.DataFrame] = {}
        reports_map: dict[str, dict[str, Any]] = {}
        selected_expirations: list[str] = []

        if source_mode == "Multi-expiry CSV":
            if uploaded_file is None:
                st.error("Upload a multi-expiry option-chain CSV before running the surface analysis.")
                return
            parsed, parse_error = parse_option_chain_csv(uploaded_file)
            if parse_error or parsed is None:
                st.error(parse_error or "Unable to parse option-chain CSV.")
                return
            normalized, preview = normalize_option_chain(parsed, valuation_date=valuation_date)
            if normalized.empty:
                st.error("The uploaded CSV did not contain usable multi-expiry quotes.")
                return
            available = sorted({str(pd.Timestamp(value).date()) for value in normalized["expiration"].dropna().unique()})
            selected_expirations = select_surface_expirations(available, valuation_date, target_days, max_expiries=max_expiries)
            for expiration in selected_expirations:
                chains[expiration] = normalized[normalized["expiration"] == pd.Timestamp(expiration)].copy()
                reports_map[expiration] = {"status": "UPLOADED", "ok": True, "selected_rows": int(len(chains[expiration])), "warnings": preview.get("warnings", [])}
        else:
            with st.spinner("Resolving expirations and loading governed option-chain caches…"):
                available, expiry_report = list_option_expirations(ticker)
                selected_expirations = select_surface_expirations(available, valuation_date, target_days, max_expiries=max_expiries)
                if not selected_expirations:
                    st.error("No usable future expirations were returned by the option provider.")
                    return
                chains, reports, fetch_warnings = fetch_option_surface_chains(
                    ticker=ticker,
                    expirations=selected_expirations,
                    cache_ttl_hours=int(cache_ttl_hours),
                    force_refresh=bool(refresh_now),
                )
                if not reports.empty:
                    reports_map = {str(row["expiration"]): row.to_dict() for _, row in reports.iterrows()}
                for warning in fetch_warnings:
                    _render_orange_warning(str(warning))
                if expiry_report.get("warnings"):
                    for warning in expiry_report.get("warnings", []):
                        _render_orange_warning(str(warning))

        with st.spinner("Building the joint carry curve, fitting SVI slices and checking calendar total variance…"):
            result = build_multi_expiry_surface(
                lab=lab,
                option_chains=chains,
                expirations=selected_expirations,
                risk_free_rate=float(risk_free_rate_pct) / 100.0,
                dividend_yield=float(dividend_yield_pct) / 100.0,
                borrow_cost=float(borrow_cost_pct) / 100.0,
                contract_style=str(contract_style),
                parity_moneyness_band=float(parity_moneyness_band),
                max_relative_spread=float(max_relative_spread),
                minimum_open_interest=int(minimum_open_interest),
                minimum_volume=int(minimum_volume),
                smoothing_penalty=float(smoothing_penalty),
                svi_penalty=float(svi_penalty),
                calendar_projection=bool(calendar_projection),
                carry_max_deviation=float(carry_max_deviation),
                carry_smoothness=float(carry_smoothness),
                source_reports=reports_map,
                valuation_date=valuation_date,
            )
        st.session_state[result_key] = result

    result = st.session_state.get(result_key)
    if not isinstance(result, Mapping):
        st.info("Build the surface to inspect the governed carry curve, multi-expiry term structure and calendar-arbitrage controls.")
        return
    if not result.get("ok"):
        _render_orange_warning("VOLATILITY SURFACE BLOCKED — " + str(result.get("reason", "unknown reason")))
        failures = result.get("failures")
        if isinstance(failures, pd.DataFrame) and not failures.empty:
            st.dataframe(failures, use_container_width=True, hide_index=True)
        return

    term = result["term_structure"].sort_values("dte")
    front = term.iloc[0]
    carry = result.get("carry_curve", {})
    cards = st.columns(8)
    cards[0].metric("Status", str(result.get("status")))
    cards[1].metric("Usable expiries", str(result.get("expiry_count")))
    cards[2].metric("Carry curve", str(carry.get("status", "N/A")))
    cards[3].metric("Parity anchors", str(carry.get("accepted_candidates", 0)))
    cards[4].metric("Calendar violations", f"{result.get('raw_calendar_violations')} → {result.get('projected_calendar_violations')}")
    cards[5].metric("Front ATM IV", _pct(front.get("atm_iv_projected")))
    cards[6].metric("Potential event windows", str(result.get("potential_event_windows", 0)))
    cards[7].metric("Surface signature", str(result.get("configuration_signature")))
    surface_spot = result.get("surface_spot")
    lab_spot = result.get("lab_spot")
    spot_gap = result.get("surface_spot_gap")
    if surface_spot is not None and lab_spot is not None:
        st.caption(
            f"Option-pricing spot {float(surface_spot):.4f} · parent-lab spot {float(lab_spot):.4f} · synchronization gap {float(spot_gap):+.2%}"
        )
    if result.get("automatic_quote_refresh_used"):
        st.info("The surface recovered after one automatic option-chain refresh and spot synchronization retry.")

    _render_orange_warning(
        "MEASURE GOVERNANCE — this is a Q-measure pricing surface. American equity/ETF chains remain one OTM European-equivalent approximation and are not physical forecasts."
    )
    for warning in result.get("warnings", []):
        _render_orange_warning(str(warning))

    expiry_warnings = result.get("expiry_warnings")
    if isinstance(expiry_warnings, pd.DataFrame) and not expiry_warnings.empty:
        with st.expander(f"Expiry-specific exceptions ({len(expiry_warnings)})", expanded=False):
            st.dataframe(expiry_warnings, use_container_width=True, hide_index=True)

    left, right = st.columns([1.15, 1.0])
    with left:
        st.plotly_chart(
            _plot_volatility_surface(result),
            use_container_width=True,
            key=f"mc_v254_surface_3d_{ticker}_{result['configuration_signature']}",
        )
    with right:
        st.plotly_chart(
            _plot_surface_term_structure(result),
            use_container_width=True,
            key=f"mc_v254_surface_term_{ticker}_{result['configuration_signature']}",
        )

    left, right = st.columns(2)
    with left:
        st.plotly_chart(
            _plot_surface_smile_slices(result),
            use_container_width=True,
            key=f"mc_v254_surface_slices_{ticker}_{result['configuration_signature']}",
        )
    with right:
        if result.get("calendar_adjustment_required"):
            st.plotly_chart(
                _plot_surface_calendar_adjustment(result),
                use_container_width=True,
                key=f"mc_v254_surface_calendar_{ticker}_{result['configuration_signature']}",
            )
        else:
            st.markdown("#### Calendar-arbitrage projection adjustment")
            st.success(
                f"No calendar adjustment required. 0 violations across the evaluated grid; maximum total-variance adjustment "
                f"{float(result.get('calendar_adjustment_max', 0.0)):.2e}."
            )

    st.markdown("#### Governed carry curve")
    carry_table = result.get("carry_curve_table", pd.DataFrame()).copy()
    if isinstance(carry_table, pd.DataFrame) and not carry_table.empty:
        carry_display = carry_table.copy()
        for column in (
            "manual_carry_anchor",
            "parity_candidate_q",
            "curve_carry_q",
            "candidate_minus_curve",
            "manual_dividend_yield",
            "manual_borrow_cost",
            "parity_early_exercise_residual",
        ):
            if column in carry_display.columns:
                carry_display[column] = carry_display[column].map(lambda value: _pct(value, signed=True))
        if "parity_dispersion_relative" in carry_display.columns:
            carry_display["parity_dispersion_relative"] = carry_display["parity_dispersion_relative"].map(_pct)
        st.dataframe(carry_display, use_container_width=True, hide_index=True)

    events = result.get("event_diagnostics")
    if isinstance(events, pd.DataFrame) and not events.empty:
        st.markdown("#### ATM term-structure event-premium diagnostics")
        event_display = events.copy()
        for column in ("atm_iv_start", "atm_iv_end", "incremental_forward_vol"):
            event_display[column] = event_display[column].map(_pct)
        event_display["atm_iv_change_pp"] = event_display["atm_iv_change_pp"].map(lambda value: _pp(value, signed=True))
        st.dataframe(event_display, use_container_width=True, hide_index=True)
        st.caption("Potential-event flags are statistical term-structure diagnostics only. Verify earnings and corporate events from an independent calendar.")

    st.markdown("#### Surface term structure and skew")
    display_term = term.copy()
    for column in ("atm_iv_raw", "atm_iv_projected", "model_free_vol", "call_25d_iv", "put_25d_iv", "effective_q", "manual_dividend_yield", "manual_borrow_cost", "parity_candidate_q", "parity_early_exercise_residual"):
        if column in display_term.columns:
            display_term[column] = display_term[column].map(lambda value: _pct(value, signed=column in {"effective_q", "manual_dividend_yield", "manual_borrow_cost", "parity_candidate_q", "parity_early_exercise_residual"}))
    for column in ("risk_reversal_25d", "butterfly_25d"):
        display_term[column] = display_term[column].map(lambda value: _pct(value, signed=True))
    st.dataframe(display_term, use_container_width=True, hide_index=True)

    st.markdown("#### Expiry-level SVI and arbitrage diagnostics")
    st.dataframe(result["expiry_summary"], use_container_width=True, hide_index=True)
    failures = result.get("failures")
    if isinstance(failures, pd.DataFrame) and not failures.empty:
        with st.expander("Failed expiries", expanded=False):
            st.dataframe(failures, use_container_width=True, hide_index=True)

    with st.expander("Surface governance and raw audit", expanded=False):
        governance_rows = [
            {"Field": "Surface engine", "Value": result.get("version")},
            {"Field": "Configuration signature", "Value": result.get("configuration_signature")},
            {"Field": "Status", "Value": result.get("status")},
            {"Field": "Usable expiries", "Value": result.get("expiry_count")},
            {"Field": "Carry status", "Value": carry.get("status")},
            {"Field": "Manual effective carry", "Value": _pct(carry.get("manual_effective_carry"), signed=True)},
            {"Field": "Accepted parity anchors", "Value": carry.get("accepted_candidates")},
            {"Field": "Rejected parity candidates", "Value": carry.get("rejected_candidates")},
            {"Field": "Raw calendar violations", "Value": result.get("raw_calendar_violations")},
            {"Field": "Projected calendar violations", "Value": result.get("projected_calendar_violations")},
            {"Field": "Calendar adjustment RMSE", "Value": result.get("calendar_adjustment_rmse")},
            {"Field": "Calendar adjustment max", "Value": result.get("calendar_adjustment_max")},
            {"Field": "Potential event windows", "Value": result.get("potential_event_windows")},
            {"Field": "Measure", "Value": result.get("governance", {}).get("measure")},
            {"Field": "Exercise style", "Value": result.get("governance", {}).get("exercise_style")},
            {"Field": "Carry curve", "Value": result.get("governance", {}).get("carry_curve")},
            {"Field": "Carry components", "Value": result.get("governance", {}).get("carry_components")},
            {"Field": "Event diagnostic", "Value": result.get("governance", {}).get("event_diagnostic")},
            {"Field": "Calendar projection", "Value": result.get("governance", {}).get("calendar_projection")},
            {"Field": "Butterfly control", "Value": result.get("governance", {}).get("butterfly_control")},
            {"Field": "Measure prohibition", "Value": result.get("governance", {}).get("prohibition")},
        ]
        st.dataframe(pd.DataFrame(governance_rows), use_container_width=True, hide_index=True)
        st.json(_jsonable({"settings": result.get("settings"), "source_reports": result.get("source_reports"), "warnings": result.get("warnings")}))

    downloads = st.columns(6)
    downloads[0].download_button(
        "Download surface grid CSV",
        data=result["surface_table"].to_csv(index=False).encode("utf-8"),
        file_name=f"{ticker}_vol_surface_{result['configuration_signature']}.csv",
        mime="text/csv",
        use_container_width=True,
    )
    downloads[1].download_button(
        "Download term structure CSV",
        data=result["term_structure"].to_csv(index=False).encode("utf-8"),
        file_name=f"{ticker}_vol_term_structure_{result['configuration_signature']}.csv",
        mime="text/csv",
        use_container_width=True,
    )
    downloads[2].download_button(
        "Download SVI diagnostics CSV",
        data=result["expiry_summary"].to_csv(index=False).encode("utf-8"),
        file_name=f"{ticker}_svi_diagnostics_{result['configuration_signature']}.csv",
        mime="text/csv",
        use_container_width=True,
    )
    downloads[3].download_button(
        "Download smile points CSV",
        data=result["smile_points"].to_csv(index=False).encode("utf-8"),
        file_name=f"{ticker}_surface_smile_points_{result['configuration_signature']}.csv",
        mime="text/csv",
        use_container_width=True,
    )
    downloads[4].download_button(
        "Download carry curve CSV",
        data=result["carry_curve_table"].to_csv(index=False).encode("utf-8"),
        file_name=f"{ticker}_carry_curve_{result['configuration_signature']}.csv",
        mime="text/csv",
        use_container_width=True,
    )
    downloads[5].download_button(
        "Download event diagnostics CSV",
        data=result["event_diagnostics"].to_csv(index=False).encode("utf-8"),
        file_name=f"{ticker}_event_diagnostics_{result['configuration_signature']}.csv",
        mime="text/csv",
        use_container_width=True,
    )


def _render_calibration_dataset_governance(lab: Mapping[str, Any], horizon: int) -> None:
    ticker = str(lab.get("ticker", "UNKNOWN"))
    surface_key = f"mc_v254_surface_result_{ticker}"
    result_key = f"mc_v255_calibration_dataset_result_{ticker}"
    surface_result = st.session_state.get(surface_key)

    st.markdown("### Heston/Bates calibration dataset governance")
    st.caption(
        "This layer freezes the exact Q-measure training and holdout instruments used by future Heston/Bates calibration. "
        "It applies event-variance policy, moneyness coverage gates, deterministic holdouts and governed vega/liquidity/quality weights."
    )

    with st.form(key=f"mc_v255_dataset_form_{ticker}", border=True):
        row1 = st.columns([1.2, 1.0, 1.1, 0.8])
        with row1[0]:
            event_policy = st.selectbox(
                "Event-variance policy",
                list(EVENT_POLICIES),
                index=list(EVENT_POLICIES).index("Strip estimated discrete event variance"),
                key=f"mc_v255_dataset_event_policy_{ticker}",
            )
        with row1[1]:
            holdout_policy = st.selectbox(
                "Holdout design",
                list(HOLDOUT_POLICIES),
                index=0,
                key=f"mc_v255_dataset_holdout_policy_{ticker}",
            )
        with row1[2]:
            weighting_method = st.selectbox(
                "Calibration weighting",
                list(WEIGHTING_METHODS),
                index=0,
                key=f"mc_v255_dataset_weighting_{ticker}",
            )
        with row1[3]:
            max_abs_k = st.selectbox(
                "Maximum |log(K/F)|",
                [0.20, 0.25, 0.30, 0.35, 0.40],
                index=2,
                format_func=lambda value: f"±{value:.2f}",
                key=f"mc_v255_dataset_k_band_{ticker}",
            )

        row2 = st.columns([0.8, 0.8, 0.8, 0.8])
        with row2[0]:
            holdout_fraction = st.selectbox(
                "Holdout fraction",
                [0.10, 0.15, 0.20, 0.25, 0.30],
                index=2,
                format_func=lambda value: f"{value:.0%}",
                key=f"mc_v255_dataset_holdout_fraction_{ticker}",
            )
        with row2[1]:
            min_maturities = st.selectbox(
                "Minimum training maturities",
                [3, 4, 5, 6],
                index=1,
                key=f"mc_v255_dataset_min_maturities_{ticker}",
            )
        with row2[2]:
            min_training_points = st.selectbox(
                "Minimum training quotes",
                [24, 40, 60, 80, 120],
                index=1,
                key=f"mc_v255_dataset_min_points_{ticker}",
            )
        with row2[3]:
            min_points_per_maturity = st.selectbox(
                "Minimum quotes / maturity",
                [4, 6, 8, 10],
                index=1,
                key=f"mc_v255_dataset_min_per_expiry_{ticker}",
            )

        row3 = st.columns([0.8, 0.8, 1.6])
        with row3[0]:
            min_ess = st.selectbox(
                "Minimum effective sample size",
                [15.0, 25.0, 40.0, 60.0],
                index=1,
                format_func=lambda value: f"{value:.0f}",
                key=f"mc_v255_dataset_min_ess_{ticker}",
            )
        with row3[1]:
            max_quote_weight = st.selectbox(
                "Maximum quote weight",
                [0.025, 0.05, 0.075, 0.10],
                index=1,
                format_func=lambda value: f"{value:.1%}",
                key=f"mc_v255_dataset_max_weight_{ticker}",
            )
        with row3[2]:
            st.caption(
                "The event-strip policy estimates discrete variance from flagged adjacent maturity windows and subtracts it from all later total-variance targets. "
                "No event date is fabricated."
            )

        submitted = st.form_submit_button(
            "Build governed Heston/Bates calibration dataset",
            use_container_width=True,
            type="primary",
            key=f"mc_v255_dataset_submit_{ticker}",
        )

    if submitted:
        if not isinstance(surface_result, Mapping) or not surface_result.get("ok"):
            st.error("Build a valid multi-expiry volatility surface before constructing the calibration dataset.")
            return
        with st.spinner("Applying event policy, holdout design and calibration weights…"):
            result = build_calibration_dataset(
                surface_result=surface_result,
                event_policy=str(event_policy),
                holdout_policy=str(holdout_policy),
                weighting_method=str(weighting_method),
                max_abs_log_moneyness=float(max_abs_k),
                holdout_fraction=float(holdout_fraction),
                min_maturities=int(min_maturities),
                min_training_points=int(min_training_points),
                min_points_per_maturity=int(min_points_per_maturity),
                min_effective_sample_size=float(min_ess),
                max_quote_weight=float(max_quote_weight),
            )
        st.session_state[result_key] = result

    result = st.session_state.get(result_key)
    if not isinstance(result, Mapping):
        if isinstance(surface_result, Mapping) and surface_result.get("ok"):
            st.info("Build the calibration dataset to freeze the exact Heston/Bates training and holdout instruments.")
        else:
            st.info("A completed Volatility Surface result is required before this dataset can be built.")
        return

    cards = st.columns(8)
    cards[0].metric("Status", str(result.get("status", "BLOCKED")))
    cards[1].metric("Training quotes", f"{int(result.get('training_points', 0)):,}")
    cards[2].metric("Holdout quotes", f"{int(result.get('holdout_points', 0)):,}")
    cards[3].metric("Training maturities", str(result.get("training_maturities", 0)))
    cards[4].metric("Effective sample size", f"{float(result.get('effective_sample_size', 0.0)):.1f}")
    cards[5].metric("Max quote weight", _pct(result.get("maximum_quote_weight")))
    cards[6].metric("Event variance removed", f"{float(result.get('event_variance_removed_total', 0.0)) * 10_000.0:.2f} bp²")
    cards[7].metric("Dataset signature", str(result.get("configuration_signature", "N/A")))

    _render_orange_warning(
        "CALIBRATION GOVERNANCE — this dataset is a Q-measure pricing target for future Heston/Bates calibration. "
        "Training weights and event adjustments do not convert Q probabilities into physical forecasts."
    )
    for blocker in result.get("blockers", []):
        _render_orange_warning("DATASET BLOCKED — " + str(blocker))
    for warning in result.get("warnings", []):
        _render_orange_warning(str(warning))

    left, right = st.columns([1.1, 1.0])
    with left:
        st.plotly_chart(
            _plot_calibration_dataset_coverage(result),
            use_container_width=True,
            key=f"mc_v255_dataset_coverage_{ticker}_{result.get('configuration_signature')}",
        )
    with right:
        st.plotly_chart(
            _plot_calibration_weight_matrix(result),
            use_container_width=True,
            key=f"mc_v255_dataset_weights_{ticker}_{result.get('configuration_signature')}",
        )

    event_adjustments = result.get("event_adjustments")
    if isinstance(event_adjustments, pd.DataFrame) and not event_adjustments.empty:
        st.plotly_chart(
            _plot_event_variance_adjustments(result),
            use_container_width=True,
            key=f"mc_v255_dataset_event_variance_{ticker}_{result.get('configuration_signature')}",
        )

    st.markdown("#### Maturity coverage and calibration-weight allocation")
    coverage = result.get("coverage_table")
    if isinstance(coverage, pd.DataFrame):
        coverage_display = coverage.copy()
        if "training_weight" in coverage_display.columns:
            coverage_display["training_weight"] = coverage_display["training_weight"].map(_pct)
        st.dataframe(coverage_display, use_container_width=True, hide_index=True)

    if isinstance(event_adjustments, pd.DataFrame) and not event_adjustments.empty:
        st.markdown("#### Event-variance policy audit")
        event_display = event_adjustments.copy()
        for column in ("actual_incremental_variance", "baseline_annualized_variance", "expected_continuous_increment", "estimated_event_variance"):
            if column in event_display.columns:
                event_display[column] = event_display[column].map(lambda value: f"{float(value) * 10_000.0:.3f} bp²")
        if "estimated_event_vol_equivalent" in event_display.columns:
            event_display["estimated_event_vol_equivalent"] = event_display["estimated_event_vol_equivalent"].map(_pct)
        st.dataframe(event_display, use_container_width=True, hide_index=True)

    training = result.get("training_dataset")
    holdout = result.get("holdout_dataset")
    st.markdown("#### Exact calibration dataset")
    if isinstance(training, pd.DataFrame) and not training.empty:
        compact_columns = [
            "expiration", "dte", "strike", "option_type", "log_moneyness", "effective_iv", "target_iv",
            "event_variance_removed", "vega_score", "liquidity_score", "quality_score", "calibration_weight",
        ]
        compact = training[[column for column in compact_columns if column in training.columns]].copy()
        for column in ("effective_iv", "target_iv"):
            if column in compact.columns:
                compact[column] = compact[column].map(_pct)
        if "event_variance_removed" in compact.columns:
            compact["event_variance_removed"] = compact["event_variance_removed"].map(lambda value: f"{float(value) * 10_000.0:.3f} bp²")
        if "calibration_weight" in compact.columns:
            compact["calibration_weight"] = compact["calibration_weight"].map(_pct)
        st.dataframe(compact, use_container_width=True, hide_index=True)

    with st.expander("Holdout and full dataset audit", expanded=False):
        if isinstance(holdout, pd.DataFrame):
            st.markdown("**Holdout instruments**")
            st.dataframe(holdout, use_container_width=True, hide_index=True)
        dataset = result.get("dataset")
        if isinstance(dataset, pd.DataFrame):
            st.markdown("**Full included/excluded audit**")
            st.dataframe(dataset, use_container_width=True, hide_index=True)
        st.markdown("**Governance record**")
        st.dataframe(
            pd.DataFrame([{"Field": key, "Value": value} for key, value in result.get("governance", {}).items()]),
            use_container_width=True,
            hide_index=True,
        )

    downloads = st.columns(6)
    dataset = result.get("dataset", pd.DataFrame())
    training = result.get("training_dataset", pd.DataFrame())
    holdout = result.get("holdout_dataset", pd.DataFrame())
    coverage = result.get("coverage_table", pd.DataFrame())
    weight_matrix = result.get("weight_matrix", pd.DataFrame())
    event_adjustments = result.get("event_adjustments", pd.DataFrame())
    signature = str(result.get("configuration_signature", "UNKNOWN"))
    downloads[0].download_button(
        "Download training CSV",
        data=training.to_csv(index=False).encode("utf-8"),
        file_name=f"{ticker}_heston_training_{signature}.csv",
        mime="text/csv",
        use_container_width=True,
    )
    downloads[1].download_button(
        "Download holdout CSV",
        data=holdout.to_csv(index=False).encode("utf-8"),
        file_name=f"{ticker}_heston_holdout_{signature}.csv",
        mime="text/csv",
        use_container_width=True,
    )
    downloads[2].download_button(
        "Download full audit CSV",
        data=dataset.to_csv(index=False).encode("utf-8"),
        file_name=f"{ticker}_calibration_dataset_audit_{signature}.csv",
        mime="text/csv",
        use_container_width=True,
    )
    downloads[3].download_button(
        "Download coverage CSV",
        data=coverage.to_csv(index=False).encode("utf-8"),
        file_name=f"{ticker}_calibration_coverage_{signature}.csv",
        mime="text/csv",
        use_container_width=True,
    )
    downloads[4].download_button(
        "Download weight matrix CSV",
        data=weight_matrix.to_csv(index=False).encode("utf-8"),
        file_name=f"{ticker}_calibration_weight_matrix_{signature}.csv",
        mime="text/csv",
        use_container_width=True,
    )
    downloads[5].download_button(
        "Download event audit CSV",
        data=event_adjustments.to_csv(index=False).encode("utf-8"),
        file_name=f"{ticker}_event_variance_audit_{signature}.csv",
        mime="text/csv",
        use_container_width=True,
    )


def _render_heston_calibration(lab: Mapping[str, Any], horizon: int) -> None:
    ticker = str(lab.get("ticker", "UNKNOWN"))
    dataset_key = f"mc_v255_calibration_dataset_result_{ticker}"
    result_key = f"mc_v260a_heston_result_{ticker}"
    dataset_result = st.session_state.get(dataset_key)

    st.markdown("### Governed Heston calibration")
    st.caption(
        "Heston is calibrated under the risk-neutral measure to the frozen training dataset. "
        "The holdout remains outside the objective, multi-start solutions are retained for identifiability analysis, "
        "and Fourier prices are cross-checked numerically."
    )

    with st.form(key=f"mc_v260a_heston_form_{ticker}", border=True):
        row1 = st.columns([1.35, 0.75, 0.75, 0.75])
        with row1[0]:
            objective = st.selectbox(
                "Calibration objective",
                list(HESTON_OBJECTIVES),
                index=0,
                key=f"mc_v260a_heston_objective_{ticker}",
            )
        with row1[1]:
            multi_start = st.selectbox(
                "Multi-starts",
                [2, 4, 8, 12, 20],
                index=2,
                key=f"mc_v260a_heston_starts_{ticker}",
            )
        with row1[2]:
            max_nfev = st.selectbox(
                "Max evaluations / start",
                [100, 200, 300, 500, 800],
                index=2,
                key=f"mc_v260a_heston_nfev_{ticker}",
            )
        with row1[3]:
            quadrature_nodes = st.selectbox(
                "Fourier nodes",
                [48, 64, 96, 128],
                index=1,
                key=f"mc_v260a_heston_nodes_{ticker}",
            )

        row2 = st.columns([1.0, 0.8, 0.8, 0.8, 0.8])
        with row2[0]:
            feller_policy = st.selectbox(
                "Feller treatment",
                list(FELLER_POLICIES),
                index=0,
                key=f"mc_v260a_heston_feller_policy_{ticker}",
            )
        with row2[1]:
            feller_penalty = st.selectbox(
                "Soft penalty strength",
                [0.0, 0.25, 1.0, 5.0],
                index=2,
                disabled=str(feller_policy) != "Soft boundary penalty",
                key=f"mc_v260a_heston_feller_penalty_{ticker}",
            )
        with row2[2]:
            kappa_upper_bound = st.selectbox(
                "κ upper bound",
                [8.0, 12.0, 20.0, 30.0],
                index=2,
                format_func=lambda value: f"{value:.0f}",
                key=f"mc_v260a_heston_kappa_bound_{ticker}",
            )
        with row2[3]:
            seed = st.number_input(
                "Calibration seed",
                min_value=0,
                max_value=2_147_483_647,
                value=42,
                step=1,
                key=f"mc_v260a_heston_seed_{ticker}",
            )
        with row2[4]:
            crosscheck_points = st.selectbox(
                "Numerical cross-check quotes",
                [0, 4, 6, 10],
                index=2,
                key=f"mc_v260a_heston_crosscheck_{ticker}",
            )

        row3 = st.columns([0.8, 0.8, 2.0])
        with row3[0]:
            run_robustness_checks = st.checkbox(
                "Run bound/Feller challengers",
                value=True,
                key=f"mc_v260a_heston_robustness_{ticker}",
            )
        with row3[1]:
            robustness_max_nfev = st.selectbox(
                "Challenger max evaluations",
                [60, 120, 200, 300],
                index=1,
                disabled=not bool(run_robustness_checks),
                key=f"mc_v260a_heston_robustness_nfev_{ticker}",
            )
        with row3[2]:
            st.caption(
                "No-penalty is the neutral pricing specification. Soft and hard Feller treatments are explicit challengers; "
                "a boundary solution or κ cap sensitivity is reported rather than hidden."
            )

        submitted = st.form_submit_button(
            "Run governed Heston robustness calibration",
            use_container_width=True,
            type="primary",
            key=f"mc_v260a_heston_submit_{ticker}",
        )

    if submitted:
        if not isinstance(dataset_result, Mapping) or not dataset_result.get("ok"):
            st.error("Build a PASS/WARNING Calibration Dataset before running Heston calibration.")
            return
        with st.spinner("Calibrating Heston across governed multi-starts and validating training, holdout and numerical pricing…"):
            result = calibrate_heston(
                dataset_result=dataset_result,
                objective=str(objective),
                multi_start=int(multi_start),
                max_nfev=int(max_nfev),
                quadrature_nodes=int(quadrature_nodes),
                feller_policy=str(feller_policy),
                feller_penalty=float(feller_penalty),
                kappa_upper_bound=float(kappa_upper_bound),
                seed=int(seed),
                numerical_crosscheck_points=int(crosscheck_points),
                run_robustness_checks=bool(run_robustness_checks),
                robustness_max_nfev=int(robustness_max_nfev),
            )
        st.session_state[result_key] = result

    result = st.session_state.get(result_key)
    if not isinstance(result, Mapping):
        if isinstance(dataset_result, Mapping) and dataset_result.get("ok"):
            st.info("Run the calibration to estimate κ, θ, σᵥ, ρ and v₀ on the governed training dataset.")
        else:
            st.info("A completed Calibration Dataset is required before Heston calibration.")
        return

    if not result.get("ok") and result.get("status") == "FAILED":
        st.error("HESTON CALIBRATION FAILED — " + str(result.get("reason", "unknown failure")))
        solutions = result.get("multi_start_solutions")
        if isinstance(solutions, pd.DataFrame) and not solutions.empty:
            st.dataframe(solutions, use_container_width=True, hide_index=True)
        return

    train_metrics = result.get("train_metrics", {})
    holdout_metrics = result.get("holdout_metrics", {})
    stability = result.get("solution_stability", {})
    local_summary = result.get("local_error_summary", {})
    parameters_map = result.get("parameters", {})
    bounds_map = result.get("bounds", {})
    kappa_cap = bounds_map.get("kappa", (float("nan"), float("nan")))[1] if isinstance(bounds_map, Mapping) else float("nan")
    cards = st.columns(8)
    cards[0].metric("Status", str(result.get("status", "FAILED")))
    cards[1].metric("Train IV RMSE", _pct(train_metrics.get("iv_rmse")))
    cards[2].metric("Holdout IV RMSE", _pct(holdout_metrics.get("iv_rmse")))
    cards[3].metric("Feller regime", str(result.get("feller_regime", "N/A")), _number(result.get("feller_ratio"), 3))
    cards[4].metric("κ / cap", f"{float(parameters_map.get('kappa', float('nan'))):.2f} / {float(kappa_cap):.0f}")
    cards[5].metric("Worst local IV bias", _pct(local_summary.get("worst_cell_mean_abs_iv_error")))
    cards[6].metric("Robustness", str(result.get("robustness_status", "NOT_RUN")))
    cards[7].metric("Numerical max error", _number(result.get("maximum_crosscheck_error"), 6))
    st.caption(
        f"Variance half-life {float(result.get('variance_half_life_days', float('nan'))):.1f} d · "
        f"Near-optimal starts {stability.get('near_optimal_solutions', 0)} · "
        f"Calibration signature {result.get('configuration_signature', 'N/A')}"
    )

    _render_orange_warning(
        "MODEL GOVERNANCE — Heston is a Q-measure pricing model. A successful calibration does not imply physical forecasting power "
        "and does not enter the validated P-measure ensemble."
    )
    for blocker in result.get("blockers", []):
        _render_orange_warning("HESTON INELIGIBLE — " + str(blocker))
    for warning in result.get("warnings", []):
        _render_orange_warning(str(warning))

    st.markdown("#### Heston parameters and constraints")
    parameter_table = result.get("parameter_table")
    if isinstance(parameter_table, pd.DataFrame):
        display = parameter_table.copy()
        display["estimate"] = display["estimate"].map(lambda value: f"{float(value):.6f}")
        display["lower_bound"] = display["lower_bound"].map(lambda value: f"{float(value):.6f}")
        display["upper_bound"] = display["upper_bound"].map(lambda value: f"{float(value):.6f}")
        st.dataframe(display, use_container_width=True, hide_index=True)

    left, right = st.columns([1.25, 1.0])
    with left:
        st.plotly_chart(
            _plot_heston_fit_smiles(result),
            use_container_width=True,
            key=f"mc_v260a_heston_fit_{ticker}_{result.get('configuration_signature')}",
        )
    with right:
        st.plotly_chart(
            _plot_heston_residual_heatmap(result),
            use_container_width=True,
            key=f"mc_v260a_heston_residuals_{ticker}_{result.get('configuration_signature')}",
        )

    left, right = st.columns(2)
    with left:
        st.plotly_chart(
            _plot_heston_multistart(result),
            use_container_width=True,
            key=f"mc_v260a_heston_multistart_{ticker}_{result.get('configuration_signature')}",
        )
    with right:
        st.plotly_chart(
            _plot_heston_parameter_position(result),
            use_container_width=True,
            key=f"mc_v260a_heston_parameter_position_{ticker}_{result.get('configuration_signature')}",
        )

    st.markdown("#### Training and holdout validation")
    metric_table = pd.DataFrame([
        {"Sample": "TRAIN", **train_metrics},
        {"Sample": "HOLDOUT", **holdout_metrics},
    ])
    for column in ("iv_rmse", "mean_abs_iv_error"):
        if column in metric_table:
            metric_table[column] = metric_table[column].map(_pct)
    if "tv_rmse" in metric_table:
        metric_table["tv_rmse"] = metric_table["tv_rmse"].map(lambda value: f"{float(value) * 10_000.0:.3f} bp²" if pd.notna(value) else "N/A")
    if "price_rmse" in metric_table:
        metric_table["price_rmse"] = metric_table["price_rmse"].map(lambda value: f"{float(value):.4f}" if pd.notna(value) else "N/A")
    st.dataframe(metric_table, use_container_width=True, hide_index=True)

    maturity_errors = result.get("maturity_errors")
    moneyness_errors = result.get("moneyness_errors")
    validation_cols = st.columns(2)
    with validation_cols[0]:
        st.markdown("**Error by maturity**")
        if isinstance(maturity_errors, pd.DataFrame):
            display = maturity_errors.copy()
            for column in ("iv_rmse", "mean_abs_iv_error"):
                if column in display:
                    display[column] = display[column].map(_pct)
            st.dataframe(display, use_container_width=True, hide_index=True)
    with validation_cols[1]:
        st.markdown("**Error by moneyness bucket**")
        if isinstance(moneyness_errors, pd.DataFrame):
            display = moneyness_errors.copy()
            for column in ("iv_rmse", "mean_abs_iv_error"):
                if column in display:
                    display[column] = display[column].map(_pct)
            st.dataframe(display, use_container_width=True, hide_index=True)

    robustness_table = result.get("robustness_table")
    local_error_table = result.get("local_error_table")
    if isinstance(robustness_table, pd.DataFrame) and not robustness_table.empty:
        st.markdown("#### Bound and Feller robustness challengers")
        display = robustness_table.copy()
        for column in ("cost_improvement_vs_selected", "parameter_distance_vs_selected", "train_iv_rmse", "holdout_iv_rmse"):
            if column in display:
                display[column] = display[column].map(_pct)
        st.dataframe(display, use_container_width=True, hide_index=True)
    if isinstance(local_error_table, pd.DataFrame) and not local_error_table.empty:
        st.markdown("#### Local residual governance")
        display = local_error_table.copy()
        for column in ("mean_iv_error", "iv_rmse", "max_abs_iv_error"):
            if column in display:
                display[column] = display[column].map(_pct)
        st.dataframe(display, use_container_width=True, hide_index=True)

    with st.expander("Multi-start, numerical and model-risk audit", expanded=False):
        solutions = result.get("multi_start_solutions")
        if isinstance(solutions, pd.DataFrame):
            st.markdown("**All multi-start solutions**")
            st.dataframe(solutions, use_container_width=True, hide_index=True)
        crosscheck = result.get("numerical_crosscheck")
        if isinstance(crosscheck, pd.DataFrame):
            st.markdown("**Gauss–Laguerre versus adaptive quadrature**")
            st.dataframe(crosscheck, use_container_width=True, hide_index=True)
        robustness = result.get("robustness_table")
        if isinstance(robustness, pd.DataFrame) and not robustness.empty:
            st.markdown("**Robustness specifications**")
            st.dataframe(robustness, use_container_width=True, hide_index=True)
        st.markdown("**Governance record**")
        st.dataframe(
            pd.DataFrame([{"Field": key, "Value": value} for key, value in result.get("governance", {}).items()]),
            use_container_width=True,
            hide_index=True,
        )

    downloads = st.columns(6)
    fit_table = result.get("fit_table", pd.DataFrame())
    solutions = result.get("multi_start_solutions", pd.DataFrame())
    maturity_errors = result.get("maturity_errors", pd.DataFrame())
    bucket_errors = result.get("moneyness_errors", pd.DataFrame())
    crosscheck = result.get("numerical_crosscheck", pd.DataFrame())
    parameters = result.get("parameter_table", pd.DataFrame())
    signature = str(result.get("configuration_signature", "UNKNOWN"))
    downloads[0].download_button("Download fitted instruments CSV", fit_table.to_csv(index=False).encode("utf-8"), f"{ticker}_heston_fit_{signature}.csv", "text/csv", use_container_width=True)
    downloads[1].download_button("Download parameters CSV", parameters.to_csv(index=False).encode("utf-8"), f"{ticker}_heston_parameters_{signature}.csv", "text/csv", use_container_width=True)
    downloads[2].download_button("Download multi-start CSV", solutions.to_csv(index=False).encode("utf-8"), f"{ticker}_heston_multistart_{signature}.csv", "text/csv", use_container_width=True)
    downloads[3].download_button("Download maturity errors CSV", maturity_errors.to_csv(index=False).encode("utf-8"), f"{ticker}_heston_maturity_errors_{signature}.csv", "text/csv", use_container_width=True)
    downloads[4].download_button("Download moneyness errors CSV", bucket_errors.to_csv(index=False).encode("utf-8"), f"{ticker}_heston_moneyness_errors_{signature}.csv", "text/csv", use_container_width=True)
    downloads[5].download_button("Download numerical audit CSV", crosscheck.to_csv(index=False).encode("utf-8"), f"{ticker}_heston_numerical_audit_{signature}.csv", "text/csv", use_container_width=True)



def _render_bates_calibration(lab: Mapping[str, Any], horizon: int) -> None:
    ticker = str(lab.get("ticker", "UNKNOWN"))
    dataset_key = f"mc_v255_calibration_dataset_result_{ticker}"
    heston_key = f"mc_v260a_heston_result_{ticker}"
    result_key = f"mc_v270a_bates_result_{ticker}"
    dataset_result = st.session_state.get(dataset_key)
    heston_result = st.session_state.get(heston_key)

    st.markdown("### Bates calibration & Heston champion–challenger")
    st.caption(
        "Bates adds a risk-neutral compound-Poisson jump component to the calibrated Heston diffusion. "
        "Both models use the same frozen dataset, weights, carry curve and holdout. Bates is retained only if "
        "the jump parameters improve out-of-sample and front-wing fit after complexity and identification gates."
    )

    with st.form(key=f"mc_v270a_bates_form_{ticker}", border=True):
        row1 = st.columns([1.35, 0.75, 0.75, 0.75])
        with row1[0]:
            objective = st.selectbox(
                "Calibration objective",
                list(HESTON_OBJECTIVES),
                index=0,
                key=f"mc_v270a_bates_objective_{ticker}",
            )
        with row1[1]:
            multi_start = st.selectbox(
                "Multi-starts",
                [2, 4, 8, 12, 20],
                index=2,
                key=f"mc_v270a_bates_starts_{ticker}",
            )
        with row1[2]:
            max_nfev = st.selectbox(
                "Max evaluations / start",
                [100, 180, 260, 400, 600],
                index=2,
                key=f"mc_v270a_bates_nfev_{ticker}",
            )
        with row1[3]:
            quadrature_nodes = st.selectbox(
                "Fourier nodes",
                [48, 64, 96, 128],
                index=1,
                key=f"mc_v270a_bates_nodes_{ticker}",
            )

        row2 = st.columns([0.75, 0.75, 0.75, 0.75, 0.85])
        with row2[0]:
            seed = st.number_input(
                "Calibration seed",
                min_value=0,
                max_value=2_147_483_647,
                value=42,
                step=1,
                key=f"mc_v270a_bates_seed_{ticker}",
            )
        with row2[1]:
            crosscheck_points = st.selectbox(
                "Numerical cross-check quotes",
                [0, 4, 6, 10],
                index=2,
                key=f"mc_v270a_bates_crosscheck_{ticker}",
            )
        with row2[2]:
            minimum_holdout_improvement = st.selectbox(
                "Minimum holdout improvement",
                [0.05, 0.10, 0.15, 0.20],
                index=1,
                format_func=lambda value: f"{value:.0%}",
                key=f"mc_v270a_bates_holdout_gate_{ticker}",
            )
        with row2[3]:
            minimum_front_wing_improvement = st.selectbox(
                "Minimum front-wing improvement",
                [0.10, 0.20, 0.30, 0.40],
                index=1,
                format_func=lambda value: f"{value:.0%}",
                key=f"mc_v270a_bates_wing_gate_{ticker}",
            )
        with row2[4]:
            maximum_other_degradation = st.selectbox(
                "Maximum other-maturity degradation",
                [0.05, 0.10, 0.15, 0.25],
                index=2,
                format_func=lambda value: f"{value:.0%}",
                key=f"mc_v270a_bates_other_gate_{ticker}",
            )

        row3 = st.columns([0.85, 0.85, 2.0])
        with row3[0]:
            maximum_other_absolute_degradation = st.selectbox(
                "Maximum absolute other-maturity degradation",
                [0.0025, 0.0035, 0.0050, 0.0075],
                index=1,
                format_func=lambda value: f"{value * 100.0:.2f} IV pp",
                key=f"mc_v270a_bates_other_absolute_gate_{ticker}",
            )
        with row3[1]:
            require_bic_improvement = st.checkbox(
                "Require pseudo-BIC improvement",
                value=True,
                key=f"mc_v270a_bates_bic_gate_{ticker}",
            )
        with row3[2]:
            st.caption(
                "Champion selection requires material holdout and shortest-maturity wing improvement, controlled errors on other maturities, "
                "stable non-degenerate jump parameters and—by default—a complexity-adjusted pseudo-BIC gain. A non-front maturity is treated "
                "as materially degraded only when both the relative and absolute tolerances are breached."
            )

        submitted = st.form_submit_button(
            "Run governed Bates calibration & champion–challenger",
            use_container_width=True,
            type="primary",
            key=f"mc_v270a_bates_submit_{ticker}",
        )

    if submitted:
        if not isinstance(dataset_result, Mapping) or not dataset_result.get("ok"):
            st.error("Build a PASS/WARNING Calibration Dataset before running Bates calibration.")
            return
        if not isinstance(heston_result, Mapping) or not heston_result.get("parameters"):
            st.error("Run the governed Heston calibration first; Bates requires the continuous-model benchmark.")
            return
        with st.spinner("Calibrating Bates across governed multi-starts and evaluating Heston versus Bates on identical training and holdout instruments…"):
            result = calibrate_bates(
                dataset_result=dataset_result,
                heston_result=heston_result,
                objective=str(objective),
                multi_start=int(multi_start),
                max_nfev=int(max_nfev),
                quadrature_nodes=int(quadrature_nodes),
                seed=int(seed),
                numerical_crosscheck_points=int(crosscheck_points),
                minimum_holdout_improvement=float(minimum_holdout_improvement),
                minimum_front_wing_improvement=float(minimum_front_wing_improvement),
                maximum_other_maturity_degradation=float(maximum_other_degradation),
                maximum_other_maturity_absolute_degradation=float(maximum_other_absolute_degradation),
                require_bic_improvement=bool(require_bic_improvement),
            )
        st.session_state[result_key] = result

    result = st.session_state.get(result_key)
    if not isinstance(result, Mapping):
        if isinstance(heston_result, Mapping) and heston_result.get("parameters"):
            st.info("Run Bates to determine whether jumps materially improve Heston after holdout, front-wing and complexity gates.")
        else:
            st.info("A completed Heston calibration is required before Bates champion–challenger analysis.")
        return

    if not result.get("ok") and result.get("status") == "FAILED":
        st.error("BATES CALIBRATION FAILED — " + str(result.get("reason", "unknown failure")))
        solutions = result.get("multi_start_solutions")
        if isinstance(solutions, pd.DataFrame) and not solutions.empty:
            st.dataframe(solutions, use_container_width=True, hide_index=True)
        return

    train_metrics = result.get("train_metrics", {})
    holdout_metrics = result.get("holdout_metrics", {})
    comparison = result.get("champion_comparison", {})
    parameters_map = result.get("parameters", {})
    stability = result.get("solution_stability", {})
    cards = st.columns(9)
    cards[0].metric("Status", str(result.get("status", "FAILED")))
    cards[1].metric("Champion", str(result.get("champion_status", "INCONCLUSIVE")))
    cards[2].metric("Holdout improvement", _pct(comparison.get("holdout_improvement"), signed=True))
    cards[3].metric("Front-wing improvement", _pct(comparison.get("front_wing_improvement"), signed=True))
    cards[4].metric("Pseudo-BIC Δ", _number(comparison.get("bic_delta_heston_minus_bates"), 2))
    cards[5].metric(
        "Other-maturity max Δ",
        f"{float(comparison.get('maximum_other_maturity_absolute_degradation', float('nan'))) * 100.0:+.2f} IV pp"
        if pd.notna(comparison.get("maximum_other_maturity_absolute_degradation")) else "N/A",
        delta=(
            f"{float(comparison.get('maximum_other_maturity_relative_degradation')):+.1%} relative"
            if pd.notna(comparison.get("maximum_other_maturity_relative_degradation")) else None
        ),
        delta_color="inverse",
    )
    cards[6].metric("Jump intensity / y", _number(parameters_map.get("jump_intensity"), 3))
    cards[7].metric("Mean jump", _pct(result.get("expected_jump_return"), signed=True))
    jump_dispersion = stability.get("jump_maximum_normalized_range")
    cards[8].metric(
        "Jump dispersion",
        _pct(jump_dispersion),
        delta="PASS" if pd.notna(jump_dispersion) and float(jump_dispersion) <= 0.35 else "REVIEW",
        delta_color="normal" if pd.notna(jump_dispersion) and float(jump_dispersion) <= 0.35 else "inverse",
    )
    st.caption(
        f"Expected jumps 30D {float(result.get('expected_jumps_30d', float('nan'))):.3f} · "
        f"Jump μ {float(parameters_map.get('jump_mean', float('nan'))):+.4f} · "
        f"Jump σ {float(parameters_map.get('jump_volatility', float('nan'))):.4f} · "
        f"Calibration signature {result.get('configuration_signature', 'N/A')}"
    )

    _render_orange_warning(
        "MODEL GOVERNANCE — Bates is a Q-measure pricing challenger. Jump parameters and Q probabilities are not physical event forecasts "
        "and do not enter the validated P-measure ensemble."
    )
    for blocker in result.get("blockers", []):
        _render_orange_warning("BATES INELIGIBLE — " + str(blocker))
    for warning in result.get("warnings", []):
        _render_orange_warning(str(warning))
    for note in result.get("champion_notes", []):
        st.info(str(note))

    st.markdown("#### Champion gate audit")
    gate_table = result.get("champion_gate_table")
    if isinstance(gate_table, pd.DataFrame) and not gate_table.empty:
        display = gate_table.copy()
        percent_gates = {
            "Holdout IV RMSE improvement",
            "Front-wing IV RMSE improvement",
            "Other-maturity relative degradation",
            "Other-maturity absolute degradation",
            "Jump-parameter stability",
        }
        for idx, row in display.iterrows():
            gate = str(row.get("gate", ""))
            observed = row.get("observed")
            threshold = row.get("threshold")
            if gate in percent_gates and pd.notna(observed) and isinstance(observed, (int, float, np.number)):
                if gate == "Other-maturity absolute degradation":
                    display.at[idx, "observed"] = f"{float(observed) * 100.0:+.2f} IV pp"
                    display.at[idx, "threshold"] = f"≤ {float(threshold) * 100.0:.2f} IV pp"
                else:
                    display.at[idx, "observed"] = f"{float(observed):+.2%}"
                    display.at[idx, "threshold"] = f"{'≤' if 'degradation' in gate.lower() or 'stability' in gate.lower() else '≥'} {float(threshold):.2%}"
            elif gate == "Pseudo-BIC improvement" and pd.notna(observed):
                display.at[idx, "observed"] = f"{float(observed):+.2f}"
                display.at[idx, "threshold"] = "> 0"
            elif gate == "Material jump component" and pd.notna(observed):
                display.at[idx, "observed"] = f"{float(observed):.3f} / y"
                display.at[idx, "threshold"] = "> 0.05 / y plus material jump size"
        display["result"] = display["passed"].map(lambda value: "PASS" if bool(value) else "FAIL")
        display = display[["gate", "observed", "threshold", "result", "detail"]]
        st.dataframe(display, use_container_width=True, hide_index=True)

    other_comparison = result.get("other_maturity_comparison")
    with st.expander("Non-front maturity degradation audit", expanded=False):
        if isinstance(other_comparison, pd.DataFrame) and not other_comparison.empty:
            display = other_comparison.copy()
            for column in ("heston_iv_rmse", "bates_iv_rmse", "absolute_degradation"):
                if column in display:
                    display[column] = display[column].map(
                        lambda value: f"{float(value) * 100.0:+.2f} IV pp" if column == "absolute_degradation" else f"{float(value):.2%}"
                    )
            if "relative_degradation" in display:
                display["relative_degradation"] = display["relative_degradation"].map(lambda value: f"{float(value):+.2%}")
            st.dataframe(display, use_container_width=True, hide_index=True)
        else:
            st.caption("No common non-front maturity comparison was available.")

    st.markdown("#### Bates parameters and constraints")
    parameter_table = result.get("parameter_table")
    if isinstance(parameter_table, pd.DataFrame):
        display = parameter_table.copy()
        for column in ("estimate", "lower_bound", "upper_bound"):
            display[column] = display[column].map(lambda value: f"{float(value):.6f}")
        st.dataframe(display, use_container_width=True, hide_index=True)

    left, right = st.columns([1.25, 1.0])
    with left:
        st.plotly_chart(
            _plot_bates_fit_smiles(result),
            use_container_width=True,
            key=f"mc_v270a_bates_fit_{ticker}_{result.get('configuration_signature')}",
        )
    with right:
        st.plotly_chart(
            _plot_bates_residual_heatmap(result),
            use_container_width=True,
            key=f"mc_v270a_bates_residuals_{ticker}_{result.get('configuration_signature')}",
        )

    left, right = st.columns(2)
    with left:
        st.plotly_chart(
            _plot_bates_champion_comparison(result),
            use_container_width=True,
            key=f"mc_v270a_bates_comparison_{ticker}_{result.get('configuration_signature')}",
        )
    with right:
        st.plotly_chart(
            _plot_bates_jump_parameter_position(result),
            use_container_width=True,
            key=f"mc_v270a_bates_jump_position_{ticker}_{result.get('configuration_signature')}",
        )

    left, right = st.columns(2)
    with left:
        st.plotly_chart(
            _plot_bates_multistart(result),
            use_container_width=True,
            key=f"mc_v270a_bates_multistart_{ticker}_{result.get('configuration_signature')}",
        )
    with right:
        st.markdown("#### Champion–challenger metrics")
        comparison_table = result.get("comparison_table")
        if isinstance(comparison_table, pd.DataFrame):
            display = comparison_table.copy()
            for column in ("train_iv_rmse", "holdout_iv_rmse", "front_wing_iv_rmse"):
                if column in display:
                    display[column] = display[column].map(_pct)
            for column in ("pseudo_aic", "pseudo_bic"):
                if column in display:
                    display[column] = display[column].map(lambda value: f"{float(value):.2f}" if pd.notna(value) else "N/A")
            st.dataframe(display, use_container_width=True, hide_index=True)

    st.markdown("#### Training and holdout validation")
    metric_table = pd.DataFrame([
        {"Sample": "TRAIN", **train_metrics},
        {"Sample": "HOLDOUT", **holdout_metrics},
    ])
    for column in ("iv_rmse", "mean_abs_iv_error"):
        if column in metric_table:
            metric_table[column] = metric_table[column].map(_pct)
    if "tv_rmse" in metric_table:
        metric_table["tv_rmse"] = metric_table["tv_rmse"].map(lambda value: f"{float(value) * 10_000.0:.3f} bp²" if pd.notna(value) else "N/A")
    if "price_rmse" in metric_table:
        metric_table["price_rmse"] = metric_table["price_rmse"].map(lambda value: f"{float(value):.4f}" if pd.notna(value) else "N/A")
    st.dataframe(metric_table, use_container_width=True, hide_index=True)

    validation_cols = st.columns(2)
    with validation_cols[0]:
        st.markdown("**Error by maturity**")
        maturity_errors = result.get("maturity_errors")
        if isinstance(maturity_errors, pd.DataFrame):
            display = maturity_errors.copy()
            for column in ("iv_rmse", "mean_abs_iv_error"):
                if column in display:
                    display[column] = display[column].map(_pct)
            st.dataframe(display, use_container_width=True, hide_index=True)
    with validation_cols[1]:
        st.markdown("**Error by moneyness bucket**")
        moneyness_errors = result.get("moneyness_errors")
        if isinstance(moneyness_errors, pd.DataFrame):
            display = moneyness_errors.copy()
            for column in ("iv_rmse", "mean_abs_iv_error"):
                if column in display:
                    display[column] = display[column].map(_pct)
            st.dataframe(display, use_container_width=True, hide_index=True)

    local_error_table = result.get("local_error_table")
    if isinstance(local_error_table, pd.DataFrame) and not local_error_table.empty:
        st.markdown("#### Local residual and front-wing governance")
        display = local_error_table.copy()
        for column in ("mean_iv_error", "iv_rmse", "max_abs_iv_error"):
            if column in display:
                display[column] = display[column].map(_pct)
        st.dataframe(display, use_container_width=True, hide_index=True)

    with st.expander("Multi-start, numerical and model-risk audit", expanded=False):
        solutions = result.get("multi_start_solutions")
        if isinstance(solutions, pd.DataFrame):
            st.markdown("**All Bates multi-start solutions**")
            st.dataframe(solutions, use_container_width=True, hide_index=True)
        crosscheck = result.get("numerical_crosscheck")
        if isinstance(crosscheck, pd.DataFrame):
            st.markdown("**Gauss–Laguerre versus adaptive quadrature**")
            st.dataframe(crosscheck, use_container_width=True, hide_index=True)
        st.markdown("**Champion metrics**")
        st.dataframe(pd.DataFrame([{"Metric": key, "Value": value} for key, value in comparison.items()]), use_container_width=True, hide_index=True)
        st.markdown("**Governance record**")
        st.dataframe(pd.DataFrame([{"Field": key, "Value": value} for key, value in result.get("governance", {}).items()]), use_container_width=True, hide_index=True)

    downloads = st.columns(8)
    signature = str(result.get("configuration_signature", "UNKNOWN"))
    downloads[0].download_button("Download fitted instruments CSV", result.get("fit_table", pd.DataFrame()).to_csv(index=False).encode("utf-8"), f"{ticker}_bates_fit_{signature}.csv", "text/csv", use_container_width=True)
    downloads[1].download_button("Download parameters CSV", result.get("parameter_table", pd.DataFrame()).to_csv(index=False).encode("utf-8"), f"{ticker}_bates_parameters_{signature}.csv", "text/csv", use_container_width=True)
    downloads[2].download_button("Download multi-start CSV", result.get("multi_start_solutions", pd.DataFrame()).to_csv(index=False).encode("utf-8"), f"{ticker}_bates_multistart_{signature}.csv", "text/csv", use_container_width=True)
    downloads[3].download_button("Download comparison CSV", result.get("comparison_table", pd.DataFrame()).to_csv(index=False).encode("utf-8"), f"{ticker}_heston_bates_comparison_{signature}.csv", "text/csv", use_container_width=True)
    downloads[4].download_button("Download maturity errors CSV", result.get("maturity_errors", pd.DataFrame()).to_csv(index=False).encode("utf-8"), f"{ticker}_bates_maturity_errors_{signature}.csv", "text/csv", use_container_width=True)
    downloads[5].download_button("Download local residuals CSV", result.get("local_error_table", pd.DataFrame()).to_csv(index=False).encode("utf-8"), f"{ticker}_bates_local_residuals_{signature}.csv", "text/csv", use_container_width=True)
    downloads[6].download_button("Download numerical audit CSV", result.get("numerical_crosscheck", pd.DataFrame()).to_csv(index=False).encode("utf-8"), f"{ticker}_bates_numerical_audit_{signature}.csv", "text/csv", use_container_width=True)

def _render_heston_q_simulation(lab: Mapping[str, Any], horizon: int) -> None:
    ticker = str(lab.get("ticker", "UNKNOWN"))
    calibration_key = f"mc_v260a_heston_result_{ticker}"
    result_key = f"mc_v261a_heston_sim_result_{ticker}"
    calibration_result = st.session_state.get(calibration_key)

    st.markdown("### Heston Q simulation & pricing validation")
    st.caption(
        "The calibrated Heston process is simulated under the risk-neutral measure. Monte Carlo prices are compared with "
        "the Fourier Heston engine to validate path discretization; this does not convert Q probabilities into physical forecasts."
    )

    available_dtes = []
    if isinstance(calibration_result, Mapping):
        fit_table = calibration_result.get("fit_table")
        if isinstance(fit_table, pd.DataFrame) and not fit_table.empty and "dte" in fit_table:
            available_dtes = sorted(set(int(value) for value in fit_table["dte"].dropna().astype(int)))
    if not available_dtes:
        available_dtes = [30]
    default_dte_index = int(np.argmin(np.abs(np.asarray(available_dtes, dtype=float) - 30.0)))

    with st.form(key=f"mc_v261a_heston_sim_form_{ticker}", border=True):
        row1 = st.columns([0.9, 1.15, 0.9, 0.9])
        with row1[0]:
            paths = st.selectbox(
                "Simulation paths",
                [2_000, 5_000, 10_000, 20_000, 50_000],
                index=2,
                key=f"mc_v261a_heston_sim_paths_{ticker}",
            )
        with row1[1]:
            scheme = st.selectbox(
                "Path scheme",
                list(HESTON_SIMULATION_SCHEMES),
                index=0,
                key=f"mc_v261a_heston_sim_scheme_{ticker}",
            )
        with row1[2]:
            steps_per_year = st.selectbox(
                "Steps per year",
                [182, 252, 365, 730],
                index=2,
                key=f"mc_v261a_heston_sim_steps_{ticker}",
            )
        with row1[3]:
            selected_dte = st.selectbox(
                "Display maturity",
                available_dtes,
                index=default_dte_index,
                format_func=lambda value: f"{int(value)}D",
                key=f"mc_v261a_heston_sim_dte_{ticker}",
            )

        row2 = st.columns([0.8, 0.8, 0.8, 0.8, 0.8])
        with row2[0]:
            seed = st.number_input(
                "Simulation seed",
                min_value=0,
                max_value=2_147_483_647,
                value=42,
                step=1,
                key=f"mc_v261a_heston_sim_seed_{ticker}",
            )
        with row2[1]:
            confidence = st.selectbox(
                "Pricing confidence",
                [0.90, 0.95, 0.99],
                index=1,
                format_func=lambda value: f"{float(value):.0%}",
                key=f"mc_v261a_heston_sim_confidence_{ticker}",
            )
        with row2[2]:
            antithetic = st.checkbox(
                "Antithetic drivers",
                value=True,
                key=f"mc_v261a_heston_sim_antithetic_{ticker}",
            )
        with row2[3]:
            analytic_qe_m = st.checkbox(
                "Analytic QE-M correction",
                value=str(scheme) == "Andersen QE-M",
                disabled=True,
                key=f"mc_v261a_heston_sim_martingale_{ticker}",
                help="Andersen QE-M enforces the conditional exponential moment analytically. No sample-mean rescaling is applied.",
            )
            martingale_correction = bool(str(scheme) == "Andersen QE-M")
        with row2[4]:
            sample_paths = st.selectbox(
                "Stored sample paths",
                [0, 20, 40, 80],
                index=2,
                key=f"mc_v261a_heston_sim_samples_{ticker}",
            )

        row3 = st.columns([0.75, 0.75, 0.75, 1.75])
        with row3[0]:
            convergence_check = st.checkbox(
                "Run replicated convergence",
                value=True,
                key=f"mc_v261a_heston_sim_convergence_{ticker}",
            )
        with row3[1]:
            convergence_paths = st.selectbox(
                "Paths / convergence grid",
                [2_500, 5_000, 10_000],
                index=1,
                disabled=not bool(convergence_check),
                key=f"mc_v261a_heston_sim_convergence_paths_{ticker}",
            )
        with row3[2]:
            convergence_replications = st.selectbox(
                "Convergence replications",
                [2, 3, 5],
                index=1,
                disabled=not bool(convergence_check),
                key=f"mc_v261a_heston_sim_convergence_replications_{ticker}",
            )
        with row3[3]:
            st.caption(
                "Andersen QE-M uses an analytic conditional-moment correction and independent spot innovation. "
                "Convergence is replication-averaged; overlapping intervals are reported as Monte Carlo-noise inconclusive."
            )

        submitted = st.form_submit_button(
            "Run governed Heston Q simulation & pricing validation",
            use_container_width=True,
            type="primary",
            key=f"mc_v261a_heston_sim_submit_{ticker}",
        )

    if submitted:
        if not isinstance(calibration_result, Mapping) or not calibration_result.get("ok"):
            st.error("Run a completed PASS/WARNING Heston Calibration before Q simulation.")
            return
        with st.spinner("Simulating the Heston variance process, validating the Q martingale and repricing governed option instruments…"):
            result = build_heston_q_simulation(
                calibration_result=calibration_result,
                paths=int(paths),
                steps_per_year=int(steps_per_year),
                scheme=str(scheme),
                seed=int(seed),
                antithetic=bool(antithetic),
                martingale_correction=bool(martingale_correction),
                confidence_level=float(confidence),
                sample_paths=int(sample_paths),
                convergence_check=bool(convergence_check),
                convergence_paths=int(convergence_paths),
                convergence_replications=int(convergence_replications),
            )
        st.session_state[result_key] = result

    result = st.session_state.get(result_key)
    if not isinstance(result, Mapping):
        if isinstance(calibration_result, Mapping) and calibration_result.get("ok"):
            st.info("Run the Heston Q simulation to validate path discretization against Fourier pricing.")
        else:
            st.info("A completed Heston Calibration is required before Q simulation.")
        return

    if result.get("calibration_signature") != (calibration_result or {}).get("configuration_signature"):
        _render_orange_warning("The Heston calibration changed after this simulation was produced. Re-run Q simulation before using the diagnostics.")

    if not result.get("ok") and result.get("status") == "FAILED":
        st.error("HESTON Q SIMULATION FAILED — " + str(result.get("reason", "unknown failure")))
        return

    distribution = result.get("distribution_summary")
    if isinstance(distribution, pd.DataFrame) and not distribution.empty and int(selected_dte) not in set(distribution["dte"].astype(int)):
        selected_dte = int(distribution.iloc[np.argmin(np.abs(distribution["dte"].to_numpy(dtype=float) - float(selected_dte)))]["dte"])
    selected_row = distribution.loc[distribution["dte"] == int(selected_dte)].iloc[0] if isinstance(distribution, pd.DataFrame) and not distribution.empty else {}
    pricing = result.get("pricing_summary", {})

    convergence_diag = result.get("convergence_diagnostic", {})
    cards = st.columns(8)
    cards[0].metric("Status", str(result.get("status", "FAILED")))
    cards[1].metric("Scheme", str(result.get("settings", {}).get("scheme", "N/A")))
    cards[2].metric("Q forward bias", f"{float(selected_row.get('forward_bias_bps', float('nan'))):+.2f} bp")
    cards[3].metric("MC–Fourier price RMSE", f"{float(pricing.get('price_rmse', float('nan'))):.4f}")
    cards[4].metric("MC–Fourier IV RMSE", _pct(pricing.get("iv_rmse")))
    cards[5].metric("Fourier CI coverage", _pct(pricing.get("confidence_coverage")))
    cards[6].metric("Variance zero states", _pct(result.get("variance_zero_observation_rate")))
    cards[7].metric("Convergence", str(convergence_diag.get("status", "NOT RUN")))
    st.caption(
        f"Paths {int(result.get('settings', {}).get('paths', 0)):,} · Steps/year {int(result.get('settings', {}).get('steps_per_year', 0))} · "
        f"Martingale method {result.get('martingale_method', 'None')} · "
        f"RMS analytic adjustment {float(result.get('rms_martingale_correction_bps', float('nan'))):.6f} bp · "
        f"Maximum observed forward bias {float(result.get('max_abs_pre_correction_forward_bias_bps', float('nan'))):.1f} bp · "
        f"Simulation signature {result.get('configuration_signature', 'N/A')}"
    )

    _render_orange_warning(
        "MEASURE GOVERNANCE — Heston terminal probabilities and option values are generated under Q. "
        "They are pricing quantities, not unbiased physical forecasts."
    )
    for blocker in result.get("blockers", []):
        _render_orange_warning("HESTON SIMULATION INELIGIBLE — " + str(blocker))
    for warning in result.get("warnings", []):
        _render_orange_warning(str(warning))

    left, right = st.columns(2)
    with left:
        st.plotly_chart(
            _plot_heston_q_spot_fan(result, int(selected_dte)),
            use_container_width=True,
            key=f"mc_v261a_heston_sim_spot_{ticker}_{result.get('configuration_signature')}_{selected_dte}",
        )
    with right:
        st.plotly_chart(
            _plot_heston_q_variance_fan(result, int(selected_dte)),
            use_container_width=True,
            key=f"mc_v261a_heston_sim_variance_{ticker}_{result.get('configuration_signature')}_{selected_dte}",
        )

    left, right = st.columns(2)
    with left:
        st.plotly_chart(
            _plot_heston_q_terminal_distribution(result, int(selected_dte)),
            use_container_width=True,
            key=f"mc_v261a_heston_sim_terminal_{ticker}_{result.get('configuration_signature')}_{selected_dte}",
        )
    with right:
        st.plotly_chart(
            _plot_heston_mc_fourier_prices(result),
            use_container_width=True,
            key=f"mc_v261a_heston_sim_price_validation_{ticker}_{result.get('configuration_signature')}",
        )

    left, right = st.columns(2)
    with left:
        st.plotly_chart(
            _plot_heston_mc_iv_residuals(result),
            use_container_width=True,
            key=f"mc_v261a_heston_sim_iv_validation_{ticker}_{result.get('configuration_signature')}",
        )
    with right:
        st.plotly_chart(
            _plot_heston_simulation_convergence(result),
            use_container_width=True,
            key=f"mc_v261a_heston_sim_convergence_chart_{ticker}_{result.get('configuration_signature')}",
        )

    st.markdown("#### Risk-neutral terminal distribution by maturity")
    if isinstance(distribution, pd.DataFrame):
        display = distribution.copy()
        for column in ("mean_return", "median_return", "var_5", "es_5", "var_1", "es_1", "prob_below_spot", "terminal_variance_zero_fraction"):
            if column in display:
                display[column] = display[column].map(_pct)
        st.dataframe(display, use_container_width=True, hide_index=True)

    st.markdown("#### Monte Carlo versus Fourier pricing validation")
    pricing_table = result.get("pricing_validation")
    if isinstance(pricing_table, pd.DataFrame):
        display = pricing_table.copy()
        for column in ("target_iv", "fourier_iv", "mc_iv", "mc_fourier_iv_error", "mc_target_iv_error"):
            if column in display:
                display[column] = display[column].map(_pct)
        st.dataframe(display, use_container_width=True, hide_index=True)

    validation_cols = st.columns(2)
    with validation_cols[0]:
        st.markdown("**Pricing error by maturity**")
        maturity = result.get("maturity_validation")
        if isinstance(maturity, pd.DataFrame):
            display = maturity.copy()
            for column in ("iv_rmse", "coverage"):
                if column in display:
                    display[column] = display[column].map(_pct)
            st.dataframe(display, use_container_width=True, hide_index=True)
    with validation_cols[1]:
        st.markdown("**Pricing error by moneyness bucket**")
        bucket = result.get("moneyness_validation")
        if isinstance(bucket, pd.DataFrame):
            display = bucket.copy()
            for column in ("iv_rmse", "coverage"):
                if column in display:
                    display[column] = display[column].map(_pct)
            st.dataframe(display, use_container_width=True, hide_index=True)

    convergence = result.get("convergence")
    if isinstance(convergence, pd.DataFrame) and not convergence.empty:
        st.markdown("#### Replicated time-step convergence audit")
        st.info(str(result.get("convergence_diagnostic", {}).get("reason", "No convergence interpretation available.")))
        st.dataframe(convergence, use_container_width=True, hide_index=True)

    with st.expander("Heston Q simulation governance and raw audit", expanded=False):
        st.dataframe(pd.DataFrame([{"Field": key, "Value": value} for key, value in result.get("governance", {}).items()]), use_container_width=True, hide_index=True)
        st.markdown("**Governed carry nodes**")
        st.dataframe(result.get("carry_nodes", pd.DataFrame()), use_container_width=True, hide_index=True)
        st.markdown("**Variance-process diagnostics**")
        st.dataframe(result.get("variance_diagnostics", pd.DataFrame()), use_container_width=True, hide_index=True)

    downloads = st.columns(6)
    signature = str(result.get("configuration_signature", "UNKNOWN"))
    downloads[0].download_button("Download pricing validation CSV", result.get("pricing_validation", pd.DataFrame()).to_csv(index=False).encode("utf-8"), f"{ticker}_heston_q_pricing_{signature}.csv", "text/csv", use_container_width=True)
    downloads[1].download_button("Download distribution CSV", result.get("distribution_summary", pd.DataFrame()).to_csv(index=False).encode("utf-8"), f"{ticker}_heston_q_distribution_{signature}.csv", "text/csv", use_container_width=True)
    downloads[2].download_button("Download path quantiles CSV", result.get("path_quantiles", pd.DataFrame()).to_csv(index=False).encode("utf-8"), f"{ticker}_heston_q_paths_{signature}.csv", "text/csv", use_container_width=True)
    downloads[3].download_button("Download variance diagnostics CSV", result.get("variance_diagnostics", pd.DataFrame()).to_csv(index=False).encode("utf-8"), f"{ticker}_heston_q_variance_{signature}.csv", "text/csv", use_container_width=True)
    downloads[4].download_button("Download convergence CSV", result.get("convergence", pd.DataFrame()).to_csv(index=False).encode("utf-8"), f"{ticker}_heston_q_convergence_{signature}.csv", "text/csv", use_container_width=True)
    downloads[5].download_button("Download terminal samples CSV", result.get("terminal_spot_samples", pd.DataFrame()).to_csv(index=False).encode("utf-8"), f"{ticker}_heston_q_terminal_samples_{signature}.csv", "text/csv", use_container_width=True)


def _render_bates_q_simulation(lab: Mapping[str, Any], horizon: int) -> None:
    ticker = str(lab.get("ticker", "UNKNOWN"))
    bates_calibration_key = f"mc_v270a_bates_result_{ticker}"
    heston_calibration_key = f"mc_v260a_heston_result_{ticker}"
    result_key = f"mc_v271_bates_sim_result_{ticker}"
    bates_calibration = st.session_state.get(bates_calibration_key)
    heston_calibration = st.session_state.get(heston_calibration_key)
    source_champion_status = (bates_calibration or {}).get("champion_status") if isinstance(bates_calibration, Mapping) else None
    role_labels = _bates_role_labels(source_champion_status)

    st.markdown("### Bates Q simulation & pricing validation")
    st.caption(
        f"{role_labels['caption']} with Andersen stochastic variance and an exact compound-Poisson lognormal jump aggregate. "
        "Monte Carlo prices are compared with Fourier Bates prices, while Heston remains the continuous benchmark."
    )

    available_dtes: list[int] = []
    if isinstance(bates_calibration, Mapping):
        fit_table = bates_calibration.get("fit_table")
        if isinstance(fit_table, pd.DataFrame) and not fit_table.empty and "dte" in fit_table:
            available_dtes = sorted(set(int(value) for value in fit_table["dte"].dropna().astype(int)))
    if not available_dtes:
        available_dtes = [30]
    default_dte_index = int(np.argmin(np.abs(np.asarray(available_dtes, dtype=float) - 30.0)))

    with st.form(key=f"mc_v271_bates_sim_form_{ticker}", border=True):
        row1 = st.columns([0.9, 1.15, 0.9, 0.9])
        with row1[0]:
            paths = st.selectbox(
                "Simulation paths",
                [2_000, 5_000, 10_000, 20_000, 50_000],
                index=2,
                key=f"mc_v271_bates_sim_paths_{ticker}",
            )
        with row1[1]:
            scheme = st.selectbox(
                "Path scheme",
                list(BATES_SIMULATION_SCHEMES),
                index=0,
                key=f"mc_v271_bates_sim_scheme_{ticker}",
            )
        with row1[2]:
            steps_per_year = st.selectbox(
                "Steps per year",
                [182, 252, 365, 730],
                index=2,
                key=f"mc_v271_bates_sim_steps_{ticker}",
            )
        with row1[3]:
            selected_dte = st.selectbox(
                "Display maturity",
                available_dtes,
                index=default_dte_index,
                format_func=lambda value: f"{int(value)}D",
                key=f"mc_v271_bates_sim_dte_{ticker}",
            )

        row2 = st.columns([0.8, 0.8, 0.9, 0.9, 0.8])
        with row2[0]:
            seed = st.number_input(
                "Simulation seed",
                min_value=0,
                max_value=2_147_483_647,
                value=42,
                step=1,
                key=f"mc_v271_bates_sim_seed_{ticker}",
            )
        with row2[1]:
            confidence = st.selectbox(
                "Pricing confidence",
                [0.90, 0.95, 0.99],
                index=1,
                format_func=lambda value: f"{float(value):.0%}",
                key=f"mc_v271_bates_sim_confidence_{ticker}",
            )
        with row2[2]:
            antithetic = st.checkbox(
                "Antithetic diffusion / jump-size normals",
                value=True,
                key=f"mc_v271_bates_sim_antithetic_{ticker}",
                help="Poisson counts remain exact independent draws; Gaussian diffusion and jump-size innovations use antithetic pairing.",
            )
        with row2[3]:
            analytic_qe_m = st.checkbox(
                "Analytic QE-M correction",
                value=str(scheme) == "Andersen QE-M",
                disabled=True,
                key=f"mc_v271_bates_sim_martingale_{ticker}",
                help="The diffusion uses Andersen's conditional exponential-moment correction; the jump drift uses the exact Bates compensator.",
            )
            martingale_correction = bool(str(scheme) == "Andersen QE-M")
        with row2[4]:
            sample_paths = st.selectbox(
                "Stored sample paths",
                [0, 20, 40, 80],
                index=2,
                key=f"mc_v271_bates_sim_samples_{ticker}",
            )

        row3 = st.columns([0.75, 0.75, 0.75, 0.75, 1.0])
        with row3[0]:
            time_convergence = st.checkbox(
                "Replicated time-grid convergence",
                value=True,
                key=f"mc_v271_bates_sim_time_convergence_{ticker}",
            )
        with row3[1]:
            convergence_paths = st.selectbox(
                "Paths / time grid",
                [2_500, 5_000, 10_000],
                index=1,
                disabled=not bool(time_convergence),
                key=f"mc_v271_bates_sim_convergence_paths_{ticker}",
            )
        with row3[2]:
            convergence_replications = st.selectbox(
                "Time-grid replications",
                [2, 3, 5],
                index=1,
                disabled=not bool(time_convergence),
                key=f"mc_v271_bates_sim_convergence_replications_{ticker}",
            )
        with row3[3]:
            path_convergence = st.checkbox(
                "Replicated path-count convergence",
                value=True,
                key=f"mc_v271_bates_sim_path_convergence_{ticker}",
            )
        with row3[4]:
            path_convergence_base = st.selectbox(
                "Base paths / precision grid",
                [2_500, 5_000, 10_000],
                index=1,
                disabled=not bool(path_convergence),
                key=f"mc_v271_bates_sim_path_base_{ticker}",
            )

        row4 = st.columns([0.75, 0.75, 2.0])
        with row4[0]:
            path_convergence_replications = st.selectbox(
                "Path-grid replications",
                [2, 3, 5],
                index=1,
                disabled=not bool(path_convergence),
                key=f"mc_v271_bates_sim_path_replications_{ticker}",
            )
        with row4[1]:
            simulate_heston = st.checkbox(
                "Simulate Heston benchmark with common diffusion seed",
                value=True,
                key=f"mc_v271_bates_sim_heston_benchmark_{ticker}",
            )
        with row4[2]:
            st.caption(
                "Bates uses the exact per-step compound-Poisson aggregate and risk-neutral jump compensator. "
                "Heston and Bates share diffusion seeds; the jump stream is independent."
            )

        submitted = st.form_submit_button(
            "Run governed Bates Q simulation & pricing validation",
            use_container_width=True,
            type="primary",
            key=f"mc_v271_bates_sim_submit_{ticker}",
        )

    if submitted:
        if not isinstance(bates_calibration, Mapping) or not bates_calibration.get("ok"):
            st.error("Run a completed PASS/WARNING Bates Calibration before Q simulation.")
            return
        if str(bates_calibration.get("champion_status")) != "BATES_CHAMPION":
            _render_orange_warning(
                f"The source Bates selection is {bates_calibration.get('champion_status')}. "
                "The simulation can run, but it remains challenger/research output. "
                f"Reason: {_bates_research_reason({}, bates_calibration)}"
            )
        with st.spinner("Simulating Bates diffusion and jumps, validating the Q martingale, repricing option instruments and comparing Heston/Bates tails…"):
            result = build_bates_q_simulation(
                bates_calibration_result=bates_calibration,
                heston_calibration_result=heston_calibration if isinstance(heston_calibration, Mapping) else None,
                paths=int(paths),
                steps_per_year=int(steps_per_year),
                scheme=str(scheme),
                seed=int(seed),
                antithetic=bool(antithetic),
                martingale_correction=bool(martingale_correction),
                confidence_level=float(confidence),
                sample_paths=int(sample_paths),
                time_convergence_check=bool(time_convergence),
                convergence_paths=int(convergence_paths),
                convergence_replications=int(convergence_replications),
                path_convergence_check=bool(path_convergence),
                path_convergence_base_paths=int(path_convergence_base),
                path_convergence_replications=int(path_convergence_replications),
                simulate_heston_benchmark=bool(simulate_heston),
            )
        st.session_state[result_key] = result

    result = st.session_state.get(result_key)
    if not isinstance(result, Mapping):
        if isinstance(bates_calibration, Mapping) and bates_calibration.get("ok"):
            st.info("Run the Bates Q simulation to validate compound-jump paths against Fourier Bates pricing.")
        else:
            st.info("A completed Bates Calibration is required before Bates Q simulation.")
        return

    if result.get("bates_calibration_signature") != (bates_calibration or {}).get("configuration_signature"):
        _render_orange_warning("The Bates calibration changed after this simulation was produced. Re-run Bates Q simulation before using the diagnostics.")
    if result.get("heston_calibration_signature") and isinstance(heston_calibration, Mapping) and result.get("heston_calibration_signature") != heston_calibration.get("configuration_signature"):
        _render_orange_warning("The Heston benchmark calibration changed after this simulation was produced. Re-run Bates Q simulation for a matched comparison.")

    if not result.get("ok") and result.get("status") == "FAILED":
        st.error("BATES Q SIMULATION FAILED — " + str(result.get("reason", "unknown failure")))
        return

    distribution = result.get("distribution_summary")
    if isinstance(distribution, pd.DataFrame) and not distribution.empty and int(selected_dte) not in set(distribution["dte"].astype(int)):
        selected_dte = int(distribution.iloc[np.argmin(np.abs(distribution["dte"].to_numpy(dtype=float) - float(selected_dte)))]["dte"])
    selected_row = distribution.loc[distribution["dte"] == int(selected_dte)].iloc[0] if isinstance(distribution, pd.DataFrame) and not distribution.empty else {}
    pricing = result.get("pricing_summary", {})
    time_diag = result.get("time_convergence_diagnostic", {})
    path_diag = result.get("path_convergence_diagnostic", {})
    source_champion_status = result.get("bates_champion_status", source_champion_status)
    role_labels = _bates_role_labels(source_champion_status)

    cards = st.columns(9)
    cards[0].metric("Status", str(result.get("status", "FAILED")))
    cards[1].metric("Scheme", str(result.get("settings", {}).get("scheme", "N/A")))
    cards[2].metric(
        "Q forward bias",
        f"{float(selected_row.get('forward_bias_bps', float('nan'))):+.2f} bp",
        delta=f"z={float(selected_row.get('forward_bias_z', float('nan'))):+.2f}",
    )
    cards[3].metric("MC–Fourier price RMSE", f"{float(pricing.get('price_rmse', float('nan'))):.4f}")
    cards[4].metric("MC–Fourier IV RMSE", _pct(pricing.get("iv_rmse")))
    cards[5].metric("Fourier CI coverage", _pct(pricing.get("confidence_coverage")))
    cards[6].metric("P(at least one jump)", _pct(selected_row.get("probability_at_least_one_jump")))
    cards[7].metric("Time convergence", str(time_diag.get("status", "NOT RUN")))
    cards[8].metric("Path convergence", str(path_diag.get("status", "NOT RUN")))

    parameters = result.get("parameters", {})
    st.caption(
        f"Paths {int(result.get('settings', {}).get('paths', 0)):,} · Steps/year {int(result.get('settings', {}).get('steps_per_year', 0))} · "
        f"λJ {float(parameters.get('jump_intensity', float('nan'))):.4f}/y · μJ {float(parameters.get('jump_mean', float('nan'))):+.4f} · "
        f"σJ {float(parameters.get('jump_volatility', float('nan'))):.4f} · Jump compensator {float(result.get('jump_compensator', float('nan'))):+.5f} · "
        f"Martingale {result.get('martingale_method', 'N/A')} · Simulation signature {result.get('configuration_signature', 'N/A')}"
    )

    _render_orange_warning(
        "MEASURE GOVERNANCE — Bates jump intensity, jump-size distribution, terminal probabilities and option values are Q-measure pricing quantities. "
        "They are not physical event forecasts."
    )
    if str(source_champion_status) != "BATES_CHAMPION":
        _render_orange_warning(
            f"SOURCE MODEL ROLE — {role_labels['noun']}. "
            f"Reason: {_bates_research_reason(result, bates_calibration if isinstance(bates_calibration, Mapping) else None)}"
        )
    low_vega_count = int(pricing.get("low_vega_amplification_count", 0) or 0)
    if low_vega_count > 0:
        st.info(
            f"LOW-VEGA IV DIAGNOSTIC — {low_vega_count} large MC–Fourier IV residual(s) are classified as "
            "low-vega amplification because the corresponding price differences remain inside Monte Carlo sampling uncertainty."
        )
    for blocker in result.get("blockers", []):
        _render_orange_warning("BATES SIMULATION INELIGIBLE — " + str(blocker))
    for warning in result.get("warnings", []):
        _render_orange_warning(str(warning))

    left, right = st.columns(2)
    with left:
        st.plotly_chart(
            _plot_bates_q_spot_fan(result, int(selected_dte)),
            use_container_width=True,
            key=f"mc_v271_bates_sim_spot_{ticker}_{result.get('configuration_signature')}_{selected_dte}",
        )
    with right:
        st.plotly_chart(
            _plot_bates_jump_process(result, int(selected_dte)),
            use_container_width=True,
            key=f"mc_v271_bates_sim_jump_process_{ticker}_{result.get('configuration_signature')}_{selected_dte}",
        )

    left, right = st.columns(2)
    with left:
        st.plotly_chart(
            _plot_bates_terminal_comparison(result, int(selected_dte)),
            use_container_width=True,
            key=f"mc_v271_bates_sim_terminal_{ticker}_{result.get('configuration_signature')}_{selected_dte}",
        )
    with right:
        st.plotly_chart(
            _plot_bates_mc_fourier_prices(result),
            use_container_width=True,
            key=f"mc_v271_bates_sim_price_validation_{ticker}_{result.get('configuration_signature')}",
        )

    left, right = st.columns(2)
    with left:
        st.plotly_chart(
            _plot_bates_mc_iv_residuals(result),
            use_container_width=True,
            key=f"mc_v271_bates_sim_iv_validation_{ticker}_{result.get('configuration_signature')}",
        )
    with right:
        st.plotly_chart(
            _plot_bates_risk_comparison(result),
            use_container_width=True,
            key=f"mc_v271_bates_sim_risk_comparison_{ticker}_{result.get('configuration_signature')}",
        )

    left, right = st.columns(2)
    with left:
        st.plotly_chart(
            _plot_bates_convergence(result, "time"),
            use_container_width=True,
            key=f"mc_v271_bates_sim_time_convergence_chart_{ticker}_{result.get('configuration_signature')}",
        )
    with right:
        st.plotly_chart(
            _plot_bates_convergence(result, "paths"),
            use_container_width=True,
            key=f"mc_v271_bates_sim_path_convergence_chart_{ticker}_{result.get('configuration_signature')}",
        )

    st.markdown("#### Bates risk-neutral terminal distribution by maturity")
    if isinstance(distribution, pd.DataFrame):
        display = distribution.copy()
        for column in (
            "mean_return", "median_return", "var_5", "es_5", "var_1", "es_1", "prob_below_spot",
            "terminal_variance_zero_fraction", "probability_at_least_one_jump", "probability_two_or_more_jumps",
        ):
            if column in display:
                display[column] = display[column].map(_pct)
        st.dataframe(display, use_container_width=True, hide_index=True)

    table_cols = st.columns(2)
    with table_cols[0]:
        st.markdown("**Jump-count diagnostics**")
        jump_table = result.get("jump_count_summary")
        if isinstance(jump_table, pd.DataFrame):
            display = jump_table.copy()
            for column in ("probability_zero_jumps", "probability_at_least_one_jump", "probability_two_or_more_jumps"):
                if column in display:
                    display[column] = display[column].map(_pct)
            st.dataframe(display, use_container_width=True, hide_index=True)
    with table_cols[1]:
        st.markdown("**Jump attribution versus Bates diffusion-only counterfactual**")
        attribution = result.get("jump_attribution")
        if isinstance(attribution, pd.DataFrame):
            display = attribution.copy()
            for column in (
                "bates_mean_return", "diffusion_only_mean_return", "jump_mean_return_contribution",
                "bates_var_5", "diffusion_only_var_5", "jump_var_5_contribution",
                "bates_es_5", "diffusion_only_es_5", "jump_es_5_contribution", "probability_at_least_one_jump",
            ):
                if column in display:
                    display[column] = display[column].map(_pct)
            st.dataframe(display, use_container_width=True, hide_index=True)

    comparison = result.get("heston_bates_comparison")
    if isinstance(comparison, pd.DataFrame) and not comparison.empty:
        st.markdown(f"#### {role_labels['comparison_title']}")
        st.dataframe(_format_heston_bates_comparison_table(comparison), use_container_width=True, hide_index=True)

    st.markdown("#### Bates Monte Carlo versus Fourier pricing validation")
    pricing_table = result.get("pricing_validation")
    if isinstance(pricing_table, pd.DataFrame):
        display = pricing_table.copy()
        for column in ("target_iv", "fourier_iv", "mc_iv", "mc_fourier_iv_error", "mc_target_iv_error"):
            if column in display:
                display[column] = display[column].astype(object).map(_pct)
        if "vega_per_iv_point" in display:
            display["vega_per_iv_point"] = display["vega_per_iv_point"].astype(object).map(lambda value: _number(value, 5))
        if "iv_error_pp" in display:
            display["iv_error_pp"] = display["iv_error_pp"].astype(object).map(lambda value: f"{float(value):+.2f} pp" if np.isfinite(float(value)) else "N/A")
        st.dataframe(display, use_container_width=True, hide_index=True)

        diagnostic_rows = pricing_table[
            pricing_table.get("iv_residual_diagnostic", pd.Series(index=pricing_table.index, dtype=object)).astype(str).ne("PASS")
        ].copy()
        if not diagnostic_rows.empty:
            st.markdown("**IV residual interpretation audit**")
            audit_columns = [
                column for column in (
                    "sample_role", "expiration", "dte", "strike", "option_type", "moneyness_bucket",
                    "mc_fourier_price_error", "mc_standard_error", "mc_fourier_z_score",
                    "mc_fourier_iv_error", "iv_error_pp", "vega_per_iv_point", "iv_residual_diagnostic",
                ) if column in diagnostic_rows
            ]
            audit = diagnostic_rows[audit_columns].copy()
            if "mc_fourier_iv_error" in audit:
                audit["mc_fourier_iv_error"] = audit["mc_fourier_iv_error"].astype(object).map(_pct)
            if "iv_error_pp" in audit:
                audit["iv_error_pp"] = audit["iv_error_pp"].astype(object).map(lambda value: f"{float(value):+.2f} pp" if np.isfinite(float(value)) else "N/A")
            if "vega_per_iv_point" in audit:
                audit["vega_per_iv_point"] = audit["vega_per_iv_point"].astype(object).map(lambda value: _number(value, 5))
            st.dataframe(audit, use_container_width=True, hide_index=True)

    validation_cols = st.columns(2)
    with validation_cols[0]:
        st.markdown("**Pricing error by maturity**")
        maturity = result.get("maturity_validation")
        if isinstance(maturity, pd.DataFrame):
            display = maturity.copy()
            for column in ("iv_rmse", "coverage"):
                if column in display:
                    display[column] = display[column].map(_pct)
            st.dataframe(display, use_container_width=True, hide_index=True)
    with validation_cols[1]:
        st.markdown("**Pricing error by moneyness bucket**")
        bucket = result.get("moneyness_validation")
        if isinstance(bucket, pd.DataFrame):
            display = bucket.copy()
            for column in ("iv_rmse", "coverage"):
                if column in display:
                    display[column] = display[column].map(_pct)
            st.dataframe(display, use_container_width=True, hide_index=True)

    for label, table_key, diag_key in (
        ("Replicated time-step convergence audit", "time_convergence", "time_convergence_diagnostic"),
        ("Replicated path-count convergence audit", "path_convergence", "path_convergence_diagnostic"),
    ):
        table = result.get(table_key)
        if isinstance(table, pd.DataFrame) and not table.empty:
            st.markdown(f"#### {label}")
            st.info(str(result.get(diag_key, {}).get("reason", "No convergence interpretation available.")))
            st.dataframe(table, use_container_width=True, hide_index=True)

    with st.expander("Bates Q simulation governance and raw audit", expanded=False):
        st.dataframe(pd.DataFrame([{"Field": key, "Value": value} for key, value in result.get("governance", {}).items()]), use_container_width=True, hide_index=True)
        st.markdown("**Governed carry nodes**")
        st.dataframe(result.get("carry_nodes", pd.DataFrame()), use_container_width=True, hide_index=True)
        st.markdown("**Variance-process diagnostics**")
        st.dataframe(result.get("variance_diagnostics", pd.DataFrame()), use_container_width=True, hide_index=True)
        st.markdown("**Jump-process diagnostics**")
        st.dataframe(result.get("jump_diagnostics", pd.DataFrame()), use_container_width=True, hide_index=True)
        raw_time = result.get("time_convergence_replications_raw")
        if isinstance(raw_time, pd.DataFrame) and not raw_time.empty:
            st.markdown("**Raw time-grid replications**")
            st.dataframe(raw_time, use_container_width=True, hide_index=True)
        raw_paths = result.get("path_convergence_replications_raw")
        if isinstance(raw_paths, pd.DataFrame) and not raw_paths.empty:
            st.markdown("**Raw path-count replications**")
            st.dataframe(raw_paths, use_container_width=True, hide_index=True)

    downloads = st.columns(7)
    signature = str(result.get("configuration_signature", "UNKNOWN"))
    downloads[0].download_button("Download pricing validation CSV", result.get("pricing_validation", pd.DataFrame()).to_csv(index=False).encode("utf-8"), f"{ticker}_bates_q_pricing_{signature}.csv", "text/csv", use_container_width=True)
    downloads[1].download_button("Download distribution CSV", result.get("distribution_summary", pd.DataFrame()).to_csv(index=False).encode("utf-8"), f"{ticker}_bates_q_distribution_{signature}.csv", "text/csv", use_container_width=True)
    downloads[2].download_button("Download jump diagnostics CSV", result.get("jump_count_summary", pd.DataFrame()).to_csv(index=False).encode("utf-8"), f"{ticker}_bates_q_jumps_{signature}.csv", "text/csv", use_container_width=True)
    downloads[3].download_button("Download Heston/Bates comparison CSV", result.get("heston_bates_comparison", pd.DataFrame()).to_csv(index=False).encode("utf-8"), f"{ticker}_heston_bates_q_comparison_{signature}.csv", "text/csv", use_container_width=True)
    downloads[4].download_button("Download path quantiles CSV", result.get("path_quantiles", pd.DataFrame()).to_csv(index=False).encode("utf-8"), f"{ticker}_bates_q_paths_{signature}.csv", "text/csv", use_container_width=True)
    downloads[5].download_button("Download convergence CSV", pd.concat([
        result.get("time_convergence", pd.DataFrame()).assign(convergence_type="TIME"),
        result.get("path_convergence", pd.DataFrame()).assign(convergence_type="PATHS"),
    ], ignore_index=True, sort=False).to_csv(index=False).encode("utf-8"), f"{ticker}_bates_q_convergence_{signature}.csv", "text/csv", use_container_width=True)
    downloads[6].download_button("Download terminal samples CSV", result.get("terminal_spot_samples", pd.DataFrame()).to_csv(index=False).encode("utf-8"), f"{ticker}_bates_q_terminal_samples_{signature}.csv", "text/csv", use_container_width=True)


def _render_model_risk_numerical_governance(lab: Mapping[str, Any], horizon: int) -> None:
    ticker = str(lab.get("ticker", "UNKNOWN"))
    dataset_key = f"mc_v255_calibration_dataset_result_{ticker}"
    heston_key = f"mc_v260a_heston_result_{ticker}"
    bates_key = f"mc_v270a_bates_result_{ticker}"
    result_key = f"mc_v280_model_risk_result_{ticker}"
    history_key = f"mc_v280_model_risk_history_{ticker}"

    dataset_result = st.session_state.get(dataset_key)
    heston_result = st.session_state.get(heston_key)
    bates_result = st.session_state.get(bates_key)

    st.markdown("### Model Risk & Numerical Governance")
    st.caption(
        "This layer independently challenges the frozen Heston/Bates calibrations through maturity-stratified quote bootstrap, "
        "local identifiability diagnostics, conditional cost sensitivity and leave-one-maturity recalibration. It does not change "
        "the source parameters or promote a model by itself."
    )

    with st.form(key=f"mc_v280_model_risk_form_{ticker}", border=True):
        row1 = st.columns([0.8, 0.8, 0.8, 0.8, 0.8])
        with row1[0]:
            bootstrap_draws = st.selectbox(
                "Bootstrap recalibrations",
                [8, 12, 20, 40, 80],
                index=3,
                key=f"mc_v280_bootstrap_draws_{ticker}",
            )
        with row1[1]:
            confidence = st.selectbox(
                "Parameter interval confidence",
                [0.90, 0.95, 0.99],
                index=1,
                format_func=lambda value: f"{value:.0%}",
                key=f"mc_v280_bootstrap_confidence_{ticker}",
            )
        with row1[2]:
            max_nfev = st.selectbox(
                "Max evaluations / draw",
                [40, 80, 120, 200],
                index=2,
                key=f"mc_v280_bootstrap_nfev_{ticker}",
            )
        with row1[3]:
            quadrature_nodes = st.selectbox(
                "Fourier nodes",
                [32, 48, 64, 96],
                index=2,
                key=f"mc_v280_nodes_{ticker}",
            )
        with row1[4]:
            seed = st.number_input(
                "Governance seed",
                min_value=0,
                max_value=2_147_483_647,
                value=42,
                step=1,
                key=f"mc_v280_seed_{ticker}",
            )

        row2 = st.columns([0.85, 0.85, 0.85, 0.85, 0.85])
        with row2[0]:
            run_jackknife = st.checkbox(
                "Run leave-one-maturity tests",
                value=True,
                key=f"mc_v280_jackknife_{ticker}",
            )
        with row2[1]:
            profile_points = st.selectbox(
                "Cost-profile grid points",
                [5, 7, 9, 13],
                index=1,
                key=f"mc_v280_profile_points_{ticker}",
            )
        with row2[2]:
            profile_span = st.selectbox(
                "Cost-profile local span",
                [0.10, 0.20, 0.30, 0.40],
                index=1,
                format_func=lambda value: f"±{value:.0%} of bound span",
                key=f"mc_v280_profile_span_{ticker}",
            )
        with row2[3]:
            minimum_success = st.selectbox(
                "Minimum recalibration success",
                [0.70, 0.80, 0.90, 0.95],
                index=1,
                format_func=lambda value: f"{value:.0%}",
                key=f"mc_v280_min_success_{ticker}",
            )
        with row2[4]:
            production_selection = st.selectbox(
                "Minimum Bates selection frequency",
                [0.60, 0.70, 0.80, 0.90],
                index=1,
                format_func=lambda value: f"{value:.0%}",
                key=f"mc_v280_selection_gate_{ticker}",
            )

        row3 = st.columns([0.8, 0.8, 2.0])
        with row3[0]:
            max_interval_width = st.selectbox(
                "Maximum normalized parameter CI width",
                [0.35, 0.50, 0.60, 0.80],
                index=2,
                key=f"mc_v280_interval_gate_{ticker}",
            )
        with row3[1]:
            max_maturity_sensitivity = st.selectbox(
                "Maximum leave-one-maturity shift",
                [0.20, 0.30, 0.35, 0.50],
                index=2,
                key=f"mc_v280_maturity_gate_{ticker}",
            )
        with row3[2]:
            st.caption(
                "Bootstrap draws preserve the number of quotes inside each expiration and recalibrate from the governed source solution. "
                "Intervals quantify quote-sample instability; they do not cover every possible structural or market-data uncertainty. "
                "At least 40 draws are required for a robust production-evidence gate; 80 draws form the preferred final evidence tier."
            )

        submitted = st.form_submit_button(
            "Run final model-risk and numerical governance",
            use_container_width=True,
            type="primary",
            key=f"mc_v280_submit_{ticker}",
        )

    if submitted:
        if not isinstance(dataset_result, Mapping) or not dataset_result.get("ok"):
            st.error("Build a PASS/WARNING Calibration Dataset before model-risk governance.")
            return
        if not isinstance(heston_result, Mapping) or not heston_result.get("parameters"):
            st.error("Run the governed Heston calibration first.")
            return
        if not isinstance(bates_result, Mapping) or not bates_result.get("parameters"):
            st.error("Run the governed Bates calibration first.")
            return
        with st.spinner("Running quote-resample recalibrations, identifiability diagnostics, cost profiles and maturity sensitivity tests…"):
            result = build_model_risk_governance(
                dataset_result=dataset_result,
                heston_result=heston_result,
                bates_result=bates_result,
                bootstrap_draws=int(bootstrap_draws),
                bootstrap_confidence=float(confidence),
                max_nfev_per_draw=int(max_nfev),
                quadrature_nodes=int(quadrature_nodes),
                seed=int(seed),
                run_maturity_jackknife=bool(run_jackknife),
                profile_grid_points=int(profile_points),
                profile_span_fraction=float(profile_span),
                minimum_bootstrap_success_rate=float(minimum_success),
                production_bates_selection_probability=float(production_selection),
                maximum_normalized_interval_width=float(max_interval_width),
                maximum_maturity_sensitivity=float(max_maturity_sensitivity),
            )
        st.session_state[result_key] = result
        if isinstance(result, Mapping) and result.get("configuration_signature"):
            history = list(st.session_state.get(history_key, []))
            snapshot = {
                "run_timestamp_utc": pd.Timestamp.utcnow().isoformat(),
                "configuration_signature": result.get("configuration_signature"),
                "status": result.get("status"),
                "recommended_role": result.get("recommended_role"),
                "source_champion_status": result.get("source_champion_status"),
                "heston_success_rate": result.get("bootstrap_summary", {}).get("heston_success_rate"),
                "bates_success_rate": result.get("bootstrap_summary", {}).get("bates_success_rate"),
                "bates_preference_probability": result.get("bootstrap_summary", {}).get("bates_selection_probability"),
                "evidence_tier": result.get("decision_diagnostics", {}).get("evidence_tier"),
                "relative_model_preference": result.get("decision_diagnostics", {}).get("relative_model_preference"),
                "absolute_production_status": result.get("decision_diagnostics", {}).get("absolute_production_status"),
            }
            if not history or history[-1].get("configuration_signature") != snapshot["configuration_signature"]:
                history.append(snapshot)
            st.session_state[history_key] = history[-100:]

    result = st.session_state.get(result_key)
    if not isinstance(result, Mapping):
        st.info("Run this final governance layer after completing the calibration dataset, Heston calibration and Bates calibration.")
        return
    if result.get("status") == "FAILED":
        st.error("MODEL-RISK GOVERNANCE FAILED — " + str(result.get("reason", "unknown failure")))
        return

    summary = result.get("bootstrap_summary", {})
    ident = result.get("identifiability_summary", pd.DataFrame())
    h_ident = ident[ident["model"] == "Heston"].iloc[0] if isinstance(ident, pd.DataFrame) and not ident.empty and (ident["model"] == "Heston").any() else {}
    b_ident = ident[ident["model"] == "Bates"].iloc[0] if isinstance(ident, pd.DataFrame) and not ident.empty and (ident["model"] == "Bates").any() else {}
    maturity = result.get("maturity_sensitivity", pd.DataFrame())
    max_maturity = float(pd.to_numeric(maturity.get("maximum_normalized_parameter_shift", pd.Series(dtype=float)), errors="coerce").max()) if isinstance(maturity, pd.DataFrame) and not maturity.empty else 0.0

    diagnostics = result.get("decision_diagnostics", {})
    cards = st.columns(8)
    cards[0].metric("Final status", _model_risk_status_label(result.get("status")))
    cards[1].metric("Recommended role", _model_risk_role_label(result.get("recommended_role")))
    cards[2].metric("Heston bootstrap success", _pct(summary.get("heston_success_rate")))
    cards[3].metric("Bates bootstrap success", _pct(summary.get("bates_success_rate")))
    cards[4].metric("Bates preferred across draws", _pct(summary.get("bates_selection_probability")))
    cards[5].metric("Heston rank", f"{int(h_ident.get('effective_rank', 0))}/{int(h_ident.get('parameter_count', 5))}" if hasattr(h_ident, 'get') else "N/A")
    cards[6].metric("Bates rank", f"{int(b_ident.get('effective_rank', 0))}/{int(b_ident.get('parameter_count', 8))}" if hasattr(b_ident, 'get') else "N/A")
    cards[7].metric("Max maturity shift", _pct(max_maturity))
    st.caption(
        f"Version {result.get('version')} · Source champion {result.get('source_champion_status')} · "
        f"Draws {summary.get('draws', 0)} · Evidence tier {diagnostics.get('evidence_tier', 'N/A')} · "
        f"Governance signature {result.get('configuration_signature', 'N/A')}"
    )

    largest_bates = diagnostics.get("largest_bates_interval", {}) or {}
    largest_jump = diagnostics.get("largest_jump_interval", {}) or {}
    largest_maturity = diagnostics.get("largest_maturity_sensitivity", {}) or {}
    decision_rows = [
        {"Decision dimension": "Relative model preference", "Result": diagnostics.get("relative_model_preference", "N/A"), "Interpretation": "Preference across bootstrap challenger tests; not an absolute production approval."},
        {"Decision dimension": "Absolute production status", "Result": diagnostics.get("absolute_production_status", "N/A"), "Interpretation": "Terminal governance decision after calibration, uncertainty, bounds and maturity-sensitivity gates."},
        {"Decision dimension": "Evidence tier", "Result": diagnostics.get("evidence_tier", "N/A"), "Interpretation": f"{summary.get('draws', 0)} bootstrap recalibrations."},
        {"Decision dimension": "Largest Bates parameter uncertainty", "Result": f"{largest_bates.get('parameter', 'N/A')} · {_pct(largest_bates.get('normalized_interval_width'))}", "Interpretation": "Bootstrap CI width relative to the governed parameter range."},
        {"Decision dimension": "Largest jump-parameter uncertainty", "Result": f"{largest_jump.get('parameter', 'N/A')} · {_pct(largest_jump.get('normalized_interval_width'))}", "Interpretation": "Largest uncertainty among jump intensity, mean and volatility."},
        {"Decision dimension": "Largest maturity sensitivity", "Result": f"{largest_maturity.get('model', 'N/A')} {largest_maturity.get('driving_parameter', 'N/A')} · {_pct(largest_maturity.get('maximum_normalized_parameter_shift'))}", "Interpretation": f"Triggered when excluding {largest_maturity.get('excluded_expiration', 'N/A')}."},
    ]
    st.markdown("#### Governance decision summary")
    st.dataframe(pd.DataFrame(decision_rows), use_container_width=True, hide_index=True)

    _render_orange_warning(
        "MODEL-RISK GOVERNANCE — Production eligibility is a terminal governance classification, not a regulatory approval. "
        "All Heston/Bates quantities remain under Q and are excluded from the validated P-measure ensemble."
    )
    for blocker in result.get("blockers", []):
        _render_orange_warning("MODEL-RISK BLOCKER — " + str(blocker))
    for warning in result.get("warnings", []):
        _render_orange_warning(str(warning))

    st.markdown("#### Final governance gate")
    gate = result.get("gate_table", pd.DataFrame())
    if isinstance(gate, pd.DataFrame):
        display_gate = gate.copy()
        if "passed" in display_gate:
            display_gate["result"] = display_gate["passed"].map(lambda value: "PASS" if bool(value) else "FAIL")
            display_gate = display_gate.drop(columns=["passed"])
        st.dataframe(display_gate, use_container_width=True, hide_index=True)

    left, right = st.columns(2)
    with left:
        st.plotly_chart(
            _plot_model_risk_bootstrap_selection(result),
            use_container_width=True,
            key=f"mc_v280_bootstrap_outcomes_{ticker}_{result.get('configuration_signature')}",
        )
    with right:
        st.plotly_chart(
            _plot_model_risk_maturity_sensitivity(result),
            use_container_width=True,
            key=f"mc_v280_maturity_sensitivity_{ticker}_{result.get('configuration_signature')}",
        )

    left, right = st.columns(2)
    with left:
        st.plotly_chart(
            _plot_model_risk_parameter_intervals(result, "Heston"),
            use_container_width=True,
            key=f"mc_v280_heston_intervals_{ticker}_{result.get('configuration_signature')}",
        )
    with right:
        st.plotly_chart(
            _plot_model_risk_parameter_intervals(result, "Bates"),
            use_container_width=True,
            key=f"mc_v280_bates_intervals_{ticker}_{result.get('configuration_signature')}",
        )

    left, right = st.columns(2)
    with left:
        st.plotly_chart(
            _plot_model_risk_correlation(result, "Heston"),
            use_container_width=True,
            key=f"mc_v280_heston_corr_{ticker}_{result.get('configuration_signature')}",
        )
    with right:
        st.plotly_chart(
            _plot_model_risk_correlation(result, "Bates"),
            use_container_width=True,
            key=f"mc_v280_bates_corr_{ticker}_{result.get('configuration_signature')}",
        )

    left, right = st.columns(2)
    with left:
        st.plotly_chart(
            _plot_model_risk_cost_profiles(result, "Heston"),
            use_container_width=True,
            key=f"mc_v280_heston_profiles_{ticker}_{result.get('configuration_signature')}",
        )
    with right:
        st.plotly_chart(
            _plot_model_risk_cost_profiles(result, "Bates"),
            use_container_width=True,
            key=f"mc_v280_bates_profiles_{ticker}_{result.get('configuration_signature')}",
        )

    bound_table = result.get("parameter_bound_diagnostics", pd.DataFrame())
    if isinstance(bound_table, pd.DataFrame) and not bound_table.empty:
        st.markdown("#### Parameter-bound governance")
        bound_display = bound_table.copy()
        for column in ("estimate", "lower_bound", "upper_bound", "ci_low", "ci_high"):
            if column in bound_display:
                bound_display[column] = bound_display[column].map(lambda value: _number(value, 6))
        for column in ("distance_to_lower_normalized", "distance_to_upper_normalized"):
            if column in bound_display:
                bound_display[column] = bound_display[column].map(_pct)
        st.dataframe(bound_display, use_container_width=True, hide_index=True)

    st.markdown("#### Parameter uncertainty")
    intervals = result.get("parameter_intervals", pd.DataFrame())
    if isinstance(intervals, pd.DataFrame):
        display = intervals.copy()
        for column in ("base_estimate", "ci_low", "bootstrap_median", "ci_high", "bootstrap_std", "normalized_interval_width"):
            if column in display:
                display[column] = display[column].map(lambda value: _number(value, 6))
        st.dataframe(display, use_container_width=True, hide_index=True)

    st.markdown("#### Local identifiability")
    if isinstance(ident, pd.DataFrame):
        display = ident.copy()
        for column in ("condition_number", "minimum_relative_singular_value", "residual_rms"):
            if column in display:
                display[column] = display[column].map(lambda value: _number(value, 6))
        st.dataframe(display, use_container_width=True, hide_index=True)

    history = st.session_state.get(history_key, [])
    if history:
        st.markdown("#### Current-session champion/challenger history")
        st.dataframe(pd.DataFrame(history), use_container_width=True, hide_index=True)
        st.caption("This history is session-scoped. Export it or persist signatures externally for formal ongoing monitoring.")

    with st.expander("Raw model-risk audit and model card", expanded=False):
        st.markdown("**Model card**")
        st.json(_jsonable(result.get("model_card", {})))
        st.markdown("**Bootstrap recalibrations**")
        st.dataframe(result.get("bootstrap_draws", pd.DataFrame()), use_container_width=True, hide_index=True)
        st.markdown("**Singular values**")
        st.dataframe(result.get("singular_values", pd.DataFrame()), use_container_width=True, hide_index=True)
        st.markdown("**Leave-one-maturity recalibrations**")
        st.dataframe(result.get("maturity_sensitivity", pd.DataFrame()), use_container_width=True, hide_index=True)
        st.markdown("**Parameter-bound diagnostics**")
        st.dataframe(result.get("parameter_bound_diagnostics", pd.DataFrame()), use_container_width=True, hide_index=True)
        st.markdown("**Governance record**")
        st.dataframe(pd.DataFrame([{"Field": key, "Value": value} for key, value in result.get("governance", {}).items()]), use_container_width=True, hide_index=True)

    signature = str(result.get("configuration_signature", "UNKNOWN"))
    downloads = st.columns(8)
    downloads[0].download_button("Download gate CSV", result.get("gate_table", pd.DataFrame()).to_csv(index=False).encode("utf-8"), f"{ticker}_model_risk_gate_{signature}.csv", "text/csv", use_container_width=True)
    downloads[1].download_button("Download parameter intervals CSV", result.get("parameter_intervals", pd.DataFrame()).to_csv(index=False).encode("utf-8"), f"{ticker}_model_risk_intervals_{signature}.csv", "text/csv", use_container_width=True)
    downloads[2].download_button("Download bootstrap draws CSV", result.get("bootstrap_draws", pd.DataFrame()).to_csv(index=False).encode("utf-8"), f"{ticker}_model_risk_bootstrap_{signature}.csv", "text/csv", use_container_width=True)
    downloads[3].download_button("Download correlations CSV", result.get("parameter_correlations", pd.DataFrame()).to_csv(index=False).encode("utf-8"), f"{ticker}_model_risk_correlations_{signature}.csv", "text/csv", use_container_width=True)
    downloads[4].download_button("Download cost profiles CSV", result.get("cost_profiles", pd.DataFrame()).to_csv(index=False).encode("utf-8"), f"{ticker}_model_risk_profiles_{signature}.csv", "text/csv", use_container_width=True)
    downloads[5].download_button("Download maturity sensitivity CSV", result.get("maturity_sensitivity", pd.DataFrame()).to_csv(index=False).encode("utf-8"), f"{ticker}_model_risk_maturity_{signature}.csv", "text/csv", use_container_width=True)
    downloads[6].download_button("Download bound diagnostics CSV", result.get("parameter_bound_diagnostics", pd.DataFrame()).to_csv(index=False).encode("utf-8"), f"{ticker}_model_risk_bounds_{signature}.csv", "text/csv", use_container_width=True)
    model_card_bytes = json.dumps(_jsonable(result.get("model_card", {})), indent=2, ensure_ascii=False).encode("utf-8")
    downloads[7].download_button("Download model card JSON", model_card_bytes, f"{ticker}_model_card_{signature}.json", "application/json", use_container_width=True)
