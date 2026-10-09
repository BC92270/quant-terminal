from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import leaves_list, linkage
from scipy.optimize import minimize
from scipy.spatial.distance import squareform
from sklearn.covariance import LedoitWolf

from .utils import safe_float


def _normalized_weights(weights: dict[str, float], cols: list[str]) -> np.ndarray:
    w = np.array([float(weights[c]) for c in cols], dtype=float)
    if not np.isfinite(w).all():
        raise ValueError("Non-finite portfolio weight")
    return w


def _shrunk_cov(rt: pd.DataFrame) -> pd.DataFrame:
    x = rt.to_numpy(dtype=float)
    if len(rt) >= max(40, 2 * rt.shape[1]):
        try:
            cov = LedoitWolf().fit(x).covariance_
            return pd.DataFrame(cov, index=rt.columns, columns=rt.columns)
        except Exception:
            pass
    cov = rt.cov()
    # nearest_psd expects a square DataFrame; covariance remains in covariance units.
    vals, vecs = np.linalg.eigh((cov.to_numpy(dtype=float) + cov.to_numpy(dtype=float).T) / 2)
    vals = np.clip(vals, 1e-12, None)
    arr = vecs @ np.diag(vals) @ vecs.T
    return pd.DataFrame(arr, index=cov.index, columns=cov.columns)


def _historical_var_cvar(returns: pd.Series, alpha: float = 0.95) -> tuple[float | None, float | None]:
    r = pd.to_numeric(returns, errors="coerce").dropna()
    if len(r) < 30:
        return None, None
    loss = -r
    var = float(np.quantile(loss, alpha))
    tail = loss[loss >= var]
    cvar = float(tail.mean()) if len(tail) else var
    return var, cvar


def portfolio_risk_decomposition(
    changes: pd.DataFrame,
    weights: dict[str, float],
    days: int,
    asset_type_map: dict[str, str] | None = None,
) -> tuple[pd.DataFrame, dict]:
    """Shrinkage covariance risk decomposition with volatility, concentration and tail metrics."""
    if not weights:
        return pd.DataFrame(), {"status": "unavailable"}
    cols = [c for c in weights if c in changes.columns]
    if len(cols) < 2:
        return pd.DataFrame(), {"status": "insufficient_assets"}
    rt = changes[cols].tail(days).dropna(how="any")
    if len(rt) < 30:
        return pd.DataFrame(), {"status": "insufficient_data", "obs": int(len(rt))}
    cov_df = _shrunk_cov(rt)
    cov = cov_df.to_numpy(dtype=float)
    try:
        w = _normalized_weights(weights, cols)
    except Exception:
        return pd.DataFrame(), {"status": "invalid_weights"}

    variance = max(float(w @ cov @ w), 1e-18)
    total = float(np.sqrt(variance))
    marginal = cov @ w / total
    component = w * marginal
    standalone_vol = np.sqrt(np.clip(np.diag(cov), 1e-18, None))
    gross = float(np.sum(np.abs(w)))
    weighted_standalone = float(np.sum(np.abs(w) * standalone_vol))
    diversification_ratio = weighted_standalone / max(total, 1e-18)
    abs_w = np.abs(w)
    norm_abs = abs_w / max(abs_w.sum(), 1e-18)
    effective_n = 1.0 / max(float(np.sum(norm_abs * norm_abs)), 1e-18)

    port_ret = rt.to_numpy(dtype=float) @ w
    var95, cvar95 = _historical_var_cvar(pd.Series(port_ret, index=rt.index), 0.95)
    var99, cvar99 = _historical_var_cvar(pd.Series(port_ret, index=rt.index), 0.99)

    rows = []
    for i, c in enumerate(cols):
        rc = component[i] / total
        rows.append({
            "Asset": c,
            "Type": (asset_type_map or {}).get(c, "Unknown"),
            "Weight": w[i],
            "Standalone vol": standalone_vol[i],
            "Marginal risk": marginal[i],
            "Component risk": component[i],
            "Risk contribution %": rc,
        })
    table = pd.DataFrame(rows).sort_values("Risk contribution %", ascending=False).reset_index(drop=True)

    # Aggregate component risk by economic asset type / cluster proxy.
    cluster = table.groupby("Type", dropna=False, as_index=False).agg(
        Weight=("Weight", "sum"),
        **{"Component risk": ("Component risk", "sum")},
        **{"Risk contribution %": ("Risk contribution %", "sum")},
    ).sort_values("Risk contribution %", ascending=False).reset_index(drop=True)

    rc = pd.to_numeric(table["Risk contribution %"], errors="coerce").fillna(0).to_numpy(dtype=float)
    risk_hhi = float(np.sum(rc * rc))
    meta = {
        "status": "ok",
        "obs": int(len(rt)),
        "daily_vol": total,
        "annualized_vol": total * np.sqrt(252),
        "sum_component": float(component.sum()),
        "gross_exposure": gross,
        "net_exposure": float(w.sum()),
        "diversification_ratio": diversification_ratio,
        "effective_n": effective_n,
        "risk_hhi": risk_hhi,
        "VaR95 daily": var95,
        "CVaR95 daily": cvar95,
        "VaR99 daily": var99,
        "CVaR99 daily": cvar99,
        "covariance_method": "Ledoit-Wolf" if len(rt) >= max(40, 2 * len(cols)) else "PSD sample covariance",
        "cluster_table": cluster,
        "covariance": cov_df,
        "portfolio_returns": pd.Series(port_ret, index=rt.index, name="Portfolio return"),
    }
    return table, meta


