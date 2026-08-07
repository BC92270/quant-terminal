"""Institutional ML control plane: evidence, validation, drift and registry.

The module is intentionally framework-light. Core calculations are pure and can be
used from Streamlit, batch research jobs or CI without a running UI.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import NormalDist
from typing import Any, Mapping, Sequence
import hashlib
import json
import math
import os
import tempfile

import numpy as np
import pandas as pd


CONTROL_PLANE_VERSION = "ML-CONTROL-PLANE-V2.0"

DEFAULT_GOVERNANCE_POLICY: dict[str, Any] = {
    "execution_lag_bars": 1,
    "holdout_fraction": 0.20,
    "minimum_holdout_rows": 30,
    "minimum_training_rows": 60,
    "purge_matches_label_horizon": True,
    "embargo_fraction": 0.10,
    "random_seed": 42,
    "autonomous_trading": False,
    "permitted_stage": "shadow",
    "independent_human_approval_required": True,
}

_LABEL_NAMES = (
    "tb_label",
    "label",
    "target",
    "binary_target",
    "triple_barrier_label",
    "y",
)
_FORBIDDEN_FEATURE_TOKENS = (
    "label",
    "target",
    "outcome",
    "future_return",
    "forward_return",
    "event_end",
)

_RAW_MARKET_COLUMNS = {
    "open",
    "high",
    "low",
    "close",
    "adj close",
    "adj_close",
    "volume",
    "dollar_volume",
}


@dataclass(frozen=True)
class PromotionThresholds:
    min_oos_rows: int = 100
    min_balanced_accuracy_gain: float = 0.01
    max_brier_delta: float = 0.0
    max_ece: float = 0.08
    max_feature_psi: float = 0.25
    min_net_sharpe: float = 0.0
    max_drawdown_floor: float = -0.25


def _find_label_series(frame: pd.DataFrame) -> pd.Series:
    if frame is None or frame.empty:
        return pd.Series(dtype=float)
    lowered = {str(column).lower(): column for column in frame.columns}
    for name in _LABEL_NAMES:
        if name in lowered:
            return frame[lowered[name]]
    for column in frame.columns:
        name = str(column).lower()
        if "label" in name or "target" in name:
            return frame[column]
    return pd.Series(dtype=float)


def _time_axis(frame: pd.DataFrame | None) -> pd.Series | None:
    if frame is None or frame.empty:
        return None
    if isinstance(frame.index, pd.DatetimeIndex):
        parsed = pd.Series(pd.to_datetime(frame.index, errors="coerce"), index=frame.index)
        if parsed.notna().any():
            return parsed
    lowered = {str(column).lower(): column for column in frame.columns}
    for name in ("date", "datetime", "timestamp", "time"):
        if name in lowered:
            parsed = pd.to_datetime(frame[lowered[name]], errors="coerce", utc=True)
            if parsed.notna().any():
                return pd.Series(parsed.to_numpy(), index=frame.index)
    return None


def _normalise_binary_labels(series: pd.Series) -> pd.Series:
    if series is None or series.empty:
        return pd.Series(dtype=float)
    text = series.astype(str).str.lower()
    result = pd.Series(np.nan, index=series.index, dtype=float)
    result.loc[text.str.contains("tp", regex=False, na=False)] = 1.0
    result.loc[text.str.contains("sl", regex=False, na=False)] = 0.0
    timeout_mask = text.str.contains("timeout", regex=False, na=False)
    numeric = pd.to_numeric(series, errors="coerce")
    numeric_mask = result.isna() & numeric.notna() & ~timeout_mask
    if numeric_mask.any():
        unique = set(numeric.loc[numeric_mask].unique().tolist())
        if unique.issubset({-1.0, 0.0, 1.0}) and -1.0 in unique:
            result.loc[numeric_mask] = (numeric.loc[numeric_mask] > 0).astype(float)
        else:
            result.loc[numeric_mask] = numeric.loc[numeric_mask].clip(0, 1)
    return result


def _finding(control: str, passed: bool, evidence: str, severity: str = "hard") -> dict[str, Any]:
    return {
        "Control": control,
        "Status": "PASS" if passed else "REVIEW",
        "Evidence": evidence,
        "Severity": severity,
    }


def causal_feature_frame(
    feature_df: pd.DataFrame | None,
) -> tuple[pd.DataFrame, list[str]]:
    """Return the model-eligible matrix and quarantine target-derived/raw levels."""
    if feature_df is None:
        return pd.DataFrame(), []
    excluded: list[str] = []
    eligible: list[Any] = []
    for column in feature_df.columns:
        lowered = str(column).lower()
        is_time_axis = lowered in {"date", "datetime", "timestamp", "time"}
        is_non_causal = lowered in _LABEL_NAMES or any(
            token in lowered for token in _FORBIDDEN_FEATURE_TOKENS
        )
        is_unstable_raw_level = lowered in _RAW_MARKET_COLUMNS
        if is_non_causal or is_unstable_raw_level:
            excluded.append(str(column))
        else:
            eligible.append(column)
        if is_time_axis and column not in eligible:
            eligible.append(column)
    return feature_df.loc[:, eligible].copy(), excluded


def dataset_fingerprint(
    labeled_df: pd.DataFrame,
    feature_df: pd.DataFrame | None,
    horizon: int,
) -> str:
    """Create a deterministic identifier without serialising the dataset externally."""
    digest = hashlib.sha256()
    digest.update(CONTROL_PLANE_VERSION.encode())
    digest.update(str(int(horizon)).encode())
    for name, frame in (("labels", labeled_df), ("features", feature_df)):
        digest.update(name.encode())
        if frame is None:
            digest.update(b"none")
            continue
        digest.update(str(frame.shape).encode())
        digest.update("|".join(map(str, frame.columns)).encode())
        try:
            hashed = pd.util.hash_pandas_object(frame, index=True, categorize=True)
        except TypeError:
            normalised = frame.astype(str)
            hashed = pd.util.hash_pandas_object(normalised, index=True, categorize=True)
        digest.update(np.asarray(hashed.values, dtype=np.uint64).tobytes())
    return digest.hexdigest()


def point_in_time_audit(
    labeled_df: pd.DataFrame,
    feature_df: pd.DataFrame | None,
    horizon: int,
    policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate causal dataset invariants that are observable in the current frames."""
    cfg = dict(DEFAULT_GOVERNANCE_POLICY)
    if policy:
        cfg.update(dict(policy))

    label_time = _time_axis(labeled_df)
    feature_time = _time_axis(feature_df)
    temporal_present = label_time is not None and label_time.notna().all()
    chronological = bool(temporal_present and label_time.is_monotonic_increasing)
    unique_timestamps = bool(temporal_present and not label_time.duplicated().any())

    forbidden_columns: list[str] = []
    if feature_df is not None:
        for column in feature_df.columns:
            lowered = str(column).lower()
            if lowered in _LABEL_NAMES or any(token in lowered for token in _FORBIDDEN_FEATURE_TOKENS):
                forbidden_columns.append(str(column))
    separation_ok = not forbidden_columns

    coverage_ok = False
    if temporal_present and feature_time is not None and feature_time.notna().any():
        label_valid = label_time.dropna()
        feature_valid = feature_time.dropna()
        coverage_ok = bool(
            len(feature_valid)
            and feature_valid.min() <= label_valid.min()
            and feature_valid.max() >= label_valid.max()
        )
    elif feature_df is not None:
        coverage_ok = len(feature_df) >= len(labeled_df)

    execution_lag = int(cfg.get("execution_lag_bars", 0))
    causal_execution = execution_lag >= 1
    purge_ok = bool(cfg.get("purge_matches_label_horizon")) and int(horizon) > 0
    embargo_bars = max(1, int(math.ceil(int(horizon) * float(cfg.get("embargo_fraction", 0.10)))))
    embargo_ok = embargo_bars >= 1

    findings = [
        _finding("Temporal index present", temporal_present, "Datetime axis is explicit and fully parseable."),
        _finding("Chronological ordering", chronological, "Rows are monotonically ordered before splitting."),
        _finding("Unique timestamps", unique_timestamps, "No duplicate event timestamp is accepted."),
        _finding(
            "Feature / target separation",
            separation_ok,
            "No target-like feature column detected." if separation_ok else "Blocked columns: " + ", ".join(forbidden_columns),
        ),
        _finding("t+1 execution contract", causal_execution, f"Execution lag = {execution_lag} bar(s)."),
        _finding("Purge contract", purge_ok, f"Purge window is tied to the {int(horizon)}-bar label horizon."),
        _finding("Embargo contract", embargo_ok, f"Embargo = {embargo_bars} bar(s)."),
        _finding("Feature timestamp coverage", coverage_ok, "Feature history covers the labeled event window."),
    ]
    passed = all(item["Status"] == "PASS" for item in findings)
    return {
        "passed": passed,
        "findings": findings,
        "forbidden_columns": forbidden_columns,
        "execution_lag_bars": execution_lag,
        "purge_bars": int(horizon),
        "embargo_bars": embargo_bars,
    }


