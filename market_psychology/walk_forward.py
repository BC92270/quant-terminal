from __future__ import annotations

"""Point-in-time / walk-forward validation for Market Psychology Lab V2.4.1.

The module is intentionally research-facing. It does not optimize the behavioral
state engine. Parameters, alert definitions and memory retrieval rules are treated
as frozen inputs and are evaluated on chronological future observations.

Design constraints
------------------
* Expanding chronological folds; no random train/test splits.
* Purge equal to the forecast horizon so a training label never reaches into the
  following test window.
* Final holdout is evaluated separately from development walk-forward folds.
* Train-derived quintile thresholds are applied unchanged to each test fold.
* HAC/Newey-West inference is used for overlapping forward horizons when
  statsmodels is available.
* Moving-block bootstrap confidence intervals preserve local serial dependence.
* Benjamini-Hochberg FDR is applied across the full development hypothesis family.
* Behavioral Memory validation only uses analogue outcomes that would already have
  been observable at the historical decision date.

None of the output is a production signal or probability of future performance.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
import hashlib
import json
import math

import numpy as np
import pandas as pd

try:  # optional but present in the Quant Terminal environment
    from scipy.stats import spearmanr, norm
except Exception:  # pragma: no cover
    spearmanr = None
    norm = None

try:
    import statsmodels.api as sm
except Exception:  # pragma: no cover
    sm = None

from .behavioral_memory import (
    DOMAIN_SPECS,
    DOMAIN_TEMPORAL_INTEGRITY,
    DOMAIN_WEIGHTS,
    MEMORY_ACTIVATION_QUANTILE,
    MEMORY_ACTIVATION_THRESHOLD,
    MEMORY_DOMAIN_CUE_THRESHOLD,
    MEMORY_EXCLUSION_DAYS,
    MEMORY_MIN_COVERAGE,
    MEMORY_SIMILARITY_QUANTILE,
    MEMORY_SIMILARITY_THRESHOLD,
    MEMORY_SPACING_DAYS,
    _candidate_salience,
    _domain_current_and_history,
    _domain_similarity,
    _select_spaced,
    load_snapshot_archive,
)

VALIDATION_VERSION = "V2.4.1"
CORE_MECHANISMS: tuple[str, ...] = (
    "attention",
    "fear",
    "herding",
    "extrapolation",
    "reflexivity",
)
DEFAULT_HORIZONS: tuple[int, ...] = (5, 20, 60)
MEMORY_HORIZONS: tuple[int, ...] = (20, 60)


@dataclass(frozen=True)
class ValidationConfig:
    min_train: int
    test_size: int
    holdout_size: int
    step: int
    bootstrap_samples: int
    memory_step: int
    profile: str


@dataclass(frozen=True)
class Fold:
    fold: str
    partition: str
    train_end: int  # exclusive, before horizon purge
    test_start: int
    test_end: int   # exclusive


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default
        x = float(value)
        return x if np.isfinite(x) else default
    except Exception:
        return default


def _normal_two_sided_p(z: float | None) -> float | None:
    if z is None or not np.isfinite(z):
        return None
    if norm is not None:
        return float(2.0 * norm.sf(abs(float(z))))
    return float(math.erfc(abs(float(z)) / math.sqrt(2.0)))


def _spearman(x: pd.Series, y: pd.Series) -> tuple[float | None, float | None]:
    frame = pd.DataFrame({"x": pd.to_numeric(x, errors="coerce"), "y": pd.to_numeric(y, errors="coerce")}).dropna()
    if len(frame) < 8 or frame["x"].nunique() < 3 or frame["y"].nunique() < 3:
        return None, None
    if spearmanr is not None:
        res = spearmanr(frame["x"].to_numpy(), frame["y"].to_numpy())
        try:
            return float(res.statistic), float(res.pvalue)
        except Exception:
            try:
                return float(res[0]), float(res[1])
            except Exception:
                pass
    rho = frame["x"].rank().corr(frame["y"].rank())
    if rho is None or not np.isfinite(rho):
        return None, None
    # Large-sample fallback only; HAC p-value below remains the preferred inference.
    n = len(frame)
    denom = max(1.0 - float(rho) ** 2, 1e-9)
    t = float(rho) * math.sqrt(max(n - 2, 1) / denom)
    return float(rho), _normal_two_sided_p(t)


def _hac_rank_tstat(x: pd.Series, y: pd.Series, maxlags: int) -> tuple[float | None, float | None]:
    frame = pd.DataFrame({"x": pd.to_numeric(x, errors="coerce"), "y": pd.to_numeric(y, errors="coerce")}).dropna()
    if len(frame) < max(30, 3 * maxlags // 2) or frame["x"].nunique() < 3 or frame["y"].nunique() < 3:
        return None, None
    xr = frame["x"].rank(pct=True).to_numpy(dtype=float)
    yr = frame["y"].rank(pct=True).to_numpy(dtype=float)
    if sm is None:  # fallback to naive rank-correlation t-stat
        rho = np.corrcoef(xr, yr)[0, 1]
        if not np.isfinite(rho):
            return None, None
        t = rho * math.sqrt(max(len(frame) - 2, 1) / max(1 - rho * rho, 1e-9))
        return float(t), _normal_two_sided_p(float(t))
    try:
        X = sm.add_constant(xr, has_constant="add")
        fit = sm.OLS(yr, X, missing="drop").fit(cov_type="HAC", cov_kwds={"maxlags": int(max(1, maxlags))})
        t = float(fit.tvalues[1])
        p = float(fit.pvalues[1])
        return t, p
    except Exception:
        return None, None


def _moving_block_indices(n: int, block: int, rng: np.random.Generator) -> np.ndarray:
    if n <= 0:
        return np.array([], dtype=int)
    block = int(np.clip(block, 1, n))
    starts_max = max(n - block + 1, 1)
    out: list[int] = []
    while len(out) < n:
        start = int(rng.integers(0, starts_max)) if starts_max > 1 else 0
        out.extend(range(start, min(start + block, n)))
    return np.asarray(out[:n], dtype=int)


def _block_bootstrap_corr_ci(
    x: pd.Series,
    y: pd.Series,
    *,
    block: int,
    samples: int,
    seed: int,
) -> tuple[float | None, float | None]:
    frame = pd.DataFrame({"x": pd.to_numeric(x, errors="coerce"), "y": pd.to_numeric(y, errors="coerce")}).dropna()
    if len(frame) < 35 or samples <= 0:
        return None, None
    xv = frame["x"].to_numpy(dtype=float)
    yv = frame["y"].to_numpy(dtype=float)
    rng = np.random.default_rng(int(seed) & 0xFFFFFFFF)
    vals: list[float] = []
    for _ in range(int(samples)):
        idx = _moving_block_indices(len(frame), max(2, int(block)), rng)
        if len(np.unique(xv[idx])) < 3 or len(np.unique(yv[idx])) < 3:
            continue
        if spearmanr is not None:
            try:
                rho = float(spearmanr(xv[idx], yv[idx]).statistic)
            except Exception:
                rho = float(pd.Series(xv[idx]).rank().corr(pd.Series(yv[idx]).rank()))
        else:
            rho = float(pd.Series(xv[idx]).rank().corr(pd.Series(yv[idx]).rank()))
        if np.isfinite(rho):
            vals.append(rho)
    if len(vals) < max(30, int(samples * 0.3)):
        return None, None
    return float(np.quantile(vals, 0.025)), float(np.quantile(vals, 0.975))


def _bootstrap_difference_ci(
    event_values: pd.Series,
    baseline_values: pd.Series,
    *,
    samples: int,
    seed: int,
) -> tuple[float | None, float | None, float | None]:
    ev = pd.to_numeric(event_values, errors="coerce").dropna().to_numpy(dtype=float)
    base = pd.to_numeric(baseline_values, errors="coerce").dropna().to_numpy(dtype=float)
    if len(ev) < 3 or len(base) < 20:
        return None, None, None
    rng = np.random.default_rng(seed & 0xFFFFFFFF)
    diffs = np.empty(int(samples), dtype=float)
    for i in range(int(samples)):
        e = rng.choice(ev, size=len(ev), replace=True)
        b = rng.choice(base, size=len(ev), replace=True)
        diffs[i] = np.nanmean(e) - np.nanmean(b)
    lo, hi = np.quantile(diffs, [0.025, 0.975])
    p = 2.0 * min(float(np.mean(diffs <= 0)), float(np.mean(diffs >= 0)))
    return float(lo), float(hi), float(min(max(p, 0.0), 1.0))


def _bh_qvalues(pvalues: Iterable[Any]) -> np.ndarray:
    p = np.asarray([np.nan if _safe_float(v) is None else float(v) for v in pvalues], dtype=float)
    out = np.full(len(p), np.nan)
    valid = np.where(np.isfinite(p))[0]
    if len(valid) == 0:
        return out
    order_local = np.argsort(p[valid])
    ordered_idx = valid[order_local]
    m = len(ordered_idx)
    q_ordered = np.empty(m, dtype=float)
    prev = 1.0
    for rank_rev in range(m - 1, -1, -1):
        rank = rank_rev + 1
        idx = ordered_idx[rank_rev]
        q = min(prev, p[idx] * m / rank)
        q_ordered[rank_rev] = q
        prev = q
    for j, idx in enumerate(ordered_idx):
        out[idx] = min(max(q_ordered[j], 0.0), 1.0)
    return out


def choose_validation_config(n_rows: int, profile: str = "STANDARD") -> ValidationConfig | None:
    n = int(n_rows)
    profile = str(profile or "STANDARD").upper().strip()
    deep = profile == "DEEP"
    if n >= 1000:
        return ValidationConfig(
            min_train=504,
            test_size=126,
            holdout_size=252,
            step=126,
            bootstrap_samples=500 if deep else 220,
            memory_step=5 if deep else 10,
            profile=profile,
        )
    if n >= 650:
        return ValidationConfig(
            min_train=378,
            test_size=84,
            holdout_size=126,
            step=84,
            bootstrap_samples=400 if deep else 180,
            memory_step=5 if deep else 10,
            profile=profile,
        )
    if n >= 450:
        return ValidationConfig(
            min_train=252,
            test_size=63,
            holdout_size=84,
            step=63,
            bootstrap_samples=300 if deep else 140,
            memory_step=5 if deep else 10,
            profile=profile,
        )
    return None


def build_walk_forward_folds(n_rows: int, config: ValidationConfig) -> list[Fold]:
    n = int(n_rows)
    dev_end = n - int(config.holdout_size)
    folds: list[Fold] = []
    start = int(config.min_train)
    k = 1
    while start < dev_end:
        end = min(start + int(config.test_size), dev_end)
        if end - start >= max(30, int(config.test_size * 0.45)):
            folds.append(Fold(f"WF{k}", "WALK_FORWARD", start, start, end))
            k += 1
        start += int(config.step)
    if config.holdout_size >= 40 and dev_end < n:
        folds.append(Fold("HOLDOUT", "HOLDOUT", dev_end, dev_end, n))
    return folds


def _state_col(history: pd.DataFrame, key: str) -> str | None:
    for col in (f"{key}_latent", key):
        if col in history.columns:
            return col
    return None


def _future_return(close: pd.Series, horizon: int) -> pd.Series:
    return close.shift(-horizon) / close - 1.0


def _future_realized_vol(close: pd.Series, horizon: int) -> pd.Series:
    ret = close.pct_change()
    return ret.shift(-1).rolling(horizon).std().shift(-(horizon - 1)) * math.sqrt(252)


def _future_tail_loss(close: pd.Series, horizon: int) -> pd.Series:
    values = pd.to_numeric(close, errors="coerce").to_numpy(dtype=float)
    out = np.full(len(values), np.nan)
    for i in range(len(values) - horizon):
        start = values[i]
        if not np.isfinite(start) or start == 0:
            continue
        path = values[i + 1 : i + horizon + 1]
        if not np.isfinite(path).any():
            continue
        worst = np.nanmin(path / start - 1.0)
        out[i] = max(-float(worst), 0.0)
    return pd.Series(out, index=close.index, dtype=float)


def _future_state_shift(history: pd.DataFrame, horizon: int) -> pd.Series:
    cols = [_state_col(history, k) for k in CORE_MECHANISMS]
    cols = [c for c in cols if c is not None]
    if len(cols) < 3:
        return pd.Series(np.nan, index=history.index, dtype=float)
    x = history[cols].apply(pd.to_numeric, errors="coerce")
    future = x.shift(-horizon)
    delta = future - x
    return np.sqrt((delta ** 2).mean(axis=1, skipna=True))


def build_validation_targets(history: pd.DataFrame, horizons: tuple[int, ...] = DEFAULT_HORIZONS) -> pd.DataFrame:
    if history is None or history.empty or "close" not in history.columns:
        return pd.DataFrame()
    work = history.copy().sort_values("date").reset_index(drop=True)
    close = pd.to_numeric(work["close"], errors="coerce")
    for h in horizons:
        work[f"target_return_{h}"] = _future_return(close, h)
        work[f"target_vol_{h}"] = _future_realized_vol(close, h)
        work[f"target_tail_{h}"] = _future_tail_loss(close, h)
        work[f"target_shift_{h}"] = _future_state_shift(work, h)
    return work


def _mechanism_validity_mask(work: pd.DataFrame, score_col: str) -> pd.Series:
    score = pd.to_numeric(work[score_col], errors="coerce")
    mask = score.notna()
    raw_name = score_col.replace("_latent", "") + "_raw" if score_col.endswith("_latent") else f"{score_col}_raw"
    if raw_name in work.columns:
        raw = pd.to_numeric(work[raw_name], errors="coerce")
        # Detect long synthetic/constant proxy plateaus. This is especially important
        # for long-horizon Herding history when benchmark history is intentionally
        # truncated to reduce provider pressure.
        rolling_range = raw.rolling(60, min_periods=40).max() - raw.rolling(60, min_periods=40).min()
        stale = rolling_range <= 1e-8
        mask &= ~stale.fillna(False)
    return mask


def _target_map(h: int) -> dict[str, str]:
    return {
        "Return": f"target_return_{h}",
        "Future vol": f"target_vol_{h}",
        "Tail loss": f"target_tail_{h}",
        "Behavioral state shift": f"target_shift_{h}",
    }


def _fold_records_for_combo(
    work: pd.DataFrame,
    mechanism: str,
    score_col: str,
    target_name: str,
    target_col: str,
    horizon: int,
    folds: list[Fold],
) -> pd.DataFrame:
    valid_mask = _mechanism_validity_mask(work, score_col)
    rows: list[pd.DataFrame] = []
    for fold in folds:
        # Purge training labels whose future horizon overlaps the test window.
        train_end = max(0, int(fold.test_start) - int(horizon))
        train = work.iloc[:train_end].copy()
        test = work.iloc[fold.test_start : fold.test_end].copy()
        train = train.loc[valid_mask.iloc[:train_end].to_numpy()]
        test = test.loc[valid_mask.iloc[fold.test_start : fold.test_end].to_numpy()]
        train_pair = train[[score_col, target_col]].apply(pd.to_numeric, errors="coerce").dropna()
        test_pair = test[[score_col, target_col]].apply(pd.to_numeric, errors="coerce").dropna()
        if len(train_pair) < 120 or len(test_pair) < max(18, min(30, horizon)):
            continue
        q20 = float(train_pair[score_col].quantile(0.20))
        q80 = float(train_pair[score_col].quantile(0.80))
        out = test.loc[test_pair.index, ["date", score_col, target_col]].copy()
        out = out.rename(columns={score_col: "score", target_col: "target"})
        out["bucket"] = np.where(out["score"] >= q80, "HIGH", np.where(out["score"] <= q20, "LOW", "MID"))
        out["fold"] = fold.fold
        out["partition"] = fold.partition
        out["mechanism"] = mechanism.title()
        out["target_name"] = target_name
        out["horizon"] = horizon

        if target_name == "Tail loss":
            train_rho, _ = _spearman(train_pair[score_col], train_pair[target_col])
            orientation = 1.0 if (train_rho or 0.0) >= 0 else -1.0
            train_risk_score = orientation * train_pair[score_col]
            risk_q80 = float(train_risk_score.quantile(0.80))
            tail_threshold = float(train_pair[target_col].quantile(0.90))
            out["tail_event"] = pd.to_numeric(out["target"], errors="coerce") >= tail_threshold
            out["risk_bucket"] = (orientation * pd.to_numeric(out["score"], errors="coerce")) >= risk_q80
            out["tail_threshold_train"] = tail_threshold
            out["risk_orientation"] = orientation
        rows.append(out)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def _summarize_combo(records: pd.DataFrame, horizon: int, bootstrap_samples: int, seed: int) -> dict[str, Any]:
    if records is None or records.empty:
        return {}
    rho, naive_p = _spearman(records["score"], records["target"])
    hac_t, hac_p = _hac_rank_tstat(records["score"], records["target"], maxlags=max(1, int(horizon)))
    ci_lo, ci_hi = _block_bootstrap_corr_ci(
        records["score"], records["target"],
        block=max(5, int(horizon)), samples=int(bootstrap_samples), seed=int(seed),
    )
    highs = pd.to_numeric(records.loc[records["bucket"] == "HIGH", "target"], errors="coerce").dropna()
    lows = pd.to_numeric(records.loc[records["bucket"] == "LOW", "target"], errors="coerce").dropna()
    high_low = float(highs.mean() - lows.mean()) if len(highs) >= 3 and len(lows) >= 3 else np.nan
    fold_ics: list[float] = []
    for _, g in records.groupby("fold"):
        frho, _ = _spearman(g["score"], g["target"])
        if frho is not None:
            fold_ics.append(float(frho))
    stability = np.nan
    if rho is not None and fold_ics:
        sign = 1 if rho >= 0 else -1
        stability = float(np.mean([1 if (v >= 0) == (sign >= 0) else 0 for v in fold_ics]))
    tail_lift = np.nan
    tail_event_rate = np.nan
    baseline_tail_rate = np.nan
    if "tail_event" in records.columns and "risk_bucket" in records.columns:
        event = records["tail_event"].astype(bool)
        risk = records["risk_bucket"].astype(bool)
        baseline_tail_rate = float(event.mean()) if len(event) else np.nan
        tail_event_rate = float(event[risk].mean()) if risk.any() else np.nan
        if np.isfinite(tail_event_rate) and np.isfinite(baseline_tail_rate) and baseline_tail_rate > 0:
            tail_lift = float(tail_event_rate / baseline_tail_rate)
    return {
        "N": int(len(records)),
        "Folds": int(records["fold"].nunique()),
        "OOS IC": rho,
        "Naive p": naive_p,
        "HAC t": hac_t,
        "HAC p": hac_p,
        "Bootstrap CI low": ci_lo,
        "Bootstrap CI high": ci_hi,
        "High - low": high_low,
        "High N": int(len(highs)),
        "Low N": int(len(lows)),
        "Fold IC median": float(np.median(fold_ics)) if fold_ics else np.nan,
        "Fold sign stability": stability,
        "Tail event rate risk bucket": tail_event_rate,
        "Tail event baseline": baseline_tail_rate,
        "Tail event lift": tail_lift,
    }



def _ci_excludes_zero(low: Any, high: Any) -> bool:
    lo = _safe_float(low)
    hi = _safe_float(high)
    return bool(lo is not None and hi is not None and (lo > 0 or hi < 0))


def _classify_holdout_replication(
    development_evidence: Any,
    dev_ic: Any,
    holdout_ic: Any,
    holdout_p: Any,
    holdout_ci_low: Any,
    holdout_ci_high: Any,
) -> str:
    """Strict evidence classification; does not alter any model or score.

    STATISTICALLY REPLICATED requires robust development evidence, same sign,
    non-trivial holdout effect, holdout p <= 10%, and a holdout bootstrap interval
    excluding zero. Same-sign effects without that precision are only directional.
    Opposite-sign evidence is called a failure only when the holdout itself is
    statistically informative; otherwise the result is inconclusive.
    """
    dev_status = str(development_evidence or "")
    eligible = dev_status in {"ROBUST OOS", "TENTATIVE"}
    dev = _safe_float(dev_ic)
    hold = _safe_float(holdout_ic)
    hp = _safe_float(holdout_p)
    if not eligible or dev is None or hold is None or abs(dev) < 1e-12 or abs(hold) < 1e-12:
        return "INCONCLUSIVE"
    same_sign = (dev * hold) > 0
    ci_sig = _ci_excludes_zero(holdout_ci_low, holdout_ci_high)
    p_sig = hp is not None and hp <= 0.10
    nontrivial = abs(hold) >= 0.03
    if dev_status == "ROBUST OOS" and same_sign and nontrivial and p_sig and ci_sig:
        return "STATISTICALLY REPLICATED"
    if same_sign and nontrivial:
        return "DIRECTIONALLY CONFIRMED"
    if (not same_sign) and nontrivial and (p_sig or ci_sig):
        return "FAILED REPLICATION"
    return "INCONCLUSIVE"


def _build_mechanism_evidence_matrix(
    dev_table: pd.DataFrame,
    confirmation: pd.DataFrame,
    coverage: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Classify evidence strength from walk-forward + holdout results only."""
    targets = ["Return", "Future vol", "Tail loss", "Behavioral state shift"]
    mechanisms = [m.title() for m in CORE_MECHANISMS]
    coverage_map: dict[str, float] = {}
    if isinstance(coverage, pd.DataFrame) and not coverage.empty:
        for _, r in coverage.iterrows():
            coverage_map[str(r.get("Mechanism"))] = float(pd.to_numeric(pd.Series([r.get("Coverage")]), errors="coerce").iloc[0]) if pd.notna(r.get("Coverage")) else np.nan
    rows = []
    details = []
    for mech in mechanisms:
        out = {"Mechanism": mech}
        mech_cov = coverage_map.get(mech, np.nan)
        for target in targets:
            d = dev_table[(dev_table["Mechanism"] == mech) & (dev_table["Target"] == target)] if not dev_table.empty else pd.DataFrame()
            c = confirmation[(confirmation["Mechanism"] == mech) & (confirmation["Target"] == target)] if not confirmation.empty else pd.DataFrame()
            robust = int(d["Development evidence"].eq("ROBUST OOS").sum()) if not d.empty else 0
            tentative = int(d["Development evidence"].eq("TENTATIVE").sum()) if not d.empty else 0
            statrep = int(c["Replication"].eq("STATISTICALLY REPLICATED").sum()) if not c.empty else 0
            directional = int(c["Replication"].eq("DIRECTIONALLY CONFIRMED").sum()) if not c.empty else 0
            failed = int(c["Replication"].eq("FAILED REPLICATION").sum()) if not c.empty else 0
            if not np.isfinite(mech_cov) or mech_cov < 0.50 or d.empty:
                level = "N/A"
            elif failed > 0 and statrep == 0 and directional == 0:
                level = "NONE"
            elif statrep >= 1 and robust >= 2 and failed == 0:
                level = "HIGH"
            elif (statrep >= 1 and robust >= 1) or (robust >= 1 and directional >= 1 and failed == 0):
                level = "MODERATE"
            elif robust >= 1 or tentative >= 1 or directional >= 1:
                level = "LOW"
            else:
                level = "NONE"
            out[target] = level
            details.append({
                "Mechanism": mech,
                "Target": target,
                "Coverage": mech_cov,
                "Robust OOS horizons": robust,
                "Tentative horizons": tentative,
                "Statistically replicated": statrep,
                "Directionally confirmed": directional,
                "Failed replication": failed,
                "Evidence": level,
            })
        rows.append(out)
    return pd.DataFrame(rows), pd.DataFrame(details)

