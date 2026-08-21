from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.api as sm

from .utils import safe_float


def _greedy_drop_collinear(x: pd.DataFrame, threshold: float = 0.92) -> tuple[pd.DataFrame, list[str]]:
    keep: list[str] = []
    dropped: list[str] = []
    for col in x.columns:
        if not keep:
            keep.append(col)
            continue
        if all(abs(x[col].corr(x[k])) < threshold for k in keep):
            keep.append(col)
        else:
            dropped.append(col)
    return x[keep], dropped


def _vif_table(x: pd.DataFrame) -> dict[str, float | None]:
    """Compute VIF without relying on formula API."""
    out: dict[str, float | None] = {}
    if x.empty:
        return out
    if x.shape[1] == 1:
        return {x.columns[0]: 1.0}
    for col in x.columns:
        others = [c for c in x.columns if c != col]
        y = x[col]
        try:
            model = sm.OLS(y, sm.add_constant(x[others], has_constant="add")).fit()
            r2 = float(model.rsquared)
            out[col] = float(1.0 / max(1.0 - r2, 1e-9))
        except Exception:
            out[col] = None
    return out


def _condition_number(x: pd.DataFrame, standardize: bool) -> float | None:
    if x is None or x.empty:
        return None
    z = x.astype(float).copy()
    if standardize:
        sd = z.std(ddof=1).replace(0.0, np.nan)
        z = (z - z.mean()) / sd
        z = z.replace([np.inf, -np.inf], np.nan).dropna(axis=1, how="any")
    if z.empty:
        return None
    try:
        X = sm.add_constant(z, has_constant="add").to_numpy(dtype=float)
        return float(np.linalg.cond(X))
    except Exception:
        return None


def _collinearity_state(condition_std: float | None, max_vif: float | None) -> tuple[str, str]:
    c = safe_float(condition_std)
    v = safe_float(max_vif)
    if (c is not None and c >= 30) or (v is not None and v >= 10):
        return "Severe", "Severe multicollinearity: conditional betas may be unstable; emphasize standardized beta and incremental R²."
    if (c is not None and c >= 15) or (v is not None and v >= 5):
        return "Elevated", "Elevated multicollinearity: interpret raw conditional betas cautiously."
    return "Controlled", "Factor collinearity is controlled on the retained design matrix."


def multivariate_factor_model(
    primary: str,
    changes: pd.DataFrame,
    factors: list[str],
    days: int,
    hac_maxlags: int = 5,
    pair_collinear_threshold: float = 0.92,
) -> tuple[pd.DataFrame, dict]:
    available = [f for f in factors if f in changes.columns and f != primary]
    if primary not in changes.columns or not available:
        return pd.DataFrame(), {"status": "unavailable"}

    df = changes[[primary] + available].tail(days).dropna()
    if len(df) < max(40, len(available) * 8):
        return pd.DataFrame(), {"status": "insufficient_data", "obs": len(df)}

    x_raw, dropped = _greedy_drop_collinear(df[available].copy(), threshold=pair_collinear_threshold)
    if x_raw.empty:
        return pd.DataFrame(), {"status": "collinear", "factors_dropped": dropped}

    y = df[primary].loc[x_raw.index]
    X = sm.add_constant(x_raw, has_constant="add")
    try:
        model = sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": hac_maxlags})
    except Exception:
        return pd.DataFrame(), {"status": "fit_failed"}

    vif = _vif_table(x_raw)
    cond_raw = safe_float(model.condition_number)
    cond_std = _condition_number(x_raw, standardize=True)
    max_vif = max([v for v in vif.values() if v is not None], default=None)
    col_state, col_message = _collinearity_state(cond_std, max_vif)

    y_std = safe_float(y.std(ddof=1))
    full_r2 = safe_float(model.rsquared)
    rows = []
    for factor in x_raw.columns:
        incremental = None
        others = [c for c in x_raw.columns if c != factor]
        if others:
            try:
                reduced = sm.OLS(y, sm.add_constant(x_raw[others], has_constant="add")).fit()
                incremental = max(0.0, (full_r2 or 0.0) - safe_float(reduced.rsquared, 0.0))
            except Exception:
                incremental = None
        else:
            incremental = full_r2

        raw_beta = safe_float(model.params.get(factor))
        x_std = safe_float(x_raw[factor].std(ddof=1))
        standardized_beta = None
        if raw_beta is not None and x_std is not None and y_std not in (None, 0):
            standardized_beta = raw_beta * x_std / y_std

        rows.append({
            "Factor": factor,
            "Raw Beta": raw_beta,
            "Standardized Beta": standardized_beta,
            "HAC t-stat": safe_float(model.tvalues.get(factor)),
            "p-value": safe_float(model.pvalues.get(factor)),
            "Incremental R²": incremental,
            "VIF": safe_float(vif.get(factor)),
        })

    table = pd.DataFrame(rows).sort_values("Incremental R²", ascending=False, na_position="last")
    meta = {
        "status": "ok",
        "obs": int(model.nobs),
        "R²": full_r2,
        "Adj R²": safe_float(model.rsquared_adj),
        "Alpha": safe_float(model.params.get("const")),
        "Alpha t-stat": safe_float(model.tvalues.get("const")),
        "Condition number raw": cond_raw,
        "Condition number standardized": cond_std,
        "Max VIF": safe_float(max_vif),
        "Multicollinearity": col_state,
        "Multicollinearity message": col_message,
        "factors_used": list(x_raw.columns),
        "factors_dropped": dropped,
    }
    return table.reset_index(drop=True), meta