def correlation_shock_scenarios(
    changes: pd.DataFrame,
    weights: dict[str, float],
    days: int,
    shock_levels: tuple[float, ...] = (0.10, 0.20, 0.35),
) -> pd.DataFrame:
    """Stress portfolio volatility by blending the correlation matrix toward +1 while preserving vols."""
    cols = [c for c in weights if c in changes.columns]
    if len(cols) < 2:
        return pd.DataFrame()
    rt = changes[cols].tail(days).dropna(how="any")
    if len(rt) < 30:
        return pd.DataFrame()
    cov = _shrunk_cov(rt).to_numpy(dtype=float)
    vols = np.sqrt(np.clip(np.diag(cov), 1e-18, None))
    corr = cov / np.outer(vols, vols)
    np.fill_diagonal(corr, 1.0)
    w = _normalized_weights(weights, cols)
    base_var = float(w @ cov @ w)
    base_vol = float(np.sqrt(max(base_var, 0.0)))
    rows = [{
        "Scenario": "Current correlation",
        "Correlation blend": 0.0,
        "Daily vol": base_vol,
        "Annualized vol": base_vol * np.sqrt(252),
        "Vol change": 0.0,
    }]
    ones = np.ones_like(corr)
    for alpha in shock_levels:
        a = float(np.clip(alpha, 0.0, 1.0))
        stressed_corr = (1.0 - a) * corr + a * ones
        np.fill_diagonal(stressed_corr, 1.0)
        stressed_cov = stressed_corr * np.outer(vols, vols)
        vol = float(np.sqrt(max(float(w @ stressed_cov @ w), 0.0)))
        rows.append({
            "Scenario": f"Correlation-to-1 blend +{a:.0%}",
            "Correlation blend": a,
            "Daily vol": vol,
            "Annualized vol": vol * np.sqrt(252),
            "Vol change": vol / max(base_vol, 1e-18) - 1.0,
        })
    return pd.DataFrame(rows)


