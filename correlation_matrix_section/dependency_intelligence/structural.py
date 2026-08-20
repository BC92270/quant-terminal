from __future__ import annotations

from statistics import NormalDist
from typing import Any

import numpy as np
import pandas as pd

from .config import DependencyConfig
from .inputs import ForceInputs


def _safe_corr(a: pd.Series | np.ndarray, b: pd.Series | np.ndarray) -> float:
    aa = np.asarray(a, dtype=float)
    bb = np.asarray(b, dtype=float)
    mask = np.isfinite(aa) & np.isfinite(bb)
    if mask.sum() < 3:
        return np.nan
    aa, bb = aa[mask], bb[mask]
    if np.nanstd(aa, ddof=1) <= 1e-14 or np.nanstd(bb, ddof=1) <= 1e-14:
        return np.nan
    return float(np.corrcoef(aa, bb)[0, 1])


def _moving_block_indices(n: int, block_length: int, rng: np.random.Generator) -> np.ndarray:
    """Circular moving-block bootstrap indices of exact length ``n``."""
    if n <= 0:
        return np.array([], dtype=int)
    L = max(1, min(int(block_length), n))
    blocks = int(np.ceil(n / L))
    starts = rng.integers(0, n, size=blocks)
    idx = []
    for s in starts:
        idx.extend(((s + np.arange(L)) % n).tolist())
    return np.asarray(idx[:n], dtype=int)


def _quantile_ci(values: list[float] | np.ndarray, level: float = 0.95) -> tuple[float, float, int]:
    v = np.asarray(values, dtype=float)
    v = v[np.isfinite(v)]
    if v.size == 0:
        return np.nan, np.nan, 0
    alpha = max(0.0, min(1.0, 1.0 - float(level)))
    return float(np.quantile(v, alpha / 2)), float(np.quantile(v, 1 - alpha / 2)), int(v.size)


def _wilson_interval(k: int, n: int, level: float = 0.95) -> tuple[float, float]:
    if n <= 0:
        return np.nan, np.nan
    p = k / n
    z = NormalDist().inv_cdf(0.5 + float(level) / 2.0)
    den = 1.0 + z * z / n
    center = (p + z * z / (2 * n)) / den
    half = z * np.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / den
    return float(max(0.0, center - half)), float(min(1.0, center + half))


def _sample_quality(n: int) -> str:
    if n < 10:
        return "Fragile"
    if n < 30:
        return "Limited"
    if n < 80:
        return "Adequate"
    return "Good"


def _lag_corr(a: np.ndarray, b: np.ndarray, lag: int, min_obs: int) -> tuple[float, int]:
    n = min(len(a), len(b))
    if n <= abs(lag):
        return np.nan, 0
    if lag > 0:  # primary_t vs later peer_{t+lag}
        aa, bb = a[:-lag], b[lag:]
    elif lag < 0:
        L = -lag
        aa, bb = a[L:], b[:-L]
    else:
        aa, bb = a, b
    mask = np.isfinite(aa) & np.isfinite(bb)
    if int(mask.sum()) < min_obs:
        return np.nan, int(mask.sum())
    return _safe_corr(aa[mask], bb[mask]), int(mask.sum())


