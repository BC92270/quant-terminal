from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .config import DependencyConfig
from .engine import DependencyIntelligence, PairDependencyAnalysis
from .export import dependency_research_pack_zip


def _fmt(x: Any, digits: int = 2) -> str:
    try:
        v = float(x)
        return f"{v:.{digits}f}" if np.isfinite(v) else "N/A"
    except Exception:
        return "N/A"


def _pct(x: Any, digits: int = 1) -> str:
    try:
        v = float(x)
        return f"{100*v:.{digits}f}%" if np.isfinite(v) else "N/A"
    except Exception:
        return "N/A"


def _mechanism_chart(df: pd.DataFrame):
    if df is None or df.empty:
        return
    x = df[df["Mechanism"] != "Residual dependency"].copy()
    if x.empty:
        return
    fig = go.Figure(go.Bar(
        x=x["Mechanism"],
        y=x["Correlation contribution"],
        text=x["Correlation contribution"].map(lambda z: f"{z:+.3f}"),
        textposition="auto",
    ))
    fig.add_hline(y=0, line_dash="dash")
    fig.update_layout(
        height=430,
        title="Shapley mechanism attribution — change from raw to force-neutral dependency",
        yaxis_title="Correlation contribution",
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(10,14,22,.55)",
    )
    st.plotly_chart(fig, use_container_width=True)


def _lead_lag_chart(df: pd.DataFrame, primary: str, peer: str):
    if df is None or df.empty:
        return
    fig = go.Figure(go.Bar(x=df["Lag days"], y=df["Correlation"], text=df["Correlation"].map(lambda z: f"{z:.2f}" if pd.notna(z) else ""), textposition="auto"))
    fig.add_hline(y=0, line_dash="dash")
    fig.update_layout(
        height=390,
        title=f"Lead-lag dependency — corr({primary}_t, {peer}_{{t+lag}})",
        xaxis_title="Lag days (positive = primary leads peer)",
        yaxis_title="Correlation",
        yaxis=dict(range=[-1.0, 1.0]),
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(10,14,22,.55)",
    )
    st.plotly_chart(fig, use_container_width=True)


def _coverage_summary(coverage: pd.DataFrame):
    if coverage is None or coverage.empty:
        st.info("Force registry unavailable.")
        return
    total = len(coverage)
    active = coverage[coverage["Status"] != "Not connected"]
    series_statuses = {"Injected series", "Active proxy", "Auto public series", "Auto market series", "Auto derived series"}
    series = coverage[coverage["Status"].isin(series_statuses)]
    events = coverage[coverage["Status"] == "Injected/auto events"]
    mechanisms = active["Mechanism"].nunique() if not active.empty else 0
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Force registry", str(total))
    c2.metric("Connected channels", str(len(active)))
    c3.metric("Active factor series", str(len(series)))
    c4.metric("Mechanisms represented", str(mechanisms))
    if len(events):
        st.caption(f"Event-driven force families connected: {len(events)} registry entries.")


def _render_overview(b: PairDependencyAnalysis):
    s = b.summary
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Raw dependency", _fmt(s.get("raw_corr")))
    c2.metric("Residual dependency", _fmt(s.get("residual_corr")))
    c3.metric("Active factors", str(s.get("factors_used", 0)))
    c4.metric("Primary factor R²", _pct(s.get("primary_factor_r2")))
    c5.metric("Peer factor R²", _pct(s.get("peer_factor_r2")))
    lag = s.get("best_nonzero_lag_days")
    lag_label = "N/A" if lag is None else f"{int(lag):+d}D"
    lag_corr = s.get("best_nonzero_lag_corr")
    lag_ev = s.get("best_nonzero_lag_evidence") or "Unassessed"
    c6.metric("Strongest non-zero lag", lag_label, f"{_fmt(lag_corr)} · {lag_ev}")
    lag_lo, lag_hi, lag_p = s.get("best_nonzero_lag_ci_low"), s.get("best_nonzero_lag_ci_high"), s.get("best_nonzero_lag_p")
    st.caption(
        f"Synchronous pair correlation: {_fmt(s.get('synchronous_corr'), 3)}. "
        f"Selected non-zero lag CI [{_fmt(lag_lo, 3)}, {_fmt(lag_hi, 3)}], max-stat p={_fmt(lag_p, 3)}. "
        "Lag association is post-selection adjusted and is not causality."
    )
    st.caption("Residual dependency is conditional on the active force set. It is not a metaphysical 'true correlation' and must not be interpreted as causal evidence.")


