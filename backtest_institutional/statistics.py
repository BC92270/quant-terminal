"""Multiple-testing-aware validation for investment research."""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from math import erf, exp, log, pi, sqrt
from typing import Iterable

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


def annualized_sharpe(returns: pd.Series, periods: int = 252) -> float:
    values = pd.to_numeric(returns, errors="coerce").dropna().to_numpy(dtype=float)
    if len(values) < 2:
        return float("nan")
    std = float(values.std(ddof=1))
    return float(values.mean() / std * sqrt(periods)) if std > 0 else float("nan")


def probabilistic_sharpe_ratio(
    returns: pd.Series,
    *,
    benchmark_sharpe: float = 0.0,
    periods: int = 252,
) -> float:
    values = pd.to_numeric(returns, errors="coerce").dropna().to_numpy(dtype=float)
    n = len(values)
    if n < 3:
        return float("nan")
    sr = annualized_sharpe(pd.Series(values), periods)
    centered = values - values.mean()
    sigma = values.std(ddof=1)
    if sigma <= 0:
        return float("nan")
    skew = float(np.mean(centered ** 3) / sigma ** 3)
    kurt = float(np.mean(centered ** 4) / sigma ** 4)
    denominator = sqrt(max(1.0 - skew * sr + ((kurt - 1.0) / 4.0) * sr * sr, 1e-12))
    z = (sr - benchmark_sharpe) * sqrt(max(n - 1, 1)) / denominator
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
) -> dict[str, float]:
    values = pd.to_numeric(returns, errors="coerce").dropna()
    candidates = np.asarray(list(trial_sharpes or []), dtype=float)
    candidates = candidates[np.isfinite(candidates)]
    sr_std = float(candidates.std(ddof=1)) if len(candidates) > 1 else 1.0 / sqrt(max(len(values), 2))
    sr_mean = float(candidates.mean()) if len(candidates) else 0.0
    threshold = expected_max_sharpe(num_trials, sr_std, mean_sharpe=sr_mean)
    probability = probabilistic_sharpe_ratio(values, benchmark_sharpe=threshold, periods=periods)
    return {
        "observed_sharpe": annualized_sharpe(values, periods),
        "expected_max_sharpe": threshold,
        "deflated_sharpe_probability": probability,
        "num_trials": int(max(num_trials, 1)),
    }


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
) -> dict[str, float]:
    clean = strategy_returns.apply(pd.to_numeric, errors="coerce").dropna(how="all").fillna(0.0)
    if clean.shape[0] < 10 or clean.shape[1] < 1:
        return {"p_value": float("nan"), "observed_max_mean": float("nan"), "strategies": clean.shape[1]}
    matrix = clean.to_numpy(dtype=float)
    observed = float(matrix.mean(axis=0).max())
    centered = matrix - matrix.mean(axis=0, keepdims=True)
    rng = np.random.default_rng(seed)
    indices = _stationary_bootstrap_indices(len(matrix), samples=bootstrap_samples, mean_block=mean_block, rng=rng)
    boot = np.empty(bootstrap_samples)
    for i, sample_index in enumerate(indices):
        boot[i] = centered[sample_index].mean(axis=0).max()
    return {
        "p_value": float((1 + np.sum(boot >= observed)) / (bootstrap_samples + 1)),
        "observed_max_mean": observed,
        "bootstrap_samples": int(bootstrap_samples),
        "strategies": int(clean.shape[1]),
    }


def hansen_spa_test(
    strategy_returns: pd.DataFrame,
    *,
    bootstrap_samples: int = 500,
    mean_block: int = 10,
    seed: int = 11,
) -> dict[str, float]:
    clean = strategy_returns.apply(pd.to_numeric, errors="coerce").dropna(how="all").fillna(0.0)
    matrix = clean.to_numpy(dtype=float)
    n = len(matrix)
    if n < 10 or clean.shape[1] < 1:
        return {"p_value": float("nan"), "observed_max_t": float("nan"), "strategies": clean.shape[1]}
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
    return {
        "p_value": float((1 + np.sum(boot >= observed)) / (bootstrap_samples + 1)),
        "observed_max_t": observed,
        "bootstrap_samples": int(bootstrap_samples),
        "strategies": int(clean.shape[1]),
    }


def cscv_probability_of_backtest_overfitting(
    strategy_returns: pd.DataFrame,
    *,
    partitions: int = 8,
    max_combinations: int = 2000,
    seed: int = 19,
) -> dict[str, float | int]:
    clean = strategy_returns.apply(pd.to_numeric, errors="coerce").dropna(how="all").fillna(0.0)
    n, strategies = clean.shape
    s = min(int(partitions), n)
    if s % 2:
        s -= 1
    if s < 4 or strategies < 2:
        return {"pbo": float("nan"), "combinations": 0, "partitions": s, "strategies": strategies}
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
    return {
        "pbo": float(np.mean(values <= 0.0)),
        "median_oos_logit": float(np.median(values)),
        "combinations": int(len(values)),
        "partitions": int(s),
        "strategies": int(strategies),
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
) -> float:
    spread = observed_sharpe - target_sharpe
    if spread <= 0:
        return float("inf")
    z = _normal_ppf(confidence)
    correction = max(1.0 - skew * observed_sharpe + ((kurtosis - 1.0) / 4.0) * observed_sharpe ** 2, 1e-12)
    return float(1.0 + correction * (z / spread) ** 2)


def institutional_validation_suite(
    returns: pd.Series,
    *,
    candidates: pd.DataFrame | None = None,
    num_trials: int = 1,
    bootstrap_samples: int = 500,
    seed: int = 7,
) -> dict[str, object]:
    clean = pd.to_numeric(returns, errors="coerce").dropna()
    if candidates is None or candidates.empty:
        candidates = pd.DataFrame({"selected": clean})
    sharpes = [annualized_sharpe(candidates[col]) for col in candidates]
    dsr = deflated_sharpe_ratio(clean, num_trials=max(num_trials, candidates.shape[1]), trial_sharpes=sharpes)
    pbo = cscv_probability_of_backtest_overfitting(candidates)
    reality = white_reality_check(candidates, bootstrap_samples=bootstrap_samples, seed=seed)
    spa = hansen_spa_test(candidates, bootstrap_samples=bootstrap_samples, seed=seed + 1)
    sr = annualized_sharpe(clean)
    return {
        "sharpe": sr,
        "psr": probabilistic_sharpe_ratio(clean),
        "dsr": dsr,
        "pbo": pbo,
        "white_reality_check": reality,
        "hansen_spa": spa,
        "minimum_track_record_days": minimum_track_record_length(sr) if np.isfinite(sr) else float("nan"),
        "observations": int(len(clean)),
        "candidate_count": int(candidates.shape[1]),
        "seed": int(seed),
    }