def lead_lag_table(
    primary: str,
    peer: str,
    changes: pd.DataFrame,
    max_lag: int = 5,
    min_obs: int = 30,
    cfg: DependencyConfig | None = None,
) -> pd.DataFrame:
    """Lead/lag cross-correlation with post-selection-aware inference.

    The displayed lag statistic is still descriptive: ``corr(primary_t, peer_{t+lag})``.
    V4.0.2 adds two uncertainty layers:

    * a joint moving-block bootstrap CI for the *selected* non-zero lag; and
    * a synchronous-pair-preserving row-permutation max-stat p-value that controls the
      search over all non-zero lags.  The null keeps each day's contemporaneous pair
      together while destroying temporal ordering, so it asks whether the strongest
      non-zero lag exceeds what can arise from the same synchronous joint distribution
      without temporal structure.

    This is an association diagnostic, not Granger/structural causality.
    """
    if primary not in changes.columns or peer not in changes.columns:
        return pd.DataFrame()
    cfg = cfg or DependencyConfig(lead_lag_max_days=max_lag, min_pair_obs=min_obs)
    frame = pd.concat([
        pd.to_numeric(changes[primary], errors="coerce").rename("a"),
        pd.to_numeric(changes[peer], errors="coerce").rename("b"),
    ], axis=1).dropna()
    if len(frame) < min_obs:
        return pd.DataFrame()
    a = frame["a"].to_numpy(float)
    b = frame["b"].to_numpy(float)
    rows: list[dict[str, Any]] = []
    for lag in range(-max_lag, max_lag + 1):
        c, n = _lag_corr(a, b, lag, min_obs)
        rows.append({
            "Lag days": lag,
            "Correlation": c,
            "Obs": n,
            "Interpretation": "Primary leads peer" if lag > 0 else "Peer leads primary" if lag < 0 else "Synchronous",
        })
    out = pd.DataFrame(rows)
    out["Abs correlation"] = out["Correlation"].abs()
    out["CI low"] = np.nan
    out["CI high"] = np.nan
    out["Selection-adjusted p"] = np.nan
    out["Evidence"] = ""
    out["Inference reps"] = 0

    nz = out[(out["Lag days"] != 0) & out["Correlation"].notna()]
    if nz.empty:
        return out
    selected_idx = nz["Abs correlation"].idxmax()
    selected_lag = int(out.loc[selected_idx, "Lag days"])
    observed_max = float(out.loc[selected_idx, "Abs correlation"])

    rng = np.random.default_rng(cfg.random_seed + 2718)
    # Fixed-selected-lag uncertainty under the observed temporal process.
    boots: list[float] = []
    for _ in range(int(cfg.lead_lag_bootstrap_samples)):
        ix = _moving_block_indices(len(frame), cfg.lead_lag_block_length, rng)
        c, _ = _lag_corr(a[ix], b[ix], selected_lag, max(20, min_obs // 2))
        if np.isfinite(c):
            boots.append(float(c))
    lo, hi, valid = _quantile_ci(boots, cfg.lead_lag_ci_level)

    # Max-stat null: preserve same-day pair distribution but destroy temporal ordering.
    null_max: list[float] = []
    base = np.column_stack([a, b])
    for _ in range(int(cfg.lead_lag_bootstrap_samples)):
        perm = rng.permutation(len(base))
        p = base[perm]
        vals = []
        for lag in range(-max_lag, max_lag + 1):
            if lag == 0:
                continue
            c, _ = _lag_corr(p[:, 0], p[:, 1], lag, max(20, min_obs // 2))
            if np.isfinite(c):
                vals.append(abs(float(c)))
        if vals:
            null_max.append(max(vals))
    if null_max:
        p_adj = float((1 + np.sum(np.asarray(null_max) >= observed_max)) / (len(null_max) + 1))
    else:
        p_adj = np.nan

    excludes_zero = np.isfinite(lo) and np.isfinite(hi) and (lo > 0 or hi < 0)
    if np.isfinite(p_adj) and p_adj <= cfg.lead_lag_support_alpha and excludes_zero:
        evidence = "Supported"
    elif np.isfinite(p_adj) and p_adj <= cfg.lead_lag_weak_alpha:
        evidence = "Weak"
    else:
        evidence = "Not supported"

    out.loc[selected_idx, "CI low"] = lo
    out.loc[selected_idx, "CI high"] = hi
    out.loc[selected_idx, "Selection-adjusted p"] = p_adj
    out.loc[selected_idx, "Evidence"] = evidence
    out.loc[selected_idx, "Inference reps"] = min(valid, len(null_max)) if null_max else valid
    return out


def _robust_z(s: pd.Series) -> pd.Series:
    x = pd.to_numeric(s, errors="coerce")
    med = float(x.median())
    mad = float((x - med).abs().median())
    if np.isfinite(mad) and mad > 1e-12:
        scale = 1.4826 * mad
    else:
        scale = float(x.std(ddof=1))
    if not np.isfinite(scale) or scale <= 1e-12:
        return x * np.nan
    return (x - med) / scale


def _bootstrap_corr(frame: pd.DataFrame, samples: int, seed: int, level: float) -> tuple[float, float, int]:
    if frame is None or len(frame) < 4:
        return np.nan, np.nan, 0
    arr = frame.iloc[:, :2].to_numpy(float)
    rng = np.random.default_rng(seed)
    vals: list[float] = []
    for _ in range(int(samples)):
        ix = rng.integers(0, len(arr), size=len(arr))
        c = _safe_corr(arr[ix, 0], arr[ix, 1])
        if np.isfinite(c):
            vals.append(float(c))
    return _quantile_ci(vals, level)


def extreme_move_dependency(
    primary: str,
    peer: str,
    changes: pd.DataFrame,
    z_threshold: float = 3.0,
    min_obs: int = 30,
    cfg: DependencyConfig | None = None,
) -> pd.DataFrame:
    """Daily extreme-move overlap with small-sample uncertainty.

    This is intentionally *not* called a jump test. Daily close-to-close returns cannot
    separate the continuous semimartingale component from intraday jumps. Conditional
    probabilities receive Wilson intervals; correlation estimates receive bootstrap
    intervals and an explicit sample-quality label.
    """
    if primary not in changes.columns or peer not in changes.columns:
        return pd.DataFrame()
    cfg = cfg or DependencyConfig(min_pair_obs=min_obs, extreme_z_threshold=z_threshold)
    frame = pd.concat([
        pd.to_numeric(changes[primary], errors="coerce").rename("a"),
        pd.to_numeric(changes[peer], errors="coerce").rename("b"),
    ], axis=1).dropna()
    if len(frame) < min_obs:
        return pd.DataFrame()
    za, zb = _robust_z(frame["a"]), _robust_z(frame["b"])
    ea, eb = za.abs() >= z_threshold, zb.abs() >= z_threshold
    co = ea & eb
    ordinary = ~(ea | eb)
    same = np.sign(frame.loc[co, "a"]) == np.sign(frame.loc[co, "b"])
    n_a, n_b, n_co, n_ord = int(ea.sum()), int(eb.sum()), int(co.sum()), int(ordinary.sum())

    p_b_a = float(n_co / n_a) if n_a else np.nan
    p_a_b = float(n_co / n_b) if n_b else np.nan
    p_same = float(same.mean()) if len(same) else np.nan
    ci_b_a = _wilson_interval(n_co, n_a, cfg.extreme_ci_level)
    ci_a_b = _wilson_interval(n_co, n_b, cfg.extreme_ci_level)
    ci_same = _wilson_interval(int(same.sum()), n_co, cfg.extreme_ci_level)

    extreme_frame = frame.loc[co, ["a", "b"]]
    ordinary_frame = frame.loc[ordinary, ["a", "b"]]
    extreme_corr = _safe_corr(extreme_frame["a"], extreme_frame["b"]) if n_co >= 4 else np.nan
    ordinary_corr = _safe_corr(ordinary_frame["a"], ordinary_frame["b"]) if n_ord >= 10 else np.nan
    eco_lo, eco_hi, eco_valid = _bootstrap_corr(extreme_frame, cfg.extreme_bootstrap_samples, cfg.random_seed + 31, cfg.extreme_ci_level)
    ord_lo, ord_hi, ord_valid = _bootstrap_corr(ordinary_frame, cfg.extreme_bootstrap_samples, cfg.random_seed + 37, cfg.extreme_ci_level)

    def row(metric: str, value: float | int, lo=np.nan, hi=np.nan, n_eff: int = 0, reps: int = 0):
        return {
            "Metric": metric,
            "Value": value,
            "CI low": lo,
            "CI high": hi,
            "N effective": int(n_eff),
            "Quality": _sample_quality(int(n_eff)),
            "Inference reps": int(reps),
        }

    rows = [
        row("Primary extreme observations", n_a, n_eff=n_a),
        row("Peer extreme observations", n_b, n_eff=n_b),
        row("Co-extreme observations", n_co, n_eff=n_co),
        row("P(peer extreme | primary extreme)", p_b_a, *ci_b_a, n_eff=n_a),
        row("P(primary extreme | peer extreme)", p_a_b, *ci_a_b, n_eff=n_b),
        row("Same-direction co-extremes", p_same, *ci_same, n_eff=n_co),
        row("Non-extreme-day correlation", ordinary_corr, ord_lo, ord_hi, n_eff=n_ord, reps=ord_valid),
        row("Co-extreme-day correlation", extreme_corr, eco_lo, eco_hi, n_eff=n_co, reps=eco_valid),
    ]
    return pd.DataFrame(rows)


def jump_dependency(primary: str, peer: str, changes: pd.DataFrame, z_threshold: float = 3.0, min_obs: int = 30) -> pd.DataFrame:
    """Backward-compatible alias for the V4.0 API; no jump-process claim is made."""
    return extreme_move_dependency(primary, peer, changes, z_threshold=z_threshold, min_obs=min_obs)


def _higher_stats(arr: np.ndarray) -> np.ndarray:
    a, b = arr[:, 0], arr[:, 1]
    sa, sb = np.std(a, ddof=1), np.std(b, ddof=1)
    if not np.isfinite(sa) or not np.isfinite(sb) or sa <= 1e-14 or sb <= 1e-14:
        return np.full(4, np.nan)
    za = (a - np.mean(a)) / sa
    zb = (b - np.mean(b)) / sb
    return np.array([
        float(np.mean(za * zb)),
        float(np.mean((za ** 2) * zb)),
        float(np.mean(za * (zb ** 2))),
        float(np.mean((za ** 2) * (zb ** 2)) - 1.0),
    ])


def higher_moment_dependency(
    primary: str,
    peer: str,
    changes: pd.DataFrame,
    min_obs: int = 60,
    cfg: DependencyConfig | None = None,
) -> pd.DataFrame:
    if primary not in changes.columns or peer not in changes.columns:
        return pd.DataFrame()
    cfg = cfg or DependencyConfig(min_pair_obs=min_obs)
    x = pd.concat([
        pd.to_numeric(changes[primary], errors="coerce").rename("a"),
        pd.to_numeric(changes[peer], errors="coerce").rename("b"),
    ], axis=1).dropna()
    if len(x) < min_obs:
        return pd.DataFrame()
    arr = x.to_numpy(float)
    point = _higher_stats(arr)
    rng = np.random.default_rng(cfg.random_seed + 811)
    boots: list[np.ndarray] = []
    for _ in range(int(cfg.higher_moment_bootstrap_samples)):
        ix = _moving_block_indices(len(arr), cfg.higher_moment_block_length, rng)
        stat = _higher_stats(arr[ix])
        if np.all(np.isfinite(stat)):
            boots.append(stat)
    boot = np.asarray(boots) if boots else np.empty((0, 4))
    labels = [
        ("Corr (2nd moment)", "Linear second-moment dependence"),
        ("Coskew primary²×peer", "Whether peer tends to move with large absolute primary moves"),
        ("Coskew primary×peer²", "Whether primary tends to move with large absolute peer moves"),
        ("Excess co-kurtosis 2×2", "Joint volatility clustering beyond independence baseline"),
    ]
    rows = []
    alpha = 1.0 - cfg.higher_moment_ci_level
    for j, (name, interp) in enumerate(labels):
        vals = boot[:, j] if boot.size else np.array([])
        vals = vals[np.isfinite(vals)]
        if len(vals):
            lo = float(np.quantile(vals, alpha / 2))
            hi = float(np.quantile(vals, 1 - alpha / 2))
            if point[j] >= 0:
                stability = float(np.mean(vals > 0))
            else:
                stability = float(np.mean(vals < 0))
        else:
            lo = hi = stability = np.nan
        excludes_zero = np.isfinite(lo) and np.isfinite(hi) and (lo > 0 or hi < 0)
        if len(vals) < 100:
            evidence = "Fragile"
        elif excludes_zero and np.isfinite(stability) and stability >= 0.90:
            evidence = "Supported"
        else:
            evidence = "Inconclusive"
        rows.append({
            "Metric": name,
            "Value": float(point[j]),
            "CI low": lo,
            "CI high": hi,
            "Sign stability": stability,
            "Evidence": evidence,
            "Obs": len(x),
            "Bootstrap reps": len(vals),
            "Interpretation": interp,
        })
    return pd.DataFrame(rows)


def liquidity_dependency(primary: str, peer: str, inputs: ForceInputs, min_obs: int = 40) -> pd.DataFrame:
    rows = []
    for metric, df in inputs.liquidity.items():
        if primary not in df.columns or peer not in df.columns:
            continue
        x = pd.concat([pd.to_numeric(df[primary], errors="coerce"), pd.to_numeric(df[peer], errors="coerce")], axis=1).dropna()
        if len(x) < min_obs:
            continue
        level_corr = float(x.iloc[:, 0].corr(x.iloc[:, 1]))
        d = x.diff().dropna()
        change_corr = float(d.iloc[:, 0].corr(d.iloc[:, 1])) if len(d) >= min_obs else np.nan
        rows.append({"Liquidity metric": metric, "Level commonality": level_corr, "Change commonality": change_corr, "Obs": len(x)})
    return pd.DataFrame(rows)


def economic_context(primary: str, peer: str, changes: pd.DataFrame, inputs: ForceInputs,
                     portfolio_weights: dict[str, float] | None = None) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    pa = inputs.asset_metadata.get(primary, {}) if isinstance(inputs.asset_metadata, dict) else {}
    pb = inputs.asset_metadata.get(peer, {}) if isinstance(inputs.asset_metadata, dict) else {}
    keys = [
        ("currency", "Currency"), ("region", "Region"), ("country", "Country"), ("sector", "Sector"),
        ("market_cap", "Market cap"), ("enterprise_value", "Enterprise value"), ("index_weight", "Index weight"), ("adv_usd", "ADV USD"),
        ("debt_to_equity", "Debt / equity"), ("total_debt", "Total debt"), ("short_percent_float", "Short % float"),
        ("beta", "Vendor beta"), ("benchmark", "Benchmark"), ("duration", "Duration"), ("dv01", "DV01"), ("cs01", "CS01"),
    ]
    for key, label in keys:
        if key in pa or key in pb:
            rows.append({"Dimension": label, primary: pa.get(key), peer: pb.get(key), "Interpretation": "Metadata context; not folded into a universal score."})

    if portfolio_weights and primary in portfolio_weights and peer in portfolio_weights:
        x = pd.concat([changes[primary], changes[peer]], axis=1).dropna()
        if len(x) >= 30:
            cov = float(np.cov(x.iloc[:, 0], x.iloc[:, 1], ddof=1)[0, 1])
            pair_var_contrib = 2.0 * float(portfolio_weights[primary]) * float(portfolio_weights[peer]) * cov * 252.0
            rows.append({"Dimension": "Portfolio pair variance contribution", primary: pair_var_contrib, peer: pair_var_contrib,
                         "Interpretation": "Exact annualized cross-term 2 w_i w_j Cov(i,j); can be negative."})

    if not inputs.ownership_matrix.empty and primary in inputs.ownership_matrix.index and peer in inputs.ownership_matrix.columns:
        val = inputs.ownership_matrix.loc[primary, peer]
        rows.append({"Dimension": "Ownership overlap", primary: val, peer: val,
                     "Interpretation": "Injected/common disclosed-ownership overlap measure; scale defined by the upstream dataset."})

    if not inputs.relationship_table.empty:
        cols = {str(c).lower(): c for c in inputs.relationship_table.columns}
        a_col = cols.get("from") or cols.get("asset_a") or cols.get("source")
        b_col = cols.get("to") or cols.get("asset_b") or cols.get("target")
        if a_col is not None and b_col is not None:
            rel = inputs.relationship_table[
                ((inputs.relationship_table[a_col].astype(str).str.upper() == primary.upper()) & (inputs.relationship_table[b_col].astype(str).str.upper() == peer.upper())) |
                ((inputs.relationship_table[a_col].astype(str).str.upper() == peer.upper()) & (inputs.relationship_table[b_col].astype(str).str.upper() == primary.upper()))
            ]
            if not rel.empty:
                rows.append({"Dimension": "Structural relationship", primary: str(rel.iloc[0].to_dict()), peer: "",
                             "Interpretation": "Injected supply-chain / ownership / legal / benchmark relationship."})
    return pd.DataFrame(rows)


def event_dependency_attribution(primary: str, peer: str, changes: pd.DataFrame, inputs: ForceInputs,
                                 cfg: DependencyConfig | None = None) -> pd.DataFrame:
    cfg = cfg or DependencyConfig()
    ev = inputs.events
    if ev.empty or "Date" not in ev.columns or primary not in changes.columns or peer not in changes.columns:
        return pd.DataFrame()
    pair = pd.concat([changes[primary], changes[peer]], axis=1).dropna().sort_index()
    rows = []
    for _, row in ev.iterrows():
        dt = pd.Timestamp(row["Date"])
        before = pair.loc[pair.index < dt].tail(cfg.event_side_window)
        after = pair.loc[pair.index >= dt].head(cfg.event_side_window)
        if len(before) < cfg.event_min_obs_side or len(after) < cfg.event_min_obs_side:
            continue
        pre = float(before.iloc[:, 0].corr(before.iloc[:, 1]))
        post = float(after.iloc[:, 0].corr(after.iloc[:, 1]))
        if not np.isfinite(pre) or not np.isfinite(post):
            continue
        rows.append({
            "Date": dt,
            "Force": row.get("Force", row.get("Event", "Event")),
            "Mechanism": row.get("Mechanism", row.get("Category", "Event")),
            "Label": row.get("Label", row.get("Description", "")),
            "Surprise": row.get("Surprise", np.nan),
            "Pre corr": pre,
            "Post corr": post,
            "Δ corr": post - pre,
        })
    detail = pd.DataFrame(rows)
    if detail.empty:
        return detail
    agg = detail.groupby(["Mechanism", "Force"], dropna=False).agg(
        Events=("Δ corr", "size"),
        **{"Median Δ corr": ("Δ corr", "median"), "Mean Δ corr": ("Δ corr", "mean"), "Mean pre corr": ("Pre corr", "mean"), "Mean post corr": ("Post corr", "mean")},
    ).reset_index()
    agg["Identification"] = "Event-window association; not causal"
    return agg.sort_values("Median Δ corr", key=lambda s: s.abs(), ascending=False).reset_index(drop=True)
