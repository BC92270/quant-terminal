from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from math import factorial, sqrt
from typing import Any

import numpy as np
import pandas as pd

from .config import DependencyConfig


@dataclass
class ForceModelResult:
    status: str = "unavailable"
    obs: int = 0
    factors_used: list[str] = field(default_factory=list)
    factors_dropped: list[str] = field(default_factory=list)
    raw_corr: float | None = None
    residual_corr: float | None = None
    raw_cov: float | None = None
    systematic_cov: float | None = None
    residual_cov: float | None = None
    reconstruction_error: float | None = None
    systematic_share_of_observed: float | None = None
    primary_r2: float | None = None
    peer_r2: float | None = None
    betas_primary: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    betas_peer: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    residual_primary: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    residual_peer: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    group_attribution: pd.DataFrame = field(default_factory=pd.DataFrame)
    shapley_bridge: pd.DataFrame = field(default_factory=pd.DataFrame)
    factor_diagnostics: pd.DataFrame = field(default_factory=pd.DataFrame)
    selection_diagnostics: pd.DataFrame = field(default_factory=pd.DataFrame)
    meta: dict[str, Any] = field(default_factory=dict)


def _safe_corr(a: np.ndarray, b: np.ndarray) -> float | None:
    if len(a) < 3:
        return None
    c = np.corrcoef(a, b)[0, 1]
    return float(c) if np.isfinite(c) else None


def _standardize_df(df: pd.DataFrame, min_std: float) -> tuple[pd.DataFrame, dict[str, float], dict[str, float]]:
    means, stds = {}, {}
    out = pd.DataFrame(index=df.index)
    for c in df.columns:
        x = pd.to_numeric(df[c], errors="coerce")
        mu = float(x.mean())
        sd = float(x.std(ddof=1))
        if not np.isfinite(sd) or sd <= min_std:
            continue
        out[c] = (x - mu) / sd
        means[c], stds[c] = mu, sd
    return out, means, stds


def _factor_screen_table(y1: pd.Series, y2: pd.Series, factors: pd.DataFrame,
                         metadata: dict[str, dict[str, Any]], cfg: DependencyConfig) -> pd.DataFrame:
    """Transparent stability-aware screen before the collinearity/family guard.

    This is not a causal selector. It penalizes sparse or temporally unstable correlations so
    a wide force registry is less likely to promote one-off full-sample relationships.
    """
    rows: list[dict[str, Any]] = []
    base_n = max(int(pd.concat([y1, y2], axis=1).dropna().shape[0]), 1)
    for c in factors.columns:
        x = pd.to_numeric(factors[c], errors="coerce")
        tmp = pd.concat([y1.rename("y1"), y2.rename("y2"), x.rename("x")], axis=1).dropna()
        if len(tmp) < cfg.min_pair_obs:
            continue
        c1 = float(tmp["y1"].corr(tmp["x"]))
        c2 = float(tmp["y2"].corr(tmp["x"]))
        rel = max(abs(c1) if np.isfinite(c1) else 0.0, abs(c2) if np.isfinite(c2) else 0.0)
        if rel < cfg.factor_min_relevance:
            stability = 0.0
            valid_windows = 0
        else:
            signs: list[float] = []
            magnitudes: list[float] = []
            valid_windows = 0
            for w in cfg.factor_stability_windows:
                if len(tmp) < max(cfg.min_pair_obs, int(w)):
                    continue
                tw = tmp.tail(int(w))
                wc1 = float(tw["y1"].corr(tw["x"]))
                wc2 = float(tw["y2"].corr(tw["x"]))
                pair = [(wc1, c1), (wc2, c2)]
                for wc, full in pair:
                    if np.isfinite(wc) and np.isfinite(full) and abs(full) > 1e-12:
                        signs.append(1.0 if np.sign(wc) == np.sign(full) else 0.0)
                        magnitudes.append(min(abs(wc) / max(abs(full), 1e-12), 1.0))
                valid_windows += 1
            if valid_windows < cfg.factor_stability_min_windows or not signs:
                stability = 0.5  # neutral penalty when history cannot support the full stability grid
            else:
                stability = 0.7 * float(np.mean(signs)) + 0.3 * float(np.mean(magnitudes))
        coverage = min(float(len(tmp)) / float(base_n), 1.0)
        score = rel * sqrt(max(coverage, 0.0)) * (0.5 + 0.5 * stability)
        rows.append({
            "Force": c, "Mechanism": metadata.get(c, {}).get("mechanism", "Custom"),
            "Family": metadata.get(c, {}).get("family", "Custom"),
            "Primary abs corr": abs(c1) if np.isfinite(c1) else np.nan,
            "Peer abs corr": abs(c2) if np.isfinite(c2) else np.nan,
            "Relevance": rel, "Coverage": coverage, "Temporal stability": stability,
            "Valid stability windows": valid_windows, "Selection score": score, "Obs": len(tmp),
        })
    out = pd.DataFrame(rows)
    return out.sort_values(["Selection score", "Relevance"], ascending=False).reset_index(drop=True) if not out.empty else out


