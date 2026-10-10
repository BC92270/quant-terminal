from __future__ import annotations

"""Dynamic heavy-tail dependence diagnostics.

This module deliberately has *research diagnostic* authority only.  It combines
bounded-influence Student-t GARCH filters, a constrained DCC(1,1) estimator, an
optional PCA reconstruction for large panels, and rolling Student-t copula
diagnostics.  A failed optimiser or numerical gate never falls back to an
apparently valid dynamic correlation path.

The implementation only depends on NumPy, pandas, SciPy and statsmodels so it can
be integrated into the existing Correlation Intelligence package without adding
an opaque volatility dependency.
"""

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats
from scipy.optimize import OptimizeResult, minimize
from scipy.special import gammaln
from statsmodels.stats.diagnostic import acorr_ljungbox


AUTHORITY = "RESEARCH_ONLY"
_NUMERICAL_FLOOR = 1e-10


@dataclass(frozen=True)
class GarchFilterResult:
    """Auditable output of one robust Student-t GARCH(1,1) filter."""

    conditional_variance: pd.Series
    standardized_residuals: pd.Series
    parameters: dict[str, float]
    metadata: dict[str, Any]


@dataclass(frozen=True)
class DynamicCorrelationResult:
    """DCC output; an empty correlation matrix means the fit was rejected."""

    latest_correlation: pd.DataFrame
    average_correlation: pd.DataFrame
    correlation_path: pd.DataFrame
    standardized_residuals: pd.DataFrame
    factor_loadings: pd.DataFrame
    metadata: dict[str, Any]


@dataclass(frozen=True)
class RollingTCopulaResult:
    """Rolling bivariate Student-t copula estimates and governance metadata."""

    diagnostics: pd.DataFrame
    metadata: dict[str, Any]


def _research_metadata(**updates: Any) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "authority": AUTHORITY,
        "decision_authority": "NONE",
        "portfolio_eligible": False,
        "execution_eligible": False,
        "forward_looking": False,
        "research_only": True,
    }
    metadata.update(updates)
    return metadata


def _empty_garch(status: str, obs: int, reason: str) -> GarchFilterResult:
    return GarchFilterResult(
        conditional_variance=pd.Series(dtype=float, name="conditional_variance"),
        standardized_residuals=pd.Series(dtype=float, name="standardized_residual"),
        parameters={},
        metadata=_research_metadata(
            status=status,
            accepted=False,
            diagnostic_eligible=False,
            observations=int(obs),
            rejection_reason=reason,
            model="robust Student-t GARCH(1,1)",
        ),
    )


def _robust_scale(values: np.ndarray) -> tuple[float, str]:
    median = float(np.median(values))
    mad = float(np.median(np.abs(values - median))) * 1.482602218505602
    if np.isfinite(mad) and mad > 1e-12:
        return mad, "MAD"
    std = float(np.std(values, ddof=1))
    if np.isfinite(std) and std > 1e-12:
        return std, "standard_deviation_fallback"
    return np.nan, "degenerate"


def _garch_variance_path(
    values: np.ndarray,
    mu: float,
    omega: float,
    alpha: float,
    beta: float,
    initial_variance: float,
    shock_cap: float,
) -> np.ndarray:
    """Bounded-influence GARCH recursion on robustly scaled observations."""

    n = len(values)
    variance = np.empty(n, dtype=float)
    unconditional = omega / max(1.0 - alpha - beta, 1e-6)
    variance[0] = max(float(initial_variance), float(unconditional), _NUMERICAL_FLOOR)
    for position in range(1, n):
        innovation2 = float((values[position - 1] - mu) ** 2)
        # A single bad print cannot inject unbounded energy into every later date.
        bounded_shock = min(innovation2, float(shock_cap) * variance[position - 1])
        variance[position] = omega + alpha * bounded_shock + beta * variance[position - 1]
        if not np.isfinite(variance[position]) or variance[position] <= _NUMERICAL_FLOOR:
            variance[position] = _NUMERICAL_FLOOR
    return variance


def _standardized_t_log_density(residual: np.ndarray, variance: np.ndarray, nu: float) -> np.ndarray:
    """Log density for a Student-t innovation standardised to unit variance."""

    scale_term = max(float(nu) - 2.0, 1e-8)
    constant = (
        gammaln((nu + 1.0) / 2.0)
        - gammaln(nu / 2.0)
        - 0.5 * np.log(np.pi * scale_term)
    )
    return (
        constant
        - 0.5 * np.log(variance)
        - 0.5 * (nu + 1.0) * np.log1p((residual * residual) / (variance * scale_term))
    )


