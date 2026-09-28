"""Multiple-testing-aware validation for investment research."""
from __future__ import annotations

from itertools import combinations
from math import erf, exp, floor, log, sqrt
from typing import Any, Iterable

import numpy as np
import pandas as pd


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + erf(value / sqrt(2.0)))


def _normal_ppf(probability: float) -> float:
    p = min(max(float(probability), 1e-12), 1.0 - 1e-12)
    a = (-39.6968302866538, 220.946098424521, -275.928510446969, 138.357751867269, -30.6647980661472, 2.50662827745924)
    b = (-54.4760987982241, 161.585836858041, -155.698979859887, 66.8013118877197, -13.2806815528857)
    c = (-0.00778489400243029, -0.322396458041136, -2.40075827716184, -2.54973253934373, 4.37466414146497, 2.93816398269878)
    d = (0.00778469570904146, 0.32246712907004, 2.445134137143, 3.75440866190742)
    low = 0.02425
    high = 1.0 - low
    if p < low:
        q = sqrt(-2.0 * log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p <= high:
        q = p - 0.5
        r = q * q
        return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)
    q = sqrt(-2.0 * log(1.0-p))
    return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)


def _validate_periods(periods: int) -> int:
    value = int(periods)
    if value <= 0:
        raise ValueError("periods must be strictly positive")
    return value


def _sampling_sharpe(returns: pd.Series | np.ndarray) -> float:
    values = pd.to_numeric(pd.Series(returns), errors="coerce").dropna().to_numpy(dtype=float)
    values = values[np.isfinite(values)]
    if len(values) < 2:
        return float("nan")
    std = float(values.std(ddof=1))
    return float(values.mean() / std) if std > 0 else float("nan")


def annualized_sharpe(returns: pd.Series, periods: int = 252) -> float:
    frequency = _validate_periods(periods)
    sampling_sharpe = _sampling_sharpe(returns)
    return float(sampling_sharpe * sqrt(frequency)) if np.isfinite(sampling_sharpe) else float("nan")


def sharpe_hac_diagnostics(
    returns: pd.Series | np.ndarray,
    *,
    hac_lags: int | None = None,
) -> dict[str, Any]:
    """Estimate a conservative Sharpe effective sample size with Bartlett HAC.

    The long-run variance uses a Newey-West/Bartlett kernel.  The automatic
    truncation lag is ``floor(4 * (n / 100) ** (2 / 9))``.  Positive serial
    dependence therefore reduces the sample size used by PSR/DSR.  Negative
    dependence is *not* allowed to increase confidence beyond the iid result:
    the variance-inflation factor is floored at one.
    """
    values = pd.to_numeric(pd.Series(returns), errors="coerce").dropna().to_numpy(dtype=float)
    values = values[np.isfinite(values)]
    n = int(len(values))
    if n < 2:
        return {
            "observations": n,
            "effective_sample_size": float("nan"),
            "hac_lags": 0,
            "variance_inflation": float("nan"),
            "long_run_variance": float("nan"),
            "sample_variance": float("nan"),
            "method": "Bartlett HAC effective sample size; negative dependence cannot increase confidence",
        }
    if hac_lags is None:
        lags = max(1, floor(4.0 * (n / 100.0) ** (2.0 / 9.0)))
    else:
        lags = int(hac_lags)
        if lags < 0:
            raise ValueError("hac_lags must be non-negative")
    lags = min(lags, n - 1)
    centered = values - values.mean()
    gamma_zero = float(np.dot(centered, centered) / n)
    if not np.isfinite(gamma_zero) or gamma_zero <= 0.0:
        return {
            "observations": n,
            "effective_sample_size": float("nan"),
            "hac_lags": int(lags),
            "variance_inflation": float("nan"),
            "long_run_variance": float("nan"),
            "sample_variance": gamma_zero,
            "method": "Bartlett HAC effective sample size; negative dependence cannot increase confidence",
        }
    long_run_variance = gamma_zero
    for lag in range(1, lags + 1):
        weight = 1.0 - lag / (lags + 1.0)
        autocovariance = float(np.dot(centered[lag:], centered[:-lag]) / n)
        long_run_variance += 2.0 * weight * autocovariance
    raw_inflation = long_run_variance / gamma_zero
    # A noisy/negative HAC estimate must not manufacture more evidence than iid.
    inflation = max(float(raw_inflation), 1.0) if np.isfinite(raw_inflation) else float("nan")
    effective = float(n / inflation) if np.isfinite(inflation) else float("nan")
    effective = min(max(effective, 2.0), float(n)) if np.isfinite(effective) else float("nan")
    return {
        "observations": n,
        "effective_sample_size": effective,
        "hac_lags": int(lags),
        "variance_inflation": inflation,
        "raw_variance_inflation": float(raw_inflation),
        "long_run_variance": float(long_run_variance),
        "sample_variance": gamma_zero,
        "method": "Bartlett HAC effective sample size; negative dependence cannot increase confidence",
    }


