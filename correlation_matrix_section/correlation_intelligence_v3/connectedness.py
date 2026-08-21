from __future__ import annotations

import numpy as np
import pandas as pd


# NumPy 2 renamed ``trapz`` to ``trapezoid``. Keep the engine compatible with
# both supported NumPy generations instead of forcing a terminal-wide upgrade.
_trapezoid = getattr(np, "trapezoid", np.trapz)
from statsmodels.tsa.api import VAR

from .estimators import trailing
from .utils import safe_float


def _select_var_lag(data: pd.DataFrame, maxlags: int = 3) -> tuple[int, dict]:
    """Select a parsimonious VAR lag using BIC, with deterministic fallbacks."""
    nobs, nvars = data.shape
    # Keep the model estimable. Each equation has roughly nvars*lag + intercept parameters.
    feasible = max(1, min(int(maxlags), max(1, (nobs - 10) // max(3 * nvars, 1))))
    best_lag = 1
    best_bic = np.inf
    diagnostics: dict[str, float | int | str | bool] = {
        "lag_max_feasible": feasible,
        "lag_selection": "BIC",
    }
    for lag in range(1, feasible + 1):
        try:
            fit = VAR(data).fit(lag, trend="c")
            bic = safe_float(fit.bic)
            if bic is not None and bic < best_bic:
                best_bic = bic
                best_lag = lag
        except Exception:
            continue
    diagnostics["lag"] = best_lag
    diagnostics["bic"] = None if not np.isfinite(best_bic) else float(best_bic)
    return best_lag, diagnostics


def generalized_fevd(
    data: pd.DataFrame,
    horizon: int = 10,
    maxlags: int = 3,
    min_obs: int = 100,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Generalized forecast-error variance decomposition (Pesaran-Shin / Diebold-Yilmaz).

    Rows are receivers i and columns are shock transmitters j. Each row is normalized to 100%.
    """
    if data is None or data.empty:
        return pd.DataFrame(), pd.DataFrame(), {"status": "unavailable"}

    clean = data.apply(pd.to_numeric, errors="coerce").dropna(how="any")
    if len(clean) < min_obs or clean.shape[1] < 2:
        return pd.DataFrame(), pd.DataFrame(), {
            "status": "insufficient_data",
            "obs": int(len(clean)),
            "assets": int(clean.shape[1]),
        }

    # Standardization improves numerical conditioning but does not change the information set.
    std = clean.std(ddof=1).replace(0, np.nan)
    z = ((clean - clean.mean()) / std).dropna(how="any")
    z.index = pd.RangeIndex(len(z))
    if len(z) < min_obs:
        return pd.DataFrame(), pd.DataFrame(), {"status": "insufficient_data", "obs": int(len(z))}

    lag, lag_meta = _select_var_lag(z, maxlags=maxlags)
    try:
        fit = VAR(z).fit(lag, trend="c")
    except Exception as exc:
        return pd.DataFrame(), pd.DataFrame(), {"status": "fit_failed", "error": type(exc).__name__}

    try:
        psi = fit.ma_rep(maxn=max(1, int(horizon) - 1))
        sigma = np.asarray(fit.sigma_u, dtype=float)
    except Exception as exc:
        return pd.DataFrame(), pd.DataFrame(), {"status": "ma_failed", "error": type(exc).__name__}

    k = z.shape[1]
    hmax = min(int(horizon), int(len(psi)))
    theta = np.zeros((k, k), dtype=float)
    sigma_diag = np.clip(np.diag(sigma), 1e-12, None)

    for i in range(k):
        denom = 0.0
        numer = np.zeros(k, dtype=float)
        ei = np.zeros(k); ei[i] = 1.0
        for h in range(hmax):
            ph = np.asarray(psi[h], dtype=float)
            row = ei @ ph
            denom += float(row @ sigma @ row.T)
            for j in range(k):
                ej = np.zeros(k); ej[j] = 1.0
                impact = float(row @ sigma @ ej)
                numer[j] += (impact * impact) / sigma_diag[j]
        if denom > 1e-18:
            theta[i, :] = numer / denom

    row_sums = theta.sum(axis=1, keepdims=True)
    theta_norm = np.divide(theta, row_sums, out=np.zeros_like(theta), where=row_sums > 1e-18)
    theta_pct = 100.0 * theta_norm
    assets = list(z.columns)
    matrix = pd.DataFrame(theta_pct, index=assets, columns=assets)

    from_others = theta_pct.sum(axis=1) - np.diag(theta_pct)
    to_others = theta_pct.sum(axis=0) - np.diag(theta_pct)
    net = to_others - from_others
    table = pd.DataFrame({
        "Asset": assets,
        "FROM others": from_others,
        "TO others": to_others,
        "NET transmitter": net,
        "Own share": np.diag(theta_pct),
    }).sort_values("NET transmitter", ascending=False).reset_index(drop=True)

    tci = float((theta_pct.sum() - np.trace(theta_pct)) / k)
    stable = None
    try:
        stable = bool(fit.is_stable(verbose=False))
    except Exception:
        pass

    meta = {
        "status": "ok",
        "obs": int(len(z)),
        "assets": int(k),
        "forecast_horizon": int(hmax),
        "TCI": tci,
        "VAR lag": int(lag),
        "VAR stable": stable,
        **lag_meta,
    }
    return matrix, table, meta


def connectedness_from_changes(
    changes: pd.DataFrame,
    universe: list[str],
    days: int = 252,
    horizon: int = 10,
    maxlags: int = 3,
    min_obs: int = 100,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    cols = [c for c in universe if c in changes.columns]
    if len(cols) < 2:
        return pd.DataFrame(), pd.DataFrame(), {"status": "insufficient_assets"}
    sample = trailing(changes[cols], days).dropna(how="any")
    return generalized_fevd(sample, horizon=horizon, maxlags=maxlags, min_obs=min_obs)


def partial_network_edges(
    partial_corr: pd.DataFrame,
    type_map: dict[str, str] | None = None,
    threshold: float = 0.12,
    max_edges: int = 50,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Sparse undirected network from partial correlations plus simple centrality diagnostics."""
    if partial_corr is None or partial_corr.empty:
        return pd.DataFrame(), pd.DataFrame()
    c = partial_corr.copy().apply(pd.to_numeric, errors="coerce")
    nodes = list(c.columns)
    rows = []
    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            w = safe_float(c.iloc[i, j])
            if w is None or abs(w) < threshold:
                continue
            a, b = nodes[i], nodes[j]
            rows.append({
                "From": a,
                "To": b,
                "Partial corr": w,
                "Abs weight": abs(w),
                "Cross asset": (type_map or {}).get(a) != (type_map or {}).get(b),
            })
    if not rows:
        return pd.DataFrame(), pd.DataFrame()
    edges = pd.DataFrame(rows).sort_values("Abs weight", ascending=False).head(int(max_edges)).reset_index(drop=True)

    central = []
    for node in nodes:
        incident = edges[(edges["From"] == node) | (edges["To"] == node)]
        signed = 0.0
        for _, r in incident.iterrows():
            signed += float(r["Partial corr"])
        central.append({
            "Asset": node,
            "Type": (type_map or {}).get(node, "Unknown"),
            "Degree": int(len(incident)),
            "Strength": float(incident["Abs weight"].sum()) if len(incident) else 0.0,
            "Signed strength": signed,
            "Cross-asset links": int(incident["Cross asset"].sum()) if len(incident) else 0,
        })
    centrality = pd.DataFrame(central).sort_values(["Strength", "Degree"], ascending=False).reset_index(drop=True)
    return edges, centrality


def spectral_connectedness(
    data: pd.DataFrame,
    maxlags: int = 3,
    min_obs: int = 120,
    n_freq: int = 512,
    bands: tuple[tuple[str, float, float], ...] = (
        ("Short 2-5D", 2*np.pi/5, np.pi),
        ("Medium 5-20D", 2*np.pi/20, 2*np.pi/5),
        ("Long >20D", 0.0, 2*np.pi/20),
    ),
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Barunik-Krehlik style spectral generalized connectedness.

    Two distinct quantities are returned for each disjoint frequency band:

    * ``Within-band connectedness``: the share of *that band's* variance-decomposition
      mass that is cross-variable. This is bounded in [0, 100] but does **not** add up
      across bands.
    * ``Absolute TCI contribution``: the band's contribution in percentage points to
      the aggregate spectral TCI. For a partition covering [0, pi], these contributions
      reconcile (up to numerical quadrature error) to ``spectral_total_TCI``.

    The generalized FEVD is normalized by the *full-spectrum row sums*, not separately
    inside each band. This is the key normalization needed for an additive frequency
    decomposition. The spectral total is an infinite-horizon/stationary VAR object and
    should not be equated mechanically with the finite-horizon FEVD TCI shown elsewhere.
    """
    if data is None or data.empty:
        return pd.DataFrame(), pd.DataFrame(), {"status": "unavailable"}
    clean = data.apply(pd.to_numeric, errors="coerce").dropna(how="any")
    if len(clean) < min_obs or clean.shape[1] < 2:
        return pd.DataFrame(), pd.DataFrame(), {"status": "insufficient_data", "obs": int(len(clean))}

    std = clean.std(ddof=1).replace(0, np.nan)
    z = ((clean - clean.mean()) / std).dropna(how="any")
    z.index = pd.RangeIndex(len(z))
    lag, lag_meta = _select_var_lag(z, maxlags=maxlags)
    try:
        fit = VAR(z).fit(lag, trend="c")
        sigma = np.asarray(fit.sigma_u, dtype=float)
        ar = np.asarray(fit.coefs, dtype=float)
    except Exception as exc:
        return pd.DataFrame(), pd.DataFrame(), {"status": "fit_failed", "error": type(exc).__name__}

    k = z.shape[1]
    # Add exact band boundaries to the Fourier grid. This makes the disjoint-band
    # trapezoidal integrals reconcile much more tightly with the full-spectrum integral.
    bounds = [0.0, np.pi]
    for _, lo, hi in bands:
        bounds.extend([float(lo), float(hi)])
    base = np.linspace(0.0, np.pi, max(64, int(n_freq)), endpoint=True)
    freqs = np.unique(np.concatenate([base, np.asarray(bounds, dtype=float)]))
    freqs.sort()

    sig_diag = np.clip(np.diag(sigma), 1e-12, None)
    causation = np.zeros((len(freqs), k, k), dtype=float)
    spectral_diag = np.zeros((len(freqs), k), dtype=float)
    eye = np.eye(k, dtype=complex)

    for fi, omega in enumerate(freqs):
        poly = eye.copy()
        for l in range(1, lag + 1):
            poly -= ar[l - 1] * np.exp(-1j * omega * l)
        try:
            h = np.linalg.inv(poly)
        except np.linalg.LinAlgError:
            h = np.linalg.pinv(poly)
        hs = h @ sigma
        spec = h @ sigma @ h.conj().T
        denom_i = np.clip(np.real(np.diag(spec)), 1e-18, None)
        spectral_diag[fi, :] = denom_i
        # Generalized causation spectrum f_jk(omega).
        causation[fi, :, :] = (np.abs(hs) ** 2 / sig_diag[None, :]) / denom_i[:, None]

    # Gamma_j(omega): variable-specific spectral-density weight integrating to one
    # over positive frequencies. The common 1/(2pi) scale cancels in the ratio.
    total_spec = _trapezoid(spectral_diag, freqs, axis=0)
    total_spec = np.clip(total_spec, 1e-18, None)
    gamma = spectral_diag / total_spec[None, :]
    theta_density = causation * gamma[:, :, None]

    # Full-spectrum generalized FEVD before row normalization.
    theta_full = _trapezoid(theta_density, freqs, axis=0)
    full_row_sums = theta_full.sum(axis=1)
    full_row_sums = np.clip(full_row_sums, 1e-18, None)
    theta_full_norm = theta_full / full_row_sums[:, None]
    spectral_total_tci = float(100.0 * (theta_full_norm.sum() - np.trace(theta_full_norm)) / k)

    assets = list(z.columns)
    band_rows: list[dict] = []
    directional_rows: list[dict] = []
    long_rows: list[dict] = []

    absolute_sum = 0.0
    mass_sum = 0.0
    for label, lo, hi in bands:
        lo, hi = float(min(lo, hi)), float(max(lo, hi))
        mask = (freqs >= lo - 1e-14) & (freqs <= hi + 1e-14)
        if int(mask.sum()) < 2:
            continue
        theta_band = _trapezoid(theta_density[mask, :, :], freqs[mask], axis=0)
        # Crucially: normalize by FULL-spectrum row sums, not by within-band row sums.
        theta_band_norm = theta_band / full_row_sums[:, None]
        offdiag = theta_band_norm.sum() - np.trace(theta_band_norm)
        total_mass = float(theta_band_norm.sum())
        absolute_tci = float(100.0 * offdiag / k)
        within_tci = float(100.0 * offdiag / total_mass) if total_mass > 1e-18 else 0.0
        mass_pct = float(100.0 * total_mass / k)
        absolute_sum += absolute_tci
        mass_sum += mass_pct

        from_abs = 100.0 * (theta_band_norm.sum(axis=1) - np.diag(theta_band_norm))
        to_abs = 100.0 * (theta_band_norm.sum(axis=0) - np.diag(theta_band_norm))
        net_abs = to_abs - from_abs

        band_rows.append({
            "Band": label,
            "Within-band connectedness": within_tci,
            "Absolute TCI contribution": absolute_tci,
            "Band variance mass": mass_pct,
            "Frequency low": lo,
            "Frequency high": hi,
        })
        for i, asset in enumerate(assets):
            directional_rows.append({
                "Band": label,
                "Asset": asset,
                "FROM absolute contribution": float(from_abs[i]),
                "TO absolute contribution": float(to_abs[i]),
                "NET absolute contribution": float(net_abs[i]),
            })
        for i, receiver in enumerate(assets):
            for j, transmitter in enumerate(assets):
                long_rows.append({
                    "Band": label,
                    "Receiver": receiver,
                    "Transmitter": transmitter,
                    "Normalized contribution": float(100.0 * theta_band_norm[i, j]),
                })

    stable = None
    try:
        stable = bool(fit.is_stable(verbose=False))
    except Exception:
        pass

    recon_error = float(absolute_sum - spectral_total_tci)
    meta = {
        "status": "ok",
        "obs": int(len(z)),
        "assets": int(k),
        "VAR lag": int(lag),
        "VAR stable": stable,
        "bands": [r["Band"] for r in band_rows],
        "spectral_total_TCI": spectral_total_tci,
        "sum_absolute_band_contributions": float(absolute_sum),
        "reconciliation_error": recon_error,
        "sum_band_variance_mass": float(mass_sum),
        "spectral_horizon": "stationary / infinite-horizon",
        "normalization": "full-spectrum generalized FEVD row normalization",
        "matrix_long": pd.DataFrame(long_rows),
        **lag_meta,
    }
    return pd.DataFrame(band_rows), pd.DataFrame(directional_rows), meta

def frequency_connectedness_from_changes(
    changes: pd.DataFrame,
    universe: list[str],
    days: int=504,
    maxlags: int=3,
    min_obs: int=120,
) -> tuple[pd.DataFrame,pd.DataFrame,dict]:
    cols=[c for c in universe if c in changes.columns]
    if len(cols)<2:
        return pd.DataFrame(),pd.DataFrame(),{"status":"insufficient_assets"}
    sample=trailing(changes[cols],days).dropna(how="any")
    return spectral_connectedness(sample,maxlags=maxlags,min_obs=min_obs)


def partial_network_stability(
    changes: pd.DataFrame,
    universe: list[str],
    days: int=252,
    bootstrap_samples: int=120,
    block: int=5,
    threshold: float=0.12,
    selection_threshold: float=0.65,
    seed: int=42,
) -> tuple[pd.DataFrame,dict]:
    """Moving-block bootstrap stability selection for partial-correlation edges."""
    cols=[c for c in universe if c in changes.columns]
    x=trailing(changes[cols],days).dropna(how="any")
    if len(x)<80 or len(cols)<3:
        return pd.DataFrame(),{"status":"insufficient_data","obs":len(x),"assets":len(cols)}
    from .estimators import correlation_matrix
    rng=np.random.default_rng(seed)
    n=len(x); b=max(2,min(int(block),max(2,n//10)))
    starts=np.arange(0,max(1,n-b+1))
    counts={(cols[i],cols[j]):0 for i in range(len(cols)) for j in range(i+1,len(cols))}
    values={k:[] for k in counts}
    valid=0
    for _ in range(int(bootstrap_samples)):
        pieces=[]
        while sum(len(p) for p in pieces)<n:
            s=int(rng.choice(starts)); pieces.append(x.iloc[s:s+b])
        boot=pd.concat(pieces,axis=0).iloc[:n].copy(); boot.index=pd.RangeIndex(n)
        arr=boot.to_numpy(dtype=float)
        cov=np.cov(arr,rowvar=False,ddof=1)
        ridge=max(1e-10,float(np.trace(cov))/max(len(cols),1)*1e-3)
        precision=np.linalg.pinv(cov + ridge*np.eye(len(cols)))
        d=np.sqrt(np.clip(np.diag(precision),1e-18,None))
        parc=-precision/np.outer(d,d); np.fill_diagonal(parc,1.0)
        pc=pd.DataFrame(parc,index=cols,columns=cols)
        valid+=1
        for key in counts:
            a,bb=key; v=safe_float(pc.loc[a,bb])
            if v is not None:
                values[key].append(v)
                if abs(v)>=threshold: counts[key]+=1
    rows=[]
    for (a,bb),count in counts.items():
        vals=np.asarray(values[(a,bb)],dtype=float)
        if len(vals)==0: continue
        freq=count/max(valid,1)
        # Two-sided bootstrap sign probability; then BH controls edge-wise multiplicity approximately.
        p_sign=float(min(1.0,2*min((np.sum(vals<=0)+1)/(len(vals)+1),(np.sum(vals>=0)+1)/(len(vals)+1))))
        rows.append({"From":a,"To":bb,"Selection frequency":freq,"Median partial corr":float(np.median(vals)),"CI low":float(np.quantile(vals,.025)),"CI high":float(np.quantile(vals,.975)),"Sign p-value":p_sign})
    out=pd.DataFrame(rows)
    if not out.empty:
        pvals=out["Sign p-value"].to_numpy(dtype=float); order=np.argsort(pvals); m=len(pvals); q=np.empty(m,dtype=float); running=1.0
        for rank_idx in range(m-1,-1,-1):
            i=order[rank_idx]; rank=rank_idx+1; running=min(running,pvals[i]*m/rank); q[i]=min(1.0,running)
        out["BH q-value"]=q
        out["Stable edge"]=(out["Selection frequency"]>=selection_threshold)
        out["Stat supported"]=out["Stable edge"] & (out["BH q-value"]<=0.10)
        out=out.sort_values(["Stat supported","Stable edge","Selection frequency"],ascending=[False,False,False]).reset_index(drop=True)
    return out,{"status":"ok","bootstrap_valid":valid,"bootstrap_requested":bootstrap_samples,"threshold":threshold,"selection_threshold":selection_threshold,"fdr_level":0.10,"obs":n,"assets":len(cols)}
