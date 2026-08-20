from __future__ import annotations

import numpy as np
import pandas as pd

from .estimators import beta_pair, pair_corr
from .utils import nearest_psd, safe_float


def build_factor_stress(primary: str, changes: pd.DataFrame, days: int, shocks: dict[str, float] | None = None) -> pd.DataFrame:
    shocks = shocks or {"QQQ": -0.02, "SPY": -0.02, "SMH": -0.03, "SOXX": -0.03, "TLT": -0.015, "HYG": -0.02, "GLD": 0.02, "UUP": 0.02}
    rows = []
    for factor, shock in shocks.items():
        if factor not in changes.columns or factor == primary:
            continue
        beta = beta_pair(changes, primary, factor, days, min_obs=25)
        corr, n = pair_corr(changes, primary, factor, days, "pearson", min_obs=25)
        impact = beta * shock if beta is not None else None
        rows.append({"Scenario": f"{factor} {shock:+.1%}", "Factor": factor, "Shock": shock, "Beta": beta, "Corr": corr, "Obs": n, "Mechanical impact": impact})
    return pd.DataFrame(rows)


def correlation_shock_portfolio(weights: pd.Series, vol: pd.Series, corr: pd.DataFrame, delta_corr: float) -> dict:
    common = [x for x in weights.index if x in vol.index and x in corr.index]
    if len(common) < 2:
        return {"status": "unavailable"}
    w = weights[common].to_numpy(dtype=float)
    sig = vol[common].to_numpy(dtype=float)
    c0 = corr.loc[common, common].to_numpy(dtype=float)
    c1 = c0.copy()
    for i in range(len(common)):
        for j in range(len(common)):
            if i != j:
                c1[i, j] = np.clip(c1[i, j] + delta_corr, -0.99, 0.99)
    c1 = nearest_psd(pd.DataFrame(c1, index=common, columns=common)).to_numpy(dtype=float)
    cov0 = np.outer(sig, sig) * c0
    cov1 = np.outer(sig, sig) * c1
    v0 = float(w @ cov0 @ w)
    v1 = float(w @ cov1 @ w)
    return {"status": "ok", "base_vol": np.sqrt(max(v0, 0)), "stressed_vol": np.sqrt(max(v1, 0)), "vol_change": np.sqrt(max(v1, 0)) - np.sqrt(max(v0, 0)), "delta_corr": delta_corr}