def probabilistic_sharpe_ratio(
    returns: pd.Series,
    *,
    benchmark_sharpe: float = 0.0,
    periods: int = 252,
    hac_lags: int | None = None,
) -> float:
    """Probability that the true Sharpe exceeds an annualized benchmark.

    The finite-sample PSR equation is defined with Sharpe ratios at the return
    sampling frequency.  Public inputs and outputs in this module remain
    annualized, so both the observed and benchmark Sharpes are converted to
    sampling-frequency units before the statistic is evaluated.  Confidence
    is based on a Bartlett-HAC effective sample size, not the raw observation
    count, so smoothed/autocorrelated returns cannot masquerade as independent
    evidence.  Set ``hac_lags=0`` only for an explicit iid diagnostic.
    """
    frequency = _validate_periods(periods)
    values = pd.to_numeric(returns, errors="coerce").dropna().to_numpy(dtype=float)
    values = values[np.isfinite(values)]
    n = len(values)
    if n < 3:
        return float("nan")
    sr = _sampling_sharpe(values)
    centered = values - values.mean()
    sigma = values.std(ddof=1)
    if sigma <= 0 or not np.isfinite(sr) or not np.isfinite(benchmark_sharpe):
        return float("nan")
    skew = float(np.mean(centered ** 3) / sigma ** 3)
    kurt = float(np.mean(centered ** 4) / sigma ** 4)
    denominator = sqrt(max(1.0 - skew * sr + ((kurt - 1.0) / 4.0) * sr * sr, 1e-12))
    benchmark_sampling = float(benchmark_sharpe) / sqrt(frequency)
    hac = sharpe_hac_diagnostics(values, hac_lags=hac_lags)
    effective_n = float(hac["effective_sample_size"])
    if not np.isfinite(effective_n):
        return float("nan")
    z = (sr - benchmark_sampling) * sqrt(max(effective_n - 1.0, 1.0)) / denominator
    return float(_normal_cdf(z))


def expected_max_sharpe(
    num_trials: int,
    sharpe_std: float,
    *,
    mean_sharpe: float = 0.0,
) -> float:
    trials = max(int(num_trials), 1)
    if trials == 1 or sharpe_std <= 0:
        return float(mean_sharpe)
    gamma = 0.5772156649015329
    term_a = (1.0 - gamma) * _normal_ppf(1.0 - 1.0 / trials)
    term_b = gamma * _normal_ppf(1.0 - 1.0 / (trials * exp(1.0)))
    return float(mean_sharpe + sharpe_std * (term_a + term_b))


