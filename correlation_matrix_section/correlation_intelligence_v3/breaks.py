from __future__ import annotations

import math
import numpy as np
import pandas as pd

from .utils import safe_float


def _corr_distance(a: pd.DataFrame, b: pd.DataFrame) -> float:
    if a.empty or b.empty:
        return np.nan
    cols = [c for c in a.columns if c in b.columns]
    if len(cols) < 2:
        return np.nan
    return _corr_distance_array(a[cols].to_numpy(dtype=float), b[cols].to_numpy(dtype=float))


def _corr_distance_array(a: np.ndarray, b: np.ndarray) -> float:
    """RMS distance between upper triangles of two correlation matrices."""
    if a.ndim != 2 or b.ndim != 2 or a.shape[1] != b.shape[1] or a.shape[1] < 2:
        return np.nan
    ca = np.corrcoef(a, rowvar=False)
    cb = np.corrcoef(b, rowvar=False)
    if not (np.isfinite(ca).all() and np.isfinite(cb).all()):
        return np.nan
    tri = np.triu_indices(a.shape[1], 1)
    return float(np.sqrt(np.mean((ca[tri] - cb[tri]) ** 2)))


def _candidate_shifts(arr: np.ndarray, w: int, step: int) -> tuple[np.ndarray, np.ndarray]:
    splits = np.arange(w, len(arr) - w + 1, max(1, int(step)), dtype=int)
    vals = np.empty(len(splits), dtype=float)
    for ii, split in enumerate(splits):
        vals[ii] = _corr_distance_array(arr[split - w:split], arr[split:split + w])
    return splits, vals


def _moving_block_resample(arr: np.ndarray, block: int, rng: np.random.Generator) -> np.ndarray:
    """Circular moving-block bootstrap sample with the same length as ``arr``."""
    n = len(arr)
    block = max(2, min(int(block), n))
    n_blocks = int(math.ceil(n / block))
    starts = rng.integers(0, n, size=n_blocks)
    offsets = np.arange(block)
    pieces = [arr[(int(s) + offsets) % n] for s in starts]
    return np.concatenate(pieces, axis=0)[:n]


def dependency_break_detector(
    changes: pd.DataFrame,
    primary: str,
    days: int = 504,
    side_window: int = 60,
    step: int = 5,
    bootstrap_samples: int = 249,
    seed: int = 42,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Detect matrix-level dependency breaks with post-selection-corrected inference.

    Candidate dates compare equal pre/post correlation windows. The reported test statistic is
    the *maximum* matrix shift over all candidate dates. Significance therefore uses a supremum
    (max-stat) moving-block bootstrap: every null resample repeats the complete break-date search
    and contributes its own maximum statistic. This corrects the selection bias that would arise
    from testing only the date selected as the largest break in the observed sample.

    The procedure is a structural-dependence diagnostic, not a causal test.
    """
    if changes is None or changes.empty or primary not in changes.columns:
        return pd.DataFrame(), pd.DataFrame(), {"status": "unavailable"}

    x = (
        changes.tail(days)
        .apply(pd.to_numeric, errors="coerce")
        .dropna(axis=1, thresh=max(40, side_window))
        .dropna(how="any")
    )
    n, p = x.shape
    w = int(side_window)
    if n < 2 * w + 10 or p < 3:
        return pd.DataFrame(), pd.DataFrame(), {"status": "insufficient_data", "obs": n, "assets": p}

    arr = x.to_numpy(dtype=float)
    splits, shifts = _candidate_shifts(arr, w, step)
    valid = np.isfinite(shifts)
    splits, shifts = splits[valid], shifts[valid]
    if len(shifts) == 0:
        return pd.DataFrame(), pd.DataFrame(), {"status": "unavailable"}

    dates = [x.index[int(s)] for s in splits]
    curve = pd.DataFrame({"Split": splits, "Date": dates, "Matrix shift": shifts})
    best_idx = int(np.argmax(shifts))
    split = int(splits[best_idx])
    observed = float(shifts[best_idx])

    rng = np.random.default_rng(seed)
    # Preserve short-run serial dependence while destroying a persistent global break.
    block = max(3, min(12, w // 6))
    null_maxima: list[float] = []
    requested = max(20, int(bootstrap_samples))
    for _ in range(requested):
        boot = _moving_block_resample(arr, block, rng)
        _, boot_shifts = _candidate_shifts(boot, w, step)
        finite = boot_shifts[np.isfinite(boot_shifts)]
        if len(finite):
            null_maxima.append(float(np.max(finite)))

    null_arr = np.asarray(null_maxima, dtype=float)
    exceedances = int(np.sum(null_arr >= observed)) if len(null_arr) else 0
    pvalue = float((1 + exceedances) / (1 + len(null_arr))) if len(null_arr) else None
    resolution = float(1.0 / (1 + len(null_arr))) if len(null_arr) else None
    at_floor = bool(len(null_arr) and exceedances == 0)

    pre = x.iloc[split - w:split]
    post = x.iloc[split:split + w]
    cp, cq = pre.corr(), post.corr()
    rows = []
    for peer in x.columns:
        if peer == primary:
            continue
        a = safe_float(cp.loc[primary, peer])
        b = safe_float(cq.loc[primary, peer])
        if a is None or b is None:
            continue
        rows.append({"Ticker": peer, "Pre corr": a, "Post corr": b, "Δ corr": b - a, "Abs Δ": abs(b - a)})
    links = (
        pd.DataFrame(rows).sort_values("Abs Δ", ascending=False).drop(columns="Abs Δ").reset_index(drop=True)
        if rows else pd.DataFrame()
    )

    critical_95 = float(np.quantile(null_arr, 0.95)) if len(null_arr) else None
    critical_99 = float(np.quantile(null_arr, 0.99)) if len(null_arr) else None
    meta = {
        "status": "ok",
        "break_date": pd.Timestamp(dates[best_idx]),
        "matrix_shift": observed,
        "bootstrap_pvalue": pvalue,
        "pvalue_resolution": resolution,
        "pvalue_at_floor": at_floor,
        "bootstrap_exceedances": exceedances,
        "significant_5pct": bool(pvalue is not None and pvalue < 0.05),
        "side_window": w,
        "step": int(step),
        "obs": n,
        "assets": p,
        "null_samples": int(len(null_arr)),
        "bootstrap_requested": requested,
        "bootstrap_block": block,
        "critical_95": critical_95,
        "critical_99": critical_99,
        "selection_adjustment": "supremum / max-stat moving-block bootstrap",
    }
    return curve, links, meta
