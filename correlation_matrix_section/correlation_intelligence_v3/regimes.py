from __future__ import annotations

import numpy as np
import pandas as pd

from .utils import fisher_corr_ci, safe_float


def regime_labels(changes: pd.DataFrame, market: str | None = None, vol_window: int = 20) -> pd.DataFrame:
    if changes is None or changes.empty:
        return pd.DataFrame(index=changes.index if isinstance(changes, pd.DataFrame) else None)
    proxy = market if market in changes.columns else changes.columns[0]
    r = changes[proxy]
    vol = r.rolling(vol_window).std()
    med_vol = vol.expanding(min_periods=max(20, vol_window)).median()
    out = pd.DataFrame(index=changes.index)
    out["Market"] = proxy
    out["Direction"] = np.where(r >= 0, "Up", "Down")
    out["Volatility"] = np.where(vol >= med_vol, "High Vol", "Low Vol")
    out["Risk regime"] = np.select(
        [(r < 0) & (vol >= med_vol), (r >= 0) & (vol < med_vol), (r >= 0) & (vol >= med_vol)],
        ["Risk-Off", "Risk-On", "Risk-On / High Vol"],
        default="Down / Low Vol",
    )
    return out


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
            lo, hi = fisher_corr_ci(full, len(base))
            row["Full CI low"], row["Full CI high"] = lo, hi
        else:
            row["Full CI low"], row["Full CI high"] = None, None

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
                lo, hi = fisher_corr_ci(corr, n)
            else:
                lo, hi = None, None
            row[f"{regime} CI low"] = lo
            row[f"{regime} CI high"] = hi

        ro, ri = row.get("Risk-Off"), row.get("Risk-On")
        row["Stress Δ"] = (ro - ri) if ro is not None and ri is not None else None
        row["Stress quality"] = min(
            [row.get("Risk-On quality", "Fragile"), row.get("Risk-Off quality", "Fragile")],
            key=lambda q: {"Fragile": 0, "Limited": 1, "Correcte": 2, "Bonne": 3}.get(q, 0),
        )
        rows.append(row)
    return pd.DataFrame(rows)
