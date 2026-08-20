from __future__ import annotations

import html
from typing import Any, Dict, Mapping, Sequence, Tuple

import numpy as np
import pandas as pd
import streamlit as st

from ..utils import _number, _pct, _pp, _price, _safe_float


def _render_orange_warning(message: str) -> None:
    safe = html.escape(str(message))
    st.markdown(
        f"""
        <div style="border:1px solid rgba(242,166,90,.55);background:rgba(242,166,90,.14);
                    color:#ffd7a8;padding:.72rem .9rem;border-radius:.5rem;margin:.28rem 0;
                    font-size:.92rem;line-height:1.35;">{safe}</div>
        """,
        unsafe_allow_html=True,
    )


def _ui_segmented_control(label: str, options: Sequence[Any], default: Any, key: str, format_func=None) -> Any:
    control = getattr(st, "segmented_control", None)
    if callable(control):
        return control(label, options=options, default=default, key=key, format_func=format_func)
    index = list(options).index(default) if default in options else 0
    return st.radio(label, options=list(options), index=index, horizontal=True, key=key, format_func=format_func)


def _ui_toggle(label: str, value: bool, key: str) -> bool:
    control = getattr(st, "toggle", None)
    if callable(control):
        return bool(control(label, value=value, key=key))
    return bool(st.checkbox(label, value=value, key=key))


def _decision_diagnostic(summary: Mapping[str, Any], matrix_diag: Mapping[str, Any]) -> Tuple[str, str, str]:
    asymmetry = float(summary.get("barrier_asymmetry_pp", 0.0))
    es5 = float(summary.get("es_5", 0.0))
    expected = float(summary.get("expected_return", 0.0))
    model_range = _safe_float(matrix_diag.get("model_expected_return_range_pp"), 0.0) or 0.0
    drift_sensitivity = abs(_safe_float(matrix_diag.get("drift_expected_return_sensitivity_pp"), 0.0) or 0.0)
    eligibility = str(summary.get("eligibility_status", "INELIGIBLE"))
    reasons = "; ".join(summary.get("eligibility_reasons", []))

    if summary.get("fallback_used") or eligibility == "FALLBACK":
        return (
            "MODEL FALLBACK ACTIVE",
            f"La calibration {summary.get('calibration_model') or 'conditionnelle'} a échoué; le moteur utilise le fallback EWMA-FHS.",
            "error",
        )
    if eligibility == "INELIGIBLE":
        return (
            "MODEL INELIGIBLE — RESEARCH ONLY",
            reasons or "Le modèle ne satisfait pas les critères minimaux de calibration.",
            "error",
        )
    if eligibility == "WARNING":
        return (
            "MODEL ELIGIBILITY WARNING",
            reasons or "Le modèle reste visible mais est exclu de l'agrégation institutionnelle.",
            "warning",
        )
    if summary.get("calibration_status") == "WARNING":
        return (
            "CONDITIONAL CALIBRATION WARNING",
            summary.get("calibration_warning") or "La calibration conditionnelle nécessite une revue.",
            "warning",
        )
    if es5 <= -0.25:
        return "ELEVATED TAIL RISK", "La perte moyenne des 5 % pires trajectoires dépasse 25 %.", "warning"
    if asymmetry <= -10.0:
        return "DOWNSIDE BARRIER DOMINANT", "Le stop précède la target avec une asymétrie supérieure à 10 points.", "error"
    if asymmetry >= 10.0 and expected > 0.0 and model_range <= 8.0:
        return "FAVORABLE BARRIER ASYMMETRY", "La target précède le stop et la dispersion inter-modèles reste contenue.", "success"
    if drift_sensitivity >= 8.0:
        return "DRIFT-SENSITIVE OUTLOOK", "Le résultat change fortement lorsque le drift historique est neutralisé.", "warning"
    if model_range >= 12.0:
        return "HIGH MODEL UNCERTAINTY", "La dispersion des rendements attendus entre moteurs est élevée.", "warning"
    return "INCONCLUSIVE DISTRIBUTION", "Aucune asymétrie suffisamment stable ne domine après comparaison des hypothèses.", "info"


