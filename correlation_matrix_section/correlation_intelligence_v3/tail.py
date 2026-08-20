from __future__ import annotations

import math
import numpy as np
import pandas as pd
from scipy import stats
from scipy.optimize import minimize, minimize_scalar

from .estimators import pair_frame
from .utils import safe_float


def rank_uniform(series: pd.Series) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce")
    n = int(s.notna().sum())
    if n == 0:
        return pd.Series(index=s.index, dtype=float)
    return s.rank(method="average") / (n + 1.0)


def wilson_interval(successes: int, n: int, z: float = 1.959963984540054) -> tuple[float | None, float | None]:
    if n <= 0:
        return None, None
    p = successes / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, center - half), min(1.0, center + half)




def tail_evidence_score(metrics: dict, target_tail_obs: int = 20) -> tuple[float, str, str]:
    """Evidence score: rewards repeatable lower-tail dependence and penalizes wide uncertainty / contradictory stress behavior.

    This is intentionally an evidence score, not a probability and not a trading signal.
    """
    ll = safe_float(metrics.get("Emp lower co-exceedance"), 0.0) or 0.0
    lower_corr = safe_float(metrics.get("Lower tail corr"), 0.0) or 0.0
    stress_lift = safe_float(metrics.get("Stress lift"), 0.0) or 0.0
    lo = safe_float(metrics.get("Lower CI low"), 0.0) or 0.0
    hi = safe_float(metrics.get("Lower CI high"), 1.0) or 1.0
    tail_n = int(metrics.get("Lower tail obs") or 0)
    cotail_n = int(metrics.get("Lower co-tail obs") or 0)

    ci_width = max(0.0, min(1.0, hi - lo))
    sample_factor = min(1.0, tail_n / max(target_tail_obs, 1))
    cotail_factor = min(1.0, cotail_n / max(target_tail_obs * 0.40, 1.0))
    precision_factor = max(0.0, 1.0 - ci_width)
    quality_factor = 0.45 * sample_factor + 0.35 * precision_factor + 0.20 * cotail_factor

    structural = (
        0.45 * max(ll, 0.0)
        + 0.30 * max(lower_corr, 0.0)
        + 0.25 * min(max(stress_lift, 0.0) / 0.25, 1.0)
    )
    contradiction = 0.25 * min(max(-stress_lift, 0.0) / 0.50, 1.0)
    score = 100.0 * max(0.0, structural - contradiction) * quality_factor
    score = float(max(0.0, min(100.0, score)))

    if tail_n < 10 or ci_width > 0.45:
        quality = "Fragile"
    elif tail_n < target_tail_obs or ci_width > 0.30:
        quality = "Limited"
    else:
        quality = "Adequate"

    if score >= 70:
        label = "Strong"
    elif score >= 50:
        label = "Moderate"
    elif score >= 30:
        label = "Limited"
    else:
        label = "Inconclusive"
    return score, label, quality

def empirical_tail_metrics(primary: str, peer: str, changes: pd.DataFrame, days: int, q: float = 0.10, target_tail_obs: int = 20) -> dict:
    df = pair_frame(changes, primary, peer, days)
    out = {"Ticker": peer, "Obs": len(df)}
    if len(df) < 40:
        out.update({"status": "insufficient_data"})
        return out
    u, v = rank_uniform(df[primary]), rank_uniform(df[peer])
    uv = pd.concat([u.rename("u"), v.rename("v"), df], axis=1).dropna()
    lower = uv["u"] <= q
    upper = uv["u"] >= 1 - q
    lower_peer = uv["v"] <= q
    upper_peer = uv["v"] >= 1 - q
    ln = int(lower.sum()); un = int(upper.sum())
    lc = int((lower & lower_peer).sum()); uc = int((upper & upper_peer).sum())
    ll = lc / ln if ln else None; lu = uc / un if un else None
    ll_lo, ll_hi = wilson_interval(lc, ln)
    lu_lo, lu_hi = wilson_interval(uc, un)
    lower_corr = safe_float(uv.loc[lower, [primary, peer]].corr().iloc[0, 1]) if ln >= 5 else None
    upper_corr = safe_float(uv.loc[upper, [primary, peer]].corr().iloc[0, 1]) if un >= 5 else None
    normal_corr = safe_float(uv[[primary, peer]].corr().iloc[0, 1])
    tau = safe_float(stats.kendalltau(uv[primary], uv[peer], variant="b").statistic)
    out.update({
        "status": "ok",
        "Emp lower co-exceedance": ll,
        "Lower CI low": ll_lo,
        "Lower CI high": ll_hi,
        "Emp upper co-exceedance": lu,
        "Upper CI low": lu_lo,
        "Upper CI high": lu_hi,
        "Lower tail corr": lower_corr,
        "Upper tail corr": upper_corr,
        "Normal corr": normal_corr,
        "Stress lift": (lower_corr - normal_corr) if lower_corr is not None and normal_corr is not None else None,
        "Kendall tau": tau,
        "Lower tail obs": ln,
        "Lower co-tail obs": lc,
        "Upper tail obs": un,
        "Upper co-tail obs": uc,
    })
    score, label, quality = tail_evidence_score(out, target_tail_obs=target_tail_obs)
    out["Tail evidence score"] = score
    out["Tail evidence"] = label
    out["Tail quality"] = quality
    out["Lower CI width"] = (ll_hi - ll_lo) if ll_lo is not None and ll_hi is not None else None
    return out


