"""V2.5.3 frozen-spec external replication across untouched assets.

This module deliberately does *not* modify any behavioral-state equation, threshold,
walk-forward rule, or evidence classifier.  It rebuilds only the historical proxy /
latent-state history for a new asset and passes that state into the already locked
V2.4.1 validation engine.

Primary external validation is CORE ONLY.  Narrative/options and Behavioral Memory
are excluded from the cross-asset transfer score because they do not yet have a long
point-in-time archive and because the aim is to test portability of the five frozen
latent mechanisms without adding new degrees of freedom after the SPY holdout was seen.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from .engine import _historical_state_series
from .latent_state import LATENT_KEYS, build_latent_state_bundle
from .walk_forward import build_validation_manifest, choose_validation_config, evaluate_mechanisms_walk_forward
from .market_sessions import last_fully_closed_us_session_cutoff, trim_frame_to_closed_sessions

EXTERNAL_VALIDATION_VERSION = "V2.5.3"
EXTERNAL_CACHE_SCHEMA_VERSION = 1
EXTERNAL_CACHE_DIRNAME = "external"
LEGACY_EXTERNAL_CACHE_DIRNAME = ".market_psychology_external_cache"
EXTERNAL_TARGET_FETCH_PASSES = 2
EXTERNAL_CACHE_MAX_LAG_DAYS = 3
DEFAULT_EXTERNAL_UNIVERSE = ("QQQ", "IWM", "DIA")


def _fetch_target_price_history_uncached(symbol: str, period: str):
    """Run the target waterfall without Streamlit memoization.

    External replication needs a genuine second network attempt after a transient
    failure. Importing the cached public helper here would simply replay the same
    cached empty DataFrame for up to ten minutes.
    """
    from .data import fetch_price_history_uncached
    return fetch_price_history_uncached(symbol, period=period, interval="1d")


def _fetch_price_history(symbol: str, period: str):
    """Backward-compatible external-target hook; uncached by design in V2.5.3."""
    return _fetch_target_price_history_uncached(symbol, period)


def _fetch_benchmark_price_history_cached(symbol: str, period: str):
    """Use the normal cached helper for 1Y benchmark context.

    Benchmarks are not the external target under test, so keeping memoization here
    avoids multiplying provider calls while preserving the frozen state equations.
    """
    from .data import fetch_price_history
    return fetch_price_history(symbol, period=period, interval="1d")


def _default_benchmarks() -> tuple[str, ...]:
    from .config import DEFAULT_BENCHMARKS
    return tuple(DEFAULT_BENCHMARKS)


def _minimum_history_rows(period: str) -> int:
    return {"6mo": 90, "1y": 180, "2y": 390, "5y": 950, "10y": 1900}.get(str(period or "5y").lower(), 950)


def _cache_root() -> Path:
    """Package-local external cache with one-time legacy migration.

    V2.5.3 scientific equations remain unchanged; only the runtime storage path is
    consolidated inside ``market_psychology/external`` so the whole Psychology Lab
    can be copied as one folder. An explicit environment override still wins.
    """
    override = os.getenv("MARKET_PSYCHOLOGY_EXTERNAL_CACHE_DIR", "").strip()
    if override:
        root = Path(override).expanduser()
        root.mkdir(parents=True, exist_ok=True)
        return root

    root = Path(__file__).resolve().parent / EXTERNAL_CACHE_DIRNAME
    root.mkdir(parents=True, exist_ok=True)

    legacy = Path.cwd() / LEGACY_EXTERNAL_CACHE_DIRNAME
    if legacy.exists() and legacy.is_dir():
        try:
            for src in legacy.iterdir():
                if not src.is_file():
                    continue
                dst = root / src.name
                if not dst.exists():
                    shutil.copy2(src, dst)
        except Exception:
            # Migration is convenience only; cache failure must never block research.
            pass
    return root


def _cache_token(value: str) -> str:
    return "".join(ch for ch in str(value).upper() if ch.isalnum() or ch in {"-", "_"}) or "UNKNOWN"


def _cache_paths(symbol: str, period: str) -> tuple[Path, Path]:
    stem = f"{_cache_token(symbol)}_{_cache_token(period)}_closed"
    root = _cache_root()
    return root / f"{stem}.csv", root / f"{stem}.json"


def _frame_last_date(frame: pd.DataFrame) -> str | None:
    if frame is None or frame.empty or "date" not in frame.columns:
        return None
    dates = pd.to_datetime(frame["date"], errors="coerce", utc=True).dropna()
    return dates.max().date().isoformat() if not dates.empty else None


def _frame_first_date(frame: pd.DataFrame) -> str | None:
    if frame is None or frame.empty or "date" not in frame.columns:
        return None
    dates = pd.to_datetime(frame["date"], errors="coerce", utc=True).dropna()
    return dates.min().date().isoformat() if not dates.empty else None


def _cache_digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _cacheable_frame(frame: pd.DataFrame, period: str) -> bool:
    return isinstance(frame, pd.DataFrame) and not frame.empty and len(frame) >= _minimum_history_rows(period) and "date" in frame.columns and "close" in frame.columns


def _persist_external_price_cache(
    symbol: str,
    period: str,
    frame: pd.DataFrame,
    *,
    source_provider: str,
    cutoff_meta: dict[str, Any],
) -> dict[str, Any]:
    """Persist only a fully-closed, sufficiently deep price history.

    This cache is a data-resilience layer, not a model artifact.  It contains OHLCV
    only and never API keys.  Atomic replacement prevents a partial write from being
    mistaken for a validated cache on the next run.
    """
    if not _cacheable_frame(frame, period):
        return {"status": "cache_not_written", "detail": "insufficient_or_invalid_history"}
    csv_path, meta_path = _cache_paths(symbol, period)
    try:
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        work = frame.copy()
        work["date"] = pd.to_datetime(work["date"], errors="coerce", utc=True)
        work = work.dropna(subset=["date", "close"]).sort_values("date").drop_duplicates("date").reset_index(drop=True)
        last_date = _frame_last_date(work)
        cutoff_date = str(cutoff_meta.get("cutoff_date") or "")
        if cutoff_date and last_date and last_date > cutoff_date:
            return {"status": "cache_not_written", "detail": "history_extends_beyond_closed_session_cutoff"}

        tmp_csv = csv_path.with_suffix(csv_path.suffix + ".tmp")
        tmp_meta = meta_path.with_suffix(meta_path.suffix + ".tmp")
        work.to_csv(tmp_csv, index=False)
        meta = {
            "schema_version": EXTERNAL_CACHE_SCHEMA_VERSION,
            "symbol": str(symbol).upper(),
            "period": str(period).lower(),
            "source_provider": str(source_provider or "N/A"),
            "source_mode": "LIVE PROVIDER",
            "rows": int(len(work)),
            "first_date": _frame_first_date(work),
            "last_date": last_date,
            "stored_at_utc": datetime.now(timezone.utc).isoformat(),
            "closed_session_cutoff": dict(cutoff_meta or {}),
        }
        meta["csv_sha256"] = _cache_digest(tmp_csv)
        tmp_meta.write_text(json.dumps(meta, indent=2, default=str))
        tmp_csv.replace(csv_path)
        tmp_meta.replace(meta_path)
        return {"status": "cache_written", "path": str(csv_path), **meta}
    except Exception as exc:
        return {"status": "cache_write_error", "detail": type(exc).__name__}


def _load_external_price_cache(
    symbol: str,
    period: str,
    *,
    cutoff_meta: dict[str, Any] | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    csv_path, meta_path = _cache_paths(symbol, period)
    if not csv_path.exists() or not meta_path.exists():
        return pd.DataFrame(), {"provider": "Local cache", "status": "cache_missing"}
    try:
        meta = json.loads(meta_path.read_text())
        if int(meta.get("schema_version", -1)) != EXTERNAL_CACHE_SCHEMA_VERSION:
            return pd.DataFrame(), {"provider": "Local cache", "status": "cache_schema_mismatch"}
        if str(meta.get("symbol", "")).upper() != str(symbol).upper() or str(meta.get("period", "")).lower() != str(period).lower():
            return pd.DataFrame(), {"provider": "Local cache", "status": "cache_identity_mismatch"}
        if str(meta.get("csv_sha256", "")) != _cache_digest(csv_path):
            return pd.DataFrame(), {"provider": "Local cache", "status": "cache_hash_mismatch"}

        frame = pd.read_csv(csv_path)
        if "date" not in frame.columns or "close" not in frame.columns:
            return pd.DataFrame(), {"provider": "Local cache", "status": "cache_bad_schema"}
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce", utc=True)
        for col in ["open", "high", "low", "close", "adj_close", "volume"]:
            if col in frame.columns:
                frame[col] = pd.to_numeric(frame[col], errors="coerce")
        frame = frame.dropna(subset=["date", "close"]).sort_values("date").drop_duplicates("date").reset_index(drop=True)
        if not _cacheable_frame(frame, period):
            return pd.DataFrame(), {"provider": "Local cache", "status": "cache_insufficient_history", "rows": int(len(frame))}

        cutoff = cutoff_meta or last_fully_closed_us_session_cutoff().as_dict()
        cutoff_date = pd.Timestamp(str(cutoff.get("cutoff_date"))).date()
        last_date = pd.Timestamp(_frame_last_date(frame)).date()
        if last_date > cutoff_date:
            return pd.DataFrame(), {"provider": "Local cache", "status": "cache_future_bar_rejected", "last_date": str(last_date), "cutoff_date": str(cutoff_date)}
        lag_days = int((cutoff_date - last_date).days)
        if lag_days > EXTERNAL_CACHE_MAX_LAG_DAYS:
            return pd.DataFrame(), {"provider": "Local cache", "status": "cache_stale", "last_date": str(last_date), "cutoff_date": str(cutoff_date), "lag_days": lag_days}

        frame.attrs["provider"] = str(meta.get("source_provider", "N/A"))
        frame.attrs["provider_attempts"] = [{
            "provider": "Local cache",
            "status": "cache_hit_validated",
            "rows": int(len(frame)),
            "detail": f"origin={meta.get('source_provider','N/A')} · last={last_date} · cutoff={cutoff_date} · lag={lag_days}d",
        }]
        frame.attrs["symbol"] = str(symbol).upper()
        return frame, {
            "provider": "Local cache",
            "status": "cache_hit_validated",
            "source_provider": str(meta.get("source_provider", "N/A")),
            "rows": int(len(frame)),
            "first_date": _frame_first_date(frame),
            "last_date": _frame_last_date(frame),
            "cutoff_date": str(cutoff_date),
            "lag_days": lag_days,
            "cache_path": str(csv_path),
        }
    except Exception as exc:
        return pd.DataFrame(), {"provider": "Local cache", "status": "cache_read_error", "detail": type(exc).__name__}


_TRANSIENT_EXTERNAL_STATUSES = {
    "request_error",
    "rate_limited",
    "provider_server_error",
    "http_error",
    "bad_json",
    "empty",
    "normalize_empty",
    "empty_or_rate_limited",
}

_PERMANENT_EXTERNAL_STATUSES = {
    "disabled",
    "package_unavailable",
    "unsupported_symbol",
    "unauthorized_or_unentitled",
    "premium_full_history_required",
    "insufficient_history",
    "insufficient_history_or_plan_limit",
}


def _retry_decision(attempts: list[dict[str, Any]]) -> tuple[bool, float, str]:
    """Classify a failed target waterfall without changing the scientific model.

    A second *uncached* pass is useful for transient transport/provider failures.
    Pure entitlement/history-depth failures are not retried because they cannot
    recover a few seconds later and would only consume quota.
    """
    statuses = [str(r.get("status", "")).strip().lower() for r in attempts if isinstance(r, dict)]
    statuses = [s for s in statuses if s]
    if not statuses:
        return True, 1.0, "no_provider_status_recorded"

    transient = [s for s in statuses if s in _TRANSIENT_EXTERNAL_STATUSES]
    if transient:
        if "rate_limited" in transient:
            return True, 3.0, "rate_limit_or_transient_provider_failure"
        if "provider_server_error" in transient or "request_error" in transient:
            return True, 1.5, "transient_transport_or_server_failure"
        return True, 0.75, "transient_empty_or_payload_failure"

    if statuses and all(s in _PERMANENT_EXTERNAL_STATUSES for s in statuses):
        return False, 0.0, "all_provider_failures_non_retryable"

    # Unknown failures get one conservative second chance; the retry is still bounded.
    return True, 1.0, "unknown_failure_one_bounded_retry"


def _fetch_external_target_resilient(symbol: str, period: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Run a bounded *truly uncached* target waterfall, then validated local cache.

    V2.5.3 fixes the V2.5.2 retry bug: the target calls
    ``fetch_price_history_uncached`` directly, so pass 2 is a real provider request
    rather than the same Streamlit-cached failure. The ordinary terminal and benchmark
    fetches remain cached.
    """
    cutoff_meta = last_fully_closed_us_session_cutoff().as_dict()
    all_attempts: list[dict[str, Any]] = []

    for pass_no in range(1, EXTERNAL_TARGET_FETCH_PASSES + 1):
        frame = _fetch_price_history(symbol, period)
        attempts = _provider_attempts(frame if isinstance(frame, pd.DataFrame) else pd.DataFrame())
        pass_attempts: list[dict[str, Any]] = []
        for row in attempts:
            row = dict(row)
            row["pass"] = pass_no
            pass_attempts.append(row)
            all_attempts.append(row)

        if isinstance(frame, pd.DataFrame) and not frame.empty:
            closed, closed_meta = trim_frame_to_closed_sessions(frame)
            if _cacheable_frame(closed, period):
                provider = str(getattr(frame, "attrs", {}).get("provider", "N/A"))
                cache_write = _persist_external_price_cache(
                    symbol, period, closed, source_provider=provider, cutoff_meta=closed_meta
                )
                closed.attrs["provider"] = provider
                closed.attrs["provider_attempts"] = all_attempts
                return closed, {
                    "available": True,
                    "source_mode": "LIVE PROVIDER",
                    "provider": provider,
                    "provider_attempts": all_attempts,
                    "validation_cutoff": closed_meta,
                    "cache": cache_write,
                    "fetch_passes": pass_no,
                }

        if pass_no < EXTERNAL_TARGET_FETCH_PASSES:
            should_retry, delay, reason = _retry_decision(pass_attempts)
            all_attempts.append({
                "provider": "External retry controller",
                "status": "retry_scheduled" if should_retry else "retry_skipped",
                "http": "",
                "rows": "",
                "detail": f"pass={pass_no} · {reason} · delay={delay:.2f}s",
                "pass": pass_no,
            })
            if not should_retry:
                break
            time.sleep(delay)

    cached, cache_diag = _load_external_price_cache(symbol, period, cutoff_meta=cutoff_meta)
    all_attempts.append(dict(cache_diag))
    if isinstance(cached, pd.DataFrame) and not cached.empty:
        closed, closed_meta = trim_frame_to_closed_sessions(cached)
        cached.attrs["provider_attempts"] = all_attempts
        return closed, {
            "available": True,
            "source_mode": "VALIDATED LOCAL CACHE",
            "provider": str(cache_diag.get("source_provider", getattr(cached, "attrs", {}).get("provider", "N/A"))),
            "provider_attempts": all_attempts,
            "validation_cutoff": closed_meta,
            "cache": cache_diag,
            "fetch_passes": EXTERNAL_TARGET_FETCH_PASSES,
        }
    return pd.DataFrame(), {
        "available": False,
        "source_mode": "UNAVAILABLE",
        "provider": "N/A",
        "provider_attempts": all_attempts,
        "validation_cutoff": cutoff_meta,
        "cache": cache_diag,
        "fetch_passes": EXTERNAL_TARGET_FETCH_PASSES,
    }


