from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .estimators import trailing
from .utils import safe_float


def implied_average_correlation(index_iv: float, weights: dict[str, float], component_ivs: dict[str, float]) -> dict:
    """Equicorrelation implied by index variance and component implied volatilities.

    Inputs are decimal volatilities (e.g. 0.20, not 20). This is an average-correlation
    identity, not a substitute for a vendor/Cboe production methodology.
    """
    idx = safe_float(index_iv)
    if idx is None or idx <= 0:
        return {"status": "invalid_index_iv"}
    names = [k for k in weights if k in component_ivs]
    if len(names) < 2:
        return {"status": "insufficient_components"}
    w = np.array([float(weights[k]) for k in names], dtype=float)
    sig = np.array([float(component_ivs[k]) for k in names], dtype=float)
    if np.any(~np.isfinite(w)) or np.any(~np.isfinite(sig)) or np.any(sig <= 0):
        return {"status": "invalid_inputs"}
    if abs(w.sum()) < 1e-12:
        return {"status": "zero_weight_sum"}
    w = w / w.sum()
    diag = float(np.sum((w * sig) ** 2))
    denom = float((np.sum(w * sig) ** 2) - diag)
    if abs(denom) < 1e-12:
        return {"status": "degenerate_denominator"}
    rho = float((idx * idx - diag) / denom)
    return {
        "status": "ok",
        "implied_corr": rho,
        "implied_corr_clipped": float(np.clip(rho, -1.0, 1.0)),
        "index_iv": idx,
        "component_count": len(names),
        "weight_sum_raw": float(np.array([weights[k] for k in names], dtype=float).sum()),
        "components": names,
    }


def weighted_realized_correlation(
    changes: pd.DataFrame,
    weights: dict[str, float],
    days: int = 63,
) -> dict:
    """Volatility-weighted average pairwise realized correlation consistent with the variance identity."""
    names = [k for k in weights if k in changes.columns]
    if len(names) < 2:
        return {"status": "insufficient_components"}
    rt = trailing(changes[names], int(days)).dropna(how="any")
    if len(rt) < 30:
        return {"status": "insufficient_data", "obs": int(len(rt))}
    w = np.array([float(weights[k]) for k in names], dtype=float)
    if abs(w.sum()) < 1e-12:
        return {"status": "zero_weight_sum"}
    w = w / w.sum()
    cov = rt.cov().to_numpy(dtype=float)
    sig = np.sqrt(np.clip(np.diag(cov), 1e-18, None))
    port_var = float(w @ cov @ w)
    diag = float(np.sum((w * sig) ** 2))
    denom = float((np.sum(w * sig) ** 2) - diag)
    if abs(denom) < 1e-18:
        return {"status": "degenerate_denominator", "obs": int(len(rt))}
    rho = float((port_var - diag) / denom)
    return {
        "status": "ok",
        "realized_corr": rho,
        "obs": int(len(rt)),
        "components": names,
        "portfolio_daily_vol": float(np.sqrt(max(port_var, 0.0))),
    }



def _normalize_term_structure(value) -> dict[int, float]:
    out: dict[int, float] = {}
    if isinstance(value, dict):
        for k, v in value.items():
            try:
                key = int(str(k).upper().replace("D", "").replace("M", "").strip())
                fv = float(v)
                if np.isfinite(fv): out[key] = fv
            except Exception:
                continue
    elif isinstance(value, pd.DataFrame) and not value.empty:
        lower = {str(c).lower(): c for c in value.columns}
        hcol = lower.get("horizon_days") or lower.get("horizon") or lower.get("days")
        ccol = lower.get("implied_corr") or lower.get("implied correlation") or lower.get("corr")
        if hcol is not None and ccol is not None:
            for _, r in value.iterrows():
                try:
                    h = int(r[hcol]); v = float(r[ccol])
                    if np.isfinite(v): out[h] = v
                except Exception: pass
    return dict(sorted(out.items()))


def _attach_forward_surface(meta: dict, analysis: dict, changes: pd.DataFrame) -> dict:
    term = _normalize_term_structure(analysis.get("correlation_implied_term_structure"))
    if term:
        if meta.get("status") != "ok":
            first_h = sorted(term)[0]
            meta.update({
                "status": "ok",
                "method": "supplied_term_structure",
                "source": str(analysis.get("correlation_implied_corr_source", "Injected implied correlation term structure")),
                "horizon_days": first_h,
                "implied_corr": term[first_h],
            })
        meta["term_structure"] = term
        keys = sorted(term)
        if len(keys) >= 2:
            meta["term_slope"] = float(term[keys[-1]] - term[keys[0]])
        realized_term = {}
        # For supplied index/component weights use the same variance-identity-consistent realized measure.
        inputs = analysis.get("correlation_implied_inputs")
        if isinstance(inputs, dict) and isinstance(inputs.get("weights"), dict):
            for h in keys:
                rr = weighted_realized_correlation(changes, inputs.get("weights", {}), h)
                if rr.get("status") == "ok": realized_term[h] = rr.get("realized_corr")
        meta["realized_term_structure"] = realized_term
        meta["term_premium"] = {h: term[h] - realized_term[h] for h in keys if h in realized_term and realized_term[h] is not None}
    skew = analysis.get("correlation_implied_skew")
    if isinstance(skew, dict):
        clean = {}
        for k, v in skew.items():
            try:
                fv=float(v)
                if np.isfinite(fv): clean[str(k)] = fv
            except Exception: pass
        if clean:
            meta["skew"] = clean
            atm = clean.get("ATM") or clean.get("atm")
            put = clean.get("Put OTM") or clean.get("put") or clean.get("put_otm")
            call = clean.get("Call OTM") or clean.get("call") or clean.get("call_otm")
            if atm is not None and put is not None: meta["put_skew_vs_atm"] = float(put-atm)
            if atm is not None and call is not None: meta["call_skew_vs_atm"] = float(call-atm)
    return meta

