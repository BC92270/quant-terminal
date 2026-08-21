from __future__ import annotations

from dataclasses import dataclass
from typing import Callable
import warnings

import numpy as np
import pandas as pd
from sklearn.covariance import GraphicalLassoCV, LedoitWolf, OAS
from sklearn.exceptions import ConvergenceWarning

from .utils import nearest_psd, safe_float

try:  # Optional adapter only; V3.1 does not require this package.
    import nonlinshrink as _nls  # type: ignore
except Exception:  # pragma: no cover
    _nls = None


@dataclass(frozen=True)
class CovarianceForecast:
    model: str
    covariance: pd.DataFrame
    metadata: dict


def _complete(changes: pd.DataFrame, days: int | None, min_obs: int = 40) -> pd.DataFrame:
    if changes is None or changes.empty:
        return pd.DataFrame()
    x = changes.tail(int(days)) if days else changes.copy()
    x = x.apply(pd.to_numeric, errors="coerce")
    x = x.dropna(axis=1, thresh=min_obs).dropna(how="any")
    return x


def _psd_cov(cov: np.ndarray, cols: list[str]) -> pd.DataFrame:
    c = np.asarray(cov, dtype=float)
    c = 0.5 * (c + c.T)
    vals, vecs = np.linalg.eigh(c)
    floor = max(1e-12, float(np.nanmedian(np.diag(c))) * 1e-8 if c.size else 1e-12)
    vals = np.maximum(vals, floor)
    c = (vecs * vals) @ vecs.T
    return pd.DataFrame(c, index=cols, columns=cols)


def covariance_to_correlation(cov: pd.DataFrame) -> pd.DataFrame:
    if cov is None or cov.empty:
        return pd.DataFrame()
    d = np.sqrt(np.clip(np.diag(cov.to_numpy(dtype=float)), 1e-18, None))
    corr = cov.to_numpy(dtype=float) / np.outer(d, d)
    np.fill_diagonal(corr, 1.0)
    return nearest_psd(pd.DataFrame(corr, index=cov.index, columns=cov.columns))


def ewma_covariance(x: pd.DataFrame, lam: float = 0.94) -> pd.DataFrame:
    if x is None or x.empty:
        return pd.DataFrame()
    arr = x.to_numpy(dtype=float)
    arr = arr - np.nanmean(arr, axis=0, keepdims=True)
    n = len(arr)
    w = (1.0 - lam) * lam ** np.arange(n - 1, -1, -1)
    w = w / max(w.sum(), 1e-18)
    cov = (arr * w[:, None]).T @ arr
    return _psd_cov(cov, list(x.columns))


def _poet_factor_count(x: pd.DataFrame, max_factors: int = 6) -> int:
    z = (x - x.mean()) / x.std(ddof=1).replace(0, np.nan)
    z = z.dropna(how="any")
    if len(z) < 10 or z.shape[1] < 2:
        return 1
    eig = np.linalg.eigvalsh(z.cov().to_numpy(dtype=float))[::-1]
    q = z.shape[1] / max(len(z), 1)
    mp_max = (1.0 + np.sqrt(q)) ** 2
    k = int(np.sum(eig > mp_max))
    return max(1, min(max_factors, max(1, k), z.shape[1] - 1))


