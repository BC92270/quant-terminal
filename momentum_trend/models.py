from __future__ import annotations

import math
import warnings
from dataclasses import replace

import numpy as np
import pandas as pd
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import Ridge
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .config import EngineConfig
from .contracts import ModelForecast
from .features import MODEL_FEATURES


Z80 = 1.2815515655446004


def _normal_probability(mean: float, standard_deviation: float) -> float:
    if not np.isfinite(standard_deviation) or standard_deviation <= 1e-12:
        return float(mean > 0)
    return float(0.5 * (1 + math.erf(mean / standard_deviation / math.sqrt(2))))


def _metrics(prediction: np.ndarray, target: np.ndarray) -> dict[str, float | int | None]:
    valid = np.isfinite(prediction) & np.isfinite(target)
    prediction = prediction[valid]
    target = target[valid]
    if len(target) < 10:
        return {"accuracy": None, "ic": None, "mae": None, "observations": len(target), "residual_std": None}
    accuracy = float(np.mean(np.sign(prediction) == np.sign(target)))
    if np.std(prediction) > 1e-12 and np.std(target) > 1e-12:
        ic = float(np.corrcoef(prediction, target)[0, 1])
    else:
        ic = None
    residual = target - prediction
    return {
        "accuracy": accuracy,
        "ic": ic,
        "mae": float(np.mean(np.abs(residual))),
        "observations": len(target),
        "residual_std": float(np.std(residual, ddof=1)),
    }


def _forecast_contract(
    *,
    name: str,
    family: str,
    horizon: int,
    expected_log_return: float,
    residual_std: float,
    metrics: dict,
    note: str,
) -> ModelForecast:
    expected = float(np.expm1(expected_log_return))
    sigma = max(float(residual_std), 1e-5)
    return ModelForecast(
        name=name,
        family=family,
        status="READY",
        horizon=horizon,
        expected_return=expected,
        lower=float(np.expm1(expected_log_return - Z80 * sigma)),
        upper=float(np.expm1(expected_log_return + Z80 * sigma)),
        probability_up=_normal_probability(expected_log_return, sigma),
        oos_directional_accuracy=metrics.get("accuracy"),
        oos_ic=metrics.get("ic"),
        oos_mae=metrics.get("mae"),
        observations=int(metrics.get("observations", 0)),
        note=note,
    )


def _supervised(frame: pd.DataFrame, horizon: int) -> tuple[pd.DataFrame, pd.Series]:
    available_features = [column for column in MODEL_FEATURES if column in frame.columns]
    x = frame[available_features].replace([np.inf, -np.inf], np.nan).copy()
    x = x.fillna(x.expanding(min_periods=1).median()).fillna(0.0)
    target = np.log(frame["close"].shift(-horizon) / frame["close"])
    return x, target


def _baseline_forecast(frame: pd.DataFrame, config: EngineConfig) -> ModelForecast:
    horizon = config.forecast_horizon
    prediction_series = (
        0.50 * np.log1p(frame["momentum_20"].clip(lower=-0.95)) * horizon / 20
        + 0.35 * np.log1p(frame["momentum_60"].clip(lower=-0.95)) * horizon / 60
        + 0.15 * frame["slope_60"].fillna(0) / config.annualisation * horizon
    )
    target = np.log(frame["close"].shift(-horizon) / frame["close"])
    evaluation = pd.concat([prediction_series, target], axis=1).dropna().tail(100)
    metrics = _metrics(evaluation.iloc[:, 0].to_numpy(), evaluation.iloc[:, 1].to_numpy())
    residual_std = metrics.get("residual_std") or float(frame["log_return"].std() * np.sqrt(horizon))
    return _forecast_contract(
        name="Time-series momentum",
        family="Classical signal",
        horizon=horizon,
        expected_log_return=float(prediction_series.iloc[-1]),
        residual_std=residual_std,
        metrics=metrics,
        note="Blend causal 20/60-day momentum and linear trend slope.",
    )