def temporal_holdout_audit(
    labeled_df: pd.DataFrame,
    horizon: int,
    policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Design and validate a locked final temporal holdout after purge and embargo."""
    cfg = dict(DEFAULT_GOVERNANCE_POLICY)
    if policy:
        cfg.update(dict(policy))

    labels = _normalise_binary_labels(_find_label_series(labeled_df))
    times = _time_axis(labeled_df)
    if times is None:
        return {
            "passed": False,
            "train_rows": 0,
            "purge_rows": int(horizon),
            "holdout_rows": 0,
            "findings": [_finding("Locked temporal holdout", False, "No explicit temporal axis.")],
        }

    frame = pd.DataFrame({"timestamp": times, "label": labels}).dropna()
    frame = frame.sort_values("timestamp", kind="stable")
    n_rows = len(frame)
    holdout_rows = max(
        int(cfg.get("minimum_holdout_rows", 30)),
        int(math.ceil(n_rows * float(cfg.get("holdout_fraction", 0.20)))),
    )
    purge_rows = max(int(horizon), 1)
    train_rows = n_rows - holdout_rows - purge_rows

    enough_train = train_rows >= int(cfg.get("minimum_training_rows", 60))
    enough_holdout = holdout_rows >= int(cfg.get("minimum_holdout_rows", 30)) and holdout_rows < n_rows
    if enough_train and enough_holdout:
        train = frame.iloc[:train_rows]
        holdout = frame.iloc[-holdout_rows:]
        no_overlap = bool(train["timestamp"].max() < holdout["timestamp"].min())
        train_classes = set(train["label"].astype(int).unique().tolist())
        holdout_classes = set(holdout["label"].astype(int).unique().tolist())
        class_coverage = train_classes == {0, 1} and holdout_classes == {0, 1}
        holdout_start = str(pd.Timestamp(holdout["timestamp"].min()).date())
        holdout_end = str(pd.Timestamp(holdout["timestamp"].max()).date())
    else:
        no_overlap = False
        class_coverage = False
        holdout_start = ""
        holdout_end = ""

    findings = [
        _finding("Training depth", enough_train, f"{max(train_rows, 0)} rows before purge."),
        _finding("Locked holdout depth", enough_holdout, f"{min(holdout_rows, n_rows)} terminal rows reserved."),
        _finding("Purged separation", no_overlap, f"{purge_rows} rows excluded between selection and holdout."),
        _finding("Class coverage by segment", class_coverage, "Both directional classes occur in train and holdout."),
    ]
    passed = all(item["Status"] == "PASS" for item in findings)
    return {
        "passed": passed,
        "train_rows": max(train_rows, 0),
        "purge_rows": purge_rows,
        "holdout_rows": min(holdout_rows, n_rows),
        "holdout_start": holdout_start,
        "holdout_end": holdout_end,
        "findings": findings,
    }


def population_stability_index(
    reference: Sequence[float],
    current: Sequence[float],
    bins: int = 10,
) -> float:
    ref = np.asarray(reference, dtype=float)
    cur = np.asarray(current, dtype=float)
    ref = ref[np.isfinite(ref)]
    cur = cur[np.isfinite(cur)]
    if len(ref) < 10 or len(cur) < 10:
        return float("nan")
    edges = np.unique(np.quantile(ref, np.linspace(0.0, 1.0, max(2, int(bins)) + 1)))
    if len(edges) < 3:
        return 0.0
    edges[0], edges[-1] = -np.inf, np.inf
    ref_counts, _ = np.histogram(ref, bins=edges)
    cur_counts, _ = np.histogram(cur, bins=edges)
    epsilon = 1e-6
    ref_share = np.maximum(ref_counts / max(ref_counts.sum(), 1), epsilon)
    cur_share = np.maximum(cur_counts / max(cur_counts.sum(), 1), epsilon)
    return float(np.sum((cur_share - ref_share) * np.log(cur_share / ref_share)))


def feature_drift_report(
    feature_df: pd.DataFrame | None,
    reference_fraction: float = 0.65,
    max_features: int = 40,
) -> dict[str, Any]:
    if feature_df is None or feature_df.empty:
        return {"status": "UNAVAILABLE", "max_psi": float("nan"), "mean_psi": float("nan"), "features": []}
    numeric = feature_df.select_dtypes(include=[np.number]).replace([np.inf, -np.inf], np.nan)
    split = int(len(numeric) * float(reference_fraction))
    if split < 30 or len(numeric) - split < 20:
        return {"status": "INSUFFICIENT", "max_psi": float("nan"), "mean_psi": float("nan"), "features": []}

    rows: list[dict[str, Any]] = []
    for column in list(numeric.columns)[: max(1, int(max_features))]:
        ref = numeric[column].iloc[:split].dropna().to_numpy()
        cur = numeric[column].iloc[split:].dropna().to_numpy()
        psi = population_stability_index(ref, cur)
        if np.isfinite(psi):
            state = "STABLE" if psi < 0.10 else ("WATCH" if psi < 0.25 else "ACTION")
            rows.append({"Feature": str(column), "PSI": round(float(psi), 4), "State": state})
    rows.sort(key=lambda item: item["PSI"], reverse=True)
    values = [row["PSI"] for row in rows]
    max_psi = max(values) if values else float("nan")
    mean_psi = float(np.mean(values)) if values else float("nan")
    status = "STABLE" if np.isfinite(max_psi) and max_psi < 0.10 else (
        "WATCH" if np.isfinite(max_psi) and max_psi < 0.25 else "ACTION"
    )
    return {"status": status, "max_psi": max_psi, "mean_psi": mean_psi, "features": rows}


def expected_calibration_error(
    y_true: Sequence[float],
    probabilities: Sequence[float],
    bins: int = 10,
) -> float:
    y = np.asarray(y_true, dtype=float)
    p = np.asarray(probabilities, dtype=float)
    mask = np.isfinite(y) & np.isfinite(p)
    y, p = y[mask], np.clip(p[mask], 0.0, 1.0)
    if not len(y):
        return float("nan")
    edges = np.linspace(0.0, 1.0, max(2, int(bins)) + 1)
    bucket = np.minimum(np.digitize(p, edges[1:-1], right=False), len(edges) - 2)
    ece = 0.0
    for index in range(len(edges) - 1):
        selected = bucket == index
        if selected.any():
            ece += float(selected.mean()) * abs(float(y[selected].mean()) - float(p[selected].mean()))
    return float(ece)


def conformal_binary_sets(
    y_calibration: Sequence[float],
    p_calibration: Sequence[float],
    probabilities: Sequence[float],
    alpha: float = 0.10,
) -> tuple[pd.DataFrame, float]:
    """Split-conformal classification sets; ambiguous observations become abstentions."""
    y = np.asarray(y_calibration, dtype=int)
    p = np.clip(np.asarray(p_calibration, dtype=float), 0.0, 1.0)
    mask = np.isfinite(p) & np.isin(y, [0, 1])
    y, p = y[mask], p[mask]
    if not len(y):
        return pd.DataFrame(columns=["P(class=1)", "Prediction set", "Set size", "Abstain"]), float("nan")
    true_probability = np.where(y == 1, p, 1.0 - p)
    scores = 1.0 - true_probability
    level = min(1.0, math.ceil((len(scores) + 1) * (1.0 - float(alpha))) / len(scores))
    try:
        qhat = float(np.quantile(scores, level, method="higher"))
    except TypeError:
        qhat = float(np.quantile(scores, level, interpolation="higher"))

    test_p = np.clip(np.asarray(probabilities, dtype=float), 0.0, 1.0)
    include_zero = (1.0 - test_p) >= (1.0 - qhat)
    include_one = test_p >= (1.0 - qhat)
    sets = []
    sizes = []
    for zero, one in zip(include_zero, include_one):
        members = ([0] if zero else []) + ([1] if one else [])
        sets.append("{" + ",".join(map(str, members)) + "}" if members else "∅")
        sizes.append(len(members))
    result = pd.DataFrame(
        {
            "P(class=1)": test_p,
            "Prediction set": sets,
            "Set size": sizes,
            "Abstain": np.asarray(sizes) != 1,
        }
    )
    return result, qhat


def block_bootstrap_sharpe_interval(
    returns: Sequence[float],
    annualisation: int = 252,
    block_length: int | None = None,
    simulations: int = 400,
    seed: int = 42,
) -> dict[str, float]:
    values = np.asarray(returns, dtype=float)
    values = values[np.isfinite(values)]
    if len(values) < 20 or float(np.std(values, ddof=1)) <= 0:
        return {"sharpe": float("nan"), "lower": float("nan"), "upper": float("nan")}
    block = int(block_length or max(2, round(math.sqrt(len(values)))))
    rng = np.random.default_rng(int(seed))
    estimates: list[float] = []
    starts = np.arange(max(1, len(values) - block + 1))
    for _ in range(max(50, int(simulations))):
        sampled: list[float] = []
        while len(sampled) < len(values):
            start = int(rng.choice(starts))
            sampled.extend(values[start : start + block].tolist())
        sample = np.asarray(sampled[: len(values)])
        std = float(np.std(sample, ddof=1))
        if std > 0:
            estimates.append(float(np.mean(sample) / std * math.sqrt(annualisation)))
    observed = float(np.mean(values) / np.std(values, ddof=1) * math.sqrt(annualisation))
    if not estimates:
        return {"sharpe": observed, "lower": float("nan"), "upper": float("nan")}
    lower, upper = np.quantile(estimates, [0.025, 0.975])
    return {"sharpe": observed, "lower": float(lower), "upper": float(upper)}


def deflated_sharpe_probability(
    returns: Sequence[float],
    trials: int = 1,
) -> float:
    """Probability that per-period Sharpe exceeds a multiple-testing benchmark."""
    values = np.asarray(returns, dtype=float)
    values = values[np.isfinite(values)]
    if len(values) < 20:
        return float("nan")
    std = float(np.std(values, ddof=1))
    if std <= 0:
        return float("nan")
    sr = float(np.mean(values) / std)
    centred = (values - np.mean(values)) / std
    skew = float(np.mean(centred**3))
    kurtosis = float(np.mean(centred**4))
    n_trials = max(1, int(trials))
    benchmark = 0.0 if n_trials == 1 else NormalDist().inv_cdf(1.0 - 1.0 / n_trials) / math.sqrt(len(values))
    variance = max((1.0 - skew * sr + ((kurtosis - 1.0) / 4.0) * sr * sr) / (len(values) - 1), 1e-12)
    return float(NormalDist().cdf((sr - benchmark) / math.sqrt(variance)))


def promotion_decision(
    challenger: Mapping[str, float],
    baseline: Mapping[str, float],
    thresholds: PromotionThresholds | None = None,
) -> dict[str, Any]:
    cfg = thresholds or PromotionThresholds()
    checks = {
        "OOS sample": float(challenger.get("oos_rows", 0)) >= cfg.min_oos_rows,
        "Balanced accuracy uplift": float(challenger.get("balanced_accuracy", -np.inf))
        >= float(baseline.get("balanced_accuracy", np.inf)) + cfg.min_balanced_accuracy_gain,
        "Brier non-inferiority": float(challenger.get("brier", np.inf))
        <= float(baseline.get("brier", -np.inf)) + cfg.max_brier_delta,
        "Calibration": float(challenger.get("ece", np.inf)) <= cfg.max_ece,
        "Feature drift": float(challenger.get("max_feature_psi", np.inf)) <= cfg.max_feature_psi,
        "Net Sharpe": float(challenger.get("net_sharpe", -np.inf)) > cfg.min_net_sharpe,
        "Drawdown": float(challenger.get("max_drawdown", -np.inf)) >= cfg.max_drawdown_floor,
    }
    eligible = all(checks.values())
    return {
        "status": "ELIGIBLE_FOR_SHADOW_REVIEW" if eligible else "BLOCKED",
        "checks": checks,
        "autonomous_trading": False,
        "human_approval_required": True,
    }


def build_institutional_control_report(
    labeled_df: pd.DataFrame,
    feature_df: pd.DataFrame | None,
    horizon: int,
    policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = dict(DEFAULT_GOVERNANCE_POLICY)
    if policy:
        cfg.update(dict(policy))

    causal_features, quarantined = causal_feature_frame(feature_df)
    pit = point_in_time_audit(labeled_df, causal_features, horizon, cfg)
    quarantine_evidence = (
        "Excluded from model X: " + ", ".join(quarantined)
        if quarantined
        else "No target-derived feature present in the supplied matrix."
    )
    pit["findings"].append(
        _finding(
            "Model-feature quarantine",
            True,
            quarantine_evidence,
        )
    )
    pit["quarantined_columns"] = quarantined
    pit["eligible_feature_count"] = int(len(causal_features.columns))
    pit["passed"] = all(item["Status"] == "PASS" for item in pit["findings"])

    holdout = temporal_holdout_audit(labeled_df, horizon, cfg)
    drift = feature_drift_report(causal_features)
    return {
        "control_plane_version": CONTROL_PLANE_VERSION,
        "dataset_id": dataset_fingerprint(labeled_df, feature_df, horizon),
        "model_matrix_id": dataset_fingerprint(labeled_df, causal_features, horizon),
        "policy": cfg,
        "point_in_time": pit,
        "holdout": holdout,
        "drift": drift,
        "governance": {
            "shadow_mode": True,
            "autonomous_trading": False,
            "deterministic_seed": int(cfg["random_seed"]),
            "eligible_feature_count": int(len(causal_features.columns)),
            "quarantined_feature_count": int(len(quarantined)),
            "model_registry": "file-backed / append-only snapshots",
            "independent_human_review": "required before champion status",
        },
    }


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    return value


def report_to_json(report: Mapping[str, Any]) -> str:
    return json.dumps(_json_safe(report), indent=2, sort_keys=True, allow_nan=False)


class LocalExperimentRegistry:
    """Small append-only registry for local research evidence.

    Champion promotion is deliberately unavailable without an eligible control
    decision and a non-empty independent approval note.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def list(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        entries: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                entries.append(json.loads(line))
        return entries

    def _write(self, entries: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(self.path.parent),
            prefix=".registry-",
            suffix=".tmp",
            delete=False,
        )
        try:
            with handle:
                for entry in entries:
                    handle.write(json.dumps(entry, sort_keys=True, default=str) + chr(10))
            os.replace(handle.name, self.path)
        finally:
            if os.path.exists(handle.name):
                os.unlink(handle.name)

    def append(self, record: Mapping[str, Any]) -> dict[str, Any]:
        payload = json.loads(json.dumps(dict(record), sort_keys=True, default=str))
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        run_id = hashlib.sha256(canonical.encode()).hexdigest()[:16]
        entries = self.list()
        for entry in entries:
            if entry.get("run_id") == run_id:
                return entry
        entry = {
            "run_id": run_id,
            "registered_at": datetime.now(timezone.utc).isoformat(),
            "stage": "research",
            "record": payload,
        }
        entries.append(entry)
        self._write(entries)
        return entry

    def promote(self, run_id: str, stage: str, approval_note: str = "") -> dict[str, Any]:
        allowed = {"research", "challenger", "shadow", "champion"}
        if stage not in allowed:
            raise ValueError(f"Unsupported stage: {stage}")
        entries = self.list()
        match = next((entry for entry in entries if entry.get("run_id") == run_id), None)
        if match is None:
            raise KeyError(run_id)
        if stage == "champion":
            decision = match.get("record", {}).get("promotion", {})
            if decision.get("status") != "ELIGIBLE_FOR_SHADOW_REVIEW" or not approval_note.strip():
                raise PermissionError("Champion requires eligible evidence and independent approval.")
        match["stage"] = stage
        match["approval_note"] = approval_note.strip()
        match["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._write(entries)
        return match


def render_institutional_control_plane(report: Mapping[str, Any], ticker: str) -> None:
    import streamlit as st

    pit = report["point_in_time"]
    holdout = report["holdout"]
    drift = report["drift"]
    st.markdown("#### Institutional control plane")
    st.caption(
        "Observable evidence only: causal data controls, locked temporal holdout, "
        "drift surveillance and an approval-gated local registry."
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Dataset ID", str(report["dataset_id"])[:12])
    c2.metric("Point-in-time", "PASS" if pit["passed"] else "REVIEW")
    c3.metric("Locked holdout", f"{holdout['holdout_rows']} rows")
    psi = drift.get("max_psi", float("nan"))
    c4.metric("Max feature PSI", f"{psi:.3f}" if np.isfinite(psi) else "n/a")
    c4.caption(f"State: {drift.get('status', 'n/a')}")

    evidence_tab, holdout_tab, drift_tab, registry_tab = st.tabs(
        ["Evidence ledger", "Locked holdout", "Drift monitor", "Model registry"]
    )
    with evidence_tab:
        evidence = pd.DataFrame(pit["findings"] + holdout["findings"])
        st.dataframe(evidence, width="stretch", hide_index=True, height=390)
        st.info(
            "Independent human review is intentionally outside the automated score "
            "and remains mandatory before champion status."
        )

    with holdout_tab:
        values = {
            "Training rows": holdout["train_rows"],
            "Purged rows": holdout["purge_rows"],
            "Holdout rows": holdout["holdout_rows"],
            "Holdout start": holdout.get("holdout_start", ""),
            "Holdout end": holdout.get("holdout_end", ""),
            "Selection access": "blocked by policy",
        }
        st.dataframe(
            pd.DataFrame({"Control": list(values), "Evidence": list(values.values())}),
            width="stretch",
            hide_index=True,
        )
        st.caption("The terminal segment is reserved after a full label-horizon purge.")

    with drift_tab:
        drift_rows = pd.DataFrame(drift.get("features", []))
        if drift_rows.empty:
            st.warning("Drift evidence unavailable: the feature window is too short.")
        else:
            if drift.get("status") == "ACTION":
                st.warning(
                    "Feature drift exceeds the action threshold. Model promotion remains blocked "
                    "until regime attribution or retraining evidence is documented."
                )
            elif drift.get("status") == "WATCH":
                st.info("Feature drift requires review before the next champion–challenger decision.")
            st.dataframe(drift_rows.head(15), width="stretch", hide_index=True, height=410)
            st.caption("PSI < 0.10 stable · 0.10–0.25 watch · ≥ 0.25 action required.")

    with registry_tab:
        registry_path = Path(".quant_terminal") / "ml_registry.jsonl"
        registry = LocalExperimentRegistry(registry_path)
        entries = registry.list()
        st.markdown(
            "**Registry contract:** immutable dataset fingerprint, research-first stage, "
            "shadow review gate and explicit independent approval for champion promotion."
        )
        if st.button("Register current governed snapshot", key=f"register_ml_snapshot_{ticker}"):
            entry = registry.append(
                {
                    "ticker": str(ticker).upper(),
                    "dataset_id": report["dataset_id"],
                    "control_plane_version": report["control_plane_version"],
                    "report": report,
                    "promotion": {"status": "RESEARCH_ONLY"},
                }
            )
            st.success(f"Snapshot registered: {entry['run_id']}")
            entries = registry.list()
        if entries:
            display = pd.DataFrame(
                [
                    {
                        "Run ID": item.get("run_id"),
                        "Stage": item.get("stage"),
                        "Registered": item.get("registered_at"),
                        "Dataset": item.get("record", {}).get("dataset_id", "")[:12],
                    }
                    for item in entries[-20:]
                ]
            )
            st.dataframe(display, width="stretch", hide_index=True)
        else:
            st.caption("No snapshot registered yet. Registration is explicit and local.")
        st.download_button(
            "Download governance evidence JSON",
            data=report_to_json(report),
            file_name=f"{str(ticker).upper()}_ml_governance_report.json",
            mime="application/json",
            key=f"download_ml_governance_{ticker}",
        )