def poet_covariance(x: pd.DataFrame, n_factors: int | None = None, threshold_scale: float = 0.75) -> tuple[pd.DataFrame, dict]:
    """Practical POET-style factor covariance.

    A low-rank PCA factor component is combined with an adaptively thresholded residual covariance.
    This follows the POET architecture but is deliberately labelled POET-style rather than a byte-for-byte
    replication of any author's reference implementation.
    """
    if x is None or x.empty or x.shape[1] < 2:
        return pd.DataFrame(), {"status": "unavailable"}
    arr = x.to_numpy(dtype=float)
    arr = arr - arr.mean(axis=0, keepdims=True)
    sample = np.cov(arr, rowvar=False, ddof=1)
    vals, vecs = np.linalg.eigh(sample)
    order = np.argsort(vals)[::-1]
    vals, vecs = vals[order], vecs[:, order]
    k = int(n_factors or _poet_factor_count(x))
    k = max(1, min(k, x.shape[1] - 1))
    low = (vecs[:, :k] * np.maximum(vals[:k], 0.0)) @ vecs[:, :k].T
    resid = sample - low
    n, p = x.shape
    scale = np.sqrt(np.outer(np.clip(np.diag(resid), 1e-18, None), np.clip(np.diag(resid), 1e-18, None)))
    tau = float(threshold_scale) * np.sqrt(np.log(max(p, 2)) / max(n, 2)) * scale
    shrunk = resid.copy()
    off = ~np.eye(p, dtype=bool)
    shrunk[off] = np.sign(resid[off]) * np.maximum(np.abs(resid[off]) - tau[off], 0.0)
    np.fill_diagonal(shrunk, np.clip(np.diag(resid), 1e-12, None))
    cov = low + shrunk
    out = _psd_cov(cov, list(x.columns))
    sparsity = float(np.mean(np.isclose(shrunk[off], 0.0))) if off.sum() else 0.0
    return out, {"status": "ok", "factors": k, "residual_sparsity": sparsity, "method": "POET-style PCA + residual threshold"}


