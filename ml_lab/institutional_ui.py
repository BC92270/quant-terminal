"""Institutional presentation, governance and research registry for the ML labs.

The functions in this module are deliberately side-effect free except for the two
Streamlit renderers.  Keeping readiness scoring and Arrow-safe table conversion
pure makes the research controls independently testable.
"""
from __future__ import annotations

from html import escape
from typing import Any, Iterable

import numpy as np
import pandas as pd
import streamlit as st

from .modeling_engine import render_ml_validation_engine
from .neural_backends import neural_runtime_status

from .institutional_engine import (
    build_institutional_control_report,
    render_institutional_control_plane,
)


INTEGRATION_PROTOCOL = 2

MODEL_CATALOG: tuple[dict[str, str], ...] = (
    {
        "Family": "Control",
        "Model": "Prior / naive",
        "Role": "Mandatory benchmark",
        "Readiness": "Operational",
        "Use": "Detect whether complexity adds real out-of-sample value.",
    },
    {
        "Family": "Linear",
        "Model": "Regularized logistic",
        "Role": "Interpretable classifier",
        "Readiness": "Operational",
        "Use": "Stable probability baseline for triple-barrier labels.",
    },
    {
        "Family": "Tabular",
        "Model": "HistGradientBoosting",
        "Role": "Nonlinear challenger",
        "Readiness": "Operational",
        "Use": "Strong native baseline for mixed nonlinear effects.",
    },
    {
        "Family": "Tabular",
        "Model": "Extra Trees",
        "Role": "Variance challenger",
        "Readiness": "Operational",
        "Use": "Robust ensemble and useful feature-importance contrast.",
    },
    {
        "Family": "Tabular",
        "Model": "LightGBM / CatBoost",
        "Role": "External challenger",
        "Readiness": "Optional",
        "Use": "High-performance tabular learners; pin and validate dependencies.",
    },
    {
        "Family": "Dense",
        "Model": "Sklearn MLP",
        "Role": "Neural baseline",
        "Readiness": "Operational",
        "Use": "Tests whether a compact nonlinear network earns its complexity.",
    },
    {
        "Family": "Sequence",
        "Model": "LSTM / GRU / Conv1D",
        "Role": "Temporal challengers",
        "Readiness": "Optional TF",
        "Use": "Sequence models with early stopping and purged evaluation.",
    },
    {
        "Family": "Sequence",
        "Model": "TCN / Transformer / PatchTST-lite",
        "Role": "Modern research",
        "Readiness": "Research",
        "Use": "Only after sample-size, leakage and stability gates pass.",
    },
    {
        "Family": "Foundation",
        "Model": "TimesFM / Chronos",
        "Role": "Forecast challenger",
        "Readiness": "Research",
        "Use": "Zero/few-shot price or return forecasting; never a drop-in label model.",
    },
)

VALIDATION_GATES: tuple[dict[str, str], ...] = (
    {
        "Gate": "Point-in-time data",
        "Control": "Feature timestamp <= decision timestamp; universe and corporate actions are vintage-aware.",
        "Evidence": "Dataset audit + feature lineage",
    },
    {
        "Gate": "Purged walk-forward",
        "Control": "No random split; purge overlapping labels and embargo every fold.",
        "Evidence": "Fold manifest + non-overlap assertions",
    },
    {
        "Gate": "Nested selection",
        "Control": "Tune only inside training folds; lock the final holdout before model selection.",
        "Evidence": "Trial ledger + immutable holdout",
    },
    {
        "Gate": "Economic realism",
        "Control": "Execute at t+1 and stress costs, spread, slippage, turnover and capacity.",
        "Evidence": "Net OOS PnL + sensitivity grid",
    },
    {
        "Gate": "Probability quality",
        "Control": "Report Brier, calibration error, reliability and threshold stability—not accuracy alone.",
        "Evidence": "Calibration card + bootstrap intervals",
    },
    {
        "Gate": "Multiplicity",
        "Control": "Benchmark naive models; track all trials and penalize repeated discovery.",
        "Evidence": "Experiment registry + deflated metrics",
    },
    {
        "Gate": "Deployment isolation",
        "Control": "Research output remains shadow-only until independent validation and approval.",
        "Evidence": "Champion/challenger sign-off",
    },
)

