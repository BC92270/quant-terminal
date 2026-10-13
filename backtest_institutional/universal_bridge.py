"""Governance bridge from the universal ledger to institutional evidence."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from io import BytesIO
import json
from typing import Any, Mapping
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import numpy as np
import pandas as pd

from backtest_universal import UniversalEngineConfig, UniversalRunResult
from backtest_universal.security import SecurityMaster

from .registry import build_run_manifest, stable_hash
from .types import RunManifest


@dataclass
class UniversalInstitutionalEnvelope:
    manifest: RunManifest
    execution: UniversalRunResult
    gate: dict[str, Any]
    model_card: dict[str, Any]
    bundle: bytes
    authoritative_source: str = "oms_execution_ledger"


def _long_market_frame(market_data: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for instrument_id, frame in sorted(market_data.items()):
        clean = frame.copy()
        clean.insert(0, "instrument_id", str(instrument_id))
        clean.insert(0, "event_time", pd.DatetimeIndex(clean.index))
        rows.append(clean.reset_index(drop=True))
    return pd.concat(rows, ignore_index=True, sort=False) if rows else pd.DataFrame()


def _checks(
    result: UniversalRunResult,
    *,
    point_in_time_authenticated: bool,
    strategy_mode: str,
    sandbox_attested: bool,
    calendar_authenticated: bool,
    execution_calibrated: bool,
    statistical_validation: Mapping[str, Any] | None,
) -> list[dict[str, str]]:
    ledger_state = (
        "PASS" if result.status == "AVAILABLE" else "WARN" if result.status == "PARTIAL" else "FAIL"
    )
    margin_available = bool(
        not result.daily.empty
        and result.daily.get("margin_available", pd.Series(dtype=bool)).fillna(False).all()
    )
    margin_breached = bool(
        int(result.diagnostics.get("margin_calls") or 0) > 0
        or result.diagnostics.get("portfolio_insolvent")
        or result.diagnostics.get("unresolved_margin_deficit")
        or (
            not result.daily.empty
            and (
                pd.to_numeric(
                    result.daily.get("maintenance_excess"), errors="coerce"
                ).fillna(float("-inf"))
                < -1e-8
            ).any()
        )
    )
    normalized_mode = str(strategy_mode).strip().lower()
    code_mode = normalized_mode in {
        "python", "python_strategy", "javascript", "typescript", "cpp",
        "rust", "csharp", "code",
    } or normalized_mode.startswith("code:")
    statistical = dict(statistical_validation or {})
    statistical_requirements = (
        "purged_oos_pass",
        "multiple_testing_pass",
        "scenario_resilience_pass",
    )
    statistical_supplied = all(name in statistical for name in statistical_requirements)
    statistical_pass = statistical_supplied and all(
        bool(statistical[name]) for name in statistical_requirements
    )
    statistical_state = (
        "PASS" if statistical_pass else "FAIL" if statistical_supplied else "UNAVAILABLE"
    )
    lifecycle_gaps = list(result.diagnostics.get("lifecycle_gaps") or [])
    oms_reconciled = bool(
        result.diagnostics.get("oms_authoritative")
        and result.diagnostics.get("oms_ledger_reconciled")
    )
    feedback_connected = bool(
        result.diagnostics.get("signal_source") == "causal_strategy_runtime"
        and int(result.diagnostics.get("portfolio_feedback_slices") or 0) > 0
        and result.diagnostics.get("last_portfolio_ledger_sha256")
    )
    return [
        {
            "gate": "Universal event ledger",
            "state": ledger_state,
            "detail": result.reason,
        },
        {
            "gate": "OMS execution authority",
            "state": "PASS" if oms_reconciled else "FAIL",
            "detail": "OMS fills, engine journal and portfolio ledger reconcile"
            if oms_reconciled
            else "OMS and accounting fill ledgers do not reconcile",
        },
        {
            "gate": "Causal portfolio feedback",
            "state": "PASS"
            if not code_mode or feedback_connected
            else "UNAVAILABLE",
            "detail": "OMS snapshot was delivered before every code callback"
            if code_mode and feedback_connected
            else "not required for precomputed/native targets"
            if not code_mode
            else "code runtime did not receive authoritative portfolio feedback",
        },
        {
            "gate": "Point-in-time data contract",
            "state": "PASS" if point_in_time_authenticated else "UNAVAILABLE",
            "detail": "signed point-in-time snapshot verified"
            if point_in_time_authenticated
            else "signed point-in-time dataset manifest required",
        },
        {
            "gate": "Causal target clock",
            "state": "PASS" if result.diagnostics.get("causal_inputs_only") else "FAIL",
            "detail": str(result.diagnostics.get("target_timing_contract", "unavailable")),
        },
        {
            "gate": "Causal target completion",
            "state": "PASS"
            if not result.diagnostics.get("terminal_target_changes_without_execution")
            else "UNAVAILABLE",
            "detail": "every material target change reached a later eligible bar"
            if not result.diagnostics.get("terminal_target_changes_without_execution")
            else "material terminal target changes had no later executable bar",
        },
        {
            "gate": "Exchange calendar contract",
            "state": "PASS" if calendar_authenticated else "UNAVAILABLE",
            "detail": "authenticated sessions, holidays and time zone"
            if calendar_authenticated
            else "exchange session/calendar evidence required",
        },
        {
            "gate": "Multi-currency cashbook",
            "state": "PASS" if result.diagnostics.get("multi_currency_cashbook") else "FAIL",
            "detail": "historical conversions included in the ledger",
        },
        {
            "gate": "Accounting reconciliation",
            "state": "PASS"
            if result.diagnostics.get("accounting_reconciled")
            else "FAIL",
            "detail": "cash, positions and final NAV reconcile"
            if result.diagnostics.get("accounting_reconciled")
            else "ledger outputs do not reconcile to final NAV",
        },
        {
            "gate": "Settlement and margin",
            "state": "FAIL"
            if margin_breached
            else "PASS"
            if margin_available
            else "UNAVAILABLE",
            "detail": "settlement and margin reconciled"
            if margin_available and not margin_breached
            else "margin call, insolvency or maintenance deficit detected"
            if margin_breached
            else "clearing or broker margin evidence incomplete",
        },
        {
            "gate": "Cash carry and capital cost",
            "state": "PASS"
            if result.diagnostics.get("cash_carry_available")
            else "UNAVAILABLE",
            "detail": "historical cash remuneration/funding applied by currency"
            if result.diagnostics.get("cash_carry_available")
            else "historical cash-rate curves required for every ledger currency",
        },
        {
            "gate": "Instrument lifecycle",
            "state": "PASS" if not lifecycle_gaps else "UNAVAILABLE",
            "detail": "no unresolved lifecycle event"
            if not lifecycle_gaps
            else "; ".join(str(item) for item in lifecycle_gaps[:3]),
        },
        {
            "gate": "Execution calibration",
            "state": "PASS" if execution_calibrated else "UNAVAILABLE",
            "detail": "spread, slippage and impact calibration authenticated"
            if execution_calibrated
            else "venue/instrument execution calibration required",
        },
        {
            "gate": "Statistical robustness",
            "state": statistical_state,
            "detail": "purged OOS, multiple-testing and scenarios passed"
            if statistical_pass
            else "purged OOS, multiple-testing and scenario evidence required",
        },
        {
            "gate": "Strategy sandbox",
            "state": "PASS" if not code_mode or sandbox_attested else "UNAVAILABLE",
            "detail": "native/target strategy; no user code executed"
            if not code_mode
            else "attested OCI runner verified"
            if sandbox_attested
            else "attested isolated runner required; host execution forbidden",
        },
    ]


def _decision(checks: list[dict[str, str]]) -> tuple[str, list[str]]:
    blockers = [item["gate"] for item in checks if item["state"] in {"FAIL", "UNAVAILABLE"}]
    if any(item["state"] == "FAIL" for item in checks):
        return "REJECT / REDESIGN", blockers
    if any(item["state"] == "UNAVAILABLE" for item in checks):
        return "HOLD — DATA REQUIRED", blockers
    if any(item["state"] == "WARN" for item in checks):
        return "CONDITIONAL REVIEW", blockers
    return "RESEARCH APPROVED", []


def _zip_write(archive: ZipFile, name: str, payload: bytes) -> None:
    info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = ZIP_DEFLATED
    info.external_attr = 0o600 << 16
    archive.writestr(info, payload)


def _bundle(
    manifest: RunManifest,
    result: UniversalRunResult,
    gate: Mapping[str, Any],
    model_card: Mapping[str, Any],
) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        manifest_payload = asdict(manifest)
        if isinstance(manifest_payload.get("metadata"), dict):
            manifest_payload["metadata"].pop("_bundle_evidence", None)
        for name, value in (
            ("manifest.json", manifest_payload),
            ("gate.json", dict(gate)),
            ("model_card.json", dict(model_card)),
        ):
            _zip_write(
                archive,
                name,
                (json.dumps(value, indent=2, sort_keys=True, default=str) + "\n").encode("utf-8"),
            )
        for name, frame in (
            ("tables/valuations.csv", result.daily),
            ("tables/orders.csv", result.orders),
            ("tables/fills.csv", result.fills),
            ("tables/events.csv", result.events),
            ("tables/positions.csv", result.positions),
            ("tables/cashbook.csv", result.cash),
        ):
            _zip_write(
                archive,
                name,
                (frame.to_csv(index=True) if isinstance(frame, pd.DataFrame) else "").encode("utf-8"),
            )
    return buffer.getvalue()


def build_universal_institutional_envelope(
    *,
    result: UniversalRunResult,
    security_master: SecurityMaster,
    market_data: Mapping[str, pd.DataFrame],
    target_weights: pd.DataFrame,
    fx_rates: Mapping[str, pd.Series],
    cash_rates: Mapping[str, pd.Series] | None = None,
    config: UniversalEngineConfig,
    strategy_name: str,
    strategy_mode: str = "native",
    strategy_artifact: Mapping[str, Any] | None = None,
    point_in_time_authenticated: bool = False,
    sandbox_attested: bool = False,
    calendar_authenticated: bool = False,
    execution_calibrated: bool = False,
    statistical_validation: Mapping[str, Any] | None = None,
    seed: int = 41,
) -> UniversalInstitutionalEnvelope:
    instruments = security_master.records()
    market = _long_market_frame(market_data)
    artifacts = {
        "security_master": instruments,
        "target_weights": target_weights,
        "fx_rates": dict(fx_rates),
        "cash_rates": dict(cash_rates or {}),
        "event_journal": result.events,
        "universal_diagnostics": result.diagnostics,
        "strategy_artifact": dict(strategy_artifact or {}),
        "statistical_validation": dict(statistical_validation or {}),
    }
    symbols = tuple(sorted(str(item["instrument_id"]) for item in instruments))
    manifest = build_run_manifest(
        config=asdict(config),
        market_data=market,
        strategy=strategy_name,
        symbol="PORTFOLIO[" + ",".join(symbols) + "]",
        seed=int(seed),
        code_path="backtest_lab.py",
        engine_version="universal-0.3.0",
        tags=("UNIVERSAL_KERNEL", "OMS_AUTHORITY", "RESEARCH_ONLY"),
        metadata={
            "base_currency": config.base_currency,
            "point_in_time": bool(point_in_time_authenticated),
            "strategy_mode": strategy_mode,
            "sandbox_attested": bool(sandbox_attested),
            "calendar_authenticated": bool(calendar_authenticated),
            "execution_calibrated": bool(execution_calibrated),
            "security_master_hash": stable_hash(instruments),
            "universe": list(symbols),
        },
        additional_artifacts=artifacts,
    )
    checks = _checks(
        result,
        point_in_time_authenticated=point_in_time_authenticated,
        strategy_mode=strategy_mode,
        sandbox_attested=sandbox_attested,
        calendar_authenticated=calendar_authenticated,
        execution_calibrated=execution_calibrated,
        statistical_validation=statistical_validation,
    )
    decision, blockers = _decision(checks)
    gate = {
        "decision": decision,
        "checks": checks,
        "blocking_gates": blockers,
        "fail_closed": True,
        "research_only": True,
        "automatic_production_authorization": False,
        "run_id": manifest.run_id,
        "authoritative_source": "oms_execution_ledger",
    }
    daily = result.daily
    returns = (
        pd.to_numeric(daily.get("return"), errors="coerce").dropna()
        if isinstance(daily, pd.DataFrame) and "return" in daily
        else pd.Series(dtype=float)
    )
    model_card = {
        "model": "Universal Backtest Kernel",
        "version": "0.3.0",
        "purpose": "Multi-asset and multi-currency research simulation",
        "authoritative_source": "oms_execution_ledger",
        "native_capabilities": [
            "causal next-bar target execution",
            "multi-currency cashbook and historical FX conversion",
            "settled and unsettled cash",
            "asset-aware initial and maintenance margin",
            "variation margin, funding, rollover, borrow and lifecycle accounting",
            "OMS-authoritative order/fill transitions reconciled to the portfolio ledger",
            "causal OMS portfolio feedback contract for isolated strategy runtimes",
            "cash and physical option exercise/assignment reference lifecycle",
            "versioned SPAN, SIMM, OCC-TIMS and portfolio-margin reference adapters",
            "deterministic real-versus-synthetic L2/L3 replay foundation",
            "idempotent distributed-job and content-addressed artifact contracts",
        ],
        "limitations": [
            "the default execution model remains bar-event unless an authenticated L2/L3 feed is attached",
            "the L2/L3 replay core is not an exchange-certified matching engine",
            "exchange holiday calendars require an external calendar adapter",
            "physical option lifecycle requires point-in-time venue calendars and deliverables",
            "SPAN, SIMM, OCC-TIMS and broker portfolio margin require official versioned parameter packages",
            "the bundled distributed coordinator is a local reference, not a deployed cluster",
            "user code requires a separately attested OCI sandbox",
            "production authorization is never automatic",
        ],
        "observations": int(len(daily)),
        "total_return": (
            float(daily["nav"].iloc[-1] / daily["nav"].iloc[0] - 1.0)
            if isinstance(daily, pd.DataFrame) and len(daily) > 1
            else np.nan
        ),
        "volatility": float(returns.std(ddof=1) * np.sqrt(config.periods_per_year))
        if len(returns) > 1
        else np.nan,
        "status": result.status,
    }
    bundle = _bundle(manifest, result, gate, model_card)
    return UniversalInstitutionalEnvelope(manifest, result, gate, model_card, bundle)