def _fetch_external_benchmark(symbol: str, period: str, shared: dict[tuple[str, str], pd.DataFrame]) -> pd.DataFrame:
    key = (str(symbol).upper(), str(period).lower())
    if key in shared:
        return shared[key].copy()
    frame = _fetch_benchmark_price_history_cached(symbol, period)
    if isinstance(frame, pd.DataFrame) and not frame.empty:
        frame, _ = trim_frame_to_closed_sessions(frame)
    shared[key] = frame.copy() if isinstance(frame, pd.DataFrame) else pd.DataFrame()
    return shared[key].copy()


def _build_external_market_pack(
    symbol: str,
    period: str,
    *,
    shared_benchmarks: dict[tuple[str, str], pd.DataFrame] | None = None,
) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    target, source = _fetch_external_target_resilient(symbol, period)
    pack: dict[str, pd.DataFrame] = {str(symbol).upper(): target}
    if target.empty:
        return pack, source

    shared = shared_benchmarks if isinstance(shared_benchmarks, dict) else {}
    benchmark_period = "1y" if str(period).lower() in {"2y", "5y", "10y"} else period
    # Reuse a successfully fetched external target later as a benchmark for the
    # other untouched assets in the same batch. This reduces provider pressure
    # without altering any historical-state equation.
    shared[(str(symbol).upper(), str(benchmark_period).lower())] = target.copy()
    for raw in _default_benchmarks():
        bench = str(raw or "").upper().strip()
        if not bench or bench == str(symbol).upper() or bench in pack:
            continue
        pack[bench] = _fetch_external_benchmark(bench, benchmark_period, shared)
    return pack, source