SOFTWARE_STACK: tuple[dict[str, str], ...] = (
    {
        "Layer": "Research workflow",
        "Tool": "Microsoft Qlib",
        "Decision": "Evaluate",
        "Value": "Dataset, model, rolling retraining and portfolio workflow.",
    },
    {
        "Layer": "Experiment tracking",
        "Tool": "MLflow",
        "Decision": "Recommended",
        "Value": "Parameters, code version, datasets, artifacts and model registry.",
    },
    {
        "Layer": "Optimization",
        "Tool": "Optuna",
        "Decision": "Optional",
        "Value": "Budgeted nested tuning with persistent trials and pruning.",
    },
    {
        "Layer": "Explainability",
        "Tool": "SHAP",
        "Decision": "Recommended",
        "Value": "Global and local diagnostics; never a causal interpretation.",
    },
    {
        "Layer": "Data / features",
        "Tool": "Parquet + Feast",
        "Decision": "Evaluate",
        "Value": "Point-in-time features, lineage and reproducible snapshots.",
    },
    {
        "Layer": "Monitoring",
        "Tool": "Evidently + custom drift",
        "Decision": "Evaluate",
        "Value": "Feature, prediction, calibration and performance drift.",
    },
    {
        "Layer": "Trading RL",
        "Tool": "FinRL-X",
        "Decision": "Research only",
        "Value": "Execution/portfolio experiments in a fully isolated simulator.",
    },
)

RESEARCH_REFERENCES: tuple[dict[str, str], ...] = (
    {
        "Date": "2026",
        "Reference": "Federal Reserve SR 26-2",
        "Topic": "Model risk management",
        "Why it matters": "Risk-based governance, validation, inventory and change control.",
        "URL": "https://www.federalreserve.gov/supervisionreg/srletters/SR2602.htm",
    },
    {
        "Date": "2023",
        "Reference": "NIST AI RMF 1.0",
        "Topic": "Govern / Map / Measure / Manage",
        "Why it matters": "Operational control framework for trustworthy AI.",
        "URL": "https://www.nist.gov/itl/ai-risk-management-framework",
    },
    {
        "Date": "2024",
        "Reference": "TimesFM",
        "Topic": "Time-series foundation model",
        "Why it matters": "A credible zero-shot forecasting challenger, not a trading oracle.",
        "URL": "https://research.google/blog/a-decoder-only-foundation-model-for-time-series-forecasting/",
    },
    {
        "Date": "2024",
        "Reference": "Chronos",
        "Topic": "Probabilistic foundation model",
        "Why it matters": "Tokenized probabilistic forecasts with zero-shot evaluation.",
        "URL": "https://arxiv.org/abs/2403.07815",
    },
    {
        "Date": "2023",
        "Reference": "PatchTST",
        "Topic": "Patch-based transformer",
        "Why it matters": "Efficient long-context sequence representation for multivariate series.",
        "URL": "https://arxiv.org/abs/2211.14730",
    },
    {
        "Date": "2023",
        "Reference": "Are Transformers Effective for Time Series?",
        "Topic": "DLinear baseline",
        "Why it matters": "A necessary warning: simple linear baselines can beat complex transformers.",
        "URL": "https://arxiv.org/abs/2205.13504",
    },
    {
        "Date": "2025",
        "Reference": "Conformal prediction for time series",
        "Topic": "Uncertainty",
        "Why it matters": "Coverage must account for temporal dependence and regime change.",
        "URL": "https://arxiv.org/abs/2511.13608",
    },
)


def safe_display_frame(frame: pd.DataFrame | None) -> pd.DataFrame:
    """Return an Arrow-friendly display copy without mutating research data."""
    if frame is None:
        return pd.DataFrame()
    out = frame.copy()
    for column in out.columns:
        series = out[column]
        if pd.api.types.is_datetime64_any_dtype(series):
            out[column] = series.dt.strftime("%Y-%m-%d %H:%M:%S").fillna("")
        elif pd.api.types.is_object_dtype(series) or isinstance(series.dtype, pd.StringDtype):
            out[column] = series.map(_display_scalar)
    return out


def _display_scalar(value: Any) -> str:
    if value is None:
        return ""
    try:
        missing = pd.isna(value)
        if isinstance(missing, (bool, np.bool_)) and bool(missing):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def _find_label_series(frame: pd.DataFrame) -> pd.Series:
    preferred = (
        "tb_label",
        "label",
        "target",
        "binary_target",
        "triple_barrier_label",
        "y",
    )
    lowered = {str(column).lower(): column for column in frame.columns}
    for name in preferred:
        if name in lowered:
            return frame[lowered[name]]
    for column in frame.columns:
        if "label" in str(column).lower() or "target" in str(column).lower():
            return frame[column]
    return pd.Series(dtype=float)


