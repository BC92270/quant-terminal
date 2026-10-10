from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable
import warnings

import numpy as np
from sklearn.covariance import GraphicalLasso, LedoitWolf
from sklearn.exceptions import ConvergenceWarning


DEFAULT_STANDARDIZED_ALPHAS: tuple[float, ...] = (
    0.005,
    0.01,
    0.02,
    0.04,
    0.08,
    0.16,
    0.32,
    0.64,
)


@dataclass(frozen=True)
class PrecisionEstimate:
    """Auditable sparse covariance/precision estimate.

    ``covariance`` and ``precision`` are always returned in the input units.  Alpha
    selection is performed on train-standardised data so that the fixed alpha grid
    does not inspect future observations and is comparable across assets.
    """

    covariance: np.ndarray
    precision: np.ndarray
    metadata: dict


TemporalPreprocessor = Callable[
    [np.ndarray, np.ndarray | None],
    tuple[np.ndarray, np.ndarray | None],
]


def temporal_forward_splits(
    n_samples: int,
    n_splits: int = 4,
    min_train_size: int | None = None,
    min_test_size: int = 2,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Return deterministic expanding-train/forward-test index splits.

    Every train block starts at zero and ends strictly before its contiguous test
    block.  No observation is ever used for both training and testing in a fold.
    """

    n = max(0, int(n_samples))
    requested = max(1, int(n_splits))
    minimum_test = max(1, int(min_test_size))
    if min_train_size is None:
        train_n = max(10, n // 2)
    else:
        train_n = max(2, int(min_train_size))
    train_n = min(train_n, n)
    available = n - train_n
    actual = min(requested, available // minimum_test)
    if actual < 2:
        return []

    base, remainder = divmod(available, actual)
    sizes = [base + (1 if i < remainder else 0) for i in range(actual)]
    splits: list[tuple[np.ndarray, np.ndarray]] = []
    test_start = train_n
    for size in sizes:
        test_end = test_start + size
        train_idx = np.arange(0, test_start, dtype=int)
        test_idx = np.arange(test_start, test_end, dtype=int)
        if len(test_idx) >= minimum_test:
            splits.append((train_idx, test_idx))
        test_start = test_end
    return splits


def _as_spd(matrix: np.ndarray, floor_scale: float = 1e-8) -> np.ndarray:
    a = np.asarray(matrix, dtype=float)
    a = np.nan_to_num(0.5 * (a + a.T), nan=0.0, posinf=0.0, neginf=0.0)
    vals, vecs = np.linalg.eigh(a)
    diag_scale = float(np.nanmedian(np.abs(np.diag(a)))) if a.size else 0.0
    floor = max(1e-12, diag_scale * float(floor_scale))
    vals = np.maximum(vals, floor)
    return (vecs * vals) @ vecs.T


def _warning_rows(
    caught: list[warnings.WarningMessage],
    *,
    stage: str,
    alpha: float | None,
    fold: int | None,
) -> list[dict]:
    return [
        {
            "stage": stage,
            "alpha": None if alpha is None else float(alpha),
            "fold": fold,
            "category": item.category.__name__,
            "message": str(item.message)[:500],
        }
        for item in caught
    ]


def _fit_standardized(
    train: np.ndarray,
    alpha: float,
    *,
    max_iter: int,
    tol: float,
) -> tuple[GraphicalLasso, np.ndarray, np.ndarray, list[warnings.WarningMessage]]:
    mean = np.mean(train, axis=0)
    scale = np.std(train, axis=0, ddof=1)
    if not np.isfinite(scale).all() or np.any(scale <= 1e-12):
        raise ValueError("degenerate_train_scale")
    z = (train - mean) / scale
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        model = GraphicalLasso(
            alpha=float(alpha),
            max_iter=max(50, int(max_iter)),
            tol=float(tol),
            assume_centered=True,
        ).fit(z)
    return model, mean, scale, list(caught)


def _gaussian_score(
    model: GraphicalLasso,
    test: np.ndarray,
    train_mean: np.ndarray,
    train_scale: np.ndarray,
) -> float:
    """Average Gaussian log likelihood up to the common constant term."""

    z = (test - train_mean) / train_scale
    empirical = (z.T @ z) / max(len(z), 1)
    precision = np.asarray(model.precision_, dtype=float)
    sign, logdet = np.linalg.slogdet(precision)
    if sign <= 0 or not np.isfinite(logdet):
        return float("-inf")
    score = 0.5 * (logdet - float(np.trace(empirical @ precision)))
    return float(score) if np.isfinite(score) else float("-inf")


def _fallback_estimate(arr: np.ndarray) -> tuple[np.ndarray, np.ndarray, str, list[dict]]:
    events: list[dict] = []
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            covariance = LedoitWolf().fit(arr).covariance_
        events.extend(_warning_rows(list(caught), stage="fallback", alpha=None, fold=None))
        method = "Ledoit-Wolf covariance + SPD precision"
    except Exception as exc:  # Defensive final path for pathological/very short inputs.
        events.append(
            {
                "stage": "fallback",
                "alpha": None,
                "fold": None,
                "category": type(exc).__name__,
                "message": str(exc)[:500],
            }
        )
        variance = np.nanvar(arr, axis=0, ddof=1) if len(arr) > 1 else np.zeros(arr.shape[1])
        variance = np.nan_to_num(variance, nan=0.0, posinf=0.0, neginf=0.0)
        floor = max(1e-12, float(np.nanmedian(np.abs(variance))) * 1e-6)
        covariance = np.diag(np.maximum(variance, floor))
        method = "Diagonal variance ridge"
    covariance = _as_spd(covariance)
    precision = _as_spd(np.linalg.pinv(covariance))
    return covariance, precision, method, events


def fixed_graphical_lasso(
    values: np.ndarray,
    alpha: float,
    *,
    max_iter: int = 150,
    tol: float = 1e-4,
) -> PrecisionEstimate:
    """Fit one pre-selected Graphical Lasso candidate with fail-closed gates.

    This primitive is used when a hyperparameter was selected at an earlier
    chronological forecast origin and is deliberately locked for subsequent
    outer folds. The caller remains responsible for documenting that origin.
    """

    raw = np.asarray(values, dtype=float)
    if raw.ndim != 2:
        raise ValueError("values must be a two-dimensional array")
    finite_rows = np.isfinite(raw).all(axis=1)
    arr = raw[finite_rows]
    selected_alpha = float(alpha)
    warning_events: list[dict] = []
    failure_reason: str | None = None
    model: GraphicalLasso | None = None
    scale: np.ndarray | None = None
    if (
        len(arr) < max(8, raw.shape[1] + 3)
        or raw.shape[1] < 2
        or not np.isfinite(selected_alpha)
        or selected_alpha <= 0.0
    ):
        failure_reason = "invalid_fixed_fit_inputs"
    elif np.any(np.std(arr, axis=0, ddof=1) <= 1e-12):
        failure_reason = "degenerate_feature_scale"
    else:
        try:
            model, _mean, scale, caught = _fit_standardized(
                arr, selected_alpha, max_iter=max_iter, tol=tol
            )
            warning_events.extend(
                _warning_rows(caught, stage="fixed_final", alpha=selected_alpha, fold=None)
            )
            if any(issubclass(item.category, ConvergenceWarning) for item in caught):
                failure_reason = "fixed_fit_convergence_warning"
            elif not (
                np.isfinite(model.covariance_).all()
                and np.isfinite(model.precision_).all()
            ):
                failure_reason = "non_finite_fixed_fit"
        except Exception as exc:
            warning_events.append(
                {
                    "stage": "fixed_final",
                    "alpha": selected_alpha,
                    "fold": None,
                    "category": type(exc).__name__,
                    "message": str(exc)[:500],
                }
            )
            failure_reason = "fixed_fit_failed"

    fallback_method: str | None = None
    if failure_reason is not None or model is None or scale is None:
        covariance, precision, fallback_method, fallback_events = _fallback_estimate(arr)
        warning_events.extend(fallback_events)
        status, converged = "fallback", False
    else:
        covariance = _as_spd(model.covariance_ * np.outer(scale, scale))
        inv_scale = 1.0 / scale
        precision = _as_spd(model.precision_ * np.outer(inv_scale, inv_scale))
        status, converged = "ok", True

    return PrecisionEstimate(
        covariance,
        precision,
        {
            "status": status,
            "method": "Fixed-alpha Graphical Lasso",
            "cv_scheme": "alpha locked by an earlier chronological outer origin",
            "alpha": selected_alpha,
            "graphical_alpha": selected_alpha,
            "alpha_grid": [selected_alpha],
            "alpha_scores": [],
            "folds": [],
            "fold_count": 0,
            "converged": converged,
            "fallback": fallback_method,
            "fallback_used": fallback_method is not None,
            "fallback_reason": failure_reason,
            "warnings": warning_events,
            "warning_count": int(len(warning_events)),
            "observations": int(len(arr)),
            "features": int(raw.shape[1]),
            "dropped_non_finite_rows": int(len(raw) - len(arr)),
            "max_iter": int(max_iter),
            "tolerance": float(tol),
            "alpha_selection_scope": "external chronological lock",
        },
    )


def temporal_graphical_lasso(
    values: np.ndarray,
    *,
    alpha_grid: Iterable[float] | None = None,
    n_splits: int = 4,
    min_train_size: int | None = None,
    max_iter: int = 500,
    tol: float = 1e-4,
    temporal_preprocessor: TemporalPreprocessor | None = None,
    preprocessor_name: str | None = None,
) -> PrecisionEstimate:
    """Fit Graphical Lasso with leakage-safe expanding-window alpha selection.

    Candidate alphas are scored only on observations strictly after each training
    block.  A converged candidate must be valid on every fold.  When temporal CV or
    the final fit is not trustworthy, a finite Ledoit-Wolf/SPD fallback is returned
    and fully disclosed in metadata; no exception or fallback is silent.
    """

    raw = np.asarray(values, dtype=float)
    if raw.ndim != 2:
        raise ValueError("values must be a two-dimensional array")
    original_rows, p = raw.shape
    finite_rows = np.isfinite(raw).all(axis=1)
    arr = raw[finite_rows]
    dropped_rows = int(original_rows - len(arr))
    alphas = sorted(
        {
            float(a)
            for a in (DEFAULT_STANDARDIZED_ALPHAS if alpha_grid is None else alpha_grid)
            if np.isfinite(a) and float(a) > 0.0
        }
    )
    min_train = max(12, 3 * p, len(arr) // 2) if min_train_size is None else int(min_train_size)
    splits = temporal_forward_splits(len(arr), n_splits=n_splits, min_train_size=min_train)
    fold_meta = [
        {
            "fold": i,
            "train_start": int(train[0]),
            "train_end": int(train[-1]),
            "train_size": int(len(train)),
            "test_start": int(test[0]),
            "test_end": int(test[-1]),
            "test_size": int(len(test)),
            "no_future_leakage": bool(train[-1] < test[0]),
        }
        for i, (train, test) in enumerate(splits)
    ]
    warning_events: list[dict] = []
    score_rows: list[dict] = []
    failure_reason: str | None = None
    final_values = arr

    if temporal_preprocessor is not None:
        try:
            final_values, unused_test = temporal_preprocessor(arr, None)
            final_values = np.asarray(final_values, dtype=float)
            if unused_test is not None:
                raise ValueError("final preprocessor must return None for absent test data")
            if final_values.shape != arr.shape or not np.isfinite(final_values).all():
                raise ValueError("preprocessor must preserve shape and return finite values")
        except Exception as exc:
            warning_events.append(
                {
                    "stage": "preprocessor",
                    "alpha": None,
                    "fold": None,
                    "category": type(exc).__name__,
                    "message": str(exc)[:500],
                }
            )
            failure_reason = "final_preprocessor_failed"

    if failure_reason is not None:
        pass
    elif p < 2:
        failure_reason = "fewer_than_two_features"
    elif len(arr) < max(8, p + 3):
        failure_reason = "insufficient_finite_observations"
    elif not alphas:
        failure_reason = "empty_alpha_grid"
    elif len(splits) < 2:
        failure_reason = "insufficient_temporal_folds"
    elif np.any(np.std(final_values, axis=0, ddof=1) <= 1e-12):
        failure_reason = "degenerate_feature_scale"

    selected_alpha: float | None = None
    selected_score: float | None = None
    if failure_reason is None:
        for alpha in alphas:
            scores: list[float] = []
            converged = True
            for fold_no, (train_idx, test_idx) in enumerate(splits):
                try:
                    train_values = arr[train_idx]
                    test_values = arr[test_idx]
                    if temporal_preprocessor is not None:
                        train_values, processed_test = temporal_preprocessor(
                            train_values, test_values
                        )
                        train_values = np.asarray(train_values, dtype=float)
                        test_values = np.asarray(processed_test, dtype=float)
                        if (
                            train_values.shape != arr[train_idx].shape
                            or test_values.shape != arr[test_idx].shape
                            or not np.isfinite(train_values).all()
                            or not np.isfinite(test_values).all()
                        ):
                            raise ValueError(
                                "preprocessor must preserve fold shapes and return finite values"
                            )
                    model, mean, scale, caught = _fit_standardized(
                        train_values, alpha, max_iter=max_iter, tol=tol
                    )
                    rows = _warning_rows(
                        caught, stage="cv", alpha=alpha, fold=fold_no
                    )
                    warning_events.extend(rows)
                    has_convergence_warning = any(
                        issubclass(item.category, ConvergenceWarning) for item in caught
                    )
                    score = _gaussian_score(model, test_values, mean, scale)
                    if has_convergence_warning or not np.isfinite(score):
                        converged = False
                        break
                    scores.append(score)
                except Exception as exc:
                    warning_events.append(
                        {
                            "stage": "cv",
                            "alpha": float(alpha),
                            "fold": fold_no,
                            "category": type(exc).__name__,
                            "message": str(exc)[:500],
                        }
                    )
                    converged = False
                    break
            eligible = converged and len(scores) == len(splits)
            mean_score = float(np.mean(scores)) if eligible else None
            score_rows.append(
                {
                    "alpha": float(alpha),
                    "mean_score": mean_score,
                    "valid_folds": int(len(scores)),
                    "total_folds": int(len(splits)),
                    "converged": bool(eligible),
                }
            )
        eligible_rows = [row for row in score_rows if row["converged"]]
        if eligible_rows:
            # Prefer the more regularised model only when mean scores are exactly tied.
            best = max(eligible_rows, key=lambda row: (row["mean_score"], row["alpha"]))
            selected_alpha = float(best["alpha"])
            selected_score = float(best["mean_score"])
        else:
            failure_reason = "no_converged_temporal_candidate"

    final_model: GraphicalLasso | None = None
    final_mean: np.ndarray | None = None
    final_scale: np.ndarray | None = None
    if failure_reason is None and selected_alpha is not None:
        try:
            final_model, final_mean, final_scale, caught = _fit_standardized(
                final_values, selected_alpha, max_iter=max_iter, tol=tol
            )
            warning_events.extend(
                _warning_rows(caught, stage="final", alpha=selected_alpha, fold=None)
            )
            if any(issubclass(item.category, ConvergenceWarning) for item in caught):
                failure_reason = "final_fit_convergence_warning"
            elif not (
                np.isfinite(final_model.covariance_).all()
                and np.isfinite(final_model.precision_).all()
            ):
                failure_reason = "non_finite_final_fit"
        except Exception as exc:
            warning_events.append(
                {
                    "stage": "final",
                    "alpha": selected_alpha,
                    "fold": None,
                    "category": type(exc).__name__,
                    "message": str(exc)[:500],
                }
            )
            failure_reason = "final_fit_failed"

    fallback_method: str | None = None
    if failure_reason is not None or final_model is None or final_scale is None:
        covariance, precision, fallback_method, fallback_events = _fallback_estimate(final_values)
        warning_events.extend(fallback_events)
        status = "fallback"
        converged = False
    else:
        covariance = final_model.covariance_ * np.outer(final_scale, final_scale)
        inv_scale = 1.0 / final_scale
        precision = final_model.precision_ * np.outer(inv_scale, inv_scale)
        covariance = _as_spd(covariance)
        precision = _as_spd(precision)
        status = "ok"
        converged = True

    metadata = {
        "status": status,
        "method": "Temporal Graphical Lasso",
        "cv_scheme": "expanding-window forward validation",
        "score": "out-of-sample Gaussian log-likelihood",
        "temporal_preprocessor": preprocessor_name,
        "preprocessor_fit_scope": (
            "train-only per temporal fold" if temporal_preprocessor is not None else None
        ),
        "alpha_scale": "train-standardised unit variance",
        "alpha": selected_alpha,
        "graphical_alpha": selected_alpha,
        "alpha_grid": alphas,
        "alpha_scores": score_rows,
        "selected_score": selected_score,
        "folds": fold_meta,
        "fold_count": int(len(fold_meta)),
        "no_future_leakage": bool(
            fold_meta and all(row["no_future_leakage"] for row in fold_meta)
        ),
        "converged": converged,
        "fallback": fallback_method,
        "fallback_used": fallback_method is not None,
        "fallback_reason": failure_reason,
        "warnings": warning_events,
        "warning_count": int(len(warning_events)),
        "observations": int(len(arr)),
        "features": int(p),
        "dropped_non_finite_rows": dropped_rows,
        "max_iter": int(max_iter),
        "tolerance": float(tol),
    }
    return PrecisionEstimate(covariance, precision, metadata)
