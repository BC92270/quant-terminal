"""Pure, auditable analytics for the institutional Risk Monitor.

The module deliberately contains no Streamlit code.  Every calculation can be
unit-tested and every approximation is returned with an explicit method label.
Return-based risk measures use the loss-tail convention used by the legacy UI:
negative values represent losses.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import log, sqrt
from typing import Any, Mapping

import numpy as np
import pandas as pd
from scipy import stats

from .advanced import build_advanced_research_snapshot

try:
    from monte_carlo.tail_event import (
        assess_evt_threshold_stability,
        evt_threshold_stability,
        fit_evt_tail,
    )
except Exception:  # pragma: no cover - EVT is an optional diagnostic layer.
    assess_evt_threshold_stability = None
    evt_threshold_stability = None
    fit_evt_tail = None


EPS = 1e-12
TRADING_DAYS = 252


@dataclass(frozen=True)
class RiskParameters:
    """User-controlled assumptions; all rates are decimal fractions."""

    horizon_days: int = 10
    confidence: float = 0.975
    portfolio_nav: float = 1_000_000.0
    position_notional: float = 100_000.0
    side: str = "Long"
    loss_limit_pct: float = 0.01
    adv_participation: float = 0.10
    volatility_stress: float = 2.0
    custom_shock: float = -0.10
    ewma_lambda: float = 0.94
    seed: int = 42

    def normalized(self) -> "RiskParameters":
        return RiskParameters(
            horizon_days=max(1, min(int(self.horizon_days), 252)),
            confidence=float(np.clip(self.confidence, 0.90, 0.999)),
            portfolio_nav=max(float(self.portfolio_nav), 1.0),
            position_notional=max(float(self.position_notional), 0.0),
            side="Short" if str(self.side).lower().startswith("short") else "Long",
            loss_limit_pct=float(np.clip(self.loss_limit_pct, 0.0001, 1.0)),
            adv_participation=float(np.clip(self.adv_participation, 0.001, 1.0)),
            volatility_stress=float(np.clip(self.volatility_stress, 1.0, 10.0)),
            custom_shock=float(np.clip(self.custom_shock, -0.99, 5.0)),
            ewma_lambda=float(np.clip(self.ewma_lambda, 0.80, 0.995)),
            seed=int(self.seed),
        )


def _finite_series(values: pd.Series | np.ndarray | list[float]) -> pd.Series:
    series = pd.to_numeric(pd.Series(values, copy=False), errors="coerce")
    return series.replace([np.inf, -np.inf], np.nan).dropna().astype(float)


def prepare_market_frame(price_data: pd.DataFrame) -> pd.DataFrame:
    """Normalize an OHLCV frame without discarding source provenance."""

    if not isinstance(price_data, pd.DataFrame) or price_data.empty:
        return pd.DataFrame()
    attrs = dict(getattr(price_data, "attrs", {}) or {})
    frame = price_data.copy()
    frame.columns = [str(column).strip().lower() for column in frame.columns]
    if "date" not in frame:
        frame = frame.reset_index().rename(columns={"index": "date"})
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce", utc=True)
    for column in ("open", "high", "low", "close", "volume"):
        if column in frame:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = (
        frame.dropna(subset=["date", "close"])
        .loc[lambda item: item["close"] > 0]
        .sort_values("date")
        .drop_duplicates("date", keep="last")
        .reset_index(drop=True)
    )
    frame.attrs.update(attrs)
    return frame


def simple_returns(frame: pd.DataFrame) -> pd.Series:
    clean = prepare_market_frame(frame)
    if clean.empty:
        return pd.Series(dtype=float)
    result = clean["close"].pct_change(fill_method=None)
    result.index = clean["date"]
    return _finite_series(result)


def log_returns(frame: pd.DataFrame) -> pd.Series:
    clean = prepare_market_frame(frame)
    if clean.empty:
        return pd.Series(dtype=float)
    result = np.log(clean["close"] / clean["close"].shift(1))
    result.index = clean["date"]
    return _finite_series(result)


def _horizon_simple_returns(returns: pd.Series, horizon: int) -> pd.Series:
    clean = _finite_series(returns)
    horizon = max(int(horizon), 1)
    if horizon == 1:
        return clean
    if len(clean) < horizon:
        return pd.Series(dtype=float)
    return (1.0 + clean).rolling(horizon).apply(np.prod, raw=True).dropna() - 1.0


def _tail_pair(values: pd.Series | np.ndarray, confidence: float) -> tuple[float | None, float | None, int]:
    clean = np.asarray(_finite_series(values), dtype=float)
    if clean.size < 20:
        return None, None, 0
    alpha = 1.0 - float(confidence)
    var = float(np.quantile(clean, alpha))
    tail = clean[clean <= var]
    return var, float(np.mean(tail)) if tail.size else var, int(tail.size)


def ewma_volatility(returns: pd.Series, decay: float = 0.94) -> dict[str, Any]:
    clean = _finite_series(returns)
    if len(clean) < 20:
        return {"daily": None, "annualized": None, "series": pd.Series(dtype=float)}
    decay = float(np.clip(decay, 0.80, 0.995))
    centered = clean - float(clean.mean())
    unconditional = max(float(centered.var(ddof=1)), EPS)
    variance = np.empty(len(centered), dtype=float)
    variance[0] = unconditional
    values = centered.to_numpy(dtype=float)
    for index in range(1, len(values)):
        variance[index] = decay * variance[index - 1] + (1.0 - decay) * values[index - 1] ** 2
    volatility = pd.Series(np.sqrt(np.maximum(variance, EPS)), index=clean.index, name="ewma_vol")
    daily = float(volatility.iloc[-1])
    return {"daily": daily, "annualized": daily * sqrt(TRADING_DAYS), "series": volatility}


def build_tail_model_comparison(
    returns: pd.Series,
    *,
    horizon: int,
    confidence: float,
    decay: float = 0.94,
    seed: int = 42,
    simulations: int = 12_000,
) -> pd.DataFrame:
    """Compare empirical, Gaussian, Student-t and filtered historical tails."""

    clean = _finite_series(returns)
    if len(clean) < 30:
        return pd.DataFrame(columns=["Model", "VaR", "ES", "Tail observations", "Status", "Method"])
    horizon = max(int(horizon), 1)
    confidence = float(np.clip(confidence, 0.90, 0.999))
    alpha = 1.0 - confidence
    rows: list[dict[str, Any]] = []

    empirical = _horizon_simple_returns(clean, horizon)
    hist_var, hist_es, hist_tail = _tail_pair(empirical, confidence)
    rows.append(
        {
            "Model": "Historical simulation",
            "VaR": hist_var,
            "ES": hist_es,
            "Tail observations": hist_tail,
            "Status": "OK" if hist_tail >= 5 else "LIMITED",
            "Method": f"Overlapping observed {horizon}D returns",
        }
    )

    logs = np.log1p(np.clip(clean.to_numpy(dtype=float), -0.999999, None))
    mean_log = float(np.mean(logs))
    sigma_log = max(float(np.std(logs, ddof=1)), EPS)
    horizon_mean = mean_log * horizon
    horizon_sigma = sigma_log * sqrt(horizon)
    z = float(stats.norm.ppf(alpha))
    gaussian_var = float(np.expm1(horizon_mean + horizon_sigma * z))
    gaussian_es_log = horizon_mean - horizon_sigma * float(stats.norm.pdf(z)) / max(alpha, EPS)
    gaussian_es = float(np.expm1(gaussian_es_log))
    rows.append(
        {
            "Model": "Gaussian parametric",
            "VaR": gaussian_var,
            "ES": min(gaussian_es, gaussian_var),
            "Tail observations": int(round(alpha * len(clean))),
            "Status": "OK",
            "Method": "Normal log-return scaling",
        }
    )

    rng = np.random.default_rng(int(seed))
    simulation_count = max(2_000, min(int(simulations), 50_000))
    try:
        degrees, location, scale = stats.t.fit(logs)
        degrees = float(np.clip(degrees, 2.05, 100.0))
        scale = max(float(scale), EPS)
        draws = stats.t.rvs(
            degrees,
            loc=float(location),
            scale=scale,
            size=(simulation_count, horizon),
            random_state=rng,
        )
        student_terminal = np.expm1(draws.sum(axis=1))
        student_var, student_es, student_tail = _tail_pair(student_terminal, confidence)
        rows.append(
            {
                "Model": "Student-t simulation",
                "VaR": student_var,
                "ES": student_es,
                "Tail observations": student_tail,
                "Status": "OK" if degrees < 95 else "NEAR_GAUSSIAN",
                "Method": f"Fitted df={degrees:.1f}; {simulation_count:,} paths",
            }
        )
    except Exception as exc:
        rows.append(
            {
                "Model": "Student-t simulation",
                "VaR": None,
                "ES": None,
                "Tail observations": 0,
                "Status": "UNAVAILABLE",
                "Method": f"Fit failed: {exc}",
            }
        )

    ewma = ewma_volatility(clean, decay)
    ewma_series = ewma["series"]
    aligned = clean.reindex(ewma_series.index)
    residuals = ((aligned - float(aligned.mean())) / ewma_series.replace(0, np.nan)).replace(
        [np.inf, -np.inf], np.nan
    ).dropna()
    if len(residuals) >= 30 and ewma["daily"] is not None:
        sampled = rng.choice(
            residuals.to_numpy(dtype=float),
            size=(simulation_count, horizon),
            replace=True,
        )
        steps = float(aligned.mean()) + float(ewma["daily"]) * sampled
        fhs_terminal = np.prod(1.0 + np.clip(steps, -0.99, None), axis=1) - 1.0
        fhs_var, fhs_es, fhs_tail = _tail_pair(fhs_terminal, confidence)
        rows.append(
            {
                "Model": "Filtered historical (EWMA)",
                "VaR": fhs_var,
                "ES": fhs_es,
                "Tail observations": fhs_tail,
                "Status": "OK",
                "Method": f"Lambda={decay:.3f}; standardized residual bootstrap",
            }
        )

    table = pd.DataFrame(rows)
    table["VaR"] = pd.to_numeric(table["VaR"], errors="coerce")
    table["ES"] = pd.to_numeric(table["ES"], errors="coerce")
    return table


def drawdown_diagnostics(frame: pd.DataFrame) -> dict[str, Any]:
    clean = prepare_market_frame(frame)
    if clean.empty:
        return {}
    close = clean.set_index("date")["close"].astype(float)
    drawdown = close / close.cummax() - 1.0
    underwater = drawdown < -1e-12
    durations: list[int] = []
    current = 0
    for flag in underwater.to_numpy(dtype=bool):
        current = current + 1 if flag else 0
        durations.append(current)
    max_duration = int(max(durations, default=0))
    current_duration = int(durations[-1]) if durations else 0
    trough_date = drawdown.idxmin()
    peak_date = close.loc[:trough_date].idxmax()
    after_trough = drawdown.loc[trough_date:]
    recovered = after_trough[after_trough >= -1e-12]
    recovery_date = recovered.index[0] if not recovered.empty else None
    recovery_days = None
    if recovery_date is not None:
        recovery_days = int(clean.loc[(clean["date"] >= trough_date) & (clean["date"] <= recovery_date)].shape[0] - 1)
    return {
        "series": drawdown,
        "max_drawdown": float(drawdown.min()),
        "current_drawdown": float(drawdown.iloc[-1]),
        "ulcer_index": float(np.sqrt(np.mean(np.square(drawdown.to_numpy(dtype=float))))),
        "max_underwater_days": max_duration,
        "current_underwater_days": current_duration,
        "peak_date": peak_date,
        "trough_date": trough_date,
        "recovery_date": recovery_date,
        "recovery_days": recovery_days,
    }


def distribution_diagnostics(returns: pd.Series) -> dict[str, Any]:
    clean = _finite_series(returns)
    if len(clean) < 20:
        return {}
    values = clean.to_numpy(dtype=float)
    downside = np.minimum(values, 0.0)
    downside_deviation = float(np.sqrt(np.mean(np.square(downside))) * sqrt(TRADING_DAYS))
    annual_return = float(np.mean(values) * TRADING_DAYS)
    losses = float(np.abs(values[values < 0]).sum())
    gains = float(values[values > 0].sum())
    rolling_vol = clean.rolling(20).std(ddof=1) * sqrt(TRADING_DAYS)
    return {
        "observations": int(len(clean)),
        "annual_return": annual_return,
        "annual_volatility": float(np.std(values, ddof=1) * sqrt(TRADING_DAYS)),
        "downside_deviation": downside_deviation,
        "sortino_zero_mar": annual_return / max(downside_deviation, EPS),
        "omega_zero": gains / max(losses, EPS),
        "skewness": float(stats.skew(values, bias=False)),
        "excess_kurtosis": float(stats.kurtosis(values, fisher=True, bias=False)),
        "tail_ratio": float(np.quantile(values, 0.95) / max(abs(np.quantile(values, 0.05)), EPS)),
        "worst_day": float(np.min(values)),
        "best_day": float(np.max(values)),
        "vol_of_vol": float(rolling_vol.dropna().std(ddof=1)) if rolling_vol.notna().sum() > 2 else None,
    }


def volatility_regime(returns: pd.Series, decay: float) -> dict[str, Any]:
    clean = _finite_series(returns)
    if len(clean) < 30:
        return {"label": "DATA LIMITED"}
    vol20_series = clean.rolling(20).std(ddof=1) * sqrt(TRADING_DAYS)
    vol20 = float(vol20_series.dropna().iloc[-1])
    window60 = min(60, len(clean))
    vol60 = float(clean.tail(window60).std(ddof=1) * sqrt(TRADING_DAYS))
    vol252 = float(clean.tail(min(252, len(clean))).std(ddof=1) * sqrt(TRADING_DAYS))
    ewma = ewma_volatility(clean, decay)
    valid = vol20_series.dropna()
    percentile = float((valid <= vol20).mean()) if not valid.empty else None
    ratio = vol20 / max(vol60, EPS)
    if ratio >= 1.50 or (percentile is not None and percentile >= 0.90):
        label = "CRISIS / SPIKE"
    elif ratio >= 1.15 or (percentile is not None and percentile >= 0.75):
        label = "HIGH VOL"
    elif ratio <= 0.75 and (percentile is None or percentile <= 0.35):
        label = "COMPRESSION"
    else:
        label = "NORMAL"
    return {
        "label": label,
        "realized_20d": vol20,
        "realized_60d": vol60,
        "realized_long": vol252,
        "ewma": ewma.get("annualized"),
        "short_long_ratio": ratio,
        "percentile": percentile,
        "series_20d": vol20_series,
    }


def _xlog_probability(count: int, probability: float) -> float:
    if count <= 0:
        return 0.0
    return count * log(max(min(float(probability), 1.0 - EPS), EPS))


def _coverage_tests(exceptions: np.ndarray, expected_probability: float) -> dict[str, Any]:
    binary = np.asarray(exceptions, dtype=int)
    n = int(binary.size)
    x = int(binary.sum())
    if n == 0:
        return {"observations": 0, "exceptions": 0, "exception_rate": None}
    expected_probability = float(np.clip(expected_probability, EPS, 1.0 - EPS))
    observed = x / n
    ll_null = _xlog_probability(x, expected_probability) + _xlog_probability(n - x, 1.0 - expected_probability)
    ll_alt = _xlog_probability(x, observed) + _xlog_probability(n - x, 1.0 - observed)
    kupiec_lr = max(0.0, -2.0 * (ll_null - ll_alt))
    kupiec_p = float(stats.chi2.sf(kupiec_lr, 1))

    independence_lr = None
    independence_p = None
    if n >= 2:
        previous, current = binary[:-1], binary[1:]
        n00 = int(np.sum((previous == 0) & (current == 0)))
        n01 = int(np.sum((previous == 0) & (current == 1)))
        n10 = int(np.sum((previous == 1) & (current == 0)))
        n11 = int(np.sum((previous == 1) & (current == 1)))
        p01 = n01 / max(n00 + n01, 1)
        p11 = n11 / max(n10 + n11, 1)
        pooled = (n01 + n11) / max(n00 + n01 + n10 + n11, 1)
        ll_ind = _xlog_probability(n01 + n11, pooled) + _xlog_probability(n00 + n10, 1.0 - pooled)
        ll_markov = (
            _xlog_probability(n01, p01)
            + _xlog_probability(n00, 1.0 - p01)
            + _xlog_probability(n11, p11)
            + _xlog_probability(n10, 1.0 - p11)
        )
        independence_lr = max(0.0, -2.0 * (ll_ind - ll_markov))
        independence_p = float(stats.chi2.sf(independence_lr, 1))
    conditional_lr = kupiec_lr + (independence_lr or 0.0)
    conditional_p = float(stats.chi2.sf(conditional_lr, 2)) if independence_lr is not None else None
    minimum_p = min(value for value in (kupiec_p, independence_p) if value is not None)
    if n < 100:
        status = "LIMITED"
    elif minimum_p < 0.01:
        status = "FAIL"
    elif minimum_p < 0.05:
        status = "WARNING"
    else:
        status = "PASS"
    return {
        "observations": n,
        "exceptions": x,
        "exception_rate": observed,
        "expected_rate": expected_probability,
        "kupiec_lr": kupiec_lr,
        "kupiec_p_value": kupiec_p,
        "independence_lr": independence_lr,
        "independence_p_value": independence_p,
        "conditional_p_value": conditional_p,
        "status": status,
    }


def var_backtests(
    returns: pd.Series,
    *,
    confidence: float,
    decay: float = 0.94,
    window: int = 125,
) -> dict[str, Any]:
    clean = _finite_series(returns)
    if len(clean) < 80:
        return {"summary": pd.DataFrame(), "series": pd.DataFrame()}
    window = max(60, min(int(window), max(60, len(clean) // 2)))
    alpha = 1.0 - float(confidence)
    historical_var = clean.rolling(window).quantile(alpha).shift(1)
    rolling_mean = clean.rolling(window).mean().shift(1)
    ewma = ewma_volatility(clean, decay)["series"].shift(1)
    gaussian_var = rolling_mean + ewma * float(stats.norm.ppf(alpha))
    series = pd.DataFrame(
        {"Return": clean, "Historical VaR": historical_var, "EWMA Gaussian VaR": gaussian_var}
    ).dropna()
    rows: list[dict[str, Any]] = []
    for model in ("Historical VaR", "EWMA Gaussian VaR"):
        exceptions = (series["Return"] < series[model]).to_numpy(dtype=int)
        tests = _coverage_tests(exceptions, alpha)
        rows.append({"Model": model, **tests})
        series[f"{model} exception"] = exceptions.astype(bool)
    return {"summary": pd.DataFrame(rows), "series": series, "window": window}


def data_quality_assessment(price_data: pd.DataFrame) -> dict[str, Any]:
    raw_rows = len(price_data) if isinstance(price_data, pd.DataFrame) else 0
    clean = prepare_market_frame(price_data)
    provider = dict(getattr(price_data, "attrs", {}).get("data_context", {}) or {}) if isinstance(price_data, pd.DataFrame) else {}
    if clean.empty:
        return {
            "score": 0.0,
            "status": "BLOCKED",
            "provider": provider,
            "checks": pd.DataFrame([{"Check": "Usable prices", "Value": "0", "Status": "FAIL"}]),
        }
    close = clean["close"]
    duplicate_rows = max(raw_rows - len(clean), 0)
    zero_return_rate = float(close.pct_change(fill_method=None).tail(60).eq(0).mean())
    volume_coverage = float(clean["volume"].notna().mean()) if "volume" in clean else 0.0
    last_date = clean["date"].iloc[-1]
    now = pd.Timestamp.now(tz="UTC")
    age_days = max(int((now.normalize() - last_date.normalize()).days), 0)
    interval = str(provider.get("recency", "")).upper()
    recency_limit = 7 if "DEPENDENT" in interval or not interval else 14
    score = 35.0
    score += 25.0 if len(clean) >= 500 else 18.0 if len(clean) >= 250 else 10.0 if len(clean) >= 120 else 0.0
    score += 15.0 if age_days <= recency_limit else 7.0 if age_days <= 30 else 0.0
    score += 10.0 if duplicate_rows == 0 else 4.0
    score += 10.0 if zero_return_rate <= 0.05 else 4.0 if zero_return_rate <= 0.15 else 0.0
    score += 5.0 if volume_coverage >= 0.90 else 2.0 if volume_coverage >= 0.50 else 0.0
    score = float(np.clip(score, 0.0, 100.0))
    status = "STRONG" if score >= 85 else "ACCEPTABLE" if score >= 70 else "LIMITED" if score >= 50 else "WEAK"
    checks = pd.DataFrame(
        [
            {"Check": "Usable observations", "Value": len(clean), "Status": "PASS" if len(clean) >= 250 else "WARN"},
            {"Check": "Last market bar", "Value": str(last_date.date()), "Status": "PASS" if age_days <= recency_limit else "WARN"},
            {"Check": "Duplicate / invalid rows removed", "Value": duplicate_rows, "Status": "PASS" if duplicate_rows == 0 else "WARN"},
            {"Check": "Zero-return rate (60 bars)", "Value": zero_return_rate, "Status": "PASS" if zero_return_rate <= 0.05 else "WARN"},
            {"Check": "Volume coverage", "Value": volume_coverage, "Status": "PASS" if volume_coverage >= 0.90 else "WARN"},
            {"Check": "Provider", "Value": provider.get("provider", "Unknown"), "Status": str(provider.get("status", "UNKNOWN")).upper()},
        ]
    )
    return {"score": score, "status": status, "provider": provider, "checks": checks, "age_days": age_days}


def liquidity_diagnostics(frame: pd.DataFrame, parameters: RiskParameters) -> dict[str, Any]:
    clean = prepare_market_frame(frame)
    if clean.empty or "volume" not in clean or clean["volume"].notna().sum() < 10:
        return {"available": False, "status": "NO VOLUME", "table": pd.DataFrame()}
    dollar_volume = clean["close"] * clean["volume"].clip(lower=0)
    adv20 = float(dollar_volume.tail(min(20, len(dollar_volume))).median())
    adv60 = float(dollar_volume.tail(min(60, len(dollar_volume))).median())
    notional = parameters.position_notional
    position_adv = notional / max(adv20, EPS)
    daily_capacity = adv20 * parameters.adv_participation
    days_to_liquidate = notional / max(daily_capacity, EPS)
    returns = clean["close"].pct_change(fill_method=None)
    amihud = (returns.abs() / dollar_volume.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan).dropna()
    amihud_per_million = float(amihud.tail(min(60, len(amihud))).median() * 1_000_000) if not amihud.empty else None
    daily_vol = float(returns.dropna().tail(min(60, returns.notna().sum())).std(ddof=1))
    # Transparent square-root impact proxy; this is a risk overlay, not an execution quote.
    impact = 0.50 * daily_vol * sqrt(max(position_adv, 0.0)) if adv20 > 0 else None
    if days_to_liquidate <= 1.0 and position_adv <= 0.10:
        status = "LIQUID"
    elif days_to_liquidate <= 3.0 and position_adv <= 0.30:
        status = "MANAGEABLE"
    else:
        status = "CONSTRAINED"
    table = pd.DataFrame(
        [
            {"Metric": "Median dollar ADV 20D", "Value": adv20, "Limit / context": "Observed close × volume"},
            {"Metric": "Median dollar ADV 60D", "Value": adv60, "Limit / context": "Observed close × volume"},
            {"Metric": "Position / ADV", "Value": position_adv, "Limit / context": "≤ 10% preferred"},
            {"Metric": "Days to liquidate", "Value": days_to_liquidate, "Limit / context": f"At {parameters.adv_participation:.0%} ADV/day"},
            {"Metric": "Amihud per $1m", "Value": amihud_per_million, "Limit / context": "Observed proxy; lower is better"},
            {"Metric": "Square-root impact proxy", "Value": impact, "Limit / context": "0.5 × daily vol × sqrt(position/ADV)"},
        ]
    )
    return {
        "available": True,
        "status": status,
        "adv20": adv20,
        "adv60": adv60,
        "position_adv": position_adv,
        "days_to_liquidate": days_to_liquidate,
        "amihud_per_million": amihud_per_million,
        "impact_proxy": impact,
        "table": table,
    }


def _worst_historical_shock(returns: pd.Series, horizon: int) -> float | None:
    series = _horizon_simple_returns(returns, horizon)
    return float(series.min()) if not series.empty else None


def build_scenario_table(
    returns: pd.Series,
    *,
    parameters: RiskParameters,
    conservative_es: float | None,
    stop_short_return: float | None,
    stop_structural_return: float | None,
    liquidity_impact: float | None,
) -> pd.DataFrame:
    daily_vol = float(_finite_series(returns).std(ddof=1)) if len(_finite_series(returns)) >= 2 else 0.0
    horizon = parameters.horizon_days
    scenarios = [
        ("Custom shock", parameters.custom_shock, "User-controlled deterministic shock"),
        ("Worst observed day", _worst_historical_shock(returns, 1), "Worst rolling historical 1D return"),
        ("Worst observed week", _worst_historical_shock(returns, 5), "Worst rolling historical 5D return"),
        ("Worst observed month", _worst_historical_shock(returns, 20), "Worst rolling historical 20D return"),
        (
            f"Volatility shock ×{parameters.volatility_stress:.1f}",
            -parameters.volatility_stress * daily_vol * sqrt(horizon),
            "Zero-drift sigma shock over selected horizon",
        ),
        ("Conservative model ES", conservative_es, "Worst eligible ES across active models"),
        ("Short stop", stop_short_return, "Trading-plan invalidation level"),
        ("Structural stop", stop_structural_return, "Structural invalidation level"),
    ]
    direction = 1.0 if parameters.side == "Long" else -1.0
    impact = abs(float(liquidity_impact or 0.0))
    rows: list[dict[str, Any]] = []
    for name, shock, source in scenarios:
        if shock is None or not np.isfinite(shock):
            continue
        market_pnl = parameters.position_notional * direction * float(shock)
        execution_cost = parameters.position_notional * impact
        stressed_pnl = market_pnl - execution_cost
        loss_limit_dollars = parameters.portfolio_nav * parameters.loss_limit_pct
        rows.append(
            {
                "Scenario": name,
                "Asset shock": float(shock),
                "Position P&L": stressed_pnl,
                "P&L / NAV": stressed_pnl / parameters.portfolio_nav,
                "Loss-limit usage": max(-stressed_pnl, 0.0) / max(loss_limit_dollars, EPS),
                "Limit breached": "YES" if stressed_pnl < -loss_limit_dollars else "NO",
                "Liquidity overlay": execution_cost,
                "Source / assumption": source,
            }
        )
    return pd.DataFrame(rows)


def position_and_reverse_stress(
    *,
    parameters: RiskParameters,
    price: float,
    stop_short: float | None,
    stop_structural: float | None,
    conservative_var: float | None,
    conservative_es: float | None,
) -> dict[str, Any]:
    direction = 1.0 if parameters.side == "Long" else -1.0
    loss_limit_dollars = parameters.portfolio_nav * parameters.loss_limit_pct
    shock_to_limit = -loss_limit_dollars / max(parameters.position_notional, EPS) / direction
    short_return = stop_short / price - 1.0 if stop_short is not None and price > 0 else None
    structural_return = stop_structural / price - 1.0 if stop_structural is not None and price > 0 else None

    def loss_distance(level_return: float | None) -> float | None:
        if level_return is None:
            return None
        loss = -direction * level_return
        return loss if loss > 0 else None

    stop_loss_pct = loss_distance(short_return)
    structural_loss_pct = loss_distance(structural_return)
    max_notional_stop = loss_limit_dollars / stop_loss_pct if stop_loss_pct else None
    max_notional_es = loss_limit_dollars / abs(conservative_es) if conservative_es is not None and conservative_es < 0 else None
    candidates = [value for value in (max_notional_stop, max_notional_es) if value is not None and np.isfinite(value)]
    model_limit = min(candidates) if candidates else None
    table = pd.DataFrame(
        [
            {"Control": "Current position", "Value": parameters.position_notional, "Limit": parameters.portfolio_nav, "Usage": parameters.position_notional / parameters.portfolio_nav},
            {"Control": "Loss limit", "Value": loss_limit_dollars, "Limit": parameters.loss_limit_pct, "Usage": None},
            {"Control": "VaR capital", "Value": parameters.position_notional * abs(conservative_var or 0.0), "Limit": loss_limit_dollars, "Usage": parameters.position_notional * abs(conservative_var or 0.0) / max(loss_limit_dollars, EPS)},
            {"Control": "ES capital", "Value": parameters.position_notional * abs(conservative_es or 0.0), "Limit": loss_limit_dollars, "Usage": parameters.position_notional * abs(conservative_es or 0.0) / max(loss_limit_dollars, EPS)},
            {"Control": "Max notional by short stop", "Value": max_notional_stop, "Limit": loss_limit_dollars, "Usage": None},
            {"Control": "Max notional by conservative ES", "Value": max_notional_es, "Limit": loss_limit_dollars, "Usage": None},
            {"Control": "Binding model limit", "Value": model_limit, "Limit": loss_limit_dollars, "Usage": parameters.position_notional / model_limit if model_limit else None},
        ]
    )
    return {
        "loss_limit_dollars": loss_limit_dollars,
        "shock_to_loss_limit": shock_to_limit,
        "stop_short_return": short_return,
        "stop_structural_return": structural_return,
        "max_notional_stop": max_notional_stop,
        "max_notional_es": max_notional_es,
        "binding_notional_limit": model_limit,
        "var_dollars": parameters.position_notional * abs(conservative_var or 0.0),
        "es_dollars": parameters.position_notional * abs(conservative_es or 0.0),
        "table": table,
    }


def evt_diagnostics(returns: pd.Series) -> dict[str, Any]:
    clean = _finite_series(returns)
    if fit_evt_tail is None or len(clean) < 120:
        return {"status": "INELIGIBLE", "reason": "At least 120 returns and SciPy EVT support are required."}
    logs = np.log1p(np.clip(clean.to_numpy(dtype=float), -0.999999, None))
    # Target roughly 30 exceedances on shorter histories, while retaining the
    # conventional 95th-percentile POT threshold on deeper samples.
    threshold_quantile = float(np.clip(1.0 - 30.0 / len(logs), 0.90, 0.95))
    fit = fit_evt_tail(
        logs,
        threshold_quantile=threshold_quantile,
        bootstrap_repetitions=80,
        seed=42,
    )
    if not fit.get("ok"):
        return fit
    stability_table = evt_threshold_stability(logs) if evt_threshold_stability is not None else pd.DataFrame()
    stability = (
        assess_evt_threshold_stability(stability_table)
        if assess_evt_threshold_stability is not None
        else {"status": "INELIGIBLE"}
    )
    return {**fit, "stability_table": stability_table, "stability": stability}


def build_alert_matrix(snapshot: Mapping[str, Any]) -> pd.DataFrame:
    parameters: RiskParameters = snapshot["parameters"]
    alerts: list[dict[str, Any]] = []

    def add(control: str, severity: str, current: Any, limit: Any, action: str) -> None:
        alerts.append({"Control": control, "Severity": severity, "Current": current, "Limit": limit, "Action": action})

    quality = snapshot["data_quality"]
    add(
        "Data quality",
        "CRITICAL" if quality["score"] < 50 else "WARNING" if quality["score"] < 70 else "OK",
        quality["score"] / 100.0,
        ">= 70%",
        "Refresh or extend history before relying on model output." if quality["score"] < 70 else "Data controls acceptable.",
    )
    provider = quality.get("provider", {}) or {}
    provider_status = str(provider.get("status", "UNKNOWN")).upper()
    provider_recency = str(provider.get("recency", "UNKNOWN")).upper()
    degraded_lineage = (
        provider_status in {"FALLBACK", "REFERENCE", "UNKNOWN"}
        or "DELAYED" in provider_recency
        or "UNSPECIFIED" in provider_recency
    )
    add(
        "Data provenance",
        "WARNING" if degraded_lineage else "OK",
        f"{provider.get('provider', 'Unknown')} · {provider_status} · {provider_recency}",
        "Primary / recency specified",
        "Keep a model-risk overlay until an entitled or explicitly current feed confirms the marks."
        if degraded_lineage else "Provider lineage and recency are explicit.",
    )
    position = snapshot["position"]
    es_usage = position["es_dollars"] / max(position["loss_limit_dollars"], EPS)
    add(
        "Expected shortfall limit",
        "CRITICAL" if es_usage > 1.0 else "WARNING" if es_usage > 0.75 else "OK",
        es_usage,
        "<= 100%",
        "Reduce notional or widen the approved risk budget." if es_usage > 1.0 else "Monitor capital usage.",
    )
    liquidity = snapshot["liquidity"]
    days = liquidity.get("days_to_liquidate")
    add(
        "Exit capacity",
        "WARNING" if days is None else "CRITICAL" if days > 5 else "WARNING" if days > 3 else "OK",
        days,
        "<= 3 days",
        "Lower position / raise ADV participation assumption only with execution evidence." if days is None or days > 3 else "Exit capacity acceptable under assumptions.",
    )
    dispersion = snapshot["model_dispersion_es"]
    add(
        "Model dispersion",
        "WARNING" if dispersion is None else "CRITICAL" if dispersion > 0.08 else "WARNING" if dispersion > 0.04 else "OK",
        dispersion,
        "<= 4 pp",
        "Use the conservative model and investigate specification risk." if dispersion and dispersion > 0.04 else "Models are reasonably aligned.",
    )
    backtest = snapshot["backtests"]["summary"]
    validation_status = "LIMITED" if backtest.empty else (
        "FAIL" if (backtest["status"] == "FAIL").any() else "WARNING" if (backtest["status"].isin(["WARNING", "LIMITED"])).any() else "PASS"
    )
    add(
        "VaR outcome analysis",
        "CRITICAL" if validation_status == "FAIL" else "WARNING" if validation_status in {"WARNING", "LIMITED"} else "OK",
        validation_status,
        "PASS",
        "Treat VaR as provisional; review exceptions and calibration." if validation_status != "PASS" else "Coverage and independence checks pass.",
    )
    drawdown = snapshot["drawdown"]
    current_dd = drawdown.get("current_drawdown")
    add(
        "Current drawdown",
        "WARNING" if current_dd is None else "CRITICAL" if current_dd <= -0.20 else "WARNING" if current_dd <= -0.10 else "OK",
        current_dd,
        "> -10%",
        "Apply drawdown de-risking and review thesis." if current_dd is not None and current_dd <= -0.10 else "No drawdown escalation.",
    )
    regime = snapshot["regime"]
    ratio = regime.get("short_long_ratio")
    add(
        "Volatility regime",
        "WARNING" if ratio is None else "CRITICAL" if ratio >= 1.5 else "WARNING" if ratio >= 1.15 else "OK",
        regime.get("label"),
        "NORMAL / COMPRESSION",
        "Cut leverage and rely on stressed estimates." if ratio is not None and ratio >= 1.15 else "Regime overlay neutral.",
    )
    severity_order = {"CRITICAL": 0, "WARNING": 1, "OK": 2}
    table = pd.DataFrame(alerts)
    table["_order"] = table["Severity"].map(severity_order).fillna(3)
    return table.sort_values(["_order", "Control"]).drop(columns="_order").reset_index(drop=True)


def build_institutional_risk_snapshot(
    price_data: pd.DataFrame,
    *,
    price: float,
    parameters: RiskParameters,
    stop_short: float | None = None,
    stop_structural: float | None = None,
    factor_returns: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Build the complete single-position institutional risk-control snapshot."""

    parameters = parameters.normalized()
    frame = prepare_market_frame(price_data)
    returns = simple_returns(frame)
    base_tail_models = build_tail_model_comparison(
        returns,
        horizon=parameters.horizon_days,
        confidence=parameters.confidence,
        decay=parameters.ewma_lambda,
        seed=parameters.seed,
    )
    backtests = var_backtests(returns, confidence=parameters.confidence, decay=parameters.ewma_lambda)
    advanced = build_advanced_research_snapshot(
        returns,
        horizon=parameters.horizon_days,
        confidence=parameters.confidence,
        seed=parameters.seed,
        base_tail_models=base_tail_models,
        backtest_summary=backtests["summary"],
        factor_returns=factor_returns,
    )
    tail_models = advanced["tail_models"]
    eligible = tail_models.dropna(subset=["VaR", "ES"]) if not tail_models.empty else pd.DataFrame()
    conservative_var = float(eligible["VaR"].min()) if not eligible.empty else None
    conservative_es = float(eligible["ES"].min()) if not eligible.empty else None
    dispersion_es = float(eligible["ES"].max() - eligible["ES"].min()) if len(eligible) >= 2 else None
    drawdown = drawdown_diagnostics(frame)
    diagnostics = distribution_diagnostics(returns)
    regime = volatility_regime(returns, parameters.ewma_lambda)
    quality = data_quality_assessment(price_data)
    liquidity = liquidity_diagnostics(frame, parameters)
    position = position_and_reverse_stress(
        parameters=parameters,
        price=float(price),
        stop_short=stop_short,
        stop_structural=stop_structural,
        conservative_var=conservative_var,
        conservative_es=conservative_es,
    )
    scenarios = build_scenario_table(
        returns,
        parameters=parameters,
        conservative_es=conservative_es,
        stop_short_return=position["stop_short_return"],
        stop_structural_return=position["stop_structural_return"],
        liquidity_impact=liquidity.get("impact_proxy"),
    )
    snapshot: dict[str, Any] = {
        "parameters": parameters,
        "parameters_dict": asdict(parameters),
        "frame": frame,
        "returns": returns,
        "tail_models": tail_models,
        "conservative_var": conservative_var,
        "conservative_es": conservative_es,
        "model_dispersion_es": dispersion_es,
        "backtests": backtests,
        "drawdown": drawdown,
        "distribution": diagnostics,
        "regime": regime,
        "data_quality": quality,
        "liquidity": liquidity,
        "position": position,
        "scenarios": scenarios,
        "evt": evt_diagnostics(returns),
        "advanced": advanced,
    }
    snapshot["alerts"] = build_alert_matrix(snapshot)
    critical = int((snapshot["alerts"]["Severity"] == "CRITICAL").sum())
    warnings = int((snapshot["alerts"]["Severity"] == "WARNING").sum())
    snapshot["control_status"] = "RED" if critical else "AMBER" if warnings else "GREEN"
    snapshot["validation_status"] = (
        "LIMITED" if backtests["summary"].empty else (
            "FAIL" if (backtests["summary"]["status"] == "FAIL").any() else
            "REVIEW" if (backtests["summary"]["status"].isin(["WARNING", "LIMITED"])).any() else "PASS"
        )
    )
    return snapshot