def incremental_asset_impact(
    changes: pd.DataFrame,
    weights: dict[str, float],
    candidates: list[str],
    days: int,
    add_weight: float = 0.05,
) -> pd.DataFrame:
    """Fund a small candidate allocation pro-rata from the existing portfolio and measure vol/CVaR impact."""
    base_cols = [c for c in weights if c in changes.columns]
    if len(base_cols) < 2:
        return pd.DataFrame()
    add = float(np.clip(add_weight, 0.005, 0.25))
    rows = []
    all_candidates = [c for c in candidates if c in changes.columns and c not in base_cols]
    base_rt = changes[base_cols].tail(days).dropna(how="any")
    if len(base_rt) < 30:
        return pd.DataFrame()
    base_w = np.array([float(weights[c]) for c in base_cols], dtype=float)
    base_cov = _shrunk_cov(base_rt).to_numpy(dtype=float)
    base_vol = float(np.sqrt(max(float(base_w @ base_cov @ base_w), 0.0)))
    base_pr = base_rt.to_numpy(dtype=float) @ base_w
    _, base_cvar = _historical_var_cvar(pd.Series(base_pr), 0.95)

    for cand in all_candidates:
        cols = base_cols + [cand]
        rt = changes[cols].tail(days).dropna(how="any")
        if len(rt) < 30:
            continue
        base_net = float(base_w.sum())
        scale = (base_net - add) / base_net if abs(base_net) > 1e-9 else 1.0
        w = np.concatenate([base_w * scale, [add]])
        cov = _shrunk_cov(rt).to_numpy(dtype=float)
        vol = float(np.sqrt(max(float(w @ cov @ w), 0.0)))
        pr = rt.to_numpy(dtype=float) @ w
        _, cvar = _historical_var_cvar(pd.Series(pr), 0.95)
        rows.append({
            "Candidate": cand,
            "Add weight": add,
            "Annualized vol": vol * np.sqrt(252),
            "Δ annualized vol": (vol - base_vol) * np.sqrt(252),
            "Δ vol %": vol / max(base_vol, 1e-18) - 1.0,
            "CVaR95 daily": cvar,
            "Δ CVaR95": (cvar - base_cvar) if cvar is not None and base_cvar is not None else None,
            "Obs": int(len(rt)),
        })
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["Δ annualized vol", "Δ CVaR95"], na_position="last").reset_index(drop=True)


def _hedge_stats(df: pd.DataFrame, primary: str, peer: str) -> dict | None:
    if df is None or len(df) < 20:
        return None
    var_h = safe_float(df[peer].var())
    cov = safe_float(df.cov().loc[primary, peer])
    if var_h is None or cov is None or var_h <= 0:
        return None
    h = cov / var_h
    residual = df[primary] - h * df[peer]
    pvol = safe_float(df[primary].std())
    rvol = safe_float(residual.std())
    reduction = 1 - rvol / max(pvol or 0.0, 1e-18) if rvol is not None and pvol is not None else None
    corr = safe_float(df[primary].corr(df[peer]))
    worst = df[df[primary] <= df[primary].quantile(0.20)]
    stress_corr = safe_float(worst[primary].corr(worst[peer])) if len(worst) >= 8 else None
    return {"Hedge ratio": h, "Corr": corr, "Stress corr": stress_corr, "Vol reduction": reduction, "Residual vol": rvol, "Obs": len(df)}


def _oos_reduction(df: pd.DataFrame, primary: str, peer: str) -> float | None:
    """70/30 chronological split: fit hedge ratio on train, evaluate volatility reduction on test."""
    if len(df) < 60:
        return None
    cut = max(30, int(len(df) * 0.70))
    train, test = df.iloc[:cut], df.iloc[cut:]
    if len(test) < 15:
        return None
    var_h = safe_float(train[peer].var())
    cov = safe_float(train.cov().loc[primary, peer])
    if var_h is None or cov is None or var_h <= 0:
        return None
    h = cov / var_h
    residual = test[primary] - h * test[peer]
    base = safe_float(test[primary].std())
    res = safe_float(residual.std())
    if base in (None, 0) or res is None:
        return None
    return 1 - res / base


