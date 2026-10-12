"""Decision-first Streamlit workspace for the institutional backtest stack.

The numerical engines deliberately stay outside this module.  This file only
turns their outputs into a short, auditable workflow: decision, performance,
executions, validation and evidence.  Raw tables remain available as drill
downs, but they are never the first thing a user has to interpret.
"""
from __future__ import annotations

from dataclasses import asdict
from html import escape
import json
import re
from typing import Any, Mapping

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st


_PUBLIC_VERSION = re.compile(r"\s*[Vv]\d+(?:\.\d+)*(?:[A-Za-z])?\b")
_GATE_LABELS = {
    "Point-in-time data contract": "Contrat point-in-time",
    "Market-data integrity & capabilities": "Intégrité et capacités des données",
    "Canonical event ledger": "Ledger d’exécution canonique",
    "Risk-order event replay": "Rejeu des ordres de risque",
    "Custom-signal availability provenance": "Disponibilité et provenance du signal",
    "Executed capital integrity": "Intégrité du capital exécuté",
    "Probabilistic Sharpe": "Significativité du Sharpe",
    "Candidate trial provenance": "Provenance des essais candidats",
    "Deflated Sharpe": "Sharpe déflaté",
    "Selection overfit": "Surapprentissage de sélection",
    "Data-snooping controls": "Contrôles de data-snooping",
    "Purged CPCV out-of-sample": "Validation purgée hors-échantillon",
    "Scenario resilience": "Résilience aux scénarios",
}


def public_label(value: Any) -> str:
    """Remove implementation-version tokens from user-facing labels."""

    text = str(value or "")
    text = _PUBLIC_VERSION.sub("", text)
    return re.sub(r"\s{2,}", " ", text).strip(" ·—-")


def _gate_label(value: Any) -> str:
    clean = public_label(value)
    return _GATE_LABELS.get(clean, clean)


def _number(value: Any, default: float = np.nan) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(default)
    return number if np.isfinite(number) else float(default)


def _pct(value: Any, digits: int = 1) -> str:
    number = _number(value)
    return "—" if not np.isfinite(number) else f"{number:.{digits}%}"


def _num(value: Any, digits: int = 2) -> str:
    number = _number(value)
    return "—" if not np.isfinite(number) else f"{number:.{digits}f}"


def _money(value: Any) -> str:
    number = _number(value)
    return "—" if not np.isfinite(number) else f"${number:,.0f}"