ALLOWED_EXTERNAL_UNIVERSE = ("QQQ", "IWM", "DIA", "NVDA", "AAPL", "TSLA")


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        x = float(value)
        return x if np.isfinite(x) else default
    except Exception:
        return default


def _provider_attempts(frame: pd.DataFrame) -> list[dict[str, Any]]:
    try:
        raw = list(frame.attrs.get("provider_attempts", []))
    except Exception:
        raw = []
    out: list[dict[str, Any]] = []
    for r in raw:
        if not isinstance(r, dict):
            continue
        out.append({
            "provider": r.get("provider", "N/A"),
            "status": r.get("status", "N/A"),
            "http": r.get("http", ""),
            "rows": r.get("rows", ""),
            "detail": r.get("detail", r.get("api_code", "")),
        })
    return out


def build_frozen_external_state(
    symbol: str,
    period: str = "5y",
    *,
    shared_benchmarks: dict[tuple[str, str], pd.DataFrame] | None = None,
) -> dict[str, Any]:
    """Build only the historical state required by the locked validation engine.

    V2.5.3 changes *data resilience only*: the target receives a bounded fresh
    provider re-fetch and, if every provider still fails, a validated closed-session
    local cache may be used. No model equation, threshold, evidence rule, or outcome
    is re-estimated.
    """
    symbol = str(symbol or "").upper().strip()
    pack, source_meta = _build_external_market_pack(symbol, period, shared_benchmarks=shared_benchmarks)
    target = pack.get(symbol, pd.DataFrame()) if isinstance(pack, dict) else pd.DataFrame()
    cutoff_meta = source_meta.get("validation_cutoff", {}) if isinstance(source_meta, dict) else {}
    if target is None or target.empty:
        return {
            "available": False,
            "symbol": symbol,
            "reason": f"No {period} price history for {symbol} after bounded provider retries and validated-cache fallback.",
            "provider_attempts": source_meta.get("provider_attempts", []) if isinstance(source_meta, dict) else [],
            "validation_cutoff": cutoff_meta,
            "price_source_mode": "UNAVAILABLE",
            "cache": source_meta.get("cache", {}) if isinstance(source_meta, dict) else {},
        }

    # Target is already closed-session trimmed before it can enter the pack.
    # Trim again defensively; this is idempotent and preserves research integrity.
    target, cutoff_meta = trim_frame_to_closed_sessions(target)
    if target.empty:
        return {
            "available": False,
            "symbol": symbol,
            "reason": "No fully closed daily bar remains after the validation cutoff.",
            "provider_attempts": source_meta.get("provider_attempts", []) if isinstance(source_meta, dict) else [],
            "validation_cutoff": cutoff_meta,
            "price_source_mode": source_meta.get("source_mode", "UNAVAILABLE") if isinstance(source_meta, dict) else "UNAVAILABLE",
        }

    raw_history = _historical_state_series(target, pack)
    if raw_history is None or raw_history.empty:
        return {"available": False, "symbol": symbol, "reason": "Historical behavioral proxy series unavailable."}

    current_raw: dict[str, float] = {}
    for key in LATENT_KEYS:
        s = pd.to_numeric(raw_history.get(key), errors="coerce") if key in raw_history.columns else pd.Series(dtype=float)
        valid = s.dropna()
        current_raw[key] = float(valid.iloc[-1]) if not valid.empty else 50.0

    # Confidence affects only the current one-step update in build_latent_state_bundle;
    # the historical normalized/latent series used by walk-forward does not depend on
    # this arbitrary current value.  Keep a fixed non-asset-specific value nonetheless.
    confidence_map = {key: 75.0 for key in LATENT_KEYS}
    latent = build_latent_state_bundle(raw_history, current_raw, confidence_map)
    history = latent.get("history", pd.DataFrame())
    if history is None or history.empty:
        return {"available": False, "symbol": symbol, "reason": "Causal latent-state history unavailable."}

    return {
        "available": True,
        "symbol": symbol,
        "history": history,
        "target_history": target,
        "behavioral_data": {},
        "external_validation_mode": True,
        "external_validation_note": "CORE ONLY · frozen historical proxy/latent specification; no narrative/options/Memory transfer claim.",
        "price_provider": str(source_meta.get("provider", getattr(target, "attrs", {}).get("provider", "N/A"))),
        "price_source_mode": str(source_meta.get("source_mode", "LIVE PROVIDER")),
        "provider_attempts": source_meta.get("provider_attempts", _provider_attempts(target)),
        "validation_cutoff": cutoff_meta,
        "cache": source_meta.get("cache", {}),
    }