def hedge_candidates(
    primary: str,
    changes: pd.DataFrame,
    peers: list[str],
    days: int,
    windows: tuple[int, ...] = (30, 90, 180, 252),
    type_map: dict[str, str] | None = None,
) -> pd.DataFrame:
    rows = []
    if primary not in changes.columns:
        return pd.DataFrame()

    for peer in peers:
        if peer == primary or peer not in changes.columns:
            continue
        selected = changes[[primary, peer]].tail(days).dropna()
        stats_sel = _hedge_stats(selected, primary, peer)
        if stats_sel is None or len(selected) < 30:
            continue

        row = {"Hedge": peer, "Type": (type_map or {}).get(peer, "Unknown"), **stats_sel}
        ratios, reductions = [], []
        for w in windows:
            dfw = changes[[primary, peer]].tail(w).dropna()
            sw = _hedge_stats(dfw, primary, peer)
            if sw is None:
                row[f"Hedge ratio {w}D"] = None
                row[f"Vol reduction {w}D"] = None
                continue
            row[f"Hedge ratio {w}D"] = sw["Hedge ratio"]
            row[f"Vol reduction {w}D"] = sw["Vol reduction"]
            hr = safe_float(sw.get("Hedge ratio"))
            vr = safe_float(sw.get("Vol reduction"))
            if hr is not None:
                ratios.append(hr)
            if vr is not None:
                reductions.append(vr)

        ratio_std = float(np.std(ratios, ddof=1)) if len(ratios) >= 2 else None
        ratio_mean_abs = float(np.mean(np.abs(ratios))) if ratios else None
        ratio_cv = ratio_std / max(ratio_mean_abs or 0.0, 1e-9) if ratio_std is not None else None
        reduction_std = float(np.std(reductions, ddof=1)) if len(reductions) >= 2 else None
        mean_reduction = float(np.mean(reductions)) if reductions else None
        sign_flip = len({np.sign(x) for x in ratios if abs(x) > 1e-12}) > 1

        if sign_flip or (ratio_cv is not None and ratio_cv > 0.75):
            stability = "Unstable"; stability_score = 0.0
        elif ratio_cv is not None and ratio_cv <= 0.25 and (reduction_std is None or reduction_std <= 0.05):
            stability = "Stable"; stability_score = 1.0
        else:
            stability = "Variable"; stability_score = 0.5

        oos = _oos_reduction(selected, primary, peer)
        selected_red = safe_float(row.get("Vol reduction"), 0.0) or 0.0
        mean_red = safe_float(mean_reduction, selected_red) or selected_red
        oos_for_score = max(-0.25, min(0.75, safe_float(oos, 0.0) or 0.0))
        robust_score = 100 * max(0.0, min(1.0,
            0.45 * max(selected_red, 0.0)
            + 0.25 * max(mean_red, 0.0)
            + 0.20 * max(oos_for_score, 0.0)
            + 0.10 * stability_score
        ))

        row.update({
            "Mean vol reduction": mean_reduction,
            "Hedge ratio CV": ratio_cv,
            "Reduction stability std": reduction_std,
            "Stability": stability,
            "OOS vol reduction": oos,
            "Robust hedge score": robust_score,
        })
        rows.append(row)

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["Robust hedge score", "Vol reduction"], ascending=False).reset_index(drop=True)


def portfolio_eigen_risk(
    changes: pd.DataFrame,
    weights: dict[str,float],
    days: int=252,
    covariance: pd.DataFrame | None=None,
) -> tuple[pd.DataFrame,dict]:
    """Decompose portfolio variance across covariance eigenmodes."""
    cols=[c for c in weights if c in changes.columns]
    if len(cols)<2:
        return pd.DataFrame(),{"status":"insufficient_assets"}
    rt=changes[cols].tail(days).dropna(how="any")
    if len(rt)<30:
        return pd.DataFrame(),{"status":"insufficient_data","obs":len(rt)}
    covdf=covariance.loc[cols,cols] if isinstance(covariance,pd.DataFrame) and set(cols).issubset(covariance.columns) else _shrunk_cov(rt)
    cov=covdf.to_numpy(dtype=float); w=np.array([float(weights[c]) for c in cols],dtype=float)
    vals,vecs=np.linalg.eigh(cov); order=np.argsort(vals)[::-1]; vals=vals[order]; vecs=vecs[:,order]
    total=float(w@cov@w)
    rows=[]
    for k,(lam,v) in enumerate(zip(vals,vecs.T),start=1):
        expo=float(w@v); contrib=float(lam*expo*expo); share=contrib/max(total,1e-18)
        top_idx=np.argsort(np.abs(v))[::-1][:min(3,len(cols))]
        drivers=", ".join(f"{cols[i]} {v[i]:+.2f}" for i in top_idx)
        rows.append({"Mode":f"PC{k}","Eigenvalue":float(lam),"Portfolio loading":expo,"Variance contribution":contrib,"Risk share":share,"Top loadings":drivers})
    table=pd.DataFrame(rows)
    return table,{"status":"ok","portfolio_variance":total,"top_mode_share":safe_float(table.iloc[0]["Risk share"]),"effective_modes":float(1/max(np.sum(np.square(table["Risk share"].to_numpy(dtype=float))),1e-18))}


