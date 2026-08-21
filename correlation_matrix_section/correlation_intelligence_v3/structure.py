from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import linkage, leaves_list
from scipy.spatial.distance import squareform
from scipy.sparse.csgraph import minimum_spanning_tree

from .estimators import correlation_matrix, trailing
from .utils import effective_rank, nearest_psd, safe_float


def hierarchical_order(corr: pd.DataFrame) -> list[str]:
    if corr is None or corr.empty or corr.shape[0] < 3:
        return list(corr.columns) if isinstance(corr, pd.DataFrame) else []
    c = corr.copy().clip(-1, 1)
    dist = np.sqrt(np.clip(2 * (1 - c.to_numpy(dtype=float)), 0, None))
    np.fill_diagonal(dist, 0.0)
    try:
        condensed = squareform(dist, checks=False)
        z = linkage(condensed, method="average")
        idx = leaves_list(z)
        return [c.columns[i] for i in idx]
    except Exception:
        return list(c.columns)


def mst_edges(corr: pd.DataFrame) -> pd.DataFrame:
    if corr is None or corr.empty or corr.shape[0] < 2:
        return pd.DataFrame()
    c = corr.clip(-1, 1)
    dist = np.sqrt(np.clip(2 * (1 - c.to_numpy(dtype=float)), 0, None))
    tree = minimum_spanning_tree(dist).tocoo()
    rows = []
    cols = list(c.columns)
    for i, j, d in zip(tree.row, tree.col, tree.data):
        rows.append({"From": cols[i], "To": cols[j], "Distance": float(d), "Corr": safe_float(c.iloc[i, j])})
    return pd.DataFrame(rows).sort_values("Distance").reset_index(drop=True)


def rmt_diagnostics(changes: pd.DataFrame, days: int, min_obs: int = 40) -> tuple[dict, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    rt = trailing(changes, days).dropna(axis=1, thresh=min_obs).dropna(how="any")
    if rt.shape[0] < min_obs or rt.shape[1] < 3:
        return {"status": "unavailable"}, pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    raw = correlation_matrix(rt, len(rt), "Pearson", min_obs=min_obs)
    raw = nearest_psd(raw)
    vals, vecs = np.linalg.eigh(raw.to_numpy(dtype=float))
    order = np.argsort(vals)[::-1]
    vals, vecs = vals[order], vecs[:, order]
    n, t = raw.shape[0], rt.shape[0]
    q = n / t
    lmin = max(0.0, (1 - np.sqrt(q)) ** 2)
    lmax = (1 + np.sqrt(q)) ** 2
    above = vals > lmax
    inside = (vals >= lmin) & (vals <= lmax)
    below = vals < lmin

    eig = pd.DataFrame({
        "Rank": np.arange(1, n + 1),
        "Eigenvalue": vals,
        "Zone": np.where(above, "Above MP", np.where(inside, "Inside MP", "Below MP")),
        "MP min": lmin,
        "MP max": lmax,
        "Variance explained": vals / max(vals.sum(), 1e-12),
    })
    loadings = []
    for k in range(min(5, n)):
        for i, asset in enumerate(raw.columns):
            loadings.append({"Component": f"PC{k+1}", "Asset": asset, "Loading": float(vecs[i, k]), "Abs loading": abs(float(vecs[i, k]))})
    loading_df = pd.DataFrame(loadings)

    # Constant residual eigenvalue cleaning: keep informative eigenvalues, replace the rest by their mean.
    clean_vals = vals.copy()
    noise_mask = ~above
    if noise_mask.any():
        clean_vals[noise_mask] = float(vals[noise_mask].mean())
    cleaned = vecs @ np.diag(clean_vals) @ vecs.T
    d = np.sqrt(np.clip(np.diag(cleaned), 1e-12, None))
    cleaned = cleaned / np.outer(d, d)
    np.fill_diagonal(cleaned, 1.0)
    clean_df = nearest_psd(pd.DataFrame(cleaned, index=raw.index, columns=raw.columns))

    summary = {
        "status": "ok",
        "n_assets": n,
        "t_obs": t,
        "q_ratio": q,
        "lambda_min": lmin,
        "lambda_max": lmax,
        "above_mp": int(above.sum()),
        "inside_mp": int(inside.sum()),
        "below_mp": int(below.sum()),
        "market_mode_strength": float(vals[0] / n),
        "effective_rank": effective_rank(vals),
        "condition_number": float(vals.max() / max(vals.min(), 1e-10)),
        "pc1_variance": float(vals[0] / vals.sum()),
    }
    return summary, eig, loading_df, clean_df
