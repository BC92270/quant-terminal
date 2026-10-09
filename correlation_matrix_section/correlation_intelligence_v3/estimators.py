from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.covariance import LedoitWolf, OAS

from .precision import temporal_graphical_lasso
from .utils import fisher_corr_ci, nearest_psd, safe_float


def trailing(df: pd.DataFrame, days: int | None) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    return df.tail(int(days)) if days is not None else df.copy()


def pair_frame(changes: pd.DataFrame, a: str, b: str, days: int | None = None) -> pd.DataFrame:
    if changes is None or changes.empty or a not in changes.columns or b not in changes.columns:
        return pd.DataFrame(columns=[a, b])
    return trailing(changes[[a, b]], days).dropna()


def pair_corr(changes: pd.DataFrame, a: str, b: str, days: int | None, method: str = "pearson", min_obs: int = 20):
    df = pair_frame(changes, a, b, days)
    if len(df) < min_obs:
        return None, len(df)
    x, y = df[a], df[b]
    m = method.lower()
    if m == "spearman":
        v = stats.spearmanr(x, y, nan_policy="omit").statistic
    elif m == "kendall":
        v = stats.kendalltau(x, y, nan_policy="omit", variant="b").statistic
    else:
        v = x.corr(y)
    return safe_float(v), len(df)


def beta_pair(changes: pd.DataFrame, y: str, x: str, days: int | None, min_obs: int = 30):
    df = pair_frame(changes, y, x, days)
    if len(df) < min_obs:
        return None
    var = safe_float(df[x].var())
    if var is None or abs(var) < 1e-18:
        return None
    return safe_float(df[[y, x]].cov().loc[y, x] / var)


def downside_corr(changes: pd.DataFrame, primary: str, peer: str, days: int, mode: str, min_obs: int = 8):
    df = pair_frame(changes, primary, peer, days)
    if df.empty:
        return None, 0
    if mode == "primary_negative":
        sub = df[df[primary] < 0]
    elif mode == "primary_worst_20":
        sub = df[df[primary] <= df[primary].quantile(0.20)]
    elif mode == "primary_best_20":
        sub = df[df[primary] >= df[primary].quantile(0.80)]
    elif mode == "peer_negative":
        sub = df[df[peer] < 0]
    else:
        sub = df
    if len(sub) < min_obs:
        return None, len(sub)
    return safe_float(sub[primary].corr(sub[peer])), len(sub)


def _listwise_matrix(changes: pd.DataFrame, days: int, min_obs: int) -> pd.DataFrame:
    rt = trailing(changes, days).copy()
    rt = rt.dropna(axis=1, thresh=min_obs)
    rt = rt.dropna(how="any")
    return rt