def structured_correlation_stress_scenarios(
    changes: pd.DataFrame,
    weights: dict[str,float],
    days: int,
    asset_type_map: dict[str,str] | None=None,
    regime_days: int=60,
) -> pd.DataFrame:
    """Institutional correlation stresses beyond uniform convergence.

    Scenarios preserve marginal volatilities and alter dependency only:
      * current
      * uniform convergence to +1
      * cluster convergence within economic asset types
      * historical high-volatility correlation matrix
      * dominant-eigenmode amplification
      * conservative worst-case PSD blend toward sign(w_i*w_j)
    """
    cols=[c for c in weights if c in changes.columns]
    if len(cols)<2: return pd.DataFrame()
    rt=changes[cols].tail(days).dropna(how="any")
    if len(rt)<30: return pd.DataFrame()
    cov=_shrunk_cov(rt).to_numpy(dtype=float); vols=np.sqrt(np.clip(np.diag(cov),1e-18,None)); corr=cov/np.outer(vols,vols); np.fill_diagonal(corr,1)
    w=np.array([float(weights[c]) for c in cols],dtype=float)
    def calc(name,c):
        c=np.asarray(c,dtype=float); c=0.5*(c+c.T); vals,vecs=np.linalg.eigh(c); vals=np.clip(vals,1e-6,None); c=(vecs*vals)@vecs.T; d=np.sqrt(np.clip(np.diag(c),1e-18,None)); c=c/np.outer(d,d); np.fill_diagonal(c,1)
        scov=c*np.outer(vols,vols); v=float(np.sqrt(max(w@scov@w,0))); return {"Scenario":name,"Daily vol":v,"Annualized vol":v*np.sqrt(252),"Matrix condition":float(np.linalg.cond(c))}
    rows=[calc("Current correlation",corr)]
    rows.append(calc("Uniform convergence +20%",0.8*corr+0.2*np.ones_like(corr)))
    # within-type convergence
    cc=corr.copy(); types=asset_type_map or {}
    for i,a in enumerate(cols):
        for j,b in enumerate(cols):
            if i!=j and types.get(a)==types.get(b): cc[i,j]=0.75*corr[i,j]+0.25*1.0
    rows.append(calc("Cluster convergence +25%",cc))
    # empirical high-vol sub-sample
    market_proxy=rt.mean(axis=1); rolling=market_proxy.rolling(20).std(); threshold=rolling.quantile(.70); hv=rt.loc[rolling>=threshold]
    if len(hv)>=20:
        hc=hv.corr().to_numpy(dtype=float); rows.append(calc("Historical high-vol correlation",hc))
    # amplify leading eigenmode of correlation
    vals,vecs=np.linalg.eigh(corr); idx=np.argmax(vals); vals2=vals.copy(); vals2[idx]*=1.25; ec=(vecs*vals2)@vecs.T; d=np.sqrt(np.clip(np.diag(ec),1e-18,None)); ec=ec/np.outer(d,d); np.fill_diagonal(ec,1)
    rows.append(calc("Dominant eigenmode +25%",ec))
    # worst-case sign target for portfolio variance: +1 if weights same sign, -1 if opposite.
    sign_target=np.sign(np.outer(w,w)); np.fill_diagonal(sign_target,1.0); wc=0.8*corr+0.2*sign_target
    rows.append(calc("Worst-case sign convergence +20%",wc))
    out=pd.DataFrame(rows); base=float(out.iloc[0]["Annualized vol"]); out["Vol change"]=out["Annualized vol"]/max(base,1e-18)-1
    return out


def _inverse_variance_weights(cov: np.ndarray) -> np.ndarray:
    iv = 1.0 / np.clip(np.diag(cov), 1e-18, None)
    return iv / max(float(iv.sum()), 1e-18)


def _cluster_variance(cov: np.ndarray, indices: list[int]) -> float:
    sub = cov[np.ix_(indices, indices)]
    w = _inverse_variance_weights(sub)
    return float(w @ sub @ w)


