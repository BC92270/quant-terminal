from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from .estimators import pair_frame


def rolling_corr_series(changes: pd.DataFrame, a: str, b: str, window: int) -> pd.Series:
    df = pair_frame(changes, a, b, None)
    if len(df) < window + 5:
        return pd.Series(dtype=float)
    return df[a].rolling(window).corr(df[b]).rename("rolling_corr")


def ewma_corr_series(changes: pd.DataFrame, a: str, b: str, lam: float = 0.94) -> pd.Series:
    df = pair_frame(changes, a, b, None)
    if len(df) < 20:
        return pd.Series(dtype=float)
    x = df[a].to_numpy(dtype=float)
    y = df[b].to_numpy(dtype=float)
    vx = np.var(x[: min(20, len(x))])
    vy = np.var(y[: min(20, len(y))])
    cov = np.cov(x[: min(20, len(x))], y[: min(20, len(y))])[0, 1]
    out = []
    for xi, yi in zip(x, y):
        vx = lam * vx + (1 - lam) * xi * xi
        vy = lam * vy + (1 - lam) * yi * yi
        cov = lam * cov + (1 - lam) * xi * yi
        rho = cov / max(np.sqrt(vx * vy), 1e-18)
        out.append(float(np.clip(rho, -0.999, 0.999)))
    return pd.Series(out, index=df.index, name="ewma_corr")


def _ewma_standardize(df: pd.DataFrame, lam: float = 0.94) -> np.ndarray:
    x = df.to_numpy(dtype=float)
    z = np.zeros_like(x)
    var = np.var(x[: min(30, len(x))], axis=0) + 1e-12
    for t in range(len(x)):
        var = lam * var + (1 - lam) * (x[t] ** 2)
        z[t] = x[t] / np.sqrt(var)
    z -= np.nanmean(z, axis=0)
    z /= np.nanstd(z, axis=0) + 1e-12
    return z


def dcc_pair_series(changes: pd.DataFrame, a: str, b: str, maxiter: int = 250) -> tuple[pd.Series, dict]:
    """Parsimonious DCC(1,1) for one pair using EWMA-standardised innovations."""
    df = pair_frame(changes, a, b, None)
    if len(df) < 80:
        return pd.Series(dtype=float), {"status": "insufficient_data"}
    z = _ewma_standardize(df)
    s = np.corrcoef(z.T)
    s = np.nan_to_num(s, nan=0.0)
    np.fill_diagonal(s, 1.0)

    def objective(theta):
        alpha, beta = theta
        if alpha < 0 or beta < 0 or alpha + beta >= 0.995:
            return 1e9
        q = s.copy()
        ll = 0.0
        for t in range(1, len(z)):
            prev = z[t - 1][:, None]
            q = (1 - alpha - beta) * s + alpha * (prev @ prev.T) + beta * q
            d = np.sqrt(np.clip(np.diag(q), 1e-12, None))
            r = q / np.outer(d, d)
            r = np.clip(r, -0.999999, 0.999999)
            np.fill_diagonal(r, 1.0)
            det = max(np.linalg.det(r), 1e-12)
            try:
                inv = np.linalg.inv(r)
            except np.linalg.LinAlgError:
                return 1e9
            zz = z[t][:, None]
            ll += np.log(det) + float((zz.T @ (inv - np.eye(2)) @ zz)[0, 0])
        return 0.5 * ll

    res = minimize(objective, x0=np.array([0.03, 0.94]), method="SLSQP", bounds=[(1e-6, 0.30), (0.10, 0.995)], constraints={"type": "ineq", "fun": lambda x: 0.994 - x[0] - x[1]}, options={"maxiter": maxiter, "ftol": 1e-8})
    alpha, beta = (res.x if res.success else np.array([0.03, 0.94]))
    q = s.copy()
    rhos = [s[0, 1]]
    for t in range(1, len(z)):
        prev = z[t - 1][:, None]
        q = (1 - alpha - beta) * s + alpha * (prev @ prev.T) + beta * q
        d = np.sqrt(np.clip(np.diag(q), 1e-12, None))
        r = q / np.outer(d, d)
        rhos.append(float(np.clip(r[0, 1], -0.999, 0.999)))
    meta = {"alpha": float(alpha), "beta": float(beta), "persistence": float(alpha + beta), "success": bool(res.success), "objective": float(res.fun) if np.isfinite(res.fun) else None}
    return pd.Series(rhos, index=df.index, name="dcc_corr"), meta