def _observations(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if np.isinf(number):
        return "∞"
    return "—" if not np.isfinite(number) else f"{number:.0f}"


def decision_view(decision: Any) -> dict[str, str]:
    """Map the machine gate to one stable, non-promotional public verdict."""

    raw = str(decision or "HOLD — DATA REQUIRED").upper()
    if raw == "RESEARCH APPROVED":
        return {
            "label": "APPROUVÉ POUR RECHERCHE",
            "tone": "pass",
            "read": "Les contrôles requis sont satisfaits pour poursuivre le protocole de recherche.",
        }
    if raw == "CONDITIONAL REVIEW":
        return {
            "label": "REVUE CONDITIONNELLE",
            "tone": "warn",
            "read": "Le résultat reste exploitable en recherche, sous réserve des contrôles signalés.",
        }
    if raw == "REJECT / REDESIGN":
        return {
            "label": "À RECONCEVOIR",
            "tone": "fail",
            "read": "Au moins un contrôle invalide l’hypothèse sous sa forme actuelle.",
        }
    return {
        "label": "PREUVES REQUISES",
        "tone": "hold",
        "read": "Le moteur reste fermé tant que les preuves bloquantes ne sont pas disponibles.",
    }


def gate_cards(summary: Mapping[str, Any] | None) -> list[dict[str, str]]:
    """Return normalized gate cards for UI rendering and contract tests."""

    summary = dict(summary or {})
    checks = summary.get("checks")
    if not isinstance(checks, list):
        checks = []
    cards: list[dict[str, str]] = []
    for item in checks:
        if not isinstance(item, Mapping):
            continue
        state = str(item.get("state") or "UNAVAILABLE").upper()
        tone = (
            "pass"
            if state == "PASS"
            else "warn"
            if state in {"WARN", "PARTIAL"}
            else "fail"
            if state == "FAIL"
            else "hold"
        )
        cards.append(
            {
                "label": _gate_label(item.get("gate") or "Contrôle"),
                "state": state,
                "detail": public_label(item.get("detail") or "Aucune preuve fournie"),
                "tone": tone,
            }
        )
    if cards:
        return cards
    state = "UNAVAILABLE" if summary.get("fail_closed", True) else "WARN"
    return [
        {
            "label": "Moteur institutionnel",
            "state": state,
            "detail": public_label(
                summary.get("engine_error") or "Preuve institutionnelle indisponible"
            ),
            "tone": "hold",
        }
    ]


def authoritative_snapshot(
    institutional: Any,
    fallback_frame: pd.DataFrame,
    periods_per_year: int,
) -> dict[str, Any]:
    """Compute display metrics from the executed ledger whenever available."""

    source = "diagnostic de référence"
    daily = pd.DataFrame()
    if institutional is not None:
        candidate = getattr(getattr(institutional, "execution", None), "daily", None)
        if isinstance(candidate, pd.DataFrame) and not candidate.empty:
            daily = candidate.copy()
            source = "ledger exécuté"

    if daily.empty:
        daily = (
            fallback_frame.copy()
            if isinstance(fallback_frame, pd.DataFrame)
            else pd.DataFrame()
        )

    nav_column = "nav" if "nav" in daily else "equity" if "equity" in daily else ""
    return_column = (
        "return"
        if "return" in daily
        else "strategy_return"
        if "strategy_return" in daily
        else ""
    )
    nav = pd.to_numeric(
        daily.get(nav_column, pd.Series(dtype=float)), errors="coerce"
    ).dropna()
    returns = pd.to_numeric(
        daily.get(return_column, pd.Series(dtype=float)), errors="coerce"
    ).dropna()

    total_return = (
        nav.iloc[-1] / nav.iloc[0] - 1.0
        if len(nav) >= 2 and nav.iloc[0] != 0
        else np.nan
    )
    drawdown = nav / nav.cummax() - 1.0 if not nav.empty else pd.Series(dtype=float)
    volatility = (
        returns.std(ddof=1) * np.sqrt(max(int(periods_per_year), 1))
        if len(returns) > 1
        else np.nan
    )
    sharpe = (
        returns.mean() / returns.std(ddof=1) * np.sqrt(max(int(periods_per_year), 1))
        if len(returns) > 1 and returns.std(ddof=1) > 0
        else np.nan
    )
    return {
        "daily": daily,
        "nav": nav,
        "returns": returns,
        "drawdown": drawdown,
        "total_return": total_return,
        "max_drawdown": drawdown.min() if not drawdown.empty else np.nan,
        "volatility": volatility,
        "sharpe": sharpe,
        "source": source,
    }


def _inject_css() -> None:
    st.markdown(
        """
        <style>
        .btw-shell{border:1px solid rgba(148,163,184,.18);border-radius:18px;padding:22px 24px;
          background:linear-gradient(135deg,rgba(9,16,29,.98),rgba(12,24,40,.94));margin:.25rem 0 1rem}
        .btw-kicker{font-size:.72rem;letter-spacing:.16em;text-transform:uppercase;color:#67e8f9;font-weight:800}
        .btw-title{font-size:1.72rem;line-height:1.15;font-weight:760;color:#f8fafc;margin:.35rem 0}
        .btw-sub{color:#94a3b8;font-size:.9rem;max-width:76rem}
        .btw-meta{display:flex;flex-wrap:wrap;gap:.5rem;margin-top:1rem}
        .btw-pill{border:1px solid rgba(148,163,184,.22);border-radius:999px;padding:.32rem .62rem;
          color:#cbd5e1;background:rgba(15,23,42,.62);font-size:.72rem}
        .btw-verdict{border:1px solid rgba(148,163,184,.18);border-left:4px solid #64748b;border-radius:14px;
          background:rgba(15,23,42,.72);padding:16px 18px;margin:.5rem 0 1rem}
        .btw-verdict.pass{border-left-color:#34d399}.btw-verdict.warn{border-left-color:#fbbf24}
        .btw-verdict.fail{border-left-color:#fb7185}.btw-verdict.hold{border-left-color:#38bdf8}
        .btw-verdict-label{font-size:1.15rem;color:#f8fafc;font-weight:780}.btw-verdict-read{color:#aebbd0;font-size:.84rem;margin-top:.25rem}
        .btw-grid{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:.65rem;margin:.55rem 0 1rem}
        .btw-kpi{border:1px solid rgba(148,163,184,.16);border-radius:12px;padding:12px 13px;background:rgba(15,23,42,.68);min-height:88px}
        .btw-kpi-label{font-size:.66rem;text-transform:uppercase;letter-spacing:.08em;color:#7f91aa}
        .btw-kpi-value{font-size:1.2rem;color:#f8fafc;font-weight:740;margin:.32rem 0}.btw-kpi-note{font-size:.68rem;color:#8291a8}
        .btw-gates{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:.7rem;margin:.5rem 0 1rem}
        .btw-gate{border:1px solid rgba(148,163,184,.16);border-top:3px solid #64748b;border-radius:12px;padding:13px;background:rgba(15,23,42,.62)}
        .btw-gate.pass{border-top-color:#34d399}.btw-gate.warn{border-top-color:#fbbf24}
        .btw-gate.fail{border-top-color:#fb7185}.btw-gate.hold{border-top-color:#38bdf8}
        .btw-gate-head{display:flex;justify-content:space-between;gap:.5rem;color:#e2e8f0;font-size:.78rem;font-weight:720}
        .btw-gate-state{font-size:.63rem;letter-spacing:.08em;color:#93c5fd}.btw-gate-detail{font-size:.7rem;color:#8fa0b7;margin-top:.45rem;line-height:1.35}
        .btw-section{font-size:.72rem;text-transform:uppercase;letter-spacing:.12em;color:#67e8f9;font-weight:760;margin:.55rem 0 .25rem}
        div[data-testid="stTabs"] button[role="tab"]{font-weight:700;letter-spacing:.01em;padding-left:1rem;padding-right:1rem}
        @media(max-width:1100px){.btw-grid{grid-template-columns:repeat(3,1fr)}.btw-gates{grid-template-columns:repeat(2,1fr)}}
        @media(max-width:720px){.btw-shell{padding:17px}.btw-title{font-size:1.35rem}.btw-grid{grid-template-columns:repeat(2,1fr)}.btw-gates{grid-template-columns:1fr}}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _kpis(items: list[tuple[str, str, str]]) -> None:
    cells = "".join(
        "<div class='btw-kpi'><div class='btw-kpi-label'>{}</div><div class='btw-kpi-value'>{}</div><div class='btw-kpi-note'>{}</div></div>".format(
            escape(public_label(label)), escape(str(value)), escape(public_label(note))
        )
        for label, value, note in items[:6]
    )
    st.markdown(f"<div class='btw-grid'>{cells}</div>", unsafe_allow_html=True)


def _gate_grid(cards: list[dict[str, str]]) -> None:
    cells = "".join(
        "<div class='btw-gate {tone}'><div class='btw-gate-head'><span>{label}</span><span class='btw-gate-state'>{state}</span></div><div class='btw-gate-detail'>{detail}</div></div>".format(
            tone=escape(item["tone"]),
            label=escape(item["label"]),
            state=escape(item["state"]),
            detail=escape(item["detail"]),
        )
        for item in cards
    )
    st.markdown(f"<div class='btw-gates'>{cells}</div>", unsafe_allow_html=True)


def _layout(title: str = "") -> dict[str, Any]:
    return {
        "template": "plotly_dark",
        "height": 390,
        "margin": dict(l=18, r=18, t=46 if title else 24, b=28),
        "title": title,
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": "rgba(9,16,29,.35)",
        "hovermode": "x unified",
        "legend": dict(orientation="h", y=1.08, x=0),
    }


def _equity_figure(
    snapshot: Mapping[str, Any], bt: pd.DataFrame, benchmark_label: str
) -> go.Figure:
    fig = go.Figure()
    nav = snapshot.get("nav")
    if isinstance(nav, pd.Series) and not nav.empty:
        normalized = nav / nav.iloc[0] * 100.0
        fig.add_trace(
            go.Scatter(
                x=normalized.index,
                y=normalized,
                name="Stratégie · ledger",
                line=dict(color="#67e8f9", width=2.6),
            )
        )
    if (
        isinstance(bt, pd.DataFrame)
        and "benchmark" in bt
        and not bt["benchmark"].dropna().empty
    ):
        bench = pd.to_numeric(bt["benchmark"], errors="coerce").dropna()
        bench = bench / bench.iloc[0] * 100.0
        fig.add_trace(
            go.Scatter(
                x=bench.index,
                y=bench,
                name=public_label(benchmark_label),
                line=dict(color="#94a3b8", width=1.6, dash="dot"),
            )
        )
    fig.update_layout(**_layout("Capital normalisé · base 100"), yaxis_title="Indice")
    return fig


def _drawdown_figure(snapshot: Mapping[str, Any]) -> go.Figure:
    drawdown = snapshot.get("drawdown")
    fig = go.Figure()
    if isinstance(drawdown, pd.Series) and not drawdown.empty:
        fig.add_trace(
            go.Scatter(
                x=drawdown.index,
                y=drawdown,
                name="Drawdown",
                fill="tozeroy",
                line=dict(color="#fb7185", width=1.4),
                fillcolor="rgba(251,113,133,.18)",
            )
        )
    fig.update_layout(**_layout("Trajectoire de drawdown"), yaxis_tickformat=".0%")
    return fig


def _monthly_figure(returns: pd.Series) -> go.Figure:
    fig = go.Figure()
    if isinstance(returns, pd.Series) and not returns.empty:
        monthly = (1.0 + returns).groupby(returns.index.to_period("M")).prod() - 1.0
        colors = np.where(monthly >= 0, "#34d399", "#fb7185")
        fig.add_trace(
            go.Bar(
                x=monthly.index.astype(str),
                y=monthly,
                marker_color=colors,
                name="Rendement mensuel",
            )
        )
    fig.update_layout(**_layout("Rendements mensuels nets"), yaxis_tickformat=".0%")
    return fig


def _rolling_quality_figure(returns: pd.Series, periods_per_year: int) -> go.Figure:
    fig = go.Figure()
    if isinstance(returns, pd.Series) and not returns.empty:
        window = max(10, int(round(periods_per_year / 4)))
        rolling_mean = returns.rolling(window).mean()
        rolling_std = returns.rolling(window).std(ddof=1)
        rolling_sharpe = rolling_mean.div(rolling_std.replace(0.0, np.nan)) * np.sqrt(
            max(periods_per_year, 1)
        )
        fig.add_trace(
            go.Scatter(
                x=rolling_sharpe.index,
                y=rolling_sharpe,
                name=f"Sharpe roulant · {window} périodes",
                line=dict(color="#a78bfa", width=2.0),
            )
        )
        fig.add_hline(y=0.0, line_color="rgba(248,250,252,.45)", line_width=1)
    fig.update_layout(
        **_layout("Stabilité du rendement ajusté du risque"), yaxis_title="Sharpe"
    )
    return fig


def _trade_figure(trades: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    if not isinstance(trades, pd.DataFrame) or trades.empty:
        fig.update_layout(**_layout("Distribution des transactions"))
        return fig
    candidate = next(
        (
            name
            for name in ["Net Return", "Return", "PnL %", "Trade Return"]
            if name in trades.columns
        ),
        "",
    )
    if candidate:
        values = pd.to_numeric(trades[candidate], errors="coerce").dropna()
        fig.add_trace(
            go.Histogram(
                x=values,
                nbinsx=min(30, max(8, int(np.sqrt(max(len(values), 1)) * 2))),
                marker_color="#67e8f9",
                opacity=0.82,
                name="Transactions",
            )
        )
        fig.add_vline(x=0, line_color="#f8fafc", line_width=1)
        fig.update_layout(
            **_layout("Distribution des rendements par transaction"),
            xaxis_tickformat=".1%",
        )
    else:
        fig.update_layout(**_layout("Distribution des transactions"))
    return fig


def _robustness_figure(cost_matrix: pd.DataFrame, wf_df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    if isinstance(cost_matrix, pd.DataFrame) and not cost_matrix.empty:
        x_col = next(
            (
                c
                for c in cost_matrix.columns
                if "cost" in str(c).lower() or "bps" in str(c).lower()
            ),
            cost_matrix.columns[0],
        )
        y_col = next(
            (
                c
                for c in cost_matrix.columns
                if "cagr" in str(c).lower() or "return" in str(c).lower()
            ),
            "",
        )
        if y_col:
            fig.add_trace(
                go.Scatter(
                    x=cost_matrix[x_col],
                    y=pd.to_numeric(cost_matrix[y_col], errors="coerce"),
                    mode="lines+markers",
                    name="Stress de coûts",
                    line=dict(color="#fbbf24", width=2),
                )
            )
    if not fig.data and isinstance(wf_df, pd.DataFrame) and not wf_df.empty:
        y_col = next(
            (
                c
                for c in wf_df.columns
                if "sharpe" in str(c).lower() or "return" in str(c).lower()
            ),
            "",
        )
        if y_col:
            fig.add_trace(
                go.Bar(
                    x=np.arange(1, len(wf_df) + 1),
                    y=pd.to_numeric(wf_df[y_col], errors="coerce"),
                    name="Fenêtres hors-échantillon",
                    marker_color="#a78bfa",
                )
            )
    fig.update_layout(**_layout("Sensibilité et robustesse"))
    return fig


def _render_evidence_configuration(
    *,
    bars: pd.DataFrame,
    result: dict[str, Any],
    cfg: Any,
    symbol: str,
    institutional: Any,
) -> None:
    from .dashboard import (
        _candidate_template,
        _commit_upload_widget,
        _factor_template,
        _horizon_options,
        _persisted_upload_name,
        _pit_manifest_template,
        _scalar_widget_kwargs,
        _upload_widget_key,
    )
    from .registry import data_hash

    legacy = result.get("data", pd.DataFrame())
    periods_per_year = int(
        getattr(cfg, "periods_per_year", 0)
        or bars.attrs.get("periods_per_year", 252)
        or 252
    )
    interval_label = str(
        getattr(cfg, "interval_label", "")
        or bars.attrs.get("interval_label", "1d")
        or "1d"
    )
    currency = str(
        getattr(cfg, "currency", "") or bars.attrs.get("currency", "") or "USD"
    ).upper()
    horizons = _horizon_options(periods_per_year)
    if st.session_state.get("bt_v70_horizon") not in horizons:
        st.session_state["bt_v70_horizon"] = min(
            horizons, key=lambda value: abs(value - periods_per_year)
        )

    with st.expander("Hypothèses d’exécution et preuves requises", expanded=False):
        st.caption(
            f"Contrat d’échantillonnage · {interval_label} · {periods_per_year} périodes/an · "
            f"base de prix {bars.attrs.get('price_basis', 'non spécifiée')} · exécution à la prochaine ouverture disponible."
        )
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.selectbox(
                "Modèle d’exécution",
                ["square_root", "volume_share", "almgren_chriss_proxy", "constant"],
                **_scalar_widget_kwargs("bt_v70_execution_model", "square_root"),
            )
            st.checkbox(
                "Déclaration point-in-time",
                help="Une déclaration seule ne constitue pas une preuve; un manifeste signé et lié au snapshot est requis.",
                **_scalar_widget_kwargs("bt_v70_point_in_time_self_attested", False),
            )
        with c2:
            st.number_input(
                "Spread (bps)",
                min_value=0.0,
                max_value=500.0,
                step=0.25,
                **_scalar_widget_kwargs("bt_v70_spread", 2.0),
            )
            st.number_input(
                "Coefficient d’impact",
                min_value=0.0,
                max_value=5.0,
                step=0.01,
                **_scalar_widget_kwargs("bt_v70_impact", 0.10),
            )
        with c3:
            st.slider(
                "Participation maximale",
                min_value=0.01,
                max_value=0.50,
                step=0.01,
                **_scalar_widget_kwargs("bt_v70_participation", 0.10),
            )
            st.number_input(
                "Coût d’emprunt de secours (bps)",
                min_value=0.0,
                max_value=5000.0,
                step=5.0,
                **_scalar_widget_kwargs("bt_v70_borrow", 0.0),
            )
        with c4:
            st.select_slider(
                "Trajectoires de scénario",
                options=[100, 250, 500, 800],
                **_scalar_widget_kwargs("bt_v70_paths", 250),
            )
            st.select_slider(
                "Horizon de scénario",
                options=horizons,
                **_scalar_widget_kwargs("bt_v70_horizon", periods_per_year),
            )

        s1, s2, s3 = st.columns(3)
        s1.number_input(
            "Graine de reproductibilité",
            min_value=1,
            max_value=1_000_000,
            step=1,
            **_scalar_widget_kwargs("bt_v70_seed", 41),
        )
        s2.selectbox(
            "Confiance de queue",
            [0.95, 0.975, 0.99],
            **_scalar_widget_kwargs("bt_v70_confidence", 0.975),
        )
        s3.slider(
            "Drawdown de stress inversé",
            min_value=-0.60,
            max_value=-0.05,
            step=0.01,
            **_scalar_widget_kwargs("bt_v70_reverse_dd", -0.20),
        )

        u1, u2, u3 = st.columns(3)
        pit_key = _upload_widget_key("bt_v70_pit_manifest")
        u1.file_uploader(
            "Manifeste point-in-time (JSON)",
            type=["json"],
            key=pit_key,
            on_change=_commit_upload_widget,
            args=("bt_v70_pit_manifest", pit_key),
        )
        candidate_key = _upload_widget_key("bt_v70_candidates")
        u2.file_uploader(
            "Famille complète de candidats (CSV)",
            type=["csv"],
            key=candidate_key,
            on_change=_commit_upload_widget,
            args=("bt_v70_candidates", candidate_key),
        )
        factor_key = _upload_widget_key("bt_v70_factors")
        u3.file_uploader(
            "Historique de facteurs (CSV)",
            type=["csv"],
            key=factor_key,
            on_change=_commit_upload_widget,
            args=("bt_v70_factors", factor_key),
        )
        st.checkbox(
            "Ledger d’essais déclaré complet",
            help="Seul un manifeste vérifiable peut satisfaire le contrôle.",
            **_scalar_widget_kwargs("bt_v70_candidates_self_attested", False),
        )

        template = _candidate_template(
            legacy.index,
            institutional.authoritative_returns if institutional is not None else None,
            frequency=interval_label,
            periods_per_year=periods_per_year,
            currency=currency,
            market_data_snapshot_hash=data_hash(bars),
        )
        factor_template = _factor_template(
            legacy.index,
            frequency=interval_label,
            periods_per_year=periods_per_year,
            currency=currency,
            market_data_snapshot_hash=data_hash(bars),
        )
        d1, d2, d3 = st.columns(3)
        d1.download_button(
            "Modèle de famille de candidats",
            data=template.to_csv(index=False).encode("utf-8"),
            file_name=f"{symbol}_candidate_family_template.csv",
            mime="text/csv",
            key="bt_evidence_candidate_template",
        )
        d2.download_button(
            "Modèle d’historique de facteurs",
            data=factor_template.to_csv(index=False).encode("utf-8"),
            file_name=f"{symbol}_factor_history_template.csv",
            mime="text/csv",
            key="bt_evidence_factor_template",
        )
        d3.download_button(
            "Brouillon de manifeste point-in-time",
            data=json.dumps(_pit_manifest_template(bars), indent=2).encode("utf-8"),
            file_name=f"{symbol}_pit_manifest_draft.json",
            mime="application/json",
            key="bt_evidence_pit_template",
        )
        persisted = [
            (
                "PIT",
                _persisted_upload_name(st.session_state.get("bt_v70_pit_manifest")),
            ),
            (
                "Candidats",
                _persisted_upload_name(st.session_state.get("bt_v70_candidates")),
            ),
            (
                "Facteurs",
                _persisted_upload_name(st.session_state.get("bt_v70_factors")),
            ),
        ]
        names = [f"{label}: {name}" for label, name in persisted if name]
        if names:
            st.caption("Preuves conservées · " + " · ".join(names))
        if st.button(
            "Appliquer ces hypothèses et relancer",
            type="primary",
            key="bt_apply_evidence_controls",
        ):
            st.session_state["bt_force_institutional_run"] = True
            st.rerun()


def _render_evidence(
    *,
    bars: pd.DataFrame,
    result: dict[str, Any],
    cfg: Any,
    symbol: str,
    institutional: Any,
    context: Mapping[str, Any] | None,
    engine_error: str,
) -> None:
    _render_evidence_configuration(
        bars=bars, result=result, cfg=cfg, symbol=symbol, institutional=institutional
    )
    context = dict(context or {})
    if engine_error:
        st.error(f"Moteur institutionnel indisponible · {public_label(engine_error)}")
    if context.get("candidate_error"):
        st.error(
            "Famille de candidats rejetée · " + public_label(context["candidate_error"])
        )
    if context.get("factor_error"):
        st.warning(
            "Historique de facteurs rejeté · " + public_label(context["factor_error"])
        )
    if institutional is None:
        st.info(
            "Le système reste fermé : aucun proxy ne peut remplacer le ledger exécuté."
        )
        return

    data_tab, execution_tab, statistics_tab, governance_tab = st.tabs(
        [
            "Données",
            "Exécution",
            "Statistiques",
            "Gouvernance",
        ]
    )
    with data_tab:
        fields = pd.DataFrame(
            [
                {
                    "Champ": public_label(name),
                    "État": item.state.value,
                    "Requis": item.required,
                    "Manquant": item.missing_ratio,
                    "Justification": public_label(item.reason),
                }
                for name, item in institutional.data_catalog.fields.items()
            ]
        )
        _kpis(
            [
                (
                    "Contrôle des données",
                    institutional.data_catalog.verdict.value,
                    "catalogue actif",
                ),
                (
                    "Point-in-time",
                    "VÉRIFIÉ"
                    if context.get("point_in_time_authenticated")
                    else "REQUIS",
                    "preuve signée",
                ),
                (
                    "Snapshot",
                    str(context.get("source_snapshot_id") or "—")[-12:],
                    "identifiant source",
                ),
                (
                    "Base de prix",
                    str(context.get("price_basis") or "non spécifiée"),
                    "contrat de prix",
                ),
            ]
        )
        with st.expander("Catalogue détaillé", expanded=False):
            st.dataframe(fields, width="stretch", hide_index=True)

    with execution_tab:
        diagnostics = institutional.execution.diagnostics
        _kpis(
            [
                (
                    "État du ledger",
                    institutional.execution.status.value,
                    "source autoritaire",
                ),
                (
                    "Taux de remplissage",
                    _pct(diagnostics.get("fill_ratio")),
                    "ordres exécutés",
                ),
                (
                    "Ordres partiels",
                    str(diagnostics.get("partial_orders", 0)),
                    "contrainte de liquidité",
                ),
                (
                    "Ordres rejetés",
                    str(diagnostics.get("rejected_orders", 0)),
                    "contrôles d’exécution",
                ),
                (
                    "Coûts totaux",
                    _money(diagnostics.get("total_cost")),
                    "commission, spread, impact",
                ),
                (
                    "Entrées causales",
                    "OUI" if diagnostics.get("causal_inputs_only") else "NON",
                    "aucun futur observé",
                ),
            ]
        )
        daily = institutional.execution.daily
        if isinstance(daily, pd.DataFrame) and not daily.empty and "nav" in daily:
            fig = go.Figure(
                go.Scatter(
                    x=daily.index,
                    y=daily["nav"],
                    line=dict(color="#67e8f9", width=2.4),
                    name="NAV exécutée",
                )
            )
            fig.update_layout(**_layout("NAV reconstruite depuis les fills"))
            st.plotly_chart(
                fig, width="stretch", key=f"bt_evidence_execution_nav__{symbol}"
            )
        fills = pd.DataFrame(institutional.execution.records()["fills"])
        with st.expander("Fills et ordres auditables", expanded=False):
            st.dataframe(fills.tail(250), width="stretch", hide_index=True)

    with statistics_tab:
        validation = institutional.validation
        certified = bool(validation.get("candidate_family_certified", False))
        _kpis(
            [
                ("Sharpe", _num(validation.get("sharpe")), "ledger exécuté"),
                (
                    "Probabilité de Sharpe",
                    _pct(validation.get("psr")),
                    "significativité",
                ),
                (
                    "Sharpe déflaté",
                    _pct(validation.get("dsr", {}).get("deflated_sharpe_probability"))
                    if certified
                    else "PREUVE REQUISE",
                    "biais de sélection",
                ),
                (
                    "Risque de surapprentissage",
                    _pct(validation.get("pbo", {}).get("pbo"))
                    if certified
                    else "PREUVE REQUISE",
                    "famille certifiée",
                ),
                (
                    "Candidats",
                    str(validation.get("candidate_count", 0)),
                    "famille déclarée",
                ),
                (
                    "Track record minimal",
                    _observations(validation.get("minimum_track_record_observations")),
                    "observations",
                ),
            ]
        )
        tests = pd.DataFrame(
            [
                {
                    "Contrôle": "Reality Check",
                    "Valeur": _pct(
                        validation.get("white_reality_check", {}).get("p_value")
                    )
                    if certified
                    else "PREUVE REQUISE",
                    "Usage": "performance maximale bootstrap",
                },
                {
                    "Contrôle": "Superior Predictive Ability",
                    "Valeur": _pct(validation.get("hansen_spa", {}).get("p_value"))
                    if certified
                    else "PREUVE REQUISE",
                    "Usage": "supériorité prédictive studentisée",
                },
                {
                    "Contrôle": "Validation purgée",
                    "Valeur": str(validation.get("cpcv_splits", 0))
                    if certified
                    else "PREUVE REQUISE",
                    "Usage": "chemins hors-échantillon",
                },
            ]
        )
        with st.expander("Méthodes et résultats détaillés", expanded=False):
            st.dataframe(tests, width="stretch", hide_index=True)

    with governance_tab:
        from .registry import ExperimentRegistry

        g1, g2 = st.columns(2)
        with g1:
            if st.button(
                "Enregistrer l’expérience immuable",
                type="primary",
                key="bt_register_experiment",
            ):
                path = ExperimentRegistry().persist(
                    institutional.manifest,
                    {
                        "decision": institutional.gate["decision"],
                        "model_card": institutional.model_card,
                        "data_verdict": institutional.data_catalog.verdict.value,
                        "execution": institutional.execution.diagnostics,
                        "validation": institutional.validation,
                        "scenario_summary": institutional.scenarios["summary"],
                    },
                )
                st.success(f"Expérience enregistrée · {path}")
        with g2:
            st.download_button(
                "Télécharger le dossier reproductible",
                data=institutional.bundle,
                file_name=f"{institutional.manifest.run_id}.zip",
                mime="application/zip",
                key="bt_download_repro_bundle",
                width="stretch",
            )
        _kpis(
            [
                ("Run ID", institutional.manifest.run_id[-12:], "identité immuable"),
                ("Source autoritaire", "LEDGER EXÉCUTÉ", "rendements nets"),
                ("Fermeture sécurisée", "ACTIVE", "preuves manquantes bloquantes"),
                ("Production", "NON AUTORISÉE", "recherche uniquement"),
            ]
        )
        with st.expander("Model card et manifeste", expanded=False):
            manifest = asdict(institutional.manifest)
            if isinstance(manifest.get("metadata"), dict):
                manifest["metadata"].pop("_bundle_evidence", None)
            st.json({"model_card": institutional.model_card, "manifest": manifest})


def render_backtest_workspace(
    *,
    ticker: str,
    bars: pd.DataFrame,
    result: dict[str, Any],
    cfg: Any,
    metrics: Mapping[str, Any],
    trades: pd.DataFrame,
    risk_events: pd.DataFrame,
    integrity: int,
    diagnostics: Mapping[str, Any],
    reasons: list[str],
    notes: list[str],
    cost_matrix: pd.DataFrame,
    sens_matrix: pd.DataFrame,
    wf_df: pd.DataFrame,
    comp_df: pd.DataFrame,
    institutional: Any,
    institutional_context: Mapping[str, Any] | None,
    engine_error: str,
) -> None:
    """Render the complete decision-first Backtest Lab workspace."""

    _inject_css()
    bt = result.get("data", pd.DataFrame())
    gate = dict(diagnostics.get("institutional_v7") or {})
    decision = decision_view(gate.get("decision"))
    periods = int(getattr(cfg, "periods_per_year", 252) or 252)
    snapshot = authoritative_snapshot(institutional, bt, periods)
    run_id = str(
        gate.get("run_id")
        or getattr(getattr(institutional, "manifest", None), "run_id", "")
    )
    as_of = (
        bt.index[-1].strftime("%Y-%m-%d")
        if isinstance(bt, pd.DataFrame)
        and not bt.empty
        and hasattr(bt.index[-1], "strftime")
        else "—"
    )
    source_raw = str(gate.get("authoritative_source") or snapshot["source"])
    source = (
        "LEDGER EXÉCUTÉ"
        if source_raw.lower().replace(" ", "_") == "execution_ledger"
        else source_raw.replace("_", " ").upper()
    )

    st.markdown(
        "<div class='btw-shell'><div class='btw-kicker'>Recherche uniquement · décision traçable</div>"
        f"<div class='btw-title'>Backtest Lab · {escape(str(ticker).upper())}</div>"
        "<div class='btw-sub'>Construire une hypothèse, mesurer son comportement net de coûts, la confronter aux contrôles de robustesse, puis conserver la preuve reproductible.</div>"
        "<div class='btw-meta'>"
        f"<span class='btw-pill'>Stratégie · {escape(public_label(getattr(cfg, 'strategy', '—')))}</span>"
        f"<span class='btw-pill'>Période · {escape(str(getattr(cfg, 'interval_label', '—')))}</span>"
        f"<span class='btw-pill'>Données au · {escape(as_of)}</span>"
        f"<span class='btw-pill'>Source · {escape(source)}</span>"
        f"<span class='btw-pill'>Run · {escape(run_id[-12:] if run_id else 'non enregistré')}</span>"
        "</div></div>",
        unsafe_allow_html=True,
    )

    blockers = [
        _gate_label(item)
        for item in gate.get("blocking_gates", [])
        if str(item).strip()
    ]
    blocker_text = " · ".join(blockers[:3]) if blockers else "Aucun contrôle bloquant"
    st.markdown(
        f"<div class='btw-verdict {decision['tone']}'><div class='btw-verdict-label'>{escape(decision['label'])}</div>"
        f"<div class='btw-verdict-read'>{escape(decision['read'])} Blocage principal : {escape(blocker_text)}.</div></div>",
        unsafe_allow_html=True,
    )

    validation = (
        getattr(institutional, "validation", {}) if institutional is not None else {}
    )
    candidate_certified = (
        bool(validation.get("candidate_family_certified", False))
        if isinstance(validation, Mapping)
        else False
    )
    _kpis(
        [
            ("Rendement net", _pct(snapshot["total_return"]), snapshot["source"]),
            ("Sharpe", _num(snapshot["sharpe"]), "annualisé"),
            ("Drawdown maximal", _pct(snapshot["max_drawdown"]), "capital exécuté"),
            ("Volatilité", _pct(snapshot["volatility"]), "annualisée"),
            (
                "Surapprentissage",
                _pct(validation.get("pbo", {}).get("pbo"))
                if candidate_certified
                else "PREUVE REQUISE",
                "famille de candidats",
            ),
            ("Intégrité", f"{int(integrity)}/100", "diagnostic complémentaire"),
        ]
    )

    summary_tab, results_tab, trades_tab, validation_tab, evidence_tab = st.tabs(
        [
            "Synthèse",
            "Résultats",
            "Transactions",
            "Validation",
            "Preuves",
        ]
    )

    with summary_tab:
        st.markdown(
            "<div class='btw-section'>Lecture de décision</div>", unsafe_allow_html=True
        )
        c1, c2 = st.columns([1.55, 1])
        with c1:
            st.plotly_chart(
                _equity_figure(
                    snapshot, bt, str(metrics.get("Benchmark Label", "Benchmark"))
                ),
                width="stretch",
                key=f"bt_summary_equity__{ticker}",
            )
        with c2:
            st.plotly_chart(
                _drawdown_figure(snapshot),
                width="stretch",
                key=f"bt_summary_drawdown__{ticker}",
            )
        _gate_grid(gate_cards(gate)[:6])
        next_actions = blockers[:3] or ["Conserver le run et lancer la revue humaine"]
        st.info("Prochaine action · " + " · ".join(next_actions))
        with st.expander("Hypothèse exécutée", expanded=False):
            st.markdown(
                f"**Stratégie** · {public_label(getattr(cfg, 'strategy', '—'))}  \n"
                f"**Benchmark** · {public_label(metrics.get('Benchmark Label', '—'))}  \n"
                f"**Exposition cible** · {_pct(_number(getattr(cfg, 'position_pct', 0)) / 100.0)}  \n"
                f"**Coût aller simple** · {_num(_number(getattr(cfg, 'fee_bps', 0)) + _number(getattr(cfg, 'slippage_bps', 0)), 1)} bps  \n"
                f"**Short** · {'autorisé' if getattr(cfg, 'allow_short', False) else 'désactivé'}"
            )

    with results_tab:
        r1, r2 = st.columns([1.55, 1])
        with r1:
            st.plotly_chart(
                _rolling_quality_figure(snapshot["returns"], periods),
                width="stretch",
                key=f"bt_results_rolling__{ticker}",
            )
        with r2:
            st.plotly_chart(
                _monthly_figure(snapshot["returns"]),
                width="stretch",
                key=f"bt_results_monthly__{ticker}",
            )
        if isinstance(comp_df, pd.DataFrame) and not comp_df.empty:
            strategy_col = next(
                (c for c in comp_df.columns if "strategy" in str(c).lower()),
                comp_df.columns[0],
            )
            score_col = next(
                (
                    c
                    for c in comp_df.columns
                    if "sharpe" in str(c).lower() or "return" in str(c).lower()
                ),
                "",
            )
            if score_col:
                compare = comp_df.copy().head(12)
                fig = go.Figure(
                    go.Bar(
                        x=compare[strategy_col].map(public_label),
                        y=pd.to_numeric(compare[score_col], errors="coerce"),
                        marker_color="#a78bfa",
                        name=public_label(score_col),
                    )
                )
                fig.update_layout(**_layout("Comparaison cohérente des stratégies"))
                st.plotly_chart(
                    fig, width="stretch", key=f"bt_results_compare__{ticker}"
                )
            with st.expander("Détail de la comparaison", expanded=False):
                st.dataframe(
                    comp_df.rename(columns=public_label),
                    width="stretch",
                    hide_index=True,
                )

    with trades_tab:
        closed = int(metrics.get("Trades", 0) or 0)
        _kpis(
            [
                ("Transactions fermées", str(closed), "ledger de stratégie"),
                (
                    "Entrées ouvertes",
                    str(int(metrics.get("Open Entries", 0) or 0)),
                    "positions initiées",
                ),
                (
                    "Rééquilibrages",
                    str(int(metrics.get("Rebalances", 0) or 0)),
                    "même sens",
                ),
                (
                    "Exposition moyenne",
                    _pct(metrics.get("Average Abs Exposure")),
                    "absolue",
                ),
                (
                    "Coûts payés",
                    _money(metrics.get("Cost Paid $")),
                    "diagnostic moteur",
                ),
                (
                    "Sorties risque",
                    str(int(metrics.get("Risk Exits", 0) or 0)),
                    "stops et limites",
                ),
            ]
        )
        st.plotly_chart(
            _trade_figure(trades),
            width="stretch",
            key=f"bt_trades_distribution__{ticker}",
        )
        with st.expander("Ledger des transactions", expanded=False):
            if isinstance(trades, pd.DataFrame) and not trades.empty:
                st.dataframe(
                    trades.rename(columns=public_label),
                    width="stretch",
                    hide_index=True,
                )
            else:
                st.info("Aucune transaction fermée pour cette configuration.")
        if isinstance(risk_events, pd.DataFrame) and not risk_events.empty:
            st.caption(
                f"{len(risk_events)} événement(s) de risque disponible(s) dans le dossier reproductible."
            )

    with validation_tab:
        _gate_grid(gate_cards(gate))
        v1, v2 = st.columns([1.35, 1])
        with v1:
            st.plotly_chart(
                _robustness_figure(cost_matrix, wf_df),
                width="stretch",
                key=f"bt_validation_robustness__{ticker}",
            )
        with v2:
            diagnostics_cards = [
                (
                    "Stabilité paramètres",
                    f"{_num((diagnostics.get('param') or {}).get('score'), 0)}/100",
                    public_label((diagnostics.get("param") or {}).get("label", "—")),
                ),
                (
                    "Walk-forward",
                    f"{_num((diagnostics.get('wf') or {}).get('score'), 0)}/100",
                    public_label((diagnostics.get("wf") or {}).get("label", "—")),
                ),
                (
                    "Coûts",
                    f"{_num((diagnostics.get('cost') or {}).get('score'), 0)}/100",
                    public_label((diagnostics.get("cost") or {}).get("label", "—")),
                ),
                (
                    "Preuve hors-échantillon",
                    f"{_num((diagnostics.get('oos_v2') or {}).get('score'), 0)}/100",
                    public_label((diagnostics.get("oos_v2") or {}).get("level", "—")),
                ),
            ]
            _kpis(diagnostics_cards)
        with st.expander("Matrice de sensibilité", expanded=False):
            if isinstance(sens_matrix, pd.DataFrame) and not sens_matrix.empty:
                st.dataframe(
                    sens_matrix.rename(columns=public_label),
                    width="stretch",
                    hide_index=True,
                )
            else:
                st.info("Matrice indisponible pour cette stratégie.")
        st.caption(
            "Les diagnostics historiques n’autorisent jamais le run; seul le gate du ledger exécuté fait autorité."
        )

    with evidence_tab:
        _render_evidence(
            bars=bars,
            result=result,
            cfg=cfg,
            symbol=ticker,
            institutional=institutional,
            context=institutional_context,
            engine_error=engine_error,
        )