def _hrp_weights(cov: np.ndarray) -> tuple[np.ndarray, list[int]]:
    """Hierarchical Risk Parity using average-linkage and recursive bisection."""

    cov = np.asarray(cov, dtype=float)
    p = len(cov)
    if p < 2:
        return np.ones(p, dtype=float), list(range(p))
    vol = np.sqrt(np.clip(np.diag(cov), 1e-18, None))
    corr = cov / np.outer(vol, vol)
    corr = np.clip(0.5 * (corr + corr.T), -1.0, 1.0)
    np.fill_diagonal(corr, 1.0)
    dist = np.sqrt(np.clip((1.0 - corr) / 2.0, 0.0, None))
    tree = linkage(squareform(dist, checks=False), method="average", optimal_ordering=True)
    order = [int(i) for i in leaves_list(tree)]
    weights = np.ones(p, dtype=float)
    clusters: list[list[int]] = [order]
    while clusters:
        next_clusters: list[list[int]] = []
        for cluster in clusters:
            if len(cluster) <= 1:
                continue
            split = len(cluster) // 2
            left, right = cluster[:split], cluster[split:]
            lv = _cluster_variance(cov, left)
            rv = _cluster_variance(cov, right)
            alpha = 1.0 - lv / max(lv + rv, 1e-18)
            weights[left] *= alpha
            weights[right] *= 1.0 - alpha
            next_clusters.extend([left, right])
        clusters = next_clusters
    weights = np.clip(weights, 0.0, None)
    weights /= max(float(weights.sum()), 1e-18)
    return weights, order


def _minimum_variance_long_only(cov: np.ndarray) -> tuple[np.ndarray, dict]:
    p = len(cov)
    start = _inverse_variance_weights(cov)

    def objective(w: np.ndarray) -> float:
        return float(w @ cov @ w)

    result = minimize(
        objective,
        x0=start,
        method="SLSQP",
        bounds=[(0.0, 1.0)] * p,
        constraints={"type": "eq", "fun": lambda w: float(w.sum() - 1.0)},
        options={"maxiter": 300, "ftol": 1e-12},
    )
    if not result.success or not np.isfinite(result.x).all():
        return start, {"success": False, "fallback": "inverse_volatility", "message": str(result.message)}
    w = np.clip(np.asarray(result.x, dtype=float), 0.0, 1.0)
    w /= max(float(w.sum()), 1e-18)
    return w, {"success": True, "fallback": None, "message": str(result.message)}


def _allocation_weights(cov: np.ndarray, method: str) -> tuple[np.ndarray, dict]:
    p = len(cov)
    if method == "Equal weight":
        return np.repeat(1.0 / p, p), {"success": True}
    if method == "Inverse volatility":
        return _inverse_variance_weights(cov), {"success": True}
    if method == "HRP":
        w, order = _hrp_weights(cov)
        return w, {"success": True, "cluster_order": order}
    if method == "Long-only minimum variance":
        return _minimum_variance_long_only(cov)
    raise ValueError(f"Unknown allocation method: {method}")


def _max_drawdown(log_returns: np.ndarray) -> float:
    wealth = np.exp(np.cumsum(np.asarray(log_returns, dtype=float)))
    peak = np.maximum.accumulate(np.r_[1.0, wealth])
    full = np.r_[1.0, wealth]
    return float(np.min(full / np.maximum(peak, 1e-18) - 1.0))


