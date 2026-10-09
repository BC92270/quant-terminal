from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import fcluster, linkage, leaves_list
from scipy.spatial.distance import squareform
from scipy.sparse.csgraph import minimum_spanning_tree
from sklearn.covariance import LedoitWolf

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


def _moving_block_indices(n: int, block: int, rng: np.random.Generator) -> np.ndarray:
    if n <= 0:
        return np.array([], dtype=int)
    b = max(2, min(int(block), n))
    starts = rng.integers(0, n, size=int(np.ceil(n / b)))
    return np.concatenate([(s + np.arange(b)) % n for s in starts])[:n]


def _lw_correlation(x: np.ndarray) -> np.ndarray:
    cov = LedoitWolf().fit(np.asarray(x, dtype=float)).covariance_
    d = np.sqrt(np.clip(np.diag(cov), 1e-18, None))
    corr = cov / np.outer(d, d)
    corr = np.clip(0.5 * (corr + corr.T), -1.0, 1.0)
    np.fill_diagonal(corr, 1.0)
    return corr


def _cluster_labels(corr: np.ndarray, n_clusters: int) -> tuple[np.ndarray, np.ndarray]:
    distance = np.sqrt(np.clip(2.0 * (1.0 - corr), 0.0, None))
    np.fill_diagonal(distance, 0.0)
    tree = linkage(squareform(distance, checks=False), method="average", optimal_ordering=True)
    labels = fcluster(tree, t=int(n_clusters), criterion="maxclust")
    return labels.astype(int), tree


def cluster_stability_bootstrap(
    changes: pd.DataFrame,
    days: int,
    min_obs: int = 60,
    bootstrap_samples: int = 200,
    block: int = 5,
    n_clusters: int | None = None,
    stability_threshold: float = 0.70,
    seed: int = 42,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Moving-block stability of hierarchical correlation clusters.

    The output is a consensus/co-clustering matrix, not a new correlation estimate.
    It answers whether two assets remain in the same cluster under plausible temporal
    resamples and therefore prevents a single dendrogram from appearing more certain
    than the data support.
    """

    if changes is None or changes.empty:
        return pd.DataFrame(), pd.DataFrame(), {"status": "insufficient_data"}
    rt = (
        changes.tail(int(days))
        .apply(pd.to_numeric, errors="coerce")
        .dropna(axis=1, thresh=int(min_obs))
        .dropna(how="any")
    )
    if len(rt) < int(min_obs) or rt.shape[1] < 3:
        return pd.DataFrame(), pd.DataFrame(), {
            "status": "insufficient_data", "obs": int(len(rt)), "assets": int(rt.shape[1])
        }
    cols = list(rt.columns)
    p = len(cols)
    k = int(n_clusters or np.clip(round(np.sqrt(p)), 2, max(2, p - 1)))
    k = max(2, min(k, p - 1))
    try:
        base_corr = _lw_correlation(rt.to_numpy(dtype=float))
        base_labels, _ = _cluster_labels(base_corr, k)
    except Exception as exc:
        return pd.DataFrame(), pd.DataFrame(), {"status": "fit_failed", "error": type(exc).__name__}

    rng = np.random.default_rng(seed)
    counts = np.zeros((p, p), dtype=float)
    valid = 0
    for _ in range(max(0, int(bootstrap_samples))):
        ix = _moving_block_indices(len(rt), block, rng)
        try:
            corr = _lw_correlation(rt.to_numpy(dtype=float)[ix])
            labels, _ = _cluster_labels(corr, k)
        except Exception:
            continue
        counts += (labels[:, None] == labels[None, :]).astype(float)
        valid += 1
    if valid == 0:
        return pd.DataFrame(), pd.DataFrame(), {
            "status": "no_valid_bootstraps", "bootstrap_requested": int(bootstrap_samples)
        }

    consensus = counts / valid
    consensus_df = pd.DataFrame(consensus, index=cols, columns=cols)
    rows: list[dict] = []
    for i in range(p):
        for j in range(i + 1, p):
            frequency = float(consensus[i, j])
            rows.append({
                "Asset A": cols[i],
                "Asset B": cols[j],
                "Base cluster A": int(base_labels[i]),
                "Base cluster B": int(base_labels[j]),
                "Base co-clustered": bool(base_labels[i] == base_labels[j]),
                "Co-cluster frequency": frequency,
                "Stable co-cluster": bool(base_labels[i] == base_labels[j] and frequency >= stability_threshold),
                "Unstable boundary": bool(0.30 < frequency < stability_threshold),
            })
    pairs = pd.DataFrame(rows).sort_values(
        ["Base co-clustered", "Co-cluster frequency"], ascending=[False, False]
    ).reset_index(drop=True)
    within = [
        consensus[i, np.where((base_labels == base_labels[i]) & (np.arange(p) != i))[0]].mean()
        if np.any((base_labels == base_labels[i]) & (np.arange(p) != i)) else np.nan
        for i in range(p)
    ]
    meta = {
        "status": "ok",
        "method": "average-linkage Ledoit-Wolf consensus clustering",
        "obs": int(len(rt)),
        "assets": int(p),
        "n_clusters": int(k),
        "bootstrap_requested": int(bootstrap_samples),
        "bootstrap_valid": int(valid),
        "block_length": int(block),
        "stability_threshold": float(stability_threshold),
        "mean_base_within_cluster_stability": float(np.nanmean(within)),
        "base_labels": {c: int(v) for c, v in zip(cols, base_labels)},
    }
    return pairs, consensus_df, meta


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