def run_external_asset(
    symbol: str, *, period: str = "5y", profile: str = "STANDARD",
    shared_benchmarks: dict[tuple[str, str], pd.DataFrame] | None = None,
) -> dict[str, Any]:
    state = build_frozen_external_state(symbol, period=period, shared_benchmarks=shared_benchmarks)
    if not state.get("available"):
        return state
    history = state.get("history", pd.DataFrame())
    config = choose_validation_config(len(history), profile)
    if config is None:
        return {
            "available": False,
            "symbol": str(symbol).upper(),
            "reason": "Insufficient history for the frozen V2.4.1 external walk-forward configuration.",
            "provider_attempts": state.get("provider_attempts", []),
        }
    mechanisms = evaluate_mechanisms_walk_forward(history, config)
    if not mechanisms.get("available"):
        return {
            "available": False,
            "symbol": str(symbol).upper(),
            "reason": mechanisms.get("reason", "Walk-forward unavailable."),
            "provider_attempts": state.get("provider_attempts", []),
        }
    manifest = build_validation_manifest(str(symbol).upper(), history, config)
    cutoff_meta = state.get("validation_cutoff", {}) if isinstance(state.get("validation_cutoff", {}), dict) else {}
    manifest["closed_session_cutoff"] = cutoff_meta
    bundle = {
        "available": True,
        "version": "V2.4.1-FROZEN-EXTERNAL",
        "config": config,
        "mechanisms": mechanisms,
        "manifest": manifest,
        "status": "EXTERNAL REPLICATION · CORE ONLY · RESEARCH",
    }
    bundle["external_validation"] = {
        "version": EXTERNAL_VALIDATION_VERSION,
        "scope": "CORE FROZEN MECHANISMS ONLY",
        "symbol": str(symbol).upper(),
        "period": period,
        "profile": profile,
        "price_provider": state.get("price_provider", "N/A"),
        "price_source_mode": state.get("price_source_mode", "LIVE PROVIDER"),
        "cache": state.get("cache", {}),
        "validation_cutoff": cutoff_meta,
    }
    return {"available": True, "symbol": str(symbol).upper(), "state": state, "bundle": bundle}