def allocation_model_comparison(
    changes: pd.DataFrame,
    universe: list[str],
    train_days: int = 252,
    test_days: int = 21,
    min_train: int = 126,
    max_folds: int = 8,
    transaction_cost_bps: float = 10.0,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """No-look-ahead allocation challenger lab.

    Four long-only approaches are fitted only on each chronological training window and
    evaluated on the following non-overlapping block.  The result is research evidence,
    not an optimiser mandate; estimated linear turnover costs are shown explicitly.
    """

    cols = list(dict.fromkeys([c for c in universe if c in changes.columns]))
    if len(cols) < 3:
        return pd.DataFrame(), pd.DataFrame(), {"status": "insufficient_assets"}
    rt = changes[cols].apply(pd.to_numeric, errors="coerce").dropna(how="any")
    n = len(rt)
    h = max(5, int(test_days))
    train = min(int(train_days), max(int(min_train), n - h))
    if n < int(min_train) + h:
        return pd.DataFrame(), pd.DataFrame(), {"status": "insufficient_data", "obs": int(n)}

    methods = ["Equal weight", "Inverse volatility", "HRP", "Long-only minimum variance"]
    starts = list(range(train, n - h + 1, h))[-max(1, int(max_folds)):]
    fold_rows: list[dict] = []
    previous: dict[str, np.ndarray] = {}
    fallback_count = 0
    for fold_no, end in enumerate(starts, start=1):
        train_frame = rt.iloc[max(0, end - train):end]
        test_frame = rt.iloc[end:end + h]
        if len(train_frame) < min_train or len(test_frame) < h:
            continue
        cov = _shrunk_cov(train_frame).to_numpy(dtype=float)
        for method in methods:
            try:
                w, fit_meta = _allocation_weights(cov, method)
            except Exception:
                continue
            if fit_meta.get("fallback"):
                fallback_count += 1
            turnover = float(0.5 * np.abs(w - previous[method]).sum()) if method in previous else 0.0
            previous[method] = w
            gross = test_frame.to_numpy(dtype=float) @ w
            cost = turnover * float(transaction_cost_bps) / 10000.0
            net = gross.copy()
            if len(net):
                net[0] -= cost
            _, cvar = _historical_var_cvar(pd.Series(net), 0.95)
            fold_rows.append({
                "Fold": int(fold_no),
                "Train start": str(train_frame.index[0]),
                "Train end": str(train_frame.index[-1]),
                "Test start": str(test_frame.index[0]),
                "Test end": str(test_frame.index[-1]),
                "Method": method,
                "OOS ann. vol": float(np.std(net, ddof=1) * np.sqrt(252)),
                "OOS mean ann.": float(np.mean(net) * 252),
                "OOS CVaR95 daily": cvar,
                "OOS max drawdown": _max_drawdown(net),
                "Turnover": turnover,
                "Estimated cost": cost,
                "Effective N": float(1.0 / max(np.sum(w * w), 1e-18)),
                "Max weight": float(np.max(w)),
                "Fit fallback": fit_meta.get("fallback"),
            })

    fold_df = pd.DataFrame(fold_rows)
    if fold_df.empty:
        return pd.DataFrame(), pd.DataFrame(), {"status": "no_valid_folds", "obs": int(n)}

    summary = fold_df.groupby("Method", as_index=False).agg(
        Folds=("Fold", "nunique"),
        **{
            "OOS ann. vol": ("OOS ann. vol", "mean"),
            "OOS mean ann.": ("OOS mean ann.", "mean"),
            "OOS CVaR95 daily": ("OOS CVaR95 daily", "mean"),
            "Worst max drawdown": ("OOS max drawdown", "min"),
            "Mean turnover": ("Turnover", "mean"),
            "Mean effective N": ("Effective N", "mean"),
            "Mean max weight": ("Max weight", "mean"),
        },
    )
    summary["Vol rank"] = summary["OOS ann. vol"].rank(method="min", ascending=True).astype(int)
    summary = summary.sort_values(["Vol rank", "OOS CVaR95 daily"]).reset_index(drop=True)

    current_cov = _shrunk_cov(rt.tail(train)).to_numpy(dtype=float)
    weight_rows: list[dict] = []
    method_meta: dict[str, dict] = {}
    for method in methods:
        w, fit_meta = _allocation_weights(current_cov, method)
        method_meta[method] = fit_meta
        for asset, weight in zip(cols, w):
            weight_rows.append({"Method": method, "Asset": asset, "Weight": float(weight)})
    weights = pd.DataFrame(weight_rows)
    meta = {
        "status": "ok",
        "authority": "RESEARCH_ONLY",
        "no_look_ahead": True,
        "obs": int(n),
        "assets": int(len(cols)),
        "universe": cols,
        "train_days": int(train),
        "test_days": int(h),
        "folds": int(fold_df["Fold"].nunique()),
        "transaction_cost_bps": float(transaction_cost_bps),
        "covariance_method": "Ledoit-Wolf",
        "fallback_count": int(fallback_count),
        "current_method_meta": method_meta,
        "fold_results": fold_df,
    }
    return summary, weights, meta
