"""Facade that composes data, execution, validation, scenarios and governance."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd

from .data_catalog import DataCatalogAssessment, assess_market_data
from .execution import ExecutionModelConfig, simulate_execution
from .registry import build_run_manifest
from .reporting import build_governance_bundle, build_model_card
from .scenarios import ScenarioConfig, run_institutional_scenario_suite
from .statistics import (
    benjamini_hochberg,
    holm_bonferroni,
    institutional_validation_suite,
    purged_combinatorial_splits,
)
from .types import AvailabilityState, RunManifest, ValidationState


@dataclass
class InstitutionalRun:
    manifest: RunManifest
    data_catalog: DataCatalogAssessment
    execution: Any
    validation: dict[str, Any]
    scenarios: dict[str, Any]
    gate: dict[str, Any]
    model_card: dict[str, Any]
    bundle: bytes


def _legacy_frame(result: dict[str, Any]) -> pd.DataFrame:
    frame = result.get("data")
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise ValueError(result.get("error", "Legacy backtest result has no data"))
    return frame.copy()


def _gate(
    catalog: DataCatalogAssessment,
    execution: Any,
    validation: dict[str, Any],
    scenarios: dict[str, Any],
) -> dict[str, Any]:
    checks = []
    checks.append({
        "gate": "Data integrity",
        "state": catalog.verdict.value,
        "detail": "; ".join(catalog.issues[:3]) or "Core data contract passed",
    })
    execution_state = execution.status.value
    checks.append({"gate": "Event execution", "state": execution_state, "detail": execution.reason})
    dsr = float(validation.get("dsr", {}).get("deflated_sharpe_probability", np.nan))
    checks.append({
        "gate": "Deflated Sharpe",
        "state": "PASS" if np.isfinite(dsr) and dsr >= 0.95 else ("WARN" if np.isfinite(dsr) and dsr >= 0.80 else "FAIL"),
        "detail": f"DSR probability {dsr:.1%}" if np.isfinite(dsr) else "DATA REQUIRED",
    })
    pbo = float(validation.get("pbo", {}).get("pbo", np.nan))
    checks.append({
        "gate": "Selection overfit",
        "state": "PASS" if np.isfinite(pbo) and pbo <= 0.20 else ("WARN" if np.isfinite(pbo) and pbo <= 0.50 else ("FAIL" if np.isfinite(pbo) else "UNAVAILABLE")),
        "detail": f"PBO {pbo:.1%}" if np.isfinite(pbo) else "DATA REQUIRED: candidate family",
    })
    summary = scenarios.get("summary", pd.DataFrame())
    worst_es = float(summary["expected_shortfall"].min()) if isinstance(summary, pd.DataFrame) and not summary.empty else np.nan
    checks.append({
        "gate": "Scenario resilience",
        "state": "PASS" if np.isfinite(worst_es) and worst_es > -0.25 else ("WARN" if np.isfinite(worst_es) and worst_es > -0.45 else "FAIL"),
        "detail": f"Worst terminal ES {worst_es:.1%}" if np.isfinite(worst_es) else "DATA REQUIRED",
    })
    states = [row["state"] for row in checks]
    if "FAIL" in states:
        decision = "REJECT / REDESIGN"
    elif "UNAVAILABLE" in states:
        decision = "HOLD — DATA REQUIRED"
    elif "WARN" in states or "PARTIAL" in states:
        decision = "CONDITIONAL REVIEW"
    else:
        decision = "RESEARCH APPROVED"
    return {
        "decision": decision,
        "checks": pd.DataFrame(checks),
        "fail_closed": True,
        "production_authorized": False,
    }


def run_institutional_stack(
    *,
    bars: pd.DataFrame,
    legacy_result: dict[str, Any],
    strategy: str,
    symbol: str,
    config_payload: dict[str, Any],
    execution_config: ExecutionModelConfig | None = None,
    scenario_config: ScenarioConfig | None = None,
    candidate_returns: pd.DataFrame | None = None,
    factor_returns: pd.DataFrame | None = None,
    seed: int = 41,
    point_in_time: bool = False,
    source: str = "Active market-data adapter",
) -> InstitutionalRun:
    legacy = _legacy_frame(legacy_result)
    target = pd.to_numeric(legacy["exposure"], errors="coerce").reindex(bars.index).ffill().fillna(0.0)
    returns = pd.to_numeric(legacy["strategy_return"], errors="coerce").dropna()
    execution_config = execution_config or ExecutionModelConfig(initial_capital=float(config_payload.get("capital", 1_000_000.0)))
    scenario_config = scenario_config or ScenarioConfig(seed=seed)
    catalog = assess_market_data(
        bars,
        symbol=symbol,
        source=source,
        point_in_time=point_in_time,
        required_capabilities=("bar_execution", "volume_impact" if execution_config.model != "constant" else "bar_execution"),
    )
    execution = simulate_execution(
        bars,
        target,
        symbol=symbol,
        config=execution_config,
    )
    candidates = candidate_returns
    if candidates is not None and not candidates.empty:
        candidates = candidates.reindex(returns.index).apply(pd.to_numeric, errors="coerce")
    validation = institutional_validation_suite(
        returns,
        candidates=candidates,
        num_trials=max(1, 1 if candidates is None else candidates.shape[1]),
        bootstrap_samples=350,
        seed=seed,
    )
    # Explicit family-wise and false-discovery controls for candidate p-values.
    candidate_p = []
    if candidates is not None and not candidates.empty:
        for column in candidates:
            series = pd.to_numeric(candidates[column], errors="coerce").dropna()
            if len(series) < 3 or series.std(ddof=1) <= 0:
                candidate_p.append(np.nan)
            else:
                z = series.mean() / (series.std(ddof=1) / np.sqrt(len(series)))
                candidate_p.append(float(2.0 * (1.0 - 0.5 * (1.0 + __import__("math").erf(abs(z) / np.sqrt(2.0))))))
    validation["holm"] = holm_bonferroni(candidate_p).to_dict(orient="records") if candidate_p else []
    validation["benjamini_hochberg"] = benjamini_hochberg(candidate_p).to_dict(orient="records") if candidate_p else []
    validation["cpcv_splits"] = len(purged_combinatorial_splits(len(returns))) if len(returns) >= 30 else 0
    scenarios = run_institutional_scenario_suite(
        returns,
        factor_returns=factor_returns,
        config=scenario_config,
    )
    manifest = build_run_manifest(
        config=config_payload | {
            "execution": asdict(execution_config),
            "scenario": asdict(scenario_config),
            "point_in_time": point_in_time,
        },
        market_data=bars,
        strategy=strategy,
        symbol=symbol,
        seed=seed,
        tags=("institutional-v7", "research"),
        metadata={"legacy_rows": len(legacy), "candidate_count": validation["candidate_count"]},
    )
    gate = _gate(catalog, execution, validation, scenarios)
    scenario_metadata = {
        "summary": scenarios["summary"].to_dict(orient="index"),
        "reverse_stress": scenarios["reverse_stress"],
        "evt": scenarios["evt"],
        "regime_mix": scenarios["regime_mix"],
        "seed": scenarios["seed"],
    }
    model_card = build_model_card(
        manifest=manifest,
        data_catalog=catalog.to_dict(),
        execution=execution.diagnostics,
        validation=validation,
        scenarios=scenario_metadata,
    )
    tables = {
        "legacy_backtest": legacy,
        "scenario_summary": scenarios["summary"],
        "gate_checks": gate["checks"],
    }
    if execution.daily is not None:
        tables["execution_daily"] = execution.daily
    if execution.fills:
        tables["fills"] = pd.DataFrame(execution.records()["fills"])
    bundle = build_governance_bundle(
        manifest=manifest,
        config=config_payload,
        data_catalog=catalog.to_dict(),
        execution=execution.diagnostics | {"status": execution.status.value, "reason": execution.reason},
        validation=validation,
        scenarios=scenario_metadata,
        tables=tables,
    )
    return InstitutionalRun(manifest, catalog, execution, validation, scenarios, gate, model_card, bundle)
