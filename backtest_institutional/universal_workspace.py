"""Interactive institutional cockpit for the universal backtest kernel.

The workspace never executes user supplied Python.  Source code can be
validated and fingerprinted here, but execution requires a separately attested
OCI runner.  Native targets and imported target series are executed only after
an explicit user action.
"""
from __future__ import annotations

from hashlib import sha256
from html import escape
from io import BytesIO
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from backtest_universal import AssetClass, UniversalBacktestEngine, UniversalEngineConfig
from backtest_universal.adapters import (
    UniversalDataset,
    build_sma_targets,
    parse_long_dataset,
    single_asset_dataset,
    universal_csv_template,
)
from backtest_universal.strategy import DEFAULT_STRATEGY_TEMPLATE, validate_strategy_source

from .universal_bridge import UniversalInstitutionalEnvelope, build_universal_institutional_envelope


_MODE_NATIVE = "Actif courant"
_MODE_IMPORT = "Portefeuille importé"
_MODE_CODE = "Stratégie Python"


def _number(value: Any, default: float = np.nan) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(default)
    return number if np.isfinite(number) else float(default)


def _money(value: Any, currency: str) -> str:
    number = _number(value)
    return "—" if not np.isfinite(number) else f"{number:,.0f} {currency}"


def _percent(value: Any, digits: int = 1) -> str:
    number = _number(value)
    return "—" if not np.isfinite(number) else f"{number:.{digits}%}"