def _ljung_box_pvalue(values: np.ndarray, lag: int) -> float | None:
    if len(values) <= lag + 5 or not np.isfinite(values).all():
        return None
    try:
        table = acorr_ljungbox(values, lags=[int(lag)], return_df=True)
        value = float(table["lb_pvalue"].iloc[-1])
        return value if np.isfinite(value) else None
    except Exception:
        return None


def fit_robust_garch(
    series: pd.Series,
    *,
    min_obs: int = 120,
    maxiter: int = 500,
    shock_cap: float = 25.0,
) -> GarchFilterResult:
    """Fit a bounded-influence Student-t GARCH(1,1) volatility filter.

    The likelihood uses variance-standardised Student-t innovations.  The shock
    entering the variance recursion is capped relative to prior conditional
    variance; this limits propagation from isolated data errors while preserving
    the original observation in the reported standardised residual.
    """

    clean = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if len(clean) < int(min_obs):
        return _empty_garch("insufficient_data", len(clean), f"requires at least {int(min_obs)} observations")
    raw = clean.to_numpy(dtype=float)
    scale, scale_method = _robust_scale(raw)
    if not np.isfinite(scale) or scale <= 1e-12:
        return _empty_garch("rejected", len(clean), "degenerate unconditional scale")

    center = float(np.median(raw))
    values = (raw - center) / scale
    clipped = np.clip(values, -8.0, 8.0)
    initial_variance = float(np.mean((clipped - np.median(clipped)) ** 2))
    initial_variance = max(initial_variance, 1e-4)

    def objective(theta: np.ndarray) -> float:
        mu, omega, alpha, beta, nu = [float(value) for value in theta]
        if (
            omega <= 0.0
            or alpha < 0.0
            or beta < 0.0
            or alpha + beta >= 0.998
            or nu <= 2.05
        ):
            return 1e30
        variance = _garch_variance_path(
            values, mu, omega, alpha, beta, initial_variance, shock_cap
        )
        log_density = _standardized_t_log_density(values - mu, variance, nu)
        if not np.isfinite(log_density).all():
            return 1e30
        return -float(np.sum(log_density))

    upper_omega = max(10.0 * initial_variance, 1.0)
    bounds = [
        (-3.0, 3.0),
        (1e-8, upper_omega),
        (1e-7, 0.50),
        (1e-7, 0.997),
        (2.051, 80.0),
    ]
    starts: list[np.ndarray] = []
    for alpha, beta, nu in ((0.05, 0.90, 8.0), (0.10, 0.80, 5.0), (0.02, 0.95, 15.0)):
        omega = max(initial_variance * (1.0 - alpha - beta), 1e-5)
        starts.append(np.asarray([float(np.mean(clipped)), omega, alpha, beta, nu]))

    attempts: list[OptimizeResult] = []
    constraint = {"type": "ineq", "fun": lambda theta: 0.998 - theta[2] - theta[3]}
    for start in starts:
        try:
            result = minimize(
                objective,
                start,
                method="SLSQP",
                bounds=bounds,
                constraints=constraint,
                options={"maxiter": int(maxiter), "ftol": 1e-9, "disp": False},
            )
            attempts.append(result)
        except Exception:
            continue

    finite_attempts = [result for result in attempts if np.isfinite(result.fun)]
    if not finite_attempts:
        return _empty_garch("rejected", len(clean), "all optimisation attempts failed numerically")
    successful = [result for result in finite_attempts if bool(result.success)]
    best = min(successful or finite_attempts, key=lambda result: float(result.fun))
    mu, omega, alpha, beta, nu = [float(value) for value in best.x]
    persistence = alpha + beta
    constraints_ok = (
        omega > 0.0
        and alpha >= 0.0
        and beta >= 0.0
        and persistence < 0.998
        and 2.05 < nu <= 80.0
    )
    accepted = bool(best.success and constraints_ok)
    if not accepted:
        return GarchFilterResult(
            conditional_variance=pd.Series(dtype=float, name="conditional_variance"),
            standardized_residuals=pd.Series(dtype=float, name="standardized_residual"),
            parameters={},
            metadata=_research_metadata(
                status="rejected",
                accepted=False,
                diagnostic_eligible=False,
                observations=int(len(clean)),
                rejection_reason="optimizer or stationarity gate failed",
                optimizer_success=bool(best.success),
                optimizer_message=str(best.message),
                attempts=int(len(attempts)),
                constraints_ok=bool(constraints_ok),
                model="robust Student-t GARCH(1,1)",
            ),
        )

    variance_scaled = _garch_variance_path(
        values, mu, omega, alpha, beta, initial_variance, shock_cap
    )
    residual_scaled = values - mu
    standardized = residual_scaled / np.sqrt(variance_scaled)
    variance_raw = variance_scaled * scale * scale
    conditional_variance = pd.Series(
        variance_raw, index=clean.index, name="conditional_variance"
    )
    standardized_series = pd.Series(
        standardized, index=clean.index, name="standardized_residual"
    )
    lag = max(1, min(10, len(standardized) // 5))
    log_likelihood = -float(best.fun)
    parameters = {
        "mu": float(center + mu * scale),
        "omega": float(omega * scale * scale),
        "alpha": alpha,
        "beta": beta,
        "nu": nu,
        "persistence": persistence,
    }
    metadata = _research_metadata(
        status="ok",
        accepted=True,
        diagnostic_eligible=True,
        observations=int(len(clean)),
        model="bounded-influence Student-t GARCH(1,1)",
        optimizer="SLSQP with three deterministic starts",
        optimizer_success=True,
        optimizer_message=str(best.message),
        iterations=int(getattr(best, "nit", 0) or 0),
        attempts=int(len(attempts)),
        successful_attempts=int(len(successful)),
        constraints_ok=True,
        stationarity_constraint="alpha + beta < 0.998",
        scale_method=scale_method,
        robust_shock_cap=float(shock_cap),
        log_likelihood=log_likelihood,
        aic=float(2 * 5 - 2 * log_likelihood),
        bic=float(np.log(len(clean)) * 5 - 2 * log_likelihood),
        residual_ljung_box_pvalue=_ljung_box_pvalue(standardized, lag),
        squared_residual_ljung_box_pvalue=_ljung_box_pvalue(standardized**2, lag),
        residual_test_lag=int(lag),
        finite_path=bool(np.isfinite(variance_raw).all() and np.isfinite(standardized).all()),
    )
    return GarchFilterResult(conditional_variance, standardized_series, parameters, metadata)


def _nearest_correlation(matrix: np.ndarray, floor: float = 1e-8) -> np.ndarray:
    value = np.asarray(matrix, dtype=float)
    value = np.nan_to_num(0.5 * (value + value.T), nan=0.0, posinf=0.0, neginf=0.0)
    eigenvalues, eigenvectors = np.linalg.eigh(value)
    eigenvalues = np.clip(eigenvalues, float(floor), None)
    value = (eigenvectors * eigenvalues) @ eigenvectors.T
    scale = np.sqrt(np.clip(np.diag(value), float(floor), None))
    value = value / np.outer(scale, scale)
    value = np.clip(0.5 * (value + value.T), -0.999999, 0.999999)
    np.fill_diagonal(value, 1.0)
    return value


def _dcc_path(innovations: np.ndarray, alpha: float, beta: float) -> np.ndarray:
    n, dimension = innovations.shape
    unconditional = _nearest_correlation(np.corrcoef(innovations, rowvar=False))
    q_matrix = unconditional.copy()
    path = np.empty((n, dimension, dimension), dtype=float)
    path[0] = unconditional
    for position in range(1, n):
        previous = innovations[position - 1][:, None]
        q_matrix = (
            (1.0 - alpha - beta) * unconditional
            + alpha * (previous @ previous.T)
            + beta * q_matrix
        )
        diagonal = np.sqrt(np.clip(np.diag(q_matrix), _NUMERICAL_FLOOR, None))
        correlation = q_matrix / np.outer(diagonal, diagonal)
        # Under the enforced DCC simplex (alpha >= 0, beta >= 0,
        # alpha + beta < 1), Q_t is a positive-definite convex combination of
        # the regularised unconditional matrix and positive-semidefinite outer
        # products. Re-projecting every observation through an eigendecomposition
        # is therefore redundant and made interactive estimation prohibitively
        # expensive. Keep the exact normalisation here; the final publication
        # gate still checks every emitted matrix for finiteness and positive
        # definiteness and fails closed if numerical assumptions are violated.
        correlation = 0.5 * (correlation + correlation.T)
        np.fill_diagonal(correlation, 1.0)
        path[position] = correlation
    return path


def _dcc_objective(theta: np.ndarray, innovations: np.ndarray) -> float:
    alpha, beta = [float(value) for value in theta]
    if alpha < 0.0 or beta < 0.0 or alpha + beta >= 0.999:
        return 1e30
    path = _dcc_path(innovations, alpha, beta)
    objective = 0.0
    for position in range(1, len(innovations)):
        correlation = path[position]
        sign, log_determinant = np.linalg.slogdet(correlation)
        if sign <= 0 or not np.isfinite(log_determinant):
            return 1e30
        try:
            solved = np.linalg.solve(correlation, innovations[position])
        except np.linalg.LinAlgError:
            return 1e30
        objective += log_determinant + float(innovations[position] @ solved)
    return 0.5 * float(objective)


def _factor_reduce(
    innovations: np.ndarray,
    columns: list[str],
    variance_threshold: float,
    max_components: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, pd.DataFrame, dict[str, Any]]:
    covariance = np.cov(innovations, rowvar=False, ddof=1)
    eigenvalues, eigenvectors = np.linalg.eigh(0.5 * (covariance + covariance.T))
    order = np.argsort(eigenvalues)[::-1]
    eigenvalues = np.clip(eigenvalues[order], _NUMERICAL_FLOOR, None)
    eigenvectors = eigenvectors[:, order]
    cumulative = np.cumsum(eigenvalues) / max(float(np.sum(eigenvalues)), _NUMERICAL_FLOOR)
    selected = int(np.searchsorted(cumulative, float(variance_threshold), side="left") + 1)
    selected = max(2, min(selected, int(max_components), len(columns) - 1))
    selected_values = eigenvalues[:selected]
    selected_vectors = eigenvectors[:, :selected]
    scores = innovations @ selected_vectors
    scores = scores / np.sqrt(selected_values)[None, :]
    scores -= np.mean(scores, axis=0, keepdims=True)
    scores /= np.std(scores, axis=0, ddof=1, keepdims=True) + 1e-12
    loadings = selected_vectors * np.sqrt(selected_values)[None, :]
    common_covariance = loadings @ loadings.T
    idiosyncratic = np.clip(np.diag(covariance - common_covariance), 1e-6, None)
    factor_names = [f"PC{position + 1}" for position in range(selected)]
    loading_frame = pd.DataFrame(loadings, index=columns, columns=factor_names)
    metadata = {
        "method": "PCA dynamic-factor reconstruction",
        "components": int(selected),
        "variance_threshold": float(variance_threshold),
        "variance_explained": float(cumulative[selected - 1]),
        "eigenvalues": [float(value) for value in selected_values],
    }
    return scores, loadings, idiosyncratic, loading_frame, metadata


def _reconstruct_asset_path(
    factor_path: np.ndarray,
    loadings: np.ndarray,
    idiosyncratic_variance: np.ndarray,
) -> np.ndarray:
    observations = factor_path.shape[0]
    assets = loadings.shape[0]
    output = np.empty((observations, assets, assets), dtype=float)
    residual_covariance = np.diag(idiosyncratic_variance)
    for position in range(observations):
        covariance = loadings @ factor_path[position] @ loadings.T + residual_covariance
        diagonal = np.sqrt(np.clip(np.diag(covariance), _NUMERICAL_FLOOR, None))
        output[position] = _nearest_correlation(covariance / np.outer(diagonal, diagonal))
    return output


def _path_to_frame(path: np.ndarray, index: pd.Index, columns: list[str]) -> pd.DataFrame:
    pairs = [(columns[left], columns[right]) for left in range(len(columns)) for right in range(left + 1, len(columns))]
    multi_columns = pd.MultiIndex.from_tuples(pairs, names=["asset_i", "asset_j"])
    values = np.column_stack(
        [path[:, left, right] for left in range(len(columns)) for right in range(left + 1, len(columns))]
    )
    return pd.DataFrame(values, index=index, columns=multi_columns)


def _empty_dynamic(
    status: str,
    reason: str,
    observations: int,
    assets: int,
    *,
    standardized_residuals: pd.DataFrame | None = None,
    extra: dict[str, Any] | None = None,
) -> DynamicCorrelationResult:
    metadata = _research_metadata(
        status=status,
        accepted=False,
        diagnostic_eligible=False,
        observations=int(observations),
        assets=int(assets),
        rejection_reason=reason,
        model="robust GARCH + constrained DCC(1,1)",
    )
    if extra:
        metadata.update(extra)
    return DynamicCorrelationResult(
        latest_correlation=pd.DataFrame(),
        average_correlation=pd.DataFrame(),
        correlation_path=pd.DataFrame(),
        standardized_residuals=(standardized_residuals if standardized_residuals is not None else pd.DataFrame()),
        factor_loadings=pd.DataFrame(),
        metadata=metadata,
    )


def fit_dynamic_dcc(
    changes: pd.DataFrame,
    *,
    days: int | None = None,
    min_obs: int = 120,
    max_direct_assets: int = 12,
    min_observations_per_dimension: float = 15.0,
    factor_variance_threshold: float = 0.85,
    factor_max_components: int = 8,
    garch_maxiter: int = 500,
    dcc_maxiter: int = 350,
    shock_cap: float = 25.0,
) -> DynamicCorrelationResult:
    """Estimate a robust GARCH-DCC diagnostic with large-panel reduction.

    The common panel and every univariate filter must pass before DCC is fitted.
    When the cross-section is too wide, DCC is estimated on standardised PCA
    factors and reconstructed with diagonal idiosyncratic risk.  The reconstructed
    path keeps the original asset labels but remains ``RESEARCH_ONLY``.
    """

    if changes is None or changes.empty:
        return _empty_dynamic("insufficient_data", "empty input", 0, 0)
    panel = changes.copy()
    if days is not None:
        panel = panel.tail(int(days))
    panel = panel.apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)
    panel = panel.dropna(axis=1, thresh=int(min_obs)).dropna(how="any")
    observations, assets = panel.shape
    if observations < int(min_obs):
        return _empty_dynamic(
            "insufficient_data",
            f"common panel requires at least {int(min_obs)} observations",
            observations,
            assets,
        )
    if assets < 2:
        return _empty_dynamic("insufficient_assets", "requires at least two eligible assets", observations, assets)

    filters: dict[str, GarchFilterResult] = {}
    failed: dict[str, str] = {}
    for column in panel.columns:
        fitted = fit_robust_garch(
            panel[column], min_obs=min_obs, maxiter=garch_maxiter, shock_cap=shock_cap
        )
        filters[str(column)] = fitted
        if not bool(fitted.metadata.get("accepted")):
            failed[str(column)] = str(fitted.metadata.get("rejection_reason", "filter rejected"))
    filter_summary = {
        name: {
            "status": result.metadata.get("status"),
            "accepted": bool(result.metadata.get("accepted")),
            "alpha": result.parameters.get("alpha"),
            "beta": result.parameters.get("beta"),
            "nu": result.parameters.get("nu"),
            "persistence": result.parameters.get("persistence"),
            "squared_residual_ljung_box_pvalue": result.metadata.get("squared_residual_ljung_box_pvalue"),
        }
        for name, result in filters.items()
    }
    if failed:
        return _empty_dynamic(
            "rejected",
            "one or more univariate volatility filters failed",
            observations,
            assets,
            extra={"failed_assets": failed, "garch_filters": filter_summary},
        )

    standardized = pd.concat(
        [filters[str(column)].standardized_residuals.rename(column) for column in panel.columns],
        axis=1,
        join="inner",
    ).dropna(how="any")
    if len(standardized) < int(min_obs):
        return _empty_dynamic(
            "rejected",
            "too few aligned standardised residuals",
            len(standardized),
            assets,
            standardized_residuals=standardized,
            extra={"garch_filters": filter_summary},
        )
    innovations = standardized.to_numpy(dtype=float)
    innovations -= np.mean(innovations, axis=0, keepdims=True)
    innovations /= np.std(innovations, axis=0, ddof=1, keepdims=True) + 1e-12
    innovations = np.clip(innovations, -10.0, 10.0)
    standardized = pd.DataFrame(innovations, index=standardized.index, columns=standardized.columns)

    high_dimension = (
        assets > int(max_direct_assets)
        or observations / max(assets, 1) < float(min_observations_per_dimension)
    )
    factor_loadings = pd.DataFrame()
    factor_metadata: dict[str, Any] = {
        "method": "none",
        "components": int(assets),
        "variance_explained": 1.0,
    }
    loadings: np.ndarray | None = None
    idiosyncratic: np.ndarray | None = None
    dcc_innovations = innovations
    if high_dimension:
        component_cap = max(2, min(int(factor_max_components), int(max_direct_assets), assets - 1))
        (
            dcc_innovations,
            loadings,
            idiosyncratic,
            factor_loadings,
            factor_metadata,
        ) = _factor_reduce(
            innovations,
            [str(column) for column in standardized.columns],
            factor_variance_threshold,
            component_cap,
        )

    attempts: list[OptimizeResult] = []
    constraint = {"type": "ineq", "fun": lambda theta: 0.999 - theta[0] - theta[1]}
    for start in (np.asarray([0.03, 0.94]), np.asarray([0.08, 0.85]), np.asarray([0.15, 0.70])):
        try:
            result = minimize(
                _dcc_objective,
                start,
                args=(dcc_innovations,),
                method="SLSQP",
                bounds=[(1e-7, 0.40), (1e-7, 0.998)],
                constraints=constraint,
                options={"maxiter": int(dcc_maxiter), "ftol": 1e-9, "disp": False},
            )
            attempts.append(result)
        except Exception:
            continue
    finite_attempts = [result for result in attempts if np.isfinite(result.fun)]
    successful = [result for result in finite_attempts if bool(result.success)]
    if not successful:
        messages = [str(result.message) for result in finite_attempts]
        return _empty_dynamic(
            "rejected",
            "DCC optimiser did not converge; no fallback path emitted",
            observations,
            assets,
            standardized_residuals=standardized,
            extra={
                "optimizer_messages": messages,
                "optimizer_attempts": int(len(attempts)),
                "garch_filters": filter_summary,
                "factor_reduction_applied": bool(high_dimension),
                "factor_reduction": factor_metadata,
            },
        )

    best = min(successful, key=lambda result: float(result.fun))
    alpha, beta = [float(value) for value in best.x]
    persistence = alpha + beta
    constraints_ok = alpha >= 0.0 and beta >= 0.0 and persistence < 0.999
    if not constraints_ok:
        return _empty_dynamic(
            "rejected",
            "DCC stationarity constraint failed",
            observations,
            assets,
            standardized_residuals=standardized,
            extra={"garch_filters": filter_summary},
        )

    fitted_path = _dcc_path(dcc_innovations, alpha, beta)
    if high_dimension:
        assert loadings is not None and idiosyncratic is not None
        asset_path = _reconstruct_asset_path(fitted_path, loadings, idiosyncratic)
    else:
        asset_path = fitted_path
    eigenvalue_minima = np.asarray(
        [np.linalg.eigvalsh(matrix).min() for matrix in asset_path], dtype=float
    )
    condition_numbers = np.asarray([np.linalg.cond(matrix) for matrix in asset_path], dtype=float)
    numerical_gate = bool(
        np.isfinite(asset_path).all()
        and np.isfinite(eigenvalue_minima).all()
        and np.isfinite(condition_numbers).all()
        and float(eigenvalue_minima.min()) > 0.0
    )
    if not numerical_gate:
        return _empty_dynamic(
            "rejected",
            "dynamic correlation path failed the finite positive-definite gate",
            observations,
            assets,
            standardized_residuals=standardized,
            extra={"garch_filters": filter_summary},
        )

    names = [str(column) for column in standardized.columns]
    latest = pd.DataFrame(asset_path[-1], index=names, columns=names)
    average = pd.DataFrame(np.mean(asset_path, axis=0), index=names, columns=names)
    path_frame = _path_to_frame(asset_path, standardized.index, names)
    metadata = _research_metadata(
        status="ok",
        accepted=True,
        diagnostic_eligible=True,
        model="bounded-influence Student-t GARCH + Gaussian quasi-DCC(1,1)",
        copula_model="rolling Student-t copula is estimated separately",
        observations=int(len(standardized)),
        assets=int(assets),
        dcc_dimension=int(dcc_innovations.shape[1]),
        alpha=alpha,
        beta=beta,
        persistence=persistence,
        constraints_ok=True,
        stationarity_constraint="alpha + beta < 0.999",
        optimizer="SLSQP with three deterministic starts",
        optimizer_success=True,
        optimizer_message=str(best.message),
        optimizer_iterations=int(getattr(best, "nit", 0) or 0),
        optimizer_attempts=int(len(attempts)),
        successful_attempts=int(len(successful)),
        objective=float(best.fun),
        factor_reduction_applied=bool(high_dimension),
        factor_reduction=factor_metadata,
        min_path_eigenvalue=float(eigenvalue_minima.min()),
        max_path_condition_number=float(condition_numbers.max()),
        finite_positive_definite_path=True,
        no_future_leakage=True,
        estimation_scope="in-sample dynamic dependence diagnostic",
        garch_filters=filter_summary,
        limitation=(
            "Not a forecast, allocation instruction, or execution signal. "
            "Point-in-time input governance and external calibration remain required."
        ),
    )
    return DynamicCorrelationResult(latest, average, path_frame, standardized, factor_loadings, metadata)


def _pseudo_observations(pair: np.ndarray) -> np.ndarray:
    observations = len(pair)
    ranks = np.column_stack(
        [stats.rankdata(pair[:, position], method="average") for position in range(2)]
    )
    return np.clip(ranks / (observations + 1.0), 1e-7, 1.0 - 1e-7)


def _gaussian_copula_log_likelihood(pseudo: np.ndarray) -> tuple[float, float]:
    normal = stats.norm.ppf(pseudo)
    rho = float(np.clip(np.corrcoef(normal, rowvar=False)[0, 1], -0.985, 0.985))
    determinant = 1.0 - rho * rho
    inverse_minus_identity = np.asarray(
        [[1.0 / determinant - 1.0, -rho / determinant], [-rho / determinant, 1.0 / determinant - 1.0]]
    )
    quadratic = np.einsum("ni,ij,nj->n", normal, inverse_minus_identity, normal)
    log_likelihood = float(np.sum(-0.5 * np.log(determinant) - 0.5 * quadratic))
    return rho, log_likelihood


def _student_t_copula_log_likelihood(pseudo: np.ndarray, rho: float, nu: float) -> float:
    if abs(rho) >= 0.995 or nu <= 2.05:
        return -np.inf
    transformed = stats.t.ppf(pseudo, df=nu)
    determinant = 1.0 - rho * rho
    if determinant <= 0.0 or not np.isfinite(transformed).all():
        return -np.inf
    quadratic = (
        transformed[:, 0] ** 2
        - 2.0 * rho * transformed[:, 0] * transformed[:, 1]
        + transformed[:, 1] ** 2
    ) / determinant
    joint_constant = (
        gammaln((nu + 2.0) / 2.0)
        - gammaln(nu / 2.0)
        - np.log(nu * np.pi)
        - 0.5 * np.log(determinant)
    )
    joint = joint_constant - 0.5 * (nu + 2.0) * np.log1p(quadratic / nu)
    marginal_constant = (
        gammaln((nu + 1.0) / 2.0)
        - gammaln(nu / 2.0)
        - 0.5 * np.log(nu * np.pi)
    )
    marginal = (
        2.0 * marginal_constant
        - 0.5 * (nu + 1.0) * np.log1p(transformed[:, 0] ** 2 / nu)
        - 0.5 * (nu + 1.0) * np.log1p(transformed[:, 1] ** 2 / nu)
    )
    value = float(np.sum(joint - marginal))
    return value if np.isfinite(value) else -np.inf


def _fit_t_copula_window(pseudo: np.ndarray, maxiter: int) -> dict[str, Any]:
    gaussian_rho, gaussian_log_likelihood = _gaussian_copula_log_likelihood(pseudo)
    tau = float(stats.kendalltau(pseudo[:, 0], pseudo[:, 1], variant="b").statistic)
    initial_rho = float(np.clip(np.sin(0.5 * np.pi * tau), -0.90, 0.90)) if np.isfinite(tau) else gaussian_rho

    def objective(theta: np.ndarray) -> float:
        likelihood = _student_t_copula_log_likelihood(pseudo, float(theta[0]), float(theta[1]))
        return -likelihood if np.isfinite(likelihood) else 1e30

    attempts: list[OptimizeResult] = []
    for degrees_of_freedom in (4.0, 8.0, 20.0):
        try:
            result = minimize(
                objective,
                np.asarray([initial_rho, degrees_of_freedom]),
                method="L-BFGS-B",
                bounds=[(-0.985, 0.985), (2.051, 80.0)],
                options={"maxiter": int(maxiter), "ftol": 1e-11, "gtol": 1e-7},
            )
            attempts.append(result)
        except Exception:
            continue
    successful = [result for result in attempts if bool(result.success) and np.isfinite(result.fun)]
    if not successful:
        return {
            "converged": False,
            "rejection_reason": "Student-t copula optimiser did not converge",
            "optimizer_attempts": int(len(attempts)),
            "Gaussian rho": gaussian_rho,
            "Gaussian log likelihood": gaussian_log_likelihood,
            "Gaussian AIC": float(2.0 - 2.0 * gaussian_log_likelihood),
        }
    best = min(successful, key=lambda result: float(result.fun))
    rho, nu = [float(value) for value in best.x]
    log_likelihood = -float(best.fun)
    tail_argument = -np.sqrt((nu + 1.0) * (1.0 - rho) / max(1.0 + rho, 1e-10))
    tail_dependence = float(2.0 * stats.t.cdf(tail_argument, df=nu + 1.0))
    student_aic = float(4.0 - 2.0 * log_likelihood)
    gaussian_aic = float(2.0 - 2.0 * gaussian_log_likelihood)
    return {
        "converged": True,
        "Rho": rho,
        "Nu": nu,
        "Lower tail dependence": tail_dependence,
        "Upper tail dependence": tail_dependence,
        "Log likelihood": log_likelihood,
        "AIC": student_aic,
        "Gaussian rho": gaussian_rho,
        "Gaussian log likelihood": gaussian_log_likelihood,
        "Gaussian AIC": gaussian_aic,
        "AIC improvement vs Gaussian": gaussian_aic - student_aic,
        "Nu at Gaussian boundary": bool(nu >= 79.5),
        "optimizer_attempts": int(len(attempts)),
        "optimizer_iterations": int(getattr(best, "nit", 0) or 0),
        "optimizer_message": str(best.message),
    }


def rolling_t_copula_diagnostics(
    changes: pd.DataFrame,
    primary: str,
    peer: str,
    *,
    window: int = 126,
    step: int = 21,
    min_obs: int = 80,
    maxiter: int = 300,
) -> RollingTCopulaResult:
    """Estimate rolling Student-t copula dependence without future leakage."""

    if changes is None or primary not in changes.columns or peer not in changes.columns:
        return RollingTCopulaResult(
            pd.DataFrame(),
            _research_metadata(
                status="insufficient_assets",
                accepted=False,
                diagnostic_eligible=False,
                primary=primary,
                peer=peer,
                rejection_reason="requested pair is unavailable",
            ),
        )
    pair = (
        changes[[primary, peer]]
        .apply(pd.to_numeric, errors="coerce")
        .replace([np.inf, -np.inf], np.nan)
        .dropna()
    )
    effective_window = max(int(window), int(min_obs))
    if len(pair) < effective_window:
        return RollingTCopulaResult(
            pd.DataFrame(),
            _research_metadata(
                status="insufficient_data",
                accepted=False,
                diagnostic_eligible=False,
                primary=primary,
                peer=peer,
                observations=int(len(pair)),
                required_observations=int(effective_window),
                rejection_reason="pair history is shorter than the rolling window",
            ),
        )

    endpoints = list(range(effective_window, len(pair) + 1, max(1, int(step))))
    if endpoints[-1] != len(pair):
        endpoints.append(len(pair))
    rows: list[dict[str, Any]] = []
    for endpoint in endpoints:
        sample = pair.iloc[endpoint - effective_window : endpoint]
        pseudo = _pseudo_observations(sample.to_numpy(dtype=float))
        fitted = _fit_t_copula_window(pseudo, maxiter=maxiter)
        row: dict[str, Any] = {
            "Window start": sample.index[0],
            "Window end": sample.index[-1],
            "Observations": int(len(sample)),
            **fitted,
        }
        lower = (pseudo[:, 0] <= 0.10) & (pseudo[:, 1] <= 0.10)
        upper = (pseudo[:, 0] >= 0.90) & (pseudo[:, 1] >= 0.90)
        row["Empirical lower co-exceedance"] = float(np.mean(lower) / 0.10)
        row["Empirical upper co-exceedance"] = float(np.mean(upper) / 0.10)
        rows.append(row)

    diagnostics = pd.DataFrame(rows)
    valid_windows = int(diagnostics.get("converged", pd.Series(dtype=bool)).fillna(False).sum())
    accepted = valid_windows > 0
    metadata = _research_metadata(
        status="ok" if accepted else "rejected",
        accepted=bool(accepted),
        diagnostic_eligible=bool(accepted),
        primary=primary,
        peer=peer,
        observations=int(len(pair)),
        window=int(effective_window),
        step=int(max(1, step)),
        windows=int(len(diagnostics)),
        valid_windows=valid_windows,
        rejected_windows=int(len(diagnostics) - valid_windows),
        model="rolling bivariate Student-t copula",
        marginal_transform="within-window empirical ranks / (n + 1)",
        tail_dependence="symmetric asymptotic Student-t copula coefficient",
        no_future_leakage=True,
        nu_identification_warning=(
            "Nu at the upper bound is evidence for a Gaussian limit, not proof of zero tail risk."
        ),
        limitation=(
            "Rolling estimates are descriptive and overlapping windows are dependent; "
            "they are not forecasts or trading signals."
        ),
    )
    return RollingTCopulaResult(diagnostics, metadata)


__all__ = [
    "AUTHORITY",
    "GarchFilterResult",
    "DynamicCorrelationResult",
    "RollingTCopulaResult",
    "fit_robust_garch",
    "fit_dynamic_dcc",
    "rolling_t_copula_diagnostics",
]