def evaluate_mechanisms_walk_forward(
    history: pd.DataFrame,
    config: ValidationConfig,
    *,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
) -> dict[str, Any]:
    work = build_validation_targets(history, horizons)
    if work.empty:
        return {"available": False, "reason": "Validation targets unavailable."}
    folds = build_walk_forward_folds(len(work), config)
    if not folds or not any(f.partition == "WALK_FORWARD" for f in folds):
        return {"available": False, "reason": "Insufficient history for chronological walk-forward folds."}

    dev_rows: list[dict[str, Any]] = []
    hold_rows: list[dict[str, Any]] = []
    dev_records_all: list[pd.DataFrame] = []
    hold_records_all: list[pd.DataFrame] = []
    seed_base = 240811
    for m_idx, mechanism in enumerate(CORE_MECHANISMS):
        score_col = _state_col(work, mechanism)
        if score_col is None:
            continue
        for h_idx, horizon in enumerate(horizons):
            for t_idx, (target_name, target_col) in enumerate(_target_map(horizon).items()):
                records = _fold_records_for_combo(work, mechanism, score_col, target_name, target_col, horizon, folds)
                if records.empty:
                    continue
                dev = records[records["partition"] == "WALK_FORWARD"].copy()
                hold = records[records["partition"] == "HOLDOUT"].copy()
                if not dev.empty:
                    summary = _summarize_combo(dev, horizon, config.bootstrap_samples, seed_base + m_idx * 1000 + h_idx * 100 + t_idx)
                    dev_rows.append({
                        "Mechanism": mechanism.title(),
                        "Horizon": f"{horizon}D",
                        "Target": target_name,
                        **summary,
                    })
                    dev_records_all.append(dev)
                if not hold.empty:
                    summary = _summarize_combo(hold, horizon, max(100, config.bootstrap_samples // 2), seed_base + 100000 + m_idx * 1000 + h_idx * 100 + t_idx)
                    hold_rows.append({
                        "Mechanism": mechanism.title(),
                        "Horizon": f"{horizon}D",
                        "Target": target_name,
                        **summary,
                    })
                    hold_records_all.append(hold)

    dev_table = pd.DataFrame(dev_rows)
    hold_table = pd.DataFrame(hold_rows)
    if dev_table.empty:
        return {"available": False, "reason": "No mechanism has enough OOS observations after purge/burn-in."}

    pcol = pd.to_numeric(dev_table.get("HAC p"), errors="coerce")
    dev_table["FDR q"] = _bh_qvalues(pcol)
    ci_excludes_zero = (
        (pd.to_numeric(dev_table["Bootstrap CI low"], errors="coerce") > 0)
        | (pd.to_numeric(dev_table["Bootstrap CI high"], errors="coerce") < 0)
    )
    stable = pd.to_numeric(dev_table["Fold sign stability"], errors="coerce") >= 0.60
    q_ok = pd.to_numeric(dev_table["FDR q"], errors="coerce") <= 0.10
    enough_folds = pd.to_numeric(dev_table["Folds"], errors="coerce") >= 3
    tentative = (pd.to_numeric(dev_table["HAC p"], errors="coerce") <= 0.10) & (pd.to_numeric(dev_table["Fold sign stability"], errors="coerce") >= 0.50)
    dev_table["Development evidence"] = np.where(
        q_ok & ci_excludes_zero & stable & enough_folds,
        "ROBUST OOS",
        np.where(tentative, "TENTATIVE", "NO EVIDENCE"),
    )

    confirmation = pd.DataFrame()
    if not hold_table.empty:
        keys = ["Mechanism", "Horizon", "Target"]
        d = dev_table[keys + ["OOS IC", "FDR q", "Development evidence", "Fold sign stability"]].rename(columns={
            "OOS IC": "Dev IC", "FDR q": "Dev q", "Fold sign stability": "Dev stability"
        })
        h = hold_table[keys + ["OOS IC", "HAC p", "Bootstrap CI low", "Bootstrap CI high", "N"]].rename(columns={
            "OOS IC": "Holdout IC", "HAC p": "Holdout p", "Bootstrap CI low": "Holdout CI low", "Bootstrap CI high": "Holdout CI high", "N": "Holdout N"
        })
        confirmation = d.merge(h, on=keys, how="left")
        dev_ic = pd.to_numeric(confirmation["Dev IC"], errors="coerce")
        hold_ic = pd.to_numeric(confirmation["Holdout IC"], errors="coerce")
        same_sign = (dev_ic * hold_ic) > 0
        confirmation["Same sign"] = same_sign
        confirmation["Holdout CI excludes zero"] = [
            _ci_excludes_zero(lo, hi) for lo, hi in zip(confirmation["Holdout CI low"], confirmation["Holdout CI high"])
        ]
        confirmation["Replication"] = [
            _classify_holdout_replication(dev_status, d_ic, h_ic, h_p, h_lo, h_hi)
            for dev_status, d_ic, h_ic, h_p, h_lo, h_hi in zip(
                confirmation["Development evidence"], confirmation["Dev IC"], confirmation["Holdout IC"],
                confirmation["Holdout p"], confirmation["Holdout CI low"], confirmation["Holdout CI high"]
            )
        ]

    coverage_rows = []
    dates = pd.to_datetime(work["date"], errors="coerce", utc=True)
    for mechanism in CORE_MECHANISMS:
        score_col = _state_col(work, mechanism)
        if score_col is None:
            continue
        vm = _mechanism_validity_mask(work, score_col)
        valid_dates = dates[vm.to_numpy()]
        coverage_rows.append({
            "Mechanism": mechanism.title(),
            "Valid rows": int(vm.sum()),
            "Coverage": float(vm.mean()) if len(vm) else np.nan,
            "First valid": valid_dates.min() if not valid_dates.empty else pd.NaT,
            "Last valid": valid_dates.max() if not valid_dates.empty else pd.NaT,
            "Validation note": "Constant raw-proxy plateaus are excluded" if f"{mechanism}_raw" in work.columns else "Latent-state availability mask",
        })

    split_rows = []
    for f in folds:
        split_rows.append({
            "Fold": f.fold,
            "Partition": f.partition,
            "Train end (pre-purge)": dates.iloc[max(f.test_start - 1, 0)] if f.test_start > 0 else pd.NaT,
            "Test start": dates.iloc[f.test_start] if f.test_start < len(dates) else pd.NaT,
            "Test end": dates.iloc[f.test_end - 1] if f.test_end - 1 < len(dates) else pd.NaT,
            "Test rows": f.test_end - f.test_start,
        })

    coverage_table = pd.DataFrame(coverage_rows)
    evidence_matrix, evidence_details = _build_mechanism_evidence_matrix(dev_table, confirmation, coverage_table)

    return {
        "available": True,
        "development": dev_table.sort_values(["Target", "Horizon", "Mechanism"]).reset_index(drop=True),
        "holdout": hold_table.sort_values(["Target", "Horizon", "Mechanism"]).reset_index(drop=True) if not hold_table.empty else pd.DataFrame(),
        "confirmation": confirmation.sort_values(["Target", "Horizon", "Mechanism"]).reset_index(drop=True) if not confirmation.empty else pd.DataFrame(),
        "splits": pd.DataFrame(split_rows),
        "coverage": coverage_table,
        "evidence_matrix": evidence_matrix,
        "evidence_details": evidence_details,
        "folds": folds,
        "work": work,
        "development_records": pd.concat(dev_records_all, ignore_index=True) if dev_records_all else pd.DataFrame(),
        "holdout_records": pd.concat(hold_records_all, ignore_index=True) if hold_records_all else pd.DataFrame(),
        "hypotheses": int(len(dev_table)),
        "fdr_survivors": int((pd.to_numeric(dev_table["FDR q"], errors="coerce") <= 0.10).sum()),
        "robust_oos": int(dev_table["Development evidence"].eq("ROBUST OOS").sum()),
        "statistically_replicated": int(confirmation["Replication"].eq("STATISTICALLY REPLICATED").sum()) if not confirmation.empty else 0,
        "directionally_confirmed": int(confirmation["Replication"].eq("DIRECTIONALLY CONFIRMED").sum()) if not confirmation.empty else 0,
        "inconclusive": int(confirmation["Replication"].eq("INCONCLUSIVE").sum()) if not confirmation.empty else 0,
        "failed_replication": int(confirmation["Replication"].eq("FAILED REPLICATION").sum()) if not confirmation.empty else 0,
        "replicated": int(confirmation["Replication"].eq("STATISTICALLY REPLICATED").sum()) if not confirmation.empty else 0,
    }


def _alarm_onsets(history: pd.DataFrame) -> pd.DataFrame:
    if history is None or history.empty or "date" not in history.columns:
        return pd.DataFrame()
    specs = [
        ("ATTENTION SHOCK", "attention"),
        ("FEAR STRESS", "fear"),
        ("CROWDING / HERDING", "herding"),
        ("EXTRAPOLATION SURGE", "extrapolation"),
        ("REFLEXIVE HEAT", "reflexivity"),
    ]
    rows = []
    for label, key in specs:
        sev_col = f"{key}_severity"
        if sev_col not in history.columns:
            continue
        sev = pd.to_numeric(history[sev_col], errors="coerce").fillna(0)
        cond = sev >= 2
        onset = cond & ~cond.shift(1, fill_value=False)
        for i in history.index[onset]:
            rows.append({"row": int(i), "Date": history.loc[i, "date"], "Alarm": label, "Severity": int(sev.loc[i])})
    return pd.DataFrame(rows)


def evaluate_alarm_event_study(
    target_work: pd.DataFrame,
    config: ValidationConfig,
    *,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
) -> pd.DataFrame:
    if target_work is None or target_work.empty:
        return pd.DataFrame()
    events = _alarm_onsets(target_work)
    if events.empty:
        return pd.DataFrame()
    holdout_start = len(target_work) - config.holdout_size
    eval_start = config.min_train
    rows: list[dict[str, Any]] = []
    for partition, lo, hi in (
        ("WALK_FORWARD", eval_start, holdout_start),
        ("HOLDOUT", holdout_start, len(target_work)),
    ):
        part_events = events[(events["row"] >= lo) & (events["row"] < hi)]
        for alarm, group in part_events.groupby("Alarm"):
            for h in horizons:
                for target_name, target_col in {
                    "Return": f"target_return_{h}",
                    "Future vol": f"target_vol_{h}",
                    "Tail loss": f"target_tail_{h}",
                }.items():
                    idx = group["row"].astype(int).to_list()
                    ev = pd.to_numeric(target_work.loc[idx, target_col], errors="coerce").dropna()
                    base = pd.to_numeric(target_work.iloc[lo:hi][target_col], errors="coerce").dropna()
                    if len(ev) < 2 or len(base) < 30:
                        continue
                    diff = float(ev.mean() - base.mean())
                    lo_ci, hi_ci, p = _bootstrap_difference_ci(
                        ev, base, samples=max(180, config.bootstrap_samples // 2),
                        seed=8811 + h * 13 + sum(ord(c) for c in alarm + target_name + partition),
                    )
                    rows.append({
                        "Partition": partition,
                        "Alarm": alarm,
                        "Horizon": f"{h}D",
                        "Target": target_name,
                        "Events": int(len(ev)),
                        "Event mean": float(ev.mean()),
                        "Baseline mean": float(base.mean()),
                        "Event - baseline": diff,
                        "Bootstrap CI low": lo_ci,
                        "Bootstrap CI high": hi_ci,
                        "Bootstrap p": p,
                    })
    out = pd.DataFrame(rows)
    if not out.empty:
        dev_mask = out["Partition"].eq("WALK_FORWARD")
        q = np.full(len(out), np.nan)
        q[dev_mask.to_numpy()] = _bh_qvalues(out.loc[dev_mask, "Bootstrap p"])
        out["FDR q"] = q
    return out



def classify_alarm_predictive_evidence(alarm_study: pd.DataFrame) -> pd.DataFrame:
    """Summarize acute alarms without implying that unusual states are forecasts."""
    if alarm_study is None or alarm_study.empty:
        return pd.DataFrame()
    rows = []
    keys = ["Horizon", "Target"]
    for alarm, grp in alarm_study.groupby("Alarm"):
        dev = grp[grp["Partition"].eq("WALK_FORWARD")].copy()
        hold = grp[grp["Partition"].eq("HOLDOUT")].copy()
        if dev.empty:
            continue
        dev_ci = (pd.to_numeric(dev["Bootstrap CI low"], errors="coerce") > 0) | (pd.to_numeric(dev["Bootstrap CI high"], errors="coerce") < 0)
        dev_surv = dev[(pd.to_numeric(dev["FDR q"], errors="coerce") <= 0.10) & dev_ci].copy()
        hold_repl = 0
        directional = 0
        for _, drow in dev_surv.iterrows():
            match = hold.copy()
            for k in keys:
                match = match[match[k].astype(str) == str(drow[k])]
            if match.empty:
                continue
            hrow = match.iloc[0]
            d_eff = _safe_float(drow.get("Event - baseline"))
            h_eff = _safe_float(hrow.get("Event - baseline"))
            if d_eff is None or h_eff is None or d_eff * h_eff <= 0:
                continue
            directional += 1
            hp = _safe_float(hrow.get("Bootstrap p"))
            if hp is not None and hp <= 0.10 and _ci_excludes_zero(hrow.get("Bootstrap CI low"), hrow.get("Bootstrap CI high")):
                hold_repl += 1
        if len(dev_surv) == 0:
            status = "NONE"
        elif hold_repl > 0:
            status = "STATISTICALLY REPLICATED"
        elif directional > 0:
            status = "DIRECTIONAL ONLY"
        else:
            status = "DEVELOPMENT ONLY"
        rows.append({
            "Alarm": alarm,
            "Development tests": int(len(dev)),
            "Development FDR+CI survivors": int(len(dev_surv)),
            "Holdout directional confirmations": int(directional),
            "Holdout statistical replications": int(hold_repl),
            "Predictive validation": status,
            "Operational role": "MONITORING / STATE ALERT" if status == "NONE" else "RESEARCH ALERT — NOT A TRADING SIGNAL",
        })
    return pd.DataFrame(rows).sort_values("Alarm").reset_index(drop=True) if rows else pd.DataFrame()

def _memory_thresholds(raw_candidates: pd.DataFrame) -> tuple[float, float]:
    calibration_pool = raw_candidates[pd.to_numeric(raw_candidates["Coverage"], errors="coerce") >= 45.0].copy()
    sim_q = float(pd.to_numeric(calibration_pool["Similarity"], errors="coerce").quantile(MEMORY_SIMILARITY_QUANTILE)) if len(calibration_pool) >= 20 else MEMORY_SIMILARITY_THRESHOLD
    sim_threshold = float(min(max(MEMORY_SIMILARITY_THRESHOLD, sim_q), max(85.0, MEMORY_SIMILARITY_THRESHOLD)))
    structural_pool = calibration_pool[pd.to_numeric(calibration_pool["Similarity"], errors="coerce") >= sim_threshold]
    act_source = structural_pool if len(structural_pool) >= 5 else calibration_pool
    act_q = float(pd.to_numeric(act_source["Activation"], errors="coerce").quantile(MEMORY_ACTIVATION_QUANTILE)) if len(act_source) >= 5 else MEMORY_ACTIVATION_THRESHOLD
    act_threshold = float(min(max(MEMORY_ACTIVATION_THRESHOLD, act_q), max(78.0, MEMORY_ACTIVATION_THRESHOLD)))
    return sim_threshold, act_threshold


def _prepare_memory_arrays(combined: pd.DataFrame) -> dict[str, Any]:
    arrays: dict[str, Any] = {"domains": {}}
    for spec in DOMAIN_SPECS:
        cols = [c for c in spec.columns if c in combined.columns]
        if not cols:
            continue
        arrays["domains"][spec.name] = {
            "spec": spec,
            "cols": cols,
            "values": combined[cols].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float),
        }
    salience_cols = [
        "beh_attention", "beh_fear", "beh_extrapolation", "beh_herding", "beh_reflexivity",
        "mkt_ret20", "mkt_vol20", "mkt_drawdown", "vol_vix", "vol_vvix",
    ]
    present = [c for c in salience_cols if c in combined.columns]
    if present:
        vals = combined[present].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
        dev = np.abs(vals - 50.0)
        with np.errstate(invalid="ignore"):
            sal = 2.2 * np.nanmean(dev, axis=1)
        arrays["salience"] = np.clip(np.where(np.isfinite(sal), sal, 0.0), 0.0, 100.0)
    else:
        arrays["salience"] = np.zeros(len(combined), dtype=float)
    arrays["dates"] = pd.DatetimeIndex(combined.index)
    return arrays


def _select_spaced_fast(frame: pd.DataFrame, top_n: int, spacing_days: int) -> pd.DataFrame:
    if frame.empty:
        return frame
    rank = {"MEMORY CANDIDATE": 4, "STRUCTURAL ANALOGUE": 3, "PARTIAL": 2, "WEAK": 1}
    work = frame.copy()
    work["_rank"] = work["Retrieval class"].map(rank).fillna(0)
    work = work.sort_values(["_rank", "Similarity", "Activation"], ascending=False)
    chosen = []
    chosen_dates: list[pd.Timestamp] = []
    for idx, row in work.iterrows():
        dt = pd.Timestamp(row["date"])
        if all(abs((dt - prev).days) >= spacing_days for prev in chosen_dates):
            chosen.append(idx)
            chosen_dates.append(dt)
        if len(chosen) >= top_n:
            break
    return work.loc[chosen].drop(columns="_rank", errors="ignore").reset_index(drop=True)


def _memory_candidate_table_at(
    combined: pd.DataFrame,
    arrays: dict[str, Any],
    current_pos: int,
    *,
    horizon: int,
    top_n: int = 8,
) -> tuple[pd.DataFrame, dict[str, float]]:
    dates: pd.DatetimeIndex = arrays["dates"]
    current_date = dates[current_pos]
    domain_defs = arrays.get("domains", {})

    domain_available: dict[str, bool] = {}
    total_weight = 0.0
    for spec in DOMAIN_SPECS:
        d = domain_defs.get(spec.name)
        if d is None:
            domain_available[spec.name] = False
            continue
        cur = d["values"][current_pos]
        available = int(np.isfinite(cur).sum()) >= spec.min_features
        domain_available[spec.name] = available
        if available:
            total_weight += DOMAIN_WEIGHTS[spec.name] * DOMAIN_TEMPORAL_INTEGRITY[spec.name]
    if total_weight <= 0:
        return pd.DataFrame(), {}

    candidate_end = current_pos - max(int(horizon), 60)
    if candidate_end <= 120:
        return pd.DataFrame(), {}

    weighted = np.zeros(candidate_end, dtype=float)
    avail_weight = np.zeros(candidate_end, dtype=float)
    domain_sims: dict[str, np.ndarray] = {}
    for spec in DOMAIN_SPECS:
        if not domain_available.get(spec.name):
            continue
        d = domain_defs.get(spec.name)
        if d is None:
            continue
        arr = d["values"]
        cur = arr[current_pos]
        cand = arr[:candidate_end]
        # Columns absent from combined were already removed. Require at least the
        # domain-specific minimum number of overlapping finite features per row.
        valid = np.isfinite(cand) & np.isfinite(cur[None, :])
        count = valid.sum(axis=1)
        diff = np.where(valid, cand - cur[None, :], 0.0)
        mse = np.divide((diff * diff).sum(axis=1), count, out=np.full(candidate_end, np.nan), where=count > 0)
        sim = 100.0 * np.exp(-np.sqrt(mse) / 40.0)
        ok = count >= spec.min_features
        sim = np.where(ok & np.isfinite(sim), sim, np.nan)
        w = DOMAIN_WEIGHTS[spec.name] * DOMAIN_TEMPORAL_INTEGRITY[spec.name]
        weighted += np.where(np.isfinite(sim), w * sim, 0.0)
        avail_weight += np.where(np.isfinite(sim), w, 0.0)
        domain_sims[spec.name] = sim

    ok = avail_weight > 0
    if not ok.any():
        return pd.DataFrame(), {}
    similarity = np.divide(weighted, avail_weight, out=np.full(candidate_end, np.nan), where=avail_weight > 0)
    coverage = np.clip(avail_weight / total_weight, 0.0, 1.0)
    salience = np.asarray(arrays.get("salience", np.zeros(len(combined))))[:candidate_end]
    age_years = np.maximum((current_date - dates[:candidate_end]).days.to_numpy(dtype=float) / 365.25, 0.0)
    recency = 100.0 * np.exp(-age_years / 5.0)
    activation = np.clip((0.72 * similarity + 0.18 * salience + 0.10 * recency) * (0.75 + 0.25 * coverage), 0.0, 100.0)

    idx = np.where(ok & np.isfinite(similarity))[0]
    raw = pd.DataFrame({
        "_pos": idx,
        "date": dates[idx],
        "Similarity": similarity[idx],
        "Activation": activation[idx],
        "Coverage": 100.0 * coverage[idx],
        "Salience": salience[idx],
        "Recency": recency[idx],
    })
    for name, sim in domain_sims.items():
        raw[f"sim::{name}"] = sim[idx]
    if raw.empty:
        return pd.DataFrame(), {}

    sim_threshold, act_threshold = _memory_thresholds(raw)
    raw["Retrieval class"] = np.where(
        (raw["Similarity"] >= sim_threshold) & (raw["Coverage"] >= 100 * MEMORY_MIN_COVERAGE) & (raw["Activation"] >= act_threshold),
        "MEMORY CANDIDATE",
        np.where(
            (raw["Similarity"] >= sim_threshold) & (raw["Coverage"] >= 100 * MEMORY_MIN_COVERAGE),
            "STRUCTURAL ANALOGUE",
            np.where((raw["Similarity"] >= 55) & (raw["Coverage"] >= 50), "PARTIAL", "WEAK"),
        ),
    )
    selected = _select_spaced_fast(raw, max(top_n, 1), MEMORY_SPACING_DAYS)
    return selected, {"similarity_threshold": sim_threshold, "activation_threshold": act_threshold}


def _outcome_series(target: pd.DataFrame, horizon: int) -> pd.DataFrame:
    w = target.copy()
    w["date"] = pd.to_datetime(w["date"], errors="coerce", utc=True)
    w = w.dropna(subset=["date"]).drop_duplicates("date").set_index("date").sort_index()
    close = pd.to_numeric(w["close"], errors="coerce")
    return pd.DataFrame({
        "ret": _future_return(close, horizon),
        "vol": _future_realized_vol(close, horizon),
        "tail": _future_tail_loss(close, horizon),
    }, index=w.index)


def evaluate_memory_walk_forward(
    symbol: str,
    target: pd.DataFrame,
    latent_history: pd.DataFrame,
    behavioral_data: dict[str, Any],
    config: ValidationConfig,
    *,
    horizons: tuple[int, ...] = MEMORY_HORIZONS,
) -> dict[str, Any]:
    if target is None or target.empty or latent_history is None or latent_history.empty:
        return {"available": False, "reason": "Memory validation inputs unavailable."}
    archive = load_snapshot_archive(symbol)
    combined, _ = _domain_current_and_history(target, latent_history, behavioral_data, archive)
    if combined.empty:
        return {"available": False, "reason": "Memory validation feature panel unavailable."}
    target_idx = target.copy()
    target_idx["date"] = pd.to_datetime(target_idx["date"], errors="coerce", utc=True)
    target_idx = target_idx.dropna(subset=["date"]).drop_duplicates("date").set_index("date").sort_index()
    combined = combined.reindex(target_idx.index)
    n = len(combined)
    memory_arrays = _prepare_memory_arrays(combined)
    holdout_start = n - config.holdout_size
    dev_start = config.min_train
    if holdout_start <= dev_start + 60:
        return {"available": False, "reason": "Insufficient history for memory walk-forward after holdout reservation."}

    rows: list[dict[str, Any]] = []
    for horizon in horizons:
        outcomes = _outcome_series(target.reset_index(drop=True), horizon).reindex(combined.index)
        for pos in range(dev_start, n - horizon, max(1, config.memory_step)):
            partition = "HOLDOUT" if pos >= holdout_start else "WALK_FORWARD"
            selected, thresholds = _memory_candidate_table_at(combined, memory_arrays, pos, horizon=horizon, top_n=8)
            if selected.empty:
                continue
            candidates = selected[selected["Retrieval class"].eq("MEMORY CANDIDATE")].copy()
            if candidates.empty:
                candidates = selected[selected["Retrieval class"].eq("STRUCTURAL ANALOGUE")].copy()
            if len(candidates) < 3:
                continue
            c_out = outcomes.reindex(pd.to_datetime(candidates["date"], utc=True))
            # Candidate outcomes are guaranteed known by candidate_end logic above.
            pred_ret = _safe_float(c_out["ret"].median())
            pred_vol = _safe_float(c_out["vol"].median())
            pred_tail = _safe_float(c_out["tail"].median())
            dt = combined.index[pos]
            actual = outcomes.loc[dt] if dt in outcomes.index else pd.Series(dtype=float)
            if pred_ret is None or _safe_float(actual.get("ret")) is None:
                continue
            rows.append({
                "date": dt,
                "Partition": partition,
                "Horizon": f"{horizon}D",
                "Candidates": int(len(candidates)),
                "Mean similarity": float(pd.to_numeric(candidates["Similarity"], errors="coerce").mean()),
                "Mean activation": float(pd.to_numeric(candidates["Activation"], errors="coerce").mean()),
                "Similarity threshold": thresholds.get("similarity_threshold"),
                "Activation threshold": thresholds.get("activation_threshold"),
                "Pred return": pred_ret,
                "Actual return": _safe_float(actual.get("ret")),
                "Pred vol": pred_vol,
                "Actual vol": _safe_float(actual.get("vol")),
                "Pred tail": pred_tail,
                "Actual tail": _safe_float(actual.get("tail")),
            })
    detail = pd.DataFrame(rows)
    if detail.empty:
        return {"available": False, "reason": "No historical date had at least three admissible analogue outcomes."}

    summary_rows: list[dict[str, Any]] = []
    for partition, pg in detail.groupby("Partition"):
        for horizon_label, hg in pg.groupby("Horizon"):
            h_int = int(str(horizon_label).upper().replace("D", ""))
            r_rho, r_p = _spearman(hg["Pred return"], hg["Actual return"])
            v_rho, v_p = _spearman(hg["Pred vol"], hg["Actual vol"])
            t_rho, t_p = _spearman(hg["Pred tail"], hg["Actual tail"])
            sign_hit = float((np.sign(pd.to_numeric(hg["Pred return"], errors="coerce")) == np.sign(pd.to_numeric(hg["Actual return"], errors="coerce"))).mean())
            if partition == "WALK_FORWARD":
                possible = max(1, math.ceil(max(holdout_start - config.min_train - h_int, 0) / max(1, config.memory_step)))
            else:
                possible = max(1, math.ceil(max(n - holdout_start - h_int, 0) / max(1, config.memory_step)))
            summary_rows.append({
                "Partition": partition,
                "Horizon": horizon_label,
                "Evaluation dates": int(len(hg)),
                "Coverage": float(min(len(hg) / possible, 1.0)),
                "Return IC": r_rho,
                "Return p": r_p,
                "Return sign hit": sign_hit,
                "Vol IC": v_rho,
                "Vol p": v_p,
                "Tail IC": t_rho,
                "Tail p": t_p,
                "Median candidates": float(pd.to_numeric(hg["Candidates"], errors="coerce").median()),
                "Median similarity": float(pd.to_numeric(hg["Mean similarity"], errors="coerce").median()),
                "Median activation": float(pd.to_numeric(hg["Mean activation"], errors="coerce").median()),
            })
    summary = pd.DataFrame(summary_rows)
    if not summary.empty:
        dev = summary[summary["Partition"].eq("WALK_FORWARD")]
        qvals = _bh_qvalues(pd.concat([dev["Return p"], dev["Vol p"], dev["Tail p"]], ignore_index=True)) if not dev.empty else np.array([])
        # Keep the summary compact; full FDR family is exposed separately below.
        family_rows = []
        for _, row in dev.iterrows():
            for metric, pcol in (("Return", "Return p"), ("Vol", "Vol p"), ("Tail", "Tail p")):
                family_rows.append({"Horizon": row["Horizon"], "Metric": metric, "p": row[pcol]})
        family = pd.DataFrame(family_rows)
        if not family.empty:
            family["q"] = _bh_qvalues(family["p"])
        else:
            family = pd.DataFrame()
    else:
        family = pd.DataFrame()

    memory_evidence = classify_memory_predictive_status(summary, family)
    return {
        "available": True,
        "summary": summary,
        "detail": detail,
        "fdr_family": family,
        "evidence": memory_evidence,
        "archive_snapshots": int(len(archive)),
        "temporal_note": "Market/breadth/behavior are point-in-time market-observed; CFTC uses publication-lag alignment; FRED remains current-vintage unless ALFRED is connected; narrative/options are archive-only.",
    }



def classify_memory_predictive_status(summary: pd.DataFrame, family: pd.DataFrame) -> dict[str, Any]:
    """Evidence classification for Behavioral Memory; role remains contextual."""
    result = {
        "role": "CONTEXTUAL / DESCRIPTIVE",
        "predictive_status": "NO PREDICTIVE EVIDENCE",
        "development_fdr_survivors": 0,
        "holdout_directional_confirmations": 0,
        "holdout_statistical_replications": 0,
    }
    if summary is None or summary.empty or family is None or family.empty:
        return result
    dev_family = family.copy()
    dev_family["q"] = pd.to_numeric(dev_family.get("q"), errors="coerce")
    survivors = dev_family[dev_family["q"] <= 0.10]
    result["development_fdr_survivors"] = int(len(survivors))
    if survivors.empty:
        return result
    wf = summary[summary["Partition"].eq("WALK_FORWARD")].copy()
    ho = summary[summary["Partition"].eq("HOLDOUT")].copy()
    metric_cols = {"Return": ("Return IC", "Return p"), "Vol": ("Vol IC", "Vol p"), "Tail": ("Tail IC", "Tail p")}
    directional = 0
    statistical = 0
    failed_sig = 0
    for _, r in survivors.iterrows():
        horizon = str(r.get("Horizon"))
        metric = str(r.get("Metric"))
        cols = metric_cols.get(metric)
        if not cols:
            continue
        dev_row = wf[wf["Horizon"].astype(str) == horizon]
        hold_row = ho[ho["Horizon"].astype(str) == horizon]
        if dev_row.empty or hold_row.empty:
            continue
        dic = _safe_float(dev_row.iloc[0].get(cols[0]))
        hic = _safe_float(hold_row.iloc[0].get(cols[0]))
        hp = _safe_float(hold_row.iloc[0].get(cols[1]))
        if dic is None or hic is None or abs(dic) < 1e-12 or abs(hic) < 1e-12:
            continue
        if dic * hic > 0:
            directional += 1
            if hp is not None and hp <= 0.10:
                statistical += 1
        elif hp is not None and hp <= 0.10:
            failed_sig += 1
    result["holdout_directional_confirmations"] = int(directional)
    result["holdout_statistical_replications"] = int(statistical)
    if statistical > 0:
        status = "STATISTICALLY REPLICATED"
    elif len(survivors) > 0:
        # Behavioral Memory is intentionally held to a stricter promotion rule than
        # single mechanism rows: same-sign holdout effects are reported separately
        # but do not upgrade its predictive status without statistical replication.
        status = "NOT REPLICATED"
    else:
        status = "NO PREDICTIVE EVIDENCE"
    result["predictive_status"] = status
    return result

def _file_hash(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    except Exception:
        return None


def build_validation_manifest(symbol: str, history: pd.DataFrame, config: ValidationConfig) -> dict[str, Any]:
    package_dir = Path(__file__).resolve().parent
    hashes = {}
    for name in ("walk_forward.py", "latent_state.py", "behavioral_memory.py", "engine.py", "validation.py"):
        h = _file_hash(package_dir / name)
        if h:
            hashes[name] = h
    dates = pd.to_datetime(history.get("date", pd.Series(dtype="datetime64[ns]")), errors="coerce", utc=True).dropna()
    return {
        "validation_version": VALIDATION_VERSION,
        "symbol": str(symbol).upper(),
        "profile": config.profile,
        "history_start": dates.min().isoformat() if not dates.empty else None,
        "history_end": dates.max().isoformat() if not dates.empty else None,
        "rows": int(len(history)),
        "min_train_rows": int(config.min_train),
        "test_block_rows": int(config.test_size),
        "holdout_rows": int(config.holdout_size),
        "bootstrap_samples": int(config.bootstrap_samples),
        "memory_evaluation_step": int(config.memory_step),
        "horizons": list(DEFAULT_HORIZONS),
        "mechanisms": list(CORE_MECHANISMS),
        "evidence_classification": {
            "holdout_p_threshold": 0.10,
            "holdout_ic_floor": 0.03,
            "statistical_replication_requires_ci_excluding_zero": True,
            "mechanism_matrix_min_validation_coverage": 0.50,
            "memory_predictive_promotion_requires_statistical_holdout_replication": True,
        },
        "code_hashes": hashes,
        "point_in_time_limitations": [
            "FRED funding history is current-vintage unless ALFRED is connected.",
            "Narrative/options history is used only when prospectively archived.",
            "Herding validation automatically excludes long constant proxy plateaus caused by truncated benchmark history.",
        ],
    }


def build_walk_forward_validation_bundle(
    state: dict[str, Any],
    *,
    profile: str = "STANDARD",
) -> dict[str, Any]:
    history = state.get("history", pd.DataFrame()) if isinstance(state, dict) else pd.DataFrame()
    target = state.get("target_history", pd.DataFrame()) if isinstance(state, dict) else pd.DataFrame()
    if history is None or history.empty:
        return {"available": False, "reason": "Latent-state history unavailable."}
    config = choose_validation_config(len(history), profile)
    if config is None:
        return {"available": False, "reason": "At least ~450 daily observations are required for V2.4.1 walk-forward validation."}
    mechanisms = evaluate_mechanisms_walk_forward(history, config)
    if not mechanisms.get("available"):
        return {"available": False, "reason": mechanisms.get("reason", "Mechanism walk-forward unavailable.")}
    alarm_study = evaluate_alarm_event_study(mechanisms["work"], config)
    alarm_evidence = classify_alarm_predictive_evidence(alarm_study)
    memory = evaluate_memory_walk_forward(
        str(state.get("symbol", "SPY")),
        target if isinstance(target, pd.DataFrame) and not target.empty else history[[c for c in history.columns if c in {"date", "close"}]].copy(),
        history,
        state.get("behavioral_data", {}) if isinstance(state.get("behavioral_data", {}), dict) else {},
        config,
    )
    manifest = build_validation_manifest(str(state.get("symbol", "SPY")), history, config)
    return {
        "available": True,
        "version": VALIDATION_VERSION,
        "config": config,
        "mechanisms": mechanisms,
        "alarms": alarm_study,
        "alarm_evidence": alarm_evidence,
        "memory": memory,
        "manifest": manifest,
        "status": "RESEARCH ONLY — no production promotion",
    }


def bundle_to_jsonable(bundle: dict[str, Any]) -> dict[str, Any]:
    """Compact serializable summary for audit/download; excludes large record-level frames."""
    if not isinstance(bundle, dict):
        return {}
    mech = bundle.get("mechanisms", {}) if isinstance(bundle.get("mechanisms", {}), dict) else {}
    mem = bundle.get("memory", {}) if isinstance(bundle.get("memory", {}), dict) else {}
    out = {
        "version": bundle.get("version"),
        "status": bundle.get("status"),
        "manifest": bundle.get("manifest", {}),
        "mechanism_summary": mech.get("development", pd.DataFrame()).to_dict("records") if isinstance(mech.get("development"), pd.DataFrame) else [],
        "holdout_summary": mech.get("holdout", pd.DataFrame()).to_dict("records") if isinstance(mech.get("holdout"), pd.DataFrame) else [],
        "replication_summary": mech.get("confirmation", pd.DataFrame()).to_dict("records") if isinstance(mech.get("confirmation"), pd.DataFrame) else [],
        "evidence_matrix": mech.get("evidence_matrix", pd.DataFrame()).to_dict("records") if isinstance(mech.get("evidence_matrix"), pd.DataFrame) else [],
        "evidence_details": mech.get("evidence_details", pd.DataFrame()).to_dict("records") if isinstance(mech.get("evidence_details"), pd.DataFrame) else [],
        "alarm_study": bundle.get("alarms", pd.DataFrame()).to_dict("records") if isinstance(bundle.get("alarms"), pd.DataFrame) else [],
        "alarm_evidence": bundle.get("alarm_evidence", pd.DataFrame()).to_dict("records") if isinstance(bundle.get("alarm_evidence"), pd.DataFrame) else [],
        "memory_summary": mem.get("summary", pd.DataFrame()).to_dict("records") if isinstance(mem.get("summary"), pd.DataFrame) else [],
        "memory_evidence": mem.get("evidence", {}),
        "memory_temporal_note": mem.get("temporal_note"),
    }
    return out


def bundle_json_bytes(bundle: dict[str, Any]) -> bytes:
    def default(o: Any):
        if isinstance(o, (pd.Timestamp, np.datetime64)):
            return pd.Timestamp(o).isoformat()
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, (np.floating,)):
            return None if not np.isfinite(o) else float(o)
        if isinstance(o, np.bool_):
            return bool(o)
        return str(o)
    return json.dumps(bundle_to_jsonable(bundle), indent=2, sort_keys=True, default=default).encode("utf-8")


__all__ = [
    "VALIDATION_VERSION",
    "ValidationConfig",
    "choose_validation_config",
    "build_walk_forward_folds",
    "build_validation_targets",
    "evaluate_mechanisms_walk_forward",
    "evaluate_alarm_event_study",
    "classify_alarm_predictive_evidence",
    "classify_memory_predictive_status",
    "evaluate_memory_walk_forward",
    "build_walk_forward_validation_bundle",
    "build_validation_manifest",
    "bundle_json_bytes",
]