def _quality_table(lab: Mapping[str, Any]) -> pd.DataFrame:
    base = lab["base"]
    quality = base["quality"]
    drift_low, drift_high = base["drift_ci_95"]
    calibration_rows = int(quality.get("calibration_rows", len(base.get("calibration_df", []))))
    return_rows = int(quality.get("returns_count", 0))
    ppy = max(int(base.get("periods_per_year", 252)), 1)
    sample_years = return_rows / ppy

    conditional = lab.get("conditional_calibrations", {})
    conditional_pass = sum(1 for fit in conditional.values() if fit.get("ok"))
    conditional_total = len(conditional)
    eligibility = lab.get("model_eligibility", {})
    eligible_count = sum(1 for item in eligibility.values() if item.get("status") == "ELIGIBLE")
    warning_count = sum(1 for item in eligibility.values() if item.get("status") == "WARNING")

    rows = [
        {
            "Block": "Display price history",
            "Status": "PASS" if len(base["df"]) >= 120 else "WARNING",
            "Value": f"{len(base['df'])} rows",
            "Interpretation": f"Display {quality.get('display_start')} → {quality.get('display_end')}",
        },
        {
            "Block": "Calibration source",
            "Status": "PASS" if base.get("calibration_source") != "display_price_data" else "WARNING",
            "Value": str(base.get("calibration_source")),
            "Interpretation": f"{calibration_rows} prices / {return_rows} returns / {sample_years:.2f} years",
        },
        {
            "Block": "Calibration sample",
            "Status": "PASS" if return_rows >= 500 else "WARNING",
            "Value": f"{return_rows} returns",
            "Interpretation": f"{quality.get('sample_start')} → {quality.get('sample_end')}",
        },
        {
            "Block": "Validation history",
            "Status": "PASS" if int(base.get("validation_observations", 0)) >= 500 else "WARNING",
            "Value": f"{int(base.get('validation_observations', 0))} returns",
            "Interpretation": f"Independent from current calibration window · source={base.get('validation_source')}",
        },
        {
            "Block": "Automatic provider bridge",
            "Status": "PASS" if str(lab.get("provider_report", {}).get("status")) in {"LIVE_FETCH", "CACHE_HIT", "SKIPPED_HIGHER_PRIORITY"} else "WARNING",
            "Value": str(lab.get("provider_report", {}).get("status", "NOT_RUN")),
            "Interpretation": f"{lab.get('provider_report', {}).get('provider', 'N/A')} · period={lab.get('provider_report', {}).get('period', 'N/A')} · rows={lab.get('provider_report', {}).get('selected_rows', 0)}",
        },
        {
            "Block": "Sampling frequency",
            "Status": "PASS",
            "Value": f"{base['frequency_label']} / {base['periods_per_year']} p.a.",
            "Interpretation": f"Median spacing: {_number(base.get('median_spacing_days'), 2)} days",
        },
        {
            "Block": "Corporate-action warning",
            "Status": "WARNING" if quality.get("extreme_return_count", 0) > 0 else "PASS",
            "Value": str(quality.get("extreme_return_count", 0)),
            "Interpretation": "Absolute returns above 50 % are flagged, not silently removed.",
        },
        {
            "Block": "Drift identification",
            "Status": "WARNING" if drift_low < 0 < drift_high else "PASS",
            "Value": f"{_pct(base['drift_ann'])} [{_pct(drift_low)}, {_pct(drift_high)}]",
            "Interpretation": "95 % sampling interval for the annualized diffusion drift.",
        },
        {
            "Block": "Volatility",
            "Status": "PASS",
            "Value": f"Historical {_pct(base['vol_ann'])} / EWMA {_pct(base['ewma_vol_ann'])}",
            "Interpretation": "Unconditional and recent conditional volatility estimates.",
        },
        {
            "Block": "Conditional-volatility calibration",
            "Status": "PASS" if conditional_pass == conditional_total and conditional_total > 0 else "WARNING",
            "Value": f"{conditional_pass}/{conditional_total} valid",
            "Interpretation": "GARCH/GJR fits used by conditional simulation engines.",
        },
        {
            "Block": "Model eligibility gate",
            "Status": "PASS" if eligible_count >= 2 else "WARNING",
            "Value": f"{eligible_count} eligible / {warning_count} warning",
            "Interpretation": "Only ELIGIBLE models enter primary cross-model aggregation.",
        },
        {
            "Block": "Tail calibration",
            "Status": "WARNING" if base["excess_kurtosis"] > 3.0 else "PASS",
            "Value": f"Skew {_number(base['skewness'])} / Excess kurtosis {_number(base['excess_kurtosis'])}",
            "Interpretation": f"Static Student-t degrees of freedom: {_number(base['student_df'])}",
        },
        {
            "Block": "Price source",
            "Status": "PASS" if base["price_source"] != "historique/close" else "WARNING",
            "Value": base["price_source"],
            "Interpretation": "Live price preferred; historical close used as fallback.",
        },
    ]
    return pd.DataFrame(rows)


