from __future__ import annotations

import hashlib
import json
import math
import platform
import random
import statistics
import sys
import uuid
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

from .phase4_models import (
    BaselineSpec,
    DatasetContract,
    ExperimentRunResult,
    ExperimentSpecification,
    ReplicationPlan,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_id(prefix: str, *parts: str) -> str:
    payload = "|".join(str(p or "").strip().lower() for p in parts)
    return f"{prefix}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"


def _asdict(value: Any) -> dict[str, Any]:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Mapping):
        return dict(value)
    raise TypeError("Expected dataclass or mapping")


def _canonical_variable(value: str) -> str:
    token = str(value or "").strip().lstrip("\\").replace("{", "").replace("}", "")
    return token


def _mapping_rows(candidate: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = candidate.get("variable_mappings") or []
    return [dict(x) for x in rows if isinstance(x, Mapping)]


def _target_for_source(candidate: Mapping[str, Any], source_names: Iterable[str]) -> str:
    wanted = {_canonical_variable(x) for x in source_names}
    for row in _mapping_rows(candidate):
        if _canonical_variable(str(row.get("source_variable") or "")) in wanted:
            return str(row.get("target_variable") or "").strip()
    return ""


def recognize_experimental_family(candidate: Any) -> str:
    row = _asdict(candidate)
    equation = str(row.get("source_equation") or "")
    eq_type = str(row.get("source_equation_type") or "").upper()
    normalized = equation.replace(" ", "").lower()
    # Narrow, explicit support only: Ornstein-Uhlenbeck / linear mean-reverting SDE.
    has_state = "dX_t" in equation or "dx_t" in normalized or "dx=" in normalized
    has_kappa = "kappa" in normalized or "\\kappa" in equation
    has_sigma = "sigma" in normalized or "\\sigma" in equation
    has_noise = "dW" in equation or "dw" in normalized
    has_mean_reversion = "-" in equation and ("X_t" in equation or "x_t" in normalized)
    if eq_type == "SDE" and has_state and has_kappa and has_sigma and has_noise and has_mean_reversion:
        return "OU_MEAN_REVERTING_SDE"
    return "UNSUPPORTED_RESEARCH_FAMILY"


def build_experiment_specification(
    candidate: Any,
    transfer_audit: Any,
    stage: str = "SYNTHETIC_SANITY",
    train_fraction: float = 0.70,
    seed: int = 17,
) -> ExperimentSpecification:
    c = _asdict(candidate)
    a = _asdict(transfer_audit)
    verdict = str(a.get("verdict") or "")
    blockers: list[str] = []
    if verdict != "PARTIAL_TRANSFER":
        blockers.append("Phase 4 requires a PARTIAL_TRANSFER audit; weaker transfer verdicts cannot become executable experiments.")
    if str(c.get("stage") or "") != "PRE_FORMALIZATION":
        blockers.append("Candidate is not a Phase-3 pre-formalization object.")
    if float(c.get("mapping_coverage") or 0.0) < 0.8:
        blockers.append("Variable mapping coverage must be at least 80%.")
    if not str(c.get("causal_hypothesis") or "").strip():
        blockers.append("Causal hypothesis is required before experimentation.")
    if not str(c.get("falsification_test") or "").strip():
        blockers.append("Falsification rule is required before experimentation.")

    family = recognize_experimental_family(c)
    if family == "UNSUPPORTED_RESEARCH_FAMILY":
        blockers.append("No audited built-in executor exists for this equation family. Arbitrary generated code is not executed in Phase 4.")

    state_target = _target_for_source(c, ("X_t", "dX_t", "X", "x_t"))
    if not state_target:
        blockers.append("A mapped target state variable for X_t is required.")

    train_fraction = min(0.9, max(0.5, float(train_fraction)))
    contract = DatasetContract(
        contract_id=_stable_id("DATA", str(c.get("candidate_id")), stage, state_target),
        created_at=_now_iso(),
        source_kind="SYNTHETIC_OR_USER_HISTORICAL",
        target_variable=state_target or "mapped_state",
        train_fraction=train_fraction,
        required_columns=(state_target,) if state_target else (),
        notes=(
            "No target-domain scientific validity is implied by execution success.",
            "Historical execution uses chronological out-of-sample evaluation only.",
        ),
    )
    baselines = (
        BaselineSpec(
            baseline_id="BASELINE-RANDOM-WALK",
            name="Random Walk / Last Observation",
            family="NAIVE_LAST_VALUE",
            description="One-step forecast equals the last observed state.",
        ),
        BaselineSpec(
            baseline_id="BASELINE-TRAIN-MEAN",
            name="Training Mean",
            family="CONSTANT_MEAN",
            description="Forecast equals the mean estimated on the training sample only.",
        ),
    )
    status = "BLOCKED" if blockers else "READY"
    experiment_id = _stable_id(
        "EXPERIMENT",
        str(c.get("candidate_id")),
        str(a.get("audit_id")),
        stage,
        family,
        state_target,
    )
    return ExperimentSpecification(
        experiment_id=experiment_id,
        created_at=_now_iso(),
        candidate_id=str(c.get("candidate_id") or ""),
        transfer_audit_id=str(a.get("audit_id") or ""),
        transfer_verdict=verdict,
        stage=stage,
        status=status,
        experimental_family=family,
        source_equation_type=str(c.get("source_equation_type") or ""),
        hypothesis=str(c.get("causal_hypothesis") or "").strip(),
        null_hypothesis=(
            f"The mapped {state_target or 'target state'} dynamics provide no out-of-sample improvement over simple baselines."
        ),
        falsification_rule=str(c.get("falsification_test") or "").strip(),
        target_variable=state_target or "mapped_state",
        mapped_variables=tuple(
            str(row.get("target_variable") or "").strip()
            for row in _mapping_rows(c)
            if str(row.get("target_variable") or "").strip()
        ),
        metrics=("RMSE", "MAE", "DIRECTIONAL_ACCURACY"),
        baselines=baselines,
        dataset_contract=contract,
        seed=int(seed),
        blockers=tuple(blockers),
        warnings=(
            "Phase 4 executes only audited built-in experiment families; it never evals or execs LLM-generated source code.",
            "A successful experiment is computational evidence, not validation that the source-domain theory transfers to finance.",
            "Production promotion is disabled in Phase 4.",
        ),
    )


def dataset_fingerprint(values: Sequence[float], labels: Sequence[str] | None = None) -> str:
    payload = {
        "values": [None if not math.isfinite(float(x)) else round(float(x), 12) for x in values],
        "labels": list(labels or []),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _forecast_trace_fingerprint(
    timestamps: Sequence[str],
    actual: Sequence[float],
    candidate_predictions: Sequence[float],
    candidate_errors: Sequence[float],
    baseline_predictions: Mapping[str, Sequence[float]],
    baseline_errors: Mapping[str, Sequence[float]],
) -> str:
    payload = {
        "timestamps": list(timestamps),
        "actual": [round(float(value), 12) for value in actual],
        "candidate_predictions": [round(float(value), 12) for value in candidate_predictions],
        "candidate_errors": [round(float(value), 12) for value in candidate_errors],
        "baseline_predictions": {
            str(name): [round(float(value), 12) for value in values]
            for name, values in sorted(baseline_predictions.items())
        },
        "baseline_errors": {
            str(name): [round(float(value), 12) for value in values]
            for name, values in sorted(baseline_errors.items())
        },
        "error_definition": "ACTUAL_MINUS_PREDICTION",
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _validate_chronological_labels(labels: Sequence[str], expected: int) -> list[str]:
    if len(labels) != expected:
        raise ValueError("Timestamp/label count must equal the number of observations.")
    parsed: list[datetime] = []
    normalized: list[str] = []
    for index, value in enumerate(labels):
        raw = str(value or "").strip()
        if not raw:
            raise ValueError(f"Historical timestamp {index} is empty.")
        candidate = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
        try:
            stamp = datetime.fromisoformat(candidate)
        except ValueError as exc:
            raise ValueError(f"Historical timestamp {index} is not ISO-8601 parseable: {raw}") from exc
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        stamp = stamp.astimezone(timezone.utc)
        if parsed and stamp <= parsed[-1]:
            raise ValueError("Historical timestamps must be strictly increasing and unique.")
        parsed.append(stamp)
        normalized.append(stamp.isoformat())
    return normalized


def _run_identity(
    experiment_id: str,
    stage: str,
    data_fingerprint_value: str,
    signature_parts: Sequence[str],
    *,
    run_signature: str = "",
    evidence_unit_id: str = "",
) -> tuple[str, str, str]:
    signature = str(run_signature or "").strip() or _stable_id(
        "RUNSIG", experiment_id, stage, data_fingerprint_value, *signature_parts
    )
    evidence_unit = str(evidence_unit_id or "").strip() or _stable_id(
        "EUNIT", experiment_id, stage, data_fingerprint_value, *signature_parts
    )
    return f"RUN-{uuid.uuid4().hex[:16]}", signature, evidence_unit


def _validate_series(values: Sequence[float], max_rows: int = 250000) -> list[float]:
    if len(values) > max_rows:
        raise ValueError(f"Dataset exceeds Phase-4 row limit ({max_rows}).")
    cleaned = [float(x) for x in values]
    if len(cleaned) < 40:
        raise ValueError("At least 40 chronological observations are required.")
    if not all(math.isfinite(x) for x in cleaned):
        raise ValueError("Historical series contains NaN/inf values; clean data explicitly before experimentation.")
    return cleaned


def _fit_ar1(train: Sequence[float]) -> tuple[float, float]:
    x = list(train[:-1])
    y = list(train[1:])
    if len(x) < 3:
        raise ValueError("Insufficient training pairs for AR(1)/OU surrogate fit.")
    xbar = statistics.fmean(x)
    ybar = statistics.fmean(y)
    denom = sum((v - xbar) ** 2 for v in x)
    if denom <= 1e-15:
        return ybar, 0.0
    phi = sum((a - xbar) * (b - ybar) for a, b in zip(x, y)) / denom
    intercept = ybar - phi * xbar
    return intercept, phi


def _metrics(actual: Sequence[float], pred: Sequence[float], previous: Sequence[float]) -> dict[str, float]:
    if len(actual) != len(pred) or len(actual) != len(previous) or not actual:
        raise ValueError("Metric arrays must have equal non-zero length.")
    errors = [a - p for a, p in zip(actual, pred)]
    rmse = math.sqrt(statistics.fmean(e * e for e in errors))
    mae = statistics.fmean(abs(e) for e in errors)
    hits = []
    for a, p, prev in zip(actual, pred, previous):
        actual_dir = 1 if a > prev else -1 if a < prev else 0
        pred_dir = 1 if p > prev else -1 if p < prev else 0
        hits.append(1.0 if actual_dir == pred_dir else 0.0)
    return {
        "RMSE": round(rmse, 10),
        "MAE": round(mae, 10),
        "DIRECTIONAL_ACCURACY": round(statistics.fmean(hits), 6),
    }


def _score_chronological_series(values: Sequence[float], train_fraction: float, dt: float = 1.0) -> dict[str, Any]:
    data = list(values)
    split = max(20, min(len(data) - 10, int(len(data) * train_fraction)))
    train = data[:split]
    test = data[split:]
    intercept, phi = _fit_ar1(train)

    previous = [train[-1]] + list(test[:-1])
    candidate_pred = [intercept + phi * prev for prev in previous]
    rw_pred = list(previous)
    train_mean = statistics.fmean(train)
    mean_pred = [train_mean] * len(test)

    candidate_errors = [actual - prediction for actual, prediction in zip(test, candidate_pred)]
    rw_errors = [actual - prediction for actual, prediction in zip(test, rw_pred)]
    mean_errors = [actual - prediction for actual, prediction in zip(test, mean_pred)]

    candidate_metrics = _metrics(test, candidate_pred, previous)
    rw_metrics = _metrics(test, rw_pred, previous)
    mean_metrics = _metrics(test, mean_pred, previous)

    deltas = {}
    for name, metrics in (("Random Walk / Last Observation", rw_metrics), ("Training Mean", mean_metrics)):
        deltas[name] = {
            "RMSE_IMPROVEMENT_PCT": round(100.0 * (metrics["RMSE"] - candidate_metrics["RMSE"]) / metrics["RMSE"], 4) if metrics["RMSE"] > 0 else 0.0,
            "MAE_IMPROVEMENT_PCT": round(100.0 * (metrics["MAE"] - candidate_metrics["MAE"]) / metrics["MAE"], 4) if metrics["MAE"] > 0 else 0.0,
        }

    fitted = {"intercept": intercept, "phi": phi}
    if 0.0 < phi < 1.0 and dt > 0:
        fitted["kappa_implied"] = -math.log(phi) / dt
        fitted["long_run_mean"] = intercept / (1.0 - phi) if abs(1.0 - phi) > 1e-12 else float("nan")
    return {
        "split": split,
        "train": train,
        "test": test,
        "candidate_metrics": candidate_metrics,
        "baseline_metrics": {
            "Random Walk / Last Observation": rw_metrics,
            "Training Mean": mean_metrics,
        },
        "deltas": deltas,
        "fitted": fitted,
        "previous": previous,
        "candidate_predictions": candidate_pred,
        "candidate_errors": candidate_errors,
        "baseline_predictions": {
            "Random Walk / Last Observation": rw_pred,
            "Training Mean": mean_pred,
        },
        "baseline_errors": {
            "Random Walk / Last Observation": rw_errors,
            "Training Mean": mean_errors,
        },
    }


def simulate_ou_series(
    n_steps: int = 2500,
    kappa: float = 0.18,
    sigma: float = 0.65,
    x0: float = 0.0,
    dt: float = 1.0,
    seed: int = 17,
    long_run_mean: float = 0.0,
    structural_break_at: int | None = None,
    post_break_kappa: float | None = None,
) -> list[float]:
    if n_steps < 40 or n_steps > 250000:
        raise ValueError("n_steps must be between 40 and 250000.")
    if kappa <= 0 or sigma <= 0 or dt <= 0:
        raise ValueError("kappa, sigma and dt must be strictly positive for the built-in OU executor.")
    rng = random.Random(int(seed))
    x = float(x0)
    out = [x]
    for i in range(1, int(n_steps)):
        current_kappa = float(post_break_kappa) if structural_break_at is not None and i >= structural_break_at and post_break_kappa is not None else float(kappa)
        shock = rng.gauss(0.0, 1.0)
        x = x + current_kappa * (long_run_mean - x) * dt + sigma * math.sqrt(dt) * shock
        out.append(x)
    return out


def _environment(executor: str = "SRB_BUILTIN_PHASE4_V1") -> dict[str, str]:
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "executor": str(executor),
    }


def _require_ready_ou(spec: Any) -> dict[str, Any]:
    row = _asdict(spec)
    if str(row.get("status")) != "READY":
        raise ValueError("Experiment specification is blocked and cannot be executed.")
    if str(row.get("experimental_family")) != "OU_MEAN_REVERTING_SDE":
        raise ValueError("No built-in Phase-4 executor exists for this experiment family.")
    return row


def run_synthetic_experiment(
    spec: Any,
    n_steps: int = 2500,
    kappa: float = 0.18,
    sigma: float = 0.65,
    x0: float = 0.0,
    dt: float = 1.0,
    seed: int | None = None,
    train_fraction: float | None = None,
    run_robustness: bool = True,
    *,
    attempt_id: str = "",
    run_signature: str = "",
    evidence_unit_id: str = "",
) -> ExperimentRunResult:
    s = _require_ready_ou(spec)
    seed = int(s.get("seed") if seed is None else seed)
    contract = s.get("dataset_contract") or {}
    tf = float(train_fraction if train_fraction is not None else contract.get("train_fraction", 0.7))
    series = simulate_ou_series(n_steps=n_steps, kappa=kappa, sigma=sigma, x0=x0, dt=dt, seed=seed)
    scored = _score_chronological_series(series, tf, dt=dt)
    fitted_kappa = float(scored["fitted"].get("kappa_implied", float("nan")))
    rel_kappa_error = abs(fitted_kappa - kappa) / kappa if math.isfinite(fitted_kappa) and kappa > 0 else float("inf")
    rw_improvement = float(scored["deltas"]["Random Walk / Last Observation"]["RMSE_IMPROVEMENT_PCT"])

    robustness: dict[str, Any] = {}
    if run_robustness:
        scenarios = {
            "LOW_NOISE": (kappa, sigma * 0.6, None, None),
            "HIGH_NOISE": (kappa, sigma * 1.5, None, None),
            "SLOW_REVERSION": (kappa * 0.55, sigma, None, None),
            "FAST_REVERSION": (kappa * 1.45, sigma, None, None),
            "STRUCTURAL_BREAK": (kappa, sigma, int(n_steps * 0.72), max(0.02, kappa * 0.35)),
        }
        for idx, (name, params) in enumerate(scenarios.items()):
            kk, ss, break_at, post_k = params
            scenario_series = simulate_ou_series(
                n_steps=n_steps, kappa=kk, sigma=ss, x0=x0, dt=dt, seed=seed + idx + 1,
                structural_break_at=break_at, post_break_kappa=post_k,
            )
            sr = _score_chronological_series(scenario_series, tf, dt=dt)
            robustness[name] = {
                "candidate_rmse": sr["candidate_metrics"]["RMSE"],
                "rw_rmse": sr["baseline_metrics"]["Random Walk / Last Observation"]["RMSE"],
                "rmse_improvement_pct": sr["deltas"]["Random Walk / Last Observation"]["RMSE_IMPROVEMENT_PCT"],
                "phi": round(float(sr["fitted"].get("phi", 0.0)), 8),
            }

    pass_sanity = math.isfinite(rel_kappa_error) and rel_kappa_error <= 0.35 and rw_improvement > 0.0
    verdict = "IMPLEMENTATION_SANITY_PASS" if pass_sanity else "IMPLEMENTATION_SANITY_FAIL"
    fingerprint = dataset_fingerprint(series)
    run_id, signature, evidence_unit = _run_identity(
        str(s.get("experiment_id")), "SYNTHETIC_SANITY", fingerprint,
        (str(seed), str(kappa), str(sigma), str(dt), str(tf)),
        run_signature=run_signature, evidence_unit_id=evidence_unit_id,
    )
    split = int(scored["split"])
    target_labels = [f"SYNTHETIC_STEP_{index:08d}" for index in range(split, len(series))]
    origin_labels = [f"SYNTHETIC_STEP_{index:08d}" for index in range(split - 1, len(series) - 1)]
    baseline_predictions = {
        name: tuple(round(float(value), 12) for value in values)
        for name, values in scored["baseline_predictions"].items()
    }
    baseline_errors = {
        name: tuple(round(float(value), 12) for value in values)
        for name, values in scored["baseline_errors"].items()
    }
    candidate_predictions = tuple(round(float(value), 12) for value in scored["candidate_predictions"])
    candidate_errors = tuple(round(float(value), 12) for value in scored["candidate_errors"])
    actual_values = tuple(round(float(value), 12) for value in scored["test"])
    trace_fingerprint = _forecast_trace_fingerprint(
        target_labels, actual_values, candidate_predictions, candidate_errors,
        baseline_predictions, baseline_errors,
    )
    return ExperimentRunResult(
        run_id=run_id,
        experiment_id=str(s.get("experiment_id")),
        created_at=_now_iso(),
        stage="SYNTHETIC_SANITY",
        status="COMPLETED",
        verdict=verdict,
        seed=seed,
        data_fingerprint=fingerprint,
        train_size=split,
        test_size=len(scored["test"]),
        candidate_metrics=scored["candidate_metrics"],
        baseline_metrics=scored["baseline_metrics"],
        deltas_vs_baseline=scored["deltas"],
        fitted_parameters={
            **{k: round(float(v), 10) for k, v in scored["fitted"].items() if isinstance(v, (int, float)) and math.isfinite(float(v))},
            "true_kappa": float(kappa),
            "true_sigma": float(sigma),
            "kappa_relative_error": round(rel_kappa_error, 8) if math.isfinite(rel_kappa_error) else 999.0,
        },
        robustness=robustness,
        falsification_status="IMPLEMENTATION_SANITY_ONLY_NOT_SCIENTIFIC_FALSIFICATION",
        environment=_environment("SRB_BUILTIN_OU_SYNTHETIC_V2"),
        warnings=(
            "Synthetic success validates the built-in numerical surrogate only; it does not validate the finance-domain mapping.",
            "The same structural family generated the synthetic data, so this stage cannot establish external validity.",
        ),
        notes=("Chronological train/test split used.", "Candidate parameters are estimated on training observations only."),
        attempt_id=str(attempt_id or ""),
        run_signature=signature,
        evidence_unit_id=evidence_unit,
        data_contract_id=str(contract.get("contract_id") or ""),
        forecast_origin_timestamps=tuple(origin_labels),
        forecast_timestamps=tuple(target_labels),
        actual_values=actual_values,
        candidate_predictions=candidate_predictions,
        candidate_errors=candidate_errors,
        baseline_predictions=baseline_predictions,
        baseline_errors=baseline_errors,
        split_timestamp=target_labels[0] if target_labels else "",
        forecast_trace_fingerprint=trace_fingerprint,
        run_protocol_version="SRB_OU_SYNTHETIC_V2",
    )


def run_historical_oos_experiment(
    spec: Any,
    values: Sequence[float],
    labels: Sequence[str] | None = None,
    train_fraction: float | None = None,
    *,
    attempt_id: str = "",
    run_signature: str = "",
    evidence_unit_id: str = "",
    data_contract_id: str = "",
    data_contract_audit_id: str = "",
    dataset_manifest_id: str = "",
    measurement_model_id: str = "",
    measurement_decision_id: str = "",
    observable_id: str = "",
    forecast_horizon: int = 1,
    selection_context: Mapping[str, Any] | None = None,
) -> ExperimentRunResult:
    s = _require_ready_ou(spec)
    contract = s.get("dataset_contract") or {}
    max_rows = int(contract.get("max_rows", 250000))
    data = _validate_series(values, max_rows=max_rows)
    if labels is None:
        raise ValueError("Historical OOS requires explicit ISO-8601 timestamps; row order alone is not an auditable chronology.")
    normalized_labels = _validate_chronological_labels(labels, len(data))
    forecast_horizon = int(forecast_horizon)
    if forecast_horizon != 1:
        raise ValueError("The audited OU executor currently supports a one-period forecast horizon only.")
    tf = float(train_fraction if train_fraction is not None else contract.get("train_fraction", 0.7))
    scored = _score_chronological_series(data, tf, dt=1.0)
    rw_delta = float(scored["deltas"]["Random Walk / Last Observation"]["RMSE_IMPROVEMENT_PCT"])
    mean_delta = float(scored["deltas"]["Training Mean"]["RMSE_IMPROVEMENT_PCT"])
    verdict = "PROMISING_OOS" if rw_delta >= 1.0 and mean_delta >= 0.0 else "NO_OOS_IMPROVEMENT"

    # Robustness to the choice of chronological split. No random CV is used for time series.
    split_results: dict[str, Any] = {}
    for split in (0.60, 0.70, 0.80):
        if len(data) * (1 - split) < 10:
            continue
        sr = _score_chronological_series(data, split, dt=1.0)
        split_results[f"TRAIN_{int(split*100)}"] = {
            "candidate_rmse": sr["candidate_metrics"]["RMSE"],
            "rw_rmse": sr["baseline_metrics"]["Random Walk / Last Observation"]["RMSE"],
            "rmse_improvement_pct": sr["deltas"]["Random Walk / Last Observation"]["RMSE_IMPROVEMENT_PCT"],
        }

    fingerprint = dataset_fingerprint(data, normalized_labels)
    run_id, signature, evidence_unit = _run_identity(
        str(s.get("experiment_id")), "HISTORICAL_OOS", fingerprint,
        (str(tf), str(observable_id or ""), str(forecast_horizon), str(data_contract_id or "")),
        run_signature=run_signature, evidence_unit_id=evidence_unit_id,
    )
    split_index = int(scored["split"])
    target_labels = normalized_labels[split_index:]
    origin_labels = normalized_labels[split_index - 1:-1]
    candidate_predictions = tuple(round(float(value), 12) for value in scored["candidate_predictions"])
    candidate_errors = tuple(round(float(value), 12) for value in scored["candidate_errors"])
    actual_values = tuple(round(float(value), 12) for value in scored["test"])
    baseline_predictions = {
        name: tuple(round(float(value), 12) for value in predictions)
        for name, predictions in scored["baseline_predictions"].items()
    }
    baseline_errors = {
        name: tuple(round(float(value), 12) for value in errors)
        for name, errors in scored["baseline_errors"].items()
    }
    trace_fingerprint = _forecast_trace_fingerprint(
        target_labels, actual_values, candidate_predictions, candidate_errors,
        baseline_predictions, baseline_errors,
    )
    return ExperimentRunResult(
        run_id=run_id,
        experiment_id=str(s.get("experiment_id")),
        created_at=_now_iso(),
        stage="HISTORICAL_OOS",
        status="COMPLETED",
        verdict=verdict,
        seed=int(s.get("seed") or 17),
        data_fingerprint=fingerprint,
        train_size=split_index,
        test_size=len(scored["test"]),
        candidate_metrics=scored["candidate_metrics"],
        baseline_metrics=scored["baseline_metrics"],
        deltas_vs_baseline=scored["deltas"],
        fitted_parameters={k: round(float(v), 10) for k, v in scored["fitted"].items() if isinstance(v, (int, float)) and math.isfinite(float(v))},
        robustness={"CHRONOLOGICAL_SPLITS": split_results},
        falsification_status="USER_DECLARED_RULE_REQUIRES_RESEARCH_REVIEW",
        environment=_environment("SRB_BUILTIN_OU_HISTORICAL_V2"),
        warnings=(
            "Historical OOS improvement is not proof of causal transfer.",
            "Multiple testing must account for every candidate, dataset, parameterization and rerun performed by the Research Brain.",
            "No transaction-cost or economic-value claim is made at this stage.",
        ),
        notes=(
            "Chronological split only; no random shuffling.",
            "AR(1)/OU surrogate and all baselines are fitted using training observations only.",
            "Production promotion remains disabled.",
        ),
        attempt_id=str(attempt_id or ""),
        run_signature=signature,
        evidence_unit_id=evidence_unit,
        data_contract_id=str(data_contract_id or contract.get("contract_id") or ""),
        data_contract_audit_id=str(data_contract_audit_id or ""),
        dataset_manifest_id=str(dataset_manifest_id or ""),
        measurement_model_id=str(measurement_model_id or ""),
        measurement_decision_id=str(measurement_decision_id or ""),
        observable_id=str(observable_id or ""),
        forecast_horizon=forecast_horizon,
        forecast_origin_timestamps=tuple(origin_labels),
        forecast_timestamps=tuple(target_labels),
        actual_values=actual_values,
        candidate_predictions=candidate_predictions,
        candidate_errors=candidate_errors,
        baseline_predictions=baseline_predictions,
        baseline_errors=baseline_errors,
        split_timestamp=target_labels[0] if target_labels else "",
        forecast_trace_fingerprint=trace_fingerprint,
        run_protocol_version="SRB_OU_HISTORICAL_V2",
        selection_context=dict(selection_context or {}),
    )


def build_replication_plan(
    spec: Any,
    paper_id: str,
    claim_ids: Iterable[str] = (),
    required_data: Iterable[str] = (),
    required_code: Iterable[str] = (),
    target_metrics: Iterable[str] = (),
) -> ReplicationPlan:
    s = _asdict(spec)
    if not paper_id:
        raise ValueError("paper_id is required for a replication plan")
    claim_rows = tuple(str(x) for x in claim_ids if str(x))
    data_rows = tuple(str(x) for x in required_data if str(x))
    code_rows = tuple(str(x) for x in required_code if str(x))
    metric_rows = tuple(str(x) for x in target_metrics if str(x))
    return ReplicationPlan(
        replication_id=_stable_id("REPL", str(s.get("experiment_id")), paper_id, str(claim_rows)),
        created_at=_now_iso(),
        experiment_id=str(s.get("experiment_id") or ""),
        paper_id=str(paper_id),
        claim_ids=claim_rows,
        required_data=data_rows,
        required_code=code_rows,
        target_metrics=metric_rows,
        status="READY_TO_REPLICATE" if data_rows and metric_rows else "DATA_REQUIRED",
        warnings=(
            "Replication should precede innovation when the transfer candidate depends on a published empirical claim.",
            "The SRB must record unsuccessful replication attempts as evidence, not discard them.",
        ),
    )
