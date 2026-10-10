from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3
from typing import Any

import numpy as np
import pandas as pd
from sklearn.covariance import LedoitWolf

from .institutional_cache import get_correlation_cache


MONITOR_SCHEMA = "quant-terminal.correlation-monitor.v1"


def _corr(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    values = frame.apply(pd.to_numeric, errors="coerce").dropna(how="any")
    if len(values) < 20 or values.shape[1] < 2:
        return pd.DataFrame()
    return values.corr()


def _top_links(matrix: pd.DataFrame, count: int = 10) -> set[tuple[str, str]]:
    if matrix is None or matrix.empty:
        return set()
    rows: list[tuple[float, str, str]] = []
    for left in range(len(matrix.columns)):
        for right in range(left + 1, len(matrix.columns)):
            value = float(matrix.iloc[left, right])
            if np.isfinite(value):
                rows.append((abs(value), str(matrix.columns[left]), str(matrix.columns[right])))
    rows.sort(reverse=True)
    return {(a, b) for _, a, b in rows[: max(1, int(count))]}


def correlation_drift_report(
    changes: pd.DataFrame,
    *,
    current_window: int = 30,
    baseline_window: int = 126,
    min_baseline_obs: int = 60,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Compare recent and strictly prior correlation structures."""

    if changes is None or changes.empty:
        return pd.DataFrame(), {"status": "unavailable", "reason": "empty_input"}
    clean = changes.apply(pd.to_numeric, errors="coerce").dropna(axis=1, thresh=current_window + min_baseline_obs)
    clean = clean.dropna(how="any")
    required = int(current_window) + int(min_baseline_obs)
    if len(clean) < required or clean.shape[1] < 2:
        return pd.DataFrame(), {
            "status": "insufficient_data",
            "observations": int(len(clean)),
            "assets": int(clean.shape[1]),
            "required_observations": required,
        }
    current = clean.tail(int(current_window))
    prior = clean.iloc[: -int(current_window)].tail(int(baseline_window))
    if len(prior) < int(min_baseline_obs):
        return pd.DataFrame(), {"status": "insufficient_baseline", "baseline_observations": int(len(prior))}
    current_corr, prior_corr = _corr(current), _corr(prior)
    common = [c for c in current_corr.columns if c in prior_corr.columns]
    current_corr, prior_corr = current_corr.loc[common, common], prior_corr.loc[common, common]
    delta = current_corr - prior_corr
    scale = max(1.0, float(np.sqrt(len(common) * max(len(common) - 1, 1))))
    normalized_frobenius = float(np.linalg.norm(delta.to_numpy(dtype=float), ord="fro") / scale)
    rows: list[dict[str, Any]] = []
    for left in range(len(common)):
        for right in range(left + 1, len(common)):
            rows.append({
                "Asset A": common[left],
                "Asset B": common[right],
                "Baseline correlation": float(prior_corr.iloc[left, right]),
                "Current correlation": float(current_corr.iloc[left, right]),
                "Correlation shift": float(delta.iloc[left, right]),
                "Absolute shift": float(abs(delta.iloc[left, right])),
            })
    links = pd.DataFrame(rows).sort_values("Absolute shift", ascending=False).reset_index(drop=True)
    prior_top, current_top = _top_links(prior_corr), _top_links(current_corr)
    union = prior_top.union(current_top)
    top_link_turnover = float(1.0 - len(prior_top.intersection(current_top)) / max(len(union), 1))
    prior_eigen = np.linalg.eigvalsh(prior_corr.to_numpy(dtype=float))
    current_eigen = np.linalg.eigvalsh(current_corr.to_numpy(dtype=float))
    prior_pc1 = float(prior_eigen[-1] / max(prior_eigen.sum(), 1e-12))
    current_pc1 = float(current_eigen[-1] / max(current_eigen.sum(), 1e-12))
    severity_score = float(np.clip(100.0 * (0.65 * normalized_frobenius + 0.25 * top_link_turnover + 0.10 * abs(current_pc1 - prior_pc1)), 0.0, 100.0))
    severity = "high" if severity_score >= 45 else "elevated" if severity_score >= 25 else "normal"
    return links, {
        "status": "ok",
        "authority": "RESEARCH_ONLY",
        "current_window": int(current_window),
        "baseline_window": int(len(prior)),
        "current_start": pd.Timestamp(current.index.min()).isoformat(),
        "baseline_end": pd.Timestamp(prior.index.max()).isoformat(),
        "normalized_frobenius_shift": normalized_frobenius,
        "max_absolute_link_shift": float(links.iloc[0]["Absolute shift"]) if not links.empty else None,
        "top_link_turnover": top_link_turnover,
        "baseline_pc1_share": prior_pc1,
        "current_pc1_share": current_pc1,
        "pc1_share_shift": current_pc1 - prior_pc1,
        "severity_score": severity_score,
        "severity": severity,
        "no_future_leakage": True,
    }


def rolling_correlation_calibration(
    changes: pd.DataFrame,
    *,
    train_days: int = 126,
    test_days: int = 21,
    max_folds: int = 8,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Chronological Ledoit-Wolf correlation calibration ledger."""

    if changes is None or changes.empty:
        return pd.DataFrame(), {"status": "unavailable"}
    frame = changes.apply(pd.to_numeric, errors="coerce").dropna(how="any")
    if frame.shape[1] < 2 or len(frame) < int(train_days) + int(test_days):
        return pd.DataFrame(), {
            "status": "insufficient_data",
            "observations": int(len(frame)),
            "required": int(train_days) + int(test_days),
        }
    endpoints = list(range(int(train_days), len(frame) - int(test_days) + 1, int(test_days)))[-int(max_folds) :]
    rows: list[dict[str, Any]] = []
    for endpoint in endpoints:
        train = frame.iloc[endpoint - int(train_days) : endpoint]
        test = frame.iloc[endpoint : endpoint + int(test_days)]
        if len(test) < max(10, int(test_days) // 2):
            continue
        estimator = LedoitWolf().fit(train.to_numpy(dtype=float))
        covariance = estimator.covariance_
        scale = np.sqrt(np.clip(np.diag(covariance), 1e-18, None))
        forecast = covariance / np.outer(scale, scale)
        realized = test.corr().to_numpy(dtype=float)
        upper = np.triu_indices_from(forecast, 1)
        errors = forecast[upper] - realized[upper]
        finite = errors[np.isfinite(errors)]
        if not len(finite):
            continue
        rows.append({
            "Train end": train.index[-1],
            "Test start": test.index[0],
            "Test end": test.index[-1],
            "Train observations": int(len(train)),
            "Test observations": int(len(test)),
            "Pair RMSE": float(np.sqrt(np.mean(finite**2))),
            "Pair MAE": float(np.mean(np.abs(finite))),
            "Mean forecast correlation": float(np.nanmean(forecast[upper])),
            "Mean realized correlation": float(np.nanmean(realized[upper])),
            "Signed calibration bias": float(np.mean(finite)),
            "Ledoit-Wolf shrinkage": float(estimator.shrinkage_),
        })
    ledger = pd.DataFrame(rows)
    if ledger.empty:
        return ledger, {"status": "unavailable", "reason": "no_valid_folds"}
    rmse = float(ledger["Pair RMSE"].mean())
    recent_rmse = float(ledger.iloc[-1]["Pair RMSE"])
    rmse_series = pd.to_numeric(ledger["Pair RMSE"], errors="coerce").dropna()
    median_rmse = float(rmse_series.median())
    mean_abs_deviation = float(np.mean(np.abs(rmse_series.to_numpy(dtype=float) - median_rmse)))
    threshold = median_rmse + 2.0 * mean_abs_deviation if len(ledger) > 2 else max(0.25, rmse * 1.5)
    return ledger, {
        "status": "ok",
        "authority": "RESEARCH_ONLY",
        "model": "Ledoit-Wolf correlation forecast",
        "folds": int(len(ledger)),
        "train_days": int(train_days),
        "test_days": int(test_days),
        "mean_pair_rmse": rmse,
        "recent_pair_rmse": recent_rmse,
        "alert_threshold": threshold,
        "recent_breach": bool(recent_rmse > threshold),
        "mean_absolute_bias": float(abs(ledger["Signed calibration bias"].mean())),
        "no_future_leakage": True,
    }


def independent_validation_status(analysis: dict[str, Any] | None) -> dict[str, Any]:
    """Validate the evidence contract without claiming independence from code alone."""

    analysis = analysis or {}
    evidence = analysis.get("correlation_independent_validation")
    if not isinstance(evidence, dict):
        return {
            "status": "not_provided",
            "independently_validated": False,
            "adapter_ready": True,
            "required_fields": ["reviewer", "review_date", "scope", "result", "evidence_sha256"],
        }
    required = {"reviewer", "review_date", "scope", "result", "evidence_sha256"}
    missing = sorted(required.difference(evidence))
    digest = str(evidence.get("evidence_sha256", ""))
    digest_ok = bool(re.fullmatch(r"[0-9a-fA-F]{64}", digest))
    result = str(evidence.get("result", "")).upper().strip()
    accepted_result = result in {"PASS", "PASS_WITH_LIMITATIONS", "REJECT"}
    if missing or not digest_ok or not accepted_result:
        return {
            "status": "invalid_contract",
            "independently_validated": False,
            "adapter_ready": True,
            "missing_fields": missing,
            "digest_valid": digest_ok,
            "result_valid": accepted_result,
        }
    return {
        "status": "verified_contract",
        "independently_validated": result in {"PASS", "PASS_WITH_LIMITATIONS"},
        "reviewer": str(evidence["reviewer"]),
        "review_date": str(evidence["review_date"]),
        "scope": str(evidence["scope"]),
        "result": result,
        "evidence_sha256": digest.lower(),
        "limitation": "Contract validation verifies structure and digest syntax, not reviewer identity.",
    }


class ValidationLedger:
    """Idempotent persistent metric history for drift and calibration surveillance."""

    def __init__(self, path: str | Path | None = None) -> None:
        cache_root = get_correlation_cache().root
        self.path = Path(path or cache_root / "validation_ledger.sqlite3").resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), timeout=5.0)
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS validation_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    ticker TEXT NOT NULL,
                    as_of TEXT NOT NULL,
                    metric TEXT NOT NULL,
                    value REAL,
                    state TEXT NOT NULL,
                    engine_version TEXT NOT NULL,
                    data_hash TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                )
                """
            )

    def append(
        self,
        ticker: str,
        as_of: Any,
        metrics: dict[str, float | int | None],
        *,
        state: str,
        engine_version: str,
        data_hash: str,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        timestamp = pd.Timestamp(as_of).isoformat()
        inserted = 0
        with self._connect() as connection:
            for metric, value in sorted(metrics.items()):
                token = json.dumps(
                    {
                        "schema": MONITOR_SCHEMA,
                        "ticker": str(ticker),
                        "as_of": timestamp,
                        "metric": str(metric),
                        "engine_version": str(engine_version),
                        "data_hash": str(data_hash),
                    },
                    sort_keys=True,
                )
                snapshot_id = sha256(token.encode("utf-8")).hexdigest()
                numeric = float(value) if value is not None and np.isfinite(float(value)) else None
                cursor = connection.execute(
                    "INSERT OR IGNORE INTO validation_snapshots VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        snapshot_id,
                        str(ticker),
                        timestamp,
                        str(metric),
                        numeric,
                        str(state),
                        str(engine_version),
                        str(data_hash),
                        json.dumps(metadata or {}, sort_keys=True, default=str),
                    ],
                )
                inserted += int(cursor.rowcount > 0)
        return inserted

    def history(self, ticker: str, limit: int = 500) -> pd.DataFrame:
        with self._connect() as connection:
            return pd.read_sql_query(
                "SELECT ticker, as_of, metric, value, state, engine_version, data_hash FROM validation_snapshots WHERE ticker = ? ORDER BY as_of DESC, metric LIMIT ?",
                connection,
                params=[str(ticker), int(limit)],
            )