def _select_factors(y1: pd.Series, y2: pd.Series, factors: pd.DataFrame, metadata: dict[str, dict[str, Any]], cfg: DependencyConfig) -> tuple[list[str], list[str], pd.DataFrame]:
    """Stability-aware screen followed by family caps and a collinearity guard."""
    screen = _factor_screen_table(y1, y2, factors, metadata, cfg)
    if screen.empty:
        return [], [], screen

    selected: list[str] = []
    dropped: list[str] = []
    reasons: dict[str, str] = {}
    family_count: dict[str, int] = {}
    for _, row in screen.iterrows():
        c = str(row["Force"])
        if float(row["Relevance"]) < cfg.factor_min_relevance:
            dropped.append(c); reasons[c] = "below relevance floor"; continue
        family = str(metadata.get(c, {}).get("family", "Custom"))
        if family_count.get(family, 0) >= cfg.max_factors_per_family:
            dropped.append(c); reasons[c] = "family cap"; continue
        reject = False
        for chosen in selected:
            pair = pd.concat([factors[c], factors[chosen]], axis=1).dropna()
            if len(pair) >= cfg.min_pair_obs:
                cc = pair.iloc[:, 0].corr(pair.iloc[:, 1])
                if np.isfinite(cc) and abs(float(cc)) >= cfg.collinearity_threshold:
                    reject = True
                    reasons[c] = f"collinear with {chosen}"
                    break
        if reject:
            dropped.append(c)
            continue
        if len(selected) >= cfg.max_factors:
            dropped.append(c); reasons[c] = "max factor cap"; continue
        selected.append(c)
        reasons[c] = "selected"
        family_count[family] = family_count.get(family, 0) + 1

    for c in screen["Force"].astype(str):
        if c not in selected and c not in dropped:
            dropped.append(c); reasons[c] = "not selected"
    screen = screen.copy()
    screen["Selection status"] = screen["Force"].astype(str).map(reasons).fillna("not selected")
    return selected, dropped, screen