def forward_correlation_diagnostics(
    analysis: dict[str, Any] | None,
    changes: pd.DataFrame,
    default_realized_days: int = 63,
) -> tuple[dict, pd.DataFrame]:
    """Resolve forward-looking correlation from injected market data.

    Supported interfaces:
      analysis['correlation_implied_inputs'] = {
          'index_iv': 0.20,
          'weights': {'AAPL': .1, ...},
          'component_ivs': {'AAPL': .25, ...},
          'horizon_days': 63,
          'source': 'OPRA/Cboe/internal'
      }

      analysis['correlation_implied_corr'] = 0.55
      analysis['correlation_implied_corr_source'] = '...'

      analysis['correlation_implied_corr_series'] = Series/DataFrame
    """
    analysis = analysis or {}
    meta: dict[str, Any] = {"status": "unavailable"}
    history = pd.DataFrame()

    supplied_series = analysis.get("correlation_implied_corr_series")
    if isinstance(supplied_series, pd.Series) and not supplied_series.empty:
        history = supplied_series.rename("Implied correlation").to_frame()
        history.index = pd.to_datetime(history.index, errors="coerce")
        history = history.dropna().sort_index()
        if not history.empty:
            latest = safe_float(history.iloc[-1, 0])
            meta = {
                "status": "ok",
                "method": "supplied_series",
                "implied_corr": latest,
                "source": str(analysis.get("correlation_implied_corr_source", "Injected implied correlation series")),
                "horizon_days": analysis.get("correlation_implied_horizon_days"),
            }
    elif isinstance(supplied_series, pd.DataFrame) and not supplied_series.empty:
        df = supplied_series.copy()
        lower = {str(c).lower(): c for c in df.columns}
        date_col = lower.get("date") or lower.get("datetime")
        corr_col = lower.get("implied_corr") or lower.get("implied correlation") or lower.get("corr")
        if date_col is not None:
            df.index = pd.to_datetime(df[date_col], errors="coerce")
        else:
            df.index = pd.to_datetime(df.index, errors="coerce")
        if corr_col is not None:
            history = pd.to_numeric(df[corr_col], errors="coerce").rename("Implied correlation").to_frame().dropna().sort_index()
            if not history.empty:
                meta = {
                    "status": "ok",
                    "method": "supplied_series",
                    "implied_corr": safe_float(history.iloc[-1, 0]),
                    "source": str(analysis.get("correlation_implied_corr_source", "Injected implied correlation series")),
                    "horizon_days": analysis.get("correlation_implied_horizon_days"),
                }

    inputs = analysis.get("correlation_implied_inputs")
    if isinstance(inputs, dict) and inputs:
        calc = implied_average_correlation(inputs.get("index_iv"), inputs.get("weights", {}), inputs.get("component_ivs", {}))
        if calc.get("status") == "ok":
            horizon_days = int(inputs.get("horizon_days") or default_realized_days)
            realized = weighted_realized_correlation(changes, inputs.get("weights", {}), horizon_days)
            meta = {
                **calc,
                "method": "variance_identity",
                "source": str(inputs.get("source", "Injected index/component option IVs")),
                "horizon_days": horizon_days,
                "realized_corr": realized.get("realized_corr"),
                "realized_obs": realized.get("obs"),
            }
            if meta.get("realized_corr") is not None:
                meta["correlation_risk_premium"] = float(meta["implied_corr_clipped"] - meta["realized_corr"])
            return _attach_forward_surface(meta, analysis, changes), history

    scalar = safe_float(analysis.get("correlation_implied_corr"))
    if scalar is not None:
        meta = {
            "status": "ok",
            "method": "supplied_scalar",
            "implied_corr": scalar,
            "source": str(analysis.get("correlation_implied_corr_source", "Injected implied correlation")),
            "horizon_days": analysis.get("correlation_implied_horizon_days"),
        }

    # If a supplied series/scalar exists but constituent inputs do not, compare against an unweighted
    # average realized correlation proxy over the current dependency universe.
    if meta.get("status") == "ok" and not changes.empty and changes.shape[1] >= 2:
        horizon = int(meta.get("horizon_days") or default_realized_days)
        rt = trailing(changes, horizon).dropna(axis=1, thresh=max(20, horizon // 2)).dropna(how="any")
        if len(rt) >= 30 and rt.shape[1] >= 2:
            c = rt.corr().to_numpy(dtype=float)
            vals = c[np.triu_indices_from(c, 1)]
            vals = vals[np.isfinite(vals)]
            if len(vals):
                realized = float(np.mean(vals))
                meta["realized_corr_proxy"] = realized
                imp = safe_float(meta.get("implied_corr"))
                if imp is not None:
                    meta["correlation_risk_premium_proxy"] = imp - realized
                meta["realized_obs"] = int(len(rt))
    return _attach_forward_surface(meta, analysis, changes), history
