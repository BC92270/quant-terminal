from __future__ import annotations

from typing import Any, Dict, Mapping

import numpy as np
import pandas as pd
import streamlit as st

from ..utils import _jsonable, _number, _pct, _pp
from .charts import (_plot_barrier_race, _plot_convergence, _plot_exceedance_curve,
                     _plot_fan_chart, _plot_matrix_heatmap, _plot_terminal_distribution,
                     _plot_time_to_hit)
from .common import (_calibration_table, _quality_table, _render_level_table, _summary_table)

def _render_overview(lab: Mapping[str, Any], horizon: int, show_paths: bool, visible_paths: int) -> None:
    summary = lab["summaries_by_horizon"][horizon]
    left, right = st.columns([2.15, 1.0])
    with left:
        st.plotly_chart(
            _plot_fan_chart(lab, horizon, show_paths, visible_paths),
            use_container_width=True,
            key=f"mc_v211_overview_fan_{lab['ticker']}_{lab['configuration_signature']}_{horizon}",
        )
    with right:
        st.markdown("#### Risk ladder")
        _render_level_table(lab)
        st.markdown("#### Distribution statistics")
        statistics = pd.DataFrame(
            [
                {"Metric": "Expected return", "Value": _pct(summary["expected_return"], signed=True)},
                {"Metric": "Mean MCSE", "Value": _pct(summary["expected_return_mcse"])},
                {"Metric": "P(Return > 0)", "Value": f"{summary['prob_positive']:.2f}%"},
                {"Metric": "VaR 5%", "Value": _pct(summary["var_5"])},
                {"Metric": "ES 5%", "Value": _pct(summary["es_5"])},
                {"Metric": "Expected max drawdown", "Value": _pct(summary["expected_max_drawdown"])},
                {"Metric": "P(Drawdown > 20%)", "Value": f"{summary['prob_drawdown_gt_20']:.2f}%"},
                {"Metric": "P(Ruin threshold)", "Value": f"{summary['prob_ruin']:.2f}%"},
            ]
        )
        st.dataframe(statistics, use_container_width=True, hide_index=True)
        st.caption(f"Barrier monitoring: {summary['effective_monitoring']}")

    left, right = st.columns(2)
    with left:
        st.plotly_chart(
            _plot_terminal_distribution(summary, lab["levels"]),
            use_container_width=True,
            key=f"mc_v211_overview_distribution_{lab['ticker']}_{lab['configuration_signature']}_{horizon}",
        )
    with right:
        st.plotly_chart(
            _plot_barrier_race(summary),
            use_container_width=True,
            key=f"mc_v211_overview_barrier_race_{lab['ticker']}_{lab['configuration_signature']}_{horizon}",
        )


def _render_models_calibration(lab: Mapping[str, Any], horizon: int) -> None:
    st.markdown("### Calibration and model-risk matrix")
    st.dataframe(_calibration_table(lab), use_container_width=True, hide_index=True)

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
            key=f"mc_heatmap_metric_{lab['ticker']}",
        )
    with control_2:
        st.caption(
            "Each row is a simulation engine. Each column is a scenario. "
            "Common random numbers reduce noise when comparing scenarios inside the same model."
        )

    st.plotly_chart(
        _plot_matrix_heatmap(lab["matrix_df"], horizon, metric),
        use_container_width=True,
        key=f"mc_v211_model_heatmap_{lab['ticker']}_{lab['configuration_signature']}_{horizon}",
    )

    with st.expander("Full scenario matrix", expanded=False):
        st.dataframe(_summary_table(lab["matrix_df"]), use_container_width=True, hide_index=True, height=520)


def _render_path_barriers(lab: Mapping[str, Any], horizon: int, show_paths: bool, visible_paths: int) -> None:
    summary = lab["summaries_by_horizon"][horizon]
    st.plotly_chart(
        _plot_fan_chart(lab, horizon, show_paths, visible_paths),
        use_container_width=True,
        key=f"mc_v211_path_fan_{lab['ticker']}_{lab['configuration_signature']}_{horizon}",
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
            key=f"mc_v211_path_barrier_race_{lab['ticker']}_{lab['configuration_signature']}_{horizon}",
        )
    with right:
        st.plotly_chart(
            _plot_time_to_hit(summary),
            use_container_width=True,
            key=f"mc_v211_path_time_to_hit_{lab['ticker']}_{lab['configuration_signature']}_{horizon}",
        )

    if summary["bridge_requested_but_unavailable"]:
        st.warning(
            "Brownian bridge was requested but is not mathematically valid for the selected non-Gaussian/bootstrap engine. "
            "Barrier monitoring automatically fell back to end-of-step observations."
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
            key=f"mc_v211_tail_distribution_{lab['ticker']}_{lab['configuration_signature']}_{horizon}",
        )
    with right:
        st.plotly_chart(
            _plot_exceedance_curve(summary),
            use_container_width=True,
            key=f"mc_v211_tail_exceedance_{lab['ticker']}_{lab['configuration_signature']}_{horizon}",
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


def _render_validation_audit(lab: Mapping[str, Any], horizon: int) -> None:
    summary = lab["summaries_by_horizon"][horizon]
    st.markdown("### Monte Carlo convergence")
    convergence = summary["convergence"].copy()
    st.plotly_chart(
        _plot_convergence(convergence),
        use_container_width=True,
        key=f"mc_v211_validation_convergence_{lab['ticker']}_{lab['configuration_signature']}_{horizon}",
    )

    display_convergence = convergence.copy()
    for column in (
        "Expected return",
        "Expected return MCSE",
        "VaR 5%",
        "ES 5%",
        "ES 5% CI low",
        "ES 5% CI high",
    ):
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
            "This is a one-step rolling Gaussian VaR baseline. V2.2 will add model-specific walk-forward distribution validation."
        )
    else:
        st.warning(validation.get("reason", "VaR validation unavailable."))

    st.markdown("### Data and calibration quality")
    st.dataframe(_quality_table(lab), use_container_width=True, hide_index=True)

    warnings = lab["base"]["quality"].get("warnings", [])
    if warnings:
        with st.expander("Quality warnings", expanded=True):
            for warning in warnings:
                st.warning(warning)

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
            {"Field": "Barrier monitoring", "Value": lab["settings"]["barrier_monitoring"]},
            {"Field": "Price source", "Value": lab["base"]["price_source"]},
            {"Field": "Measure", "Value": lab["assumptions"]["measure"]},
            {"Field": "Level source", "Value": lab["levels"]["source"]},
        ]
    )
    st.dataframe(governance, use_container_width=True, hide_index=True)

    with st.expander("Raw assumptions and limitations", expanded=False):
        st.json(_jsonable(lab["assumptions"]))

    with st.expander("Raw active-horizon summary", expanded=False):
        raw_summary = {
            key: value
            for key, value in summary.items()
            if not isinstance(value, (np.ndarray, pd.DataFrame))
        }
        st.json(_jsonable(raw_summary))

    with st.expander("Raw scenario matrix", expanded=False):
        st.dataframe(lab["matrix_df"], use_container_width=True, hide_index=True, height=520)