def _ar1_forecast(frame: pd.DataFrame, config: EngineConfig) -> ModelForecast:
    horizon = config.forecast_horizon
    returns = frame["log_return"].dropna().to_numpy()
    if len(returns) < 80:
        return ModelForecast("AR(1)", "Classical linear", "INSUFFICIENT_DATA", horizon, note="At least 80 returns required.")

    def fit_predict(sample: np.ndarray) -> float:
        y = sample[1:]
        x = np.column_stack([np.ones(len(sample) - 1), sample[:-1]])
        intercept, phi = np.linalg.lstsq(x, y, rcond=None)[0]
        phi = float(np.clip(phi, -0.98, 0.98))
        last = float(sample[-1])
        forecasts = []
        for _ in range(horizon):
            last = float(intercept + phi * last)
            forecasts.append(last)
        return float(sum(forecasts))

    oos_prediction: list[float] = []
    oos_target: list[float] = []
    window = min(252, max(80, len(returns) // 2))
    start = max(window, len(returns) - 90)
    for index in range(start, len(returns) - horizon):
        oos_prediction.append(fit_predict(returns[index - window:index]))
        oos_target.append(float(returns[index:index + horizon].sum()))
    metrics = _metrics(np.asarray(oos_prediction), np.asarray(oos_target))
    residual_std = metrics.get("residual_std") or float(np.std(returns) * np.sqrt(horizon))
    return _forecast_contract(
        name="AR(1)",
        family="Classical linear",
        horizon=horizon,
        expected_log_return=fit_predict(returns[-window:]),
        residual_std=residual_std,
        metrics=metrics,
        note="Rolling autoregression on log returns; coefficients constrained for stability.",
    )


def _kalman_state(frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    observations = np.log(frame["close"].to_numpy(dtype=float))
    states = np.zeros((len(observations), 2))
    variances = np.zeros(len(observations))
    state = np.array([observations[0], 0.0])
    covariance = np.eye(2) * 0.05
    transition = np.array([[1.0, 1.0], [0.0, 1.0]])
    observation = np.array([[1.0, 0.0]])
    return_variance = max(float(np.nanvar(np.diff(observations))), 1e-7)
    process_noise = np.diag([return_variance * 0.08, return_variance * 0.005])
    measurement_noise = return_variance * 0.45
    for index, value in enumerate(observations):
        predicted_state = transition @ state
        predicted_covariance = transition @ covariance @ transition.T + process_noise
        innovation = value - float((observation @ predicted_state)[0])
        innovation_variance = float((observation @ predicted_covariance @ observation.T)[0, 0] + measurement_noise)
        gain = predicted_covariance @ observation.T / innovation_variance
        state = predicted_state + gain[:, 0] * innovation
        covariance = (np.eye(2) - gain @ observation) @ predicted_covariance
        states[index] = state
        variances[index] = max(innovation_variance, 1e-12)
    return states, variances


def _kalman_forecast(frame: pd.DataFrame, config: EngineConfig) -> ModelForecast:
    horizon = config.forecast_horizon
    if len(frame) < 60:
        return ModelForecast("Kalman local trend", "State space", "INSUFFICIENT_DATA", horizon)
    states, variances = _kalman_state(frame)
    prediction = states[:, 1] * horizon
    target = np.log(frame["close"].shift(-horizon) / frame["close"]).to_numpy()
    valid_prediction = prediction[:-horizon][-100:]
    valid_target = target[:-horizon][-100:]
    metrics = _metrics(valid_prediction, valid_target)
    residual_std = metrics.get("residual_std") or float(math.sqrt(variances[-1] * horizon))
    return _forecast_contract(
        name="Kalman local trend",
        family="State space",
        horizon=horizon,
        expected_log_return=float(prediction[-1]),
        residual_std=residual_std,
        metrics=metrics,
        note="Recursive level/slope filter; no full-sample smoothing.",
    )


def _time_series_oos_predictions(
    estimator_factory,
    x: pd.DataFrame,
    target: pd.Series,
    horizon: int,
    splits: int = 3,
) -> tuple[np.ndarray, np.ndarray]:
    valid_target = target.notna()
    last_label = int(np.flatnonzero(valid_target.to_numpy())[-1]) if valid_target.any() else -1
    if last_label < 100:
        return np.array([]), np.array([])
    boundaries = np.linspace(max(80, last_label // 2), last_label + 1, splits + 1, dtype=int)
    predictions: list[float] = []
    actuals: list[float] = []
    for fold in range(splits):
        test_start, test_end = boundaries[fold], boundaries[fold + 1]
        train_end = max(0, test_start - horizon)
        if train_end < 60 or test_end <= test_start:
            continue
        model = estimator_factory()
        model.fit(x.iloc[:train_end], target.iloc[:train_end])
        fold_prediction = model.predict(x.iloc[test_start:test_end])
        fold_target = target.iloc[test_start:test_end].to_numpy()
        valid = np.isfinite(fold_target)
        predictions.extend(fold_prediction[valid].tolist())
        actuals.extend(fold_target[valid].tolist())
    return np.asarray(predictions), np.asarray(actuals)


def _ridge_forecast(frame: pd.DataFrame, config: EngineConfig) -> ModelForecast:
    horizon = config.forecast_horizon
    x, target = _supervised(frame, horizon)
    valid = target.notna()
    if valid.sum() < 100:
        return ModelForecast("Ridge factor model", "Classical linear", "INSUFFICIENT_DATA", horizon)

    factory = lambda: Pipeline([("scale", StandardScaler()), ("model", Ridge(alpha=4.0))])
    oos_prediction, oos_target = _time_series_oos_predictions(factory, x, target, horizon)
    metrics = _metrics(oos_prediction, oos_target)
    model = factory()
    model.fit(x.loc[valid], target.loc[valid])
    expected = float(model.predict(x.tail(1))[0])
    residual_std = metrics.get("residual_std") or float(target.loc[valid].std())
    return _forecast_contract(
        name="Ridge factor model",
        family="Classical linear",
        horizon=horizon,
        expected_log_return=expected,
        residual_std=residual_std,
        metrics=metrics,
        note="Regularised linear factor model with purged expanding time splits.",
    )


def _neural_forecast(frame: pd.DataFrame, config: EngineConfig) -> ModelForecast:
    horizon = config.forecast_horizon
    if not config.enable_neural_model:
        return ModelForecast("Deep MLP sequence", "Neural", "DISABLED", horizon, note="Disabled by mandate.")
    x, target = _supervised(frame, horizon)
    valid_indices = np.flatnonzero(target.notna().to_numpy())
    if len(valid_indices) < 180:
        return ModelForecast(
            "Deep MLP sequence",
            "Neural",
            "INSUFFICIENT_DATA",
            horizon,
            observations=len(valid_indices),
            note="180 labelled observations required; no synthetic neural forecast is substituted.",
        )

    split = int(len(valid_indices) * 0.75)
    train_indices = valid_indices[: max(1, split - horizon)]
    test_indices = valid_indices[split:]

    def factory(max_iter: int = 220):
        return Pipeline(
            [
                ("scale", StandardScaler()),
                (
                    "model",
                    MLPRegressor(
                        hidden_layer_sizes=(48, 24, 8),
                        activation="tanh",
                        alpha=0.025,
                        learning_rate_init=0.002,
                        early_stopping=True,
                        validation_fraction=0.18,
                        n_iter_no_change=16,
                        max_iter=max_iter,
                        random_state=config.random_state,
                    ),
                ),
            ]
        )

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ConvergenceWarning)
        validation_model = factory()
        validation_model.fit(x.iloc[train_indices], target.iloc[train_indices])
        prediction = validation_model.predict(x.iloc[test_indices])
        actual = target.iloc[test_indices].to_numpy()
        metrics = _metrics(prediction, actual)
        final_model = factory(260)
        final_model.fit(x.iloc[valid_indices], target.iloc[valid_indices])
        expected = float(final_model.predict(x.tail(1))[0])
    residual_std = metrics.get("residual_std") or float(target.iloc[valid_indices].std())
    return _forecast_contract(
        name="Deep MLP sequence",
        family="Neural",
        horizon=horizon,
        expected_log_return=expected,
        residual_std=residual_std,
        metrics=metrics,
        note="Three hidden layers on causal lag/factor features; chronological holdout, then refit.",
    )


def run_model_suite(frame: pd.DataFrame, config: EngineConfig) -> tuple[ModelForecast, ...]:
    models = (
        _baseline_forecast,
        _ar1_forecast,
        _kalman_forecast,
        _ridge_forecast,
        _neural_forecast,
    )
    forecasts: list[ModelForecast] = []
    for model in models:
        try:
            forecasts.append(model(frame, config))
        except Exception as exc:  # model isolation is deliberate in the UI
            name = model.__name__.strip("_").replace("_forecast", "").replace("_", " ").title()
            forecasts.append(
                ModelForecast(name, "Isolated", "ERROR", config.forecast_horizon, note=f"{type(exc).__name__}: {exc}")
            )
    return tuple(forecasts)

