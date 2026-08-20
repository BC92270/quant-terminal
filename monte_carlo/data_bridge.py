from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Tuple

import numpy as np
import pandas as pd


SUPPORTED_PROVIDER_PERIODS = ("5y", "10y", "max")
SUPPORTED_PRICE_BASES = ("adjusted", "raw")
_CACHE_SCHEMA_VERSION = 1


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_ticker(ticker: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", str(ticker).strip().upper())
    return value or "UNKNOWN"


def default_cache_dir() -> Path:
    configured = os.environ.get("MC_LONG_HISTORY_CACHE_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path.cwd() / ".quant_cache" / "monte_carlo" / "long_history"


def _cache_paths(
    ticker: str,
    provider: str,
    period: str,
    price_basis: str,
    cache_dir: str | os.PathLike[str] | None,
) -> Tuple[Path, Path]:
    root = Path(cache_dir).expanduser() if cache_dir is not None else default_cache_dir()
    stem = "__".join(
        [
            _safe_ticker(ticker),
            re.sub(r"[^A-Za-z0-9._-]+", "_", str(provider).lower()),
            str(period).lower(),
            str(price_basis).lower(),
        ]
    )
    return root / f"{stem}.csv", root / f"{stem}.json"


def _flatten_provider_columns(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    if not isinstance(output.columns, pd.MultiIndex):
        return output

    recognized = {
        "date",
        "datetime",
        "open",
        "high",
        "low",
        "close",
        "adj close",
        "adj_close",
        "volume",
        "dividends",
        "stock splits",
        "stock_splits",
    }
    flattened: list[str] = []
    for column in output.columns:
        parts = [str(part) for part in column if str(part) not in {"", "None"}]
        chosen = None
        for part in parts:
            if part.strip().lower() in recognized:
                chosen = part
                break
        flattened.append(chosen or (parts[0] if parts else "column"))
    output.columns = flattened
    return output


def normalize_provider_history(
    frame: pd.DataFrame,
    price_basis: str = "adjusted",
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Normalize provider OHLCV data and make corporate-action handling explicit.

    ``adjusted`` uses Adj Close as the calibration close and scales OHLC by the
    same adjustment factor. This avoids silent split jumps while preserving an
    internally coherent OHLC path for barrier validation.
    """
    price_basis = str(price_basis or "adjusted").lower()
    if price_basis not in SUPPORTED_PRICE_BASES:
        price_basis = "adjusted"

    report: Dict[str, Any] = {
        "input_rows": int(len(frame)) if isinstance(frame, pd.DataFrame) else 0,
        "output_rows": 0,
        "price_basis_requested": price_basis,
        "price_basis_applied": "unavailable",
        "duplicate_dates_removed": 0,
        "missing_close_removed": 0,
        "nonpositive_close_removed": 0,
        "split_event_count": 0,
        "dividend_event_count": 0,
        "extreme_adjusted_return_count": 0,
        "warnings": [],
    }
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        report["warnings"].append("Provider returned an empty price history.")
        return pd.DataFrame(), report

    df = _flatten_provider_columns(frame)
    if "date" not in {str(c).strip().lower() for c in df.columns} and "datetime" not in {
        str(c).strip().lower() for c in df.columns
    }:
        df = df.reset_index()
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
    rename_map: Dict[str, str] = {}
    if "datetime" in df.columns and "date" not in df.columns:
        rename_map["datetime"] = "date"
    if "index" in df.columns and "date" not in df.columns:
        rename_map["index"] = "date"
    if "adjclose" in df.columns and "adj_close" not in df.columns:
        rename_map["adjclose"] = "adj_close"
    if "adjusted_close" in df.columns and "adj_close" not in df.columns:
        rename_map["adjusted_close"] = "adj_close"
    if "stock_splits" not in df.columns and "stock_split" in df.columns:
        rename_map["stock_split"] = "stock_splits"
    if rename_map:
        df = df.rename(columns=rename_map)

    if "close" not in df.columns and "adj_close" in df.columns:
        df["close"] = df["adj_close"]
    if "close" not in df.columns:
        report["warnings"].append("Provider history has no close or adjusted-close column.")
        return pd.DataFrame(), report

    if "date" not in df.columns:
        report["warnings"].append("Provider history has no usable date column.")
        return pd.DataFrame(), report

    df["date"] = pd.to_datetime(df["date"], errors="coerce", utc=True).dt.tz_convert(None)
    df = df.dropna(subset=["date"])
    report["duplicate_dates_removed"] = int(df["date"].duplicated(keep="last").sum())
    df = df.drop_duplicates(subset=["date"], keep="last").sort_values("date")

    numeric_columns = (
        "open",
        "high",
        "low",
        "close",
        "adj_close",
        "volume",
        "dividends",
        "stock_splits",
    )
    for column in numeric_columns:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")

    raw_close = df["close"].astype(float).copy()
    df["raw_close"] = raw_close
    applied_adjustment = False
    if price_basis == "adjusted" and "adj_close" in df.columns:
        adjusted = pd.to_numeric(df["adj_close"], errors="coerce")
        factor = adjusted / raw_close.replace(0.0, np.nan)
        factor = factor.where(np.isfinite(factor) & (factor > 0.0))
        valid_share = float(factor.notna().mean()) if len(factor) else 0.0
        if valid_share >= 0.90:
            factor = factor.ffill().bfill().fillna(1.0)
            for column in ("open", "high", "low", "close"):
                source = pd.to_numeric(df[column], errors="coerce") if column in df.columns else raw_close
                df[column] = source * factor
            df["close"] = adjusted.where(adjusted > 0.0, df["close"])
            applied_adjustment = True
            report["price_basis_applied"] = "adjusted_ohlc_from_adj_close"
        else:
            report["warnings"].append(
                "Adjusted close coverage was insufficient; raw OHLC was retained."
            )

    if not applied_adjustment:
        for column in ("open", "high", "low"):
            if column not in df.columns:
                df[column] = raw_close
        report["price_basis_applied"] = "raw_ohlc"

    if "volume" not in df.columns:
        df["volume"] = np.nan
    if "dividends" not in df.columns:
        df["dividends"] = 0.0
    if "stock_splits" not in df.columns:
        df["stock_splits"] = 0.0

    report["missing_close_removed"] = int(df["close"].isna().sum())
    report["nonpositive_close_removed"] = int((df["close"] <= 0.0).sum())
    df = df.replace([np.inf, -np.inf], np.nan).dropna(subset=["close"])
    df = df[df["close"] > 0.0].copy()

    report["split_event_count"] = int((df["stock_splits"].fillna(0.0).abs() > 0.0).sum())
    report["dividend_event_count"] = int((df["dividends"].fillna(0.0).abs() > 0.0).sum())
    adjusted_returns = df["close"].pct_change()
    report["extreme_adjusted_return_count"] = int((adjusted_returns.abs() > 0.50).sum())
    if report["extreme_adjusted_return_count"] > 0:
        report["warnings"].append(
            f"{report['extreme_adjusted_return_count']} adjusted return(s) above 50% remain; corporate-action review required."
        )

    output_columns = [
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "adj_close",
        "raw_close",
        "dividends",
        "stock_splits",
    ]
    output = df[[column for column in output_columns if column in df.columns]].reset_index(drop=True)
    report["output_rows"] = int(len(output))
    if not output.empty:
        report["start_date"] = output["date"].iloc[0].isoformat()
        report["end_date"] = output["date"].iloc[-1].isoformat()
    return output, report


def _load_cache(data_path: Path, metadata_path: Path) -> Tuple[pd.DataFrame | None, Dict[str, Any] | None]:
    if not data_path.exists() or not metadata_path.exists():
        return None, None
    try:
        frame = pd.read_csv(data_path, parse_dates=["date"])
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if int(metadata.get("cache_schema_version", 0)) != _CACHE_SCHEMA_VERSION:
            return None, None
        return frame, metadata
    except Exception:
        return None, None


def _write_cache(data_path: Path, metadata_path: Path, frame: pd.DataFrame, metadata: Mapping[str, Any]) -> None:
    data_path.parent.mkdir(parents=True, exist_ok=True)
    data_tmp = data_path.with_suffix(data_path.suffix + ".tmp")
    meta_tmp = metadata_path.with_suffix(metadata_path.suffix + ".tmp")
    frame.to_csv(data_tmp, index=False)
    meta_tmp.write_text(json.dumps(dict(metadata), indent=2, sort_keys=True, default=str), encoding="utf-8")
    data_tmp.replace(data_path)
    meta_tmp.replace(metadata_path)


def _cache_age_hours(metadata: Mapping[str, Any], now: datetime) -> float | None:
    fetched = metadata.get("fetched_at_utc")
    if not fetched:
        return None
    try:
        timestamp = datetime.fromisoformat(str(fetched).replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        return max(0.0, (now - timestamp.astimezone(timezone.utc)).total_seconds() / 3600.0)
    except Exception:
        return None


def _yfinance_fetcher(ticker: str, period: str) -> pd.DataFrame:
    try:
        import yfinance as yf
    except Exception as exc:  # pragma: no cover - environment dependent
        raise RuntimeError("yfinance is not installed") from exc

    return yf.download(
        ticker,
        period=period,
        interval="1d",
        progress=False,
        auto_adjust=False,
        actions=True,
        group_by="column",
        threads=False,
        timeout=15,
    )


def fetch_long_history(
    ticker: str,
    period: str = "10y",
    provider: str = "yfinance",
    price_basis: str = "adjusted",
    cache_ttl_hours: int = 12,
    force_refresh: bool = False,
    allow_stale_fallback: bool = True,
    cache_dir: str | os.PathLike[str] | None = None,
    provider_fetcher: Callable[[str, str], pd.DataFrame] | None = None,
    now: datetime | None = None,
) -> Tuple[pd.DataFrame | None, Dict[str, Any]]:
    """Fetch and cache a long daily history with explicit provenance.

    The function never hides provider failure. A fresh cache is preferred; when
    a live request fails, a stale cache may be used only with an explicit
    ``STALE_CACHE_FALLBACK`` status.
    """
    now = now or _utc_now()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    period = str(period or "10y").lower()
    if period not in SUPPORTED_PROVIDER_PERIODS:
        period = "10y"
    price_basis = str(price_basis or "adjusted").lower()
    if price_basis not in SUPPORTED_PRICE_BASES:
        price_basis = "adjusted"
    provider = str(provider or "yfinance").lower()
    cache_ttl_hours = max(0, int(cache_ttl_hours))

    data_path, metadata_path = _cache_paths(ticker, provider, period, price_basis, cache_dir)
    cached_frame, cached_metadata = _load_cache(data_path, metadata_path)
    cached_age = _cache_age_hours(cached_metadata or {}, now) if cached_metadata else None
    cache_fresh = cached_frame is not None and cached_age is not None and cached_age <= cache_ttl_hours

    base_report: Dict[str, Any] = {
        "provider": provider,
        "ticker": str(ticker),
        "period": period,
        "price_basis": price_basis,
        "cache_ttl_hours": cache_ttl_hours,
        "force_refresh": bool(force_refresh),
        "cache_path": str(data_path),
        "cache_age_hours": cached_age,
        "status": "NOT_RUN",
        "ok": False,
        "warnings": [],
        "error": None,
    }

    if cache_fresh and not force_refresh:
        report = dict(base_report)
        report.update(cached_metadata or {})
        report.update(
            {
                "status": "CACHE_HIT",
                "ok": True,
                "cache_age_hours": cached_age,
                "selected_rows": int(len(cached_frame)),
            }
        )
        return cached_frame.copy(), report

    fetcher = provider_fetcher
    if fetcher is None:
        if provider != "yfinance":
            base_report["status"] = "FAILED"
            base_report["error"] = f"Unsupported provider: {provider}"
            return None, base_report
        fetcher = _yfinance_fetcher

    try:
        raw = fetcher(str(ticker), period)
        normalized, normalization = normalize_provider_history(raw, price_basis=price_basis)
        if normalized.empty:
            raise RuntimeError("provider returned no normalized rows")

        last_date = pd.Timestamp(normalized["date"].iloc[-1])
        last_date_utc = last_date.tz_localize(timezone.utc) if last_date.tzinfo is None else last_date.tz_convert(timezone.utc)
        observation_age_days = max(0.0, (now - last_date_utc.to_pydatetime()).total_seconds() / 86_400.0)
        warnings = list(normalization.get("warnings", []))
        if observation_age_days > 10.0:
            warnings.append(f"Provider history last observation is {observation_age_days:.1f} days old.")

        metadata: Dict[str, Any] = {
            "cache_schema_version": _CACHE_SCHEMA_VERSION,
            "provider": provider,
            "ticker": str(ticker),
            "period": period,
            "price_basis": price_basis,
            "fetched_at_utc": now.astimezone(timezone.utc).isoformat(),
            "last_observation": last_date.isoformat(),
            "observation_age_days": observation_age_days,
            "selected_rows": int(len(normalized)),
            "normalization": normalization,
            "warnings": warnings,
        }
        _write_cache(data_path, metadata_path, normalized, metadata)
        report = dict(base_report)
        report.update(metadata)
        report.update({"status": "LIVE_FETCH", "ok": True, "cache_age_hours": 0.0})
        return normalized.copy(), report
    except Exception as exc:
        if allow_stale_fallback and cached_frame is not None:
            report = dict(base_report)
            report.update(cached_metadata or {})
            warnings = list(report.get("warnings", []))
            warnings.append(f"Live provider request failed; stale cache used: {exc}")
            report.update(
                {
                    "status": "STALE_CACHE_FALLBACK",
                    "ok": True,
                    "error": str(exc),
                    "warnings": warnings,
                    "cache_age_hours": cached_age,
                    "selected_rows": int(len(cached_frame)),
                }
            )
            return cached_frame.copy(), report

        base_report.update({"status": "FAILED", "ok": False, "error": str(exc)})
        base_report["warnings"].append(f"Automatic long-history provider failed: {exc}")
        return None, base_report
