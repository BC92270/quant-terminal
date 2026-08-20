from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Mapping, Sequence, Tuple

import numpy as np
import pandas as pd
from scipy.optimize import LinearConstraint, Bounds, brentq, minimize
from scipy.integrate import trapezoid
from scipy.special import ndtr
from scipy.ndimage import gaussian_filter1d

OPTIONS_RISK_NEUTRAL_VERSION = "OPTIONS-RISK-NEUTRAL-2.7.1B"
OPTIONS_CHAIN_PROVIDER = "yfinance"
OPTIONS_CACHE_TTL_HOURS = 2
OPTIONS_MIN_QUOTES = 10
OPTIONS_MIN_PAIRED_QUOTES = 4
OPTIONS_MIN_CACHE_MIDPOINTS = 10
OPTIONS_MIN_CACHE_MIDPOINT_RATIO = 0.05
OPTIONS_DEFAULT_PARITY_MONEYNESS_BAND = 0.20
OPTIONS_MIN_IMPLIED_CARRY = -0.03
OPTIONS_MAX_IMPLIED_CARRY = 0.20


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_ticker(ticker: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", str(ticker).strip().upper())
    return value or "UNKNOWN"


def default_options_cache_dir() -> Path:
    configured = os.environ.get("MC_OPTIONS_CACHE_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path.cwd() / ".quant_cache" / "monte_carlo" / "options"


def _cache_paths(
    ticker: str,
    expiration: str,
    cache_dir: str | os.PathLike[str] | None = None,
) -> Tuple[Path, Path]:
    root = Path(cache_dir).expanduser() if cache_dir is not None else default_options_cache_dir()
    stem = f"{_safe_ticker(ticker)}__{str(expiration)}"
    return root / f"{stem}.csv", root / f"{stem}.json"


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


def _load_cache(data_path: Path, metadata_path: Path) -> Tuple[pd.DataFrame | None, Dict[str, Any] | None]:
    if not data_path.exists() or not metadata_path.exists():
        return None, None
    try:
        frame = pd.read_csv(data_path)
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
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


def _raw_chain_cache_quality(frame: pd.DataFrame | None) -> Dict[str, Any]:
    """Assess whether a cached raw chain is suitable for midpoint-IV work.

    A cache can be temporally fresh while economically unusable (for example,
    pre-market snapshots with mostly zero bids).  The surface must not trust the
    TTL alone.  This check intentionally uses only raw quote fields so it can run
    before normalization and without a model-dependent forward.
    """
    result: Dict[str, Any] = {
        "rows": 0,
        "valid_midpoints": 0,
        "valid_midpoint_ratio": 0.0,
        "has_provider_underlying": False,
        "usable": False,
        "reasons": [],
    }
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        result["reasons"].append("empty_cache")
        return result
    df = frame.copy()
    df.columns = [_canonical_column(column) for column in df.columns]
    result["rows"] = int(len(df))
    for column in ("bid", "ask", "provider_underlying_price"):
        if column not in df.columns:
            df[column] = np.nan
        df[column] = pd.to_numeric(df[column], errors="coerce")
    valid = (df["bid"] > 0.0) & (df["ask"] > 0.0) & (df["ask"] >= df["bid"])
    count = int(valid.sum())
    ratio = float(count / max(len(df), 1))
    provider = df["provider_underlying_price"]
    has_underlying = bool((np.isfinite(provider) & (provider > 0.0)).any())
    result.update({
        "valid_midpoints": count,
        "valid_midpoint_ratio": ratio,
        "has_provider_underlying": has_underlying,
    })
    if count < OPTIONS_MIN_CACHE_MIDPOINTS:
        result["reasons"].append("too_few_two_sided_midpoints")
    if ratio < OPTIONS_MIN_CACHE_MIDPOINT_RATIO:
        result["reasons"].append("midpoint_ratio_too_low")
    # Missing synchronized-underlying metadata is recorded for audit but does
    # not by itself invalidate an otherwise liquid cache.  Low midpoint quality
    # is the hard refresh trigger; the surface still reports lab-spot fallback.
    result["usable"] = not result["reasons"]
    return result


def _yfinance_expirations(ticker: str) -> Sequence[str]:
    try:
        import yfinance as yf
    except Exception as exc:  # pragma: no cover - environment dependent
        raise RuntimeError("yfinance is not installed") from exc
    values = list(yf.Ticker(str(ticker)).options or [])
    return [str(value) for value in values]


def _yfinance_chain(ticker: str, expiration: str) -> pd.DataFrame:
    try:
        import yfinance as yf
    except Exception as exc:  # pragma: no cover - environment dependent
        raise RuntimeError("yfinance is not installed") from exc
    chain = yf.Ticker(str(ticker)).option_chain(str(expiration))
    calls = chain.calls.copy()
    puts = chain.puts.copy()
    calls["option_type"] = "call"
    puts["option_type"] = "put"
    calls["expiration"] = str(expiration)
    puts["expiration"] = str(expiration)

    # yfinance exposes underlying metadata with the option-chain response.
    # Preserve a synchronized underlying mark on every row so intraday option
    # quotes are not inverted against a stale daily close from the parent lab.
    underlying = getattr(chain, "underlying", {}) or {}
    price = float("nan")
    price_source = "unavailable"
    for key in (
        "regularMarketPrice",
        "postMarketPrice",
        "preMarketPrice",
        "regularMarketPreviousClose",
        "previousClose",
    ):
        try:
            value = float(underlying.get(key))
        except Exception:
            value = float("nan")
        if np.isfinite(value) and value > 0.0:
            price = value
            price_source = key
            break
    quote_time = underlying.get("regularMarketTime") or underlying.get("postMarketTime") or underlying.get("preMarketTime")
    for frame in (calls, puts):
        frame["provider_underlying_price"] = price
        frame["provider_underlying_source"] = price_source
        frame["provider_underlying_time"] = quote_time
    return pd.concat([calls, puts], ignore_index=True, sort=False)


def list_option_expirations(
    ticker: str,
    provider_fetcher: Callable[[str], Sequence[str]] | None = None,
) -> Tuple[list[str], Dict[str, Any]]:
    fetcher = provider_fetcher or _yfinance_expirations
    report: Dict[str, Any] = {
        "provider": OPTIONS_CHAIN_PROVIDER,
        "ticker": str(ticker),
        "ok": False,
        "status": "FAILED",
        "expirations": [],
        "warnings": [],
    }
    try:
        expirations = sorted({str(value) for value in fetcher(str(ticker)) if str(value)})
    except Exception as exc:
        report["warnings"].append(f"Expiration lookup failed: {exc}")
        return [], report
    report.update({"ok": bool(expirations), "status": "LIVE_FETCH", "expirations": expirations})
    if not expirations:
        report["warnings"].append("Provider returned no option expirations.")
    return expirations, report


def fetch_option_chain(
    ticker: str,
    expiration: str,
    cache_ttl_hours: int = OPTIONS_CACHE_TTL_HOURS,
    force_refresh: bool = False,
    cache_dir: str | os.PathLike[str] | None = None,
    provider_fetcher: Callable[[str, str], pd.DataFrame] | None = None,
    now: datetime | None = None,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    now = now or _utc_now()
    data_path, metadata_path = _cache_paths(ticker, expiration, cache_dir)
    cached, cached_meta = _load_cache(data_path, metadata_path)
    age = _cache_age_hours(cached_meta or {}, now)
    report: Dict[str, Any] = {
        "provider": OPTIONS_CHAIN_PROVIDER,
        "ticker": str(ticker),
        "expiration": str(expiration),
        "ok": False,
        "status": "FAILED",
        "cache_age_hours": age,
        "selected_rows": 0,
        "warnings": [],
    }
    cache_quality = _raw_chain_cache_quality(cached)
    report.update({
        "cache_valid_midpoints": int(cache_quality.get("valid_midpoints", 0)),
        "cache_valid_midpoint_ratio": float(cache_quality.get("valid_midpoint_ratio", 0.0)),
        "cache_has_provider_underlying": bool(cache_quality.get("has_provider_underlying", False)),
        "cache_quality_reasons": list(cache_quality.get("reasons", [])),
    })
    fresh_cache = cached is not None and cached_meta is not None and age is not None and age <= float(cache_ttl_hours)
    rejected_fresh_cache = bool(fresh_cache and not force_refresh and not cache_quality.get("usable", False))
    if fresh_cache and not force_refresh and cache_quality.get("usable", False):
        report.update({"ok": True, "status": "CACHE_HIT", "selected_rows": int(len(cached))})
        return cached, report
    if rejected_fresh_cache:
        reasons = ", ".join(cache_quality.get("reasons", [])) or "unknown quality failure"
        report["warnings"].append(
            f"Fresh option cache was rejected by the quote-quality gate ({reasons}); a live refresh was attempted."
        )

    fetcher = provider_fetcher or _yfinance_chain
    try:
        frame = fetcher(str(ticker), str(expiration))
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            raise RuntimeError("provider returned an empty option chain")
        live_quality = _raw_chain_cache_quality(frame)
        metadata = {
            "provider": OPTIONS_CHAIN_PROVIDER,
            "ticker": str(ticker),
            "expiration": str(expiration),
            "fetched_at_utc": now.isoformat(),
            "rows": int(len(frame)),
            "valid_midpoints": int(live_quality.get("valid_midpoints", 0)),
            "valid_midpoint_ratio": float(live_quality.get("valid_midpoint_ratio", 0.0)),
            "has_provider_underlying": bool(live_quality.get("has_provider_underlying", False)),
        }
        _write_cache(data_path, metadata_path, frame, metadata)
        status = "LIVE_REFRESH_LOW_QUALITY_CACHE" if rejected_fresh_cache else "LIVE_FETCH"
        report.update({
            "ok": True,
            "status": status,
            "selected_rows": int(len(frame)),
            "cache_age_hours": 0.0,
            "live_valid_midpoints": int(live_quality.get("valid_midpoints", 0)),
            "live_valid_midpoint_ratio": float(live_quality.get("valid_midpoint_ratio", 0.0)),
            "live_has_provider_underlying": bool(live_quality.get("has_provider_underlying", False)),
        })
        if not live_quality.get("usable", False):
            report["warnings"].append(
                "The live option chain also failed the raw quote-quality gate; downstream smile governance may block the expiry."
            )
        return frame, report
    except Exception as exc:
        report["warnings"].append(f"Option-chain fetch failed: {exc}")
        if cached is not None and cached_meta is not None:
            fallback_status = "LOW_QUALITY_CACHE_FALLBACK" if rejected_fresh_cache else "STALE_CACHE_FALLBACK"
            report.update({"ok": True, "status": fallback_status, "selected_rows": int(len(cached))})
            return cached, report
        return pd.DataFrame(), report


def parse_option_chain_csv(source: Any) -> Tuple[pd.DataFrame | None, str | None]:
    try:
        frame = pd.read_csv(source)
    except Exception as exc:
        return None, f"Unable to parse option-chain CSV: {exc}"
    if frame.empty:
        return None, "Option-chain CSV is empty."
    return frame, None


def _canonical_column(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")


def normalize_option_chain(
    frame: pd.DataFrame,
    expiration: str | pd.Timestamp | None = None,
    valuation_date: str | pd.Timestamp | None = None,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    report: Dict[str, Any] = {
        "input_rows": int(len(frame)) if isinstance(frame, pd.DataFrame) else 0,
        "output_rows": 0,
        "dropped_rows": 0,
        "call_rows": 0,
        "put_rows": 0,
        "warnings": [],
    }
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        report["warnings"].append("Option chain is empty.")
        return pd.DataFrame(), report

    df = frame.copy()
    df.columns = [_canonical_column(column) for column in df.columns]
    aliases = {
        "type": "option_type",
        "right": "option_type",
        "cp": "option_type",
        "optiontype": "option_type",
        "last": "last_price",
        "lastprice": "last_price",
        "last_trade_price": "last_price",
        "openinterest": "open_interest",
        "oi": "open_interest",
        "impliedvolatility": "implied_volatility",
        "iv": "implied_volatility",
        "expiry": "expiration",
        "expiration_date": "expiration",
        "quote_date": "valuation_date",
        "lasttradedate": "last_trade_date",
        "last_trade_datetime": "last_trade_date",
    }
    df = df.rename(columns={column: aliases[column] for column in df.columns if column in aliases})
    if "option_type" not in df.columns:
        symbol_col = next((column for column in ("contract_symbol", "contractsymbol", "symbol") if column in df.columns), None)
        if symbol_col is not None:
            text = df[symbol_col].astype(str).str.upper()
            df["option_type"] = np.where(text.str.contains(r"C\d{8}", regex=True), "call", np.where(text.str.contains(r"P\d{8}", regex=True), "put", ""))
    if "option_type" not in df.columns or "strike" not in df.columns:
        report["warnings"].append("Option chain requires strike and option_type columns.")
        return pd.DataFrame(), report

    option_type = df["option_type"].astype(str).str.strip().str.lower()
    option_type = option_type.replace({"c": "call", "calls": "call", "p": "put", "puts": "put"})
    df["option_type"] = option_type

    for column in ("strike", "bid", "ask", "last_price", "open_interest", "volume", "implied_volatility", "provider_underlying_price"):
        if column not in df.columns:
            df[column] = np.nan
        df[column] = pd.to_numeric(df[column], errors="coerce")

    if "expiration" not in df.columns:
        df["expiration"] = expiration
    elif expiration is not None:
        df["expiration"] = df["expiration"].fillna(expiration)
    df["expiration"] = pd.to_datetime(df["expiration"], errors="coerce").dt.normalize()

    if "valuation_date" not in df.columns:
        df["valuation_date"] = valuation_date if valuation_date is not None else pd.Timestamp.utcnow().tz_localize(None).normalize()
    df["valuation_date"] = pd.to_datetime(df["valuation_date"], errors="coerce").dt.normalize()

    valid_quote = (df["ask"] >= df["bid"]) & (df["ask"] > 0.0) & (df["bid"] > 0.0)
    midpoint = (df["bid"] + df["ask"]) / 2.0
    fallback = df["last_price"].where(df["last_price"] > 0.0)
    df["mid"] = midpoint.where(valid_quote, fallback)
    df["mark_source"] = np.where(valid_quote, "bid_ask_mid", np.where(fallback.notna(), "last_trade_fallback", "missing"))
    df["spread"] = (df["ask"] - df["bid"]).where(valid_quote)
    df["relative_spread"] = df["spread"] / df["mid"].replace(0.0, np.nan)
    df["open_interest"] = df["open_interest"].fillna(0.0).clip(lower=0.0)
    df["volume"] = df["volume"].fillna(0.0).clip(lower=0.0)
    df["quote_weight"] = (
        np.sqrt(1.0 + df["open_interest"] + df["volume"])
        / (1.0 + df["relative_spread"].fillna(2.0).clip(lower=0.0))
    )
    df.loc[df["mark_source"] == "last_trade_fallback", "quote_weight"] *= 0.10
    if "last_trade_date" in df.columns:
        df["last_trade_date"] = pd.to_datetime(df["last_trade_date"], errors="coerce", utc=True).dt.tz_convert(None)

    before = len(df)
    df = df[
        df["option_type"].isin(["call", "put"])
        & np.isfinite(df["strike"])
        & (df["strike"] > 0.0)
        & np.isfinite(df["mid"])
        & (df["mid"] > 0.0)
        & df["expiration"].notna()
        & df["valuation_date"].notna()
    ].copy()
    df = df.sort_values(["expiration", "strike", "option_type"]).drop_duplicates(["expiration", "strike", "option_type"], keep="last")
    report["dropped_rows"] = int(before - len(df))
    report["output_rows"] = int(len(df))
    report["call_rows"] = int((df["option_type"] == "call").sum())
    report["put_rows"] = int((df["option_type"] == "put").sum())
    if report["output_rows"] < OPTIONS_MIN_QUOTES:
        report["warnings"].append("Fewer than ten usable option quotes remain after normalization.")
    return df.reset_index(drop=True), report


def _resolve_pricing_spot(
    chain: pd.DataFrame,
    lab_spot: float,
    time_to_expiry: float,
    risk_free_rate: float,
    dividend_yield: float,
) -> dict[str, Any]:
    """Choose the spot synchronized to the option-chain response when available.

    The parent Monte Carlo lab can be based on a daily close while option quotes
    update intraday.  Midpoint-IV inversion must therefore prefer the underlying
    mark returned with the same option-chain response.  Cached legacy chains that
    do not carry this metadata remain on the parent-lab spot and are eligible for
    the one-shot refresh path in the surface UI.
    """
    provider = pd.to_numeric(chain.get("provider_underlying_price", pd.Series(dtype=float)), errors="coerce")
    provider = provider[np.isfinite(provider) & (provider > 0.0)]
    if not provider.empty:
        pricing_spot = float(provider.median())
        source = "provider_option_chain_underlying"
    else:
        pricing_spot = float(lab_spot)
        source = "lab_current_price"
    gap = pricing_spot / lab_spot - 1.0 if np.isfinite(lab_spot) and lab_spot > 0.0 else float("nan")
    return {
        "pricing_spot": pricing_spot,
        "lab_spot": float(lab_spot),
        "source": source,
        "spot_gap": float(gap),
        "provider_observations": int(len(provider)),
        "legacy_cache_without_underlying": bool(provider.empty),
    }


def _weighted_median(values: np.ndarray, weights: np.ndarray) -> float:
    order = np.argsort(values)
    x = np.asarray(values, dtype=float)[order]
    w = np.asarray(weights, dtype=float)[order]
    if not np.isfinite(w).all() or float(w.sum()) <= 0.0:
        return float(np.median(x))
    cutoff = 0.5 * float(w.sum())
    return float(x[np.searchsorted(np.cumsum(w), cutoff, side="left")])


def estimate_forward_from_parity(
    chain: pd.DataFrame,
    spot: float,
    time_to_expiry: float,
    risk_free_rate: float,
    dividend_yield: float = 0.0,
    contract_style: str = "European",
    parity_moneyness_band: float = OPTIONS_DEFAULT_PARITY_MONEYNESS_BAND,
    min_implied_carry: float = OPTIONS_MIN_IMPLIED_CARRY,
    max_implied_carry: float = OPTIONS_MAX_IMPLIED_CARRY,
) -> Tuple[float, float, pd.DataFrame, Dict[str, Any]]:
    """Estimate a forward from matched call-put quotes under an explicit governance gate.

    Exact European put-call parity is not imposed blindly on American equity/ETF
    options.  Near-ATM pairs are used, robust outliers are removed, and implausible
    carry estimates fall back to the user-supplied carry assumption.
    """
    calls = chain[chain["option_type"] == "call"][["strike", "mid", "quote_weight", "mark_source"]].rename(
        columns={"mid": "call_mid", "quote_weight": "call_weight", "mark_source": "call_mark_source"}
    )
    puts = chain[chain["option_type"] == "put"][["strike", "mid", "quote_weight", "mark_source"]].rename(
        columns={"mid": "put_mid", "quote_weight": "put_weight", "mark_source": "put_mark_source"}
    )
    pairs = calls.merge(puts, on="strike", how="inner")
    fallback_forward = float(spot * math.exp((risk_free_rate - dividend_yield) * time_to_expiry))
    report: Dict[str, Any] = {
        "paired_quotes_raw": int(len(pairs)),
        "paired_quotes": 0,
        "method": "manual_dividend_yield",
        "contract_style": str(contract_style),
        "parity_exact": str(contract_style).strip().lower().startswith("europe"),
        "accepted": False,
        "fallback_used": True,
        "fallback_forward": fallback_forward,
        "warnings": [],
    }
    if len(pairs) < OPTIONS_MIN_PAIRED_QUOTES:
        report["warnings"].append("Put-call parity had too few matched strikes; manual carry was used.")
        return fallback_forward, float(dividend_yield), pairs, report

    band = float(max(0.02, parity_moneyness_band))
    pairs["log_moneyness"] = np.log(pairs["strike"].astype(float) / max(float(spot), 1e-12))
    pairs = pairs[pairs["log_moneyness"].abs() <= band].copy()
    pairs = pairs[(pairs["call_mark_source"] == "bid_ask_mid") & (pairs["put_mark_source"] == "bid_ask_mid")].copy()
    if len(pairs) < OPTIONS_MIN_PAIRED_QUOTES:
        report["warnings"].append("Too few near-ATM two-sided call-put pairs remained; manual carry was used.")
        return fallback_forward, float(dividend_yield), pairs, report

    pairs["forward_implied"] = pairs["strike"] + math.exp(risk_free_rate * time_to_expiry) * (pairs["call_mid"] - pairs["put_mid"])
    pairs["pair_weight"] = np.minimum(pairs["call_weight"], pairs["put_weight"]).clip(lower=1e-6)
    valid = pairs[np.isfinite(pairs["forward_implied"]) & (pairs["forward_implied"] > 0.0)].copy()
    if len(valid) < OPTIONS_MIN_PAIRED_QUOTES:
        report["warnings"].append("Put-call parity forward estimates were invalid; manual carry was used.")
        return fallback_forward, float(dividend_yield), pairs, report

    preliminary = _weighted_median(valid["forward_implied"].to_numpy(), valid["pair_weight"].to_numpy())
    absolute_deviation = np.abs(valid["forward_implied"] - preliminary)
    mad = float(np.median(absolute_deviation))
    robust_scale = max(1.4826 * mad, 0.001 * float(spot))
    robust = valid[absolute_deviation <= 4.5 * robust_scale].copy()
    if len(robust) < OPTIONS_MIN_PAIRED_QUOTES:
        robust = valid
    forward_candidate = _weighted_median(robust["forward_implied"].to_numpy(), robust["pair_weight"].to_numpy())
    implied_q_candidate = risk_free_rate - math.log(max(forward_candidate, 1e-12) / max(float(spot), 1e-12)) / max(time_to_expiry, 1e-12)
    residual = robust["forward_implied"] - forward_candidate
    dispersion = float(np.sqrt(np.average(residual**2, weights=robust["pair_weight"])))
    dispersion_relative = dispersion / max(float(spot), 1e-12)
    carry_plausible = float(min_implied_carry) <= implied_q_candidate <= float(max_implied_carry)
    dispersion_plausible = dispersion_relative <= 0.02
    accepted = bool(carry_plausible and dispersion_plausible)

    report.update(
        {
            "paired_quotes": int(len(robust)),
            "candidate_forward": float(forward_candidate),
            "candidate_implied_dividend_yield": float(implied_q_candidate),
            "forward_dispersion": dispersion,
            "forward_dispersion_relative": dispersion_relative,
            "carry_bounds": [float(min_implied_carry), float(max_implied_carry)],
            "moneyness_band": band,
            "accepted": accepted,
            "fallback_used": not accepted,
        }
    )
    if not report["parity_exact"]:
        report["warnings"].append(
            "American-style exercise makes European put-call parity an approximation; only near-ATM two-sided pairs were used."
        )
    if not carry_plausible:
        report["warnings"].append(
            f"Parity-implied carry {implied_q_candidate:.2%} breached the governed bounds; manual carry was used."
        )
    if not dispersion_plausible:
        report["warnings"].append(
            f"Parity forwards were dispersed by {dispersion_relative:.2%} of spot; manual carry was used."
        )
    if accepted:
        report.update({"method": "governed_put_call_parity", "implied_dividend_yield": float(implied_q_candidate)})
        return float(forward_candidate), float(implied_q_candidate), robust.reset_index(drop=True), report
    return fallback_forward, float(dividend_yield), robust.reset_index(drop=True), report


def _pava_non_decreasing(values: np.ndarray, weights: np.ndarray | None = None) -> np.ndarray:
    y = np.asarray(values, dtype=float)
    w = np.ones_like(y) if weights is None else np.asarray(weights, dtype=float)
    blocks: list[list[float]] = []
    for value, weight in zip(y, w):
        blocks.append([float(value), float(max(weight, 1e-12)), 1.0])
        while len(blocks) >= 2 and blocks[-2][0] > blocks[-1][0]:
            a = blocks.pop()
            b = blocks.pop()
            total_w = a[1] + b[1]
            blocks.append([(a[0] * a[1] + b[0] * b[1]) / total_w, total_w, a[2] + b[2]])
    output: list[float] = []
    for value, _, count in blocks:
        output.extend([value] * int(count))
    return np.asarray(output, dtype=float)


def _convex_monotone_initial(strikes: np.ndarray, observed: np.ndarray, lower: np.ndarray, upper: np.ndarray, disc_r: float) -> np.ndarray:
    h = np.diff(strikes)
    slopes = np.diff(observed) / h
    slopes = np.clip(slopes, -disc_r, 0.0)
    slopes = _pava_non_decreasing(slopes, h)
    increments = np.concatenate([[0.0], np.cumsum(slopes * h)])
    low_c0 = float(np.max(lower - increments))
    high_c0 = float(np.min(upper - increments))
    if low_c0 > high_c0:
        c0 = float(np.clip(observed[0], lower[0], upper[0]))
        candidate = c0 + increments
        return np.clip(candidate, lower, upper)
    c0_ls = float(np.mean(observed - increments))
    c0 = float(np.clip(c0_ls, low_c0, high_c0))
    return np.clip(c0 + increments, lower, upper)


def project_arbitrage_free_call_curve(
    strikes: np.ndarray,
    observed_calls: np.ndarray,
    weights: np.ndarray,
    spot: float,
    time_to_expiry: float,
    risk_free_rate: float,
    dividend_yield: float,
    smoothing_penalty: float = 1e-4,
) -> Tuple[np.ndarray, Dict[str, Any]]:
    strikes = np.asarray(strikes, dtype=float)
    observed = np.asarray(observed_calls, dtype=float)
    weights = np.asarray(weights, dtype=float)
    order = np.argsort(strikes)
    strikes, observed, weights = strikes[order], observed[order], weights[order]
    disc_r = math.exp(-risk_free_rate * time_to_expiry)
    disc_q = math.exp(-dividend_yield * time_to_expiry)
    lower = np.maximum(spot * disc_q - strikes * disc_r, 0.0)
    upper = np.full_like(strikes, spot * disc_q)
    observed = np.clip(observed, lower, upper)
    weights = np.where(np.isfinite(weights) & (weights > 0.0), weights, 1.0)
    weights = weights / max(float(np.median(weights)), 1e-12)

    n = len(strikes)
    if n < 3:
        return observed, {"success": False, "status": "BLOCKED", "reason": "At least three strikes are required."}

    rows: list[np.ndarray] = []
    lbs: list[float] = []
    ubs: list[float] = []
    h = np.diff(strikes)
    for index in range(n - 1):
        row = np.zeros(n)
        row[index] = 1.0
        row[index + 1] = -1.0
        rows.append(row)
        lbs.append(0.0)
        ubs.append(float(disc_r * h[index]))
    for index in range(n - 2):
        row = np.zeros(n)
        row[index] = 1.0 / h[index]
        row[index + 1] = -(1.0 / h[index] + 1.0 / h[index + 1])
        row[index + 2] = 1.0 / h[index + 1]
        rows.append(row)
        lbs.append(0.0)
        ubs.append(np.inf)
    constraint = LinearConstraint(np.vstack(rows), np.asarray(lbs), np.asarray(ubs))
    bounds = Bounds(lower, upper)
    initial = _convex_monotone_initial(strikes, observed, lower, upper, disc_r)

    def objective(values: np.ndarray) -> float:
        residual = values - observed
        slopes = np.diff(values) / h
        curvature = np.diff(slopes)
        return float(np.sum(weights * residual * residual) + float(smoothing_penalty) * np.sum(curvature * curvature))

    result = minimize(
        objective,
        initial,
        method="SLSQP",
        bounds=bounds,
        constraints=[constraint],
        options={"maxiter": 2_000, "ftol": 1e-12, "disp": False},
    )
    projected = np.asarray(result.x if result.success else initial, dtype=float)
    residual = projected - observed
    slopes = np.diff(projected) / h
    convexity = np.diff(slopes)
    diagnostics = {
        "success": bool(result.success),
        "status": "PASS" if result.success else "WARNING_FALLBACK",
        "message": str(result.message),
        "iterations": int(getattr(result, "nit", 0)),
        "weighted_rmse": float(np.sqrt(np.average(residual**2, weights=weights))),
        "max_monotonicity_violation": float(max(0.0, np.max(np.diff(projected)))) if len(projected) > 1 else 0.0,
        "max_convexity_violation": float(max(0.0, -np.min(convexity))) if len(convexity) else 0.0,
        "fallback_used": not bool(result.success),
    }
    return projected, diagnostics


def _normal_pdf(value: float) -> float:
    return math.exp(-0.5 * value * value) / math.sqrt(2.0 * math.pi)


def black_scholes_price(
    spot: float,
    strike: float,
    time_to_expiry: float,
    risk_free_rate: float,
    dividend_yield: float,
    volatility: float,
    option_type: str,
) -> float:
    if time_to_expiry <= 0.0 or volatility <= 0.0:
        intrinsic = max(spot - strike, 0.0) if str(option_type).lower() == "call" else max(strike - spot, 0.0)
        return float(intrinsic)
    vol_sqrt = volatility * math.sqrt(time_to_expiry)
    d1 = (math.log(spot / strike) + (risk_free_rate - dividend_yield + 0.5 * volatility**2) * time_to_expiry) / vol_sqrt
    d2 = d1 - vol_sqrt
    if str(option_type).lower() == "call":
        return float(spot * math.exp(-dividend_yield * time_to_expiry) * ndtr(d1) - strike * math.exp(-risk_free_rate * time_to_expiry) * ndtr(d2))
    return float(strike * math.exp(-risk_free_rate * time_to_expiry) * ndtr(-d2) - spot * math.exp(-dividend_yield * time_to_expiry) * ndtr(-d1))


def implied_volatility(
    price: float,
    spot: float,
    strike: float,
    time_to_expiry: float,
    risk_free_rate: float,
    dividend_yield: float,
    option_type: str,
) -> float:
    if not np.isfinite(price) or price <= 0.0 or time_to_expiry <= 0.0:
        return float("nan")
    lower = black_scholes_price(spot, strike, time_to_expiry, risk_free_rate, dividend_yield, 1e-6, option_type)
    upper = black_scholes_price(spot, strike, time_to_expiry, risk_free_rate, dividend_yield, 5.0, option_type)
    if price < lower - 1e-8 or price > upper + 1e-8:
        return float("nan")
    try:
        return float(
            brentq(
                lambda sigma: black_scholes_price(spot, strike, time_to_expiry, risk_free_rate, dividend_yield, sigma, option_type) - price,
                1e-6,
                5.0,
                maxiter=200,
            )
        )
    except Exception:
        return float("nan")


def _discrete_density_from_calls(strikes: np.ndarray, calls: np.ndarray, risk_free_rate: float, time_to_expiry: float) -> pd.DataFrame:
    strikes = np.asarray(strikes, dtype=float)
    calls = np.asarray(calls, dtype=float)
    left = strikes[:-2]
    center = strikes[1:-1]
    right = strikes[2:]
    slope_left = (calls[1:-1] - calls[:-2]) / (center - left)
    slope_right = (calls[2:] - calls[1:-1]) / (right - center)
    second = 2.0 * (slope_right - slope_left) / (right - left)
    raw_density = math.exp(risk_free_rate * time_to_expiry) * second
    clipped = np.clip(raw_density, 0.0, None)
    raw_mass = float(trapezoid(clipped, center)) if len(center) > 1 else 0.0
    density = clipped / raw_mass if raw_mass > 0.0 else clipped
    if len(center) > 1:
        increments = 0.5 * (density[1:] + density[:-1]) * np.diff(center)
        cdf = np.concatenate([[0.0], np.cumsum(increments)])
        if cdf[-1] > 0.0:
            cdf = cdf / cdf[-1]
    else:
        cdf = np.zeros_like(center)
    return pd.DataFrame(
        {
            "strike": center,
            "raw_density": raw_density,
            "density": density,
            "cdf": np.clip(cdf, 0.0, 1.0),
        }
    ), raw_mass


def _smooth_density_for_display(density_table: pd.DataFrame, points: int = 240) -> pd.DataFrame:
    """Create a smooth display-only density without changing risk metrics."""
    table = density_table.sort_values("strike").drop_duplicates("strike")
    if len(table) < 4:
        return table[["strike", "density"]].copy()
    strike = table["strike"].to_numpy(dtype=float)
    density = np.clip(table["density"].to_numpy(dtype=float), 0.0, None)
    grid = np.linspace(float(strike.min()), float(strike.max()), int(max(points, 60)))
    interpolated = np.interp(grid, strike, density, left=0.0, right=0.0)
    smoothed = gaussian_filter1d(interpolated, sigma=2.0, mode="nearest")
    smoothed = np.clip(smoothed, 0.0, None)
    mass = float(trapezoid(smoothed, grid))
    if mass > 0.0:
        smoothed /= mass
    return pd.DataFrame({"strike": grid, "density": smoothed})


def _quantile_from_density(density_table: pd.DataFrame, probability: float) -> float:
    table = density_table.sort_values("strike")
    cdf = table["cdf"].to_numpy(dtype=float)
    strike = table["strike"].to_numpy(dtype=float)
    if len(strike) == 0:
        return float("nan")
    return float(np.interp(float(probability), cdf, strike, left=strike[0], right=strike[-1]))


def _density_moments(density_table: pd.DataFrame) -> Dict[str, float]:
    strike = density_table["strike"].to_numpy(dtype=float)
    density = density_table["density"].to_numpy(dtype=float)
    if len(strike) < 2 or float(trapezoid(density, strike)) <= 0.0:
        return {key: float("nan") for key in ("mean", "variance", "skewness", "excess_kurtosis")}
    mass = float(trapezoid(density, strike))
    mean = float(trapezoid(strike * density, strike) / mass)
    centered = strike - mean
    variance = float(trapezoid(centered**2 * density, strike) / mass)
    if variance <= 0.0:
        return {"mean": mean, "variance": variance, "skewness": float("nan"), "excess_kurtosis": float("nan")}
    skewness = float(trapezoid(centered**3 * density, strike) / mass / variance**1.5)
    kurtosis = float(trapezoid(centered**4 * density, strike) / mass / variance**2 - 3.0)
    return {"mean": mean, "variance": variance, "skewness": skewness, "excess_kurtosis": kurtosis}


def _density_expected_shortfall(density_table: pd.DataFrame, threshold: float) -> float:
    table = density_table.sort_values("strike")
    strike = table["strike"].to_numpy(dtype=float)
    density = table["density"].to_numpy(dtype=float)
    mask = strike <= threshold
    if int(mask.sum()) < 2:
        return float("nan")
    mass = float(trapezoid(density[mask], strike[mask]))
    if mass <= 0.0:
        return float("nan")
    return float(trapezoid(strike[mask] * density[mask], strike[mask]) / mass)


def _model_free_variance(
    otm_table: pd.DataFrame,
    forward: float,
    time_to_expiry: float,
    risk_free_rate: float,
) -> Tuple[float, Dict[str, Any]]:
    table = otm_table.sort_values("strike").drop_duplicates("strike").copy()
    report: Dict[str, Any] = {"ok": False, "quote_count": int(len(table)), "warnings": []}
    if len(table) < 5 or time_to_expiry <= 0.0:
        report["warnings"].append("Insufficient OTM strikes for model-free variance.")
        return float("nan"), report
    strikes = table["strike"].to_numpy(dtype=float)
    prices = table["otm_mid"].to_numpy(dtype=float)
    k0_candidates = strikes[strikes <= forward]
    if len(k0_candidates) == 0:
        report["warnings"].append("No strike below the forward for K0 selection.")
        return float("nan"), report
    k0 = float(k0_candidates[-1])
    delta_k = np.empty_like(strikes)
    delta_k[1:-1] = 0.5 * (strikes[2:] - strikes[:-2])
    delta_k[0] = strikes[1] - strikes[0]
    delta_k[-1] = strikes[-1] - strikes[-2]
    variance = (
        2.0 / time_to_expiry * np.sum(delta_k / (strikes**2) * math.exp(risk_free_rate * time_to_expiry) * prices)
        - 1.0 / time_to_expiry * (forward / k0 - 1.0) ** 2
    )
    if not np.isfinite(variance) or variance <= 0.0:
        report["warnings"].append("Model-free variance was non-positive.")
        return float("nan"), report
    report.update({"ok": True, "k0": k0, "annualized_variance": float(variance), "annualized_volatility": float(math.sqrt(variance))})
    return float(variance), report


def _build_synthetic_call_curve(
    chain: pd.DataFrame,
    spot: float,
    time_to_expiry: float,
    risk_free_rate: float,
    dividend_yield: float,
    forward: float,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Build a call-equivalent curve from the OTM side of the chain.

    OTM puts are converted to call-equivalent prices below the forward and OTM
    calls are used above the forward.  This avoids unstable deep-ITM marks and
    reduces, but does not eliminate, American early-exercise contamination.
    """
    disc_r = math.exp(-risk_free_rate * time_to_expiry)
    disc_q = math.exp(-dividend_yield * time_to_expiry)
    records: list[dict[str, Any]] = []
    otm_records: list[dict[str, Any]] = []
    unique_strikes = np.sort(chain["strike"].astype(float).unique())
    below_forward = unique_strikes[unique_strikes <= float(forward)]
    k0 = float(below_forward[-1]) if len(below_forward) else float(unique_strikes[0])
    for strike, group in chain.groupby("strike", sort=True):
        strike = float(strike)
        call = group[group["option_type"] == "call"]
        put = group[group["option_type"] == "put"]
        observations: list[Tuple[float, float, str]] = []
        near_forward = abs(math.log(max(strike, 1e-12) / max(float(forward), 1e-12))) <= 0.025
        if strike < float(forward) and not put.empty:
            row = put.iloc[-1]
            converted = float(row["mid"] + spot * disc_q - strike * disc_r)
            observations.append((converted, float(row["quote_weight"]), "otm_put_parity"))
        elif strike > float(forward) and not call.empty:
            row = call.iloc[-1]
            observations.append((float(row["mid"]), float(row["quote_weight"]), "otm_call"))
        elif near_forward:
            if not call.empty:
                row = call.iloc[-1]
                observations.append((float(row["mid"]), float(row["quote_weight"]), "near_atm_call"))
            if not put.empty:
                row = put.iloc[-1]
                converted = float(row["mid"] + spot * disc_q - strike * disc_r)
                observations.append((converted, float(row["quote_weight"]), "near_atm_put_parity"))
        # Explicit fallback only when the preferred OTM side is absent.
        if not observations and not call.empty:
            row = call.iloc[-1]
            observations.append((float(row["mid"]), 0.25 * float(row["quote_weight"]), "fallback_call"))
        if not observations and not put.empty:
            row = put.iloc[-1]
            converted = float(row["mid"] + spot * disc_q - strike * disc_r)
            observations.append((converted, 0.25 * float(row["quote_weight"]), "fallback_put_parity"))
        if not observations:
            continue
        values = np.asarray([item[0] for item in observations], dtype=float)
        weights = np.asarray([max(item[1], 1e-9) for item in observations], dtype=float)
        synthetic_call = float(np.average(values, weights=weights))
        records.append(
            {
                "strike": strike,
                "observed_call_equivalent": synthetic_call,
                "quote_weight": float(weights.sum()),
                "sources": "+".join(item[2] for item in observations),
            }
        )
        if strike < k0 and not put.empty:
            row = put.iloc[-1]
            otm_records.append({"strike": strike, "otm_mid": float(row["mid"]), "option_type": "put"})
        elif strike > k0 and not call.empty:
            row = call.iloc[-1]
            otm_records.append({"strike": strike, "otm_mid": float(row["mid"]), "option_type": "call"})
        elif strike == k0:
            mids = group["mid"].to_numpy(dtype=float)
            if len(mids):
                otm_records.append({"strike": strike, "otm_mid": float(np.mean(mids)), "option_type": "atm"})
    return pd.DataFrame(records), pd.DataFrame(otm_records)


def _risk_neutral_metrics(density_table: pd.DataFrame, spot: float, forward: float) -> Dict[str, float]:
    moments = _density_moments(density_table)
    p05 = _quantile_from_density(density_table, 0.05)
    p01 = _quantile_from_density(density_table, 0.01)
    p50 = _quantile_from_density(density_table, 0.50)
    p95 = _quantile_from_density(density_table, 0.95)
    es05_price = _density_expected_shortfall(density_table, p05)
    es01_price = _density_expected_shortfall(density_table, p01)
    strike = density_table["strike"].to_numpy(dtype=float)
    cdf = density_table["cdf"].to_numpy(dtype=float)
    probability_below_spot = float(np.interp(spot, strike, cdf, left=0.0, right=1.0)) if len(strike) else float("nan")
    mode = float(density_table.loc[density_table["density"].idxmax(), "strike"]) if not density_table.empty else float("nan")
    return {
        "mean_terminal_price": moments["mean"],
        "mean_consistency_error": moments["mean"] - forward,
        "median_terminal_price": p50,
        "mode_terminal_price": mode,
        "q_var_5": p05 / spot - 1.0,
        "q_es_5": es05_price / spot - 1.0,
        "q_var_1": p01 / spot - 1.0,
        "q_es_1": es01_price / spot - 1.0,
        "q_p95": p95 / spot - 1.0,
        "probability_below_spot": probability_below_spot,
        "risk_neutral_skewness": moments["skewness"],
        "risk_neutral_excess_kurtosis": moments["excess_kurtosis"],
    }


def _physical_comparison(lab: Mapping[str, Any], days_to_expiry: int, spot: float) -> Dict[str, Any]:
    available = sorted(int(value) for value in lab.get("paths_by_horizon", {}).keys())
    if not available:
        return {"available": False}
    horizon = min(available, key=lambda value: abs(value - int(days_to_expiry)))
    paths = np.asarray(lab["paths_by_horizon"][horizon], dtype=float)
    returns = paths[:, -1] / float(spot) - 1.0
    return {
        "available": True,
        "horizon": int(horizon),
        "returns": returns,
        "expected_return": float(np.mean(returns)),
        "median_return": float(np.median(returns)),
        "var_5": float(np.quantile(returns, 0.05)),
        "es_5": float(np.mean(returns[returns <= np.quantile(returns, 0.05)])),
        "probability_below_spot": float(np.mean(returns < 0.0)),
        "measure": "Physical P / selected simulation engine",
    }


def _configuration_signature(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(dict(payload), sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16].upper()


@dataclass(frozen=True)
class OptionsRiskNeutralSettings:
    expiration: str
    risk_free_rate: float = 0.04
    dividend_yield: float = 0.0
    forward_method: str = "Governed put-call parity"
    contract_style: str = "European"
    parity_moneyness_band: float = OPTIONS_DEFAULT_PARITY_MONEYNESS_BAND
    max_relative_spread: float = 0.50
    minimum_open_interest: int = 0
    minimum_volume: int = 0
    smoothing_penalty: float = 1e-4


def build_options_risk_neutral_lab(
    lab: Mapping[str, Any],
    option_chain: pd.DataFrame,
    expiration: str | pd.Timestamp,
    risk_free_rate: float = 0.04,
    dividend_yield: float = 0.0,
    forward_method: str = "Governed put-call parity",
    contract_style: str = "European",
    parity_moneyness_band: float = OPTIONS_DEFAULT_PARITY_MONEYNESS_BAND,
    max_relative_spread: float = 0.50,
    minimum_open_interest: int = 0,
    minimum_volume: int = 0,
    smoothing_penalty: float = 1e-4,
    source_report: Mapping[str, Any] | None = None,
    valuation_date: str | pd.Timestamp | None = None,
) -> Dict[str, Any]:
    lab_spot = float(lab.get("base", {}).get("current_price", float("nan")))
    if not np.isfinite(lab_spot) or lab_spot <= 0.0:
        return {"ok": False, "status": "BLOCKED", "reason": "A positive current spot price is required."}
    normalized, normalization_report = normalize_option_chain(option_chain, expiration=expiration, valuation_date=valuation_date)
    if normalized.empty:
        return {"ok": False, "status": "BLOCKED", "reason": "; ".join(normalization_report.get("warnings", [])) or "No usable option quotes."}

    target_expiry = pd.Timestamp(expiration).normalize()
    normalized = normalized[normalized["expiration"] == target_expiry].copy()
    if normalized.empty:
        return {"ok": False, "status": "BLOCKED", "reason": f"No quotes matched expiration {target_expiry.date()}."}
    valuation = pd.Timestamp(valuation_date).normalize() if valuation_date is not None else normalized["valuation_date"].max()
    if pd.isna(valuation):
        valuation = pd.Timestamp.utcnow().tz_localize(None).normalize()
    calendar_days = int((target_expiry - valuation).days)
    time_to_expiry = max(calendar_days / 365.0, 1.0 / 365.0)

    spot_report = _resolve_pricing_spot(
        normalized,
        lab_spot=lab_spot,
        time_to_expiry=time_to_expiry,
        risk_free_rate=float(risk_free_rate),
        dividend_yield=float(dividend_yield),
    )
    spot = float(spot_report["pricing_spot"])
    if not np.isfinite(spot) or spot <= 0.0:
        return {"ok": False, "status": "BLOCKED", "reason": "Unable to resolve a synchronized positive option-pricing spot."}

    filters = (
        (normalized["open_interest"] >= int(minimum_open_interest))
        & (normalized["volume"] >= int(minimum_volume))
        & (normalized["mark_source"] == "bid_ask_mid")
        & (normalized["relative_spread"].fillna(np.inf) <= float(max_relative_spread))
    )
    clean = normalized[filters].copy()
    normalization_report["liquidity_fallback_used"] = False
    if len(clean) < OPTIONS_MIN_QUOTES:
        clean = normalized.copy()
        normalization_report["liquidity_fallback_used"] = True
        normalization_report["warnings"].append("Liquidity filters left too few midpoint quotes; the normalized chain was retained with WARNING status.")

    forward, implied_q, parity_table, forward_report = estimate_forward_from_parity(
        clean,
        spot=spot,
        time_to_expiry=time_to_expiry,
        risk_free_rate=float(risk_free_rate),
        dividend_yield=float(dividend_yield),
        contract_style=str(contract_style),
        parity_moneyness_band=float(parity_moneyness_band),
    )
    parity_requested = str(forward_method).lower().startswith(("put", "governed"))
    effective_q = float(implied_q if parity_requested and forward_report.get("accepted") else dividend_yield)
    if not parity_requested:
        forward = float(spot * math.exp((float(risk_free_rate) - effective_q) * time_to_expiry))
        forward_report["method"] = "manual_dividend_yield"
        forward_report["accepted"] = False
        forward_report["fallback_used"] = False

    synthetic, otm_table = _build_synthetic_call_curve(
        clean,
        spot=spot,
        time_to_expiry=time_to_expiry,
        risk_free_rate=float(risk_free_rate),
        dividend_yield=effective_q,
        forward=forward,
    )
    if len(synthetic) < 5:
        return {"ok": False, "status": "BLOCKED", "reason": "At least five unique strikes are required after quote normalization."}

    projected, projection_report = project_arbitrage_free_call_curve(
        synthetic["strike"].to_numpy(),
        synthetic["observed_call_equivalent"].to_numpy(),
        synthetic["quote_weight"].to_numpy(),
        spot=spot,
        time_to_expiry=time_to_expiry,
        risk_free_rate=float(risk_free_rate),
        dividend_yield=effective_q,
        smoothing_penalty=float(smoothing_penalty),
    )
    synthetic["projected_call"] = projected
    synthetic["projection_error"] = synthetic["projected_call"] - synthetic["observed_call_equivalent"]
    density_table, raw_density_mass = _discrete_density_from_calls(
        synthetic["strike"].to_numpy(),
        synthetic["projected_call"].to_numpy(),
        risk_free_rate=float(risk_free_rate),
        time_to_expiry=time_to_expiry,
    )
    if density_table.empty or float(density_table["density"].sum()) <= 0.0:
        return {"ok": False, "status": "BLOCKED", "reason": "Risk-neutral density extraction failed."}

    # Provider IVs are retained for audit but never used as the displayed smile.
    # The effective IV is recomputed from the governed bid/ask midpoint.
    clean["provider_iv"] = clean["implied_volatility"]
    clean["effective_iv"] = [
        implied_volatility(
            price=float(row.mid),
            spot=spot,
            strike=float(row.strike),
            time_to_expiry=time_to_expiry,
            risk_free_rate=float(risk_free_rate),
            dividend_yield=effective_q,
            option_type=str(row.option_type),
        )
        for row in clean.itertuples(index=False)
    ]
    log_moneyness = np.log(clean["strike"].astype(float) / max(float(forward), 1e-12))
    preferred_otm = (
        ((clean["option_type"] == "call") & (clean["strike"] >= float(forward)))
        | ((clean["option_type"] == "put") & (clean["strike"] <= float(forward)))
    )
    clean["smile_eligible"] = (
        np.isfinite(clean["effective_iv"])
        & (clean["effective_iv"] >= 0.01)
        & (clean["effective_iv"] <= 5.0)
        & (log_moneyness.abs() <= 0.35)
        & preferred_otm
        & (clean["mark_source"] == "bid_ask_mid")
    )

    model_free_variance, variance_report = _model_free_variance(
        otm_table,
        forward=forward,
        time_to_expiry=time_to_expiry,
        risk_free_rate=float(risk_free_rate),
    )
    risk_neutral_metrics = _risk_neutral_metrics(density_table, spot=spot, forward=forward)
    display_density_table = _smooth_density_for_display(density_table)
    physical = _physical_comparison(lab, days_to_expiry=calendar_days, spot=spot)

    strike_min = float(synthetic["strike"].min())
    strike_max = float(synthetic["strike"].max())
    forward_coverage = (forward - strike_min) / max(strike_max - strike_min, 1e-12)
    warnings = list(normalization_report.get("warnings", [])) + list(forward_report.get("warnings", [])) + list(variance_report.get("warnings", []))
    spot_gap = float(spot_report.get("spot_gap", float("nan")))
    if spot_report.get("source") == "provider_option_chain_underlying" and np.isfinite(spot_gap) and abs(spot_gap) > 0.0025:
        warnings.append(
            f"Option quotes were synchronized to the provider chain underlying ({spot:.4f}) rather than the parent-lab spot ({lab_spot:.4f}); gap {spot_gap:+.2%}."
        )
    status = "PASS"
    if normalization_report.get("liquidity_fallback_used"):
        status = "WARNING"
    if np.isfinite(spot_gap) and abs(spot_gap) > 0.02:
        status = "WARNING"
    if str(contract_style).strip().lower().startswith("american"):
        status = "WARNING"
        warnings.append(
            "US equity/ETF options are American-style; the terminal Q-density is an OTM European-equivalent approximation and may retain early-exercise premium."
        )
    if parity_requested and not forward_report.get("accepted"):
        status = "WARNING"
        warnings.append("Governed put-call parity was rejected; manual carry determined the effective forward.")
    reliable_smile_quotes = int(clean["smile_eligible"].sum())
    if reliable_smile_quotes < 8:
        status = "WARNING"
        warnings.append("Fewer than eight midpoint-recomputed OTM IV quotes passed the smile reliability gate.")
    mean_consistency_relative = abs(float(risk_neutral_metrics.get("mean_consistency_error", float("nan")))) / max(float(spot), 1e-12)
    if np.isfinite(mean_consistency_relative) and mean_consistency_relative > 0.01:
        status = "WARNING"
        warnings.append("The finite-strike Q-density mean differs from the effective forward by more than 1% of spot.")
    if len(clean) < 20 or len(synthetic) < 12:
        status = "WARNING"
        warnings.append("The chain is sparse for institutional density extraction.")
    if forward_coverage < 0.15 or forward_coverage > 0.85:
        status = "WARNING"
        warnings.append("Strike coverage is materially one-sided around the implied forward.")
    if raw_density_mass < 0.70 or raw_density_mass > 1.30:
        status = "WARNING"
        warnings.append("The finite-strike density mass required material renormalization.")
    if not projection_report.get("success"):
        status = "WARNING"
        warnings.append("Arbitrage-free projection used the deterministic convex fallback.")
    if calendar_days < 3:
        status = "WARNING"
        warnings.append("Very short time to expiry makes finite-difference density estimates unstable.")

    repricing = synthetic[["strike", "observed_call_equivalent", "projected_call", "projection_error", "sources"]].copy()
    settings = OptionsRiskNeutralSettings(
        expiration=str(target_expiry.date()),
        risk_free_rate=float(risk_free_rate),
        dividend_yield=float(dividend_yield),
        forward_method=str(forward_method),
        contract_style=str(contract_style),
        parity_moneyness_band=float(parity_moneyness_band),
        max_relative_spread=float(max_relative_spread),
        minimum_open_interest=int(minimum_open_interest),
        minimum_volume=int(minimum_volume),
        smoothing_penalty=float(smoothing_penalty),
    )
    signature = _configuration_signature(
        {
            "engine": OPTIONS_RISK_NEUTRAL_VERSION,
            "ticker": lab.get("ticker"),
            "pricing_spot": spot,
            "lab_spot": lab_spot,
            "spot_source": spot_report.get("source"),
            "settings": asdict(settings),
            "quotes": int(len(clean)),
            "forward": forward,
        }
    )
    return {
        "ok": True,
        "status": status,
        "version": OPTIONS_RISK_NEUTRAL_VERSION,
        "configuration_signature": signature,
        "settings": asdict(settings),
        "spot": spot,
        "pricing_spot": spot,
        "lab_spot": lab_spot,
        "pricing_spot_source": str(spot_report.get("source")),
        "spot_sync_gap": float(spot_report.get("spot_gap", float("nan"))),
        "spot_sync_report": spot_report,
        "valuation_date": str(pd.Timestamp(valuation).date()),
        "expiration": str(target_expiry.date()),
        "calendar_days": calendar_days,
        "time_to_expiry": time_to_expiry,
        "risk_free_rate": float(risk_free_rate),
        "dividend_yield_input": float(dividend_yield),
        "dividend_yield_effective": effective_q,
        "contract_style": str(contract_style),
        "parity_requested": bool(parity_requested),
        "parity_accepted": bool(forward_report.get("accepted")),
        "reliable_smile_quotes": int(clean["smile_eligible"].sum()),
        "forward": float(forward),
        "forward_report": forward_report,
        "normalization_report": normalization_report,
        "source_report": dict(source_report or {}),
        "projection_report": projection_report,
        "variance_report": variance_report,
        "model_free_variance": model_free_variance,
        "model_free_volatility": math.sqrt(model_free_variance) if np.isfinite(model_free_variance) and model_free_variance > 0.0 else float("nan"),
        "expected_move_1sigma": spot * math.sqrt(model_free_variance * time_to_expiry) if np.isfinite(model_free_variance) and model_free_variance > 0.0 else float("nan"),
        "raw_density_mass": raw_density_mass,
        "risk_neutral_metrics": risk_neutral_metrics,
        "physical_comparison": physical,
        "clean_chain": clean.reset_index(drop=True),
        "parity_table": parity_table,
        "synthetic_call_curve": synthetic,
        "density_table": density_table,
        "display_density_table": display_density_table,
        "repricing_table": repricing,
        "otm_variance_table": otm_table,
        "warnings": list(dict.fromkeys(str(value) for value in warnings if str(value))),
        "measure_governance": {
            "risk_neutral": "Q-measure inferred from current option prices and explicit carry assumptions.",
            "physical": "P-measure from historical calibration and the selected Monte Carlo simulation engine.",
            "exercise_style": "American equity/ETF chains are treated as an OTM European-equivalent approximation unless a European contract style is explicitly selected.",
            "prohibition": "Q probabilities are pricing probabilities, not unbiased real-world forecasts.",
        },
    }