def factor_graphical_covariance(x: pd.DataFrame, n_factors: int | None = None) -> tuple[pd.DataFrame, dict]:
    """Low-rank factor component + sparse residual precision covariance."""
    if x is None or x.empty or x.shape[1] < 2:
        return pd.DataFrame(), {"status": "unavailable"}
    arr = x.to_numpy(dtype=float)
    mu = arr.mean(axis=0, keepdims=True)
    xc = arr - mu
    sample = np.cov(xc, rowvar=False, ddof=1)
    vals, vecs = np.linalg.eigh(sample)
    order = np.argsort(vals)[::-1]
    vals, vecs = vals[order], vecs[:, order]
    k = int(n_factors or _poet_factor_count(x))
    k = max(1, min(k, x.shape[1] - 1))
    load = vecs[:, :k]
    scores = xc @ load
    common = scores @ load.T
    residual = xc - common
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ConvergenceWarning)
            gl = GraphicalLassoCV(cv=min(5, max(2, len(x) // 40)), max_iter=200).fit(residual)
        resid_cov = gl.covariance_
        alpha = safe_float(gl.alpha_)
    except Exception:
        resid_cov = np.cov(residual, rowvar=False, ddof=1)
        alpha = None
    factor_cov = load @ np.cov(scores, rowvar=False, ddof=1) @ load.T if k > 1 else np.outer(load[:, 0], load[:, 0]) * float(np.var(scores[:, 0], ddof=1))
    out = _psd_cov(factor_cov + resid_cov, list(x.columns))
    return out, {"status": "ok", "factors": k, "graphical_alpha": alpha, "method": "Factor + Graphical Lasso residual"}


def rmt_spectral_covariance(x: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """RMT constant-residual-eigenvalue cleaning while preserving marginal volatility."""
    if x is None or x.empty or x.shape[1] < 2:
        return pd.DataFrame(), {"status": "unavailable"}
    sample_cov = x.cov()
    sd = np.sqrt(np.clip(np.diag(sample_cov), 1e-18, None))
    corr = sample_cov.to_numpy(dtype=float) / np.outer(sd, sd)
    vals, vecs = np.linalg.eigh(corr)
    n, p = x.shape
    q = p / max(n, 1)
    mp_max = (1 + np.sqrt(q)) ** 2
    informative = vals > mp_max
    cleaned = vals.copy()
    if (~informative).any():
        cleaned[~informative] = float(np.mean(vals[~informative]))
    cc = (vecs * cleaned) @ vecs.T
    d = np.sqrt(np.clip(np.diag(cc), 1e-18, None))
    cc = cc / np.outer(d, d)
    np.fill_diagonal(cc, 1.0)
    cov = cc * np.outer(sd, sd)
    return _psd_cov(cov, list(x.columns)), {"status": "ok", "informative_eigenvalues": int(informative.sum()), "mp_max": float(mp_max), "method": "RMT spectral cleaning"}


def covariance_estimate(
    changes: pd.DataFrame,
    model: str,
    days: int = 252,
    min_obs: int = 60,
    ewma_lambda: float = 0.94,
    external_nls: Callable | None = None,
) -> CovarianceForecast:
    x = _complete(changes, days, min_obs)
    if x.empty or x.shape[1] < 2:
        return CovarianceForecast(model, pd.DataFrame(), {"status": "insufficient_data", "obs": int(len(x)), "assets": int(x.shape[1])})
    name = str(model)
    key = name.lower()
    meta = {"status": "ok", "obs": int(len(x)), "assets": int(x.shape[1])}
    if key in {"sample", "sample covariance"}:
        cov = _psd_cov(x.cov().to_numpy(dtype=float), list(x.columns))
    elif key in {"ledoit-wolf", "ledoit wolf", "lw"}:
        fit = LedoitWolf().fit(x.to_numpy(dtype=float))
        cov = _psd_cov(fit.covariance_, list(x.columns)); meta["shrinkage"] = safe_float(fit.shrinkage_)
    elif key == "oas":
        fit = OAS().fit(x.to_numpy(dtype=float))
        cov = _psd_cov(fit.covariance_, list(x.columns)); meta["shrinkage"] = safe_float(fit.shrinkage_)
    elif key == "ewma":
        cov = ewma_covariance(x, ewma_lambda); meta["lambda"] = float(ewma_lambda)
    elif key in {"poet", "poet-style"}:
        cov, extra = poet_covariance(x); meta.update(extra)
    elif key in {"factor-glasso", "factor graphical lasso"}:
        cov, extra = factor_graphical_covariance(x); meta.update(extra)
    elif key in {"rmt", "rmt spectral"}:
        cov, extra = rmt_spectral_covariance(x); meta.update(extra)
    elif key in {"nonlinear shrinkage", "nls"}:
        fn = external_nls
        if fn is None and _nls is not None:
            fn = _nls.shrink_cov
        if fn is None:
            return CovarianceForecast(name, pd.DataFrame(), {**meta, "status": "optional_dependency_unavailable", "reason": "Inject analysis['correlation_nonlinear_shrinkage_callable'] or install nonlinshrink."})
        try:
            raw = np.asarray(fn(x.to_numpy(dtype=float)), dtype=float)
            cov = _psd_cov(raw, list(x.columns)); meta["method"] = "Analytical nonlinear shrinkage adapter"
        except Exception as exc:
            return CovarianceForecast(name, pd.DataFrame(), {**meta, "status": "fit_failed", "error": type(exc).__name__})
    else:
        return CovarianceForecast(name, pd.DataFrame(), {**meta, "status": "unknown_model"})
    meta["condition_number"] = float(np.linalg.cond(cov.to_numpy(dtype=float)))
    return CovarianceForecast(name, cov, meta)


def _gmv_weights(cov: np.ndarray) -> np.ndarray:
    inv = np.linalg.pinv(cov)
    one = np.ones(len(cov))
    w = inv @ one
    den = float(one @ w)
    return w / den if abs(den) > 1e-18 else np.repeat(1 / len(cov), len(cov))


def _qlike(forecast: np.ndarray, realized: np.ndarray) -> float:
    f = 0.5 * (forecast + forecast.T)
    sign, logdet = np.linalg.slogdet(f)
    if sign <= 0:
        return np.inf
    inv = np.linalg.pinv(f)
    return float((logdet + np.trace(inv @ realized)) / len(f))


def _paired_champion_inference(
    fold_records: pd.DataFrame,
    champion: str,
    runner_up: str | None,
    bootstrap_samples: int = 2000,
    seed: int = 42,
) -> dict:
    """Paired bootstrap uncertainty for the top two covariance models.

    A per-fold composite loss is built from cross-model percentile ranks of QLIKE,
    relative Frobenius error, realized GMV volatility and turnover. Lower is better.
    The paired bootstrap resamples common forecast folds and therefore measures whether
    the selected champion's OOS edge over the runner-up is persistent rather than a
    consequence of one or two favorable folds.
    """
    if fold_records is None or fold_records.empty or not runner_up:
        return {"champion_status": "Single model", "runner_up": runner_up}

    metrics = ["QLIKE", "Relative Frobenius", "OOS GMV ann. vol", "GMV turnover"]
    fr = fold_records.copy()
    fr["Fold composite loss"] = np.nan
    fold_losses = []
    for fold, g in fr.groupby("Fold", sort=True):
        g = g.copy()
        pieces = []
        for metric in metrics:
            vals = pd.to_numeric(g[metric], errors="coerce")
            if vals.notna().sum() >= 2:
                pieces.append(vals.rank(pct=True, ascending=True).to_numpy(dtype=float))
        if not pieces:
            continue
        comp = np.nanmean(np.vstack(pieces), axis=0)
        for idx, loss in zip(g.index, comp):
            fold_losses.append({"Fold": fold, "Model": str(g.loc[idx, "Model"]), "Composite loss": float(loss)})
    fl = pd.DataFrame(fold_losses)
    if fl.empty:
        return {"champion_status": "Insufficient fold inference", "runner_up": runner_up}

    a = fl[fl["Model"] == champion][["Fold", "Composite loss"]].rename(columns={"Composite loss": "champion_loss"})
    b = fl[fl["Model"] == runner_up][["Fold", "Composite loss"]].rename(columns={"Composite loss": "runner_loss"})
    paired = a.merge(b, on="Fold", how="inner").dropna()
    if len(paired) < 6:
        return {
            "champion_status": "Insufficient fold inference",
            "runner_up": runner_up,
            "paired_folds": int(len(paired)),
        }

    # Positive difference means the champion has lower loss and is therefore better.
    diff = (paired["runner_loss"] - paired["champion_loss"]).to_numpy(dtype=float)
    observed = float(np.mean(diff))
    rng = np.random.default_rng(seed)
    bcount = max(500, int(bootstrap_samples))
    idx = rng.integers(0, len(diff), size=(bcount, len(diff)))
    boot = diff[idx].mean(axis=1)
    prob = float(np.mean(boot > 0.0))
    ci_low, ci_high = [float(v) for v in np.quantile(boot, [0.025, 0.975])]

    if ci_low > 0.0 and prob >= 0.95:
        status = "Supported edge"
    elif observed > 0.0 and prob >= 0.80:
        status = "Weak edge"
    else:
        status = "Statistically tied"

    return {
        "champion_status": status,
        "runner_up": runner_up,
        "paired_folds": int(len(diff)),
        "champion_probability": prob,
        "composite_loss_edge": observed,
        "composite_loss_edge_ci_low": ci_low,
        "composite_loss_edge_ci_high": ci_high,
        "champion_bootstrap_samples": int(bcount),
    }


def covariance_model_validation(
    changes: pd.DataFrame,
    models: tuple[str, ...],
    train_days: int = 252,
    forecast_horizon: int = 5,
    min_train: int = 126,
    max_folds: int = 24,
    ewma_lambda: float = 0.94,
    external_nls: Callable | None = None,
    champion_bootstrap_samples: int = 2000,
    seed: int = 42,
) -> tuple[pd.DataFrame, dict]:
    """Walk-forward champion/challenger covariance validation with selection uncertainty.

    Evaluation uses non-overlapping forecast blocks. Realized covariance is the covariance
    of the next H returns. QLIKE is the multivariate Gaussian covariance loss; economic
    diagnostics use GMV realized volatility and turnover. The aggregate champion is then
    challenged against the runner-up with a paired bootstrap over common OOS folds.
    """
    if changes is None or changes.empty:
        return pd.DataFrame(), {"status": "unavailable"}
    x = changes.apply(pd.to_numeric, errors="coerce").dropna(axis=1, thresh=min_train).dropna(how="any")
    p = x.shape[1]
    if len(x) < min_train + max(5, forecast_horizon) or p < 2:
        return pd.DataFrame(), {"status": "insufficient_data", "obs": int(len(x)), "assets": int(p)}

    h = max(1, int(forecast_horizon))
    starts = list(range(max(min_train, train_days), len(x) - h + 1, h))
    if len(starts) > max_folds:
        starts = starts[-max_folds:]

    rows = []
    fold_records: list[dict] = []
    for model in models:
        qlikes: list[float] = []
        frobs: list[float] = []
        vols: list[float] = []
        turns: list[float] = []
        prev_w = None
        skipped = 0
        for fold_no, end in enumerate(starts):
            train = x.iloc[max(0, end - train_days):end]
            test = x.iloc[end:end + h]
            if len(train) < min_train or len(test) < max(2, min(h, 3)):
                skipped += 1
                continue
            fit = covariance_estimate(
                train, model, days=len(train), min_obs=min_train,
                ewma_lambda=ewma_lambda, external_nls=external_nls,
            )
            if fit.covariance.empty:
                skipped += 1
                continue
            f = fit.covariance.to_numpy(dtype=float)
            r = np.cov(test.to_numpy(dtype=float), rowvar=False, ddof=1)
            if r.ndim != 2 or r.shape != f.shape:
                skipped += 1
                continue
            r = _psd_cov(r, list(x.columns)).to_numpy(dtype=float)
            qv = _qlike(f, r)
            fv = float(np.linalg.norm(f - r, ord="fro") / max(np.linalg.norm(r, ord="fro"), 1e-18))
            if not (np.isfinite(qv) and np.isfinite(fv)):
                skipped += 1
                continue

            w = _gmv_weights(f)
            vol = float(np.sqrt(max(w @ r @ w, 0.0))) * np.sqrt(252)
            turn = float(0.5 * np.abs(w - prev_w).sum()) if prev_w is not None else np.nan
            prev_w = w

            qlikes.append(qv)
            frobs.append(fv)
            vols.append(vol)
            if np.isfinite(turn):
                turns.append(turn)
            fold_records.append({
                "Fold": int(fold_no),
                "Forecast start": str(x.index[end]),
                "Model": str(model),
                "QLIKE": float(qv),
                "Relative Frobenius": float(fv),
                "OOS GMV ann. vol": float(vol),
                "GMV turnover": None if not np.isfinite(turn) else float(turn),
            })

        if qlikes:
            rows.append({
                "Model": model,
                "Folds": len(qlikes),
                "QLIKE": float(np.mean(qlikes)),
                "Relative Frobenius": float(np.mean(frobs)),
                "OOS GMV ann. vol": float(np.mean(vols)),
                "GMV turnover": float(np.mean(turns)) if turns else None,
                "Skipped": skipped,
            })

    if not rows:
        return pd.DataFrame(), {"status": "no_valid_models", "assets": p, "obs": int(len(x))}

    out = pd.DataFrame(rows)
    rank_cols = [c for c in ["QLIKE", "Relative Frobenius", "OOS GMV ann. vol", "GMV turnover"] if c in out]
    score = np.zeros(len(out), dtype=float)
    denom = 0
    for c in rank_cols:
        vals = pd.to_numeric(out[c], errors="coerce")
        if vals.notna().sum() >= 2:
            score += vals.rank(pct=True, ascending=True).fillna(1.0).to_numpy(dtype=float)
            denom += 1
    out["Validation score"] = 100 * (1 - score / max(denom, 1))
    out = out.sort_values(["Validation score", "QLIKE"], ascending=[False, True]).reset_index(drop=True)
    out["Rank"] = np.arange(1, len(out) + 1)

    champion = str(out.iloc[0]["Model"])
    runner_up = str(out.iloc[1]["Model"]) if len(out) > 1 else None
    fold_df = pd.DataFrame(fold_records)
    inference = _paired_champion_inference(
        fold_df, champion, runner_up,
        bootstrap_samples=champion_bootstrap_samples, seed=seed,
    )

    meta = {
        "status": "ok",
        "champion": champion,
        "forecast_horizon": h,
        "train_days": int(train_days),
        "folds": int(out["Folds"].max()),
        "assets": int(p),
        "obs": int(len(x)),
        "fold_losses": fold_df,
        **inference,
    }
    return out, meta