def _calibration_table(lab: Mapping[str, Any]) -> pd.DataFrame:
    base = lab["base"]
    settings = lab["settings"]
    low, high = base["drift_ci_95"]
    window = settings.get("calibration_window")
    window_label = "Maximum available" if window is None else f"Last {int(window)} returns requested"
    report = lab.get("calibration_source_report", {})
    return pd.DataFrame(
        [
            {"Parameter": "Current price", "Estimate": _price(base["current_price"]), "Method": base["price_source"]},
            {"Parameter": "Calibration source", "Estimate": str(base.get("calibration_source")), "Method": f"mode={report.get('mode', 'auto')} · selected rows={report.get('selected_rows', 0)}"},
            {"Parameter": "Calibration sample", "Estimate": f"{base['calibration_observations']} returns", "Method": f"{window_label}"},
            {"Parameter": "Annualized diffusion drift", "Estimate": _pct(base["drift_ann"]), "Method": "Log-return mean + 0.5 sigma²"},
            {"Parameter": "Drift 95% interval", "Estimate": f"[{_pct(low)}, {_pct(high)}]", "Method": "Sampling uncertainty"},
            {"Parameter": "Expected annual price return", "Estimate": _pct(base["expected_return_ann"]), "Method": "exp(mu) - 1"},
            {"Parameter": "Historical volatility", "Estimate": _pct(base["vol_ann"]), "Method": "Std(log return) × sqrt(periods/year)"},
            {"Parameter": "EWMA volatility", "Estimate": _pct(base["ewma_vol_ann"]), "Method": f"lambda={settings['ewma_lambda']:.3f}"},
            {"Parameter": "Static Student-t degrees of freedom", "Estimate": _number(base["student_df"]), "Method": "Method-of-moments from excess kurtosis"},
            {"Parameter": "Historical max drawdown", "Estimate": _pct(base["max_drawdown"]), "Method": "Calibration sample"},
            {"Parameter": "ATR 14", "Estimate": _price(base["atr_14"]), "Method": "Display sample true-range rolling mean"},
        ]
    )


def _conditional_calibration_display(lab: Mapping[str, Any]) -> pd.DataFrame:
    frame = lab.get("conditional_calibration_table")
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return pd.DataFrame()
    display = frame.copy()
    numeric = (
        "Omega", "Alpha", "Beta", "Gamma", "Nu", "Persistence", "Log-likelihood", "AIC", "BIC",
        "Residual skew", "Residual excess kurtosis", "Persistence delta", "Last-vol ratio",
    )
    for column in numeric:
        if column in display.columns:
            display[column] = display[column].map(lambda value: _number(value, 4) if pd.notna(value) else "N/A")
    for column in ("Last vol ann.", "Long-run vol ann."):
        if column in display.columns:
            display[column] = display[column].map(_pct)
    return display


