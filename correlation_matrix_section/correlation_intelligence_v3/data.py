from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from typing import Any

import numpy as np
import pandas as pd

from .utils import max_consecutive_missing, normalize_ticker, unique_keep_order
from .synchronization import apply_alignment_lags, synchronization_audit
from .institutional_cache import get_correlation_cache
from .market_data_adapters import download_stooq_daily, validate_point_in_time_contract

try:
    import yfinance as yf
except Exception:  # pragma: no cover
    yf = None


@dataclass
class DataBundle:
    levels: pd.DataFrame
    changes: pd.DataFrame
    quality: pd.DataFrame
    source: str
    transform_map: dict[str, str]
    provider_map: dict[str, str] = field(default_factory=dict)
    synchronization: pd.DataFrame = field(default_factory=pd.DataFrame)
    alignment_lag_map: dict[str, int] = field(default_factory=dict)
    market_metadata: dict[str, Any] = field(default_factory=dict)
    data_contract: dict[str, Any] = field(default_factory=dict)
    cache_meta: dict[str, Any] = field(default_factory=dict)


def default_peer_universe(ticker: str) -> list[str]:
    t = normalize_ticker(ticker)
    universes = {
        "NVDA": ["NVDA", "AMD", "AVGO", "TSM", "ASML", "MU", "ARM", "MRVL", "SMH", "SOXX", "QQQ", "SPY", "TLT", "HYG", "GLD", "UUP", "^VIX"],
        "AMD": ["AMD", "NVDA", "AVGO", "TSM", "ASML", "MU", "ARM", "MRVL", "SMH", "SOXX", "QQQ", "SPY", "TLT", "HYG", "^VIX"],
        "AVGO": ["AVGO", "NVDA", "AMD", "TSM", "ASML", "MU", "MRVL", "QCOM", "SMH", "SOXX", "QQQ", "SPY", "TLT", "^VIX"],
        "AAPL": ["AAPL", "MSFT", "GOOGL", "META", "AMZN", "NVDA", "QQQ", "XLK", "SPY", "TLT", "UUP", "^VIX"],
        "MSFT": ["MSFT", "AAPL", "GOOGL", "AMZN", "META", "NVDA", "CRM", "QQQ", "XLK", "SPY", "TLT", "UUP", "^VIX"],
        "TSLA": ["TSLA", "RIVN", "LCID", "F", "GM", "NIO", "LI", "XLY", "QQQ", "SPY", "TLT", "USO", "^VIX"],
        "JPM": ["JPM", "BAC", "WFC", "C", "GS", "MS", "XLF", "KBE", "SPY", "TLT", "HYG", "^VIX"],
        "XOM": ["XOM", "CVX", "COP", "SLB", "EOG", "OXY", "XLE", "USO", "SPY", "UUP", "TLT"],
        "LLY": ["LLY", "NVO", "MRK", "PFE", "JNJ", "ABBV", "XLV", "IBB", "SPY", "TLT", "^VIX"],
    }
    if t in universes:
        return unique_keep_order(universes[t])
    return unique_keep_order([t, "SPY", "QQQ", "IWM", "TLT", "HYG", "GLD", "USO", "UUP", "BTC-USD", "^VIX"])


def classify_asset(ticker: str, primary: str, custom_map: dict[str, str] | None = None) -> str:
    t, p = normalize_ticker(ticker), normalize_ticker(primary)
    if custom_map and t in custom_map:
        return str(custom_map[t])
    if t == p:
        return "Primary"
    if t in {"SPY", "QQQ", "IWM", "DIA"}:
        return "Benchmark"
    if t in {"TLT", "IEF", "SHY", "BND"}:
        return "Rates ETF"
    if t in {"HYG", "LQD", "JNK"}:
        return "Credit ETF"
    if t in {"GLD", "SLV", "USO", "UNG", "DBC"}:
        return "Commodity ETF"
    if t in {"UUP", "FXE", "FXY"} or t.endswith("=X"):
        return "FX"
    if t.endswith("-USD"):
        return "Crypto"
    if t.startswith("^VIX") or t in {"VXX", "UVXY"}:
        return "Volatility"
    if t in {"SMH", "SOXX", "XLK", "XLF", "XLY", "XLV", "XLE", "XLC", "XLI", "XLP", "XLU", "KBE", "IBB"}:
        return "ETF / Sector"
    return "Peer Equity"