def render_dependency_intelligence_tab(bundle: Any, primary: str, analysis: dict[str, Any] | None = None,
                                       portfolio_weights: dict[str, float] | None = None):
    """Render the multi-force layer inside the Correlation Matrix section.

    `bundle` is the frozen V3.1.1 AnalysisBundle. This function does not mutate it.
    """
    analysis = analysis or {}
    changes = getattr(bundle, "changes", pd.DataFrame())
    ranking = getattr(bundle, "ranking", pd.DataFrame())
    if changes is None or changes.empty or primary not in changes.columns:
        st.info("Dependency Drivers unavailable: frozen core changes are missing.")
        return

    peers = [x for x in changes.columns if x != primary]
    ranked = ranking.get("Ticker", pd.Series(dtype=str)).dropna().astype(str).tolist() if isinstance(ranking, pd.DataFrame) and not ranking.empty else []
    default_peer = next((x for x in ranked if x in peers), peers[0] if peers else None)
    if not default_peer:
        st.info("No peer available.")
        return

    st.subheader("Multi-Force Dependency Intelligence")
    st.caption("This layer explains mechanisms that can generate or alter dependence: fundamentals, macro/policy, FX, flows, ownership, liquidity, derivatives, information, events and structural measurement. The statistical core V3.1.1 remains frozen underneath.")

    left, mid, right = st.columns([1.2, .9, 2.0])
    with left:
        peer = st.selectbox("Pair inspector", peers, index=peers.index(default_peer), key=f"depv401_peer_{primary}")
    with mid:
        modes = ["Max public + project", "Balanced public + project", "Injected only"]
        default_mode = str(analysis.get("dependency_data_hub_mode", "max") or "max").lower()
        mode_index = 2 if "inject" in default_mode or default_mode in {"off", "none"} else 1 if "bal" in default_mode else 0
        hub_mode_label = st.selectbox("Dependency Data Hub", modes, index=mode_index, key=f"depv402_hub_{primary}")
    with right:
        st.markdown("**Identification doctrine:** proxy/regression/event-window outputs are associational unless an upstream dataset explicitly carries a credible structural identification design.")

    run_analysis = dict(analysis)
    run_analysis["dependency_data_hub_mode"] = {
        "Max public + project": "max", "Balanced public + project": "balanced", "Injected only": "injected-only"
    }[hub_mode_label]
    threshold = float(run_analysis.get("dependency_extreme_z_threshold", run_analysis.get("dependency_jump_z_threshold", 3.0)))
    cfg = DependencyConfig(
        max_factors=int(run_analysis.get("dependency_max_factors", 12)),
        lead_lag_max_days=int(run_analysis.get("dependency_lead_lag_max_days", 5)),
        extreme_z_threshold=threshold,
        jump_z_threshold=threshold,
    )
    engine = DependencyIntelligence(cfg)
    dep = engine.analyse_pair(primary, peer, changes, run_analysis, portfolio_weights=portfolio_weights)
    if dep.status != "ok":
        st.warning(dep.summary.get("message", "Dependency layer unavailable."))
        return

    _render_overview(dep)

    sub = st.tabs(["Force Map", "Dependency Decomposition", "Events / Lead-Lag / Extremes", "Market Structure", "Input & Audit"])

    with sub[0]:
        st.markdown("### Force registry & coverage")
        _coverage_summary(dep.coverage)
        mech = dep.coverage.groupby(["Mechanism", "Status"], dropna=False).size().rename("Count").reset_index()
        st.dataframe(mech, use_container_width=True, hide_index=True)
        with st.expander("Full force registry", expanded=False):
            st.dataframe(dep.coverage, use_container_width=True, hide_index=True, height=650)
        st.caption("'Not connected' means the mechanism is represented in the architecture but no live/injected series, event or metadata channel is available in this run. The registry is intentionally open-ended.")

        if dep.force_model.status == "ok":
            st.markdown("### Active factor exposures")
            f = dep.force_model.factor_diagnostics.copy()
            for c in ["Primary beta (1σ)", "Peer beta (1σ)", "Joint beta magnitude"]:
                if c in f:
                    f[c] = f[c].map(lambda z: _fmt(z, 3))
            st.dataframe(f, use_container_width=True, hide_index=True)
            if dep.force_model.factors_dropped:
                with st.expander("Dropped/redundant factors", expanded=False):
                    st.write(", ".join(dep.force_model.factors_dropped))
            if not dep.force_model.selection_diagnostics.empty:
                with st.expander("High-dimensional force selection diagnostics", expanded=False):
                    screen = dep.force_model.selection_diagnostics.copy()
                    for c in ["Primary abs corr", "Peer abs corr", "Relevance", "Coverage", "Temporal stability", "Selection score"]:
                        if c in screen:
                            screen[c] = screen[c].map(lambda z: _fmt(z, 3))
                    st.dataframe(screen, use_container_width=True, hide_index=True, height=420)
                    st.caption("Stability-aware relevance screening precedes the family cap and collinearity guard. It reduces one-window data mining; it is not a causal selector.")
        else:
            st.info("No sufficiently robust active factor set. Inject additional dependency_force_series / metadata to expand attribution.")

    with sub[1]:
        st.markdown("### Dependency spaces")
        spaces = dep.spaces.copy()
        if "Correlation" in spaces:
            spaces["Correlation"] = spaces["Correlation"].map(lambda z: _fmt(z, 3))
        st.dataframe(spaces, use_container_width=True, hide_index=True)

        if dep.force_model.status == "ok":
            fm = dep.force_model
            a, b, c, d, e = st.columns(5)
            a.metric("Raw corr", _fmt(fm.raw_corr, 3))
            b.metric("Residual corr", _fmt(fm.residual_corr, 3))
            c.metric("Systematic covariance", _fmt(fm.systematic_cov, 6))
            d.metric("Residual covariance", _fmt(fm.residual_cov, 6))
            e.metric("Cov reconstruction error", _fmt(fm.reconstruction_error, 10))

            st.markdown("### Mechanism attribution — exact covariance allocation")
            ga = fm.group_attribution.copy()
            if not ga.empty:
                for col in ["Systematic covariance contribution", "Primary beta norm", "Peer beta norm"]:
                    if col in ga:
                        ga[col] = ga[col].map(lambda z: _fmt(z, 6 if "covariance" in col.lower() else 3))
                if "% of systematic covariance" in ga:
                    ga["% of systematic covariance"] = ga["% of systematic covariance"].map(_pct)
                st.dataframe(ga, use_container_width=True, hide_index=True)
                st.caption("Cross-mechanism factor covariance terms are split 50/50 between the two mechanisms, so group contributions reconcile exactly to the model's systematic covariance. Signed shares can exceed 100% when mechanisms offset each other.")

            st.markdown("### Correlation bridge — order-independent Shapley attribution")
            sh = fm.shapley_bridge.copy()
            if not sh.empty:
                _mechanism_chart(sh)
                sh["Correlation contribution"] = sh["Correlation contribution"].map(lambda z: f"{z:+.4f}")
                sh["Absolute magnitude"] = sh["Absolute magnitude"].map(lambda z: _fmt(z, 4))
                st.dataframe(sh, use_container_width=True, hide_index=True)
                st.caption("These are two different decompositions: the covariance table allocates the model's systematic covariance in covariance units; the Shapley bridge allocates the change in correlation from raw to force-neutral dependency. Shapley averages each mechanism's marginal correlation effect across orderings, reducing ordering bias under correlated forces.")
        else:
            st.info("Force decomposition requires an active factor set with sufficient common history.")

    with sub[2]:
        st.markdown("### Lead-lag dependency")
        _lead_lag_chart(dep.lead_lag, primary, peer)
        ll = dep.lead_lag.copy()
        if not ll.empty:
            for c in ["Correlation", "Abs correlation", "CI low", "CI high", "Selection-adjusted p"]:
                if c in ll:
                    ll[c] = ll[c].map(lambda z: _fmt(z, 3))
            st.dataframe(ll, use_container_width=True, hide_index=True)
        st.caption("Positive lag means primary_t is compared with a later peer return. V4.0.2 reports a moving-block CI for the selected lag and a max-stat p-value across all non-zero lags under a synchronous-pair-preserving temporal-null permutation. Association only; not causality.")

        st.markdown("### Daily extreme-move / co-extreme dependency")
        if dep.extremes.empty:
            st.info("Extreme-move diagnostics unavailable on current history.")
        else:
            j = dep.extremes.copy()
            prob_mask = j["Metric"].astype(str).str.startswith("P(") | j["Metric"].astype(str).str.contains("Same-direction")
            j["Value"] = [_pct(v) if is_prob else _fmt(v, 3) for v, is_prob in zip(j["Value"], prob_mask)]
            if "CI low" in j and "CI high" in j:
                lows, highs = [], []
                for lo, hi, is_prob in zip(j["CI low"], j["CI high"], prob_mask):
                    lows.append(_pct(lo) if is_prob else _fmt(lo, 3))
                    highs.append(_pct(hi) if is_prob else _fmt(hi, 3))
                j["CI low"], j["CI high"] = lows, highs
            st.dataframe(j, use_container_width=True, hide_index=True)
            st.caption(f"Daily robust-z extreme-move proxy (|z| ≥ {cfg.extreme_z_threshold:.1f}). Conditional probabilities use Wilson intervals; correlation rows use bootstrap intervals and an explicit sample-quality label. This is not an intraday jump/co-jump test.")

        st.markdown("### Higher-order comoments")
        hm = dep.higher_moments.copy()
        if not hm.empty:
            for c in ["Value", "CI low", "CI high"]:
                if c in hm:
                    hm[c] = hm[c].map(lambda z: _fmt(z, 4))
            if "Sign stability" in hm:
                hm["Sign stability"] = hm["Sign stability"].map(_pct)
            st.dataframe(hm, use_container_width=True, hide_index=True)
            st.caption("Correlation is only a second-moment object. Coskewness and co-kurtosis are materially noisier, so V4.0.2 reports moving-block bootstrap intervals, sign stability and Supported/Inconclusive status rather than point estimates alone.")

        st.markdown("### Event-force dependency shifts")
        if dep.events.empty:
            st.info("No usable dependency_event_table events for this pair. Event windows require enough pre/post observations.")
        else:
            ev = dep.events.copy()
            for c in ["Median Δ corr", "Mean Δ corr", "Mean pre corr", "Mean post corr"]:
                if c in ev:
                    ev[c] = ev[c].map(lambda z: _fmt(z, 3))
            st.dataframe(ev, use_container_width=True, hide_index=True)
            st.caption("Event-window shifts are descriptive. They do not identify the event as the cause unless the upstream research design provides valid identification.")

    with sub[3]:
        st.markdown("### Economic / structural context")
        if dep.economic_context.empty:
            st.info("No dependency_asset_metadata / ownership / relationship inputs for this pair.")
        else:
            st.dataframe(dep.economic_context, use_container_width=True, hide_index=True)

        st.markdown("### Liquidity commonality")
        if dep.liquidity.empty:
            st.info("No dependency_liquidity_series channel injected. Add spread/depth/ADV/borrow/short-interest metrics to separate return dependency from liquidity dependency.")
        else:
            lq = dep.liquidity.copy()
            for c in ["Level commonality", "Change commonality"]:
                if c in lq:
                    lq[c] = lq[c].map(lambda z: _fmt(z, 3))
            st.dataframe(lq, use_container_width=True, hide_index=True)

        st.markdown("### Interpretation framework")
        st.dataframe(pd.DataFrame([
            ["Fundamental/Systematic", "Cash flows, sector, style, country, earnings, supply chain"],
            ["Exogenous", "Monetary policy, macro, rates, FX, fiscal, credit, commodities, geopolitics, regulation, climate"],
            ["Endogenous Market", "Ownership, ETF/index flows, liquidity, leverage, funding, dealer hedging, positioning, forced sales"],
            ["Information/Event", "News, surprises, attention, lead-lag diffusion, daily extremes; intraday jumps only when a realized-jump feed exists"],
            ["Structural/Measurement", "Currency denomination, market hours, asset risk units, P&L space, market cap/index/portfolio weights"],
        ], columns=["Mechanism origin", "Examples"]), use_container_width=True, hide_index=True)

    with sub[4]:
        st.markdown("### Dependency Data Hub audit")
        hs = dep.data_hub_summary or {}
        h1, h2, h3, h4, h5 = st.columns(5)
        h1.metric("Hub mode", str(hs.get("mode", "injected-only")))
        h2.metric("Force series", str(hs.get("auto_force_series", 0)))
        h3.metric("Event rows", str(hs.get("auto_event_rows", 0)))
        h4.metric("Liquidity metrics", str(hs.get("liquidity_metrics", 0)))
        h5.metric("FX currencies", str(hs.get("fx_currencies", 0)))
        if dep.data_hub_audit.empty:
            st.info("No automatic provider item was activated in this run. Injected/project channels remain valid.")
        else:
            st.dataframe(dep.data_hub_audit, use_container_width=True, hide_index=True, height=440)
        st.caption("FRED provider cascade: project/internal macro levels → fresh persistent cache → keyed official FRED API → small public CSV chunks → stale last-valid cache. Audit columns expose provider/fallback/cache age/last observation. Auto state variables remain associational level/change proxies, never relabelled as macro surprises; explicit user/project inputs override auto-enrichment.")

        st.markdown("### Integration contracts")
        st.code("""# Continuous / surprise force series (already shocks by default)
analysis['dependency_force_series'] = factor_df
analysis['dependency_force_metadata'] = {
    'FedSurprise': {
        'force': 'Fed policy surprise',
        'mechanism': 'Exogenous',
        'family': 'Monetary policy',
        'identification': 'Surprise-based association',
        'source': 'Internal macro surprise engine',
        'input_kind': 'shock',
        'transform': 'none',
    },
}

# Event forces
analysis['dependency_event_table'] = pd.DataFrame([
    {'Date':'2026-01-28','Force':'Fed policy surprise','Mechanism':'Exogenous','Label':'FOMC'},
    {'Date':'2026-02-10','Force':'Export controls','Mechanism':'Exogenous','Label':'Semiconductor policy'},
])

# Asset structure / economic importance
analysis['dependency_asset_metadata'] = {
    'NVDA': {'currency':'USD','sector':'Semiconductors','market_cap':..., 'index_weight':...},
    'ASML': {'currency':'EUR','sector':'Semiconductor equipment','market_cap':...},
}
analysis['dependency_base_currency'] = 'USD'
analysis['dependency_fx_to_base'] = {'EUR': eurusd_level_series}  # USD per EUR

# Liquidity commonality
analysis['dependency_liquidity_series'] = {
    'BidAskSpread': spread_df, 'Depth': depth_df, 'BorrowFee': borrow_df,
}

# Cross-asset economic risk space
analysis['dependency_pnl_series'] = pnl_df  # can embed notional, DV01, CS01, Greeks

# Optional structural relationships / ownership
analysis['dependency_ownership_matrix'] = ownership_overlap_df
analysis['dependency_relationship_table'] = relationship_df
""", language="python")
        st.caption("The registry can absorb additional force families without changing the frozen correlation core. Custom factor/event names are allowed; metadata controls their mechanism, family, source and identification label.")

        st.markdown("### Current active-force audit")
        if dep.force_model.status == "ok":
            audit = pd.DataFrame([
                ["Common observations", dep.force_model.obs],
                ["Selected factors", len(dep.force_model.factors_used)],
                ["Dropped/redundant factors", len(dep.force_model.factors_dropped)],
                ["Covariance reconstruction error", dep.force_model.reconstruction_error],
                ["Causal claim", "No — association only by default"],
            ], columns=["Diagnostic", "Value"])
            st.dataframe(audit, use_container_width=True, hide_index=True)
        else:
            st.info("Force model not active on the selected pair.")

        pack = dependency_research_pack_zip(dep)
        st.download_button(
            "Download Dependency Intelligence Research Pack",
            data=pack,
            file_name=f"{primary}_{peer}_dependency_intelligence_v4_0_2.zip",
            mime="application/zip",
            key=f"depv402_export_{primary}_{peer}",
        )