def _eligibility_display(lab: Mapping[str, Any]) -> pd.DataFrame:
    frame = lab.get("model_eligibility_table")
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return pd.DataFrame()
    display = frame.copy()
    for column in ("Persistence", "Nu", "LB residual p", "LB squared p"):
        if column in display.columns:
            display[column] = display[column].map(lambda value: _number(value, 4) if pd.notna(value) else "N/A")
    return display


def _summary_table(matrix_df: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "horizon", "scenario", "model", "eligibility_status", "calibration_status", "fallback_used",
        "barrier_monitoring_effective", "persistence", "drift_used", "vol_used", "expected_return",
        "expected_return_mcse", "median_return", "prob_positive", "barrier_asymmetry_pp",
        "prob_target_before_stop", "prob_stop_before_target", "var_5", "es_5", "expected_max_drawdown", "prob_ruin",
    ]
    available = [column for column in columns if column in matrix_df.columns]
    display = matrix_df[available].copy()
    if display.empty:
        return display

    display = display.rename(
        columns={
            "horizon": "Horizon", "scenario": "Scenario", "model": "Model",
            "eligibility_status": "Eligibility", "calibration_status": "Calibration", "fallback_used": "Fallback",
            "barrier_monitoring_effective": "Barrier monitoring", "persistence": "Persistence",
            "drift_used": "Drift", "vol_used": "Volatility", "expected_return": "Expected return",
            "expected_return_mcse": "Mean MCSE", "median_return": "Median return", "prob_positive": "P(Return > 0)",
            "barrier_asymmetry_pp": "Barrier asymmetry", "prob_target_before_stop": "Target before stop",
            "prob_stop_before_target": "Stop before target", "var_5": "VaR 5%", "es_5": "ES 5%",
            "expected_max_drawdown": "Expected max DD", "prob_ruin": "P(Ruin threshold)",
        }
    )
    display["Horizon"] = display["Horizon"].map(lambda x: f"{int(x)}D")
    for column in ("Drift", "Volatility", "Expected return", "Mean MCSE", "Median return", "VaR 5%", "ES 5%", "Expected max DD"):
        if column in display.columns:
            display[column] = display[column].map(_pct)
    for column in ("P(Return > 0)", "Target before stop", "Stop before target", "P(Ruin threshold)"):
        if column in display.columns:
            display[column] = display[column].map(lambda x: f"{float(x):.2f}%")
    if "Barrier asymmetry" in display.columns:
        display["Barrier asymmetry"] = display["Barrier asymmetry"].map(lambda x: _pp(float(x), signed=True))
    if "Persistence" in display.columns:
        display["Persistence"] = display["Persistence"].map(lambda x: _number(x, 4) if pd.notna(x) else "N/A")
    if "Fallback" in display.columns:
        display["Fallback"] = display["Fallback"].map(lambda x: "YES" if bool(x) else "NO")
    return display


def _render_status_banner(label: str, text: str, severity: str) -> None:
    message = f"**{label}** — {text}"
    if severity == "success":
        st.success(message)
    elif severity == "warning":
        st.markdown(
            '<div style="padding:0.8rem 1rem;border:1px solid rgba(242,166,90,.65);'
            'background:rgba(242,166,90,.16);border-radius:.45rem;color:#ffd9a8;">'
            f'<strong>{html.escape(label)}</strong> — {html.escape(text)}</div>',
            unsafe_allow_html=True,
        )
    elif severity == "error":
        st.error(message)
    else:
        st.info(message)