def _clean_index(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.index = pd.to_datetime(out.index, errors="coerce").tz_localize(None)
    out = out[~out.index.isna()].sort_index()
    out = out[~out.index.duplicated(keep="last")]
    return out


def primary_levels_from_app(price_data: pd.DataFrame, ticker: str) -> pd.Series | None:
    if price_data is None or price_data.empty:
        return None
    df = price_data.copy()
    df.columns = [str(c).lower() for c in df.columns]
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.tz_localize(None)
        df = df.set_index("date")
    else:
        df.index = pd.to_datetime(df.index, errors="coerce").tz_localize(None)
    col = "adj_close" if "adj_close" in df.columns else "close" if "close" in df.columns else None
    if col is None:
        return None
    s = pd.to_numeric(df[col], errors="coerce").rename(normalize_ticker(ticker))
    return s.dropna().sort_index()


def _extract_close_from_yf(raw: pd.DataFrame, ticker: str) -> pd.Series | None:
    if raw is None or raw.empty:
        return None
    t = normalize_ticker(ticker)
    if isinstance(raw.columns, pd.MultiIndex):
        for price_field in ("Close", "Adj Close"):
            if price_field in raw.columns.get_level_values(0) and t in raw[price_field].columns:
                return pd.to_numeric(raw[price_field][t], errors="coerce").rename(t)
        try:
            if ("Close", t) in raw.columns:
                return pd.to_numeric(raw[("Close", t)], errors="coerce").rename(t)
        except Exception:
            pass
    for c in ("Close", "Adj Close", "close", "adj_close"):
        if c in raw.columns:
            return pd.to_numeric(raw[c], errors="coerce").rename(t)
    return None


def download_levels_yfinance(tickers: list[str], period: str) -> pd.DataFrame:
    """Compatibility fallback only. No forward-fill is performed."""
    if yf is None or not tickers:
        return pd.DataFrame()
    try:
        raw = yf.download(
            tickers=tickers,
            period=period,
            interval="1d",
            progress=False,
            auto_adjust=True,
            threads=True,
            group_by="column",
        )
        if raw is None or raw.empty:
            return pd.DataFrame()
        frames: list[pd.Series] = []
        for t in tickers:
            s = _extract_close_from_yf(raw, t)
            if s is not None:
                frames.append(s)
        if not frames:
            return pd.DataFrame()
        return _clean_index(pd.concat(frames, axis=1))
    except Exception:
        frames = []
        for t in tickers:
            try:
                raw = yf.download(t, period=period, interval="1d", progress=False, auto_adjust=True, threads=False)
                s = _extract_close_from_yf(raw, t)
                if s is not None:
                    frames.append(s)
            except Exception:
                continue
        return _clean_index(pd.concat(frames, axis=1)) if frames else pd.DataFrame()


def transform_levels(levels: pd.DataFrame, transform_map: dict[str, str] | None = None) -> tuple[pd.DataFrame, dict[str, str]]:
    """
    Transform each series independently before pair alignment.

    Supported conventions:
      log_return    : log(P_t/P_t-1), default for tradable prices
      simple_return : P_t/P_t-1 - 1
      diff          : X_t-X_t-1 (yields/spreads/IV levels)
      bp_diff       : 10000*(X_t-X_t-1)
      log_diff      : log(X_t)-log(X_t-1)
    """
    if levels is None or levels.empty:
        return pd.DataFrame(), {}
    tmap = {normalize_ticker(k): str(v) for k, v in (transform_map or {}).items()}
    out = pd.DataFrame(index=levels.index)
    used: dict[str, str] = {}
    for col in levels.columns:
        t = normalize_ticker(col)
        s = pd.to_numeric(levels[col], errors="coerce")
        mode = tmap.get(t, "log_return")
        if mode == "simple_return":
            x = s.pct_change(fill_method=None)
        elif mode == "diff":
            x = s.diff()
        elif mode == "bp_diff":
            x = s.diff() * 10000.0
        elif mode == "log_diff":
            x = np.log(s.where(s > 0)).diff()
        else:
            x = np.log(s.where(s > 0) / s.shift(1).where(s.shift(1) > 0))
            mode = "log_return"
        out[t] = x.replace([np.inf, -np.inf], np.nan)
        used[t] = mode
    return out.dropna(how="all"), used


def _internal_quality(s: pd.Series) -> tuple[float, int]:
    non_missing = s.dropna()
    if non_missing.empty:
        return np.nan, 0
    start, end = non_missing.index.min(), non_missing.index.max()
    internal = s.loc[start:end]
    if internal.empty:
        return np.nan, 0
    return float(internal.isna().mean()), max_consecutive_missing(internal)


def _requested_period_calendar_days(period: str | None, as_of: pd.Timestamp | None) -> int | None:
    """Translate the supported yfinance-style period into an auditable calendar span.

    This deliberately returns ``None`` for ``max`` and unknown values: inventing a
    requested start date would make an absolute coverage metric look more precise
    than the underlying request actually is.
    """
    value = str(period or "").strip().lower()
    if not value or value == "max":
        return None
    if value == "ytd":
        if as_of is None or pd.isna(as_of):
            return None
        end = pd.Timestamp(as_of).tz_localize(None).normalize()
        return max(1, int((end - pd.Timestamp(year=end.year, month=1, day=1)).days) + 1)

    match = re.fullmatch(r"(\d+)\s*(d|wk|mo|y)", value)
    if not match:
        return None
    amount = int(match.group(1))
    multiplier = {"d": 1.0, "wk": 7.0, "mo": 365.25 / 12.0, "y": 365.25}[match.group(2)]
    return max(1, int(round(amount * multiplier)))


def build_quality(
    levels: pd.DataFrame,
    changes: pd.DataFrame,
    transform_map: dict[str, str],
    provider_map: dict[str, str],
    source: str,
    requested_period: str | None = None,
) -> pd.DataFrame:
    """Build an explicit, non-relative-only audit of history and missing data.

    ``Coverage %`` remains for backwards compatibility, but now means the most
    conservative available coverage measure: observed-grid completeness capped by
    requested-period calendar depth.  The former cross-sectional ratio is retained
    as ``Relative history depth %`` and must not be read as absolute coverage.
    """
    rows = []
    if levels is None:
        levels = pd.DataFrame()

    obs_counts = [int(levels[c].notna().sum()) for c in levels.columns if int(levels[c].notna().sum()) > 0]
    reference_obs = float(np.median(obs_counts)) if obs_counts else 0.0
    grid_obs = int(len(levels.index))
    grid_end = pd.Timestamp(levels.index.max()) if grid_obs else None
    requested_calendar_days = _requested_period_calendar_days(requested_period, grid_end)

    for col in levels.columns:
        s = pd.to_numeric(levels[col], errors="coerce")
        c = changes[col] if col in changes.columns else pd.Series(dtype=float)
        non_missing = int(s.notna().sum())
        start = s.dropna().index.min() if non_missing else None
        end = s.dropna().index.max() if non_missing else None
        internal_missing, largest_internal_gap = _internal_quality(s)
        valid_positions = np.flatnonzero(s.notna().to_numpy())
        leading_missing = int(valid_positions[0]) if len(valid_positions) else grid_obs
        trailing_missing = int(grid_obs - valid_positions[-1] - 1) if len(valid_positions) else 0
        internal_missing_obs = (
            int(s.iloc[valid_positions[0] : valid_positions[-1] + 1].isna().sum())
            if len(valid_positions)
            else 0
        )
        total_missing = max(0, grid_obs - non_missing)

        observed_grid_coverage = non_missing / grid_obs if grid_obs > 0 else np.nan
        relative_history_depth = min(1.0, non_missing / reference_obs) if reference_obs > 0 else np.nan
        within_history_coverage = 1.0 - internal_missing if not pd.isna(internal_missing) else np.nan
        history_span_days = (
            int((pd.Timestamp(end) - pd.Timestamp(start)).days) + 1
            if start is not None and end is not None
            else 0
        )
        requested_period_depth = (
            min(1.0, history_span_days / requested_calendar_days)
            if requested_calendar_days and history_span_days > 0
            else np.nan
        )
        coverage_components = [observed_grid_coverage]
        if not pd.isna(requested_period_depth):
            coverage_components.append(requested_period_depth)
        coverage = min(coverage_components) if coverage_components and not pd.isna(coverage_components[0]) else np.nan
        shortfall = max(0, int(round(reference_obs - non_missing))) if reference_obs > 0 else 0
        if pd.isna(coverage):
            coverage_status = "Unknown"
        elif coverage >= 0.95:
            coverage_status = "OK"
        elif coverage >= 0.80:
            coverage_status = "Partial"
        else:
            coverage_status = "Backfill required"
        rows.append({
            "Ticker": col,
            "Provider": provider_map.get(col, source),
            "Transform": transform_map.get(col, "N/A"),
            "Level obs": non_missing,
            "Return obs": int(c.notna().sum()),
            "Coverage %": coverage,
            "Coverage basis": (
                "min(observed grid, requested period depth)"
                if requested_calendar_days is not None
                else "observed grid"
            ),
            "Observed grid coverage %": observed_grid_coverage,
            "Within-history coverage %": within_history_coverage,
            "Relative history depth %": relative_history_depth,
            "Requested period depth %": requested_period_depth,
            "Requested period": str(requested_period) if requested_period is not None else "Unknown",
            "Requested period calendar days": requested_calendar_days,
            "Observed grid obs": grid_obs,
            "Reference median obs": reference_obs,
            "History depth obs": non_missing,
            "History span calendar days": history_span_days,
            "History shortfall obs": shortfall,
            "Total missing obs": total_missing,
            "Leading missing obs": leading_missing,
            "Internal missing obs": internal_missing_obs,
            "Trailing missing obs": trailing_missing,
            "Internal missing %": internal_missing,
            "Largest internal gap": largest_internal_gap,
            "Coverage status": coverage_status,
            "Début": start.strftime("%Y-%m-%d") if start is not None else "N/A",
            "Fin": end.strftime("%Y-%m-%d") if end is not None else "N/A",
        })
    return pd.DataFrame(rows)


def _merge_primary_authoritative(
    levels: pd.DataFrame,
    primary_s: pd.Series,
    primary: str,
) -> tuple[pd.DataFrame, bool]:
    """
    Keep the longer provider history and overwrite overlapping dates with app data.
    Returns (merged_levels, did_backfill).
    """
    primary = normalize_ticker(primary)
    out = levels.copy() if isinstance(levels, pd.DataFrame) else pd.DataFrame()
    fallback = pd.to_numeric(out[primary], errors="coerce") if primary in out.columns else pd.Series(dtype=float)
    fallback = fallback.dropna().sort_index()
    app = pd.to_numeric(primary_s, errors="coerce").dropna().sort_index().rename(primary)

    if fallback.empty:
        merged = app
        did_backfill = False
    else:
        merged = app.combine_first(fallback).sort_index()
        did_backfill = bool(fallback.index.min() < app.index.min())

    out = out.drop(columns=[primary], errors="ignore")
    out = pd.concat([merged.rename(primary), out], axis=1).sort_index()
    return _clean_index(out), did_backfill


def load_data_bundle(
    tickers: list[str],
    primary: str,
    price_data: pd.DataFrame | None,
    period: str,
    analysis: dict[str, Any] | None = None,
) -> DataBundle:
    """
    Priority order:
      1) analysis['correlation_prices'] DataFrame (central data layer / preloaded levels)
      2) analysis['correlation_data_loader'] callable(tickers, period) -> DataFrame
      3) yfinance compatibility fallback

    V3 primary-history rule:
      - provider/central history is retained for dates before app history;
      - app primary prices overwrite overlapping dates and are authoritative there;
      - no cross-market forward-fill is ever applied.
    """
    analysis = analysis or {}
    primary = normalize_ticker(primary)
    tickers = unique_keep_order(tickers)
    source = "unknown"
    levels = pd.DataFrame()
    provider_map: dict[str, str] = {}
    data_contract: dict[str, Any] = {
        "status": "unverified",
        "authoritative": False,
        "authority": "RESEARCH_SNAPSHOT",
    }
    cache_meta: dict[str, Any] = {"status": "not_used", "hit": False}

    supplied = analysis.get("correlation_prices")
    if isinstance(supplied, pd.DataFrame) and not supplied.empty:
        levels = supplied.copy()
        if "date" in [str(c).lower() for c in levels.columns]:
            date_col = next(c for c in levels.columns if str(c).lower() == "date")
            levels[date_col] = pd.to_datetime(levels[date_col], errors="coerce")
            levels = levels.set_index(date_col)
        levels.columns = [normalize_ticker(c) for c in levels.columns]
        levels = _clean_index(levels)
        source = str(analysis.get("correlation_data_source", "Quant Terminal Data Layer"))
        provider_map = {c: source for c in levels.columns}
        data_contract = validate_point_in_time_contract(
            levels,
            analysis.get("correlation_point_in_time_contract")
            if isinstance(analysis.get("correlation_point_in_time_contract"), dict)
            else None,
        )
        data_contract["authority"] = "POINT_IN_TIME_DECLARED" if data_contract.get("authoritative") else "RESEARCH_SNAPSHOT"
    else:
        loader = analysis.get("correlation_data_loader")
        if callable(loader):
            try:
                loaded = loader(tickers=tickers, period=period)
                if isinstance(loaded, pd.DataFrame) and not loaded.empty:
                    levels = loaded.copy()
                    if "date" in [str(c).lower() for c in levels.columns]:
                        date_col = next(c for c in levels.columns if str(c).lower() == "date")
                        levels[date_col] = pd.to_datetime(levels[date_col], errors="coerce")
                        levels = levels.set_index(date_col)
                    levels.columns = [normalize_ticker(c) for c in levels.columns]
                    levels = _clean_index(levels)
                    source = str(analysis.get("correlation_data_source", "Quant Terminal Data Layer"))
                    provider_map = {c: source for c in levels.columns}
                    data_contract = validate_point_in_time_contract(
                        levels,
                        analysis.get("correlation_point_in_time_contract")
                        if isinstance(analysis.get("correlation_point_in_time_contract"), dict)
                        else None,
                    )
                    data_contract["authority"] = "POINT_IN_TIME_DECLARED" if data_contract.get("authoritative") else "RESEARCH_SNAPSHOT"
            except Exception:
                levels = pd.DataFrame()

    if levels.empty:
        cache = get_correlation_cache()
        cache_key = json.dumps(
            {
                "tickers": tickers,
                "period": str(period),
                "as_of_date": pd.Timestamp.now(tz="UTC").date().isoformat(),
                "interval": "1d",
                "schema": "free-daily-v1",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        cached_frame = cache.get_frame("market_data_daily", cache_key)
        cached_meta = cache.get_object("market_data_daily_meta", cache_key)
        if cached_frame.hit and isinstance(cached_frame.value, pd.DataFrame):
            levels = _clean_index(cached_frame.value)
            meta_value = cached_meta.value if cached_meta.hit and isinstance(cached_meta.value, dict) else {}
            provider_map = {
                normalize_ticker(k): str(v)
                for k, v in (meta_value.get("provider_map", {}) if isinstance(meta_value, dict) else {}).items()
            }
            source = str(meta_value.get("source", "Cached free research snapshot"))
            cache_meta = {
                "status": "hit",
                "hit": True,
                "backend": cached_frame.backend,
                "age_seconds": cached_frame.age_seconds,
            }
        else:
            levels = download_levels_yfinance(tickers, period)
            provider_map = {c: "yfinance compatibility fallback" for c in levels.columns}
            missing = [t for t in tickers if t not in levels.columns or int(levels[t].notna().sum()) < 20]
            if missing:
                stooq_levels, stooq_providers = download_stooq_daily(missing, period)
                if not stooq_levels.empty:
                    for column in stooq_levels.columns:
                        if column not in levels.columns or int(levels[column].notna().sum()) < 20:
                            levels[column] = stooq_levels[column]
                            provider_map[column] = stooq_providers.get(column, "Stooq public CSV fallback")
                    levels = _clean_index(levels)
            providers = set(provider_map.values())
            source = " + ".join(sorted(providers)) if providers else "free research snapshot unavailable"
            stored_frame = cache.put_frame(
                "market_data_daily",
                cache_key,
                levels,
                metadata={"authority": "FREE_RESEARCH_NOT_POINT_IN_TIME"},
            )
            cache.put_object(
                "market_data_daily_meta",
                cache_key,
                {"provider_map": provider_map, "source": source},
                metadata={"authority": "FREE_RESEARCH_NOT_POINT_IN_TIME"},
            )
            cache_meta = {
                "status": "stored" if stored_frame else "bypassed",
                "hit": False,
                "backend": cache.status().get("catalog_backend"),
                "age_seconds": 0.0,
            }
        data_contract = {
            "status": "research_only",
            "authoritative": False,
            "authority": "FREE_RESEARCH_NOT_POINT_IN_TIME",
            "revision_policy": "provider current-history snapshot; vintage reconstruction unavailable",
            "license_scope": "research compatibility fallback; verify provider terms before redistribution",
        }

    primary_s = primary_levels_from_app(price_data, primary) if isinstance(price_data, pd.DataFrame) else None
    if primary_s is not None and not primary_s.empty:
        fallback_provider = provider_map.get(primary, source)
        levels, did_backfill = _merge_primary_authoritative(levels, primary_s, primary)
        if did_backfill:
            provider_map[primary] = f"App primary + {fallback_provider} backfill"
        else:
            provider_map[primary] = "App primary"
        if "yfinance" in source.lower() or "stooq" in source.lower() or "free research" in source.lower():
            source = f"App primary + {source} peers/backfill"
        elif source not in {"unknown", "App primary"}:
            source = f"App primary + {source}"

    # Optional explicit per-series provider provenance from the central data layer.
    explicit_provider_map = analysis.get("correlation_provider_map")
    if isinstance(explicit_provider_map, dict):
        for k, v in explicit_provider_map.items():
            provider_map[normalize_ticker(k)] = str(v)

    levels = levels[[c for c in tickers if c in levels.columns]].copy() if not levels.empty else levels
    provider_map = {c: provider_map.get(c, source) for c in levels.columns}

    transform_map = analysis.get("correlation_transform_map", {})
    changes, used_map = transform_levels(levels, transform_map)

    # V3.1 session-alignment layer. No prices are filled; only transformed return/shock series
    # can be shifted when the user/central data layer explicitly supplies session-lag metadata.
    raw_lags = analysis.get("correlation_alignment_lags", {})
    alignment_lags: dict[str, int] = {}
    if isinstance(raw_lags, dict):
        for k, v in raw_lags.items():
            try:
                alignment_lags[normalize_ticker(k)] = int(v)
            except Exception:
                continue
    changes = apply_alignment_lags(changes, alignment_lags)
    market_metadata = analysis.get("correlation_market_metadata", {})
    if not isinstance(market_metadata, dict):
        market_metadata = {}
    normalized_meta = {normalize_ticker(k): v for k, v in market_metadata.items()}

    quality = build_quality(levels, changes, used_map, provider_map, source, requested_period=period)
    sync = synchronization_audit(levels, changes, normalized_meta, alignment_lags)
    return DataBundle(
        levels=levels,
        changes=changes,
        quality=quality,
        source=source,
        transform_map=used_map,
        provider_map=provider_map,
        synchronization=sync,
        alignment_lag_map=alignment_lags,
        market_metadata=normalized_meta,
        data_contract=data_contract,
        cache_meta=cache_meta,
    )
