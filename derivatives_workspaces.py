"""Decision-oriented workspaces for Options & Futures Intelligence.

This module owns the presentation and the pure cross-sectional analytics for
all outer workspaces except Strategy Lab.  It intentionally distinguishes
observable market fields from hypotheses (especially dealer gamma signs).
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import zipfile
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st


CYAN = "#39d6e8"
BLUE = "#5b8cff"
GREEN = "#38d996"
AMBER = "#f5b942"
RED = "#ff5c75"
PURPLE = "#a779e9"
GRID = "rgba(148,163,184,.14)"
PLOT_TEMPLATE = "plotly_dark"


def _num(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        out = float(value)
        return out if np.isfinite(out) else default
    except (TypeError, ValueError):
        return default


def _pct(value: Any, digits: int = 1) -> str:
    number = _num(value)
    return "N/A" if number is None else f"{number * 100:.{digits}f}%"


def _price(value: Any) -> str:
    number = _num(value)
    return "N/A" if number is None else f"{number:,.2f}"


def _large(value: Any) -> str:
    number = _num(value)
    if number is None:
        return "N/A"
    sign = "−" if number < 0 else ""
    number = abs(number)
    for scale, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if number >= scale:
            return f"{sign}{number / scale:.2f}{suffix}"
    return f"{sign}{number:.0f}"


def _figure(title: str, height: int = 420) -> go.Figure:
    fig = go.Figure()
    fig.update_layout(
        template=PLOT_TEMPLATE,
        height=height,
        title=title,
        margin=dict(l=20, r=20, t=56, b=25),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(8,15,28,.65)",
        legend=dict(orientation="h", y=1.02, x=1, xanchor="right", yanchor="bottom"),
        hovermode="x unified",
    )
    fig.update_xaxes(gridcolor=GRID, zerolinecolor=GRID)
    fig.update_yaxes(gridcolor=GRID, zerolinecolor=GRID)
    return fig


def _data_context(context: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    return dict(context or {})


def render_data_provenance(context: Optional[Mapping[str, Any]], compact: bool = False) -> None:
    ctx = _data_context(context)
    provider = str(ctx.get("provider") or "Source inconnue")
    recency = str(ctx.get("recency") or "UNKNOWN").upper()
    status = str(ctx.get("status") or "unknown").lower()
    rows = int(_num(ctx.get("rows"), 0) or 0)
    stamp = str(ctx.get("quote_timestamp") or "horodatage indisponible")
    quality = dict(ctx.get("quality") or {})
    color = GREEN if status == "ok" and recency == "REAL-TIME" else AMBER if status in {"ok", "fallback"} else RED
    label = f"{provider} · {recency} · {rows:,} contrats"
    st.markdown(
        f"<div style='border:1px solid {color}55;border-left:4px solid {color};padding:.55rem .8rem;"
        f"border-radius:8px;background:rgba(15,23,42,.55);font-size:.86rem'>"
        f"<b style='color:{color}'>{label}</b> &nbsp; <span style='color:#94a3b8'>{stamp}</span></div>",
        unsafe_allow_html=True,
    )
    if not compact:
        coverage = _num(quality.get("two_sided_coverage"))
        spread = _num(quality.get("median_spread_pct"))
        age = _num(quality.get("median_quote_age_seconds"))
        pieces = [str(ctx.get("message") or "")]
        if coverage is not None:
            pieces.append(f"NBBO bilatéral {_pct(coverage, 0)}")
        if spread is not None:
            pieces.append(f"spread médian {_pct(spread, 1)}")
        if age is not None:
            pieces.append(f"âge médian {age:.0f}s")
        st.caption(" · ".join(piece for piece in pieces if piece))


def _metric_row(items: Sequence[Tuple[str, str, str]]) -> None:
    columns = st.columns(len(items))
    for column, (label, value, delta) in zip(columns, items):
        column.metric(label, value, delta or None, delta_color="off")


def normalize_surface(surface: pd.DataFrame) -> pd.DataFrame:
    if surface is None or surface.empty:
        return pd.DataFrame()
    out = surface.copy()
    if "iv" not in out.columns and "impliedVolatility" in out.columns:
        out["iv"] = out["impliedVolatility"]
    if "option_type" not in out.columns:
        out["option_type"] = "unknown"
    for column in ("strike", "iv", "dte", "volume", "openInterest"):
        if column in out.columns:
            out[column] = pd.to_numeric(out[column], errors="coerce")
    out = out.dropna(subset=[column for column in ("strike", "iv") if column in out.columns])
    out = out[(out["iv"] > 0.01) & (out["iv"] < 5.0)]
    return out.replace([np.inf, -np.inf], np.nan)


def option_liquidity_snapshot(calls: pd.DataFrame, puts: pd.DataFrame) -> Dict[str, Any]:
    frames = [frame for frame in (calls, puts) if frame is not None and not frame.empty]
    if not frames:
        return {"contracts": 0, "two_sided": 0.0, "median_spread": None, "volume": 0.0, "oi": 0.0}
    frame = pd.concat(frames, ignore_index=True)
    bid = pd.to_numeric(frame.get("bid", pd.Series(index=frame.index, dtype=float)), errors="coerce")
    ask = pd.to_numeric(frame.get("ask", pd.Series(index=frame.index, dtype=float)), errors="coerce")
    mid = (bid + ask) / 2.0
    valid = (bid > 0) & (ask > 0) & (ask >= bid)
    spreads = ((ask - bid) / mid.replace(0, np.nan)).where(valid)
    volume = pd.to_numeric(frame.get("volume", pd.Series(index=frame.index, dtype=float)), errors="coerce").fillna(0)
    oi = pd.to_numeric(frame.get("openInterest", pd.Series(index=frame.index, dtype=float)), errors="coerce").fillna(0)
    return {
        "contracts": len(frame),
        "two_sided": float(valid.mean()),
        "median_spread": float(spreads.median()) if spreads.notna().any() else None,
        "volume": float(volume.sum()),
        "oi": float(oi.sum()),
    }


def positioning_by_strike(calls: pd.DataFrame, puts: pd.DataFrame, spot: float) -> pd.DataFrame:
    rows: List[pd.DataFrame] = []
    for label, frame in (("call", calls), ("put", puts)):
        if frame is None or frame.empty:
            continue
        work = frame.copy()
        work["strike"] = pd.to_numeric(work.get("strike"), errors="coerce")
        work["openInterest"] = pd.to_numeric(work.get("openInterest"), errors="coerce").fillna(0)
        work["volume"] = pd.to_numeric(work.get("volume"), errors="coerce").fillna(0)
        work["side"] = label
        rows.append(work[["strike", "side", "openInterest", "volume"]])
    if not rows:
        return pd.DataFrame()
    joined = pd.concat(rows, ignore_index=True).dropna(subset=["strike"])
    pivot_oi = joined.pivot_table(index="strike", columns="side", values="openInterest", aggfunc="sum", fill_value=0)
    pivot_vol = joined.pivot_table(index="strike", columns="side", values="volume", aggfunc="sum", fill_value=0)
    result = pd.DataFrame(index=sorted(joined["strike"].unique()))
    result["call_oi"] = pivot_oi.get("call", 0)
    result["put_oi"] = pivot_oi.get("put", 0)
    result["call_volume"] = pivot_vol.get("call", 0)
    result["put_volume"] = pivot_vol.get("put", 0)
    result = result.fillna(0).reset_index(names="strike")
    result["total_oi"] = result["call_oi"] + result["put_oi"]
    result["total_volume"] = result["call_volume"] + result["put_volume"]
    result["volume_oi"] = result["total_volume"] / result["total_oi"].replace(0, np.nan)
    result["put_call_oi"] = result["put_oi"] / result["call_oi"].replace(0, np.nan)
    result["distance_spot"] = result["strike"] / max(float(spot), 1e-12) - 1.0
    total = result["total_oi"].sum()
    result["oi_share"] = result["total_oi"] / total if total > 0 else 0.0
    return result.sort_values("strike").reset_index(drop=True)


def delta_skew_snapshot(calls: pd.DataFrame, puts: pd.DataFrame, spot: float) -> Dict[str, Any]:
    def prepared(frame: pd.DataFrame, kind: str) -> pd.DataFrame:
        if frame is None or frame.empty:
            return pd.DataFrame()
        out = frame.copy()
        out["iv"] = pd.to_numeric(out.get("iv", out.get("impliedVolatility")), errors="coerce")
        vendor = pd.to_numeric(out.get("delta_vendor", pd.Series(index=out.index, dtype=float)), errors="coerce")
        model = pd.to_numeric(out.get("delta", pd.Series(index=out.index, dtype=float)), errors="coerce")
        out["effective_delta"] = vendor.combine_first(model)
        out["strike"] = pd.to_numeric(out.get("strike"), errors="coerce")
        out["weight"] = pd.to_numeric(out.get("openInterest", 0), errors="coerce").fillna(0) + 1
        return out.dropna(subset=["iv", "strike"])

    call = prepared(calls, "call")
    put = prepared(puts, "put")

    def closest_delta(frame: pd.DataFrame, target: float) -> Optional[float]:
        if frame.empty or frame["effective_delta"].notna().sum() == 0:
            return None
        idx = (frame["effective_delta"] - target).abs().idxmin()
        return _num(frame.loc[idx, "iv"])

    def atm(frame: pd.DataFrame) -> Optional[float]:
        if frame.empty:
            return None
        near = frame.assign(distance=(frame["strike"] - spot).abs()).nsmallest(4, "distance")
        valid = near.dropna(subset=["iv"])
        if valid.empty:
            return None
        return float(np.average(valid["iv"], weights=valid["weight"]))

    c25 = closest_delta(call, 0.25)
    p25 = closest_delta(put, -0.25)
    atm_values = [value for value in (atm(call), atm(put)) if value is not None]
    atm_iv = float(np.mean(atm_values)) if atm_values else None
    rr25 = p25 - c25 if p25 is not None and c25 is not None else None
    bf25 = (p25 + c25) / 2.0 - atm_iv if p25 is not None and c25 is not None and atm_iv is not None else None
    return {"call_25d_iv": c25, "put_25d_iv": p25, "atm_iv": atm_iv, "rr25": rr25, "bf25": bf25}


def gamma_exposure_by_strike(
    calls: pd.DataFrame,
    puts: pd.DataFrame,
    spot: float,
    assumption: str = "concentration",
) -> pd.DataFrame:
    rows: List[pd.DataFrame] = []
    for kind, frame in (("call", calls), ("put", puts)):
        if frame is None or frame.empty:
            continue
        work = frame.copy()
        work["strike"] = pd.to_numeric(work.get("strike"), errors="coerce")
        vendor = pd.to_numeric(work.get("gamma_vendor", pd.Series(index=work.index, dtype=float)), errors="coerce")
        model = pd.to_numeric(work.get("gamma", pd.Series(index=work.index, dtype=float)), errors="coerce")
        work["gamma_effective"] = vendor.combine_first(model).fillna(0)
        work["openInterest"] = pd.to_numeric(work.get("openInterest"), errors="coerce").fillna(0)
        base = work["gamma_effective"].abs() * work["openInterest"] * 100.0 * float(spot) ** 2 * 0.01
        if assumption == "calls_plus_puts_minus":
            sign = 1.0 if kind == "call" else -1.0
        elif assumption == "calls_minus_puts_plus":
            sign = -1.0 if kind == "call" else 1.0
        else:
            sign = 1.0
        work["exposure"] = base * sign
        work["absolute_exposure"] = base
        work["kind"] = kind
        rows.append(work[["strike", "kind", "exposure", "absolute_exposure", "openInterest"]])
    if not rows:
        return pd.DataFrame()
    result = pd.concat(rows, ignore_index=True).dropna(subset=["strike"])
    return result.groupby("strike", as_index=False).agg(
        exposure=("exposure", "sum"), absolute_exposure=("absolute_exposure", "sum"), open_interest=("openInterest", "sum")
    ).sort_values("strike")


def term_structure(surface: pd.DataFrame, spot: float) -> pd.DataFrame:
    work = normalize_surface(surface)
    if work.empty or "expiration" not in work.columns:
        return pd.DataFrame()
    rows = []
    for expiration, group in work.groupby("expiration"):
        group = group.assign(distance=(group["strike"] - spot).abs()).nsmallest(8, "distance")
        weights = pd.to_numeric(group.get("openInterest", 0), errors="coerce").fillna(0) + 1
        iv = float(np.average(group["iv"], weights=weights)) if len(group) else np.nan
        dte = _num(group["dte"].dropna().iloc[0]) if "dte" in group and group["dte"].notna().any() else None
        rows.append({"expiration": str(expiration), "dte": dte, "atm_iv": iv, "expected_move": iv * math.sqrt(max(dte or 1, 1) / 365.0)})
    return pd.DataFrame(rows).dropna(subset=["dte", "atm_iv"]).sort_values("dte")


def render_executive_workspace(
    ticker: str,
    expiration: str,
    spot: float,
    metrics: Mapping[str, Any],
    macro_summary: Mapping[str, Any],
    calls: pd.DataFrame,
    puts: pd.DataFrame,
    data_context: Optional[Mapping[str, Any]],
) -> None:
    st.subheader("Executive Decision Cockpit")
    render_data_provenance(data_context)
    liquidity = option_liquidity_snapshot(calls, puts)
    skew = delta_skew_snapshot(calls, puts, spot)
    _metric_row(
        [
            ("Spot", _price(spot), f"{expiration} · {int(_num(metrics.get('dte'), 0) or 0)} DTE"),
            ("Implied / realized", f"{_pct(metrics.get('atm_iv'))} / {_pct(metrics.get('rv20'))}", f"VRP {_pct(metrics.get('iv_premium_20'))}"),
            ("25Δ put-call skew", _pct(skew.get("rr25")), "protection − upside"),
            ("Liquidity", _pct(liquidity.get("two_sided"), 0), f"spread médian {_pct(liquidity.get('median_spread'))}"),
            ("Macro tape", str(macro_summary.get("tape_state", "N/A")), f"score {_num(macro_summary.get('tape_score'), 50):.0f}/100"),
        ]
    )
    st.markdown("#### Decision stack")
    premium = _num(metrics.get("iv_premium_20"))
    rr = _num(skew.get("rr25"))
    dte = int(_num(metrics.get("dte"), 0) or 0)
    two_sided = _num(liquidity.get("two_sided"), 0) or 0
    decisions = [
        {
            "Pilier": "Volatility valuation",
            "État": "IV riche" if premium is not None and premium > 0.25 else "IV non extrême" if premium is not None else "Non mesuré",
            "Décision": "Favoriser structures à vega borné / vente définie." if premium is not None and premium > 0.25 else "Le prix de convexité ne bloque pas l'achat; valider le catalyste.",
            "Invalidation": "Recalibrer si l'IV ou la courbe change de régime.",
        },
        {
            "Pilier": "Skew & tails",
            "État": "Put wing riche" if rr is not None and rr > 0.03 else "Skew équilibré" if rr is not None else "Non mesuré",
            "Décision": "Comparer put spread/collar au put sec." if rr is not None and rr > 0.03 else "Pas de distorsion 25Δ majeure détectée.",
            "Invalidation": "Le delta-skew est cross-sectionnel, pas un forecast.",
        },
        {
            "Pilier": "Execution quality",
            "État": "Exécutable" if two_sided >= 0.65 else "Fragile",
            "Décision": "Ordres limites et contrôle du slippage." if two_sided >= 0.65 else "Réduire les jambes/tailles ou changer d'échéance.",
            "Invalidation": "Revalider NBBO et tailles juste avant l'ordre.",
        },
        {
            "Pilier": "Time & event risk",
            "État": "Très court terme" if dte < 3 else "Court terme" if dte < 14 else "Standard",
            "Décision": "Surveiller gamma/charm intraday." if dte < 7 else "La surface et le carry dominent davantage.",
            "Invalidation": "Calendrier, dividendes et exercise anticipé non garantis.",
        },
    ]
    st.dataframe(pd.DataFrame(decisions), width="stretch", hide_index=True)
    left, right = st.columns([1.15, 1])
    with left:
        st.markdown("#### Trade readiness gate")
        checks = pd.DataFrame(
            [
                ("Source et récence visibles", bool(data_context and data_context.get("status") in {"ok", "fallback"})),
                ("NBBO bilatéral ≥ 65%", two_sided >= 0.65),
                ("Expiration > 2 DTE", dte > 2),
                ("Thèse de volatilité identifiée", premium is not None),
                ("Risque macro qualifié", macro_summary.get("tape_state") is not None),
            ],
            columns=["Contrôle", "Validé"],
        )
        checks["Statut"] = np.where(checks["Validé"], "PASS", "REVIEW")
        st.dataframe(checks[["Contrôle", "Statut"]], width="stretch", hide_index=True)
    with right:
        st.markdown("#### Action brief")
        if two_sided < 0.4:
            st.error("Qualité d'exécution insuffisante : ne pas transformer l'analyse en ordre sans vérifier les quotes.")
        elif dte < 3:
            st.warning("Régime très court : le hedge local et le slippage peuvent dominer la thèse directionnelle.")
        else:
            st.success("La chaîne est analysable. Construire le ticket dans Strategy Lab puis stresser spot, IV et temps.")
        st.caption("Le cockpit est un filtre de décision, pas une recommandation d'investissement ni un système d'exécution.")


def render_surface_workspace(
    ticker: str,
    calls: pd.DataFrame,
    puts: pd.DataFrame,
    surface: pd.DataFrame,
    spot: float,
    expiration: str,
    window_pct: float,
    data_context: Optional[Mapping[str, Any]],
) -> None:
    st.subheader("Options Market & Surface")
    render_data_provenance(data_context, compact=True)
    chain_tab, surface_tab, term_tab, quality_tab = st.tabs(["Chain & NBBO", "Vol surface", "Term & event", "Diagnostics"])
    chain = pd.concat([frame for frame in (calls, puts) if frame is not None and not frame.empty], ignore_index=True) if not (calls.empty and puts.empty) else pd.DataFrame()
    with chain_tab:
        if chain.empty:
            st.info("Chaîne indisponible.")
        else:
            low, high = spot * (1 - window_pct), spot * (1 + window_pct)
            view = chain[(chain["strike"] >= low) & (chain["strike"] <= high)].copy()
            view["NBBO mid"] = (pd.to_numeric(view.get("bid"), errors="coerce") + pd.to_numeric(view.get("ask"), errors="coerce")) / 2
            view["Spread %"] = (view["ask"] - view["bid"]) / view["NBBO mid"].replace(0, np.nan)
            keep = ["option_type", "contractSymbol", "strike", "bid", "ask", "bidSize", "askSize", "NBBO mid", "Spread %", "lastPrice", "volume", "openInterest", "iv", "delta_vendor", "gamma_vendor", "quoteTimestamp"]
            st.dataframe(view[[c for c in keep if c in view.columns]], width="stretch", hide_index=True, height=500)
            st.caption("NBBO = meilleure offre/demande consolidée lorsqu'elle est fournie. Le dernier trade n'est pas une quote exécutable.")
    normalized = normalize_surface(surface)
    with surface_tab:
        if normalized.empty:
            st.info("Surface multi-échéances indisponible.")
        else:
            filtered = normalized[(normalized["strike"] >= spot * (1 - window_pct)) & (normalized["strike"] <= spot * (1 + window_pct))].copy()
            filtered["moneyness"] = filtered["strike"] / spot
            grouped = filtered.groupby(["dte", "moneyness"], as_index=False)["iv"].median().sort_values(["dte", "moneyness"])
            fig = _figure("Surface IV observée — points de marché, sans promesse d'absence d'arbitrage", 520)
            fig.add_trace(go.Mesh3d(x=grouped["moneyness"], y=grouped["dte"], z=grouped["iv"], intensity=grouped["iv"], colorscale="Viridis", opacity=.88, name="IV"))
            fig.update_scenes(xaxis_title="K / Spot", yaxis_title="DTE", zaxis_title="IV")
            st.plotly_chart(fig, width="stretch")
            st.warning("Surface descriptive : aucune calibration SVI/SABR ni garantie butterfly/calendar-arbitrage n'est revendiquée.")
    with term_tab:
        term = term_structure(normalized, spot)
        if term.empty:
            st.info("Structure par terme indisponible.")
        else:
            fig = _figure("ATM IV et mouvement implicite par échéance")
            fig.add_trace(go.Scatter(x=term["dte"], y=term["atm_iv"], mode="lines+markers", name="ATM IV", line=dict(color=CYAN, width=3)))
            fig.add_trace(go.Scatter(x=term["dte"], y=term["expected_move"], mode="lines+markers", name="Move implicite", yaxis="y2", line=dict(color=AMBER)))
            fig.update_layout(yaxis=dict(title="IV", tickformat=".0%"), yaxis2=dict(title="Move", overlaying="y", side="right", tickformat=".0%"))
            st.plotly_chart(fig, width="stretch")
            term["forward_variance_slope"] = np.nan
            if len(term) > 1:
                total_variance = term["atm_iv"] ** 2 * term["dte"] / 365
                term.loc[term.index[1:], "forward_variance_slope"] = np.diff(total_variance) / np.diff(term["dte"] / 365)
            st.dataframe(term, width="stretch", hide_index=True)
    with quality_tab:
        liquidity = option_liquidity_snapshot(calls, puts)
        _metric_row([
            ("Contrats", f"{liquidity['contracts']:,}", expiration),
            ("NBBO bilatéral", _pct(liquidity["two_sided"], 0), "coverage"),
            ("Spread médian", _pct(liquidity["median_spread"]), "mid-relative"),
            ("Volume / OI", _pct(liquidity["volume"] / liquidity["oi"] if liquidity["oi"] else None), "activité vs stock"),
        ])
        st.markdown("**Contrôles nécessaires avant calibration institutionnelle** : nettoyage des quotes croisées, parité put-call, monotonie/convexité des prix, calendar arbitrage, dividendes, taux et exercice américain.")


def render_positioning_workspace(
    calls: pd.DataFrame,
    puts: pd.DataFrame,
    spot: float,
    metrics: Mapping[str, Any],
    window_pct: float,
    data_context: Optional[Mapping[str, Any]],
) -> None:
    st.subheader("Open Interest & Positioning")
    render_data_provenance(data_context, compact=True)
    st.info("L'open interest est un stock de contrats en fin de séance précédente. Il ne révèle ni le sens acheteur/vendeur, ni le participant, ni l'ouverture/fermeture intraday.")
    position = positioning_by_strike(calls, puts, spot)
    if position.empty:
        st.info("Open interest indisponible.")
        return
    view = position[(position["strike"] >= spot * (1 - window_pct)) & (position["strike"] <= spot * (1 + window_pct))].copy()
    hhi = float((position["oi_share"] ** 2).sum()) if not position.empty else np.nan
    top = position.nlargest(1, "oi_share").iloc[0]
    _metric_row([
        ("Call OI", _large(position["call_oi"].sum()), "prior close"),
        ("Put OI", _large(position["put_oi"].sum()), f"PCR {_num(metrics.get('pcr_oi'), 0):.2f}"),
        ("Concentration HHI", f"{hhi:.3f}", "strike concentration"),
        ("Top strike", _price(top["strike"]), _pct(top["oi_share"], 1) + " de l'OI"),
        ("Max-pain descriptif", _price(metrics.get("max_pain")), "non prédictif"),
    ])
    left, right = st.columns([1.35, 1])
    with left:
        fig = _figure("OI observé par strike")
        fig.add_trace(go.Bar(x=view["strike"], y=view["call_oi"], name="Call OI", marker_color=GREEN))
        fig.add_trace(go.Bar(x=view["strike"], y=-view["put_oi"], name="Put OI", marker_color=RED))
        fig.add_vline(x=spot, line_color=CYAN, line_dash="dash", annotation_text="Spot")
        fig.update_layout(barmode="relative", yaxis_title="Contrats (puts négatifs visuellement)")
        st.plotly_chart(fig, width="stretch")
    with right:
        activity = view.nlargest(12, "total_volume")[["strike", "total_volume", "total_oi", "volume_oi", "oi_share"]]
        st.markdown("#### Intraday activity vs prior OI")
        st.dataframe(activity, width="stretch", hide_index=True)
        st.caption("Un volume/OI élevé signale de l'activité, pas automatiquement de nouvelles positions.")
    st.markdown("#### Candidate levels — confidence-aware")
    candidates = position.nlargest(12, "total_oi").copy()
    candidates["distance"] = candidates["distance_spot"].map(lambda x: _pct(x))
    candidates["classification"] = np.where(candidates["strike"] >= spot, "zone haute potentielle", "zone basse potentielle")
    candidates["confidence"] = np.where(candidates["oi_share"] >= 0.05, "élevée sur concentration / faible sur direction", "modérée sur concentration / faible sur direction")
    st.dataframe(candidates[["strike", "classification", "distance", "call_oi", "put_oi", "total_volume", "oi_share", "confidence"]], width="stretch", hide_index=True)


def render_volatility_workspace(
    metrics: Mapping[str, Any],
    calls: pd.DataFrame,
    puts: pd.DataFrame,
    surface: pd.DataFrame,
    spot: float,
    expiration: str,
    data_context: Optional[Mapping[str, Any]],
) -> None:
    st.subheader("Volatility, Skew & Variance")
    render_data_provenance(data_context, compact=True)
    skew = delta_skew_snapshot(calls, puts, spot)
    _metric_row([
        ("ATM IV", _pct(skew.get("atm_iv") or metrics.get("atm_iv")), f"RV20 {_pct(metrics.get('rv20'))}"),
        ("Variance premium", _pct(metrics.get("iv_premium_20")), "IV / RV20 − 1"),
        ("25Δ risk reversal", _pct(skew.get("rr25")), "put IV − call IV"),
        ("25Δ butterfly", _pct(skew.get("bf25")), "wing avg − ATM"),
        ("Expected move", _pct(metrics.get("expected_move_pct")), f"± {_price(metrics.get('expected_move_price'))}"),
    ])
    smile_tab, regime_tab, scenario_tab = st.tabs(["Delta skew", "Term & VRP", "Scenario map"])
    with smile_tab:
        fig = _figure(f"Smile {expiration} — IV par delta")
        for label, frame, color in (("Calls", calls, GREEN), ("Puts", puts, RED)):
            if frame is None or frame.empty:
                continue
            vendor = pd.to_numeric(frame.get("delta_vendor", pd.Series(index=frame.index, dtype=float)), errors="coerce")
            model = pd.to_numeric(frame.get("delta", pd.Series(index=frame.index, dtype=float)), errors="coerce")
            delta = vendor.combine_first(model)
            iv = pd.to_numeric(frame.get("iv", frame.get("impliedVolatility")), errors="coerce")
            mask = delta.notna() & iv.between(.01, 5)
            fig.add_trace(go.Scatter(x=delta[mask], y=iv[mask], mode="markers", name=label, marker=dict(color=color, size=7, opacity=.75)))
        fig.update_xaxes(title="Delta (vendor prioritaire, modèle en repli)")
        fig.update_yaxes(title="IV", tickformat=".0%")
        st.plotly_chart(fig, width="stretch")
        st.caption("Risk reversal 25Δ = IV put − IV call. Butterfly 25Δ = moyenne des wings − ATM. Les conventions sont affichées pour éviter toute ambiguïté.")
    with regime_tab:
        term = term_structure(surface, spot)
        if term.empty:
            st.info("Historique/terme insuffisant. L'IV Rank exige une série historique normalisée et n'est pas simulé à partir d'un seul snapshot.")
        else:
            term["total_variance"] = term["atm_iv"] ** 2 * term["dte"] / 365
            fig = _figure("Total variance par échéance")
            fig.add_trace(go.Scatter(x=term["dte"], y=term["total_variance"], mode="lines+markers", line=dict(color=PURPLE, width=3), name="σ²T"))
            st.plotly_chart(fig, width="stretch")
            st.dataframe(term, width="stretch", hide_index=True)
        st.warning("IV Rank / percentile non affiché tant qu'un historique de snapshots fiable n'est pas persisté. Une valeur fabriquée ici serait trompeuse.")
    with scenario_tab:
        iv = _num(skew.get("atm_iv") or metrics.get("atm_iv"))
        dte = int(_num(metrics.get("dte"), 1) or 1)
        if iv is None:
            st.info("IV indisponible pour construire la carte.")
        else:
            moves = np.array([-2, -1, 0, 1, 2], dtype=float)
            horizons = np.array([1, min(5, dte), min(10, dte), dte], dtype=int)
            horizons = np.unique(np.maximum(horizons, 1))
            matrix = []
            for horizon in horizons:
                sigma_move = spot * iv * math.sqrt(horizon / 365)
                matrix.append([spot + multiple * sigma_move for multiple in moves])
            heat = _figure("Spot bands sous diffusion lognormale locale", 390)
            heat.add_trace(go.Heatmap(z=np.array(matrix), x=[f"{m:+.0f}σ" for m in moves], y=[f"{h}j" for h in horizons], colorscale="RdYlGn", text=np.round(matrix, 2), texttemplate="%{text}"))
            st.plotly_chart(heat, width="stretch")
            st.caption("Carte de repères, pas distribution prédictive : IV plate, pas de jumps ni recalibration du smile.")


def render_gamma_workspace(
    metrics: Mapping[str, Any],
    spot: float,
    calls: pd.DataFrame,
    puts: pd.DataFrame,
    window_pct: float,
    data_context: Optional[Mapping[str, Any]],
) -> None:
    st.subheader("Gamma & Greeks Positioning")
    render_data_provenance(data_context, compact=True)
    options = {
        "Concentration seulement — aucun signe dealer": "concentration",
        "Hypothèse calls + / puts −": "calls_plus_puts_minus",
        "Hypothèse calls − / puts +": "calls_minus_puts_plus",
    }
    choice = st.selectbox("Convention d'inventaire", list(options), help="Le flux OPRA/OI ne révèle pas l'inventaire dealer. Le signe doit donc rester une hypothèse explicite.")
    assumption = options[choice]
    gamma = gamma_exposure_by_strike(calls, puts, spot, assumption)
    if gamma.empty:
        st.info("Gamma indisponible.")
        return
    view = gamma[(gamma["strike"] >= spot * (1 - window_pct)) & (gamma["strike"] <= spot * (1 + window_pct))].copy()
    total_abs = float(view["absolute_exposure"].sum())
    peak = view.loc[view["absolute_exposure"].idxmax()] if not view.empty else pd.Series(dtype=float)
    signed = float(view["exposure"].sum()) if assumption != "concentration" else None
    _metric_row([
        ("Absolute gamma concentration", _large(total_abs), "$ per 1% spot proxy"),
        ("Peak strike", _price(peak.get("strike")), _large(peak.get("absolute_exposure"))),
        ("Signed scenario", _large(signed), "N/A sans hypothèse" if signed is None else choice),
        ("Spot → peak", _pct(_num(peak.get("strike"), spot) / spot - 1 if spot else None), "distance"),
    ])
    fig = _figure("Gamma exposure cross-section")
    y = view["absolute_exposure"] if assumption == "concentration" else view["exposure"]
    colors = [GREEN if value >= 0 else RED for value in y]
    fig.add_trace(go.Bar(x=view["strike"], y=y, marker_color=colors, name="Gamma"))
    fig.add_vline(x=spot, line_color=CYAN, line_dash="dash", annotation_text="Spot")
    fig.update_yaxes(title="$ gamma proxy pour 1% de spot")
    st.plotly_chart(fig, width="stretch")
    if assumption == "concentration":
        st.success("Mode factuel : localisation de la convexité, sans conclure que les dealers sont longs ou shorts gamma.")
    else:
        st.warning("Scénario hypothétique uniquement. Pour une inférence directionnelle plus solide, il faut au minimum open/close, customer/firm/MM et historique d'inventaire.")
    greek_rows = []
    for greek in ("delta", "gamma", "vega", "theta"):
        values = []
        for frame in (calls, puts):
            if frame is None or frame.empty:
                continue
            vendor = pd.to_numeric(frame.get(f"{greek}_vendor", pd.Series(index=frame.index, dtype=float)), errors="coerce")
            model = pd.to_numeric(frame.get(greek, pd.Series(index=frame.index, dtype=float)), errors="coerce")
            effective = vendor.combine_first(model)
            oi = pd.to_numeric(frame.get("openInterest", 0), errors="coerce").fillna(0)
            values.append(float((effective.fillna(0) * oi * 100).sum()))
        greek_rows.append({"Greek": greek.title(), "OI-weighted magnitude": sum(values), "Usage": {"Delta": "hedge directionnel local", "Gamma": "variation du delta", "Vega": "sensibilité IV", "Theta": "carry journalier"}[greek.title()]})
    st.dataframe(pd.DataFrame(greek_rows), width="stretch", hide_index=True)
    st.caption("Pour l'analyse complète des 11 Greeks, leurs courbes, heatmaps et contributions par jambe, utiliser le Greek Intelligence Center de Strategy Lab.")


def render_futures_workspace(
    ticker: str,
    price_data: pd.DataFrame,
    macro_df: pd.DataFrame,
    macro_summary: Mapping[str, Any],
    futures_curve: pd.DataFrame,
    futures_context: Optional[Mapping[str, Any]],
    product_code: str,
) -> None:
    st.subheader("Futures Curve, Carry & Macro")
    render_data_provenance(futures_context, compact=True)
    ctx = dict(futures_context or {})
    provider = str(ctx.get("provider") or "Source inconnue")
    recency = str(ctx.get("recency") or "UNKNOWN").upper()
    public_fallback = "YAHOO" in provider.upper() or str(ctx.get("status") or "").lower() == "fallback"

    curve_tab, cross_tab, risk_tab = st.tabs(["Contract curve", "Cross-asset tape", "Basis & risk"])
    with curve_tab:
        if futures_curve is None or futures_curve.empty:
            st.warning(
                f"Courbe {product_code} indisponible via les providers configurés. "
                "Le Cross-asset tape reste indépendant et peut continuer à utiliser les proxies publics."
            )
        else:
            curve = futures_curve.copy()
            curve["mark"] = pd.to_numeric(curve.get("mark"), errors="coerce")
            valid_curve = curve.dropna(subset=["mark"]).copy()
            if valid_curve.empty:
                st.warning(f"Courbe {product_code} reçue mais aucun mark exploitable n'est disponible.")
            else:
                if "last_trade_date" in valid_curve.columns and pd.to_datetime(valid_curve["last_trade_date"], errors="coerce").notna().any():
                    sort_col = "last_trade_date"
                    valid_curve[sort_col] = pd.to_datetime(valid_curve[sort_col], errors="coerce")
                    x_title = "Last trade date"
                elif "contract_month" in valid_curve.columns:
                    sort_col = "contract_month"
                    valid_curve[sort_col] = pd.to_datetime(valid_curve[sort_col], errors="coerce")
                    x_title = "Contract month (public fallback)"
                else:
                    sort_col = "ticker"
                    x_title = "Contract"
                valid_curve = valid_curve.sort_values(sort_col, na_position="last").reset_index(drop=True)
                front = valid_curve.iloc[0]
                back = valid_curve.iloc[-1]
                front_mark = _num(front.get("mark"))
                back_mark = _num(back.get("mark"))
                if front_mark is not None and back_mark is not None:
                    if back_mark > front_mark:
                        state = "Contango"
                    elif back_mark < front_mark:
                        state = "Backwardation"
                    else:
                        state = "Flat"
                    back_front = back_mark / front_mark - 1.0 if front_mark else None
                else:
                    state, back_front = "N/A", None

                bid = _num(front.get("bid"))
                ask = _num(front.get("ask"))
                front_spread = ask - bid if bid is not None and ask is not None and ask >= bid else None
                volume_note = "public bar" if public_fallback else "session"
                spread_note = "non disponible en fallback public" if front_spread is None else "absolute"
                _metric_row([
                    ("Front", str(front.get("ticker", "N/A")), _price(front_mark)),
                    ("Curve regime", state, f"back/front {_pct(back_front)}"),
                    ("Front volume", _large(front.get("volume")), volume_note),
                    ("Front spread", _price(front_spread), spread_note),
                ])

                fig = _figure(f"{product_code} futures term curve")
                x_values = valid_curve[sort_col] if sort_col in valid_curve.columns else valid_curve["ticker"]
                fig.add_trace(go.Scatter(
                    x=x_values,
                    y=valid_curve["mark"],
                    mode="lines+markers+text",
                    text=valid_curve["ticker"],
                    textposition="top center",
                    line=dict(color=CYAN, width=3),
                    name="Mark",
                ))
                fig.update_xaxes(title=x_title)
                fig.update_yaxes(title="Futures mark")
                st.plotly_chart(fig, width="stretch")

                display = [
                    "ticker", "contract_month", "last_trade_date", "days_to_maturity", "curve_tenor_days",
                    "bid", "ask", "mark", "settlement", "previous_close", "volume", "change", "change_percent",
                    "vs_front_pct", "annualized_roll_pct", "tick_size", "trading_venue", "mark_source",
                ]
                st.dataframe(valid_curve[[column for column in display if column in valid_curve.columns]], width="stretch", hide_index=True)

                if public_fallback:
                    st.warning(
                        "Fallback public Yahoo actif : la courbe utilise des contrats individuels et des marks publics retardés. "
                        "Ce ne sont ni des NBBO exécutables ni des settlements officiels. Les dates exactes Last Trade / First Notice "
                        "ne sont pas inventées lorsqu'elles ne sont pas fournies. `annualized_roll_pct` est une pente de courbe "
                        "annualisée entre mois de contrat, pas un roll yield réalisé."
                    )
                else:
                    st.caption(
                        "Carry annualisé = pente mécanique mark/front ramenée à 365 jours; hors funding, convexité, "
                        "roll calendar et spécifications produit."
                    )

    with cross_tab:
        if macro_df is None or macro_df.empty:
            st.info("Tape cross-asset indisponible.")
        else:
            _metric_row([
                ("Macro regime", str(macro_summary.get("tape_state", "N/A")), f"score {_num(macro_summary.get('tape_score'), 50):.0f}/100"),
                ("Instruments", f"{len(macro_df):,}", "futures + ETF/index proxies"),
                ("Pressure", str(sum(macro_df.get("Regime", pd.Series(dtype=str)).eq("Pression"))), "facteurs"),
            ])
            st.dataframe(macro_df, width="stretch", hide_index=True, height=500)
            st.caption("Les proxies ne sont pas la courbe futures. Ils servent uniquement à la confirmation cross-asset.")

    with risk_tab:
        st.markdown("#### Basis and roll checklist")
        if public_fallback:
            checklist = pd.DataFrame([
                ("Contract identification", "Ticker individuel et mois de contrat", "Yahoo + mapping produit local"),
                ("Executable mark", "NBBO midpoint / tailles", "NON DISPONIBLE — mark public retardé"),
                ("Official settlement", "Settlement exchange", "NON REVENDIQUÉ dans le fallback"),
                ("Curve", "Front/deferred public marks", "Disponible — delayed/public"),
                ("Basis", "Futures − cash adjusted for carry", "Requires matched cash/index + rates/dividends"),
                ("Roll", "Calendar spread, liquidity migration, roll window", "Pente mois-contrat seulement; historique requis"),
                ("Margin", "SPAN 2 / broker house add-ons", "Not available in market-data API"),
            ], columns=["Control", "Definition", "Status / source"])
        else:
            checklist = pd.DataFrame([
                ("Contract specification", "Multiplier, tick, venue, last trade date", "Massive contracts"),
                ("Executable mark", "NBBO midpoint; last trade only as fallback", "Massive snapshot"),
                ("Curve", "Front/deferred marks and slope", "Computed"),
                ("Basis", "Futures − cash adjusted for carry", "Requires matched cash/index + rates/dividends"),
                ("Roll", "Calendar spread, liquidity migration, roll window", "Needs historical snapshots"),
                ("Margin", "SPAN 2 / broker house add-ons", "Not available in market-data API"),
            ], columns=["Control", "Definition", "Status / source"])
        st.dataframe(checklist, width="stretch", hide_index=True)
        st.warning(
            "Aucun chiffre de marge TIMS/SPAN n'est inventé. Le calcul exige les paramètres du clearing/broker "
            "et la composition exacte du portefeuille."
        )

def build_export_package(
    ticker: str,
    expiration: str,
    metrics: Mapping[str, Any],
    calls: pd.DataFrame,
    puts: pd.DataFrame,
    surface: pd.DataFrame,
    macro_df: pd.DataFrame,
    futures_curve: pd.DataFrame,
    data_context: Optional[Mapping[str, Any]],
    futures_context: Optional[Mapping[str, Any]],
) -> Tuple[bytes, Dict[str, Any]]:
    created = datetime.now(timezone.utc).isoformat()
    manifest: Dict[str, Any] = {
        "schema_version": "2.0",
        "created_at_utc": created,
        "ticker": ticker,
        "expiration": expiration,
        "models": {
            "chain": "vendor quotes + normalized cross-section",
            "greeks": "vendor when present; Black-Scholes proxy fallback",
            "dealer_gamma": "not asserted; scenario convention only",
            "surface": "observed descriptive points; not arbitrage-free calibrated",
        },
        "options_data": dict(data_context or {}),
        "futures_data": dict(futures_context or {}),
        "files": {},
    }
    buffers: Dict[str, bytes] = {}
    frames = {
        "options_calls.csv": calls,
        "options_puts.csv": puts,
        "vol_surface.csv": surface,
        "macro_tape.csv": macro_df,
        "futures_curve.csv": futures_curve,
    }
    for name, frame in frames.items():
        if frame is not None and not frame.empty:
            buffers[name] = frame.to_csv(index=False).encode("utf-8")
    summary = {key: (value if np.isscalar(value) and not isinstance(value, (pd.DataFrame, pd.Series)) else None) for key, value in dict(metrics).items()}
    buffers["analytics_summary.json"] = json.dumps(summary, indent=2, default=str, allow_nan=False).encode("utf-8")
    readme = (
        "Quant Terminal — Derivatives Evidence Package\n\n"
        "This archive is an analysis snapshot, not an order or investment recommendation.\n"
        "Open interest is prior-end-of-day and directionless. Signed dealer gamma is never asserted.\n"
        "Inspect manifest.json for source, recency, model conventions and SHA-256 hashes.\n"
    ).encode("utf-8")
    buffers["README.txt"] = readme
    for name, payload in buffers.items():
        manifest["files"][name] = {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
    manifest_payload = json.dumps(manifest, indent=2, default=str).encode("utf-8")
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, payload in buffers.items():
            bundle.writestr(name, payload)
        bundle.writestr("manifest.json", manifest_payload)
    return archive.getvalue(), manifest


def render_export_workspace(
    ticker: str,
    expiration: str,
    metrics: Mapping[str, Any],
    calls: pd.DataFrame,
    puts: pd.DataFrame,
    surface: pd.DataFrame,
    macro_df: pd.DataFrame,
    futures_curve: pd.DataFrame,
    data_context: Optional[Mapping[str, Any]],
    futures_context: Optional[Mapping[str, Any]],
) -> None:
    st.subheader("Export, Provenance & Audit Trail")
    render_data_provenance(data_context)
    package, manifest = build_export_package(ticker, expiration, metrics, calls, puts, surface, macro_df, futures_curve, data_context, futures_context)
    _metric_row([
        ("Package", f"{len(package) / 1024:.1f} KB", "ZIP compressed"),
        ("Artifacts", str(len(manifest["files"]) + 1), "manifest included"),
        ("Schema", str(manifest["schema_version"]), "versioned"),
        ("Integrity", "SHA-256", "per artifact"),
    ])
    st.download_button(
        "Télécharger le package institutionnel (.zip)",
        data=package,
        file_name=f"derivatives_evidence_{ticker}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.zip",
        mime="application/zip",
        type="primary",
    )
    meta_tab, files_tab, caveat_tab = st.tabs(["Run manifest", "Artifacts", "Model governance"])
    with meta_tab:
        st.json({key: value for key, value in manifest.items() if key != "files"}, expanded=False)
    with files_tab:
        table = pd.DataFrame([{"Artifact": name, **metadata} for name, metadata in manifest["files"].items()])
        st.dataframe(table, width="stretch", hide_index=True)
    with caveat_tab:
        st.markdown(
            "- Snapshot reproductibility requires the same licensed source and timestamp.\n"
            "- OPRA quotes/trades do not reveal customer direction or dealer inventory.\n"
            "- Vendor Greeks and model proxies are stored in separate columns.\n"
            "- Surface points are descriptive until a calibrated arbitrage-free model is enabled.\n"
            "- Margin, borrow, dividends, early exercise and commissions require portfolio/broker inputs."
        )