def _inject_css() -> None:
    st.markdown(
        """
        <style>
        .uni-hero{border:1px solid rgba(103,232,249,.22);border-radius:16px;padding:19px 21px;
          background:linear-gradient(135deg,rgba(8,20,34,.98),rgba(14,30,48,.94));margin:.25rem 0 .9rem}
        .uni-kicker{font-size:.68rem;letter-spacing:.15em;text-transform:uppercase;color:#67e8f9;font-weight:800}
        .uni-title{font-size:1.32rem;color:#f8fafc;font-weight:780;margin:.28rem 0}.uni-copy{color:#9fb0c6;font-size:.82rem}
        .uni-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:.6rem;margin:.65rem 0 1rem}
        .uni-card{border:1px solid rgba(148,163,184,.16);border-radius:12px;padding:12px;background:rgba(15,23,42,.62)}
        .uni-label{font-size:.64rem;text-transform:uppercase;letter-spacing:.08em;color:#8294aa}.uni-value{color:#f8fafc;font-size:1.05rem;font-weight:760;margin:.3rem 0}
        .uni-note{font-size:.67rem;color:#8291a8;line-height:1.35}.uni-state{border-left:4px solid #38bdf8;border-radius:12px;padding:13px 15px;background:rgba(15,23,42,.72);margin:.55rem 0 .8rem}
        .uni-state.pass{border-left-color:#34d399}.uni-state.warn{border-left-color:#fbbf24}.uni-state.fail{border-left-color:#fb7185}
        .uni-gates{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:.6rem;margin:.65rem 0}
        .uni-gate{border:1px solid rgba(148,163,184,.16);border-top:3px solid #38bdf8;border-radius:11px;padding:11px;background:rgba(15,23,42,.58)}
        .uni-gate.pass{border-top-color:#34d399}.uni-gate.warn{border-top-color:#fbbf24}.uni-gate.fail{border-top-color:#fb7185}
        .uni-gate-title{color:#e2e8f0;font-size:.74rem;font-weight:720}.uni-gate-state{float:right;color:#93c5fd;font-size:.61rem;letter-spacing:.06em}.uni-gate-detail{color:#8698af;font-size:.66rem;margin-top:.38rem;line-height:1.35}
        @media(max-width:900px){.uni-grid{grid-template-columns:repeat(2,1fr)}.uni-gates{grid-template-columns:1fr}}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _price_contract(bars: pd.DataFrame) -> tuple[str, bool]:
    raw = str(getattr(bars, "attrs", {}).get("price_basis", "raw")).strip().lower()
    if "total" in raw and "adjust" in raw:
        return "total_return_adjusted", False
    if "adjust" in raw:
        return "adjusted", False
    return "raw", True


def _current_currency(bars: pd.DataFrame, cfg: Any) -> tuple[str, bool]:
    declared = str(
        getattr(cfg, "currency", "")
        or getattr(bars, "attrs", {}).get("currency", "")
        or getattr(bars, "attrs", {}).get("quote_currency", "")
    ).strip().upper()
    return (declared, True) if len(declared) == 3 else ("USD", False)


def _engine_config(
    *,
    base_currency: str,
    initial_cash: float,
    commission_bps: float,
    spread_bps: float,
    slippage_bps: float,
    max_participation: float,
    allow_short: bool,
    price_basis: str,
    apply_corporate_actions: bool,
) -> UniversalEngineConfig:
    return UniversalEngineConfig(
        base_currency=str(base_currency).upper(),
        initial_cash=float(initial_cash),
        commission_bps=float(commission_bps),
        spread_bps=float(spread_bps),
        slippage_bps=float(slippage_bps),
        max_participation=float(max_participation),
        allow_short=bool(allow_short),
        price_basis=price_basis,
        apply_corporate_actions=bool(apply_corporate_actions),
    )


def _execute(
    *,
    dataset: UniversalDataset,
    targets: pd.DataFrame,
    target_available_at: pd.Series | None,
    config: UniversalEngineConfig,
    strategy_name: str,
    strategy_mode: str,
    strategy_artifact: dict[str, Any],
) -> UniversalInstitutionalEnvelope:
    result = UniversalBacktestEngine(
        security_master=dataset.security_master,
        config=config,
    ).run(
        market_data=dataset.market_data,
        target_weights=targets,
        fx_rates=dataset.fx_rates,
        cash_rates=dataset.cash_rates or {},
        target_available_at=target_available_at,
    )
    return build_universal_institutional_envelope(
        result=result,
        security_master=dataset.security_master,
        market_data=dataset.market_data,
        target_weights=targets,
        fx_rates=dataset.fx_rates,
        cash_rates=dataset.cash_rates or {},
        config=config,
        strategy_name=strategy_name,
        strategy_mode=strategy_mode,
        strategy_artifact=strategy_artifact,
        # A UI checkbox is not evidence.  Only a signed upstream manifest may
        # set this flag in a future authenticated data adapter.
        point_in_time_authenticated=False,
        sandbox_attested=False,
    )


def _render_capability_map() -> None:
    items = [
        ("Actifs", "9 familles", "actions, ETF, FX, crypto, futures, options, CFD, taux"),
        ("Horloge", "CAUSALE", "cible connue à t, exécution strictement après t"),
        ("Cash", "MULTI-DEVISES", "conversion historique, règlement séparé"),
        ("Risque", "MARGE + LIQUIDATION", "initiale, maintenance et sorties forcées"),
    ]
    cells = "".join(
        "<div class='uni-card'><div class='uni-label'>{}</div><div class='uni-value'>{}</div><div class='uni-note'>{}</div></div>".format(
            *(escape(str(value)) for value in item)
        )
        for item in items
    )
    st.markdown(f"<div class='uni-grid'>{cells}</div>", unsafe_allow_html=True)


def _render_gate(envelope: UniversalInstitutionalEnvelope) -> None:
    decision = str(envelope.gate.get("decision", "HOLD — DATA REQUIRED"))
    tone = "pass" if decision == "RESEARCH APPROVED" else "warn" if decision == "CONDITIONAL REVIEW" else "fail" if decision == "REJECT / REDESIGN" else ""
    blockers = envelope.gate.get("blocking_gates") or []
    detail = "Aucun contrôle bloquant" if not blockers else " · ".join(map(str, blockers[:4]))
    st.markdown(
        f"<div class='uni-state {tone}'><strong>{escape(decision)}</strong><br><span class='uni-copy'>{escape(detail)} · Recherche uniquement, jamais de promotion automatique.</span></div>",
        unsafe_allow_html=True,
    )
    cards = []
    for item in envelope.gate.get("checks", []):
        state = str(item.get("state", "UNAVAILABLE")).upper()
        card_tone = "pass" if state == "PASS" else "warn" if state == "WARN" else "fail" if state == "FAIL" else ""
        cards.append(
            "<div class='uni-gate {}'><div class='uni-gate-title'>{}<span class='uni-gate-state'>{}</span></div><div class='uni-gate-detail'>{}</div></div>".format(
                card_tone,
                escape(str(item.get("gate", "Contrôle"))),
                escape(state),
                escape(str(item.get("detail", ""))),
            )
        )
    st.markdown(f"<div class='uni-gates'>{''.join(cards)}</div>", unsafe_allow_html=True)


def _performance_figure(daily: pd.DataFrame, currency: str) -> go.Figure:
    fig = go.Figure()
    if not daily.empty and "nav" in daily:
        fig.add_trace(go.Scatter(x=daily.index, y=daily["nav"], name="Capital net", line=dict(color="#67e8f9", width=2.4)))
    fig.update_layout(
        template="plotly_dark",
        height=360,
        margin=dict(l=20, r=20, t=42, b=25),
        title=f"Capital exécuté · {currency}",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(9,16,29,.35)",
        hovermode="x unified",
    )
    return fig


def _risk_figure(daily: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    if not daily.empty:
        if "drawdown" in daily:
            fig.add_trace(go.Scatter(x=daily.index, y=daily["drawdown"], name="Drawdown", fill="tozeroy", line=dict(color="#fb7185")))
        if "gross_exposure" in daily:
            fig.add_trace(go.Scatter(x=daily.index, y=daily["gross_exposure"], name="Exposition brute", line=dict(color="#fbbf24", dash="dot"), yaxis="y2"))
    fig.update_layout(
        template="plotly_dark",
        height=360,
        margin=dict(l=20, r=20, t=42, b=25),
        title="Drawdown et utilisation du capital",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(9,16,29,.35)",
        hovermode="x unified",
        yaxis=dict(tickformat=".0%"),
        yaxis2=dict(overlaying="y", side="right", tickformat=".1x"),
        legend=dict(orientation="h", y=1.12),
    )
    return fig


def _render_result(envelope: UniversalInstitutionalEnvelope, currency: str) -> None:
    result = envelope.execution
    daily = result.daily
    returns = pd.to_numeric(daily.get("return"), errors="coerce").dropna() if not daily.empty and "return" in daily else pd.Series(dtype=float)
    total_return = daily["nav"].iloc[-1] / daily["nav"].iloc[0] - 1.0 if len(daily) > 1 else np.nan
    max_drawdown = pd.to_numeric(daily.get("drawdown"), errors="coerce").min() if not daily.empty and "drawdown" in daily else np.nan
    sharpe = returns.mean() / returns.std(ddof=1) * np.sqrt(252.0) if len(returns) > 1 and returns.std(ddof=1) > 0 else np.nan
    columns = st.columns(5)
    values = [
        ("Capital final", _money(daily["nav"].iloc[-1], currency) if not daily.empty else "—"),
        ("Rendement net", _percent(total_return)),
        ("Sharpe", "—" if not np.isfinite(sharpe) else f"{sharpe:.2f}"),
        ("Drawdown max", _percent(max_drawdown)),
        ("Exécutions", str(len(result.fills))),
    ]
    for column, (label, value) in zip(columns, values):
        column.metric(label, value)
    left, right = st.columns([1.45, 1])
    with left:
        st.plotly_chart(_performance_figure(daily, currency), width="stretch", key="bt_uni_nav")
    with right:
        st.plotly_chart(_risk_figure(daily), width="stretch", key="bt_uni_risk")
    _render_gate(envelope)

    ledger_tabs = st.tabs(["Positions & cash", "Ordres & exécutions", "Événements", "Preuves"])
    with ledger_tabs[0]:
        c1, c2 = st.columns(2)
        with c1:
            st.caption("Positions finales")
            st.dataframe(result.positions, width="stretch", hide_index=True)
        with c2:
            st.caption("Cashbook réglé et non réglé")
            st.dataframe(result.cash, width="stretch", hide_index=True)
    with ledger_tabs[1]:
        st.caption("Le ledger d’exécution est la source autoritaire du rendement.")
        st.dataframe(result.orders, width="stretch", hide_index=True)
        st.dataframe(result.fills, width="stretch", hide_index=True)
    with ledger_tabs[2]:
        st.dataframe(result.events, width="stretch", hide_index=True)
        gaps = result.diagnostics.get("lifecycle_gaps") or []
        if gaps:
            st.warning("Contrats de cycle de vie incomplets · " + " · ".join(map(str, gaps[:5])))
    with ledger_tabs[3]:
        st.download_button(
            "Télécharger le dossier reproductible",
            data=envelope.bundle,
            file_name=f"{envelope.manifest.run_id}.zip",
            mime="application/zip",
            key="bt_uni_bundle",
            width="stretch",
        )
        st.json(
            {
                "run_id": envelope.manifest.run_id,
                "authoritative_source": envelope.authoritative_source,
                "gate": envelope.gate,
                "model_card": envelope.model_card,
                "config_hash": envelope.manifest.config_hash,
                "data_hash": envelope.manifest.data_hash,
                "code_hash": envelope.manifest.code_hash,
            }
        )


def _render_native(ticker: str, bars: pd.DataFrame, cfg: Any, session_key: str) -> None:
    inferred_currency, authenticated_currency = _current_currency(bars, cfg)
    price_basis, corporate_actions = _price_contract(bars)
    left, middle, right = st.columns(3)
    with left:
        asset_label = st.selectbox(
            "Classe d’actif",
            ["ETF", "EQUITY", "CRYPTO_SPOT", "CRYPTO_PERPETUAL", "FUTURE", "CFD", "RATE"],
            key="bt_uni_asset_class",
        )
        quote_currency = st.text_input("Devise de cotation", inferred_currency, max_chars=3, key="bt_uni_quote").strip().upper()
        base_currency = st.text_input("Devise du portefeuille", inferred_currency, max_chars=3, key="bt_uni_base").strip().upper()
    with middle:
        fast = st.number_input("Moyenne rapide", min_value=1, max_value=500, value=20, step=1, key="bt_uni_fast")
        slow = st.number_input("Moyenne lente", min_value=2, max_value=1000, value=100, step=1, key="bt_uni_slow")
        initial_cash = st.number_input("Capital initial", min_value=1_000.0, value=1_000_000.0, step=10_000.0, key="bt_uni_cash")
    with right:
        commission = st.number_input("Commission · bps", min_value=0.0, value=0.5, step=0.1, key="bt_uni_commission")
        spread = st.number_input("Spread · bps", min_value=0.0, value=2.0, step=0.5, key="bt_uni_spread")
        slippage = st.number_input("Slippage · bps", min_value=0.0, value=1.0, step=0.5, key="bt_uni_slippage")
        cash_rate_pct = st.number_input(
            "Taux cash annualisé · %",
            min_value=-10.0,
            max_value=100.0,
            value=0.0,
            step=0.1,
            key="bt_uni_cash_rate",
        )
    c1, c2, c3 = st.columns(3)
    with c1:
        participation = st.slider("Participation volume maximale", 0.01, 1.0, 0.10, 0.01, key="bt_uni_participation")
    with c2:
        allow_short = st.toggle("Autoriser les positions vendeuses", value=False, key="bt_uni_short")
    with c3:
        st.caption(f"Prix · {price_basis} · actions sur titres {'rejouées' if corporate_actions else 'désactivées pour éviter le double comptage'}")
    if not authenticated_currency:
        st.warning("La devise n’est pas authentifiée par la source. Vérifiez explicitement la cotation avant le run.")
    if st.button("Exécuter dans le ledger universel", type="primary", key="bt_uni_run_native", width="stretch"):
        try:
            if len(quote_currency) != 3 or len(base_currency) != 3:
                raise ValueError("les devises doivent contenir exactement trois lettres")
            dataset = single_asset_dataset(
                ticker,
                bars,
                currency=quote_currency,
                asset_class=AssetClass(asset_label),
                settlement_days=1 if asset_label in {"ETF", "EQUITY"} else 0,
            )
            dataset.cash_rates = {
                base_currency: pd.Series(
                    float(cash_rate_pct) / 100.0,
                    index=pd.DatetimeIndex(bars.index),
                )
            }
            if quote_currency != base_currency:
                raise ValueError("DATA REQUIRED: le mode actif courant exige une série FX historique; utilisez le portefeuille importé")
            targets = build_sma_targets(
                dataset.market_data,
                fast=int(fast),
                slow=int(slow),
                gross_weight=0.95,
            )
            config = _engine_config(
                base_currency=base_currency,
                initial_cash=initial_cash,
                commission_bps=commission,
                spread_bps=spread,
                slippage_bps=slippage,
                max_participation=participation,
                allow_short=allow_short,
                price_basis=price_basis,
                apply_corporate_actions=corporate_actions,
            )
            envelope = _execute(
                dataset=dataset,
                targets=targets,
                target_available_at=None,
                config=config,
                strategy_name=f"SMA {int(fast)}/{int(slow)}",
                strategy_mode="native",
                strategy_artifact={
                    "kind": "native_sma",
                    "fast": int(fast),
                    "slow": int(slow),
                    "gross_weight": 0.95,
                },
            )
            st.session_state[session_key] = {"envelope": envelope, "currency": base_currency, "mode": _MODE_NATIVE}
        except Exception as exc:
            st.error(f"Run universel indisponible · {exc}")


def _read_uploaded_csv(uploaded: Any) -> pd.DataFrame:
    payload = uploaded.getvalue() if hasattr(uploaded, "getvalue") else bytes(uploaded)
    if len(payload) > 64 * 1024 * 1024:
        raise ValueError("le fichier dépasse 64 MiB")
    return pd.read_csv(BytesIO(payload))


def _render_import(session_key: str) -> None:
    template = universal_csv_template()
    st.download_button(
        "Télécharger le modèle multi-actifs",
        data=template.to_csv(index=False).encode("utf-8"),
        file_name="backtest_universal_template.csv",
        mime="text/csv",
        key="bt_uni_template",
    )
    st.caption("Format long · instrument canonique, classe d’actif, devise, OHLCV, FX historique et cible horodatée.")
    base_currency = st.text_input("Devise de référence", "USD", max_chars=3, key="bt_uni_import_base").strip().upper()
    uploaded = st.file_uploader("Importer le dataset et les cibles", type=["csv"], key="bt_uni_upload")
    preview: pd.DataFrame | None = None
    if uploaded is not None:
        try:
            preview = _read_uploaded_csv(uploaded)
            st.dataframe(preview.head(30), width="stretch", hide_index=True)
        except Exception as exc:
            st.error(f"Fichier illisible · {exc}")
    if st.button("Valider et exécuter le portefeuille", type="primary", key="bt_uni_run_import", disabled=preview is None, width="stretch"):
        try:
            if preview is None:
                raise ValueError("aucun dataset")
            dataset = parse_long_dataset(preview, base_currency=base_currency)
            targets = dataset.target_weights
            if targets is None or targets.dropna(how="all").empty:
                targets = build_sma_targets(
                    dataset.market_data, fast=20, slow=100, gross_weight=0.90
                )
                strategy_name = "SMA portefeuille"
                artifact = {
                    "kind": "native_sma",
                    "fast": 20,
                    "slow": 100,
                    "gross_weight": 0.90,
                }
            else:
                strategy_name = "Cibles importées"
                artifact = {"kind": "imported_targets", "csv_sha256": sha256(preview.to_csv(index=False).encode("utf-8")).hexdigest()}
            config = _engine_config(
                base_currency=base_currency,
                initial_cash=1_000_000.0,
                commission_bps=0.5,
                spread_bps=2.0,
                slippage_bps=1.0,
                max_participation=0.10,
                allow_short=False,
                price_basis="raw",
                apply_corporate_actions=True,
            )
            envelope = _execute(
                dataset=dataset,
                targets=targets,
                target_available_at=dataset.target_available_at,
                config=config,
                strategy_name=strategy_name,
                strategy_mode="imported_targets",
                strategy_artifact=artifact,
            )
            st.session_state[session_key] = {"envelope": envelope, "currency": base_currency, "mode": _MODE_IMPORT}
        except Exception as exc:
            st.error(f"Run universel indisponible · {exc}")


def _render_code() -> None:
    st.warning("SANDBOX REQUIRED · Le code n’est jamais exécuté dans Streamlit ni dans le Codespace hôte.")
    source = st.text_area(
        "Code de stratégie",
        value=DEFAULT_STRATEGY_TEMPLATE,
        height=360,
        key="bt_uni_source",
    )
    report = validate_strategy_source(source)
    c1, c2, c3 = st.columns(3)
    c1.metric("Politique statique", report.status)
    c2.metric("Nœuds analysés", str(report.node_count))
    c3.metric("Empreinte", report.source_sha256[:12])
    if report.passed:
        st.success("Contrat SDK valide · prêt à être soumis à un runner OCI attesté.")
    else:
        st.error("Politique refusée · " + " · ".join(report.issues[:8]))
    st.info("Pour devenir exécutable : image immuable, réseau coupé, racine en lecture seule, aucun secret, utilisateur non-root et résultat signé. En l’absence de ces preuves, le moteur échoue fermé.")


def render_universal_workspace(*, ticker: str, bars: pd.DataFrame, cfg: Any) -> None:
    """Render the universal kernel workspace inside the Backtest Lab."""

    _inject_css()
    st.markdown(
        "<div class='uni-hero'><div class='uni-kicker'>Noyau multi-actifs · recherche gouvernée</div>"
        "<div class='uni-title'>Moteur universel</div>"
        "<div class='uni-copy'>Construisez un run multi-instruments, rejouez les coûts, devises, règlements, marges et événements de cycle de vie, puis inspectez chaque preuve avant décision.</div></div>",
        unsafe_allow_html=True,
    )
    _render_capability_map()
    mode = st.radio(
        "Point d’entrée",
        [_MODE_NATIVE, _MODE_IMPORT, _MODE_CODE],
        horizontal=True,
        key="bt_uni_mode",
    )
    session_key = f"bt_universal_result::{str(ticker).upper()}"
    if mode == _MODE_NATIVE:
        _render_native(ticker, bars, cfg, session_key)
    elif mode == _MODE_IMPORT:
        _render_import(session_key)
    else:
        _render_code()

    stored = st.session_state.get(session_key)
    if isinstance(stored, dict) and isinstance(stored.get("envelope"), UniversalInstitutionalEnvelope):
        if mode == _MODE_CODE:
            st.info(
                "Le dernier run validé reste conservé, mais il n’est pas affiché ici : "
                "le code édité ci-dessus n’a pas été exécuté."
            )
            return
        if stored.get("mode") != mode:
            st.caption(f"Dernier run conservé · {stored.get('mode')}")
        _render_result(stored["envelope"], str(stored.get("currency", "USD")))
    else:
        st.info("Aucun run universel exécuté. La configuration reste un brouillon jusqu’au clic explicite.")