def _metric_with_ci(label: str, value: str, interval: Tuple[float, float] | None = None, percentage_points: bool = False) -> None:
    st.metric(label, value)
    if interval is not None and all(np.isfinite(interval)):
        if percentage_points:
            st.caption(f"CI: {interval[0]:.2f}% → {interval[1]:.2f}%")
        else:
            st.caption(f"CI: {_pct(interval[0])} → {_pct(interval[1])}")


def _render_executive_strip(lab: Mapping[str, Any], horizon: int) -> None:
    summary = lab["summaries_by_horizon"][horizon]
    diag = lab["matrix_diagnostics"][horizon]
    cols = st.columns(6)
    with cols[0]:
        _metric_with_ci("Median outcome", _pct(summary["median_return"], signed=True))
    with cols[1]:
        _metric_with_ci("Expected Shortfall 5%", _pct(summary["es_5"]), summary["es_5_ci"])
    with cols[2]:
        _metric_with_ci("Target before stop", f"{summary['prob_target_before_stop']:.2f}%", summary["target_before_stop_ci"], percentage_points=True)
    with cols[3]:
        _metric_with_ci("Stop before target", f"{summary['prob_stop_before_target']:.2f}%", summary["stop_before_target_ci"], percentage_points=True)
    with cols[4]:
        st.metric("Model return range", _pp(diag["model_expected_return_range_pp"]))
        eligible_count = int(diag.get("eligible_model_count", 0))
        warning_count = int(diag.get("warning_model_count", 0))
        basis = str(diag.get("aggregation_basis", "NONE"))
        if eligible_count > 0:
            st.caption(f"{eligible_count} eligible model(s) · {warning_count} warning · aggregation: eligible only")
        elif basis == "WARNING_FALLBACK":
            st.caption(f"No eligible models · {warning_count} warning-tier model(s) · cross-model range uses explicit warning fallback")
        else:
            st.caption("No eligible models · cross-model aggregation unavailable")
    with cols[5]:
        conditional_vol = summary.get("initial_conditional_vol_ann")
        if conditional_vol is not None and np.isfinite(conditional_vol):
            st.metric("Initial conditional vol", _pct(conditional_vol))
            st.caption(f"Persistence {_number(summary.get('persistence'), 4)} · {summary.get('eligibility_status')}")
        else:
            st.metric("Drift sensitivity", _pp(diag["drift_expected_return_sensitivity_pp"], signed=True))
            st.caption(f"Historical minus neutral drift · {summary.get('eligibility_status')}")

    label, text, severity = _decision_diagnostic(summary, diag)
    _render_status_banner(label, text, severity)


def _render_level_table(lab: Mapping[str, Any]) -> None:
    levels = lab["levels"]
    current = levels["current"]
    rows = [
        ("Structural stop", levels["stop_structural"]), ("Short stop", levels["stop_short"]),
        ("Current", current), ("Target 1", levels["target_1"]), ("Target 2", levels["target_2"]),
    ]
    frame = pd.DataFrame(
        [{"Level": name, "Price": _price(value), "Distance": _pct(value / current - 1.0, signed=True)} for name, value in rows]
    )
    st.dataframe(frame, use_container_width=True, hide_index=True)
    st.caption(f"Level source: {lab['levels']['source']}")


def _build_form_defaults(ticker: str) -> Dict[str, Any]:
    return {
        "simulations": 3_000,
        "matrix_simulations": 2_000,
        "scenario": "Conservateur",
        "model": "GBM normal",
        "seed": 42,
        "barrier_monitoring": "Brownian bridge (GBM)",
        "confidence_level": 0.95,
        "mean_block_length": 10,
        "ewma_lambda": 0.94,
        "ruin_threshold": -0.30,
        "calibration_window": None,
        "calibration_source_mode": "auto",
        "garch_maxiter": 800,
        "garch_min_observations": 120,
        "stability_check": True,
        "provider_enabled": True,
        "provider_period": "10y",
        "provider_price_basis": "adjusted",
        "provider_cache_ttl_hours": 12,
        "level_mode": "Automatique ATR/structure",
        "ticker": ticker,
    }