def _asset_row(result: dict[str, Any]) -> dict[str, Any]:
    symbol = str(result.get("symbol", ""))
    if not result.get("available"):
        return {
            "Asset": symbol,
            "Status": "UNAVAILABLE",
            "Rows": np.nan,
            "Folds": np.nan,
            "Hypotheses": np.nan,
            "FDR survivors": np.nan,
            "Robust OOS": np.nan,
            "Core stat replicated": np.nan,
            "Directional confirmations": np.nan,
            "Failed replications": np.nan,
            "Provider": "N/A",
            "Source mode": str(result.get("price_source_mode", "UNAVAILABLE")),
            "Validation end": "N/A",
            "Reason": str(result.get("reason", "Unavailable")),
        }
    bundle = result.get("bundle", {})
    mech = bundle.get("mechanisms", {}) if isinstance(bundle.get("mechanisms", {}), dict) else {}
    manifest = bundle.get("manifest", {}) if isinstance(bundle.get("manifest", {}), dict) else {}
    ext = bundle.get("external_validation", {}) if isinstance(bundle.get("external_validation", {}), dict) else {}
    folds = mech.get("folds", [])
    wf_folds = sum(1 for f in folds if getattr(f, "partition", "") == "WALK_FORWARD") if folds else 0
    return {
        "Asset": symbol,
        "Status": "OK",
        "Rows": int(manifest.get("rows", 0) or 0),
        "Folds": int(wf_folds),
        "Hypotheses": int(mech.get("hypotheses", 0) or 0),
        "FDR survivors": int(mech.get("fdr_survivors", 0) or 0),
        "Robust OOS": int(mech.get("robust_oos", 0) or 0),
        "Core stat replicated": int(mech.get("statistically_replicated", 0) or 0),
        "Directional confirmations": int(mech.get("directionally_confirmed", 0) or 0),
        "Failed replications": int(mech.get("failed_replication", 0) or 0),
        "Provider": ext.get("price_provider", "N/A"),
        "Source mode": ext.get("price_source_mode", "LIVE PROVIDER"),
        "Validation end": str(manifest.get("history_end", ""))[:10],
        "Reason": "",
    }