def _finite_coverage(frame: pd.DataFrame) -> float:
    if frame is None or frame.empty:
        return 0.0
    numeric = frame.select_dtypes(include=[np.number]).replace([np.inf, -np.inf], np.nan)
    if numeric.empty:
        return 0.0
    return float(numeric.notna().mean().mean())


def compute_research_readiness(
    labeled_df: pd.DataFrame,
    feature_df: pd.DataFrame | None = None,
    horizon: int = 20,
) -> dict[str, Any]:
    """Score observable research controls; never production or investment readiness."""
    labels = _find_label_series(labeled_df).dropna()
    observations = int(len(labels))
    text_labels = labels.astype(str).str.lower()
    has_tp_sl = (
        text_labels.str.contains("tp", regex=False).any()
        and text_labels.str.contains("sl", regex=False).any()
    )
    numeric_labels = pd.to_numeric(labels, errors="coerce").dropna()
    unique_numeric = set(numeric_labels.unique().tolist())
    if has_tp_sl:
        directional = labels.loc[~text_labels.str.contains("timeout", regex=False)]
    elif {-1.0, 1.0}.issubset(unique_numeric):
        directional = numeric_labels.loc[numeric_labels != 0]
    else:
        directional = labels
    counts = directional.value_counts()
    directional_count = int(len(directional))
    minority_share = float(counts.min() / directional_count) if len(counts) >= 2 and directional_count else 0.0

    text_columns = labeled_df.select_dtypes(include=["object", "string"])
    if text_columns.empty:
        timeout_ratio = 0.0
    else:
        timeout_hits = text_columns.apply(
            lambda series: series.astype(str).str.contains("timeout", case=False, na=False)
        ).any(axis=1)
        timeout_ratio = float(timeout_hits.mean()) if len(timeout_hits) else 0.0

    coverage = _finite_coverage(feature_df if feature_df is not None else labeled_df)
    control_report = build_institutional_control_report(
        labeled_df=labeled_df,
        feature_df=feature_df,
        horizon=int(horizon),
    )
    sample_ok = observations >= max(250, int(horizon) * 12)
    balance_ok = minority_share >= 0.20
    coverage_ok = coverage >= 0.90
    timeout_ok = timeout_ratio <= 0.35

    gates = {
        "Sample size": sample_ok,
        "Class balance": balance_ok,
        "Feature coverage": coverage_ok,
        "Barrier resolution": timeout_ok,
        "Point-in-time controls": bool(control_report["point_in_time"]["passed"]),
        "Locked temporal holdout": bool(control_report["holdout"]["passed"]),
    }
    weights = {
        "Sample size": 20,
        "Class balance": 15,
        "Feature coverage": 15,
        "Barrier resolution": 10,
        "Point-in-time controls": 20,
        "Locked temporal holdout": 20,
    }
    score = int(sum(weights[name] for name, passed in gates.items() if passed))
    status = (
        "Institutional research"
        if score >= 80
        else ("Controlled research" if score >= 55 else "Research only")
    )
    return {
        "score": score,
        "status": status,
        "observations": observations,
        "minority_share": minority_share,
        "feature_coverage": coverage,
        "timeout_ratio": timeout_ratio,
        "gates": gates,
        "control_report": control_report,
    }


def is_dl_protocol_compatible(protocol: Any) -> bool:
    try:
        return int(protocol) >= INTEGRATION_PROTOCOL
    except (TypeError, ValueError):
        return False


