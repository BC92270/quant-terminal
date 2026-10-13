"""Code-first institutional Strategy Studio for Backtest Lab.

The UI makes the causal boundary visible: user code is compiled and evaluated
inside Docker, while the trusted universal engine remains the only authority
for orders, fills, cash, risk, P&L and evidence.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from html import escape
from io import BytesIO
import json
import os
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
import streamlit as st

from backtest_sandbox import (
    DockerStrategyRunner,
    SandboxLimits,
    StrategyLanguage,
    template_for,
    validate_source,
)
from backtest_sandbox.docker_runner import (
    SandboxExecutionError,
    SandboxUnavailableError,
)
from backtest_universal import (
    AssetClass,
    OptionRight,
    SettlementType,
    UniversalBacktestEngine,
)
from backtest_universal.adapters import (
    UniversalDataset,
    parse_long_dataset,
    single_asset_dataset,
    universal_csv_template,
)

from .universal_bridge import (
    UniversalInstitutionalEnvelope,
    build_universal_institutional_envelope,
)
from .scenarios import ScenarioConfig, run_institutional_scenario_suite
from .statistics import institutional_validation_suite
from .universal_workspace import (
    _engine_config,
    _money,
    _percent,
    _performance_figure,
    _price_contract,
    _risk_figure,
)


_STUDIO = "Studio"
_RUNS = "Runs"
_COMPARE = "Compare"
_VALIDATION = "Validation"
_EVIDENCE = "Evidence"
_WORKFLOW = (_STUDIO, _RUNS, _COMPARE, _VALIDATION, _EVIDENCE)
_LANGUAGES = tuple(StrategyLanguage)
_ASSET_CLASSES = tuple(item.value for item in AssetClass)


def _inject_css() -> None:
    st.markdown(
        """
        <style>
        .bcs-hero{border:1px solid rgba(56,189,248,.24);border-radius:18px;padding:22px 24px;
          background:radial-gradient(circle at 85% 10%,rgba(14,165,233,.15),transparent 36%),linear-gradient(135deg,#07111f,#0d1d31);margin:.2rem 0 .8rem}
        .bcs-kicker{font-size:.72rem;letter-spacing:.16em;text-transform:uppercase;color:#67e8f9;font-weight:800}
        .bcs-title{font-size:1.55rem;line-height:1.2;color:#f8fafc;font-weight:780;margin:.3rem 0}.bcs-copy{color:#a6b6cb;font-size:.88rem;max-width:980px;line-height:1.5}
        .bcs-strip{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:.55rem;margin:.65rem 0 1rem}
        .bcs-chip{border:1px solid rgba(148,163,184,.18);border-radius:12px;padding:10px 12px;background:rgba(15,23,42,.64)}
        .bcs-chip-label{font-size:.62rem;letter-spacing:.08em;text-transform:uppercase;color:#8193aa}.bcs-chip-value{font-size:.8rem;color:#e6edf7;font-weight:700;margin-top:.22rem}
        .bcs-panel{border:1px solid rgba(148,163,184,.17);border-radius:14px;padding:14px 15px;background:rgba(9,18,32,.62);margin-bottom:.7rem}
        .bcs-panel-title{color:#f1f5f9;font-size:.78rem;font-weight:780;letter-spacing:.05em;text-transform:uppercase;margin-bottom:.45rem}
        .bcs-ok{color:#34d399}.bcs-warn{color:#fbbf24}.bcs-fail{color:#fb7185}.bcs-muted{color:#8da0b8;font-size:.75rem;line-height:1.5}
        .bcs-gates{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:.6rem;margin:.65rem 0}
        .bcs-gate{border:1px solid rgba(148,163,184,.16);border-left:4px solid #64748b;border-radius:10px;padding:11px;background:rgba(15,23,42,.58)}
        .bcs-gate.pass{border-left-color:#34d399}.bcs-gate.fail{border-left-color:#fb7185}.bcs-gate.unavailable{border-left-color:#fbbf24}
        .bcs-gate-name{color:#e5edf7;font-size:.73rem;font-weight:730}.bcs-gate-state{float:right;font-size:.62rem;letter-spacing:.06em}.bcs-gate-detail{color:#899bb1;font-size:.67rem;line-height:1.35;margin-top:.35rem}
        div[data-testid="stTextArea"] textarea{font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;font-size:.78rem;line-height:1.45}
        @media(max-width:900px){.bcs-strip{grid-template-columns:repeat(2,1fr)}.bcs-gates{grid-template-columns:1fr}}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _segmented(label: str, options: tuple[str, ...], key: str, default: str) -> str:
    if hasattr(st, "segmented_control"):
        value = st.segmented_control(
            label,
            options=list(options),
            default=default,
            key=key,
            label_visibility="collapsed",
            width="stretch",
        )
    else:
        value = st.radio(
            label,
            list(options),
            index=list(options).index(default),
            horizontal=True,
            key=key,
            label_visibility="collapsed",
        )
    return str(value or default)


def _controller_key_path() -> str | None:
    explicit = os.environ.get("BACKTEST_SANDBOX_KEY_PATH", "").strip()
    if explicit:
        return explicit
    live_root = Path("/workspaces/.codex-runtime-backtest-code")
    return (
        str(live_root / "controller_ed25519.pem") if live_root.parent.exists() else None
    )


def _runner() -> DockerStrategyRunner:
    return DockerStrategyRunner(
        limits=SandboxLimits(
            wall_seconds=120,
            compile_seconds=45,
            callback_seconds=5,
            memory_mib=768,
            cpu_cores=1.0,
            pids=64,
            tmp_mib=384,
            output_mib=16,
        ),
        controller_key_path=_controller_key_path(),
    )


def _currency(bars: pd.DataFrame, cfg: Any) -> tuple[str, bool]:
    value = (
        str(
            getattr(cfg, "currency", "")
            or getattr(bars, "attrs", {}).get("currency", "")
            or getattr(bars, "attrs", {}).get("quote_currency", "")
        )
        .strip()
        .upper()
    )
    return (value, True) if len(value) == 3 else ("USD", False)


def _parse_parameters(raw: str) -> dict[str, float]:
    value = json.loads(str(raw or "{}"))
    if not isinstance(value, dict):
        raise ValueError("les paramètres doivent être un objet JSON")
    clean: dict[str, float] = {}
    for key, item in value.items():
        name = str(key)
        if not name.replace("_", "").isalnum():
            raise ValueError(f"nom de paramètre invalide : {name}")
        number = float(item)
        if not np.isfinite(number):
            raise ValueError(f"paramètre non fini : {name}")
        clean[name] = number
    return clean


def _read_csv(uploaded: Any) -> pd.DataFrame:
    payload = uploaded.getvalue() if hasattr(uploaded, "getvalue") else bytes(uploaded)
    if len(payload) > 64 * 1024 * 1024:
        raise ValueError("le dataset dépasse 64 MiB")
    return pd.read_csv(BytesIO(payload))


def _dataset_hash(dataset: UniversalDataset) -> str:
    digest = sha256()
    for symbol, frame in sorted(dataset.market_data.items()):
        digest.update(str(symbol).encode("utf-8"))
        digest.update(frame.to_csv(index=True).encode("utf-8"))
    digest.update(
        json.dumps(
            dataset.security_master.records(), sort_keys=True, default=str
        ).encode("utf-8")
    )
    return digest.hexdigest()


def _latest(runs: list[dict[str, Any]]) -> dict[str, Any] | None:
    return runs[-1] if runs else None


def _runs() -> list[dict[str, Any]]:
    value = st.session_state.setdefault("bt_code_run_registry", [])
    return value if isinstance(value, list) else []


def _render_hero(ticker: str) -> None:
    st.markdown(
        "<div class='bcs-hero'><div class='bcs-kicker'>Research only · code-first · ledger autoritaire</div>"
        f"<div class='bcs-title'>Strategy Studio · {escape(str(ticker).upper())}</div>"
        "<div class='bcs-copy'>Écrivez, validez, compilez et rejouez une stratégie sans exposer le Codespace hôte. "
        "Le conteneur ne voit les données que dans l’ordre causal et ne peut émettre que des expositions cibles ; "
        "le moteur universel calcule ensuite les ordres, exécutions, coûts, marge, cash et preuves.</div></div>",
        unsafe_allow_html=True,
    )
    items = (
        ("Langages", "6 runtimes"),
        ("Données", "9 classes d’actifs"),
        ("Horloge", "Slices atomiques"),
        ("Sécurité", "Docker sans réseau"),
        ("Autorité", "Ledger exécuté"),
    )
    st.markdown(
        "<div class='bcs-strip'>"
        + "".join(
            f"<div class='bcs-chip'><div class='bcs-chip-label'>{escape(label)}</div><div class='bcs-chip-value'>{escape(value)}</div></div>"
            for label, value in items
        )
        + "</div>",
        unsafe_allow_html=True,
    )


def _gate_grid(envelope: UniversalInstitutionalEnvelope) -> None:
    cards: list[str] = []
    for item in envelope.gate.get("checks", []):
        state = str(item.get("state", "UNAVAILABLE")).upper()
        tone = (
            "pass" if state == "PASS" else "fail" if state == "FAIL" else "unavailable"
        )
        cards.append(
            f"<div class='bcs-gate {tone}'><div class='bcs-gate-name'>{escape(str(item.get('gate','Contrôle')))}"
            f"<span class='bcs-gate-state'>{escape(state)}</span></div>"
            f"<div class='bcs-gate-detail'>{escape(str(item.get('detail','')))}</div></div>"
        )
    st.markdown(
        "<div class='bcs-gates'>" + "".join(cards) + "</div>", unsafe_allow_html=True
    )


def _executed_returns(record: Mapping[str, Any]) -> pd.Series:
    daily = record["envelope"].execution.daily
    if not isinstance(daily, pd.DataFrame) or "return" not in daily:
        return pd.Series(dtype=float)
    return (
        pd.to_numeric(daily["return"], errors="coerce")
        .replace([np.inf, -np.inf], np.nan)
        .dropna()
    )


def _compact_scenarios(result: Mapping[str, Any]) -> dict[str, Any]:
    """Keep audit outputs while dropping large simulated path matrices."""

    config = result.get("config")
    summary = result.get("summary")
    return {
        "summary": (
            summary.copy() if isinstance(summary, pd.DataFrame) else pd.DataFrame()
        ),
        "availability": dict(result.get("availability") or {}),
        "reverse_stress": dict(result.get("reverse_stress") or {}),
        "evt": dict(result.get("evt") or {}),
        "regime_mix": dict(result.get("regime_mix") or {}),
        "markov": dict(result.get("markov") or {}),
        "multivariate": dict(result.get("multivariate") or {}),
        "factor_model": dict(result.get("factor_model") or {}),
        "marginal_student_t": dict(result.get("marginal_student_t") or {}),
        "historical_bootstrap": dict(result.get("historical_bootstrap") or {}),
        "policy": dict(result.get("policy") or {}),
        "institutional_eligible": bool(result.get("institutional_eligible", False)),
        "seed": int(result.get("seed", 41)),
        "config": dict(getattr(config, "__dict__", {}) or {}),
    }


def _execution_diagnostics(record: Mapping[str, Any]) -> dict[str, Any]:
    execution = record["envelope"].execution
    fills = (
        execution.fills if isinstance(execution.fills, pd.DataFrame) else pd.DataFrame()
    )
    orders = (
        execution.orders
        if isinstance(execution.orders, pd.DataFrame)
        else pd.DataFrame()
    )
    daily = (
        execution.daily if isinstance(execution.daily, pd.DataFrame) else pd.DataFrame()
    )
    participation = (
        pd.to_numeric(fills.get("participation"), errors="coerce").dropna()
        if "participation" in fills
        else pd.Series(dtype=float)
    )
    impact = (
        pd.to_numeric(fills.get("impact_bps"), errors="coerce").dropna()
        if "impact_bps" in fills
        else pd.Series(dtype=float)
    )
    maintenance = (
        pd.to_numeric(daily.get("maintenance_excess"), errors="coerce").dropna()
        if "maintenance_excess" in daily
        else pd.Series(dtype=float)
    )
    return {
        "fills": int(len(fills)),
        "orders_not_filled": (
            int(orders["status"].astype(str).str.upper().ne("FILLED").sum())
            if "status" in orders
            else 0
        ),
        "forced_fills": (
            int(fills["forced"].fillna(False).astype(bool).sum())
            if "forced" in fills
            else 0
        ),
        "max_participation": (
            float(participation.max()) if not participation.empty else np.nan
        ),
        "median_participation": (
            float(participation.median()) if not participation.empty else np.nan
        ),
        "max_impact_bps": float(impact.max()) if not impact.empty else np.nan,
        "minimum_maintenance_excess": (
            float(maintenance.min()) if not maintenance.empty else np.nan
        ),
        "terminal_target_changes_without_execution": list(
            execution.diagnostics.get("terminal_target_changes_without_execution") or []
        ),
        "accounting_reconciled": bool(
            execution.diagnostics.get("accounting_reconciled")
        ),
    }


def _tool_coverage(record: Mapping[str, Any]) -> pd.DataFrame:
    envelope = record["envelope"]
    sandbox = record["sandbox"]
    analysis = dict(record.get("analysis") or {})
    scenarios = dict(analysis.get("scenarios") or {})
    availability = dict(scenarios.get("availability") or {})
    statistics = dict(analysis.get("statistics") or {})
    gates = {
        str(item.get("gate")): str(item.get("state", "UNAVAILABLE"))
        for item in envelope.gate.get("checks", [])
    }

    def scenario_state(name: str) -> str:
        return str((availability.get(name) or {}).get("state", "NOT RUN"))

    def statistical_state(name: str) -> str:
        value = statistics.get(name)
        if not statistics:
            return "NOT RUN"
        if isinstance(value, Mapping):
            state = str(value.get("state", "")).upper()
            if value.get("available") is False or state == "UNAVAILABLE":
                return "UNAVAILABLE"
            if value.get("available") is True or state == "AVAILABLE":
                return "AVAILABLE"
        return "AVAILABLE" if value is not None else "UNAVAILABLE"

    rows = [
        ("Code", "Politique statique multi-langage", "PASS"),
        ("Code", "Compilation runtime", "PASS" if sandbox.compiler else "UNAVAILABLE"),
        (
            "Isolation",
            "Docker sans réseau / non-root / read-only",
            "PASS" if sandbox.attestation.passed else "FAIL",
        ),
        (
            "Causalité",
            "Slices multi-actifs atomiques",
            "PASS"
            if sandbox.diagnostics.get("causal_streaming")
            and sandbox.diagnostics.get("atomic_market_slices")
            else "FAIL",
        ),
        (
            "Causalité",
            "Look-ahead guard",
            "PASS"
            if sandbox.diagnostics.get("future_data_exposed") is False
            else "FAIL",
        ),
        (
            "Ledger",
            "Ordres, fills et comptabilité",
            gates.get("Universal event ledger", "UNAVAILABLE"),
        ),
        (
            "Ledger",
            "FX multi-devises",
            gates.get("Multi-currency cashbook", "UNAVAILABLE"),
        ),
        (
            "Ledger",
            "Règlement et marge",
            gates.get("Settlement and margin", "UNAVAILABLE"),
        ),
        (
            "Ledger",
            "Corporate actions / lifecycle",
            gates.get("Instrument lifecycle", "UNAVAILABLE"),
        ),
        (
            "Exécution",
            "Spread, slippage, impact, participation",
            gates.get("Execution calibration", "UNAVAILABLE"),
        ),
        ("Scénarios", "Bootstrap historique", scenario_state("Historical bootstrap")),
        ("Scénarios", "Student-t marginal", scenario_state("Marginal Student-t")),
        (
            "Scénarios",
            "Student-t multivarié",
            scenario_state("Multivariate Student-t"),
        ),
        (
            "Scénarios",
            "Régimes de Markov",
            scenario_state("Markov regime switching"),
        ),
        ("Scénarios", "EVT / queue empirique", scenario_state("EVT empirical tail")),
        ("Scénarios", "Spirale de liquidité", scenario_state("Liquidity spiral")),
        ("Statistiques", "PSR / HAC", statistical_state("psr")),
        ("Statistiques", "DSR", statistical_state("dsr")),
        ("Statistiques", "PBO / CSCV", statistical_state("pbo")),
        (
            "Statistiques",
            "White Reality Check",
            statistical_state("white_reality_check"),
        ),
        ("Statistiques", "Hansen SPA", statistical_state("hansen_spa")),
        ("Statistiques", "CPCV purgé + embargo", statistical_state("cpcv")),
        (
            "Preuves",
            "Snapshot point-in-time signé",
            gates.get("Point-in-time data contract", "UNAVAILABLE"),
        ),
        ("Gouvernance", "Promotion automatique", "DISABLED"),
    ]
    return pd.DataFrame(rows, columns=["Domaine", "Outil / contrôle", "État"])


def _run_metrics(record: Mapping[str, Any]) -> None:
    envelope: UniversalInstitutionalEnvelope = record["envelope"]
    daily = envelope.execution.daily
    returns = (
        pd.to_numeric(daily.get("return"), errors="coerce").dropna()
        if "return" in daily
        else pd.Series(dtype=float)
    )
    total = (
        daily["nav"].iloc[-1] / daily["nav"].iloc[0] - 1.0 if len(daily) > 1 else np.nan
    )
    drawdown = (
        pd.to_numeric(daily.get("drawdown"), errors="coerce").min()
        if "drawdown" in daily
        else np.nan
    )
    sharpe = (
        returns.mean() / returns.std(ddof=1) * np.sqrt(252.0)
        if len(returns) > 1 and returns.std(ddof=1) > 0
        else np.nan
    )
    values = (
        (
            "Capital final",
            _money(daily["nav"].iloc[-1], str(record["currency"]))
            if not daily.empty
            else "—",
        ),
        ("Rendement net", _percent(total)),
        ("Sharpe", "—" if not np.isfinite(sharpe) else f"{sharpe:.2f}"),
        ("Drawdown max", _percent(drawdown)),
        ("Fills", str(len(envelope.execution.fills))),
        ("Décision", str(envelope.gate.get("decision", "—"))),
    )
    for column, (label, value) in zip(st.columns(6), values):
        column.metric(label, value)


def _render_record(record: dict[str, Any], *, view_key: str) -> None:
    envelope: UniversalInstitutionalEnvelope = record["envelope"]
    sandbox = record["sandbox"]
    _run_metrics(record)
    view = st.radio(
        "Vue du run",
        ["Performance", "Ledger", "Événements", "Sandbox"],
        horizontal=True,
        key=view_key,
    )
    if view == "Performance":
        left, right = st.columns([1.45, 1])
        with left:
            st.plotly_chart(
                _performance_figure(envelope.execution.daily, str(record["currency"])),
                width="stretch",
                key=view_key + "__nav",
            )
        with right:
            st.plotly_chart(
                _risk_figure(envelope.execution.daily),
                width="stretch",
                key=view_key + "__risk",
            )
        decision = str(envelope.gate.get("decision", "HOLD — DATA REQUIRED"))
        blockers = envelope.gate.get("blocking_gates") or []
        st.warning(
            decision + (" · " + " · ".join(map(str, blockers[:4])) if blockers else "")
        )
    elif view == "Ledger":
        st.caption(
            "Le ledger universel — jamais le conteneur — est la source autoritaire du rendement."
        )
        st.dataframe(envelope.execution.orders, width="stretch", hide_index=True)
        st.dataframe(envelope.execution.fills, width="stretch", hide_index=True)
        positions, cash = st.columns(2)
        positions.dataframe(
            envelope.execution.positions, width="stretch", hide_index=True
        )
        cash.dataframe(envelope.execution.cash, width="stretch", hide_index=True)
    elif view == "Événements":
        st.dataframe(envelope.execution.events, width="stretch", hide_index=True)
        st.json(envelope.execution.diagnostics)
    else:
        st.json(sandbox.evidence())
        if sandbox.logs:
            st.dataframe(
                pd.DataFrame(list(sandbox.logs)), width="stretch", hide_index=True
            )
        else:
            st.caption("Aucun log utilisateur émis.")


def _dataset_controls(
    ticker: str, bars: pd.DataFrame, cfg: Any
) -> tuple[UniversalDataset | None, str, bool]:
    inferred, currency_authenticated = _currency(bars, cfg)
    mode = st.radio(
        "Univers de données",
        ["Actif courant", "CSV multi-actifs"],
        horizontal=True,
        key="bt_code_dataset_mode",
    )
    if mode == "Actif courant":
        asset = st.selectbox(
            "Classe d’actif",
            _ASSET_CLASSES,
            index=_ASSET_CLASSES.index("EQUITY"),
            key="bt_code_asset",
        )
        quote = (
            st.text_input("Devise cotation", inferred, max_chars=3, key="bt_code_quote")
            .strip()
            .upper()
        )
        base = (
            st.text_input(
                "Devise portefeuille", inferred, max_chars=3, key="bt_code_base"
            )
            .strip()
            .upper()
        )
        if len(quote) != 3 or len(base) != 3:
            st.error("Les devises doivent contenir trois lettres.")
            return None, base or "USD", currency_authenticated
        if quote != base:
            st.warning(
                "Série FX historique requise : passez au CSV multi-actifs pour une cotation différente de la devise du portefeuille."
            )
            return None, base, currency_authenticated
        instrument_kwargs: dict[str, Any] = {
            "instrument_id": st.text_input(
                "Identifiant instrument",
                str(ticker).upper(),
                key="bt_code_instrument_id",
            ).strip().upper(),
            "exchange": st.text_input(
                "Place / venue", "UNKNOWN", key="bt_code_exchange"
            ).strip().upper(),
        }
        selected_asset = AssetClass(asset)
        derivative = selected_asset in {AssetClass.FUTURE, AssetClass.OPTION}
        with st.expander("Contrat, lots et cycle de vie", expanded=derivative):
            instrument_kwargs["lot_size"] = st.number_input(
                "Taille de lot",
                min_value=0.00000001,
                value=1.0 if derivative else 0.00000001,
                format="%.8f",
                key="bt_code_lot_size",
            )
            instrument_kwargs["tick_size"] = st.number_input(
                "Tick size",
                min_value=0.00000001,
                value=0.01,
                format="%.8f",
                key="bt_code_tick_size",
            )
            if selected_asset == AssetClass.FX:
                inferred_leg = str(ticker).replace("/", "").upper()[:3]
                instrument_kwargs["base_currency"] = st.text_input(
                    "Devise de base FX",
                    inferred_leg if len(inferred_leg) == 3 else "EUR",
                    max_chars=3,
                    key="bt_code_fx_base_currency",
                ).strip().upper()
            elif selected_asset == AssetClass.FUTURE:
                instrument_kwargs["root_symbol"] = st.text_input(
                    "Racine future",
                    str(ticker).upper(),
                    key="bt_code_future_root",
                ).strip().upper()
                instrument_kwargs["multiplier"] = st.number_input(
                    "Multiplicateur contrat",
                    min_value=0.00000001,
                    value=1.0,
                    format="%.8f",
                    key="bt_code_future_multiplier",
                )
                last_bar = pd.Timestamp(pd.DatetimeIndex(bars.index).max())
                instrument_kwargs["expiry"] = pd.Timestamp(
                    st.date_input(
                        "Échéance",
                        value=(last_bar + pd.Timedelta(days=90)).date(),
                        key="bt_code_future_expiry",
                    ),
                    tz="UTC",
                ).to_pydatetime()
            elif selected_asset == AssetClass.OPTION:
                instrument_kwargs["underlying_symbol"] = st.text_input(
                    "Sous-jacent",
                    str(ticker).upper(),
                    key="bt_code_option_underlying",
                ).strip().upper()
                instrument_kwargs["strike"] = st.number_input(
                    "Strike",
                    min_value=0.00000001,
                    value=float(
                        pd.to_numeric(
                            bars.iloc[-1].get("Close", bars.iloc[-1].get("close", 100.0)),
                            errors="coerce",
                        )
                    ),
                    key="bt_code_option_strike",
                )
                instrument_kwargs["option_right"] = OptionRight(
                    st.selectbox(
                        "Droit",
                        [item.value for item in OptionRight],
                        key="bt_code_option_right",
                    )
                )
                instrument_kwargs["settlement_type"] = SettlementType(
                    st.selectbox(
                        "Règlement",
                        [item.value for item in SettlementType],
                        key="bt_code_option_settlement",
                    )
                )
                instrument_kwargs["multiplier"] = st.number_input(
                    "Multiplicateur option",
                    min_value=0.00000001,
                    value=100.0,
                    key="bt_code_option_multiplier",
                )
                last_bar = pd.Timestamp(pd.DatetimeIndex(bars.index).max())
                instrument_kwargs["expiry"] = pd.Timestamp(
                    st.date_input(
                        "Expiration",
                        value=(last_bar + pd.Timedelta(days=30)).date(),
                        key="bt_code_option_expiry",
                    ),
                    tz="UTC",
                ).to_pydatetime()
        dataset = single_asset_dataset(
            ticker,
            bars,
            currency=quote,
            asset_class=selected_asset,
            settlement_days=1 if asset in {"EQUITY", "ETF"} else 0,
            **instrument_kwargs,
        )
        dataset.cash_rates = {base: pd.Series(0.0, index=pd.DatetimeIndex(bars.index))}
        return dataset, base, currency_authenticated

    st.download_button(
        "Modèle CSV universel",
        data=universal_csv_template().to_csv(index=False).encode("utf-8"),
        file_name="backtest_universe.csv",
        mime="text/csv",
        key="bt_code_csv_template",
        width="stretch",
    )
    base = (
        st.text_input(
            "Devise portefeuille", "USD", max_chars=3, key="bt_code_import_base"
        )
        .strip()
        .upper()
    )
    uploaded = st.file_uploader(
        "Dataset point-in-time / recherche", type=["csv"], key="bt_code_dataset_upload"
    )
    if uploaded is None:
        st.caption(
            "Importez OHLCV, security master, FX et événements de cycle de vie au format long."
        )
        return None, base, False
    try:
        raw = _read_csv(uploaded)
        st.dataframe(raw.head(12), width="stretch", hide_index=True)
        return parse_long_dataset(raw, base_currency=base), base, False
    except Exception as exc:
        st.error(f"Dataset refusé · {exc}")
        return None, base, False


def _execution_controls(base_currency: str) -> dict[str, Any]:
    with st.expander("Hypothèses d’exécution et risque", expanded=False):
        row1 = st.columns(4)
        initial_cash = row1[0].number_input(
            "Capital initial",
            min_value=1_000.0,
            value=1_000_000.0,
            step=10_000.0,
            key="bt_code_cash",
        )
        commission = row1[1].number_input(
            "Commission · bps",
            min_value=0.0,
            value=0.5,
            step=0.1,
            key="bt_code_commission",
        )
        spread = row1[2].number_input(
            "Spread · bps", min_value=0.0, value=2.0, step=0.5, key="bt_code_spread"
        )
        slippage = row1[3].number_input(
            "Slippage · bps", min_value=0.0, value=1.0, step=0.5, key="bt_code_slippage"
        )
        row2 = st.columns(4)
        impact = row2[0].number_input(
            "Impact plein volume · bps",
            min_value=0.0,
            value=25.0,
            step=1.0,
            key="bt_code_impact",
        )
        participation = row2[1].slider(
            "Participation max", 0.01, 1.0, 0.10, 0.01, key="bt_code_participation"
        )
        allow_short = row2[2].toggle(
            "Positions vendeuses", value=False, key="bt_code_short"
        )
        seed = row2[3].number_input(
            "Seed",
            min_value=0,
            max_value=2_147_483_647,
            value=41,
            step=1,
            key="bt_code_seed",
        )
        st.caption(
            f"Devise de référence · {base_currency} · exécution cible strictement sur une barre ultérieure"
        )
    return {
        "initial_cash": initial_cash,
        "commission": commission,
        "spread": spread,
        "slippage": slippage,
        "impact": impact,
        "participation": participation,
        "allow_short": allow_short,
        "seed": int(seed),
    }


def _render_studio(ticker: str, bars: pd.DataFrame, cfg: Any) -> None:
    left, center, right = st.columns([0.9, 1.8, 1.05], gap="large")
    with left:
        st.markdown(
            "<div class='bcs-panel-title'>Projet & univers</div>",
            unsafe_allow_html=True,
        )
        language = st.selectbox(
            "Langage",
            _LANGUAGES,
            format_func=lambda item: item.label,
            key="bt_code_language",
        )
        dataset, base_currency, currency_authenticated = _dataset_controls(
            ticker, bars, cfg
        )
        parameters_raw = st.text_area(
            "Paramètres JSON",
            value='{"fast": 20, "slow": 100}',
            height=92,
            key="bt_code_parameters",
        )
        try:
            parameters = _parse_parameters(parameters_raw)
            parameters_error = ""
        except Exception as exc:
            parameters = {}
            parameters_error = str(exc)
            st.error(parameters_error)
    with center:
        st.markdown(
            "<div class='bcs-panel-title'>Éditeur de stratégie</div>",
            unsafe_allow_html=True,
        )
        source_key = f"bt_code_source::{language.value}"
        uploaded_source = st.file_uploader(
            "Importer un fichier source",
            type=[language.extension.lstrip(".")],
            key=f"bt_code_upload::{language.value}",
            label_visibility="collapsed",
        )
        if uploaded_source is not None:
            payload = uploaded_source.getvalue()
            upload_hash = sha256(payload).hexdigest()
            hash_key = source_key + "::upload"
            if st.session_state.get(hash_key) != upload_hash:
                st.session_state[source_key] = payload.decode("utf-8")
                st.session_state[hash_key] = upload_hash
        source = st.text_area(
            "Code",
            value=template_for(language),
            height=520,
            key=source_key,
            label_visibility="collapsed",
        )
        st.download_button(
            "Télécharger le source",
            data=source.encode("utf-8"),
            file_name="strategy" + language.extension,
            mime="text/plain",
            key=f"bt_code_download::{language.value}",
        )
    report = validate_source(source, language)
    runner = _runner()
    digest = runner.image_digest()
    with right:
        st.markdown(
            "<div class='bcs-panel-title'>Inspecteur de préflight</div>",
            unsafe_allow_html=True,
        )
        policy_tone = "bcs-ok" if report.passed else "bcs-fail"
        docker_tone = "bcs-ok" if digest else "bcs-fail"
        data_tone = "bcs-ok" if dataset is not None else "bcs-warn"
        st.markdown(
            "<div class='bcs-panel'>"
            f"<div class='{policy_tone}'>● Politique · {escape(report.status)}</div>"
            f"<div class='{docker_tone}'>● Image Docker · {'IMMUTABLE' if digest else 'ABSENTE'}</div>"
            f"<div class='{data_tone}'>● Dataset · {'PRÊT' if dataset is not None else 'À FOURNIR'}</div>"
            f"<div class='bcs-muted'>SHA source · {report.source_sha256[:16]}<br>"
            f"Image · {escape(digest[:24] if digest else 'quant-terminal/backtest-sandbox:2.0.0')}<br>"
            "Réseau · coupé<br>RootFS · lecture seule<br>Utilisateur · 65532:65532<br>Capacités · aucune</div></div>",
            unsafe_allow_html=True,
        )
        if report.issues:
            st.error(" · ".join(report.issues[:8]))
        st.caption(
            "La politique statique est une défense supplémentaire ; Docker constitue la frontière d’isolation."
        )
        with st.expander("Limites du runner", expanded=False):
            st.json(runner.limits.evidence())
    execution = _execution_controls(base_currency)
    actions = st.columns([1, 1, 1, 2])
    validate_clicked = actions[0].button(
        "Valider", key="bt_code_validate", width="stretch"
    )
    compile_clicked = actions[1].button(
        "Compiler Docker",
        key="bt_code_compile",
        disabled=not report.passed or not bool(digest),
        width="stretch",
    )
    run_clicked = actions[2].button(
        "Exécuter",
        key="bt_code_run",
        type="primary",
        disabled=not report.passed
        or not bool(digest)
        or dataset is None
        or bool(parameters_error),
        width="stretch",
    )
    actions[3].caption("Validate → Compile → Run · aucune promotion automatique")
    if validate_clicked:
        if report.passed:
            st.success(
                f"Politique {report.policy_version} validée · {report.source_bytes:,} octets · {report.source_sha256[:16]}"
            )
        else:
            st.error("Source refusée par la politique statique.")
    if compile_clicked:
        with st.spinner(f"Compilation {language.label} dans Docker…"):
            compiled = runner.compile(source, language)
        st.session_state["bt_code_last_compile"] = compiled
        if compiled.passed:
            st.success(
                f"Compilation attestée · {compiled.compiler} · {compiled.duration_ms} ms"
            )
        else:
            st.error("Compilation refusée · " + " · ".join(compiled.diagnostics[:8]))
    compiled = st.session_state.get("bt_code_last_compile")
    if compiled is not None and getattr(compiled, "language", None) == language:
        with st.expander("Dernier rapport de compilation", expanded=False):
            st.json(
                {
                    "status": compiled.status,
                    "language": compiled.language.value,
                    "compiler": compiled.compiler,
                    "duration_ms": compiled.duration_ms,
                    "source_sha256": compiled.source_sha256,
                    "image_digest": compiled.image_digest,
                    "diagnostics": list(compiled.diagnostics),
                }
            )
    if run_clicked and dataset is not None:
        try:
            with st.spinner(
                f"Run causal {language.label} · sandbox Docker → ledger universel…"
            ):
                sandbox = runner.run(
                    source=source,
                    language=language,
                    market_data=dataset.market_data,
                    parameters=parameters,
                    seed=execution["seed"],
                )
                price_basis, corporate_actions = _price_contract(bars)
                config = _engine_config(
                    base_currency=base_currency,
                    initial_cash=float(execution["initial_cash"]),
                    commission_bps=float(execution["commission"]),
                    spread_bps=float(execution["spread"]),
                    slippage_bps=float(execution["slippage"]),
                    max_participation=float(execution["participation"]),
                    allow_short=bool(execution["allow_short"]),
                    price_basis=price_basis,
                    apply_corporate_actions=corporate_actions,
                )
                config = type(config)(
                    **{
                        **config.__dict__,
                        "impact_bps_at_full_participation": float(execution["impact"]),
                    }
                )
                result = UniversalBacktestEngine(
                    security_master=dataset.security_master,
                    config=config,
                ).run(
                    market_data=dataset.market_data,
                    target_weights=sandbox.targets,
                    fx_rates=dataset.fx_rates,
                    cash_rates=dataset.cash_rates or {},
                    target_available_at=sandbox.target_available_at,
                )
                artifact = {
                    "kind": "sandbox_strategy",
                    "language": language.value,
                    "source_sha256": sandbox.source_sha256,
                    "dataset_sha256": _dataset_hash(dataset),
                    "sandbox": sandbox.evidence(),
                    "parameters": parameters,
                }
                envelope = build_universal_institutional_envelope(
                    result=result,
                    security_master=dataset.security_master,
                    market_data=dataset.market_data,
                    target_weights=sandbox.targets,
                    fx_rates=dataset.fx_rates,
                    cash_rates=dataset.cash_rates or {},
                    config=config,
                    strategy_name=f"Code · {language.label}",
                    strategy_mode=f"code:{language.value}",
                    strategy_artifact=artifact,
                    point_in_time_authenticated=False,
                    sandbox_attested=sandbox.attestation.passed,
                    calendar_authenticated=False,
                    execution_calibrated=False,
                    statistical_validation=None,
                    seed=execution["seed"],
                )
            record = {
                "run_id": envelope.manifest.run_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "ticker": str(ticker).upper(),
                "language": language,
                "currency": base_currency,
                "currency_authenticated": currency_authenticated,
                "dataset_sha256": artifact["dataset_sha256"],
                "envelope": envelope,
                "sandbox": sandbox,
            }
            record["analysis"] = {"execution": _execution_diagnostics(record)}
            runs = _runs()
            runs.append(record)
            del runs[:-20]
            st.session_state["bt_code_selected_run"] = record["run_id"]
            st.success(
                f"Run {record['run_id']} enregistré · {sandbox.bars_processed:,} barres · "
                f"{sandbox.signals_emitted:,} signaux · ledger universel réconcilié"
            )
            _run_metrics(record)
        except (
            SandboxUnavailableError,
            SandboxExecutionError,
            ValueError,
            RuntimeError,
        ) as exc:
            st.error(f"Run refusé sans résultat partiel · {exc}")


def _select_record(runs: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    if not runs:
        st.info("Aucun run de code exécuté dans cette session.")
        return None
    mapping = {str(item["run_id"]): item for item in reversed(runs)}
    selected = st.selectbox(
        "Run",
        list(mapping),
        format_func=lambda run_id: f"{run_id[-12:]} · {mapping[run_id]['language'].label} · {mapping[run_id]['created_at'][:19]} UTC",
        key=key,
    )
    return mapping[str(selected)]


def _render_runs(runs: list[dict[str, Any]]) -> None:
    record = _select_record(runs, "bt_code_runs_select")
    if record:
        _render_record(record, view_key="bt_code_run_view")


def _render_compare(runs: list[dict[str, Any]]) -> None:
    if len(runs) < 2:
        st.info("Exécutez au moins deux stratégies pour ouvrir la comparaison.")
        return
    rows: list[dict[str, Any]] = []
    for record in runs:
        envelope = record["envelope"]
        daily = envelope.execution.daily
        returns = (
            pd.to_numeric(daily.get("return"), errors="coerce").dropna()
            if "return" in daily
            else pd.Series(dtype=float)
        )
        rows.append(
            {
                "run_id": record["run_id"],
                "langage": record["language"].label,
                "créé_à": record["created_at"],
                "rendement_net": daily["nav"].iloc[-1] / daily["nav"].iloc[0] - 1.0
                if len(daily) > 1
                else np.nan,
                "sharpe": returns.mean() / returns.std(ddof=1) * np.sqrt(252.0)
                if len(returns) > 1 and returns.std(ddof=1) > 0
                else np.nan,
                "drawdown_max": pd.to_numeric(
                    daily.get("drawdown"), errors="coerce"
                ).min()
                if "drawdown" in daily
                else np.nan,
                "fills": len(envelope.execution.fills),
                "décision": envelope.gate.get("decision"),
                "source_sha256": record["sandbox"].source_sha256,
            }
        )
    comparison = pd.DataFrame(rows)
    st.dataframe(
        comparison.style.format(
            {"rendement_net": "{:.2%}", "sharpe": "{:.2f}", "drawdown_max": "{:.2%}"}
        ),
        width="stretch",
        hide_index=True,
    )
    st.caption(
        "Comparer une famille de candidats ne remplace pas un protocole purgé OOS ni la correction du multiple testing."
    )


def _render_validation(runs: list[dict[str, Any]]) -> None:
    record = _select_record(runs, "bt_code_validation_select")
    if not record:
        return
    envelope = record["envelope"]
    analysis = record.setdefault("analysis", {})
    analysis.setdefault("execution", _execution_diagnostics(record))

    st.markdown("### Validation institutionnelle")
    st.caption(
        "Les diagnostics partent exclusivement des rendements du ledger exécuté. "
        "Une sortie UNAVAILABLE reste bloquante et n’est jamais remplacée par une approximation rassurante."
    )
    actions = st.columns([1, 1, 2])
    run_scenarios = actions[0].button(
        "Lancer stress & liquidité",
        key="bt_code_run_scenarios",
        type="primary",
        width="stretch",
    )
    run_statistics = actions[1].button(
        "Lancer robustesse statistique",
        key="bt_code_run_statistics",
        width="stretch",
    )
    actions[2].caption(
        "500 trajectoires · horizon 126 périodes · bootstrap, Student-t, Markov, EVT, liquidity spiral et reverse stress"
    )

    if run_scenarios:
        try:
            with st.spinner("Génération des scénarios institutionnels…"):
                scenario_result = run_institutional_scenario_suite(
                    _executed_returns(record),
                    config=ScenarioConfig(
                        horizon_days=126,
                        paths=500,
                        seed=41,
                        confidence=0.975,
                        liquidity_cost_bps=35.0,
                        target_drawdown=-0.20,
                        policy="institutional",
                    ),
                )
            analysis["scenarios"] = _compact_scenarios(scenario_result)
            liquidity = analysis["scenarios"]["availability"].get(
                "Liquidity spiral", {}
            )
            if liquidity.get("state") == "AVAILABLE":
                st.success(
                    "Spirale de liquidité (liquidity trap) calculée sur les rendements exécutés."
                )
            else:
                st.warning(
                    "Spirale de liquidité indisponible · "
                    + str(liquidity.get("reason", "preuve insuffisante"))
                )
        except Exception as exc:
            analysis["scenario_error"] = str(exc)
            st.error(f"Stress institutionnel indisponible · {exc}")

    if run_statistics:
        try:
            selected_returns = _executed_returns(record)
            candidate_series = {
                str(item["run_id"]): _executed_returns(item) for item in runs
            }
            candidates = (
                pd.concat(candidate_series, axis=1) if candidate_series else None
            )
            with st.spinner("PSR, DSR, PBO, Reality Check, SPA et CPCV purgé…"):
                analysis["statistics"] = institutional_validation_suite(
                    selected_returns,
                    candidates=candidates,
                    num_trials=max(len(candidate_series), 1),
                    bootstrap_samples=500,
                    seed=41,
                    periods=252,
                    cpcv_test_folds=2,
                    cpcv_total_folds=6,
                    cpcv_purge=5,
                    cpcv_embargo=5,
                )
            st.success(
                "Validation statistique terminée · les preuves manquantes restent explicitement UNAVAILABLE."
            )
        except Exception as exc:
            analysis["statistics_error"] = str(exc)
            st.error(f"Robustesse statistique indisponible · {exc}")

    st.markdown("#### Couverture des outils")
    coverage = _tool_coverage(record)
    st.dataframe(coverage, width="stretch", hide_index=True)

    decision = str(envelope.gate.get("decision", "HOLD — DATA REQUIRED"))
    blockers = envelope.gate.get("blocking_gates") or []
    if decision == "RESEARCH APPROVED":
        st.success(decision)
    else:
        st.warning(decision + " · " + " · ".join(map(str, blockers[:5])))
    _gate_grid(envelope)

    execution = dict(analysis.get("execution") or {})
    metrics = st.columns(6)
    metrics[0].metric("Fills", str(execution.get("fills", 0)))
    metrics[1].metric("Ordres non remplis", str(execution.get("orders_not_filled", 0)))
    metrics[2].metric("Liquidations forcées", str(execution.get("forced_fills", 0)))
    metrics[3].metric(
        "Participation max",
        _percent(execution.get("max_participation")),
    )
    metrics[4].metric(
        "Impact max",
        "—"
        if not np.isfinite(float(execution.get("max_impact_bps", np.nan)))
        else f"{float(execution['max_impact_bps']):.2f} bps",
    )
    metrics[5].metric(
        "Réconciliation",
        "PASS" if execution.get("accounting_reconciled") else "FAIL",
    )

    scenarios = dict(analysis.get("scenarios") or {})
    summary = scenarios.get("summary")
    if isinstance(summary, pd.DataFrame) and not summary.empty:
        st.markdown("#### Scénarios extrêmes et liquidity trap")
        st.dataframe(
            summary.style.format(
                {
                    "median_terminal_return": "{:.2%}",
                    "p05_terminal_return": "{:.2%}",
                    "expected_shortfall": "{:.2%}",
                    "median_max_drawdown": "{:.2%}",
                    "p05_max_drawdown": "{:.2%}",
                    "breach_probability": "{:.1%}",
                }
            ),
            width="stretch",
        )
        availability = (
            pd.DataFrame.from_dict(scenarios.get("availability") or {}, orient="index")
            .reset_index()
            .rename(columns={"index": "Scénario"})
        )
        st.dataframe(availability, width="stretch", hide_index=True)
        st.json(
            {
                "reverse_stress": scenarios.get("reverse_stress"),
                "evt": scenarios.get("evt"),
                "regime_mix": scenarios.get("regime_mix"),
                "policy": scenarios.get("policy"),
            }
        )

    statistics = dict(analysis.get("statistics") or {})
    if statistics:
        st.markdown("#### Surapprentissage et multiple testing")
        stat_rows = []
        for label, key in (
            ("PSR", "psr"),
            ("DSR", "dsr"),
            ("PBO / CSCV", "pbo"),
            ("White Reality Check", "white_reality_check"),
            ("Hansen SPA", "hansen_spa"),
            ("CPCV purgé", "cpcv"),
        ):
            value = statistics.get(key)
            state = "UNAVAILABLE"
            reason = "preuve non fournie"
            if isinstance(value, Mapping):
                available = value.get("available")
                declared = str(value.get("state", "")).upper()
                state = (
                    "AVAILABLE"
                    if available is True or declared == "AVAILABLE"
                    else "UNAVAILABLE"
                    if available is False or declared == "UNAVAILABLE"
                    else "CALCULATED"
                )
                reason = str(
                    value.get("reason") or value.get("method") or "diagnostic calculé"
                )
            stat_rows.append({"Test": label, "État": state, "Lecture": reason})
        st.dataframe(pd.DataFrame(stat_rows), width="stretch", hide_index=True)
        with st.expander("Diagnostics statistiques complets", expanded=False):
            st.json(statistics)

    st.json(
        {
            "research_only": True,
            "automatic_production_authorization": False,
            "sandbox_attested": record["sandbox"].attestation.passed,
            "causal_streaming": record["sandbox"].diagnostics.get("causal_streaming"),
            "future_data_exposed": record["sandbox"].diagnostics.get(
                "future_data_exposed"
            ),
            "point_in_time_authenticated": envelope.manifest.metadata.get(
                "point_in_time"
            ),
        }
    )


def _render_evidence(runs: list[dict[str, Any]]) -> None:
    record = _select_record(runs, "bt_code_evidence_select")
    if not record:
        return
    envelope = record["envelope"]
    sandbox = record["sandbox"]
    columns = st.columns(4)
    columns[0].metric("Run", record["run_id"][-12:])
    columns[1].metric("Code SHA", sandbox.source_sha256[:12])
    columns[2].metric("Image SHA", sandbox.image_digest[7:19])
    columns[3].metric(
        "Signature", "VÉRIFIÉE" if sandbox.attestation.signature_verified else "ABSENTE"
    )
    st.download_button(
        "Télécharger le dossier reproductible",
        data=envelope.bundle,
        file_name=f"{record['run_id']}.zip",
        mime="application/zip",
        key="bt_code_evidence_bundle",
        type="primary",
        width="stretch",
    )
    analysis = dict(record.get("analysis") or {})
    if analysis:

        def json_default(value: Any) -> Any:
            if isinstance(value, pd.DataFrame):
                return {
                    "index": [str(item) for item in value.index],
                    "records": value.reset_index(drop=True).to_dict(orient="records"),
                }
            if isinstance(value, pd.Series):
                return {str(key): item for key, item in value.items()}
            if isinstance(value, (np.integer, np.floating)):
                return value.item()
            if isinstance(value, np.ndarray):
                return value.tolist()
            return str(value)

        validation_payload = (
            json.dumps(
                analysis,
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
                default=json_default,
            )
            + "\n"
        ).encode("utf-8")
        st.download_button(
            "Télécharger les diagnostics de validation",
            data=validation_payload,
            file_name=f"{record['run_id']}-validation.json",
            mime="application/json",
            key="bt_code_validation_bundle",
            width="stretch",
        )
    st.json(
        {
            "manifest": {
                "run_id": envelope.manifest.run_id,
                "config_hash": envelope.manifest.config_hash,
                "data_hash": envelope.manifest.data_hash,
                "code_hash": envelope.manifest.code_hash,
            },
            "sandbox": sandbox.evidence(),
            "gate": envelope.gate,
        }
    )


def render_code_workspace(*, ticker: str, bars: pd.DataFrame, cfg: Any) -> None:
    """Render the primary Backtest Lab experience."""

    _inject_css()
    _render_hero(ticker)
    workflow = _segmented("Workflow", _WORKFLOW, "bt_code_workflow", _STUDIO)
    runs = _runs()
    if workflow == _STUDIO:
        _render_studio(ticker, bars, cfg)
    elif workflow == _RUNS:
        _render_runs(runs)
    elif workflow == _COMPARE:
        _render_compare(runs)
    elif workflow == _VALIDATION:
        _render_validation(runs)
    else:
        _render_evidence(runs)


__all__ = ["render_code_workspace"]