def _evidence_rank(value: Any) -> int:
    return {"NONE": 0, "LOW": 1, "MODERATE": 2, "HIGH": 3}.get(str(value).upper(), -1)


def summarize_external_results(results: Iterable[dict[str, Any]]) -> dict[str, Any]:
    results = list(results)
    asset_summary = pd.DataFrame([_asset_row(r) for r in results])
    evidence_rows: list[dict[str, Any]] = []
    sign_rows: list[dict[str, Any]] = []

    for r in results:
        if not r.get("available"):
            continue
        symbol = str(r.get("symbol", ""))
        bundle = r.get("bundle", {})
        mech = bundle.get("mechanisms", {}) if isinstance(bundle.get("mechanisms", {}), dict) else {}
        matrix = mech.get("evidence_matrix", pd.DataFrame())
        if isinstance(matrix, pd.DataFrame) and not matrix.empty:
            for _, row in matrix.iterrows():
                m = str(row.get("Mechanism", ""))
                for target in ["Return", "Future vol", "Tail loss", "Behavioral state shift"]:
                    evidence_rows.append({"Asset": symbol, "Mechanism": m, "Target": target, "Evidence": str(row.get(target, "N/A"))})
        dev = mech.get("development", pd.DataFrame())
        if isinstance(dev, pd.DataFrame) and not dev.empty:
            tmp = dev.copy()
            tmp["OOS IC"] = pd.to_numeric(tmp.get("OOS IC"), errors="coerce")
            for (m, target), g in tmp.groupby(["Mechanism", "Target"], dropna=False):
                vals = pd.to_numeric(g["OOS IC"], errors="coerce").dropna()
                med = float(vals.median()) if not vals.empty else np.nan
                sign_rows.append({"Asset": symbol, "Mechanism": str(m), "Target": str(target), "Median OOS IC": med})

    evidence_long = pd.DataFrame(evidence_rows)
    sign_long = pd.DataFrame(sign_rows)
    support_rows: list[dict[str, Any]] = []
    if not evidence_long.empty:
        for (mech, target), g in evidence_long.groupby(["Mechanism", "Target"], dropna=False):
            usable = g[g["Evidence"].ne("N/A")].copy()
            ranks = usable["Evidence"].map(_evidence_rank) if not usable.empty else pd.Series(dtype=float)
            moderate_plus = int((ranks >= 2).sum()) if not ranks.empty else 0
            low_plus = int((ranks >= 1).sum()) if not ranks.empty else 0
            none_n = int((ranks == 0).sum()) if not ranks.empty else 0
            sign_sub = sign_long[(sign_long["Mechanism"] == mech) & (sign_long["Target"] == target)] if not sign_long.empty else pd.DataFrame()
            signs = np.sign(pd.to_numeric(sign_sub.get("Median OOS IC"), errors="coerce").dropna()) if not sign_sub.empty else pd.Series(dtype=float)
            signs = signs[signs != 0]
            if len(signs):
                pos = int((signs > 0).sum())
                neg = int((signs < 0).sum())
                sign_consensus = max(pos, neg) / len(signs)
                dominant_sign = "+" if pos > neg else "-" if neg > pos else "MIXED"
            else:
                sign_consensus = np.nan
                dominant_sign = "N/A"

            n = len(usable)
            if n >= 2 and moderate_plus >= 2 and (not np.isfinite(sign_consensus) or sign_consensus >= 0.67):
                support = "CONSISTENT EXTERNAL SUPPORT"
            elif n >= 2 and low_plus >= 2 and (not np.isfinite(sign_consensus) or sign_consensus >= 0.67):
                support = "DIRECTIONAL EXTERNAL SUPPORT"
            elif n >= 2 and low_plus >= 1 and none_n >= 1:
                support = "MIXED"
            elif n >= 1 and low_plus >= 1:
                support = "SINGLE-ASSET ONLY"
            else:
                support = "NO EXTERNAL SUPPORT"
            support_rows.append({
                "Mechanism": mech,
                "Target": target,
                "Assets evaluable": n,
                "Moderate/High": moderate_plus,
                "Low+": low_plus,
                "None": none_n,
                "Dominant OOS sign": dominant_sign,
                "Sign consensus": sign_consensus,
                "External support": support,
            })
    support = pd.DataFrame(support_rows)
    return {
        "asset_summary": asset_summary,
        "evidence_long": evidence_long,
        "sign_long": sign_long,
        "support": support,
        "available_assets": int(asset_summary["Status"].eq("OK").sum()) if not asset_summary.empty else 0,
        "requested_assets": int(len(asset_summary)),
    }