def deflated_sharpe_ratio(
    returns: pd.Series,
    *,
    num_trials: int,
    trial_sharpes: Iterable[float] | None = None,
    periods: int = 252,
    hac_lags: int | None = None,
) -> dict[str, Any]:
    """Return a DSR only when a genuine, estimable trial family is supplied.

    ``trial_sharpes`` and all returned Sharpe ratios are annualized.  A single
    selected strategy cannot identify the multiple-testing distribution; in
    that case the result is explicitly unavailable instead of the misleading
    50% value produced when the selected Sharpe is its own benchmark.
    """
    frequency = _validate_periods(periods)
    values = pd.to_numeric(returns, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    raw_candidates = [] if trial_sharpes is None else list(trial_sharpes)
    candidates = pd.to_numeric(pd.Series(raw_candidates, dtype=object), errors="coerce").to_numpy(dtype=float)
    candidates = candidates[np.isfinite(candidates)]
    effective_trials = max(int(num_trials), int(len(candidates)), 1)
    hac = sharpe_hac_diagnostics(values, hac_lags=hac_lags)
    result: dict[str, Any] = {
        "observed_sharpe": annualized_sharpe(values, frequency),
        "expected_max_sharpe": float("nan"),
        "deflated_sharpe_probability": float("nan"),
        "num_trials": effective_trials,
        "candidate_sharpes": int(len(candidates)),
        "effective_sample_size": hac["effective_sample_size"],
        "hac_lags": hac["hac_lags"],
        "hac_variance_inflation": hac["variance_inflation"],
        "serial_dependence_method": hac["method"],
        "available": False,
        "state": "UNAVAILABLE",
        "reason": "DATA REQUIRED: at least two finite candidate trial Sharpes",
    }
    if len(values) < 3:
        result["reason"] = "DATA REQUIRED: at least three selected-strategy observations"
        return result
    if len(candidates) < 2 or effective_trials < 2:
        return result
    sr_std = float(candidates.std(ddof=1))
    if not np.isfinite(sr_std) or sr_std <= 0:
        result["reason"] = "UNAVAILABLE: candidate Sharpe dispersion is zero or not estimable"
        return result
    sr_mean = float(candidates.mean())
    threshold = expected_max_sharpe(effective_trials, sr_std, mean_sharpe=sr_mean)
    probability = probabilistic_sharpe_ratio(
        values,
        benchmark_sharpe=threshold,
        periods=frequency,
        hac_lags=hac_lags,
    )
    if not np.isfinite(probability):
        result["reason"] = "UNAVAILABLE: selected-strategy PSR could not be estimated"
        return result
    result.update({
        "expected_max_sharpe": threshold,
        "deflated_sharpe_probability": probability,
        "available": True,
        "state": "AVAILABLE",
        "reason": "Estimated from the supplied candidate Sharpe distribution",
    })
    return result


def _complete_candidate_matrix(
    strategy_returns: pd.DataFrame,
    *,
    min_history_coverage: float = 0.80,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Retain a common candidate sample only when full-history coverage is sufficient."""
    minimum_coverage = float(min_history_coverage)
    if not 0.0 < minimum_coverage <= 1.0:
        raise ValueError("min_history_coverage must be in (0, 1]")
    if not isinstance(strategy_returns, pd.DataFrame):
        strategy_returns = pd.DataFrame(strategy_returns)
    numeric = strategy_returns.apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)
    input_rows = int(len(numeric))
    clean = numeric.dropna(axis=0, how="any")
    dropped = input_rows - int(len(clean))
    coverage = float(len(clean) / input_rows) if input_rows else 0.0
    metadata: dict[str, Any] = {
        "input_observations": input_rows,
        "observations": int(len(clean)),
        "dropped_incomplete_rows": dropped,
        "strategies": int(clean.shape[1]),
        "history_coverage": coverage,
        "minimum_history_coverage": minimum_coverage,
        "missing_policy": "complete-case intersection across all candidates; missing returns are never zero-filled",
    }
    if clean.shape[1] == 0:
        metadata.update({"available": False, "state": "UNAVAILABLE", "reason": "DATA REQUIRED: candidate family"})
    elif clean.empty:
        metadata.update({
            "available": False,
            "state": "UNAVAILABLE",
            "reason": "DATA REQUIRED: candidates have no common complete observations",
        })
    elif coverage < minimum_coverage:
        metadata.update({
            "available": False,
            "state": "UNAVAILABLE",
            "reason": (
                f"DATA REQUIRED: candidate common-history coverage {coverage:.1%} is below "
                f"the {minimum_coverage:.1%} minimum"
            ),
        })
    else:
        metadata.update({"available": True, "state": "AVAILABLE", "reason": "Common candidate sample available"})
    return clean, metadata


def _stationary_bootstrap_indices(
    n: int,
    *,
    samples: int,
    mean_block: int,
    rng: np.random.Generator,
) -> np.ndarray:
    probability = 1.0 / max(int(mean_block), 1)
    result = np.empty((samples, n), dtype=int)
    for sample in range(samples):
        current = int(rng.integers(0, n))
        for i in range(n):
            if i == 0 or rng.random() < probability:
                current = int(rng.integers(0, n))
            else:
                current = (current + 1) % n
            result[sample, i] = current
    return result


def white_reality_check(
    strategy_returns: pd.DataFrame,
    *,
    bootstrap_samples: int = 500,
    mean_block: int = 10,
    seed: int = 7,
    min_history_coverage: float = 0.80,
) -> dict[str, Any]:
    clean, metadata = _complete_candidate_matrix(
        strategy_returns,
        min_history_coverage=min_history_coverage,
    )
    if not metadata["available"] or clean.shape[0] < 10 or clean.shape[1] < 1:
        reason = metadata["reason"] if not metadata["available"] else "DATA REQUIRED: at least ten common observations"
        return metadata | {
            "p_value": float("nan"),
            "observed_max_mean": float("nan"),
            "available": False,
            "state": "UNAVAILABLE",
            "reason": reason,
        }
    matrix = clean.to_numpy(dtype=float)
    observed = float(matrix.mean(axis=0).max())
    centered = matrix - matrix.mean(axis=0, keepdims=True)
    rng = np.random.default_rng(seed)
    indices = _stationary_bootstrap_indices(len(matrix), samples=bootstrap_samples, mean_block=mean_block, rng=rng)
    boot = np.empty(bootstrap_samples)
    for i, sample_index in enumerate(indices):
        boot[i] = centered[sample_index].mean(axis=0).max()
    return metadata | {
        "p_value": float((1 + np.sum(boot >= observed)) / (bootstrap_samples + 1)),
        "observed_max_mean": observed,
        "bootstrap_samples": int(bootstrap_samples),
    }


def hansen_spa_test(
    strategy_returns: pd.DataFrame,
    *,
    bootstrap_samples: int = 500,
    mean_block: int = 10,
    seed: int = 11,
    min_history_coverage: float = 0.80,
) -> dict[str, Any]:
    clean, metadata = _complete_candidate_matrix(
        strategy_returns,
        min_history_coverage=min_history_coverage,
    )
    matrix = clean.to_numpy(dtype=float)
    n = len(matrix)
    if not metadata["available"] or n < 10 or clean.shape[1] < 1:
        reason = metadata["reason"] if not metadata["available"] else "DATA REQUIRED: at least ten common observations"
        return metadata | {
            "p_value": float("nan"),
            "observed_max_t": float("nan"),
            "available": False,
            "state": "UNAVAILABLE",
            "reason": reason,
        }
    means = matrix.mean(axis=0)
    std_error = matrix.std(axis=0, ddof=1) / sqrt(n)
    valid = std_error > 1e-12
    t_stats = np.divide(means, std_error, out=np.zeros_like(means), where=valid)
    observed = float(np.max(t_stats))
    # Hansen consistent recentering: poor models remain truncated away from the null frontier.
    threshold = -sqrt(2.0 * log(max(log(n), 1.0001)))
    recenter = np.where(t_stats >= threshold, means, 0.0)
    centered = matrix - recenter
    rng = np.random.default_rng(seed)
    indices = _stationary_bootstrap_indices(n, samples=bootstrap_samples, mean_block=mean_block, rng=rng)
    boot = np.empty(bootstrap_samples)
    for i, sample_index in enumerate(indices):
        sample_mean = centered[sample_index].mean(axis=0)
        boot[i] = np.max(np.divide(sample_mean, std_error, out=np.zeros_like(sample_mean), where=valid))
    return metadata | {
        "p_value": float((1 + np.sum(boot >= observed)) / (bootstrap_samples + 1)),
        "observed_max_t": observed,
        "bootstrap_samples": int(bootstrap_samples),
    }


def cscv_probability_of_backtest_overfitting(
    strategy_returns: pd.DataFrame,
    *,
    partitions: int = 8,
    max_combinations: int = 2000,
    seed: int = 19,
    min_history_coverage: float = 0.80,
) -> dict[str, Any]:
    clean, metadata = _complete_candidate_matrix(
        strategy_returns,
        min_history_coverage=min_history_coverage,
    )
    n, strategies = clean.shape
    s = min(int(partitions), n)
    if s % 2:
        s -= 1
    if not metadata["available"] or s < 4 or strategies < 2:
        if not metadata["available"]:
            reason = metadata["reason"]
        elif strategies < 2:
            reason = "DATA REQUIRED: CSCV/PBO needs at least two candidates"
        else:
            reason = "DATA REQUIRED: CSCV/PBO needs at least four common observations"
        return metadata | {
            "pbo": float("nan"),
            "median_oos_logit": float("nan"),
            "combinations": 0,
            "partitions": s,
            "available": False,
            "state": "UNAVAILABLE",
            "reason": reason,
        }
    slices = [part for part in np.array_split(np.arange(n), s) if len(part)]
    combos = list(combinations(range(s), s // 2))
    if len(combos) > max_combinations:
        rng = np.random.default_rng(seed)
        chosen = rng.choice(len(combos), size=max_combinations, replace=False)
        combos = [combos[int(i)] for i in chosen]
    matrix = clean.to_numpy(dtype=float)
    logits: list[float] = []
    for training_slices in combos:
        train_set = set(training_slices)
        train_idx = np.concatenate([slices[i] for i in training_slices])
        test_idx = np.concatenate([slices[i] for i in range(s) if i not in train_set])
        train_score = matrix[train_idx].mean(axis=0)
        winner = int(np.argmax(train_score))
        test_score = matrix[test_idx].mean(axis=0)
        rank = int(np.argsort(np.argsort(test_score))[winner]) + 1
        percentile = min(max(rank / (strategies + 1.0), 1e-9), 1.0 - 1e-9)
        logits.append(log(percentile / (1.0 - percentile)))
    values = np.asarray(logits, dtype=float)
    return metadata | {
        "pbo": float(np.mean(values <= 0.0)),
        "median_oos_logit": float(np.median(values)),
        "combinations": int(len(values)),
        "partitions": int(s),
    }


def purged_combinatorial_splits(
    n_observations: int,
    *,
    test_folds: int = 2,
    total_folds: int = 6,
    purge: int = 5,
    embargo: int = 5,
) -> list[tuple[np.ndarray, np.ndarray]]:
    if total_folds < 3 or test_folds < 1 or test_folds >= total_folds:
        raise ValueError("Invalid CPCV fold specification")
    if n_observations < total_folds:
        raise ValueError("CPCV requires at least one observation per fold")
    if purge < 0 or embargo < 0:
        raise ValueError("purge and embargo must be non-negative")
    folds = np.array_split(np.arange(n_observations), total_folds)
    results: list[tuple[np.ndarray, np.ndarray]] = []
    all_idx = np.arange(n_observations)
    for chosen in combinations(range(total_folds), test_folds):
        test = np.concatenate([folds[i] for i in chosen])
        forbidden = np.zeros(n_observations, dtype=bool)
        for idx in test:
            lo = max(0, int(idx) - purge)
            hi = min(n_observations, int(idx) + embargo + 1)
            forbidden[lo:hi] = True
        train = all_idx[~forbidden]
        results.append((train, np.sort(test)))
    return results


def cpcv_oos_validation(
    selected_returns: pd.Series,
    candidate_returns: pd.DataFrame,
    *,
    periods: int = 252,
    test_folds: int = 2,
    total_folds: int = 6,
    purge: int = 5,
    embargo: int = 5,
    min_train_observations: int = 10,
    min_test_observations: int = 2,
    min_history_coverage: float = 0.80,
    min_path_execution_fraction: float = 0.80,
    min_paths_executed: int = 4,
) -> dict[str, Any]:
    """Select candidates in each purged train set and evaluate them OOS.

    This is an executable CPCV validation, not a split counter.  Candidate
    choice is made solely from each training set; all reported candidate path
    returns and Sharpes come from the held-out observations.  The supplied
    ``selected_returns`` series is evaluated as a fixed-strategy OOS baseline.
    Missing values are handled through one explicit complete-case intersection
    across the selected strategy and every candidate.
    """
    frequency = _validate_periods(periods)
    minimum_coverage = float(min_history_coverage)
    minimum_path_fraction = float(min_path_execution_fraction)
    minimum_paths = int(min_paths_executed)
    if not 0.0 < minimum_coverage <= 1.0:
        raise ValueError("min_history_coverage must be in (0, 1]")
    if not 0.0 < minimum_path_fraction <= 1.0:
        raise ValueError("min_path_execution_fraction must be in (0, 1]")
    if minimum_paths < 1:
        raise ValueError("min_paths_executed must be strictly positive")
    unavailable: dict[str, Any] = {
        "available": False,
        "state": "UNAVAILABLE",
        "reason": "DATA REQUIRED: candidate family",
        "paths_requested": 0,
        "paths_executed": 0,
        "paths_skipped": 0,
        "path_execution_fraction": 0.0,
        "minimum_path_execution_fraction": minimum_path_fraction,
        "minimum_paths_executed": minimum_paths,
        "path_results": [],
        "selection_counts": {},
        "input_observations": 0,
        "full_history_observations": 0,
        "observations": 0,
        "dropped_incomplete_rows": 0,
        "history_coverage": 0.0,
        "minimum_history_coverage": minimum_coverage,
        "candidate_count": 0,
        "missing_policy": "complete-case intersection across selected and all candidates; missing returns are never zero-filled",
    }
    if not isinstance(candidate_returns, pd.DataFrame) or candidate_returns.shape[1] < 2:
        if isinstance(candidate_returns, pd.DataFrame):
            unavailable["candidate_count"] = int(candidate_returns.shape[1])
            unavailable["input_observations"] = int(len(candidate_returns))
        unavailable["reason"] = "DATA REQUIRED: CPCV/OOS needs at least two candidates"
        return unavailable
    if not candidate_returns.columns.is_unique:
        unavailable["candidate_count"] = int(candidate_returns.shape[1])
        unavailable["input_observations"] = int(len(candidate_returns))
        unavailable["reason"] = "UNAVAILABLE: candidate names must be unique"
        return unavailable
    selected = pd.to_numeric(selected_returns, errors="coerce").replace([np.inf, -np.inf], np.nan)
    candidates = candidate_returns.apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)
    unavailable["candidate_count"] = int(candidates.shape[1])
    unavailable["input_observations"] = int(len(candidates))
    unavailable["full_history_observations"] = int(len(selected))
    if not selected.index.is_unique or not candidates.index.is_unique:
        unavailable["reason"] = "UNAVAILABLE: CPCV/OOS indices must be unique"
        return unavailable
    internal_name = "__institutional_selected_baseline__"
    while internal_name in candidates.columns:
        internal_name += "_"
    combined = pd.concat([selected.rename(internal_name), candidates], axis=1, join="inner")
    aligned_input = int(len(combined))
    complete = combined.dropna(axis=0, how="any")
    unavailable["input_observations"] = aligned_input
    unavailable["observations"] = int(len(complete))
    unavailable["dropped_incomplete_rows"] = aligned_input - int(len(complete))
    full_history = int(len(selected))
    coverage = float(len(complete) / full_history) if full_history else 0.0
    unavailable["full_history_observations"] = full_history
    unavailable["history_coverage"] = coverage
    if coverage < minimum_coverage:
        unavailable["reason"] = (
            f"DATA REQUIRED: CPCV candidate coverage {coverage:.1%} is below "
            f"the {minimum_coverage:.1%} full-history minimum"
        )
        return unavailable
    if len(complete) < total_folds:
        unavailable["reason"] = "DATA REQUIRED: insufficient common complete observations for CPCV folds"
        return unavailable
    baseline = complete.pop(internal_name)
    matrix = complete
    try:
        splits = purged_combinatorial_splits(
            len(matrix),
            test_folds=test_folds,
            total_folds=total_folds,
            purge=purge,
            embargo=embargo,
        )
    except ValueError as exc:
        unavailable["reason"] = f"UNAVAILABLE: {exc}"
        return unavailable
    fold_membership = np.empty(len(matrix), dtype=int)
    for fold_id, positions in enumerate(np.array_split(np.arange(len(matrix)), total_folds)):
        fold_membership[positions] = fold_id
    path_results: list[dict[str, Any]] = []
    skipped = 0
    for path_id, (train_idx, test_idx) in enumerate(splits):
        if len(train_idx) < min_train_observations or len(test_idx) < min_test_observations:
            skipped += 1
            continue
        train = matrix.iloc[train_idx]
        train_sharpes = pd.Series(
            {column: annualized_sharpe(train[column], frequency) for column in matrix.columns},
            dtype=float,
        ).replace([np.inf, -np.inf], np.nan).dropna()
        if train_sharpes.empty:
            skipped += 1
            continue
        winner = train_sharpes.idxmax()
        candidate_oos = matrix.iloc[test_idx][winner]
        baseline_oos = baseline.iloc[test_idx]
        candidate_oos_sharpe = annualized_sharpe(candidate_oos, frequency)
        baseline_oos_sharpe = annualized_sharpe(baseline_oos, frequency)
        if not np.isfinite(candidate_oos_sharpe) or not np.isfinite(baseline_oos_sharpe):
            skipped += 1
            continue
        path_results.append({
            "path_id": int(path_id),
            "test_fold_ids": sorted({int(value) for value in fold_membership[test_idx]}),
            "selected_candidate": str(winner),
            "train_observations": int(len(train_idx)),
            "test_observations": int(len(test_idx)),
            "train_sharpe": float(train_sharpes.loc[winner]),
            "oos_sharpe": float(candidate_oos_sharpe),
            "oos_mean_return": float(candidate_oos.mean()),
            "selected_baseline_oos_sharpe": float(baseline_oos_sharpe),
            "selected_baseline_oos_mean_return": float(baseline_oos.mean()),
        })
    if not path_results:
        unavailable.update({
            "paths_requested": int(len(splits)),
            "paths_skipped": int(len(splits)),
            "reason": "UNAVAILABLE: no CPCV path met the train/test estimation requirements",
        })
        return unavailable
    path_frame = pd.DataFrame(path_results)
    counts = path_frame["selected_candidate"].value_counts().sort_index()
    requested = int(len(splits))
    executed = int(len(path_results))
    execution_fraction = float(executed / requested) if requested else 0.0
    path_coverage_available = (
        executed >= minimum_paths
        and execution_fraction >= minimum_path_fraction
    )
    if path_coverage_available:
        state = "AVAILABLE"
        reason = "Candidates selected in purged train sets and evaluated on held-out observations"
    else:
        state = "UNAVAILABLE"
        reason = (
            f"DATA REQUIRED: only {executed}/{requested} CPCV paths executed "
            f"({execution_fraction:.1%}); require at least {minimum_paths} paths and "
            f"{minimum_path_fraction:.1%} coverage"
        )
    return unavailable | {
        "available": path_coverage_available,
        "state": state,
        "reason": reason,
        "paths_requested": int(len(splits)),
        "paths_executed": executed,
        "paths_skipped": int(skipped),
        "path_execution_fraction": execution_fraction,
        "path_results": path_results,
        "selection_counts": {str(key): int(value) for key, value in counts.items()},
        "median_oos_sharpe": float(path_frame["oos_sharpe"].median()),
        "mean_oos_return": float(path_frame["oos_mean_return"].mean()),
        "positive_oos_path_fraction": float((path_frame["oos_mean_return"] > 0).mean()),
        # Compatibility alias consumed by the institutional decision gate.
        "positive_oos_share": float((path_frame["oos_mean_return"] > 0).mean()),
        "selected_baseline_median_oos_sharpe": float(path_frame["selected_baseline_oos_sharpe"].median()),
        "median_sharpe_degradation": float((path_frame["train_sharpe"] - path_frame["oos_sharpe"]).median()),
    }


def holm_bonferroni(p_values: Iterable[float], alpha: float = 0.05) -> pd.DataFrame:
    p = np.asarray(list(p_values), dtype=float)
    valid = np.isfinite(p)
    order = np.argsort(np.where(valid, p, np.inf))
    adjusted = np.full(len(p), np.nan)
    running = 0.0
    m = int(valid.sum())
    for rank, idx in enumerate(order[:m]):
        running = max(running, (m - rank) * p[idx])
        adjusted[idx] = min(running, 1.0)
    return pd.DataFrame({"p_value": p, "adjusted_p": adjusted, "reject": adjusted <= alpha})


def benjamini_hochberg(p_values: Iterable[float], alpha: float = 0.05) -> pd.DataFrame:
    p = np.asarray(list(p_values), dtype=float)
    valid_indices = np.where(np.isfinite(p))[0]
    sorted_indices = valid_indices[np.argsort(p[valid_indices])]
    m = len(sorted_indices)
    adjusted = np.full(len(p), np.nan)
    running = 1.0
    for reverse_rank, idx in enumerate(sorted_indices[::-1], start=1):
        rank = m - reverse_rank + 1
        running = min(running, p[idx] * m / rank)
        adjusted[idx] = min(running, 1.0)
    return pd.DataFrame({"p_value": p, "adjusted_p": adjusted, "reject": adjusted <= alpha})


def minimum_track_record_length(
    observed_sharpe: float,
    *,
    target_sharpe: float = 0.0,
    confidence: float = 0.95,
    skew: float = 0.0,
    kurtosis: float = 3.0,
    periods: int = 252,
) -> float:
    frequency = _validate_periods(periods)
    observed_sampling = observed_sharpe / sqrt(frequency)
    target_sampling = target_sharpe / sqrt(frequency)
    spread = observed_sampling - target_sampling
    if spread <= 0:
        return float("inf")
    z = _normal_ppf(confidence)
    correction = max(
        1.0 - skew * observed_sampling + ((kurtosis - 1.0) / 4.0) * observed_sampling ** 2,
        1e-12,
    )
    return float(1.0 + correction * (z / spread) ** 2)


def institutional_validation_suite(
    returns: pd.Series,
    *,
    candidates: pd.DataFrame | None = None,
    num_trials: int = 1,
    bootstrap_samples: int = 500,
    seed: int = 7,
    periods: int = 252,
    cpcv_test_folds: int = 2,
    cpcv_total_folds: int = 6,
    cpcv_purge: int = 5,
    cpcv_embargo: int = 5,
    min_candidate_history_coverage: float = 0.80,
    cpcv_min_path_execution_fraction: float = 0.80,
    cpcv_min_paths_executed: int = 4,
    hac_lags: int | None = None,
) -> dict[str, object]:
    frequency = _validate_periods(periods)
    selected_numeric = pd.to_numeric(returns, errors="coerce").replace([np.inf, -np.inf], np.nan)
    clean = selected_numeric.dropna()
    candidate_count = int(candidates.shape[1]) if isinstance(candidates, pd.DataFrame) else 0
    if candidates is None:
        numeric_candidates = pd.DataFrame(index=clean.index)
    elif not isinstance(candidates, pd.DataFrame):
        numeric_candidates = pd.DataFrame(candidates)
        candidate_count = int(numeric_candidates.shape[1])
    else:
        numeric_candidates = candidates.apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)

    alignment: dict[str, Any] = {
        "state": "UNAVAILABLE",
        "reason": "DATA REQUIRED: candidate family",
        "input_observations": int(len(numeric_candidates)),
        "full_history_observations": int(len(selected_numeric)),
        "observations": 0,
        "dropped_incomplete_rows": 0,
        "history_coverage": 0.0,
        "minimum_history_coverage": float(min_candidate_history_coverage),
        "missing_policy": "complete-case intersection across selected and all candidates; missing returns are never zero-filled",
    }
    aligned_selected = clean.iloc[0:0]
    aligned_candidates = numeric_candidates.iloc[0:0]
    if candidate_count > 0:
        if not clean.index.is_unique or not numeric_candidates.index.is_unique:
            alignment["reason"] = "UNAVAILABLE: selected and candidate indices must be unique"
        elif not numeric_candidates.columns.is_unique:
            alignment["reason"] = "UNAVAILABLE: candidate names must be unique"
        else:
            marker = "__institutional_selected_baseline__"
            while marker in numeric_candidates.columns:
                marker += "_"
            combined = pd.concat([selected_numeric.rename(marker), numeric_candidates], axis=1, join="inner")
            common = combined.dropna(axis=0, how="any")
            alignment.update({
                "input_observations": int(len(combined)),
                "observations": int(len(common)),
                "dropped_incomplete_rows": int(len(combined) - len(common)),
                "history_coverage": (
                    float(len(common) / len(selected_numeric))
                    if len(selected_numeric)
                    else 0.0
                ),
            })
            if common.empty:
                alignment["reason"] = "DATA REQUIRED: selected strategy and candidates have no common complete observations"
            elif alignment["history_coverage"] < float(min_candidate_history_coverage):
                alignment["reason"] = (
                    f"DATA REQUIRED: candidate coverage {alignment['history_coverage']:.1%} is below "
                    f"the {float(min_candidate_history_coverage):.1%} full-history minimum"
                )
            else:
                aligned_selected = common.pop(marker)
                aligned_candidates = common
                alignment.update({"state": "AVAILABLE", "reason": "Common selected/candidate sample available"})

    sharpes = [annualized_sharpe(aligned_candidates[col], frequency) for col in aligned_candidates]
    dsr = deflated_sharpe_ratio(
        aligned_selected,
        num_trials=max(int(num_trials), candidate_count, 1),
        trial_sharpes=sharpes,
        periods=frequency,
        hac_lags=hac_lags,
    )
    if alignment["state"] != "AVAILABLE" and not dsr["available"]:
        dsr["reason"] = alignment["reason"]
    pbo = cscv_probability_of_backtest_overfitting(
        aligned_candidates,
        min_history_coverage=min_candidate_history_coverage,
    )
    reality = white_reality_check(
        aligned_candidates,
        bootstrap_samples=bootstrap_samples,
        seed=seed,
        min_history_coverage=min_candidate_history_coverage,
    )
    spa = hansen_spa_test(
        aligned_candidates,
        bootstrap_samples=bootstrap_samples,
        seed=seed + 1,
        min_history_coverage=min_candidate_history_coverage,
    )
    cpcv = cpcv_oos_validation(
        selected_numeric,
        numeric_candidates,
        periods=frequency,
        test_folds=cpcv_test_folds,
        total_folds=cpcv_total_folds,
        purge=cpcv_purge,
        embargo=cpcv_embargo,
        min_history_coverage=min_candidate_history_coverage,
        min_path_execution_fraction=cpcv_min_path_execution_fraction,
        min_paths_executed=cpcv_min_paths_executed,
    )
    sr = annualized_sharpe(clean, frequency)
    minimum_record = minimum_track_record_length(sr, periods=frequency) if np.isfinite(sr) else float("nan")
    return {
        "sharpe": sr,
        "psr": probabilistic_sharpe_ratio(clean, periods=frequency, hac_lags=hac_lags),
        "psr_hac": sharpe_hac_diagnostics(clean, hac_lags=hac_lags),
        "dsr": dsr,
        "pbo": pbo,
        "white_reality_check": reality,
        "hansen_spa": spa,
        "cpcv": cpcv,
        "cpcv_splits": int(cpcv["paths_executed"]),
        "minimum_track_record_days": minimum_record,
        "minimum_track_record_observations": minimum_record,
        "observations": int(len(clean)),
        "candidate_count": candidate_count,
        "candidate_alignment": alignment,
        "periods_per_year": frequency,
        "seed": int(seed),
    }
