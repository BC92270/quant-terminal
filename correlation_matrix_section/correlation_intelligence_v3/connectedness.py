from __future__ import annotations

import numpy as np
import pandas as pd
from statsmodels.stats.diagnostic import acorr_ljungbox


# NumPy 2 renamed ``trapz`` to ``trapezoid``. Keep the engine compatible with
# both supported NumPy generations instead of forcing a terminal-wide upgrade.
_trapezoid = getattr(np, "trapezoid", None)
if _trapezoid is None:  # NumPy < 2.0 compatibility
    _trapezoid = np.trapz
from statsmodels.tsa.api import VAR

from .estimators import trailing
from .utils import safe_float


def _matrix_validation(
    values: np.ndarray,
    *,
    expected_row_sum: float,
    prefix: str,
    atol: float = 1e-6,
) -> dict:
    """Return JSON-safe numerical checks for a row-normalized decomposition.

    The helper is deliberately independent from the VAR implementation so the
    same publication gate is applied to time- and frequency-domain outputs.
    """
    arr = np.asarray(values, dtype=float)
    finite = bool(arr.ndim == 2 and arr.size > 0 and np.isfinite(arr).all())
    nonnegative = bool(finite and np.all(arr >= -atol))
    if finite:
        row_sums = arr.sum(axis=1)
        max_error = float(np.max(np.abs(row_sums - float(expected_row_sum))))
        normalized = bool(np.allclose(row_sums, expected_row_sum, atol=atol, rtol=1e-8))
    else:
        max_error = None
        normalized = False
    return {
        f"{prefix}_finite": finite,
        f"{prefix}_nonnegative": nonnegative,
        f"{prefix}_rows_normalized": normalized,
        f"{prefix}_row_sum_max_error": max_error,
        f"{prefix}_checks_pass": bool(finite and nonnegative and normalized),
    }