def run_external_batch(
    symbols: Iterable[str],
    *,
    period: str = "5y",
    profile: str = "STANDARD",
) -> dict[str, Any]:
    clean: list[str] = []
    for s in symbols:
        x = str(s or "").upper().strip()
        if x and x not in clean:
            clean.append(x)
    shared_benchmarks: dict[tuple[str, str], pd.DataFrame] = {}
    results = [run_external_asset(s, period=period, profile=profile, shared_benchmarks=shared_benchmarks) for s in clean]
    summary = summarize_external_results(results)
    asset_summary = summary.get("asset_summary", pd.DataFrame())
    validation_ends: list[str] = []
    if isinstance(asset_summary, pd.DataFrame) and not asset_summary.empty and "Status" in asset_summary.columns and "Validation end" in asset_summary.columns:
        validation_ends = sorted({str(x) for x in asset_summary.loc[asset_summary["Status"].eq("OK"), "Validation end"].dropna().astype(str) if str(x) not in {"", "N/A", "None"}})
    requested_n = int(len(clean))
    usable_n = int(summary.get("available_assets", 0) or 0)
    complete = requested_n > 0 and usable_n == requested_n
    ends_aligned = complete and len(validation_ends) == 1
    baseline_eligible = requested_n >= 3 and complete and ends_aligned
    if baseline_eligible:
        baseline_reason = f"ELIGIBLE · {usable_n}/{requested_n} assets · aligned {validation_ends[0]}"
    elif not complete:
        baseline_reason = f"NOT ELIGIBLE · {usable_n}/{requested_n} assets usable"
    elif requested_n < 3:
        baseline_reason = f"NOT ELIGIBLE · only {requested_n} external asset(s) requested"
    else:
        baseline_reason = "NOT ELIGIBLE · validation-end mismatch"

    return {
        "available": usable_n > 0,
        "version": EXTERNAL_VALIDATION_VERSION,
        "scope": "CORE FROZEN MECHANISMS ONLY",
        "period": period,
        "profile": profile,
        "symbols": clean,
        "results": results,
        "validation_end_aligned": ends_aligned,
        "validation_ends": validation_ends,
        "batch_complete": complete,
        "baseline_eligible": baseline_eligible,
        "baseline_reason": baseline_reason,
        **summary,
        "note": "External replication is a frozen-spec transfer test. V2.5.3 changes target data resilience only: true uncached target retries plus a validated closed-session local-cache fallback. No parameter is re-estimated from cross-asset outcomes, and narrative/options/Behavioral Memory are not promoted by this table.",
    }


