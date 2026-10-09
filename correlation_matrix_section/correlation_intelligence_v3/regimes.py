from __future__ import annotations

import numpy as np
import pandas as pd
import zlib

from .utils import safe_float


def regime_labels(changes: pd.DataFrame, market: str | None = None, vol_window: int = 20, trend_window: int = 20) -> pd.DataFrame:
    if changes is None or changes.empty:
        return pd.DataFrame(index=changes.index if isinstance(changes, pd.DataFrame) else None)
    proxy = market if market in changes.columns else changes.columns[0]
    r = changes[proxy]
    vol = r.rolling(vol_window).std()
    med_vol = vol.expanding(min_periods=max(20, vol_window)).median()
    trend = r.rolling(trend_window, min_periods=trend_window).sum()
    valid = trend.notna() & vol.notna() & med_vol.notna()
    out = pd.DataFrame(index=changes.index)
    out["Market"] = proxy
    out["Trend return"] = trend
    out["Direction"] = pd.Series(pd.NA, index=out.index, dtype="object")
    out["Volatility"] = pd.Series(pd.NA, index=out.index, dtype="object")
    out["Risk regime"] = pd.Series(pd.NA, index=out.index, dtype="object")
    out.loc[valid, "Direction"] = np.where(trend[valid] >= 0, "Up", "Down")
    out.loc[valid, "Volatility"] = np.where(
        vol[valid] >= med_vol[valid], "High Vol", "Low Vol"
    )
    out.loc[valid, "Risk regime"] = np.select(
        [
            (trend[valid] < 0) & (vol[valid] >= med_vol[valid]),
            (trend[valid] >= 0) & (vol[valid] < med_vol[valid]),
            (trend[valid] >= 0) & (vol[valid] >= med_vol[valid]),
        ],
        ["Risk-Off", "Risk-On", "Risk-On / High Vol"],
        default="Down / Low Vol",
    )
    return out


def _moving_block_corr_ci(
    frame: pd.DataFrame,
    a: str,
    b: str,
    samples: int,
    block: int,
    seed: int,
    level: float = 0.95,
) -> tuple[float | None, float | None, int]:
    x = frame[[a, b]].dropna()
    n = len(x)
    if n < 12 or samples <= 0:
        return None, None, 0
    arr = x.to_numpy(dtype=float)
    rng = np.random.default_rng(seed)
    width = max(2, min(int(block), n))
    values: list[float] = []
    for _ in range(int(samples)):
        starts = rng.integers(0, n, size=int(np.ceil(n / width)))
        ix = np.concatenate([(s + np.arange(width)) % n for s in starts])[:n]
        corr = np.corrcoef(arr[ix, 0], arr[ix, 1])[0, 1]
        if np.isfinite(corr):
            values.append(float(corr))
    if len(values) < max(30, samples // 3):
        return None, None, len(values)
    alpha = (1.0 - float(level)) / 2.0
    lo, hi = np.quantile(values, [alpha, 1.0 - alpha])
    return float(lo), float(hi), len(values)


def _quality(n: int, reliable_obs: int) -> str:
    if n < 20:
        return "Fragile"
    if n < reliable_obs:
        return "Limited"
    if n < 60:
        return "Correcte"
    return "Bonne"


def conditional_pair_table(
    primary: str,
    changes: pd.DataFrame,
    peers: list[str],
    market: str | None,
    days: int,
    min_obs: int = 12,
    reliable_obs: int = 30,
    bootstrap_samples: int = 199,
    block_length: int = 5,
    random_seed: int = 42,
) -> pd.DataFrame:
    rt = changes.tail(days)
    labels = regime_labels(rt, market)
    rows = []
    regimes = ["Risk-On", "Risk-Off", "High Vol", "Low Vol"]

    for peer in peers:
        if peer == primary or peer not in rt.columns:
            continue
        base = rt[[primary, peer]].dropna()
        full = safe_float(base[primary].corr(base[peer])) if len(base) >= min_obs else None
        row = {"Ticker": peer, "Full": full, "N Full": len(base), "Full quality": _quality(len(base), reliable_obs)}
        if full is not None:
            salt = zlib.crc32(f"{primary}|{peer}|Full".encode("utf-8"))
            lo, hi, reps = _moving_block_corr_ci(base, primary, peer, bootstrap_samples, block_length, random_seed + salt)
            row["Full CI low"], row["Full CI high"] = lo, hi
            row["Full CI reps"] = reps
        else:
            row["Full CI low"], row["Full CI high"] = None, None
            row["Full CI reps"] = 0

        for regime in regimes:
            if regime in {"High Vol", "Low Vol"}:
                mask = labels["Volatility"] == regime
            else:
                mask = labels["Risk regime"] == regime
            sub = rt.loc[mask, [primary, peer]].dropna()
            n = len(sub)
            corr = safe_float(sub[primary].corr(sub[peer])) if n >= min_obs else None
            row[regime] = corr
            row[f"N {regime}"] = n
            row[f"{regime} quality"] = _quality(n, reliable_obs)
            if corr is not None:
                salt = zlib.crc32(f"{primary}|{peer}|{regime}".encode("utf-8"))
                lo, hi, reps = _moving_block_corr_ci(sub, primary, peer, bootstrap_samples, block_length, random_seed + salt)
            else:
                lo, hi, reps = None, None, 0
            row[f"{regime} CI low"] = lo
            row[f"{regime} CI high"] = hi
            row[f"{regime} CI reps"] = reps

        ro, ri = row.get("Risk-Off"), row.get("Risk-On")
        row["Stress Δ"] = (ro - ri) if ro is not None and ri is not None else None
        row["Stress quality"] = min(
            [row.get("Risk-On quality", "Fragile"), row.get("Risk-Off quality", "Fragile")],
            key=lambda q: {"Fragile": 0, "Limited": 1, "Correcte": 2, "Bonne": 3}.get(q, 0),
        )
        row["CI method"] = f"moving-block bootstrap ({bootstrap_samples} requested, block {block_length})"
        row["Regime definition"] = "20D market trend × expanding-median 20D volatility"
        rows.append(row)
    return pd.DataFrame(rows)