def _pseudo_obs(df: pd.DataFrame, a: str, b: str) -> np.ndarray:
    u = rank_uniform(df[a]).to_numpy(dtype=float)
    v = rank_uniform(df[b]).to_numpy(dtype=float)
    uv = np.column_stack([u, v])
    return np.clip(uv, 1e-6, 1 - 1e-6)


def _gaussian_copula_fit(uv: np.ndarray) -> dict:
    z = stats.norm.ppf(uv)
    rho = float(np.clip(np.corrcoef(z.T)[0, 1], -0.99, 0.99))
    det = 1 - rho * rho
    inv_minus_i = np.array([[1 / det - 1, -rho / det], [-rho / det, 1 / det - 1]])
    quad = np.einsum("ni,ij,nj->n", z, inv_minus_i, z)
    ll = float(np.sum(-0.5 * np.log(det) - 0.5 * quad))
    return {"Model": "Gaussian", "Param 1": rho, "Param 2": None, "LogLik": ll, "AIC": 2 - 2 * ll, "λL": 0.0, "λU": 0.0}


def _student_t_copula_fit(uv: np.ndarray) -> dict:
    def negll(theta):
        rho, nu = theta
        if abs(rho) >= 0.995 or nu <= 2.05 or nu > 80:
            return 1e12
        z = stats.t.ppf(uv, df=nu)
        shape = np.array([[1.0, rho], [rho, 1.0]])
        try:
            joint = stats.multivariate_t.logpdf(z, loc=np.zeros(2), shape=shape, df=nu)
            marg = stats.t.logpdf(z[:, 0], df=nu) + stats.t.logpdf(z[:, 1], df=nu)
            ll = np.sum(joint - marg)
            return -float(ll) if np.isfinite(ll) else 1e12
        except Exception:
            return 1e12
    res = minimize(negll, x0=[0.4, 8.0], bounds=[(-0.99, 0.99), (2.1, 80.0)], method="L-BFGS-B")
    rho, nu = res.x if res.success else (0.0, 8.0)
    ll = -negll((rho, nu))
    arg = -math.sqrt((nu + 1) * (1 - rho) / max(1 + rho, 1e-9))
    lam = float(2 * stats.t.cdf(arg, df=nu + 1))
    return {"Model": "Student-t", "Param 1": float(rho), "Param 2": float(nu), "LogLik": ll, "AIC": 4 - 2 * ll, "λL": lam, "λU": lam}


def _clayton_log_density(uv: np.ndarray, theta: float) -> np.ndarray:
    u, v = uv[:, 0], uv[:, 1]
    inner = u ** (-theta) + v ** (-theta) - 1
    return np.log1p(theta) + (-1 - theta) * (np.log(u) + np.log(v)) + (-2 - 1 / theta) * np.log(inner)


def _clayton_fit(uv: np.ndarray) -> dict:
    def negll(theta):
        if theta <= 1e-5:
            return 1e12
        vals = _clayton_log_density(uv, theta)
        return -float(np.sum(vals)) if np.isfinite(vals).all() else 1e12
    res = minimize_scalar(negll, bounds=(1e-4, 20.0), method="bounded")
    theta = float(res.x); ll = -negll(theta)
    lam_l = float(2 ** (-1 / theta))
    return {"Model": "Clayton", "Param 1": theta, "Param 2": None, "LogLik": ll, "AIC": 2 - 2 * ll, "λL": lam_l, "λU": 0.0}


def _gumbel_log_density(uv: np.ndarray, theta: float) -> np.ndarray:
    u, v = uv[:, 0], uv[:, 1]
    x, y = -np.log(u), -np.log(v)
    a = x ** theta + y ** theta
    c = np.exp(-(a ** (1 / theta)))
    term = (x * y) ** (theta - 1) / (u * v)
    bracket = a ** (2 / theta - 2) * (1 + (theta - 1) * a ** (-1 / theta))
    dens = c * term * bracket
    return np.log(np.clip(dens, 1e-300, None))


def _gumbel_fit(uv: np.ndarray) -> dict:
    def negll(theta):
        if theta < 1.0:
            return 1e12
        vals = _gumbel_log_density(uv, theta)
        return -float(np.sum(vals)) if np.isfinite(vals).all() else 1e12
    res = minimize_scalar(negll, bounds=(1.0001, 12.0), method="bounded")
    theta = float(res.x); ll = -negll(theta)
    lam_u = float(2 - 2 ** (1 / theta))
    return {"Model": "Gumbel", "Param 1": theta, "Param 2": None, "LogLik": ll, "AIC": 2 - 2 * ll, "λL": 0.0, "λU": lam_u}


