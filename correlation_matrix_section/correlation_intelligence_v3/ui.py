from __future__ import annotations

import math
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .config import CorrelationConfig
from .data import default_peer_universe
from .dynamics import dcc_pair_series, ewma_corr_series, rolling_corr_series
from .engine import CorrelationEngine
from .export import research_pack_zip
from .tail import bootstrap_tail_uncertainty, fit_copulas
from .utils import fmt_corr, fmt_num, fmt_pct, fmt_pvalue, fmt_score, html_safe, parse_ticker_text, table_height
from ..dependency_intelligence.ui import render_dependency_intelligence_tab


def _inject_css():
    st.markdown("""
    <style>
    .corr-v3-card {border:1px solid rgba(148,163,184,.22);background:rgba(15,23,42,.42);border-radius:13px;padding:13px 14px;min-height:118px}
    .corr-v3-label {font-size:.77rem;font-weight:700;color:rgba(226,232,240,.67);letter-spacing:.02em;margin-bottom:7px}
    .corr-v3-value {font-size:1.48rem;font-weight:800;color:#f8fafc;line-height:1.08;overflow-wrap:anywhere}
    .corr-v3-sub {font-size:.78rem;color:rgba(226,232,240,.58);margin-top:8px;line-height:1.25}
    .corr-v3-strip {border:1px solid rgba(56,189,248,.18);background:rgba(2,132,199,.07);border-radius:10px;padding:10px 12px;color:rgba(226,232,240,.82);font-size:.84rem}
    </style>
    """, unsafe_allow_html=True)


def _card(label: str, value: str, sub: str = ""):
    st.markdown(
        f"<div class='corr-v3-card'><div class='corr-v3-label'>{html_safe(label)}</div>"
        f"<div class='corr-v3-value'>{html_safe(value)}</div>"
        f"<div class='corr-v3-sub'>{html_safe(sub)}</div></div>",
        unsafe_allow_html=True,
    )