def _var_fit_diagnostics(fit, lag: int, columns: list[str]) -> dict:
    """Collect cheap, auditable VAR diagnostics without raising on edge cases."""
    stable = None
    stability_error = None
    try:
        stable = bool(fit.is_stable(verbose=False))
    except Exception as exc:  # pragma: no cover - statsmodels normally implements this
        stability_error = type(exc).__name__

    try:
        sigma = np.asarray(fit.sigma_u, dtype=float)
    except Exception:
        sigma = np.empty((0, 0), dtype=float)
    sigma_finite = bool(sigma.ndim == 2 and sigma.size > 0 and np.isfinite(sigma).all())
    sigma_square = bool(sigma_finite and sigma.shape[0] == sigma.shape[1] == len(columns))
    sigma_condition = None
    sigma_min_eigenvalue = None
    sigma_positive_diagonal = False
    if sigma_square:
        try:
            sigma_condition_raw = float(np.linalg.cond(sigma))
            sigma_condition = sigma_condition_raw if np.isfinite(sigma_condition_raw) else None
            sigma_min_eigenvalue_raw = float(np.linalg.eigvalsh((sigma + sigma.T) / 2.0).min())
            sigma_min_eigenvalue = sigma_min_eigenvalue_raw if np.isfinite(sigma_min_eigenvalue_raw) else None
            sigma_positive_diagonal = bool(np.all(np.diag(sigma) > 0.0))
        except (ValueError, np.linalg.LinAlgError):
            pass

    try:
        residuals = np.asarray(fit.resid, dtype=float)
    except Exception:
        residuals = np.empty((0, len(columns)), dtype=float)
    residuals_finite = bool(
        residuals.ndim == 2
        and residuals.shape[0] > 0
        and residuals.shape[1] == len(columns)
        and np.isfinite(residuals).all()
    )

    lb_lag = None
    lb_pvalues: dict[str, float] = {}
    portmanteau_pvalue = None
    portmanteau_error = None
    if residuals_finite:
        n_resid = int(residuals.shape[0])
        candidate = min(10, max(1, n_resid // 5))
        if candidate <= int(lag) and int(lag) + 1 < n_resid:
            candidate = int(lag) + 1
        if 0 < candidate < n_resid:
            lb_lag = int(candidate)
            for idx, name in enumerate(columns):
                if float(np.std(residuals[:, idx], ddof=0)) <= np.finfo(float).eps:
                    continue
                try:
                    result = acorr_ljungbox(residuals[:, idx], lags=[lb_lag], return_df=True)
                    pvalue = safe_float(result["lb_pvalue"].iloc[-1])
                    if pvalue is not None:
                        lb_pvalues[str(name)] = float(pvalue)
                except Exception:
                    continue
            try:
                whiteness = fit.test_whiteness(nlags=lb_lag, adjusted=True)
                portmanteau_pvalue = safe_float(getattr(whiteness, "pvalue", None))
            except Exception as exc:
                portmanteau_error = type(exc).__name__
    lb_min = min(lb_pvalues.values()) if lb_pvalues else None

    covariance_valid = bool(
        sigma_square
        and sigma_condition is not None
        and sigma_condition <= 1e8
        and sigma_min_eigenvalue is not None
        and sigma_min_eigenvalue > 1e-12
        and sigma_positive_diagonal
    )
    whiteness_available = bool(
        len(lb_pvalues) == len(columns) and portmanteau_pvalue is not None
    )
    whiteness_pass = bool(
        whiteness_available and portmanteau_pvalue is not None and portmanteau_pvalue >= 0.05
    )
    warnings: list[str] = []
    if lb_min is not None and lb_min < 0.05:
        warnings.append("univariate_residual_serial_correlation")
    if portmanteau_pvalue is not None and portmanteau_pvalue < 0.05:
        warnings.append("multivariate_residual_serial_correlation")
    if sigma_condition is not None and sigma_condition > 1e8:
        warnings.append("ill_conditioned_residual_covariance")
    if stable is None:
        warnings.append("stability_check_unavailable")
    if not whiteness_available:
        warnings.append("residual_whiteness_check_unavailable")
    if not residuals_finite:
        warnings.append("non_finite_residuals")
    if not covariance_valid:
        warnings.append("invalid_residual_covariance")

    return {
        "VAR stable": stable,
        "stability_check_error": stability_error,
        "residual_obs": int(residuals.shape[0]) if residuals.ndim == 2 else 0,
        "residuals_finite": residuals_finite,
        "residual_covariance_finite": sigma_finite,
        "residual_covariance_positive_diagonal": sigma_positive_diagonal,
        "residual_covariance_condition": sigma_condition,
        "residual_covariance_min_eigenvalue": sigma_min_eigenvalue,
        "residual_ljung_box_lag": lb_lag,
        "residual_ljung_box_min_pvalue": lb_min,
        "residual_ljung_box_pvalues": lb_pvalues,
        "residual_portmanteau_adjusted": True,
        "residual_portmanteau_pvalue": portmanteau_pvalue,
        "residual_portmanteau_error": portmanteau_error,
        "residual_whiteness_available": whiteness_available,
        "residual_whiteness_pass_5pct": whiteness_pass if whiteness_available else None,
        "fit_diagnostics_ok": bool(
            stable is True and residuals_finite and covariance_valid and whiteness_pass
        ),
        "diagnostic_warnings": warnings,
    }


def _fail_closed_meta(
    status: str,
    reason: str,
    *,
    obs: int,
    assets: int,
    lag: int,
    lag_meta: dict,
    diagnostics: dict,
) -> dict:
    """Build the common non-authoritative result contract."""
    return {
        "status": status,
        "authoritative": False,
        "non_authoritative_reason": reason,
        "obs": int(obs),
        "assets": int(assets),
        "VAR lag": int(lag),
        **lag_meta,
        **diagnostics,
    }


def _select_var_lag(data: pd.DataFrame, maxlags: int = 3) -> tuple[int, dict]:
    """Select BIC among lags that pass the connectedness publication gate.

    If no candidate passes stability, residual covariance and multivariate
    whiteness diagnostics, the ordinary BIC winner is returned so the caller can
    publish an explicit fail-closed reason instead of silently changing models.
    """
    nobs, nvars = data.shape
    # Keep the model estimable. Each equation has roughly nvars*lag + intercept parameters.
    feasible = max(1, min(int(maxlags), max(1, (nobs - 10) // max(3 * nvars, 1))))
    best_any_lag = 1
    best_any_bic = np.inf
    best_valid_lag = None
    best_valid_bic = np.inf
    candidate_rows: list[dict] = []
    diagnostics: dict = {
        "lag_max_feasible": feasible,
        "lag_selection": "BIC among publication-gate-admissible candidates",
    }
    for lag in range(1, feasible + 1):
        try:
            fit = VAR(data).fit(lag, trend="c")
            bic = safe_float(fit.bic)
            fit_diag = _var_fit_diagnostics(fit, lag, list(data.columns))
            admissible = bool(fit_diag.get("fit_diagnostics_ok"))
            candidate_rows.append({
                "lag": int(lag),
                "bic": bic,
                "admissible": admissible,
                "stable": fit_diag.get("VAR stable"),
                "portmanteau_pvalue": fit_diag.get("residual_portmanteau_pvalue"),
                "covariance_condition": fit_diag.get("residual_covariance_condition"),
            })
            if bic is not None and bic < best_any_bic:
                best_any_bic = bic
                best_any_lag = lag
            if admissible and bic is not None and bic < best_valid_bic:
                best_valid_bic = bic
                best_valid_lag = lag
        except Exception as exc:
            candidate_rows.append({
                "lag": int(lag), "bic": None, "admissible": False,
                "error": type(exc).__name__,
            })
            continue
    if best_valid_lag is not None:
        selected_lag = int(best_valid_lag)
        selected_bic = best_valid_bic
        diagnostics["lag_selection_status"] = "admissible_candidate_selected"
    else:
        selected_lag = int(best_any_lag)
        selected_bic = best_any_bic
        diagnostics["lag_selection_status"] = "no_admissible_candidate_fail_closed"
    diagnostics["lag"] = selected_lag
    diagnostics["bic"] = None if not np.isfinite(selected_bic) else float(selected_bic)
    diagnostics["lag_candidates"] = candidate_rows
    diagnostics["admissible_lag_count"] = int(sum(bool(row.get("admissible")) for row in candidate_rows))
    return selected_lag, diagnostics


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
    std = clean.std(ddof=1)
    scale_floor = 10.0 * np.finfo(float).eps * clean.abs().max().clip(lower=1.0)
    std = std.where(std.abs() > scale_floor, np.nan)
    z = ((clean - clean.mean()) / std).dropna(how="any")
    z.index = pd.RangeIndex(len(z))
    if len(z) < min_obs:
        return pd.DataFrame(), pd.DataFrame(), {"status": "insufficient_data", "obs": int(len(z))}

    lag, lag_meta = _select_var_lag(z, maxlags=maxlags)
    try:
        fit = VAR(z).fit(lag, trend="c")
    except Exception as exc:
        return pd.DataFrame(), pd.DataFrame(), {"status": "fit_failed", "error": type(exc).__name__}

    assets = list(z.columns)
    fit_diagnostics = _var_fit_diagnostics(fit, lag, assets)
    if fit_diagnostics["VAR stable"] is not True:
        return pd.DataFrame(), pd.DataFrame(), _fail_closed_meta(
            "unstable_var" if fit_diagnostics["VAR stable"] is False else "stability_unverified",
            "VAR stability failed or could not be verified; connectedness output suppressed.",
            obs=len(z), assets=len(assets), lag=lag, lag_meta=lag_meta,
            diagnostics=fit_diagnostics,
        )
    if not fit_diagnostics["fit_diagnostics_ok"]:
        return pd.DataFrame(), pd.DataFrame(), _fail_closed_meta(
            "invalid_var_diagnostics",
            "Residual whiteness, residuals, or residual covariance failed the publication gate; connectedness output suppressed.",
            obs=len(z), assets=len(assets), lag=lag, lag_meta=lag_meta,
            diagnostics=fit_diagnostics,
        )

    try:
        psi = fit.ma_rep(maxn=max(1, int(horizon) - 1))
        sigma = np.asarray(fit.sigma_u, dtype=float)
    except Exception as exc:
        return pd.DataFrame(), pd.DataFrame(), {"status": "ma_failed", "error": type(exc).__name__}

    k = z.shape[1]
    hmax = max(1, min(max(1, int(horizon)), int(len(psi))))
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
    fevd_checks = _matrix_validation(theta_pct, expected_row_sum=100.0, prefix="fevd")
    if not fevd_checks["fevd_checks_pass"]:
        return pd.DataFrame(), pd.DataFrame(), _fail_closed_meta(
            "invalid_fevd",
            "Generalized FEVD failed finite, non-negativity, or row-normalization checks.",
            obs=len(z), assets=len(assets), lag=lag, lag_meta=lag_meta,
            diagnostics={**fit_diagnostics, **fevd_checks},
        )
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
    meta = {
        "status": "ok",
        "authoritative": True,
        "obs": int(len(z)),
        "assets": int(k),
        "forecast_horizon": int(hmax),
        "TCI": tci,
        "VAR lag": int(lag),
        **lag_meta,
        **fit_diagnostics,
        **fevd_checks,
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

    std = clean.std(ddof=1)
    scale_floor = 10.0 * np.finfo(float).eps * clean.abs().max().clip(lower=1.0)
    std = std.where(std.abs() > scale_floor, np.nan)
    z = ((clean - clean.mean()) / std).dropna(how="any")
    z.index = pd.RangeIndex(len(z))
    if len(z) < min_obs:
        return pd.DataFrame(), pd.DataFrame(), {
            "status": "insufficient_data",
            "obs": int(len(z)),
            "assets": int(z.shape[1]),
        }
    lag, lag_meta = _select_var_lag(z, maxlags=maxlags)
    try:
        fit = VAR(z).fit(lag, trend="c")
    except Exception as exc:
        return pd.DataFrame(), pd.DataFrame(), {"status": "fit_failed", "error": type(exc).__name__}

    assets = list(z.columns)
    fit_diagnostics = _var_fit_diagnostics(fit, lag, assets)
    if fit_diagnostics["VAR stable"] is not True:
        meta = _fail_closed_meta(
            "unstable_var" if fit_diagnostics["VAR stable"] is False else "stability_unverified",
            "VAR stability failed or could not be verified; spectral connectedness output suppressed.",
            obs=len(z), assets=len(assets), lag=lag, lag_meta=lag_meta,
            diagnostics=fit_diagnostics,
        )
        meta["matrix_long"] = pd.DataFrame()
        return pd.DataFrame(), pd.DataFrame(), meta
    if not fit_diagnostics["fit_diagnostics_ok"]:
        meta = _fail_closed_meta(
            "invalid_var_diagnostics",
            "Residual whiteness, residuals, or residual covariance failed the publication gate; spectral output suppressed.",
            obs=len(z), assets=len(assets), lag=lag, lag_meta=lag_meta,
            diagnostics=fit_diagnostics,
        )
        meta["matrix_long"] = pd.DataFrame()
        return pd.DataFrame(), pd.DataFrame(), meta

    try:
        sigma = np.asarray(fit.sigma_u, dtype=float)
        ar = np.asarray(fit.coefs, dtype=float)
    except Exception as exc:
        return pd.DataFrame(), pd.DataFrame(), {"status": "coefficient_failed", "error": type(exc).__name__}

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

    spectral_checks = _matrix_validation(theta_full_norm, expected_row_sum=1.0, prefix="spectral_fevd")
    band_values = pd.DataFrame(band_rows)
    band_finite = bool(
        not band_values.empty
        and np.isfinite(
            band_values[[
                "Within-band connectedness",
                "Absolute TCI contribution",
                "Band variance mass",
            ]].to_numpy(dtype=float)
        ).all()
    )
    spectral_tci_valid = bool(np.isfinite(spectral_total_tci) and -1e-8 <= spectral_total_tci <= 100.0 + 1e-8)
    spectral_checks.update({
        "spectral_band_values_finite": band_finite,
        "spectral_total_tci_bounded": spectral_tci_valid,
    })
    if not spectral_checks["spectral_fevd_checks_pass"] or not band_finite or not spectral_tci_valid:
        meta = _fail_closed_meta(
            "invalid_spectral_fevd",
            "Spectral FEVD failed finite, boundedness, or row-normalization checks.",
            obs=len(z), assets=len(assets), lag=lag, lag_meta=lag_meta,
            diagnostics={**fit_diagnostics, **spectral_checks},
        )
        meta["matrix_long"] = pd.DataFrame()
        return pd.DataFrame(), pd.DataFrame(), meta

    recon_error = float(absolute_sum - spectral_total_tci)
    meta = {
        "status": "ok",
        "authoritative": True,
        "obs": int(len(z)),
        "assets": int(k),
        "VAR lag": int(lag),
        "bands": [r["Band"] for r in band_rows],
        "spectral_total_TCI": spectral_total_tci,
        "sum_absolute_band_contributions": float(absolute_sum),
        "reconciliation_error": recon_error,
        "sum_band_variance_mass": float(mass_sum),
        "spectral_horizon": "stationary / infinite-horizon",
        "normalization": "full-spectrum generalized FEVD row normalization",
        "matrix_long": pd.DataFrame(long_rows),
        **lag_meta,
        **fit_diagnostics,
        **spectral_checks,
    }
    return band_values, pd.DataFrame(directional_rows), meta

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
    rng=np.random.default_rng(seed)
    n=len(x); b=max(2,min(int(block),max(2,n//10)))
    starts=np.arange(0,max(1,n-b+1))
    pair_left,pair_right=np.triu_indices(len(cols),1)
    pair_count=len(pair_left)
    requested=max(0,int(bootstrap_samples))
    values=np.full((requested,pair_count),np.nan,dtype=float)
    counts=np.zeros(pair_count,dtype=int)
    arr=x.to_numpy(dtype=float)
    blocks=int(np.ceil(n/b))
    offsets=np.arange(b,dtype=int)
    valid=0
    for sample in range(requested):
        sampled_starts=rng.choice(starts,size=blocks,replace=True)
        indices=(sampled_starts[:,None]+offsets[None,:]).reshape(-1)[:n]
        boot=arr[indices]
        cov=np.cov(boot,rowvar=False,ddof=1)
        ridge=max(1e-10,float(np.trace(cov))/max(len(cols),1)*1e-3)
        precision=np.linalg.pinv(cov + ridge*np.eye(len(cols)))
        d=np.sqrt(np.clip(np.diag(precision),1e-18,None))
        parc=-precision/np.outer(d,d); np.fill_diagonal(parc,1.0)
        pair_values=parc[pair_left,pair_right]
        finite=np.isfinite(pair_values)
        values[sample,finite]=pair_values[finite]
        counts[finite]+=np.abs(pair_values[finite])>=threshold
        valid+=1
    rows=[]
    for pair_position,(left,right) in enumerate(zip(pair_left,pair_right)):
        a,bb=cols[int(left)],cols[int(right)]
        vals=values[:,pair_position]
        vals=vals[np.isfinite(vals)]
        if len(vals)==0: continue
        freq=float(counts[pair_position]/max(valid,1))
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
