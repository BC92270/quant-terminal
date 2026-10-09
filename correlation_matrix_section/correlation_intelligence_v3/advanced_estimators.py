from __future__ import annotations

"""Robust and nonlinear dependency estimators.

The objects in this module deliberately remain separate from covariance forecasts:

* regularized Tyler estimates an elliptical scatter/correlation matrix and is PSD;
* distance correlation is a nonlinear dependence diagnostic in ``[0, 1]`` and must
  never be passed to a covariance optimiser as if it were a signed correlation.

Keeping the two contracts explicit prevents a visually attractive dependence matrix
from silently acquiring portfolio authority.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class RobustCorrelationResult:
    matrix: pd.DataFrame
    metadata: dict


def _common_panel(changes: pd.DataFrame, days: int, min_obs: int) -> pd.DataFrame:
    if changes is None or changes.empty:
        return pd.DataFrame()
    x = (
        changes.tail(int(days))
        .apply(pd.to_numeric, errors="coerce")
        .dropna(axis=1, thresh=int(min_obs))
        .dropna(how="any")
    )
    if len(x) < int(min_obs) or x.shape[1] < 2:
        return pd.DataFrame()
    finite = np.isfinite(x.to_numpy(dtype=float)).all(axis=1)
    return x.loc[finite]


def _nearest_correlation(a: np.ndarray, floor: float = 1e-8) -> np.ndarray:
    x = np.asarray(a, dtype=float)
    x = np.nan_to_num(0.5 * (x + x.T), nan=0.0, posinf=0.0, neginf=0.0)
    vals, vecs = np.linalg.eigh(x)
    vals = np.clip(vals, floor, None)
    x = (vecs * vals) @ vecs.T
    d = np.sqrt(np.clip(np.diag(x), floor, None))
    x = x / np.outer(d, d)
    x = np.clip(0.5 * (x + x.T), -1.0, 1.0)
    np.fill_diagonal(x, 1.0)
    return x


def regularized_tyler_correlation(
    changes: pd.DataFrame,
    days: int,
    min_obs: int = 40,
    shrinkage: float | None = None,
    max_iter: int = 300,
    tolerance: float = 1e-7,
) -> RobustCorrelationResult:
    """Estimate a shrinkage Tyler correlation matrix.

    Tyler scatter is resistant to radial outliers and heavy tails.  A positive
    shrinkage intensity guarantees a well-conditioned solution when ``n`` is close
    to ``p``.  The trace normalisation is immaterial after conversion to correlation
    but makes convergence diagnostics deterministic and auditable.
    """

    x = _common_panel(changes, days, min_obs)
    if x.empty:
        return RobustCorrelationResult(pd.DataFrame(), {"status": "insufficient_data", "obs": int(len(x))})

    arr = x.to_numpy(dtype=float)
    arr = arr - np.median(arr, axis=0, keepdims=True)
    scale = np.median(np.abs(arr), axis=0) * 1.4826
    fallback_scale = np.std(arr, axis=0, ddof=1)
    scale = np.where(np.isfinite(scale) & (scale > 1e-12), scale, fallback_scale)
    scale = np.where(np.isfinite(scale) & (scale > 1e-12), scale, 1.0)
    z = arr / scale
    norms = np.linalg.norm(z, axis=1)
    z = z[np.isfinite(norms) & (norms > 1e-12)]
    n, p = z.shape
    if n < min_obs:
        return RobustCorrelationResult(pd.DataFrame(), {"status": "insufficient_nonzero_rows", "obs": int(n)})

    # A data-driven but deterministic regularisation floor.  It rises as p/n grows.
    rho = float(shrinkage) if shrinkage is not None else float(np.clip(p / max(n, 1), 0.05, 0.35))
    rho = float(np.clip(rho, 1e-4, 0.95))
    scatter = np.eye(p, dtype=float)
    converged = False
    delta = np.inf
    iterations = 0

    for iterations in range(1, int(max_iter) + 1):
        inv = np.linalg.pinv(scatter, hermitian=True)
        denom = np.einsum("ij,jk,ik->i", z, inv, z)
        good = np.isfinite(denom) & (denom > 1e-14)
        if int(good.sum()) < max(10, p + 1):
            break
        weighted = z[good] / np.sqrt(denom[good])[:, None]
        update = (p / int(good.sum())) * (weighted.T @ weighted)
        update *= p / max(float(np.trace(update)), 1e-18)
        update = (1.0 - rho) * update + rho * np.eye(p)
        update *= p / max(float(np.trace(update)), 1e-18)
        delta = float(np.linalg.norm(update - scatter, ord="fro") / max(np.linalg.norm(scatter, ord="fro"), 1e-18))
        scatter = 0.5 * (update + update.T)
        if delta <= tolerance:
            converged = True
            break

    corr = _nearest_correlation(scatter)
    out = pd.DataFrame(corr, index=x.columns, columns=x.columns)
    eig = np.linalg.eigvalsh(corr)
    meta = {
        "status": "ok" if converged else "max_iter_or_degenerate",
        "authoritative": bool(converged),
        "method": "regularized Tyler scatter",
        "obs": int(n),
        "assets": int(p),
        "shrinkage": rho,
        "iterations": int(iterations),
        "converged": bool(converged),
        "relative_delta": float(delta) if np.isfinite(delta) else None,
        "min_eigenvalue": float(eig.min()),
        "condition_number": float(np.linalg.cond(corr)),
        "centering": "coordinate median",
        "scaling": "MAD with standard-deviation fallback",
    }
    return RobustCorrelationResult(out, meta)


def _distance_correlation_1d(x: np.ndarray, y: np.ndarray) -> float:
    """Biased sample distance correlation, bounded and stable for UI diagnostics."""

    x = np.asarray(x, dtype=float).reshape(-1)
    y = np.asarray(y, dtype=float).reshape(-1)
    if len(x) < 4 or len(x) != len(y):
        return np.nan
    a = np.abs(x[:, None] - x[None, :])
    b = np.abs(y[:, None] - y[None, :])
    A = a - a.mean(axis=0)[None, :] - a.mean(axis=1)[:, None] + a.mean()
    B = b - b.mean(axis=0)[None, :] - b.mean(axis=1)[:, None] + b.mean()
    dcov2 = float(np.mean(A * B))
    dvarx2 = float(np.mean(A * A))
    dvary2 = float(np.mean(B * B))
    denom = np.sqrt(max(dvarx2 * dvary2, 0.0))
    if denom <= 1e-18:
        return 0.0
    # dCor^2 = dCov^2 / sqrt(dVarX^2 dVarY^2).
    return float(np.sqrt(np.clip(dcov2 / denom, 0.0, 1.0)))


def distance_correlation_matrix(
    changes: pd.DataFrame,
    days: int,
    min_obs: int = 30,
) -> RobustCorrelationResult:
    """Pairwise nonlinear dependence matrix with explicit non-covariance authority."""

    if changes is None or changes.empty:
        return RobustCorrelationResult(pd.DataFrame(), {"status": "insufficient_data"})
    rt = changes.tail(int(days)).apply(pd.to_numeric, errors="coerce")
    cols = list(rt.columns)
    if len(cols) < 2:
        return RobustCorrelationResult(pd.DataFrame(), {"status": "insufficient_assets"})
    out = np.eye(len(cols), dtype=float)
    nobs = np.zeros((len(cols), len(cols)), dtype=int)
    for i in range(len(cols)):
        nobs[i, i] = int(rt[cols[i]].notna().sum())
        for j in range(i + 1, len(cols)):
            pair = rt[[cols[i], cols[j]]].dropna()
            nobs[i, j] = nobs[j, i] = int(len(pair))
            value = _distance_correlation_1d(pair.iloc[:, 0].to_numpy(), pair.iloc[:, 1].to_numpy()) if len(pair) >= min_obs else np.nan
            out[i, j] = out[j, i] = value
    matrix = pd.DataFrame(out, index=cols, columns=cols)
    finite_pairs = int(np.isfinite(out[np.triu_indices(len(cols), 1)]).sum())
    return RobustCorrelationResult(matrix, {
        "status": "ok" if finite_pairs else "insufficient_pairs",
        "method": "biased sample distance correlation",
        "assets": int(len(cols)),
        "finite_pairs": finite_pairs,
        "min_pair_obs": int(min_obs),
        "signed": False,
        "covariance_authority": False,
        "portfolio_eligible": False,
        "note": "Nonlinear dependence diagnostic; not a signed hedge/covariance matrix.",
        "pair_observations": pd.DataFrame(nobs, index=cols, columns=cols),
    })


def nonlinear_dependency_ranking(
    primary: str,
    changes: pd.DataFrame,
    days: int,
    min_obs: int = 30,
) -> pd.DataFrame:
    if primary not in changes.columns:
        return pd.DataFrame()
    rows: list[dict] = []
    rt = changes.tail(int(days)).apply(pd.to_numeric, errors="coerce")
    for peer in rt.columns:
        if peer == primary:
            continue
        pair = rt[[primary, peer]].dropna()
        if len(pair) < min_obs:
            continue
        pearson = float(pair[primary].corr(pair[peer]))
        dcor = _distance_correlation_1d(pair[primary].to_numpy(), pair[peer].to_numpy())
        rows.append({
            "Ticker": peer,
            "Distance correlation": dcor,
            "Abs Pearson": abs(pearson),
            "Nonlinear excess": dcor - abs(pearson),
            "Pearson sign": float(np.sign(pearson)),
            "Obs": int(len(pair)),
        })
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["Nonlinear excess", "Distance correlation"], ascending=False).reset_index(drop=True)