def _parse_weights_text(raw: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for token in str(raw or "").replace("\n", ",").replace(";", ",").split(","):
        token = token.strip()
        if not token or ":" not in token:
            continue
        name, value = token.split(":", 1)
        try:
            w = float(value.strip().replace("%", ""))
            if "%" in value:
                w /= 100.0
            if np.isfinite(w):
                out[name.strip().upper()] = w
        except Exception:
            continue
    return out


def _format_weights(weights: dict[str, float]) -> str:
    return ", ".join(f"{k}:{v:.4g}" for k, v in (weights or {}).items())


def _heatmap(corr: pd.DataFrame, title: str, order: list[str] | None = None):
    if corr is None or corr.empty:
        st.info("Matrice indisponible sur cet échantillon.")
        return
    c = corr.copy()
    if order:
        order = [x for x in order if x in c.columns]
        if len(order) == len(c.columns):
            c = c.loc[order, order]
    show_text = len(c) <= 22
    text = np.vectorize(lambda x: f"{x:.2f}")(c.values) if show_text else None
    fig = go.Figure(go.Heatmap(
        z=c.values,
        x=c.columns,
        y=c.index,
        zmin=-1,
        zmax=1,
        colorscale="RdBu",
        reversescale=True,
        text=text,
        texttemplate="%{text}" if show_text else None,
        hovertemplate="%{y} vs %{x}<br>ρ=%{z:.3f}<extra></extra>",
        colorbar=dict(title="ρ"),
    ))
    fig.update_layout(
        height=max(520, min(880, 120 + 34 * len(c))),
        title=title,
        template="plotly_dark",
        margin=dict(l=35, r=30, t=65, b=35),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(10,14,22,.55)",
    )
    st.plotly_chart(fig, use_container_width=True)


def _term_structure_chart(df: pd.DataFrame, primary: str):
    if df is None or df.empty:
        return
    top = df.head(8).copy()
    windows = [("Corr 30D", 30), ("Corr 90D", 90), ("Corr 180D", 180), ("Corr 1Y", 252)]
    fig = go.Figure()
    for _, row in top.iterrows():
        fig.add_trace(go.Scatter(
            x=[w for _, w in windows],
            y=[row.get(c) for c, _ in windows],
            mode="lines+markers",
            name=str(row.get("Ticker")),
        ))
    fig.add_hline(y=0, line_dash="dash")
    fig.update_layout(
        height=470,
        title=f"Correlation term structure — {primary}",
        xaxis_title="Horizon (jours)",
        yaxis_title="Corrélation",
        yaxis=dict(range=[-1.05, 1.05]),
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(10,14,22,.55)",
        hovermode="x unified",
    )
    st.plotly_chart(fig, use_container_width=True)


def _rmt_chart(eig: pd.DataFrame, title: str = "Eigen spectrum vs Marchenko-Pastur"):
    if eig is None or eig.empty:
        return
    fig = go.Figure(go.Bar(
        x=eig["Rank"],
        y=eig["Eigenvalue"],
        text=eig["Eigenvalue"].map(lambda x: f"{x:.2f}"),
        textposition="auto",
    ))
    fig.add_hline(y=float(eig["MP max"].iloc[0]), line_dash="dash", annotation_text="MP max")
    fig.add_hline(y=float(eig["MP min"].iloc[0]), line_dash="dot", annotation_text="MP min")
    fig.update_layout(
        height=470,
        title=title,
        xaxis_title="Rang",
        yaxis_title="Eigenvalue",
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(10,14,22,.55)",
    )
    st.plotly_chart(fig, use_container_width=True)


def _fmt_ranking(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    for c in [
        "Corr", "Spearman", "Kendall", "Corr 30D", "Corr 90D", "Corr 180D", "Corr 1Y",
        "ΔCorr 30D-1Y", "Downside corr", "Worst 20% corr", "Upside corr", "Stress lift",
        "CI low", "CI high",
    ]:
        if c in out:
            out[c] = out[c].map(fmt_corr)
    for c in ["Beta ticker vs peer", "R²"]:
        if c in out:
            out[c] = out[c].map(fmt_num)
    return out


def _spring_positions(mst: pd.DataFrame, seed: int = 42) -> dict[str, tuple[float, float]]:
    if mst is None or mst.empty:
        return {}
    nodes = sorted(set(mst["From"]).union(set(mst["To"])))
    n = len(nodes)
    idx = {node: i for i, node in enumerate(nodes)}
    rng = np.random.default_rng(seed)
    angles = np.linspace(0, 2 * np.pi, n, endpoint=False)
    pos = np.column_stack([np.cos(angles), np.sin(angles)]) + rng.normal(0, 0.03, size=(n, 2))
    k = math.sqrt(1.0 / max(n, 1))
    edges = [(idx[a], idx[b], float(d)) for a, b, d in zip(mst["From"], mst["To"], mst["Distance"])]

    for step in range(180):
        disp = np.zeros_like(pos)
        for i in range(n):
            delta = pos[i] - pos
            dist = np.sqrt((delta * delta).sum(axis=1)) + 1e-6
            force = (k * k / dist)[:, None] * (delta / dist[:, None])
            force[i] = 0
            disp[i] += force.sum(axis=0)
        for i, j, d in edges:
            delta = pos[i] - pos[j]
            dist = float(np.linalg.norm(delta)) + 1e-6
            desired = max(0.25, min(1.6, d))
            attraction = (dist - desired) * 0.18
            vec = delta / dist
            disp[i] -= attraction * vec
            disp[j] += attraction * vec
        temp = max(0.015, 0.12 * (1 - step / 180))
        norm = np.linalg.norm(disp, axis=1) + 1e-9
        pos += disp / norm[:, None] * np.minimum(norm, temp)[:, None]
        pos -= pos.mean(axis=0)
    scale = np.max(np.abs(pos)) or 1.0
    pos /= scale
    return {node: (float(pos[idx[node], 0]), float(pos[idx[node], 1])) for node in nodes}


def _mst_graph(mst: pd.DataFrame, primary: str, type_map: dict[str, str]):
    if mst is None or mst.empty:
        st.info("MST indisponible.")
        return
    pos = _spring_positions(mst)
    degree = {n: 0 for n in pos}
    fig = go.Figure()
    for _, row in mst.iterrows():
        a, b = str(row["From"]), str(row["To"])
        if a not in pos or b not in pos:
            continue
        degree[a] += 1
        degree[b] += 1
        corr = float(row.get("Corr", 0.0) or 0.0)
        fig.add_trace(go.Scatter(
            x=[pos[a][0], pos[b][0]],
            y=[pos[a][1], pos[b][1]],
            mode="lines",
            line=dict(width=max(1.0, 1.0 + 4.0 * abs(corr))),
            hoverinfo="skip",
            showlegend=False,
        ))

    nodes = list(pos)
    hover = [f"{n}<br>{type_map.get(n, 'Unknown')}<br>degree={degree.get(n,0)}" for n in nodes]
    sizes = [24 if n == primary else 14 + 3 * degree.get(n, 0) for n in nodes]
    symbols = ["diamond" if n == primary else "circle" for n in nodes]
    fig.add_trace(go.Scatter(
        x=[pos[n][0] for n in nodes],
        y=[pos[n][1] for n in nodes],
        mode="markers+text",
        text=nodes,
        textposition="top center",
        marker=dict(size=sizes, symbol=symbols, line=dict(width=1)),
        hovertext=hover,
        hovertemplate="%{hovertext}<extra></extra>",
        showlegend=False,
    ))
    fig.update_layout(
        height=590,
        title="Minimum Spanning Tree — dependency network",
        template="plotly_dark",
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(10,14,22,.40)",
        margin=dict(l=20, r=20, t=65, b=20),
    )
    st.plotly_chart(fig, use_container_width=True)



def _partial_graph(edges: pd.DataFrame, centrality: pd.DataFrame, primary: str, type_map: dict[str, str]):
    if edges is None or edges.empty:
        st.info("Partial-correlation network indisponible ou trop sparse.")
        return
    layout_edges = edges.copy()
    layout_edges["Distance"] = np.sqrt(np.clip(2 * (1 - layout_edges["Abs weight"]), 0.05, None))
    pos = _spring_positions(layout_edges[["From", "To", "Distance"]])
    strength_map = {}
    if isinstance(centrality, pd.DataFrame) and not centrality.empty:
        strength_map = dict(zip(centrality["Asset"], pd.to_numeric(centrality["Strength"], errors="coerce").fillna(0)))
    fig = go.Figure()
    for _, row in edges.iterrows():
        a, b = str(row["From"]), str(row["To"])
        if a not in pos or b not in pos:
            continue
        w = float(row.get("Partial corr", 0.0) or 0.0)
        fig.add_trace(go.Scatter(
            x=[pos[a][0], pos[b][0]], y=[pos[a][1], pos[b][1]], mode="lines",
            line=dict(width=max(1.0, 1.0 + 7.0 * abs(w)), dash="solid" if w >= 0 else "dot"),
            hovertext=f"{a} ↔ {b}<br>partial ρ={w:.3f}", hoverinfo="text", showlegend=False,
        ))
    nodes = list(pos)
    sizes = [28 if n == primary else 13 + 9 * min(1.5, float(strength_map.get(n, 0))) for n in nodes]
    fig.add_trace(go.Scatter(
        x=[pos[n][0] for n in nodes], y=[pos[n][1] for n in nodes], mode="markers+text",
        text=nodes, textposition="top center",
        marker=dict(size=sizes, symbol=["diamond" if n == primary else "circle" for n in nodes], line=dict(width=1)),
        hovertext=[f"{n}<br>{type_map.get(n,'Unknown')}<br>strength={strength_map.get(n,0):.2f}" for n in nodes],
        hovertemplate="%{hovertext}<extra></extra>", showlegend=False,
    ))
    fig.update_layout(
        height=580, title="Partial-correlation network — conditional dependency",
        template="plotly_dark", xaxis=dict(visible=False), yaxis=dict(visible=False),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(10,14,22,.40)", margin=dict(l=20,r=20,t=65,b=20),
    )
    st.plotly_chart(fig, use_container_width=True)


def _connectedness_graph(matrix: pd.DataFrame, table: pd.DataFrame, primary: str, max_edges: int = 22):
    if matrix is None or matrix.empty:
        st.info("Directional connectedness indisponible.")
        return
    nodes = list(matrix.columns)
    n = len(nodes)
    angles = np.linspace(0, 2*np.pi, n, endpoint=False)
    pos = {node: (float(np.cos(a)), float(np.sin(a))) for node, a in zip(nodes, angles)}
    net_map = {}
    if isinstance(table, pd.DataFrame) and not table.empty:
        net_map = dict(zip(table["Asset"], pd.to_numeric(table["NET transmitter"], errors="coerce").fillna(0)))
    edges = []
    # matrix row=receiver, col=transmitter => edge transmitter -> receiver
    for receiver in nodes:
        for transmitter in nodes:
            if receiver == transmitter:
                continue
            w = float(matrix.loc[receiver, transmitter])
            edges.append((transmitter, receiver, w))
    edges = sorted(edges, key=lambda x: x[2], reverse=True)[:max_edges]
    fig = go.Figure()
    for a, b, w in edges:
        x0,y0 = pos[a]; x1,y1 = pos[b]
        fig.add_trace(go.Scatter(
            x=[x0,x1], y=[y0,y1], mode="lines", line=dict(width=max(1.0, 0.7 + w/7.0)),
            hovertext=f"{a} → {b}<br>FEVD share={w:.2f}%", hoverinfo="text", showlegend=False,
        ))
        # Small arrowhead at the receiving end.
        fig.add_annotation(x=x1, y=y1, ax=x0, ay=y0, xref="x", yref="y", axref="x", ayref="y",
                           showarrow=True, arrowhead=2, arrowsize=.65, arrowwidth=max(1.0, 0.5+w/12.0), opacity=.45, text="")
    node_sizes = [28 if x == primary else 16 + min(16, abs(float(net_map.get(x,0)))/2) for x in nodes]
    fig.add_trace(go.Scatter(
        x=[pos[n][0] for n in nodes], y=[pos[n][1] for n in nodes], mode="markers+text", text=nodes,
        textposition="top center", marker=dict(size=node_sizes, symbol=["diamond" if n==primary else "circle" for n in nodes], line=dict(width=1)),
        hovertext=[f"{n}<br>NET={net_map.get(n,0):.2f} pp" for n in nodes], hovertemplate="%{hovertext}<extra></extra>", showlegend=False,
    ))
    fig.update_layout(
        height=590, title="Directional connectedness — generalized FEVD network",
        template="plotly_dark", xaxis=dict(visible=False, range=[-1.35,1.35]), yaxis=dict(visible=False, range=[-1.35,1.35]),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(10,14,22,.40)", margin=dict(l=20,r=20,t=65,b=20),
    )
    st.plotly_chart(fig, use_container_width=True)


def _forward_corr_chart(history: pd.DataFrame):
    if history is None or history.empty:
        return
    fig = go.Figure(go.Scatter(x=history.index, y=history.iloc[:,0], mode="lines", name="Implied correlation"))
    fig.update_layout(height=390, title="Implied correlation history", yaxis=dict(range=[-0.05,1.05]), template="plotly_dark",
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(10,14,22,.55)")
    st.plotly_chart(fig, use_container_width=True)



def _break_p_label(meta: dict) -> str:
    if not isinstance(meta, dict):
        return "N/A"
    p = meta.get("bootstrap_pvalue")
    resolution = meta.get("pvalue_resolution")
    if meta.get("pvalue_at_floor") and resolution is not None:
        try:
            return f"≤{float(resolution):.4f}"
        except Exception:
            pass
    return fmt_pvalue(p)


def _break_chart(curve: pd.DataFrame, meta: dict):
    if curve is None or curve.empty:
        return
    fig=go.Figure(go.Scatter(x=curve["Date"],y=curve["Matrix shift"],mode="lines",name="Matrix shift"))
    bd=meta.get("break_date")
    if bd is not None:
        fig.add_vline(x=pd.Timestamp(bd).timestamp()*1000,line_dash="dash",annotation_text="max break")
    fig.update_layout(height=390,title="Dependency matrix structural-shift monitor",template="plotly_dark",paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(10,14,22,.55)",yaxis_title="RMS correlation shift")
    st.plotly_chart(fig,use_container_width=True)


def _frequency_chart(df: pd.DataFrame):
    if df is None or df.empty:
        return
    col = "Absolute TCI contribution"
    fig = go.Figure(go.Bar(
        x=df["Band"], y=df[col],
        text=df[col].map(lambda x: f"{float(x):.2f} pp"), textposition="auto",
    ))
    fig.update_layout(
        height=360, title="Absolute spectral connectedness contribution by frequency band",
        template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(10,14,22,.55)", yaxis_title="Contribution to spectral TCI (percentage points)",
    )
    st.plotly_chart(fig, use_container_width=True)


def _tail_surface_heatmap(df: pd.DataFrame):
    if df is None or df.empty:
        return
    p=df.pivot_table(index="Ticker",columns="Quantile",values="Excess vs independence",aggfunc="first")
    if p.empty: return
    fig=go.Figure(go.Heatmap(z=p.values,x=p.columns,y=p.index,zmid=0,colorscale="RdBu",reversescale=True,colorbar=dict(title="Excess"),hovertemplate="%{y} · %{x}<br>excess=%{z:.3f}<extra></extra>"))
    fig.update_layout(height=max(390,45*len(p)+130),title="Tail dependence surface — excess co-exceedance vs independence",template="plotly_dark",paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(10,14,22,.55)")
    st.plotly_chart(fig,use_container_width=True)


def _forward_term_chart(meta: dict):
    term=meta.get("term_structure") if isinstance(meta,dict) else None
    if not isinstance(term,dict) or not term: return
    xs=sorted(int(x) for x in term)
    fig=go.Figure(go.Scatter(x=xs,y=[term[x] for x in xs],mode="lines+markers",name="Implied"))
    realized=meta.get("realized_term_structure",{})
    if isinstance(realized,dict) and realized:
        fig.add_trace(go.Scatter(x=[x for x in xs if x in realized],y=[realized[x] for x in xs if x in realized],mode="lines+markers",name="Realized"))
    fig.update_layout(height=380,title="Implied correlation term structure",xaxis_title="Horizon (days)",yaxis_title="Correlation",yaxis=dict(range=[-0.05,1.05]),template="plotly_dark",paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(10,14,22,.55)")
    st.plotly_chart(fig,use_container_width=True)


@st.cache_data(ttl=180, max_entries=8, show_spinner=False)
def _cached_engine_analysis(ticker: str, tickers: tuple[str, ...], price_data: pd.DataFrame, selected_days: int, period: str, analysis_local: dict):
    return CorrelationEngine(CorrelationConfig()).analyse(ticker, list(tickers), price_data, selected_days, period, analysis_local)

def _contains_callable(d: dict) -> bool:
    for v in (d or {}).values():
        if callable(v):
            return True
        if isinstance(v, dict) and any(callable(x) for x in v.values()):
            return True
    return False

def render_correlation_intelligence_v3(ticker: str, price_data: pd.DataFrame, analysis: dict | None = None):
    ticker = str(ticker or "").upper().strip()
    analysis = analysis or {}
    cfg = CorrelationConfig()
    _inject_css()
    st.subheader(f"Correlation Intelligence V4.0.2 — {ticker}")

    with st.expander("Universe & methodology", expanded=False):
        default_text = ", ".join(default_peer_universe(ticker))
        universe_text = st.text_area("Assets / proxies", value=default_text, height=90, key=f"corrv31_universe_{ticker}")
        c1, c2, c3 = st.columns(3)
        with c1:
            period = st.selectbox("Historique téléchargé", cfg.data_period_options, index=cfg.data_period_options.index(cfg.default_data_period), key=f"corrv31_period_{ticker}")
        with c2:
            selected_days = st.selectbox("Fenêtre centrale", [30, 60, 90, 180, 252], index=2, format_func=lambda x: "1Y" if x == 252 else f"{x}D", key=f"corrv31_days_{ticker}")
        with c3:
            estimator = st.selectbox("Estimateur matrice", cfg.estimator_options, index=cfg.estimator_options.index(cfg.default_estimator), key=f"corrv31_estimator_{ticker}")
        d1, d2 = st.columns([1, 2])
        with d1:
            tail_mode = st.selectbox("Tail horizon", cfg.tail_mode_options, index=cfg.tail_mode_options.index(cfg.tail_mode_default), key=f"corrv31_tailmode_{ticker}", help="Adaptive vise environ 30 observations de lower tail et découple le tail du 90D central.")
        with d2:
            existing_weights = analysis.get("portfolio_weights") if isinstance(analysis.get("portfolio_weights"), dict) else {}
            weights_text = st.text_input("Portfolio weights (optional)", value=_format_weights(existing_weights), key=f"corrv31_weights_{ticker}", placeholder="NVDA:0.30, QQQ:0.30, TLT:0.20, GLD:0.20")
            if not str(weights_text).strip():
                st.caption("Le texte grisé est uniquement un exemple : aucun portefeuille n’est actif tant que des poids ne sont pas réellement saisis ou injectés.")
        st.caption("V3.1.1 FINAL: fréquence BK normalisée/réconciliée, break sup-bootstrap post-sélection, incertitude champion OOS et réseau bootstrap haute précision. Aucun forward-fill cross-market.")

    tickers = parse_ticker_text(universe_text, ticker)
    analysis_local = dict(analysis)
    analysis_local["correlation_tail_mode"] = tail_mode
    parsed_weights = _parse_weights_text(weights_text)
    if parsed_weights:
        analysis_local["portfolio_weights"] = parsed_weights
    engine = CorrelationEngine(cfg)
    with st.spinner("Estimation V4.0.2: covariance OOS, sup-break, connectedness spectral et portfolio risk…"):
        if _contains_callable(analysis_local):
            bundle = engine.analyse(ticker, tickers, price_data, int(selected_days), period, analysis_local)
        else:
            bundle = _cached_engine_analysis(ticker, tuple(tickers), price_data, int(selected_days), period, analysis_local)
    s = bundle.summary
    if s.get("status") != "ok":
        st.error(s.get("message", "Correlation engine indisponible."))
        if not bundle.quality.empty:
            st.dataframe(bundle.quality, use_container_width=True, hide_index=True)
        return

    cards = st.columns(6)
    with cards[0]:
        _card("Dependency regime", s["dependency_label"], fmt_score(s["dependency_score"]))
    with cards[1]:
        _card("Correlation change", fmt_corr(s.get("corr_change")), "mean |Δρ 30D−1Y| top links")
    with cards[2]:
        _card("Dominant driver", str(s.get("dominant_factor")), f"std β {fmt_num(s.get('factor_standardized_beta'))} · inc R² {fmt_pct(s.get('factor_incremental_r2'))}")
    with cards[3]:
        _card("Historical hedge candidate", str(s.get("best_hedge")), f"{s.get('hedge_stability')} · OOS {fmt_pct(s.get('hedge_oos_reduction'))}")
    with cards[4]:
        _card("Tail evidence", str(s.get("tail_evidence")), f"{s.get('tail_peer')} · q10 {fmt_pct(s.get('tail_lower'))} · Ntail {s.get('tail_obs',0)} · {s.get('tail_horizon',0)}D")
    with cards[5]:
        _card("Stat confidence", str(s.get("confidence_label")), f"{fmt_score(s.get('confidence_score'))} · {s.get('n_obs', 0)} obs")

    conn_txt = f" · TCI {fmt_num(s.get('connectedness_tci'))}%" if s.get("connectedness_tci") is not None else ""
    fwd_txt = f" · Implied corr {fmt_pct(s.get('forward_implied_corr'))}" if s.get("forward_implied_corr") is not None else ""
    cov_txt = ""
    if s.get("covariance_champion"):
        cov_status = str(s.get("covariance_champion_status") or "")
        runner = s.get("covariance_runner_up")
        if cov_status == "Statistically tied" and runner:
            cov_txt = f" · Cov selection {html_safe(s.get('covariance_champion'))}≈{html_safe(runner)} (tied)"
        else:
            cov_txt = f" · Cov selection {html_safe(s.get('covariance_champion'))} ({html_safe(cov_status or 'selected')})"
    br_txt = ""
    if s.get("break_date") is not None:
        br_txt = f" · Break {pd.Timestamp(s.get('break_date')).date()} p={_break_p_label(bundle.break_meta)}"
    st.markdown(
        f"<div class='corr-v3-strip'>Source: <b>{html_safe(s.get('data_source'))}</b> · {s.get('n_assets')} séries · "
        f"Fenêtre {selected_days}D · Tail {s.get('tail_mode')} {s.get('tail_horizon') or 'N/A'}D · Peer-RMT {s.get('rmt_peer_assets')} actifs · PC1 {fmt_pct(s.get('pc1_variance'))} · "
        f"effective rank {fmt_num(s.get('effective_rank'))}{conn_txt}{cov_txt}{br_txt}{fwd_txt}</div>",
        unsafe_allow_html=True,
    )

    tabs = st.tabs([
        "Executive", "Matrix & Clusters", "Dynamics & Breaks", "Factor Intelligence",
        "Tail & Stress", "Network / RMT", "Portfolio & Forward", "Model Validation", "Dependency Drivers", "Diagnostics / Export",
    ])

    with tabs[0]:
        st.subheader("Decision-oriented executive view")
        exec_rows = [
            ["Most linked peer", s.get("peer"), fmt_corr(s.get("peer_corr")), "Pair dependency on selected horizon"],
            ["Dependency risk", s.get("dependency_label"), fmt_score(s.get("dependency_score")), "Composite concentration/change/tail evidence; not a trading signal"],
            ["Dominant driver", s.get("dominant_factor"), f"std β {fmt_num(s.get('factor_standardized_beta'))}", "Multivariate HAC factor model with VIF / standardized condition diagnostics"],
            ["Historical hedge candidate", s.get("best_hedge"), f"{fmt_pct(s.get('hedge_vol_reduction'))} · {s.get('hedge_stability')}", "Systematic instruments prioritized; robustness includes multi-window and OOS checks"],
            ["Tail evidence", s.get("tail_evidence"), f"{s.get('tail_peer')} · {fmt_pct(s.get('tail_lower'))} · {s.get('tail_horizon')}D", "Adaptive tail horizon targets a usable number of tail observations"],
        ]
        if s.get("covariance_champion"):
            cstate = s.get("covariance_champion")
            if s.get("covariance_champion_status") == "Statistically tied" and s.get("covariance_runner_up"):
                cstate = f"{cstate} ≈ {s.get('covariance_runner_up')}"
            cmetric = f"{bundle.covariance_meta.get('forecast_horizon','N/A')}D · {s.get('covariance_champion_status') or 'selected'}"
            exec_rows.append(["Covariance forecast selection", cstate, cmetric, "Walk-forward OOS selection plus paired-bootstrap uncertainty versus runner-up"])
        if s.get("break_date") is not None:
            exec_rows.append(["Dependency break", str(pd.Timestamp(s.get("break_date")).date()), f"p={_break_p_label(bundle.break_meta)}", "Max-stat dependency shift with post-selection supremum moving-block bootstrap"])
        if s.get("connectedness_tci") is not None:
            exec_rows.append(["Directional connectedness", s.get("net_transmitter"), f"TCI {fmt_num(s.get('connectedness_tci'))}% · NET {fmt_num(s.get('net_transmitter_value'))}", "Generalized FEVD: positive NET identifies a shock transmitter in the selected VAR universe"])
        if s.get("forward_implied_corr") is not None:
            exec_rows.append(["Forward correlation", "Implied vs realized", f"{fmt_pct(s.get('forward_implied_corr'))} vs {fmt_pct(s.get('forward_realized_corr'))}", "Injected option-implied correlation; premium is forward minus realized"])
        exec_df = pd.DataFrame(exec_rows, columns=["Block", "Asset / state", "Metric", "Interpretation"])
        st.dataframe(exec_df, use_container_width=True, hide_index=True)
        _term_structure_chart(bundle.term_structure, ticker)

    with tabs[1]:
        c1, _ = st.columns([1, 2])
        with c1:
            matrix_mode = st.radio("Matrix", ["Selected estimator", "Champion forecast", "Raw Pearson", "Ledoit-Wolf", "Partial", "RMT-cleaned full"], index=0, key=f"corrv31_matrixmode_{ticker}")
            reorder = st.checkbox("Hierarchical ordering", value=True, key=f"corrv31_clusterorder_{ticker}")
        matrix = {
            "Raw Pearson": bundle.corr_raw,
            "Ledoit-Wolf": bundle.corr_shrunk,
            "Partial": bundle.corr_partial,
            "RMT-cleaned full": bundle.corr_rmt_cleaned_full,
            "Champion forecast": bundle.corr_forecast,
        }.get(matrix_mode)
        if matrix_mode == "Selected estimator":
            from .estimators import correlation_matrix
            matrix = correlation_matrix(bundle.changes, int(selected_days), estimator, cfg.min_matrix_obs if estimator in {"Ledoit-Wolf", "OAS", "Partial"} else cfg.min_pair_obs)
        order = bundle.cluster_order if reorder else None
        _heatmap(matrix, f"{matrix_mode} — {selected_days}D", order)
        if not bundle.term_structure.empty:
            st.subheader("Correlation change monitor")
            show = bundle.term_structure.copy().head(15)
            for c in ["Corr 30D", "Corr 90D", "Corr 180D", "Corr 1Y", "ΔCorr 30D-1Y"]:
                if c in show:
                    show[c] = show[c].map(fmt_corr)
            st.dataframe(show, use_container_width=True, hide_index=True, height=table_height(show, max_height=600))

    with tabs[2]:
        st.subheader("Dynamic correlation")
        available = [x for x in bundle.changes.columns if x != ticker]
        defaults = bundle.ranking["Ticker"].head(4).tolist() if not bundle.ranking.empty else available[:4]
        peers = st.multiselect("Pairs", available, default=[x for x in defaults if x in available], key=f"corrv31_dynpeers_{ticker}")
        method = st.radio("Dynamic estimator", ["Rolling", "EWMA", "DCC(1,1)"], horizontal=True, key=f"corrv31_dynmethod_{ticker}")
        fig = go.Figure()
        metas = []
        for peer in peers[:6]:
            if method == "Rolling":
                series = rolling_corr_series(bundle.changes, ticker, peer, 60)
            elif method == "EWMA":
                series = ewma_corr_series(bundle.changes, ticker, peer, cfg.ewma_lambda)
            else:
                series, meta = dcc_pair_series(bundle.changes, ticker, peer, cfg.dcc_maxiter)
                metas.append({"Pair": f"{ticker}/{peer}", **meta})
            if not series.empty:
                fig.add_trace(go.Scatter(x=series.index, y=series.values, mode="lines", name=peer))
        if fig.data:
            fig.add_hline(y=0, line_dash="dash")
            fig.add_hline(y=.7, line_dash="dot", annotation_text="high corr")
            fig.update_layout(height=520, title=f"{method} conditional dependence", yaxis=dict(range=[-1.05, 1.05]), template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(10,14,22,.55)", hovermode="x unified")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Pas assez d'observations pour l'estimateur sélectionné.")
        if metas:
            st.dataframe(pd.DataFrame(metas), use_container_width=True, hide_index=True)

        st.subheader("Conditional correlation by regime")
        if bundle.regime_table.empty:
            st.info("Regime table indisponible.")
        else:
            default_cols = [
                "Ticker", "Full",
                "Risk-On", "N Risk-On", "Risk-On quality",
                "Risk-Off", "N Risk-Off", "Risk-Off quality",
                "High Vol", "N High Vol", "High Vol quality",
                "Low Vol", "N Low Vol", "Low Vol quality",
                "Stress Δ", "Stress quality",
            ]
            x = bundle.regime_table[[c for c in default_cols if c in bundle.regime_table.columns]].copy().head(20)
            for c in ["Full", "Risk-On", "Risk-Off", "High Vol", "Low Vol", "Stress Δ"]:
                if c in x:
                    x[c] = x[c].map(fmt_corr)
            st.dataframe(x, use_container_width=True, hide_index=True, height=table_height(x, max_height=650))
            with st.expander("Regime confidence intervals", expanded=False):
                ci_cols = ["Ticker"] + [c for c in bundle.regime_table.columns if "CI low" in c or "CI high" in c]
                ci = bundle.regime_table[[c for c in ci_cols if c in bundle.regime_table.columns]].copy().head(20)
                for c in ci.columns:
                    if c != "Ticker":
                        ci[c] = ci[c].map(fmt_corr)
                st.dataframe(ci, use_container_width=True, hide_index=True)

        st.subheader("Dependency break detector")
        bm=bundle.break_meta
        if bm.get("status") != "ok":
            st.info(f"Break detector indisponible: {bm.get('status','N/A')}")
        else:
            b1,b2,b3,b4=st.columns(4)
            b1.metric("Last strongest break", str(pd.Timestamp(bm.get("break_date")).date()))
            b2.metric("Matrix shift", fmt_num(bm.get("matrix_shift")))
            b3.metric("Sup-bootstrap p-value", _break_p_label(bm))
            b4.metric("Significant 5%", str(bm.get("significant_5pct")))
            _break_chart(bundle.break_curve,bm)
            if not bundle.break_links.empty:
                bx=bundle.break_links.head(12).copy()
                for c in ["Pre corr","Post corr","Δ corr"]:
                    if c in bx: bx[c]=bx[c].map(fmt_corr)
                st.dataframe(bx,use_container_width=True,hide_index=True)
            st.caption(f"Diagnostic de rupture, pas test causal. Le p-value est post-sélection: chaque moving-block bootstrap refait toute la recherche du maximum ({bm.get('null_samples',0)} réplications; méthode {bm.get('selection_adjustment','max-stat')}).")

    with tabs[3]:
        st.subheader("Multivariate factor attribution")
        meta = bundle.factor_meta
        if bundle.factor_table.empty:
            st.info("Facteur multivarié indisponible. Ajoute des proxies facteurs ou augmente l'historique.")
        else:
            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("Model R²", fmt_pct(meta.get("R²")))
            m2.metric("Adj R²", fmt_pct(meta.get("Adj R²")))
            m3.metric("Obs", str(meta.get("obs", "N/A")))
            m4.metric("Std Condition #", fmt_num(meta.get("Condition number standardized")))
            m5.metric("Max VIF", fmt_num(meta.get("Max VIF")))

            state = meta.get("Multicollinearity", "N/A")
            msg = meta.get("Multicollinearity message", "")
            if state == "Severe":
                st.warning(msg)
            elif state == "Elevated":
                st.info(msg)
            else:
                st.success(msg)

            x = bundle.factor_table.copy()
            for c in ["Raw Beta", "Standardized Beta", "HAC t-stat", "VIF"]:
                if c in x:
                    x[c] = x[c].map(fmt_num)
            if "p-value" in x:
                x["p-value"] = x["p-value"].map(fmt_pvalue)
            if "Incremental R²" in x:
                x["Incremental R²"] = x["Incremental R²"].map(fmt_pct)
            st.dataframe(x, use_container_width=True, hide_index=True)
            st.caption("Standardized beta compare les facteurs sur une échelle commune; Incremental R² mesure leur apport marginal. VIF et condition number diagnostiquent la multicolinéarité.")
            with st.expander("Factor model audit", expanded=False):
                audit = pd.DataFrame([
                    ["Raw condition #", fmt_num(meta.get("Condition number raw"))],
                    ["Standardized condition #", fmt_num(meta.get("Condition number standardized"))],
                    ["Max VIF", fmt_num(meta.get("Max VIF"))],
                    ["Factors used", ", ".join(meta.get("factors_used", []))],
                    ["Dropped pair-collinear factors", ", ".join(meta.get("factors_dropped", [])) or "None"],
                ], columns=["Diagnostic", "Value"])
                st.dataframe(audit, use_container_width=True, hide_index=True)

        st.subheader("Peer dependency ranking")
        default_cols = ["Ticker", "Type", "Corr", "ΔCorr 30D-1Y", "Beta ticker vs peer", "Worst 20% corr", "Stress lift", "CI low", "CI high", "Stability", "Obs"]
        x = _fmt_ranking(bundle.ranking[[c for c in default_cols if c in bundle.ranking.columns]])
        st.dataframe(x, use_container_width=True, hide_index=True, height=table_height(x, max_height=650))

    with tabs[4]:
        st.subheader("Adaptive tail dependence with uncertainty")
        if bundle.tail_table.empty:
            st.info("Tail diagnostics indisponibles.")
        else:
            cols = [
                "Ticker", "Type", "Tail evidence", "Tail evidence score", "Tail quality",
                "Tail horizon days", "Lower tail obs", "Lower co-tail obs",
                "Emp lower co-exceedance", "Lower CI low", "Lower CI high", "Lower tail corr", "Stress lift",
                "Emp upper co-exceedance", "Upper CI low", "Upper CI high",
            ]
            x = bundle.tail_table[[c for c in cols if c in bundle.tail_table.columns]].head(15).copy()
            for c in ["Emp lower co-exceedance", "Lower CI low", "Lower CI high", "Emp upper co-exceedance", "Upper CI low", "Upper CI high"]:
                if c in x:
                    x[c] = x[c].map(fmt_pct)
            for c in ["Lower tail corr", "Stress lift"]:
                if c in x:
                    x[c] = x[c].map(fmt_corr)
            if "Tail evidence score" in x:
                x["Tail evidence score"] = x["Tail evidence score"].map(fmt_score)
            st.dataframe(x, use_container_width=True, hide_index=True, height=table_height(x, max_height=650))
            st.caption(f"Tail mode: {bundle.tail_mode}. Adaptive vise ~{cfg.tail_target_obs} observations q={cfg.tail_quantile:.0%} quand l'historique le permet. Le co-exceedance reste descriptif, pas un λL asymptotique.")

            available_tail = [z for z in bundle.tail_table.get("Ticker", pd.Series(dtype=str)).dropna().tolist() if z in bundle.changes.columns]
            if available_tail:
                peer = st.selectbox("Tail / copula pair", available_tail, index=0, key=f"corrv31_copula_{ticker}")
                peer_row = bundle.tail_table[bundle.tail_table["Ticker"] == peer].iloc[0]
                tail_days = int(peer_row.get("Tail horizon days") or selected_days)
                t1, t2, t3, t4 = st.columns(4)
                t1.metric("Tail horizon", f"{tail_days}D")
                t2.metric("Lower-tail N", str(int(peer_row.get("Lower tail obs") or 0)))
                t3.metric("Co-exceedance", fmt_pct(peer_row.get("Emp lower co-exceedance")))
                t4.metric("Evidence", str(peer_row.get("Tail evidence", "N/A")))

                cop = fit_copulas(ticker, peer, bundle.changes, tail_days)
                if cop.empty:
                    st.info("Historique insuffisant pour comparer les copules sur l'horizon tail retenu.")
                else:
                    y = cop.copy()
                    for c in ["Param 1", "Param 2", "LogLik", "AIC", "ΔAIC"]:
                        if c in y:
                            y[c] = y[c].map(fmt_num)
                    for c in ["λL", "λU"]:
                        if c in y:
                            y[c] = y[c].map(fmt_pct)
                    st.dataframe(y, use_container_width=True, hide_index=True)
                    st.caption("Pseudo-vraisemblance sur pseudo-observations; AIC compare Gaussian, Student-t, Clayton et Gumbel. Diagnostic de structure, pas certitude de modèle.")

                with st.expander("Moving-block bootstrap tail uncertainty", expanded=False):
                    boot = bootstrap_tail_uncertainty(
                        ticker, peer, bundle.changes, tail_days, q=cfg.tail_quantile,
                        samples=cfg.tail_bootstrap_samples, block=cfg.tail_bootstrap_block, seed=cfg.random_seed,
                    )
                    if boot.get("status") != "ok":
                        st.info(f"Bootstrap indisponible: {boot.get('obs',0)} observations communes.")
                    else:
                        boot_df = pd.DataFrame([
                            ["Lower co-exceedance", boot.get("coex_median"), boot.get("coex_ci_low"), boot.get("coex_ci_high"), boot.get("coex_samples")],
                            ["Lower-tail corr", boot.get("lower_corr_median"), boot.get("lower_corr_ci_low"), boot.get("lower_corr_ci_high"), boot.get("lower_corr_samples")],
                            ["Stress lift", boot.get("stress_lift_median"), boot.get("stress_lift_ci_low"), boot.get("stress_lift_ci_high"), boot.get("stress_lift_samples")],
                        ], columns=["Metric", "Bootstrap median", "95% low", "95% high", "Samples"])
                        for c in ["Bootstrap median", "95% low", "95% high"]:
                            boot_df[c] = boot_df[c].map(fmt_corr)
                        st.dataframe(boot_df, use_container_width=True, hide_index=True)
                        st.caption("Moving-block bootstrap conserve partiellement la dépendance temporelle; ces intervalles complètent, sans remplacer, les diagnostics paramétriques/copula.")

        st.subheader("Tail dependence surface")
        if bundle.tail_surface.empty:
            st.info("Tail surface indisponible sur l'historique courant.")
        else:
            _tail_surface_heatmap(bundle.tail_surface)
            with st.expander("Tail surface data",expanded=False):
                ts=bundle.tail_surface.copy()
                for c in ["Co-exceedance","Independence baseline","Excess vs independence","CI low","CI high"]:
                    if c in ts: ts[c]=ts[c].map(fmt_pct)
                if "Conditional corr" in ts: ts["Conditional corr"]=ts["Conditional corr"].map(fmt_corr)
                st.dataframe(ts,use_container_width=True,hide_index=True)
            st.caption("La surface compare lower/upper co-exceedance à plusieurs quantiles et soustrait le niveau attendu sous indépendance; elle évite de dépendre d'un q10 unique.")

        st.subheader("Factor stress linkage")
        if not bundle.stress_table.empty:
            y = bundle.stress_table.copy()
            y["Shock"] = y["Shock"].map(fmt_pct)
            y["Mechanical impact"] = y["Mechanical impact"].map(fmt_pct)
            y["Beta"] = y["Beta"].map(fmt_num)
            y["Corr"] = y["Corr"].map(fmt_corr)
            st.dataframe(y, use_container_width=True, hide_index=True)
            st.caption("Stress linkage reste un diagnostic mécanique pairwise. Les betas conditionnels multivariés sont analysés séparément dans Factor Intelligence.")

    with tabs[5]:
        st.subheader("Random Matrix Theory / Eigen Risk")
        rmt_mode = st.radio("RMT universe", ["Homogeneous peers", "Full dependency universe"], horizontal=True, key=f"corrv31_rmtmode_{ticker}")
        if rmt_mode == "Homogeneous peers":
            rs, eig, loadings = bundle.rmt_summary, bundle.rmt_eigen, bundle.rmt_loadings
            universe_caption = ", ".join(bundle.rmt_peer_universe)
        else:
            rs, eig, loadings = bundle.rmt_full_summary, bundle.rmt_full_eigen, bundle.rmt_full_loadings
            universe_caption = ", ".join(bundle.changes.columns)

        if rs.get("status") != "ok":
            st.info("RMT indisponible : échantillon commun insuffisant.")
        else:
            a = st.columns(6)
            a[0].metric("Above MP", rs.get("above_mp"))
            a[1].metric("Inside MP", rs.get("inside_mp"))
            a[2].metric("Below MP", rs.get("below_mp"))
            a[3].metric("PC1", fmt_pct(rs.get("pc1_variance")))
            a[4].metric("Effective rank", fmt_num(rs.get("effective_rank")))
            a[5].metric("Condition #", fmt_num(rs.get("condition_number")))
            st.caption(f"Universe: {universe_caption}")
            _rmt_chart(eig, f"Eigen spectrum vs Marchenko-Pastur — {rmt_mode}")
            st.subheader("Leading eigenvector loadings")
            if not loadings.empty:
                pc1 = loadings[loadings["Component"] == "PC1"].sort_values("Abs loading", ascending=False).head(15)
                st.dataframe(pc1, use_container_width=True, hide_index=True)
            st.caption("Le mode Homogeneous peers évite de gonfler artificiellement le market mode en mélangeant single names, benchmarks et ETF qui contiennent les mêmes composants.")

        st.subheader("Minimum Spanning Tree")
        if bundle.mst_table.empty:
            st.info("MST indisponible.")
        else:
            _mst_graph(bundle.mst_table, ticker, bundle.asset_type_map)
            with st.expander("MST edge table", expanded=False):
                st.dataframe(bundle.mst_table, use_container_width=True, hide_index=True, height=table_height(bundle.mst_table, max_height=560))

        st.subheader("Partial-correlation network")
        if bundle.partial_network_edges.empty:
            st.info("Réseau partiel trop sparse ou indisponible sur la fenêtre sélectionnée.")
        else:
            _partial_graph(bundle.partial_network_edges, bundle.partial_network_centrality, ticker, bundle.asset_type_map)
            ccols = ["Asset", "Type", "Degree", "Strength", "Signed strength", "Cross-asset links"]
            cent = bundle.partial_network_centrality[[c for c in ccols if c in bundle.partial_network_centrality.columns]].head(15).copy()
            for c in ["Strength", "Signed strength"]:
                if c in cent:
                    cent[c] = cent[c].map(fmt_num)
            st.dataframe(cent, use_container_width=True, hide_index=True)
            st.caption("La partial correlation retire la dépendance conditionnelle expliquée par les autres actifs du système; elle complète la corrélation brute, elle ne la remplace pas.")

        st.subheader("Network statistical inference")
        if bundle.partial_network_stability.empty:
            st.info("Bootstrap stability selection indisponible.")
        else:
            ns=bundle.partial_network_stability.copy()
            for c in ["Selection frequency","CI low","CI high"]:
                if c in ns: ns[c]=ns[c].map(fmt_pct if c=="Selection frequency" else fmt_corr)
            for c in ["Sign p-value","BH q-value"]:
                if c in ns: ns[c]=ns[c].map(fmt_pvalue)
            if "Median partial corr" in ns: ns["Median partial corr"]=ns["Median partial corr"].map(fmt_corr)
            st.dataframe(ns.head(25),use_container_width=True,hide_index=True)
            st.caption(f"Stable edge = sélection dans ≥{cfg.network_selection_threshold:.0%} des moving-block bootstraps; Stat supported ajoute Benjamini-Hochberg q≤10%. Précision actuelle: {bundle.partial_network_stability_meta.get('bootstrap_valid',0)} réplications valides.")

        st.subheader("Directional connectedness")
        cm = bundle.connectedness_meta
        if cm.get("status") != "ok" or bundle.connectedness_matrix.empty:
            st.info(f"Connectedness VAR/FEVD indisponible: {cm.get('status','N/A')} · obs {cm.get('obs','N/A')}")
        else:
            k1,k2,k3,k4 = st.columns(4)
            k1.metric("Total connectedness", f"{fmt_num(cm.get('TCI'))}%")
            k2.metric("VAR lag", str(cm.get("VAR lag", "N/A")))
            k3.metric("FEVD horizon", str(cm.get("forecast_horizon", "N/A")))
            k4.metric("VAR stable", str(cm.get("VAR stable", "N/A")))
            st.caption("Universe: " + ", ".join(bundle.connectedness_universe))
            _connectedness_graph(bundle.connectedness_matrix, bundle.connectedness_table, ticker)
            ct = bundle.connectedness_table.copy()
            for c in ["FROM others", "TO others", "NET transmitter", "Own share"]:
                if c in ct:
                    ct[c] = ct[c].map(lambda v: f"{float(v):.2f}%" if pd.notna(v) else "N/A")
            st.dataframe(ct, use_container_width=True, hide_index=True)
            with st.expander("Generalized FEVD matrix", expanded=False):
                m = bundle.connectedness_matrix.copy()
                st.dataframe(m.style.format("{:.2f}%"), use_container_width=True)
            st.caption("Rows receive shocks and columns transmit shocks. NET = TO − FROM; a positive NET identifies a net shock transmitter in the selected VAR universe.")

        st.subheader("Frequency connectedness")
        if bundle.frequency_connectedness.empty:
            st.info(f"Frequency decomposition indisponible: {bundle.frequency_meta.get('status','N/A')}")
        else:
            fm = bundle.frequency_meta
            f1,f2,f3 = st.columns(3)
            f1.metric("Spectral total TCI", f"{fmt_num(fm.get('spectral_total_TCI'))}%")
            f2.metric("Sum absolute bands", f"{fmt_num(fm.get('sum_absolute_band_contributions'))}%")
            f3.metric("Reconciliation error", f"{fmt_num(fm.get('reconciliation_error'))} pp")
            _frequency_chart(bundle.frequency_connectedness)
            fc=bundle.frequency_connectedness.copy()
            for c in ["Within-band connectedness","Absolute TCI contribution","Band variance mass"]:
                if c in fc: fc[c]=fc[c].map(lambda v:f"{float(v):.2f}%")
            st.dataframe(fc,use_container_width=True,hide_index=True)
            with st.expander("Directional absolute contribution by frequency",expanded=False):
                fd=bundle.frequency_directional.copy()
                for c in ["FROM absolute contribution","TO absolute contribution","NET absolute contribution"]:
                    if c in fd: fd[c]=fd[c].map(lambda v:f"{float(v):.2f} pp")
                st.dataframe(fd,use_container_width=True,hide_index=True)
            st.caption("Within-band connectedness mesure l’intensité conditionnelle à la bande et ne s’additionne pas. Absolute TCI contribution est additive et doit se réconcilier avec le Spectral total TCI. Ce total spectral est un objet VAR stationnaire/infinite-horizon distinct du TCI FEVD à horizon 10 affiché au-dessus.")

    with tabs[6]:
        st.subheader("Hedge efficiency & robustness")
        if bundle.hedges.empty:
            st.info("Aucun hedge candidat exploitable.")
        else:
            filter_mode = st.radio("Hedge universe", ["Systematic", "Peer equities", "All"], horizontal=True, key=f"corrv31_hedgeuniverse_{ticker}")
            h = bundle.hedges.copy()
            systematic_types = {"Benchmark", "ETF / Sector", "Rates ETF", "Credit ETF", "Commodity ETF", "FX", "Volatility", "Crypto"}
            if filter_mode == "Systematic":
                h = h[h["Type"].isin(systematic_types)]
            elif filter_mode == "Peer equities":
                h = h[h["Type"] == "Peer Equity"]
            if h.empty:
                st.info("Aucun candidat dans cet univers.")
            else:
                cols = [
                    "Hedge", "Type", "Robust hedge score", "Hedge ratio", "Corr", "Stress corr", "Vol reduction",
                    "Mean vol reduction", "OOS vol reduction", "Stability", "Hedge ratio CV", "Residual vol", "Obs",
                ]
                x = h[[c for c in cols if c in h.columns]].head(20).copy()
                for c in ["Hedge ratio", "Hedge ratio CV", "Robust hedge score"]:
                    if c in x:
                        x[c] = x[c].map(fmt_num if c != "Robust hedge score" else fmt_score)
                for c in ["Corr", "Stress corr"]:
                    if c in x:
                        x[c] = x[c].map(fmt_corr)
                for c in ["Vol reduction", "Mean vol reduction", "OOS vol reduction", "Residual vol"]:
                    if c in x:
                        x[c] = x[c].map(fmt_pct)
                st.dataframe(x, use_container_width=True, hide_index=True, height=table_height(x, max_height=650))
                st.caption("Robust hedge score combine efficacité sur la fenêtre, stabilité multi-horizon et test chronologique 70/30. Un hedge positif suppose une position opposée dans l'instrument de couverture.")

                with st.expander("Multi-window hedge stability", expanded=False):
                    wcols = ["Hedge", "Type", "Stability"]
                    for w in cfg.hedge_windows:
                        wcols += [f"Hedge ratio {w}D", f"Vol reduction {w}D"]
                    ww = h[[c for c in wcols if c in h.columns]].head(15).copy()
                    for c in ww.columns:
                        if c.startswith("Hedge ratio"):
                            ww[c] = ww[c].map(fmt_num)
                        elif c.startswith("Vol reduction"):
                            ww[c] = ww[c].map(fmt_pct)
                    st.dataframe(ww, use_container_width=True, hide_index=True)

        st.subheader("Portfolio dependency & risk decomposition")
        if bundle.portfolio_table.empty:
            st.info("Ajoute des poids dans 'Portfolio weights (optional)' en haut du module, ou fournis analysis['portfolio_weights'], pour activer MCTR/CTR, CVaR et correlation shocks.")
        else:
            pm = bundle.portfolio_meta
            p1,p2,p3,p4,p5,p6 = st.columns(6)
            p1.metric("Ann. vol", fmt_pct(pm.get("annualized_vol")))
            p2.metric("CVaR 95% daily", fmt_pct(pm.get("CVaR95 daily")))
            p3.metric("Diversification ratio", fmt_num(pm.get("diversification_ratio")))
            p4.metric("Effective N", fmt_num(pm.get("effective_n")))
            p5.metric("Risk HHI", fmt_num(pm.get("risk_hhi")))
            p6.metric("Gross exposure", fmt_pct(pm.get("gross_exposure")))
            st.caption(f"Covariance: {pm.get('covariance_method','N/A')} · observations communes: {pm.get('obs','N/A')}")

            x = bundle.portfolio_table.copy()
            for c in ["Weight", "Standalone vol", "Marginal risk", "Component risk", "Risk contribution %"]:
                if c in x:
                    x[c] = x[c].map(fmt_pct)
            st.dataframe(x, use_container_width=True, hide_index=True)

            if not bundle.portfolio_cluster_table.empty:
                st.subheader("Risk contribution by asset class / cluster proxy")
                cl = bundle.portfolio_cluster_table.copy()
                for c in ["Weight", "Component risk", "Risk contribution %"]:
                    if c in cl:
                        cl[c] = cl[c].map(fmt_pct)
                st.dataframe(cl, use_container_width=True, hide_index=True)

            if not bundle.portfolio_eigen_table.empty:
                st.subheader("Portfolio eigen-risk")
                em=bundle.portfolio_eigen_meta
                e1,e2=st.columns(2)
                e1.metric("PC1 portfolio risk share",fmt_pct(em.get("top_mode_share")))
                e2.metric("Effective risk modes",fmt_num(em.get("effective_modes")))
                et=bundle.portfolio_eigen_table.head(10).copy()
                for c in ["Risk share"]:
                    if c in et: et[c]=et[c].map(fmt_pct)
                for c in ["Eigenvalue","Portfolio loading","Variance contribution"]:
                    if c in et: et[c]=et[c].map(fmt_num)
                st.dataframe(et,use_container_width=True,hide_index=True)
                st.caption("Risk_k = λ_k (w'v_k)^2. Cette vue révèle si plusieurs positions ne sont en réalité qu'une seule exposition latente.")

            if not bundle.portfolio_structured_stress.empty:
                st.subheader("Structured correlation stress")
                ps=bundle.portfolio_structured_stress.copy()
                for c in ["Daily vol","Annualized vol","Vol change"]:
                    if c in ps: ps[c]=ps[c].map(fmt_pct)
                if "Matrix condition" in ps: ps["Matrix condition"]=ps["Matrix condition"].map(fmt_num)
                st.dataframe(ps,use_container_width=True,hide_index=True)
                st.caption("Scénarios: convergence uniforme, intra-cluster, régime high-vol historique, amplification du mode dominant et convergence worst-case selon les signes des poids.")

            if not bundle.portfolio_shock_table.empty:
                st.subheader("Legacy uniform correlation shock")
                cs = bundle.portfolio_shock_table.copy()
                for c in ["Correlation blend", "Daily vol", "Annualized vol", "Vol change"]:
                    if c in cs:
                        cs[c] = cs[c].map(fmt_pct)
                st.dataframe(cs, use_container_width=True, hide_index=True)
                fig = go.Figure(go.Bar(x=bundle.portfolio_shock_table["Scenario"], y=bundle.portfolio_shock_table["Annualized vol"], text=bundle.portfolio_shock_table["Annualized vol"].map(fmt_pct), textposition="auto"))
                fig.update_layout(height=390, title="Portfolio volatility under correlation convergence", yaxis_tickformat=".1%", template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(10,14,22,.55)")
                st.plotly_chart(fig, use_container_width=True)
                st.caption("Le stress conserve les volatilités marginales et mélange progressivement la matrice vers une corrélation de +1. Il isole le risque de disparition de diversification.")

            if not bundle.portfolio_incremental_table.empty:
                st.subheader(f"Incremental asset impact — add {cfg.incremental_add_weight:.0%}")
                inc = bundle.portfolio_incremental_table.head(15).copy()
                for c in ["Add weight", "Annualized vol", "Δ annualized vol", "Δ vol %", "CVaR95 daily", "Δ CVaR95"]:
                    if c in inc:
                        inc[c] = inc[c].map(fmt_pct)
                st.dataframe(inc, use_container_width=True, hide_index=True)
                st.caption("L'ajout est financé pro-rata en préservant l'exposition nette quand elle est non nulle; Δvol et ΔCVaR indiquent si le candidat ajoute ou détruit de la diversification historique.")

        st.subheader("Forward-looking / implied correlation")
        fm = bundle.forward_corr_meta
        if fm.get("status") != "ok":
            st.info("Pas de donnée option-implied injectée. Le moteur est prêt pour analysis['correlation_implied_inputs'], scalar/series, term structure ou skew.")
            with st.expander("Expected implied-correlation input schema", expanded=False):
                st.code("""analysis['correlation_implied_inputs'] = {
    'index_iv': 0.20,
    'weights': {'AAPL': 0.10, 'MSFT': 0.10, ...},
    'component_ivs': {'AAPL': 0.25, 'MSFT': 0.23, ...},
    'horizon_days': 63,
    'source': 'OPRA / Cboe / internal vol surface'
}
analysis['correlation_implied_term_structure'] = {21:0.48, 63:0.52, 126:0.55, 252:0.57}
analysis['correlation_implied_skew'] = {'Put OTM':0.60, 'ATM':0.52, 'Call OTM':0.47}""", language="python")
        else:
            f1,f2,f3,f4 = st.columns(4)
            implied = fm.get("implied_corr_clipped", fm.get("implied_corr"))
            realized = fm.get("realized_corr", fm.get("realized_corr_proxy"))
            premium = fm.get("correlation_risk_premium", fm.get("correlation_risk_premium_proxy"))
            f1.metric("Implied corr", fmt_pct(implied))
            f2.metric("Realized corr", fmt_pct(realized))
            f3.metric("Corr risk premium", fmt_pct(premium))
            f4.metric("Horizon", f"{fm.get('horizon_days','N/A')}D")
            st.caption(f"Source: {fm.get('source','N/A')} · method: {fm.get('method','N/A')}. The variance-identity mode is an average/equicorrelation diagnostic, not a replication of a licensed production index methodology.")
            _forward_corr_chart(bundle.forward_corr_history)
            _forward_term_chart(fm)
            if isinstance(fm.get("skew"),dict) and fm.get("skew"):
                st.subheader("Implied-correlation skew")
                sk=pd.DataFrame([{"Slice":k,"Implied correlation":v} for k,v in fm["skew"].items()])
                sk["Implied correlation"]=sk["Implied correlation"].map(fmt_pct)
                st.dataframe(sk,use_container_width=True,hide_index=True)

    with tabs[7]:
        st.subheader("Covariance forecast & model validation")
        cm=bundle.covariance_meta
        if bundle.covariance_validation.empty:
            st.info(f"Validation indisponible: {cm.get('status','N/A')}")
        else:
            v1,v2,v3,v4,v5=st.columns(5)
            v1.metric("Operational selection",str(cm.get("champion","N/A")))
            v2.metric("Selection confidence",str(cm.get("champion_status","N/A")), fmt_pct(cm.get("champion_probability")) if cm.get("champion_probability") is not None else None)
            v3.metric("Runner-up",str(cm.get("runner_up","N/A")))
            v4.metric("Forecast horizon",f"{cm.get('forecast_horizon','N/A')}D")
            v5.metric("Walk-forward folds",str(cm.get("folds","N/A")))
            cv=bundle.covariance_validation.copy()
            for c in ["QLIKE","Relative Frobenius"]:
                if c in cv: cv[c]=cv[c].map(fmt_num)
            for c in ["OOS GMV ann. vol","GMV turnover"]:
                if c in cv: cv[c]=cv[c].map(fmt_pct)
            if "Validation score" in cv: cv["Validation score"]=cv["Validation score"].map(fmt_score)
            st.dataframe(cv,use_container_width=True,hide_index=True)
            st.caption("Champion/challenger walk-forward: QLIKE + relative Frobenius + realized GMV risk + turnover. La sélection opérationnelle est ensuite comparée au runner-up par paired bootstrap sur les folds OOS; un tie statistique est explicitement conservé.")
            _heatmap(bundle.corr_forecast,f"Operational forecast correlation — {cm.get('champion','N/A')}")
            with st.expander("Model definitions / optional nonlinear shrinkage",expanded=False):
                st.markdown("**POET-style** = PCA low-rank + residual thresholding. **Factor-GLasso** = low-rank factors + sparse residual precision. **RMT spectral** = constant-residual-eigenvalue cleaning. Analytical nonlinear shrinkage is an optional adapter only and is never silently approximated.")

    with tabs[8]:
        render_dependency_intelligence_tab(
            bundle,
            ticker,
            analysis_local,
            portfolio_weights=analysis_local.get("portfolio_weights") if isinstance(analysis_local.get("portfolio_weights"), dict) else None,
        )

    with tabs[9]:
        st.subheader("Data quality & audit")
        q = bundle.quality.copy()
        for c in ["Coverage %", "Internal missing %"]:
            if c in q:
                q[c] = q[c].map(fmt_pct)
        st.dataframe(q, use_container_width=True, hide_index=True, height=table_height(q, max_height=650))
        st.caption("Coverage mesure la profondeur historique demandée; Internal missing % et Largest internal gap ne comptent plus l'historique antérieur indisponible comme des trous internes. Provider est suivi série par série.")
        st.subheader("Market synchronization audit")
        if bundle.synchronization.empty:
            st.info("Aucune métadonnée de session injectée. Les returns restent alignés par observations communes sans forward-fill.")
        else:
            st.dataframe(bundle.synchronization,use_container_width=True,hide_index=True)
            st.caption("Pour les marchés à closes non synchrones, fournis analysis['correlation_market_metadata'] et analysis['correlation_alignment_lags']. Hayashi-Yoshida est exposé dans synchronization.py pour un futur adapter intraday asynchrone; il n'est jamais appliqué à des closes daily par défaut.")
        pack = research_pack_zip(bundle, cfg, {"ticker": ticker, "selected_days": selected_days, "data_source": bundle.data_source, "engine_version": "4.0"})
        st.download_button("Télécharger le Research Pack ZIP", data=pack, file_name=f"{ticker}_correlation_research_pack_v4_0_{selected_days}D.zip", mime="application/zip", key=f"corrv31_export_{ticker}_{selected_days}")


# Backward-compatible public entry points. Existing app.py can keep the old import/call.
def render_correlation_intelligence_v2(ticker: str, price_data: pd.DataFrame, analysis: dict | None = None):
    return render_correlation_intelligence_v3(ticker, price_data, analysis)


def render_correlation_intelligence_v1(ticker: str, price_data: pd.DataFrame, analysis: dict | None = None):
    return render_correlation_intelligence_v3(ticker, price_data, analysis)
