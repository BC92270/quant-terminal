from __future__ import annotations

import numpy as np
import pandas as pd

from .utils import safe_float


def _wilson(k: int, n: int, z: float = 1.959963984540054) -> tuple[float | None, float | None]:
    if n <= 0:
        return None, None
    p = k / n
    den = 1 + z*z/n
    center = (p + z*z/(2*n))/den
    half = z*np.sqrt((p*(1-p)/n) + z*z/(4*n*n))/den
    return float(max(0, center-half)), float(min(1, center+half))


def pair_tail_surface(changes: pd.DataFrame, primary: str, peer: str, days: int = 504,
                      quantiles: tuple[float, ...] = (0.05, 0.10, 0.25, 0.75, 0.90, 0.95)) -> pd.DataFrame:
    if changes is None or primary not in changes or peer not in changes:
        return pd.DataFrame()
    df = changes[[primary, peer]].tail(days).dropna()
    if len(df) < 60:
        return pd.DataFrame()
    rows = []
    for q in quantiles:
        q = float(q)
        if q <= 0.5:
            pcut = df[primary].quantile(q); qcut = df[peer].quantile(q)
            cond = df[primary] <= pcut; joint = cond & (df[peer] <= qcut)
            label = f"q{int(round(100*q))} lower"
            baseline = q
        else:
            pcut = df[primary].quantile(q); qcut = df[peer].quantile(q)
            cond = df[primary] >= pcut; joint = cond & (df[peer] >= qcut)
            label = f"q{int(round(100*q))} upper"
            baseline = 1-q
        n = int(cond.sum()); k = int(joint.sum())
        prob = k/n if n else None
        lo, hi = _wilson(k, n)
        sub = df.loc[cond]
        corr = safe_float(sub[primary].corr(sub[peer])) if len(sub) >= 5 else None
        rows.append({
            "Quantile": label,
            "q": q,
            "Conditional obs": n,
            "Joint obs": k,
            "Co-exceedance": prob,
            "Independence baseline": baseline,
            "Excess vs independence": (prob-baseline) if prob is not None else None,
            "CI low": lo,
            "CI high": hi,
            "Conditional corr": corr,
        })
    return pd.DataFrame(rows)


def tail_surface_table(changes: pd.DataFrame, primary: str, peers: list[str], days: int = 504,
                       quantiles: tuple[float, ...] = (0.05, 0.10, 0.25, 0.75, 0.90, 0.95)) -> pd.DataFrame:
    rows = []
    for peer in peers:
        s = pair_tail_surface(changes, primary, peer, days, quantiles)
        if s.empty:
            continue
        for _, r in s.iterrows():
            rows.append({"Ticker": peer, **r.to_dict()})
    return pd.DataFrame(rows)