def _inject_institutional_css() -> None:
    st.markdown(
        """
        <style>
        .qt-ml-hero {
            padding: 1.35rem 1.45rem;
            margin: .3rem 0 1rem;
            border: 1px solid rgba(65, 215, 201, .24);
            border-radius: 18px;
            background:
                radial-gradient(circle at 85% 12%, rgba(45, 212, 191, .16), transparent 35%),
                linear-gradient(135deg, rgba(9, 24, 39, .98), rgba(13, 40, 54, .92));
            box-shadow: 0 18px 45px rgba(0, 0, 0, .18);
        }
        .qt-ml-kicker {
            color: #60e5d2;
            font-size: .72rem;
            font-weight: 800;
            letter-spacing: .14em;
            text-transform: uppercase;
        }
        .qt-ml-title {
            color: #f4fbff;
            font-size: clamp(1.3rem, 2.4vw, 2rem);
            font-weight: 760;
            line-height: 1.12;
            margin: .35rem 0;
        }
        .qt-ml-copy { color: #a8bdca; max-width: 850px; font-size: .92rem; }
        .qt-ml-badge {
            display: inline-block;
            margin-top: .8rem;
            padding: .28rem .62rem;
            border-radius: 999px;
            background: rgba(96, 229, 210, .11);
            color: #9ff4e7;
            font-size: .72rem;
            font-weight: 700;
        }
        .qt-kpi {
            min-height: 116px;
            padding: .95rem 1rem;
            border: 1px solid rgba(148, 184, 203, .18);
            border-radius: 14px;
            background: rgba(10, 27, 41, .72);
        }
        .qt-kpi-label { color: #89a4b3; font-size: .70rem; letter-spacing: .08em; text-transform: uppercase; }
        .qt-kpi-value { color: #f3fbff; font-size: 1.45rem; font-weight: 760; margin: .18rem 0; }
        .qt-kpi-note { color: #91aab7; font-size: .72rem; }
        .qt-gate {
            padding: .78rem .9rem;
            margin: .28rem 0;
            border-radius: 11px;
            background: rgba(12, 34, 49, .66);
            border-left: 3px solid #526879;
            color: #c7d7df;
            font-size: .82rem;
        }
        .qt-gate-pass { border-left-color: #3bd6b1; }
        .qt-gate-review { border-left-color: #f4b85a; }
        .qt-section-note {
            color: #91aab7;
            font-size: .82rem;
            margin: -.25rem 0 .75rem;
        }
        div[data-testid="stDataFrame"] {
            border: 1px solid rgba(137, 173, 191, .16);
            border-radius: 12px;
            overflow: hidden;
        }
        div[data-baseweb="tab-list"] { gap: .25rem; overflow-x: auto; }
        div[data-baseweb="tab"] { white-space: nowrap; }
        @media (max-width: 760px) {
            .qt-ml-hero { padding: 1.05rem; border-radius: 14px; }
            .qt-kpi { min-height: 98px; margin-bottom: .35rem; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _kpi(column: Any, label: str, value: str, note: str) -> None:
    column.markdown(
        '<div class="qt-kpi">'
        f'<div class="qt-kpi-label">{escape(label)}</div>'
        f'<div class="qt-kpi-value">{escape(value)}</div>'
        f'<div class="qt-kpi-note">{escape(note)}</div>'
        "</div>",
        unsafe_allow_html=True,
    )


def _catalog_frame(rows: Iterable[dict[str, str]]) -> pd.DataFrame:
    return safe_display_frame(pd.DataFrame(list(rows)))


def render_institutional_overview(
    ticker: str,
    labeled_df: pd.DataFrame,
    feature_df: pd.DataFrame,
    horizon: int,
) -> None:
    """Render a decision-first overview while preserving the detailed workbench."""
    _inject_institutional_css()
    readiness = compute_research_readiness(labeled_df, feature_df, horizon)
    control_report = readiness["control_report"]
    safe_ticker = escape(str(ticker).upper())

    st.markdown(
        '<div class="qt-ml-hero">'
        '<div class="qt-ml-kicker">Institutional ML Research Console</div>'
        f'<div class="qt-ml-title">{safe_ticker} · Evidence before complexity</div>'
        '<div class="qt-ml-copy">A governed research surface for leakage-safe labels, '
        'purged validation, calibrated probabilities and champion–challenger review. '
        'No model shown here is authorized for autonomous trading.</div>'
        '<div class="qt-ml-badge">SHADOW MODE · READ ONLY · t+1 EXECUTION</div>'
        "</div>",
        unsafe_allow_html=True,
    )

    k1, k2, k3, k4 = st.columns(4)
    _kpi(k1, "Research readiness", f"{readiness['score']}/100", readiness["status"])
    _kpi(k2, "Labeled observations", f"{readiness['observations']:,}", f"target ≥ {max(250, horizon * 12):,}")
    _kpi(k3, "Minority class", f"{readiness['minority_share']:.1%}", "target ≥ 20%")
    _kpi(k4, "Feature coverage", f"{readiness['feature_coverage']:.1%}", "finite numeric values")

    st.progress(readiness["score"] / 100.0, text="Research-control readiness")
    view = st.radio(
        "Institutional view",
        ("Research posture", "Governance & monitoring", "ML validation engine", "Model universe", "Validation & risk", "Stack & literature"),
        horizontal=True,
        key="ml_institutional_view_v2",
    )

    if view == "Research posture":
        st.markdown("#### Decision gates")
        st.markdown(
            '<div class="qt-section-note">Green means observed in the current frame. '
            'Amber means documentary or independent evidence is still required.</div>',
            unsafe_allow_html=True,
        )
        left, right = st.columns(2)
        for index, (name, passed) in enumerate(readiness["gates"].items()):
            target = left if index % 2 == 0 else right
            css = "qt-gate qt-gate-pass" if passed else "qt-gate qt-gate-review"
            state = "PASS" if passed else "REVIEW"
            target.markdown(
                f'<div class="{css}"><strong>{state}</strong> · {escape(name)}</div>',
                unsafe_allow_html=True,
            )
        st.info(
            "Promotion rule: outperform the naive and logistic baselines after costs, "
            "across purged folds and regimes, with stable calibration and a locked holdout."
        )

    elif view == "Governance & monitoring":
        render_institutional_control_plane(control_report, ticker)

    elif view == "ML validation engine":
        render_ml_validation_engine(
            ticker=ticker,
            labeled_df=labeled_df,
            feature_df=feature_df,
            horizon=horizon,
            control_report=control_report,
        )

    elif view == "Model universe":
        st.markdown("#### Champion–challenger universe")
        st.markdown(
            '<div class="qt-section-note">Operational means supported by the current Python stack. '
            'Optional and research models remain explicit challengers—not implied upgrades.</div>',
            unsafe_allow_html=True,
        )
        catalog = _catalog_frame(MODEL_CATALOG)
        family = st.selectbox(
            "Filter family",
            ["All"] + sorted(catalog["Family"].unique().tolist()),
            key="ml_catalog_family_v2",
        )
        if family != "All":
            catalog = catalog.loc[catalog["Family"] == family]
        st.dataframe(catalog, width="stretch", hide_index=True, height=360)
        st.caption(
            "Default ordering is complexity-aware: prior → logistic → tree ensembles → "
            "compact neural models → sequence/foundation challengers."
        )

    elif view == "Validation & risk":
        st.markdown("#### Validation protocol")
        st.markdown(
            '<div class="qt-section-note">Every gate produces evidence. A high backtest metric '
            'without the evidence column remains unvalidated.</div>',
            unsafe_allow_html=True,
        )
        st.dataframe(_catalog_frame(VALIDATION_GATES), width="stretch", hide_index=True, height=350)
        with st.expander("Metric contract", expanded=False):
            st.markdown(
                """
                - **Classification:** balanced accuracy, ROC-AUC, precision/recall/F1, Brier and reliability.
                - **Trading:** net return, Sharpe with uncertainty, drawdown, turnover, hit rate and capacity proxy.
                - **Stability:** fold dispersion, regime dispersion, threshold sensitivity and feature drift.
                - **Uncertainty:** block bootstrap; conformal coverage only with dependence-aware diagnostics.
                """
            )
        st.warning(
            "A model may improve statistical scores and still fail economically after latency, "
            "transaction costs, turnover or selection bias."
        )

    else:
        stack_tab, literature_tab = st.tabs(["Software stack", "Research radar"])
        with stack_tab:
            st.dataframe(_catalog_frame(SOFTWARE_STACK), width="stretch", hide_index=True, height=310)
            st.caption("Recommended tools are architecture targets; they are not silently installed.")
        with literature_tab:
            for item in RESEARCH_REFERENCES:
                st.markdown(
                    f"**[{item['Reference']}]({item['URL']})** · {item['Date']} · {item['Topic']}  \\n"
                    f"{item['Why it matters']}"
                )


def render_deep_learning_radar(tensorflow_available: bool) -> None:
    """Compact orientation block for the optional DL workbench."""
    _inject_institutional_css()
    runtimes = neural_runtime_status()
    status = (
        f"PyTorch {'detected' if runtimes['pytorch'] else 'not installed'} · "
        f"TensorFlow {'detected' if runtimes['tensorflow'] else 'not installed'}"
    )
    st.markdown(
        '<div class="qt-ml-hero">'
        '<div class="qt-ml-kicker">Deep Learning Research Workbench</div>'
        '<div class="qt-ml-title">Sequence models under institutional controls</div>'
        f'<div class="qt-ml-copy">{escape(status)}. Neural challengers must beat simple baselines '
        'under the same purged folds, costs and calibration contract.</div>'
        '<div class="qt-ml-badge">OPTIONAL · LAZY LOADED · SHADOW ONLY</div>'
        "</div>",
        unsafe_allow_html=True,
    )
    st.caption(
        "Use MLP as the neural control; PyTorch/TensorFlow LSTM, GRU and Conv1D for compact sequences; "
        "reserve TCN/Transformer/PatchTST-style research for larger, multi-asset datasets."
    )