def correlation_matrix(
    changes: pd.DataFrame,
    days: int,
    estimator: str = "Pearson",
    min_obs: int = 30,
    return_metadata: bool = False,
):
    """Estimate a correlation matrix, optionally returning audit metadata.

    Existing callers continue to receive a ``DataFrame``.  With
    ``return_metadata=True`` the return value is ``(matrix, metadata)``.  In
    particular, Partial exposes its leakage-safe temporal-CV alpha, fold bounds,
    convergence warnings and any explicit fallback.
    """

    def result(matrix: pd.DataFrame, metadata: dict):
        return (matrix, metadata) if return_metadata else matrix

    if changes is None or changes.empty:
        return result(pd.DataFrame(), {"status": "insufficient_data", "estimator": estimator})
    est = estimator.lower()
    rt = trailing(changes, days).dropna(axis=1, thresh=min_obs)
    if rt.shape[1] < 2:
        return result(
            pd.DataFrame(),
            {"status": "insufficient_data", "estimator": estimator, "assets": int(rt.shape[1])},
        )
    if est == "pearson":
        matrix = rt.corr(method="pearson")
        return result(matrix, {"status": "ok", "estimator": "Pearson", "assets": int(matrix.shape[1])})
    if est == "spearman":
        matrix = rt.corr(method="spearman")
        return result(matrix, {"status": "ok", "estimator": "Spearman", "assets": int(matrix.shape[1])})
    if est == "kendall":
        matrix = rt.corr(method="kendall")
        return result(matrix, {"status": "ok", "estimator": "Kendall", "assets": int(matrix.shape[1])})

    complete = _listwise_matrix(changes, days, min_obs)
    if complete.shape[0] < min_obs or complete.shape[1] < 2:
        return result(
            pd.DataFrame(),
            {
                "status": "insufficient_data",
                "estimator": estimator,
                "obs": int(complete.shape[0]),
                "assets": int(complete.shape[1]),
            },
        )
    x = complete.to_numpy(dtype=float)
    metadata = {
        "status": "ok",
        "estimator": estimator,
        "obs": int(complete.shape[0]),
        "assets": int(complete.shape[1]),
    }

    if est == "ledoit-wolf":
        model = LedoitWolf().fit(x)
        cov = model.covariance_
        metadata["shrinkage"] = safe_float(model.shrinkage_)
    elif est == "oas":
        model = OAS().fit(x)
        cov = model.covariance_
        metadata["shrinkage"] = safe_float(model.shrinkage_)
    elif est == "partial":
        # Return partial correlation, not covariance correlation.
        fit = temporal_graphical_lasso(x)
        precision = fit.precision
        metadata.update(fit.metadata)
        metadata["estimator"] = "Partial"
        d = np.sqrt(np.clip(np.diag(precision), 1e-18, None))
        partial = -precision / np.outer(d, d)
        np.fill_diagonal(partial, 1.0)
        partial = np.clip(0.5 * (partial + partial.T), -1.0, 1.0)
        np.fill_diagonal(partial, 1.0)
        matrix = pd.DataFrame(partial, index=complete.columns, columns=complete.columns)
        raw_min_eigenvalue = float(np.linalg.eigvalsh(0.5 * (partial + partial.T)).min())
        metadata["raw_partial_min_eigenvalue"] = raw_min_eigenvalue
        metadata["psd_projection_applied"] = False
        metadata["output_min_eigenvalue"] = raw_min_eigenvalue
        metadata["covariance_authority"] = False
        metadata["portfolio_eligible"] = False
        metadata["matrix_contract"] = (
            "conditional pairwise association; positive semidefiniteness is not required"
        )
        return result(matrix, metadata)
    else:
        cov = np.cov(x, rowvar=False)

    sd = np.sqrt(np.clip(np.diag(cov), 1e-18, None))
    corr = cov / np.outer(sd, sd)
    np.fill_diagonal(corr, 1.0)
    matrix = nearest_psd(pd.DataFrame(corr, index=complete.columns, columns=complete.columns))
    metadata["output_min_eigenvalue"] = float(
        np.linalg.eigvalsh(matrix.to_numpy(dtype=float)).min()
    )
    return result(matrix, metadata)


def pair_metrics(changes: pd.DataFrame, primary: str, peer: str, selected_days: int) -> dict:
    csel, n = pair_corr(changes, primary, peer, selected_days, "pearson", min_obs=20)
    c30, _ = pair_corr(changes, primary, peer, 30, "pearson", min_obs=15)
    c90, _ = pair_corr(changes, primary, peer, 90, "pearson", min_obs=25)
    c180, _ = pair_corr(changes, primary, peer, 180, "pearson", min_obs=40)
    c252, _ = pair_corr(changes, primary, peer, 252, "pearson", min_obs=60)
    spear, _ = pair_corr(changes, primary, peer, selected_days, "spearman", min_obs=20)
    kendall, _ = pair_corr(changes, primary, peer, selected_days, "kendall", min_obs=20)
    beta = beta_pair(changes, primary, peer, selected_days, min_obs=25)
    dcor, dn = downside_corr(changes, primary, peer, selected_days, "primary_negative")
    worst, wn = downside_corr(changes, primary, peer, selected_days, "primary_worst_20")
    upside, un = downside_corr(changes, primary, peer, selected_days, "primary_best_20")
    lo, hi = fisher_corr_ci(csel, n) if csel is not None else (None, None)
    return {
        "Ticker": peer,
        "Corr": csel,
        "Spearman": spear,
        "Kendall": kendall,
        "Corr 30D": c30,
        "Corr 90D": c90,
        "Corr 180D": c180,
        "Corr 1Y": c252,
        "ΔCorr 30D-1Y": (c30 - c252) if c30 is not None and c252 is not None else None,
        "Beta ticker vs peer": beta,
        "R²": csel * csel if csel is not None else None,
        "Downside corr": dcor,
        "Worst 20% corr": worst,
        "Upside corr": upside,
        "Stress lift": (worst - csel) if worst is not None and csel is not None else None,
        "Obs": n,
        "Downside obs": dn,
        "Worst obs": wn,
        "Upside obs": un,
        "CI low": lo,
        "CI high": hi,
    }
