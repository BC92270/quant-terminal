"""Streamlit cockpit for the institutional V7 layer."""
from __future__ import annotations

from dataclasses import asdict
import json
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .engine import run_institutional_stack
from .execution import ExecutionModelConfig
from .registry import ExperimentRegistry, _json_safe
from .scenarios import ScenarioConfig


def _config_payload(cfg: Any) -> dict[str, Any]:
    values = vars(cfg) if hasattr(cfg, "__dict__") else dict(cfg or {})
    return {
        str(key): _json_safe(value)
        for key, value in values.items()
        if not isinstance(value, (pd.DataFrame, pd.Series))
    }


def _metric(value: Any, *, percent: bool = False, decimals: int = 2) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "DATA REQUIRED"
    if not np.isfinite(number):
        return "DATA REQUIRED"
    return f"{number:.{decimals}%}" if percent else f"{number:.{decimals}f}"


def _candidate_matrix(upload: Any, index: pd.Index) -> pd.DataFrame | None:
    if upload is None:
        return None
    raw = pd.read_csv(upload)
    if raw.empty:
        return None
    numeric = raw.apply(pd.to_numeric, errors="coerce")
    useful = numeric.columns[numeric.notna().sum() >= max(3, len(raw) // 2)]
    numeric = numeric[useful]
    if numeric.empty:
        return None
    if len(numeric) == len(index):
        numeric.index = index
    elif len(numeric) < len(index):
        numeric.index = index[-len(numeric):]
    else:
        numeric = numeric.iloc[-len(index):]
        numeric.index = index
    return numeric


def render_institutional_v70(
    *,
    bars: pd.DataFrame,
    result: dict[str, Any],
    cfg: Any,
    symbol: str,
) -> None:
    st.markdown("## Institutional Backtest V7")
    st.caption(
        "Couche auditable et fail-closed : données, ledger événementiel, coûts calibrables, "
        "validation multi-tests, scénarios de rupture, registre et dossier de gouvernance."
    )
    legacy = result.get("data", pd.DataFrame())
    if not isinstance(legacy, pd.DataFrame) or legacy.empty:
        st.error(result.get("error", "Le moteur de référence ne fournit aucune série exploitable."))
        return

    with st.expander("V7 · Assumptions & calibration", expanded=True):
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            execution_model = st.selectbox(
                "Execution model",
                ["square_root", "volume_share", "almgren_chriss_proxy", "constant"],
                key="bt_v70_execution_model",
            )
            point_in_time = st.checkbox(
                "Point-in-time snapshot certified",
                value=False,
                key="bt_v70_point_in_time",
                help="À activer uniquement si l’adaptateur et l’univers sont effectivement horodatés sans biais de survie.",
            )
        with c2:
            spread_bps = st.number_input("Spread (bps)", 0.0, 500.0, 2.0, 0.25, key="bt_v70_spread")
            impact_coefficient = st.number_input(
                "Impact coefficient", 0.0, 5.0, 0.10, 0.01, key="bt_v70_impact"
            )
        with c3:
            max_participation = st.slider(
                "Max participation", 0.01, 0.50, 0.10, 0.01, key="bt_v70_participation"
            )
            annual_borrow_bps = st.number_input(
                "Borrow fallback (bps, 0 = unavailable)", 0.0, 5000.0, 0.0, 5.0,
                key="bt_v70_borrow",
            )
        with c4:
            scenario_paths = st.select_slider(
                "Scenario paths", options=[100, 250, 500, 800], value=250, key="bt_v70_paths"
            )
            scenario_horizon = st.select_slider(
                "Horizon (days)", options=[63, 126, 252, 504], value=252, key="bt_v70_horizon"
            )

        s1, s2, s3, s4 = st.columns(4)
        with s1:
            scenario_seed = st.number_input("Reproducibility seed", 1, 1_000_000, 41, 1, key="bt_v70_seed")
        with s2:
            confidence = st.selectbox("Tail confidence", [0.95, 0.975, 0.99], index=1, key="bt_v70_confidence")
        with s3:
            target_drawdown = st.slider(
                "Reverse-stress drawdown", -0.60, -0.05, -0.20, 0.01, key="bt_v70_reverse_dd"
            )
        with s4:
            candidate_file = st.file_uploader(
                "Candidate returns (CSV)",
                type=["csv"],
                key="bt_v70_candidates",
                help="Une colonne par stratégie/paramétrage pour DSR, CSCV/PBO, Reality Check, SPA, Holm et FDR.",
            )

    candidate_returns = _candidate_matrix(candidate_file, legacy.index)
    capital = float(getattr(cfg, "capital", 1_000_000.0))
    fee_bps = float(getattr(cfg, "fee_bps", 0.5))
    slip_bps = float(getattr(cfg, "slippage_bps", 1.0))
    execution_config = ExecutionModelConfig(
        model=execution_model,
        initial_capital=capital,
        commission_bps=fee_bps,
        spread_bps=float(spread_bps),
        slippage_bps=slip_bps,
        impact_coefficient=float(impact_coefficient),
        max_participation=float(max_participation),
        annual_borrow_bps=float(annual_borrow_bps) if annual_borrow_bps > 0 else None,
    )
    scenario_config = ScenarioConfig(
        horizon_days=int(scenario_horizon),
        paths=int(scenario_paths),
        seed=int(scenario_seed),
        confidence=float(confidence),
        target_drawdown=float(target_drawdown),
    )
    try:
        institutional = run_institutional_stack(
            bars=bars,
            legacy_result=result,
            strategy=str(getattr(cfg, "strategy", "UNSPECIFIED")),
            symbol=symbol,
            config_payload=_config_payload(cfg),
            execution_config=execution_config,
            scenario_config=scenario_config,
            candidate_returns=candidate_returns,
            seed=int(scenario_seed),
            point_in_time=bool(point_in_time),
        )
    except Exception as exc:
        st.error(f"Institutional V7 engine: {exc}")
        return

    decision = institutional.gate["decision"]
    if decision == "RESEARCH APPROVED":
        st.success(f"Decision gate · {decision}")
    elif decision == "CONDITIONAL REVIEW":
        st.warning(f"Decision gate · {decision}")
    else:
        st.error(f"Decision gate · {decision}")

    k1, k2, k3, k4, k5 = st.columns(5)
    dsr = institutional.validation["dsr"]["deflated_sharpe_probability"]
    pbo = institutional.validation["pbo"]["pbo"]
    reverse = institutional.scenarios["reverse_stress"]
    k1.metric("Run ID", institutional.manifest.run_id[-10:])
    k2.metric("Data gate", institutional.data_catalog.verdict.value)
    k3.metric("DSR probability", _metric(dsr, percent=True))
    k4.metric("PBO", _metric(pbo, percent=True))
    k5.metric("Reverse shock ×", _metric(reverse.get("multiplier")))

    cockpit_tab, data_tab, stats_tab, scenario_tab, governance_tab = st.tabs([
        "Decision Cockpit", "Data & Execution", "Statistical Validation",
        "Scenario Lab", "Registry & Governance",
    ])

    with cockpit_tab:
        st.dataframe(institutional.gate["checks"], use_container_width=True, hide_index=True)
        st.markdown("#### Institutional architecture")
        st.dataframe(pd.DataFrame([
            ["Data Catalog", institutional.data_catalog.verdict.value, "PIT, OHLC QA, actions, survivorship, borrow, capacity"],
            ["Event Ledger", institutional.execution.status.value, "Orders, fills, partials, settlement, cash, positions"],
            ["Research Validation", "ACTIVE", "DSR, CSCV/PBO, CPCV, Reality Check, SPA, Holm, FDR"],
            ["Scenario Engine", "ACTIVE", "Student-t, Markov, EVT, liquidity spiral, reverse stress"],
            ["Governance", "ACTIVE", "Immutable run ID, lineage, model card, export bundle"],
        ], columns=["Layer", "State", "Decision use"]), use_container_width=True, hide_index=True)
        st.info("Le verdict V7 reste un gate de recherche. Il n’autorise jamais automatiquement un déploiement production.")

    with data_tab:
        catalog_rows = []
        for name, status in institutional.data_catalog.fields.items():
            catalog_rows.append({
                "field": name, "state": status.state.value, "required": status.required,
                "missing": status.missing_ratio, "reason": status.reason,
            })
        st.markdown("#### Data Catalog")
        st.dataframe(pd.DataFrame(catalog_rows), use_container_width=True, hide_index=True)
        st.markdown("#### Capability matrix")
        capability_rows = [
            {"capability": name, "state": item.state.value, "reason": item.reason}
            for name, item in institutional.data_catalog.capabilities.items()
        ]
        st.dataframe(pd.DataFrame(capability_rows), use_container_width=True, hide_index=True)
        e1, e2, e3, e4 = st.columns(4)
        diagnostics = institutional.execution.diagnostics
        e1.metric("Ledger state", institutional.execution.status.value)
        e2.metric("Fills", diagnostics.get("filled_orders", 0))
        e3.metric("Partial / rejected", f"{diagnostics.get('partial_orders', 0)} / {diagnostics.get('rejected_orders', 0)}")
        e4.metric("Total costs", f"{diagnostics.get('total_cost', 0.0):,.0f}")
        if institutional.execution.daily is not None and not institutional.execution.daily.empty:
            daily = institutional.execution.daily
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=daily.index, y=daily["nav"], name="Execution NAV", line=dict(color="#38bdf8")))
            fig.update_layout(template="plotly_dark", height=360, margin=dict(l=20, r=20, t=30, b=20))
            st.plotly_chart(fig, use_container_width=True)
        fills = pd.DataFrame(institutional.execution.records()["fills"])
        st.dataframe(fills.tail(250), use_container_width=True, hide_index=True)

    with stats_tab:
        validation = institutional.validation
        v1, v2, v3, v4, v5 = st.columns(5)
        v1.metric("Sharpe", _metric(validation["sharpe"]))
        v2.metric("PSR", _metric(validation["psr"], percent=True))
        v3.metric("DSR", _metric(validation["dsr"]["deflated_sharpe_probability"], percent=True))
        v4.metric("CSCV / PBO", _metric(validation["pbo"]["pbo"], percent=True))
        v5.metric("Min track record", _metric(validation["minimum_track_record_days"]) + " d")
        tests = pd.DataFrame([
            ["White Reality Check", validation["white_reality_check"]["p_value"], "Bootstrap max-performance"],
            ["Hansen SPA", validation["hansen_spa"]["p_value"], "Studentized superior predictive ability"],
            ["CPCV paths", validation["cpcv_splits"], "Purged + embargo combinatorial splits"],
            ["Candidate family", validation["candidate_count"], "Uploaded strategies / parameter trials"],
        ], columns=["Test", "Value", "Method"])
        st.dataframe(tests, use_container_width=True, hide_index=True)
        if candidate_returns is None:
            st.warning("PBO, Reality Check, SPA, Holm et FDR exigent une vraie famille de candidats. Importer le CSV des essais ; aucun scénario synthétique n’est présenté comme une observation réelle.")
        else:
            corrections = pd.DataFrame({
                "candidate": list(candidate_returns.columns),
                "Holm adjusted p": [row.get("adjusted_p") for row in validation["holm"]],
                "BH/FDR adjusted p": [row.get("adjusted_p") for row in validation["benjamini_hochberg"]],
            })
            st.dataframe(corrections, use_container_width=True, hide_index=True)

    with scenario_tab:
        summary = institutional.scenarios["summary"].copy()
        st.dataframe(summary.style.format("{:.2%}"), use_container_width=True)
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=summary.index, y=summary["expected_shortfall"],
            name="Terminal Expected Shortfall", marker_color="#fb7185",
        ))
        fig.add_trace(go.Bar(
            x=summary.index, y=summary["median_max_drawdown"],
            name="Median Max Drawdown", marker_color="#fbbf24",
        ))
        fig.update_layout(template="plotly_dark", barmode="group", height=390, margin=dict(l=20, r=20, t=30, b=80))
        st.plotly_chart(fig, use_container_width=True)
        r1, r2, r3 = st.columns(3)
        r1.metric("Reverse multiplier", _metric(reverse.get("multiplier")))
        r2.metric("EVT threshold", _metric(institutional.scenarios["evt"].get("threshold"), percent=True))
        r3.metric("Crisis regime share", _metric(institutional.scenarios["regime_mix"].get("crisis"), percent=True))
        st.json({
            "reverse_stress": reverse,
            "evt_calibration": institutional.scenarios["evt"],
            "regime_mix": institutional.scenarios["regime_mix"],
            "seed": institutional.scenarios["seed"],
        })

    with governance_tab:
        registry = ExperimentRegistry()
        g1, g2 = st.columns([1, 1])
        with g1:
            if st.button("Register immutable experiment", type="primary", key="bt_v70_register"):
                path = registry.persist(institutional.manifest, {
                    "decision": institutional.gate["decision"],
                    "model_card": institutional.model_card,
                    "data_verdict": institutional.data_catalog.verdict.value,
                    "execution": institutional.execution.diagnostics,
                    "validation": institutional.validation,
                    "scenario_summary": institutional.scenarios["summary"],
                })
                st.success(f"Registered · {path}")
        with g2:
            st.download_button(
                "Download reproducibility bundle",
                data=institutional.bundle,
                file_name=f"{institutional.manifest.run_id}.zip",
                mime="application/zip",
                key="bt_v70_download",
            )
        runs = registry.list_runs()
        st.dataframe(runs, use_container_width=True, hide_index=True)
        st.markdown("#### Model card")
        st.json(institutional.model_card)
        st.markdown("#### Reproducibility manifest")
        st.json(_json_safe(asdict(institutional.manifest)))