def _ols_residual(y: np.ndarray, X: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    X1 = np.column_stack([np.ones(len(X)), X])
    beta = np.linalg.lstsq(X1, y, rcond=None)[0]
    fit = X1 @ beta
    resid = y - fit
    sst = float(np.sum((y - np.mean(y)) ** 2))
    r2 = 1.0 - float(np.sum(resid ** 2)) / sst if sst > 0 else np.nan
    return beta[1:], resid, r2


def _residual_corr_for_groups(y1: pd.Series, y2: pd.Series, X: pd.DataFrame, groups: dict[str, list[str]], subset: set[str]) -> float:
    cols = [c for g in subset for c in groups[g] if c in X.columns]
    frame = pd.concat([y1.rename("y1"), y2.rename("y2"), X[cols]], axis=1).dropna()
    if len(frame) < max(30, len(cols) + 10):
        return np.nan
    a, b = frame["y1"].to_numpy(float), frame["y2"].to_numpy(float)
    if not cols:
        return float(np.corrcoef(a, b)[0, 1])
    xx = frame[cols].to_numpy(float)
    _, ra, _ = _ols_residual(a, xx)
    _, rb, _ = _ols_residual(b, xx)
    return float(np.corrcoef(ra, rb)[0, 1])


def _shapley_bridge(y1: pd.Series, y2: pd.Series, X: pd.DataFrame, metadata: dict[str, dict[str, Any]], cfg: DependencyConfig) -> pd.DataFrame:
    groups: dict[str, list[str]] = {}
    for c in X.columns:
        g = str(metadata.get(c, {}).get("mechanism", "Custom"))
        groups.setdefault(g, []).append(c)
    names = list(groups)
    G = len(names)
    if G == 0:
        return pd.DataFrame()

    raw = _residual_corr_for_groups(y1, y2, X, groups, set())
    full = _residual_corr_for_groups(y1, y2, X, groups, set(names))
    if not np.isfinite(raw) or not np.isfinite(full):
        return pd.DataFrame()

    contrib = {g: 0.0 for g in names}
    rng = np.random.default_rng(cfg.random_seed)

    if G <= cfg.exact_shapley_max_groups:
        # Shapley value of v(S)=raw_corr-residual_corr(S). Exact over mechanism coalitions.
        cache: dict[frozenset[str], float] = {}
        for r in range(G + 1):
            for combo in combinations(names, r):
                S = frozenset(combo)
                c = _residual_corr_for_groups(y1, y2, X, groups, set(S))
                cache[S] = raw - c if np.isfinite(c) else np.nan
        for g in names:
            others = [x for x in names if x != g]
            for r in range(G):
                for combo in combinations(others, r):
                    S = frozenset(combo)
                    vS, vSg = cache.get(S), cache.get(S | {g})
                    if not np.isfinite(vS) or not np.isfinite(vSg):
                        continue
                    w = factorial(r) * factorial(G - r - 1) / factorial(G)
                    contrib[g] += w * (vSg - vS)
    else:
        # Monte Carlo permutations preserve the Shapley interpretation for wider registries.
        counts = {g: 0 for g in names}
        for _ in range(cfg.shapley_permutations):
            perm = list(rng.permutation(names))
            S: set[str] = set()
            prev = 0.0
            for g in perm:
                c = _residual_corr_for_groups(y1, y2, X, groups, S | {g})
                if not np.isfinite(c):
                    S.add(g)
                    continue
                v = raw - c
                contrib[g] += v - prev
                counts[g] += 1
                prev = v
                S.add(g)
        for g in names:
            if counts[g] > 0:
                contrib[g] /= counts[g]

    rows = [{"Mechanism": g, "Correlation contribution": contrib[g], "Factors": ", ".join(groups[g])} for g in names]
    rows.append({"Mechanism": "Residual dependency", "Correlation contribution": full, "Factors": "Unexplained after active force set"})
    out = pd.DataFrame(rows)
    out["Absolute magnitude"] = out["Correlation contribution"].abs()
    return out.sort_values("Absolute magnitude", ascending=False).reset_index(drop=True)


def fit_force_model(primary: str, peer: str, changes: pd.DataFrame, force_series: pd.DataFrame,
                    metadata: dict[str, dict[str, Any]], cfg: DependencyConfig | None = None) -> ForceModelResult:
    cfg = cfg or DependencyConfig()
    res = ForceModelResult()
    if primary not in changes.columns or peer not in changes.columns or force_series.empty:
        return res

    y1 = pd.to_numeric(changes[primary], errors="coerce").rename("primary")
    y2 = pd.to_numeric(changes[peer], errors="coerce").rename("peer")
    selected, dropped, selection_diag = _select_factors(y1, y2, force_series, metadata, cfg)
    if not selected:
        res.selection_diagnostics = selection_diag
        res.meta = {"reason": "No factor passed minimum observations/relevance filters"}
        return res

    Xz, _, _ = _standardize_df(force_series[selected], cfg.min_factor_std)
    selected = [c for c in selected if c in Xz.columns]
    frame = pd.concat([y1, y2, Xz[selected]], axis=1).dropna()
    if len(frame) < max(cfg.min_pair_obs, len(selected) + 15):
        res.meta = {"reason": "Insufficient common observations", "common_obs": len(frame)}
        return res

    a = frame["primary"].to_numpy(float)
    b = frame["peer"].to_numpy(float)
    X = frame[selected].to_numpy(float)
    beta_a, resid_a, r2a = _ols_residual(a, X)
    beta_b, resid_b, r2b = _ols_residual(b, X)

    cov_f = np.cov(X, rowvar=False, ddof=1)
    if np.ndim(cov_f) == 0:
        cov_f = np.array([[float(cov_f)]])
    sys_cov = float(beta_a @ cov_f @ beta_b)
    resid_cov = float(np.cov(resid_a, resid_b, ddof=1)[0, 1])
    raw_cov = float(np.cov(a, b, ddof=1)[0, 1])
    recon = sys_cov + resid_cov
    raw_corr = _safe_corr(a, b)
    residual_corr = _safe_corr(resid_a, resid_b)

    beta_a_s = pd.Series(beta_a, index=selected, name="Primary beta (per 1σ force)")
    beta_b_s = pd.Series(beta_b, index=selected, name="Peer beta (per 1σ force)")

    # Exact group allocation of systematic covariance. Cross-group covariance terms are
    # split equally between the two groups, so contributions sum exactly to sys_cov.
    M = np.outer(beta_a, beta_b) * cov_f
    group_names = [str(metadata.get(c, {}).get("mechanism", "Custom")) for c in selected]
    unique_groups = list(dict.fromkeys(group_names))
    grows = []
    for g in unique_groups:
        idx = [i for i, gg in enumerate(group_names) if gg == g]
        other = [i for i in range(len(selected)) if i not in idx]
        within = float(M[np.ix_(idx, idx)].sum()) if idx else 0.0
        cross_out = float(M[np.ix_(idx, other)].sum()) if idx and other else 0.0
        cross_in = float(M[np.ix_(other, idx)].sum()) if idx and other else 0.0
        contribution = within + 0.5 * (cross_out + cross_in)
        factors_g = [selected[i] for i in idx]
        grows.append({
            "Mechanism": g,
            "Systematic covariance contribution": contribution,
            "% of systematic covariance": contribution / sys_cov if abs(sys_cov) > 1e-14 else np.nan,
            "Primary beta norm": float(np.linalg.norm(beta_a[idx])) if idx else 0.0,
            "Peer beta norm": float(np.linalg.norm(beta_b[idx])) if idx else 0.0,
            "Factors": ", ".join(factors_g),
        })
    group_df = pd.DataFrame(grows)
    if not group_df.empty:
        group_df["Absolute magnitude"] = group_df["Systematic covariance contribution"].abs()
        group_df = group_df.sort_values("Absolute magnitude", ascending=False).reset_index(drop=True)

    diagnostics = []
    for c in selected:
        ma = metadata.get(c, {})
        diagnostics.append({
            "Force": c,
            "Mechanism": ma.get("mechanism", "Custom"),
            "Family": ma.get("family", "Custom"),
            "Primary beta (1σ)": beta_a_s[c],
            "Peer beta (1σ)": beta_b_s[c],
            "Identification": ma.get("identification", "Associational"),
            "Source": ma.get("source", "Injected"),
        })
    diag_df = pd.DataFrame(diagnostics)
    if not diag_df.empty:
        diag_df["Joint beta magnitude"] = np.sqrt(diag_df["Primary beta (1σ)"] ** 2 + diag_df["Peer beta (1σ)"] ** 2)
        diag_df = diag_df.sort_values("Joint beta magnitude", ascending=False).reset_index(drop=True)

    residual_a_s = pd.Series(resid_a, index=frame.index, name=primary)
    residual_b_s = pd.Series(resid_b, index=frame.index, name=peer)
    shapley = _shapley_bridge(frame["primary"], frame["peer"], frame[selected], metadata, cfg)

    res.status = "ok"
    res.obs = len(frame)
    res.factors_used = selected
    res.factors_dropped = dropped
    res.raw_corr = raw_corr
    res.residual_corr = residual_corr
    res.raw_cov = raw_cov
    res.systematic_cov = sys_cov
    res.residual_cov = resid_cov
    res.reconstruction_error = recon - raw_cov
    res.systematic_share_of_observed = sys_cov / raw_cov if abs(raw_cov) > 1e-14 else None
    res.primary_r2 = float(r2a) if np.isfinite(r2a) else None
    res.peer_r2 = float(r2b) if np.isfinite(r2b) else None
    res.betas_primary = beta_a_s
    res.betas_peer = beta_b_s
    res.residual_primary = residual_a_s
    res.residual_peer = residual_b_s
    res.group_attribution = group_df
    res.shapley_bridge = shapley
    res.factor_diagnostics = diag_df
    res.selection_diagnostics = selection_diag
    res.meta = {
        "association_only": True,
        "causal_claim": False,
        "selected_factor_count": len(selected),
        "dropped_factor_count": len(dropped),
        "group_count": len(unique_groups),
        "reconstruction_covariance": recon,
        "selection_method": "stability-aware relevance + family cap + collinearity guard",
    }
    return res