def fit_copulas(primary: str, peer: str, changes: pd.DataFrame, days: int) -> pd.DataFrame:
    df = pair_frame(changes, primary, peer, days)
    if len(df) < 60:
        return pd.DataFrame()
    uv = _pseudo_obs(df, primary, peer)
    fits = []
    for fn in (_gaussian_copula_fit, _student_t_copula_fit, _clayton_fit, _gumbel_fit):
        try:
            fits.append(fn(uv))
        except Exception:
            continue
    if not fits:
        return pd.DataFrame()
    out = pd.DataFrame(fits).sort_values("AIC").reset_index(drop=True)
    out["ΔAIC"] = out["AIC"] - out["AIC"].min()
    return out


def resolve_tail_days(
    changes: pd.DataFrame,
    primary: str,
    peer: str,
    mode: str = "Adaptive",
    central_days: int = 90,
    q: float = 0.10,
    target_tail_obs: int = 30,
    max_days: int = 756,
) -> int:
    """Resolve a dedicated tail estimation horizon independent from the central correlation window."""
    available = len(pair_frame(changes, primary, peer, None))
    if available <= 0:
        return int(central_days)
    mode_norm = str(mode or "Adaptive").strip().lower()
    fixed = {
        "central": int(central_days),
        "1y": 252,
        "2y": 504,
        "3y": 756,
        "5y": 1260,
    }
    if mode_norm in fixed:
        return int(min(available, fixed[mode_norm]))
    required = int(math.ceil(max(target_tail_obs, 10) / max(float(q), 1e-6)))
    required = max(int(central_days), min(int(max_days), required))
    return int(min(available, required))


def adaptive_tail_metrics(
    primary: str,
    peer: str,
    changes: pd.DataFrame,
    central_days: int,
    mode: str = "Adaptive",
    q: float = 0.10,
    target_tail_obs: int = 30,
    max_days: int = 756,
) -> dict:
    days = resolve_tail_days(
        changes,
        primary,
        peer,
        mode=mode,
        central_days=central_days,
        q=q,
        target_tail_obs=target_tail_obs,
        max_days=max_days,
    )
    out = empirical_tail_metrics(primary, peer, changes, days, q=q, target_tail_obs=target_tail_obs)
    out["Tail horizon days"] = days
    out["Tail horizon mode"] = mode
    out["Tail target obs"] = target_tail_obs
    return out


def _moving_block_indices(n: int, block: int, rng: np.random.Generator) -> np.ndarray:
    if n <= 0:
        return np.array([], dtype=int)
    block = max(1, min(int(block), n))
    starts = rng.integers(0, max(1, n - block + 1), size=int(math.ceil(n / block)))
    idx = np.concatenate([np.arange(s, min(s + block, n)) for s in starts])
    if len(idx) < n:
        idx = np.resize(idx, n)
    return idx[:n]


def bootstrap_tail_uncertainty(
    primary: str,
    peer: str,
    changes: pd.DataFrame,
    days: int,
    q: float = 0.10,
    samples: int = 300,
    block: int = 5,
    seed: int = 42,
) -> dict:
    """Moving-block bootstrap intervals for tail co-exceedance, lower-tail corr and stress lift."""
    df = pair_frame(changes, primary, peer, days).dropna()
    if len(df) < 80:
        return {"status": "insufficient_data", "obs": int(len(df))}
    rng = np.random.default_rng(int(seed))
    metrics = {"coex": [], "lower_corr": [], "stress_lift": []}
    for _ in range(max(50, int(samples))):
        idx = _moving_block_indices(len(df), block, rng)
        boot = df.iloc[idx].copy()
        # Reset index because duplicated dates are expected in a bootstrap resample.
        boot.index = pd.RangeIndex(len(boot))
        try:
            m = empirical_tail_metrics(primary, peer, boot, len(boot), q=q, target_tail_obs=max(10, int(len(boot) * q)))
        except Exception:
            continue
        for key, source in (("coex", "Emp lower co-exceedance"), ("lower_corr", "Lower tail corr"), ("stress_lift", "Stress lift")):
            val = safe_float(m.get(source))
            if val is not None:
                metrics[key].append(val)

    out = {"status": "ok", "obs": int(len(df)), "samples_requested": int(samples)}
    for key, vals in metrics.items():
        arr = np.asarray(vals, dtype=float)
        if len(arr) >= 30:
            out[f"{key}_median"] = float(np.median(arr))
            out[f"{key}_ci_low"] = float(np.quantile(arr, 0.025))
            out[f"{key}_ci_high"] = float(np.quantile(arr, 0.975))
            out[f"{key}_samples"] = int(len(arr))
        else:
            out[f"{key}_median"] = None
            out[f"{key}_ci_low"] = None
            out[f"{key}_ci_high"] = None
            out[f"{key}_samples"] = int(len(arr))
    return out