def external_bundle_to_jsonable(bundle: dict[str, Any]) -> dict[str, Any]:
    def records(value: Any) -> list[dict[str, Any]]:
        if isinstance(value, pd.DataFrame):
            return value.replace({np.nan: None}).to_dict(orient="records")
        return []

    assets = []
    for r in bundle.get("results", []) if isinstance(bundle, dict) else []:
        if not isinstance(r, dict):
            continue
        entry = {"symbol": r.get("symbol"), "available": bool(r.get("available"))}
        if r.get("available"):
            b = r.get("bundle", {}) if isinstance(r.get("bundle", {}), dict) else {}
            m = b.get("manifest", {}) if isinstance(b.get("manifest", {}), dict) else {}
            mech = b.get("mechanisms", {}) if isinstance(b.get("mechanisms", {}), dict) else {}
            ext = b.get("external_validation", {}) if isinstance(b.get("external_validation", {}), dict) else {}
            state = r.get("state", {}) if isinstance(r.get("state", {}), dict) else {}
            entry.update({
                "data_source": {
                    "provider": ext.get("price_provider"),
                    "source_mode": ext.get("price_source_mode"),
                    "cache": ext.get("cache", {}),
                    "provider_attempts": state.get("provider_attempts", []),
                },
                "manifest": m,
                "counts": {
                    "hypotheses": mech.get("hypotheses"),
                    "fdr_survivors": mech.get("fdr_survivors"),
                    "robust_oos": mech.get("robust_oos"),
                    "statistically_replicated": mech.get("statistically_replicated"),
                    "directionally_confirmed": mech.get("directionally_confirmed"),
                    "failed_replication": mech.get("failed_replication"),
                },
                "evidence_matrix": records(mech.get("evidence_matrix")),
            })
        else:
            entry["reason"] = r.get("reason")
            entry["provider_attempts"] = r.get("provider_attempts", [])
        assets.append(entry)
    return {
        "external_validation_version": bundle.get("version"),
        "scope": bundle.get("scope"),
        "period": bundle.get("period"),
        "profile": bundle.get("profile"),
        "symbols": bundle.get("symbols", []),
        "note": bundle.get("note"),
        "asset_summary": records(bundle.get("asset_summary")),
        "cross_asset_support": records(bundle.get("support")),
        "validation_end_aligned": bundle.get("validation_end_aligned"),
        "validation_ends": bundle.get("validation_ends", []),
        "batch_complete": bundle.get("batch_complete"),
        "baseline_eligible": bundle.get("baseline_eligible"),
        "baseline_reason": bundle.get("baseline_reason"),
        "assets": assets,
    }


def external_bundle_json_bytes(bundle: dict[str, Any]) -> bytes:
    return json.dumps(external_bundle_to_jsonable(bundle), indent=2, default=str).encode("utf-8")
