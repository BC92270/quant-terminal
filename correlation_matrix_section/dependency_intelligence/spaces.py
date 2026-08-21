from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .inputs import ForceInputs


def _pair_corr(a: pd.Series, b: pd.Series, min_obs: int = 30) -> tuple[float | None, int]:
    x = pd.concat([pd.to_numeric(a, errors="coerce"), pd.to_numeric(b, errors="coerce")], axis=1).dropna()
    if len(x) < min_obs:
        return None, int(len(x))
    c = float(x.iloc[:, 0].corr(x.iloc[:, 1]))
    return (c if np.isfinite(c) else None), int(len(x))


def _currency(asset: str, inputs: ForceInputs) -> str | None:
    meta = inputs.asset_metadata.get(asset, {}) if isinstance(inputs.asset_metadata, dict) else {}
    cur = meta.get("currency") if isinstance(meta, dict) else None
    return str(cur).upper() if cur else None


def _fx_log_return(currency: str, inputs: ForceInputs) -> pd.Series | None:
    if currency == inputs.base_currency:
        return None
    s = inputs.fx_to_base.get(currency)
    if s is None:
        return None
    x = pd.to_numeric(s, errors="coerce")
    x = x.where(x > 0)
    return np.log(x).diff()


def base_currency_return(local_return: pd.Series, asset: str, inputs: ForceInputs) -> tuple[pd.Series | None, str]:
    """Convert a local-currency log return to base-currency log return.

    Contract: dependency_fx_to_base[currency] is the *base-currency value of one unit of
    local currency* (e.g. USD per EUR when base=USD). For log returns this gives
    r_asset_base = r_asset_local + r_local_currency_in_base.
    """
    cur = _currency(asset, inputs)
    if not cur:
        return None, "currency metadata missing"
    if cur == inputs.base_currency:
        return pd.to_numeric(local_return, errors="coerce"), f"already {inputs.base_currency}"
    fx = _fx_log_return(cur, inputs)
    if fx is None:
        return None, f"FX series {cur}->{inputs.base_currency} missing"
    aligned = pd.concat([pd.to_numeric(local_return, errors="coerce"), fx.rename("fx")], axis=1)
    return (aligned.iloc[:, 0] + aligned["fx"]).rename(local_return.name), f"{cur}->{inputs.base_currency} unhedged"


def dependency_spaces(primary: str, peer: str, changes: pd.DataFrame, inputs: ForceInputs,
                      residual_primary: pd.Series | None = None, residual_peer: pd.Series | None = None,
                      min_obs: int = 30) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if primary not in changes or peer not in changes:
        return pd.DataFrame()

    raw_corr, n = _pair_corr(changes[primary], changes[peer], min_obs)
    rows.append({"Space": "Observed / core", "Correlation": raw_corr, "Obs": n, "Status": "Active",
                 "Interpretation": "Current transformed return/shock space used by the frozen correlation core."})

    # Base-currency view, only when explicit currency metadata + FX conversion are available.
    pb, ps = base_currency_return(changes[primary], primary, inputs)
    qb, qs = base_currency_return(changes[peer], peer, inputs)
    if pb is not None and qb is not None:
        c, nn = _pair_corr(pb, qb, min_obs)
        rows.append({"Space": f"Base currency ({inputs.base_currency})", "Correlation": c, "Obs": nn, "Status": "Active",
                     "Interpretation": f"Unhedged investor view; {ps}; {qs}."})
    else:
        rows.append({"Space": f"Base currency ({inputs.base_currency})", "Correlation": None, "Obs": 0, "Status": "Needs metadata/data",
                     "Interpretation": f"{ps}; {qs}."})

    # Perfect-FX-hedge approximation: local return, ignoring hedge carry and transaction costs.
    pc, qc = _currency(primary, inputs), _currency(peer, inputs)
    if pc and qc:
        c, nn = _pair_corr(changes[primary], changes[peer], min_obs)
        if pc == inputs.base_currency and qc == inputs.base_currency:
            status = "Not required / identical"
            interp = f"Both assets are already denominated in base currency {inputs.base_currency}; FX hedging does not change this pair view."
        else:
            status = "Approximation"
            interp = "Local-currency dependency under a perfect FX hedge approximation; hedge carry, basis and transaction costs ignored."
        rows.append({"Space": "FX-hedged local", "Correlation": c, "Obs": nn, "Status": status, "Interpretation": interp})
    else:
        rows.append({"Space": "FX-hedged local", "Correlation": None, "Obs": 0, "Status": "Needs currency metadata",
                     "Interpretation": "Requires dependency_asset_metadata[currency]."})

    if residual_primary is not None and residual_peer is not None:
        c, nn = _pair_corr(residual_primary, residual_peer, min_obs)
        rows.append({"Space": "Force-neutral residual", "Correlation": c, "Obs": nn, "Status": "Active",
                     "Interpretation": "Residual dependency after the active multi-force model; associational, not structural causality."})

    if not inputs.pnl_series.empty and primary in inputs.pnl_series.columns and peer in inputs.pnl_series.columns:
        c, nn = _pair_corr(inputs.pnl_series[primary], inputs.pnl_series[peer], min_obs)
        rows.append({"Space": "P&L risk space", "Correlation": c, "Obs": nn, "Status": "Active",
                     "Interpretation": "Dependency of injected economic P&L series (can embed DV01/CS01/Greeks/notional)."})
    else:
        rows.append({"Space": "P&L risk space", "Correlation": None, "Obs": 0, "Status": "Optional",
                     "Interpretation": "Inject dependency_pnl_series for cross-asset P&L-normalized dependency."})

    return pd.DataFrame(rows)
