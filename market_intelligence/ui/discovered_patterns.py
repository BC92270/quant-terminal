"""Institutional ML pattern discovery and decision-handoff workspace."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import pandas as pd
import streamlit as st

from ..contracts import WorkspaceSnapshot
from ..evidence import canonical_json
from ..patterns.bridge import build_pattern_strategy_bridge
from ..patterns.contracts import (
    PatternCandidate,
    PatternCandidateState,
    PatternDiscoveryConfig,
    PatternDiscoveryReport,
    PatternRunState,
    PatternStrategyBridge,
)
from ..patterns.features import build_pattern_feature_bundle
from ..strategy import StrategicDecisionMemo
from .common import bounded_table, card, esc, provenance, section_header, tone_for_status


def _pct(value: float | None) -> str:
    return "N/A" if value is None else f"{value:+.2%}"


def _number(value: float | None, decimals: int = 3) -> str:
    return "N/A" if value is None else f"{value:.{decimals}f}"


def _verified_report(report: PatternDiscoveryReport | None) -> bool:
    if report is None:
        return False
    try:
        return report.verify_hash()
    except Exception:
        return False


def pattern_candidates_frame(report: PatternDiscoveryReport) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Pattern ID": candidate.pattern_id,
                "State": candidate.state.value,
                "Signature": candidate.signature,
                "Direction learned in train": candidate.direction,
                "Train occurrences": candidate.train_occurrences,
                "Run-locked OOS occurrences": candidate.oos_occurrences,
                "Non-overlap OOS occurrences": candidate.oos_nonoverlap_occurrences,
                "Train forward mean (%)": (
                    None
                    if candidate.train_mean_forward_return is None
                    else 100.0 * candidate.train_mean_forward_return
                ),
                "OOS forward mean (%)": (
                    None
                    if candidate.oos_mean_forward_return is None
                    else 100.0 * candidate.oos_mean_forward_return
                ),
                "OOS after cost (%)": (
                    None
                    if candidate.oos_after_cost_mean is None
                    else 100.0 * candidate.oos_after_cost_mean
                ),
                "OOS rest after cost (%)": (
                    None
                    if candidate.oos_rest_after_cost_mean is None
                    else 100.0 * candidate.oos_rest_after_cost_mean
                ),
                "Conditional uplift (%)": (
                    None
                    if candidate.conditional_uplift is None
                    else 100.0 * candidate.conditional_uplift
                ),
                "OOS hit rate (%)": (
                    None if candidate.oos_hit_rate is None else 100.0 * candidate.oos_hit_rate
                ),
                "Full-OOS per-bar Sharpe": candidate.oos_strategy_sharpe,
                "Per-bar Sharpe lower 95%": candidate.oos_strategy_sharpe_lower_95,
                "Non-overlap Deflated Sharpe P": candidate.deflated_sharpe_probability,
                "Shift diagnostic p": candidate.raw_p_value,
                "BY diagnostic q": candidate.fdr_q_value,
                "Subperiod stability": candidate.stability,
                "Proximity heuristic": candidate.current_match_score,
                "Execution": "DISABLED",
            }
            for candidate in report.candidates
        ]
    )


def pattern_gates_frame(report: PatternDiscoveryReport) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Gate": gate.gate_id,
                "State": gate.state.value,
                "Strategic blocker": "YES" if gate.blocks_strategic_admission else "NO",
                "Reason": gate.reason,
                "Evidence": gate.evidence,
            }
            for gate in report.gates
        ]
    )


def model_scores_frame(report: PatternDiscoveryReport) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Model": score.model,
                "OOS rows": score.oos_rows,
                "Balanced accuracy": score.balanced_accuracy,
                "ROC AUC": score.roc_auc,
                "Brier": score.brier,
                "ECE": score.expected_calibration_error,
                "Role": "BASELINE" if score.model in {"Prior", "Logistic"} else "CHALLENGER",
            }
            for score in report.model_scores
        ]
    )


def _selected_candidate(
    report: PatternDiscoveryReport,
    selection: Any,
) -> PatternCandidate:
    try:
        position = int(selection.selection.rows[0])
        return report.candidates[position]
    except (AttributeError, IndexError, TypeError, ValueError):
        return next(
            (
                candidate
                for candidate in report.candidates
                if candidate.pattern_id == (report.current_pattern_id or report.nearest_pattern_id)
            ),
            report.candidates[0],
        )


def _render_configuration(
    snapshot: WorkspaceSnapshot,
    price_data: Any,
) -> tuple[PatternDiscoveryConfig, Any, bool]:
    section_header(
        "RESEARCH PROTOCOL",
        "Discovery mandate & run-locked validation design",
        "TRAIN-ONLY CLUSTER SEARCH · PURGE · RUN-LOCKED TERMINAL OOS · BY DIAGNOSTIC",
    )
    with st.expander("PATTERN ENGINE CONFIGURATION", expanded=True):
        a, b, c, d = st.columns(4)
        with a:
            horizon = st.selectbox(
                "FORWARD HORIZON (BARS)",
                (3, 5, 10, 20),
                index=1,
                key="mi_pattern_horizon_bars",
                help="Labels only. Forward returns never enter the discovery feature matrix.",
            )
        with b:
            costs = st.number_input(
                "COST PER OCCURRENCE (BPS)",
                min_value=0.0,
                max_value=100.0,
                value=10.0,
                step=1.0,
                key="mi_pattern_cost_bps",
            )
        with c:
            max_clusters = st.selectbox(
                "MAX CLUSTER STATES",
                (4, 5, 6, 7),
                index=2,
                key="mi_pattern_max_clusters",
                help="The selected count maximizes return-blind training silhouette subject to cluster-depth controls.",
            )
        with d:
            fdr_alpha = st.selectbox(
                "RUN-LOCAL BY SCREEN",
                (0.05, 0.10, 0.15),
                index=1,
                key="mi_pattern_fdr_alpha",
                format_func=lambda value: f"q = {value:.0%}",
            )
        st.caption(
            "Fixed institutional controls: ≥180 usable rows · ≥100 selection rows · ≥40 run-locked terminal OOS rows · "
            "purge equals label horizon · three purged supervised folds · no automatic promotion."
        )
    config = PatternDiscoveryConfig(
        horizon_bars=int(horizon),
        transaction_cost_bps=float(costs),
        max_clusters=int(max_clusters),
        fdr_alpha=float(fdr_alpha),
    )
    bundle = build_pattern_feature_bundle(price_data, snapshot.symbol, config)
    integrity = dict(snapshot.audit.get("context_integrity") or {})
    subject_ok = (
        integrity.get("state") == "MATCHED"
        and integrity.get("fusion_allowed") is True
        and str(integrity.get("requested_symbol") or "").upper() == snapshot.symbol.upper()
    )
    ready = subject_ok and not bundle.audit.blocking_reasons and len(bundle.features) >= config.min_rows
    audit = bundle.audit
    controls = st.columns(7)
    with controls[0]:
        card("Source", audit.source, audit.source_status, tone="cyan" if audit.source_identified else "amber")
    with controls[1]:
        card("Normalized rows", str(audit.normalized_rows), f"{len(bundle.features)} usable causal rows")
    with controls[2]:
        card(
            "Dataset cutoff",
            audit.data_cutoff.strftime("%Y-%m-%d") if audit.data_cutoff else "N/A",
            audit.recency,
        )
    with controls[3]:
        card(
            "PIT contract",
            "INTERNALLY CHECKED" if audit.pit_lineage_complete else "UNVERIFIED",
            "known by next open + admissible revisions" if audit.pit_lineage_complete else "strategic quarantine",
            tone="green" if audit.pit_lineage_complete else "amber",
        )
    with controls[4]:
        card(
            "Subject identity",
            "MATCHED" if subject_ok else "BLOCKED",
            f"requested / governed {snapshot.symbol}",
            tone="green" if subject_ok else "red",
        )
    with controls[5]:
        card(
            "Run readiness",
            "READY" if ready else "WAITING DATA",
            f"minimum {config.min_rows} usable rows",
            tone="green" if ready else "amber",
        )
    with controls[6]:
        price_contract_ok = audit.open_price_observed and audit.corporate_action_safe
        card(
            "Price provenance",
            "OBSERVED" if price_contract_ok else "BLOCKED",
            (
                f"open yes · adjustment {audit.price_adjustment_policy}"
                if price_contract_ok
                else "observed next-open + safe adjustment required"
            ),
            tone="green" if price_contract_ok else "red",
        )
    if bundle.audit.blocking_reasons:
        message = "Input contract blocked: " + " ".join(bundle.audit.blocking_reasons)
        if "NO_MARKET_HISTORY" in bundle.audit.quality_flags:
            st.warning(message)
        else:
            st.error(message)
    elif len(bundle.features) < config.min_rows:
        st.warning(
            f"Only {len(bundle.features)} causal rows survive feature warm-up and labels. Load a deeper terminal "
            f"history so at least {config.min_rows} rows remain; no estimator has been fitted."
        )
    if not subject_ok:
        st.error("Subject isolation is active. Pattern training is disabled because requested and governed identities do not match.")
    if bundle.audit.quality_flags:
        st.caption("Input flags · " + " · ".join(bundle.audit.quality_flags))
    return config, bundle, ready


def _render_decision_cockpit(
    report: PatternDiscoveryReport,
    bridge: PatternStrategyBridge,
) -> None:
    screened = sum(
        candidate.state == PatternCandidateState.RUN_LOCAL_SCREENED_HYPOTHESIS
        for candidate in report.candidates
    )
    nearest = next(
        (candidate for candidate in report.candidates if candidate.pattern_id == report.nearest_pattern_id),
        None,
    )
    top = st.columns(6)
    with top[0]:
        card(
            "Engine state",
            report.state.value,
            report.engine_version,
            tone=tone_for_status(report.state.value),
        )
    with top[1]:
        card("Discovered states", str(len(report.candidates)), f"k={report.selected_clusters}")
    with top[2]:
        card("Run-locked terminal OOS", str(report.holdout_rows), f"purge {report.purge_rows} bars", tone="cyan")
    with top[3]:
        card(
            "Run-local screen",
            str(screened),
            "diagnostic hypotheses · not validated FDR",
            tone="cyan" if screened else "amber",
        )
    with top[4]:
        card(
            "Nearest trained state",
            nearest.pattern_id[-8:] if nearest else "N/A",
            f"{report.current_assignment_status} · proximity {_number(nearest.current_match_score if nearest else None)}",
            tone="amber" if report.current_assignment_status == "UNASSIGNED_OOD" else "cyan",
        )
    with top[5]:
        card(
            "Strategic bridge",
            bridge.status_label,
            "current memo unchanged",
            tone=tone_for_status(bridge.state.value),
        )

    bridge_tone = tone_for_status(bridge.state.value)
    st.markdown(
        f'''<div class="mi-decision-hero">
          <div class="mi-decision-question"><span>RESEARCH DECISION</span><h3>{esc(report.reason)}</h3>
            <p>Unsupervised market-state discovery, direction fixed in train, evaluation only on run-locked terminal OOS outcomes after declared cost.</p></div>
          <div class="mi-decision-answer mi-decision-answer-{esc(bridge_tone)}"><span>STRATEGIC HANDOFF</span><h3>{esc(bridge.status_label)}</h3>
            <p>{esc(bridge.strategic_action)} Current memo admission: NO.</p></div>
        </div>''',
        unsafe_allow_html=True,
    )
    if nearest is not None:
        if report.current_assignment_status == "UNASSIGNED_OOD":
            st.warning(
                "The current observation is outside the train-fit q99 novelty heuristic. It remains UNASSIGNED_OOD; "
                "the nearest trained state below is contextual only and is not a state assignment."
            )
        left, right = st.columns([1.35, 1.0], gap="medium")
        with left:
            st.markdown(
                f'''<div class="mi-state"><div class="mi-card-title">NEAREST TRAINED STATE · {esc(nearest.pattern_id)}</div>
                <div class="mi-state-code">{esc(report.current_assignment_status)} · {esc(nearest.state.value)}</div>
                <div class="mi-state-copy">{esc(nearest.signature)}</div>
                <div class="mi-chip-row"><span class="mi-chip">TRAIN DIRECTION {esc(nearest.direction)}</span>
                <span class="mi-chip">PROXIMITY HEURISTIC {_number(nearest.current_match_score)}</span>
                <span class="mi-chip">EXECUTION DISABLED</span></div></div>''',
                unsafe_allow_html=True,
            )
        with right:
            decision = pd.DataFrame(
                [
                    {"Decision field": "Current assignment", "Value": report.current_assignment_status},
                    {"Decision field": "Nearest-state research status", "Value": nearest.state.value},
                    {"Decision field": "Run-locked terminal OOS after cost", "Value": _pct(nearest.oos_after_cost_mean)},
                    {"Decision field": "Conditional uplift", "Value": _pct(nearest.conditional_uplift)},
                    {"Decision field": "Run-local BY diagnostic q", "Value": _number(nearest.fdr_q_value)},
                    {"Decision field": "Stability", "Value": nearest.stability},
                    {"Decision field": "Capital / execution", "Value": "ABSENT / DISABLED"},
                ]
            )
            bounded_table(decision, height=285)


def _render_discovery_map(report: PatternDiscoveryReport) -> None:
    frame = pattern_candidates_frame(report)
    selection = st.dataframe(
        frame,
        width="stretch",
        hide_index=True,
        height=310,
        key="mi_patterns_ml_grid",
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "Train forward mean (%)": st.column_config.NumberColumn(format="%.3f%%"),
            "OOS forward mean (%)": st.column_config.NumberColumn(format="%.3f%%"),
            "OOS after cost (%)": st.column_config.NumberColumn(format="%.3f%%"),
            "OOS rest after cost (%)": st.column_config.NumberColumn(format="%.3f%%"),
            "Conditional uplift (%)": st.column_config.NumberColumn(format="%.3f%%"),
            "OOS hit rate (%)": st.column_config.NumberColumn(format="%.1f%%"),
            "Proximity heuristic": st.column_config.ProgressColumn(min_value=0.0, max_value=1.0, format="%.2f"),
        },
    )
    selected = _selected_candidate(report, selection)
    a, b = st.columns([1.15, 1.0], gap="medium")
    with a:
        st.markdown(
            f'''<div class="mi-state"><div class="mi-card-title">SELECTED PATTERN · {esc(selected.pattern_id)}</div>
            <div class="mi-state-code">{esc(selected.state.value)}</div>
            <div class="mi-state-copy">{esc(selected.signature)}</div>
            <div class="mi-chip-row"><span class="mi-chip">DIRECTION {esc(selected.direction)}</span>
            <span class="mi-chip">TRAIN {selected.train_occurrences}</span><span class="mi-chip">OOS {selected.oos_occurrences}</span>
            <span class="mi-chip">NON-OVERLAP {selected.oos_nonoverlap_occurrences}</span></div></div>''',
            unsafe_allow_html=True,
        )
    with b:
        evidence = pd.DataFrame(
            [
                {"Measure": "Train forward mean", "Value": _pct(selected.train_mean_forward_return)},
                {"Measure": "Run-locked terminal OOS forward mean", "Value": _pct(selected.oos_mean_forward_return)},
                {"Measure": "Run-locked terminal OOS after cost", "Value": _pct(selected.oos_after_cost_mean)},
                {"Measure": "OOS rest after cost", "Value": _pct(selected.oos_rest_after_cost_mean)},
                {"Measure": "Conditional uplift vs rest", "Value": _pct(selected.conditional_uplift)},
                {"Measure": "Hit rate", "Value": _pct(selected.oos_hit_rate)},
                {
                    "Measure": "Full-OOS per-bar Sharpe / lower 95%",
                    "Value": (
                        f"{_number(selected.oos_strategy_sharpe)} / "
                        f"{_number(selected.oos_strategy_sharpe_lower_95)}"
                    ),
                },
                {
                    "Measure": "Non-overlap Deflated Sharpe probability",
                    "Value": _pct(selected.deflated_sharpe_probability),
                },
                {
                    "Measure": "Shift diagnostic p / BY diagnostic q",
                    "Value": f"{_number(selected.raw_p_value)} / {_number(selected.fdr_q_value)}",
                },
            ]
        )
        bounded_table(evidence, height=285)
    try:
        import plotly.graph_objects as go

        chart = frame.dropna(subset=["OOS after cost (%)", "BY diagnostic q"]).copy()
        if not chart.empty:
            colors = {
                PatternCandidateState.RUN_LOCAL_SCREENED_HYPOTHESIS.value: "#45d6e0",
                PatternCandidateState.PROMISING_HYPOTHESIS.value: "#e0bd45",
                PatternCandidateState.REJECTED_OOS.value: "#ff6b6b",
                PatternCandidateState.INSUFFICIENT_OOS.value: "#78909c",
            }
            figure = go.Figure()
            for state, group in chart.groupby("State", sort=False):
                figure.add_trace(
                    go.Scatter(
                        x=group["BY diagnostic q"],
                        y=group["OOS after cost (%)"],
                        mode="markers+text",
                        name=state,
                        text=group["Pattern ID"].str[-6:],
                        textposition="top center",
                        marker={
                            "size": 12 + group["Run-locked OOS occurrences"].clip(0, 80) * 0.35,
                            "color": colors.get(state, "#7ec8e3"),
                            "line": {"color": "rgba(255,255,255,.35)", "width": 1},
                        },
                        customdata=group[["Signature", "Run-locked OOS occurrences"]],
                        hovertemplate="%{customdata[0]}<br>OOS=%{customdata[1]}<br>q=%{x:.3f}<br>net=%{y:.3f}%<extra></extra>",
                    )
                )
            figure.add_vline(x=report.config.fdr_alpha, line_dash="dash", line_color="#e0bd45")
            figure.add_hline(y=0.0, line_dash="dot", line_color="#ff6b6b")
            figure.update_layout(
                height=390,
                margin={"l": 35, "r": 20, "t": 35, "b": 35},
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(8,18,24,.35)",
                font={"color": "#cfe1e7"},
                xaxis_title="Run-local circular-shift / BY diagnostic q",
                yaxis_title="Mean outcome after declared cost (%)",
                legend_title="Research state",
            )
            st.plotly_chart(figure, width="stretch", config={"displayModeBar": False})
    except Exception:
        st.caption("Discovery map unavailable; the governed evidence table remains authoritative.")


def _render_validation(report: PatternDiscoveryReport) -> None:
    fdr_gate = next((gate for gate in report.gates if gate.gate_id == "FDR_CORRECTION"), None)
    fdr_open = fdr_gate is None or fdr_gate.state.value != "PASS"
    left, right = st.columns([1.15, 1.0], gap="medium")
    with left:
        section_header("CONTROL MATRIX", "Admission gates", "FAIL-CLOSED · EVIDENCE-LINKED")
        bounded_table(pattern_gates_frame(report), height=470)
    with right:
        section_header("TEMPORAL DESIGN", "Selection → purge → run-locked terminal OOS", "NO RANDOM SPLIT")
        split = pd.DataFrame(
            [
                {"Segment": "Selection / fit", "Rows": report.train_rows, "Permitted use": "Scaler, centroids, direction"},
                {"Segment": "Purged gap", "Rows": report.purge_rows, "Permitted use": "NONE — label overlap control"},
                {"Segment": "Run-locked terminal OOS", "Rows": report.holdout_rows, "Permitted use": "Evaluation only"},
            ]
        )
        bounded_table(split, height=185)
        st.markdown(
            f'''<div class="mi-state"><div class="mi-card-title">MULTIPLE-TESTING SCOPE</div>
            <div class="mi-state-code">RUN-LOCAL BY DIAGNOSTIC · {'ADMISSION BLOCKED' if fdr_open else 'POLICY REVIEW'}</div>
            <div class="mi-state-copy">The disclosed family contains all {len(report.candidates)} reported clusters; under-powered tests remain in the family as p=1 but are not displayed as estimates.
            Circular-shift invariance is not independently established, so this screen never claims validated FDR. White Reality Check / Hansen SPA and PBO remain open until the complete experiment history is registered.</div></div>''',
            unsafe_allow_html=True,
        )


def _render_models(report: PatternDiscoveryReport) -> None:
    scores = model_scores_frame(report)
    if scores.empty:
        st.warning("The supervised challenger control plane did not return an admissible leaderboard. Discovery remains isolated and research-only.")
        return
    top = st.columns(4)
    selected_challenger = next((row for row in report.model_scores if row.model == report.supervised_champion), None)
    with top[0]:
        card(
            "Selected classification challenger",
            report.supervised_champion or "N/A",
            report.supervised_engine_version or "engine unavailable",
            tone="cyan",
        )
    with top[1]:
        card(
            "OOS balanced accuracy",
            _number(selected_challenger.balanced_accuracy if selected_challenger else None),
            "purged expanding folds",
        )
    with top[2]:
        card("OOS Brier", _number(selected_challenger.brier if selected_challenger else None), "lower is better")
    with top[3]:
        card(
            "Promotion gate",
            report.supervised_promotion_status,
            "classification only · economic promotion closed",
            tone="amber",
        )
    bounded_table(scores, height=330)
    st.info(
        "The selected classification challenger is a separate diagnostic over the same causal matrix. "
        "Its leaderboard does not convert a cluster into alpha and cannot override the run-locked terminal OOS test."
    )


def _render_lineage(
    report: PatternDiscoveryReport,
    bridge: PatternStrategyBridge,
) -> None:
    if not _verified_report(report):
        st.error("Report integrity check failed. Rendering and export are disabled; re-run the governed engine.")
        return
    identity = pd.DataFrame(
        [
            {"Field": "Report ID", "Value": report.report_id},
            {"Field": "Content hash", "Value": report.content_hash},
            {
                "Field": "Integrity boundary",
                "Value": "SELF-CONSISTENCY ONLY · NO EXTERNAL SIGNATURE / AUTHENTICITY CLAIM",
            },
            {"Field": "Dataset ID", "Value": report.input_audit.dataset_id},
            {
                "Field": "Requested / source subject",
                "Value": f"{report.input_audit.symbol} / {report.input_audit.source_symbol}",
            },
            {"Field": "Engine / policy", "Value": f"{report.engine_version} / {report.policy_version}"},
            {"Field": "Source", "Value": f"{report.input_audit.source} · {report.input_audit.source_status}"},
            {
                "Field": "Economic price contract",
                "Value": (
                    f"open observed={report.input_audit.open_price_observed} · "
                    f"adjusted close observed={report.input_audit.adjusted_close_observed} · "
                    f"{report.input_audit.price_adjustment_policy}"
                ),
            },
            {
                "Field": "PIT contract known-at / revisions",
                "Value": (
                    f"{report.input_audit.source_known_at.isoformat() if report.input_audit.source_known_at else 'UNDECLARED'} "
                    f"· {report.input_audit.revision_policy}"
                ),
            },
            {
                "Field": "PIT contract status",
                "Value": "INTERNALLY CHECKED" if report.input_audit.pit_lineage_complete else "UNVERIFIED",
            },
            {"Field": "Data cutoff", "Value": report.input_audit.data_cutoff.isoformat() if report.input_audit.data_cutoff else "N/A"},
            {
                "Field": "Latest row known-at",
                "Value": (
                    report.input_audit.latest_row_known_at.isoformat()
                    if report.input_audit.latest_row_known_at
                    else "UNDECLARED"
                ),
            },
            {"Field": "Report evaluated-at", "Value": report.evaluated_at.isoformat()},
            {"Field": "Feature count", "Value": str(len(report.feature_names))},
            {
                "Field": "Runtime",
                "Value": " · ".join(f"{name} {version}" for name, version in report.runtime_versions),
            },
            {"Field": "Strategic bridge", "Value": f"{bridge.bridge_id} · {bridge.state.value}"},
            {"Field": "Current memo admission", "Value": "NO — IMMUTABLE"},
            {"Field": "Authority", "Value": "RESEARCH ONLY · HUMAN REVIEW REQUIRED · EXECUTION DISABLED"},
        ]
    )
    bounded_table(identity, height=360)
    st.download_button(
        "EXPORT MACHINE-VERIFIABLE PATTERN REPORT · JSON",
        data=canonical_json(
            {
                "report": report,
                "verification": {
                    "content_hash_valid": True,
                    "scope": "RESEARCH_ONLY",
                    "autonomous_trading": False,
                    "capital_authority": False,
                    "execution_allowed": False,
                },
            }
        ),
        file_name=f"mi_pattern_report_{report.symbol}_{report.report_id}.json",
        mime="application/json",
        width="stretch",
        type="secondary",
        key="mi_pattern_report_export",
    )
    with st.expander("FEATURE MANIFEST & RUN CONFIGURATION", expanded=False):
        st.code("\n".join(report.feature_names), language="text")
        st.json(asdict(report.config), expanded=False)
        if report.fit_artifact is not None:
            st.caption(
                "Exact imputer, scaler, centroid, cluster search, every q99 novelty threshold, current scaled vector "
                "and all current centroid distances are bound into the report hash. The q99 boundary remains an "
                "uncalibrated train-fit heuristic."
            )
            st.json(asdict(report.fit_artifact), expanded=False)


def render_discovered_patterns(
    snapshot: WorkspaceSnapshot,
    *,
    price_data: Any = None,
    strategic_memo: StrategicDecisionMemo | None = None,
    pattern_bridge: PatternStrategyBridge | None = None,
) -> None:
    section_header(
        "GOVERN DESK / 11",
        "ML Pattern Discovery & Strategic Evidence Lab",
        "REAL FIT · CAUSAL FEATURES · RUN-LOCKED TERMINAL OOS · RESEARCH ONLY",
    )
    st.markdown(
        '<div class="mi-alert"><b>MACHINE DISCOVERY IS A HYPOTHESIS FACTORY, NOT AN ALPHA CERTIFICATE.</b> '
        "The engine can discover recurring market states, estimate run-locked terminal OOS outcomes and recommend the next "
        "research action. It cannot auto-promote a model, select capital, create an order or rewrite an existing memo.</div>",
        unsafe_allow_html=True,
    )
    config, bundle, ready = _render_configuration(snapshot, price_data)
    current_report = st.session_state.get("mi_pattern_discovery_report")
    report = current_report if isinstance(current_report, PatternDiscoveryReport) else None
    same_run = bool(
        report is not None
        and _verified_report(report)
        and report.input_audit.dataset_id == bundle.audit.dataset_id
        and report.config == config
        and report.symbol == snapshot.symbol.upper()
    )
    completed_notice = st.session_state.pop("mi_pattern_report_notice", None)
    if completed_notice and same_run and report is not None:
        st.success(f"Governed research report created · {report.report_id}")
    if report is not None and not same_run:
        if not _verified_report(report):
            st.error(
                "The cached report failed its immutable content-hash check. Rendering, export and strategic "
                "handoff are disabled until the governed engine is re-run."
            )
        else:
            st.warning(
                "A prior session report exists, but its dataset identity or visible protocol differs from the "
                "current research context. It is detached and excluded from rendering and the strategic bridge "
                "until re-run."
            )
    run = st.button(
        "RUN GOVERNED ML PATTERN DISCOVERY",
        type="primary",
        width="stretch",
        disabled=not ready,
        key="mi_pattern_run_engine",
        help="Fits deterministic train-only clusters, evaluates a purged run-locked terminal OOS segment, then runs the ML Lab challenger diagnostic.",
    )
    if run:
        with st.spinner("Fitting market-state discovery and purged OOS challengers…"):
            from ..patterns.engine import discover_market_patterns

            report = discover_market_patterns(
                price_data,
                snapshot.symbol,
                config,
            )
            st.session_state["mi_pattern_discovery_report"] = report
            same_run = bool(
                _verified_report(report)
                and report.input_audit.dataset_id == bundle.audit.dataset_id
                and report.config == config
                and report.symbol == snapshot.symbol.upper()
            )
        if not _verified_report(report):
            st.error("The engine returned an unverifiable artifact. It is quarantined and cannot be rendered or exported.")
        else:
            # The strategy ribbon is rendered before this workspace. A single
            # controlled rerun makes it consume the newly signed report in the
            # same visible interaction instead of showing a stale NOT_RUN state.
            st.session_state["mi_pattern_report_notice"] = report.report_id
            st.rerun()

    active_report = report if same_run else None
    if pattern_bridge is None or (active_report is not None and pattern_bridge.report_id != active_report.report_id):
        pattern_bridge = build_pattern_strategy_bridge(
            snapshot,
            active_report,
            current_dataset_id=bundle.audit.dataset_id if bundle.audit.normalized_rows else None,
            memo_id=strategic_memo.memo_id if strategic_memo is not None else None,
        )
    if active_report is None:
        section_header("ENGINE READINESS", "What becomes available after a governed run", "NO CACHED RESULT IMPLIED")
        readiness = pd.DataFrame(
            [
                {"Layer": "Causal representation", "Method": "Up to 25 backward-looking price, shape, volatility, drawdown and liquidity features", "Decision value": "Describe recurring market states without chart-image theatre"},
                {"Layer": "Unsupervised discovery", "Method": "Train-only robust scaling + k-means + return-blind silhouette selection", "Decision value": "Generate a bounded family of recurring state hypotheses"},
                {"Layer": "Run-locked economic test", "Method": "Direction fixed in train; next-open entry; purged terminal OOS; cost; conditional uplift vs rest", "Decision value": "Reject states that do not survive chronology, baseline or cost"},
                {"Layer": "Multiplicity", "Method": "Circular-shift + Benjamini-Yekutieli run-local diagnostic; non-overlap Deflated Sharpe", "Decision value": "Screen conservatively while keeping inferential and global experiment debt explicit"},
                {"Layer": "Supervised challenge", "Method": "Prior, logistic, boosted tree and Extra Trees on purged expanding folds", "Decision value": "Falsify whether nonlinear complexity improves causal OOS classification"},
                {"Layer": "Strategic bridge", "Method": "Dataset, subject, clock, PIT contract, shadow and independent-review gates", "Decision value": "Convert evidence gaps into a bounded research action, never a trade"},
            ]
        )
        bounded_table(readiness, height=365)
    elif active_report.state != PatternRunState.COMPLETED_RESEARCH_ONLY:
        st.error(f"{active_report.state.value} · {active_report.reason}")
        bounded_table(pattern_gates_frame(active_report), height=260)
    else:
        _render_decision_cockpit(active_report, pattern_bridge)
        cockpit, discovery, validation, models, lineage = st.tabs(
            ("DECISION COCKPIT", "DISCOVERY MAP", "OOS & GATES", "NONLINEAR CHALLENGER", "LINEAGE & EXPORT")
        )
        with cockpit:
            action = pd.DataFrame(
                [
                    {"Strategic field": "Bridge state", "Decision": pattern_bridge.state.value},
                    {"Strategic field": "Recommended research action", "Decision": pattern_bridge.strategic_action},
                    {"Strategic field": "Why", "Decision": pattern_bridge.reason},
                    {"Strategic field": "Admitted to current memo", "Decision": "NO"},
                    {"Strategic field": "Capital authority", "Decision": "NONE"},
                    {"Strategic field": "Execution", "Decision": "DISABLED"},
                ]
            )
            bounded_table(action, height=280)
            st.info(
                "The useful decision is the next controlled research action: re-run, acquire lineage, extend OOS, "
                "start shadow observation, or submit an immutable enlarged packet for independent review."
            )
        with discovery:
            _render_discovery_map(active_report)
        with validation:
            _render_validation(active_report)
        with models:
            _render_models(active_report)
        with lineage:
            _render_lineage(active_report, pattern_bridge)

    with st.expander("LEGACY PATTERN TAXONOMY · PRESERVED FOR LINEAGE", expanded=False):
        bounded_table(snapshot.patterns.copy(), height=245)
    provenance(
        "Actual estimators run only against inherited chronological OHLCV. Canonical fixture patterns remain labelled "
        "taxonomy, not training data. Run-local circular-shift/BY diagnostics and non-overlap Deflated Sharpe do not establish validated FDR or replace a complete White Reality Check, "
        "Hansen SPA, PBO, independently verified point-in-time provider lineage, forward shadow history or independent human review."
    )
