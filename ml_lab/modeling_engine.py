"""Executable institutional ML engine for causal champion-challenger research."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable, Sequence
import hashlib
import json
import math

import numpy as np
import pandas as pd

from sklearn.base import clone
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    balanced_accuracy_score,
    brier_score_loss,
    precision_score,
    recall_score,
    f1_score,
    roc_auc_score,
)
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import RobustScaler

from .institutional_engine import (
    LocalExperimentRegistry,
    block_bootstrap_sharpe_interval,
    causal_feature_frame,
    conformal_binary_sets,
    deflated_sharpe_probability,
    expected_calibration_error,
    promotion_decision,
)


ML_ENGINE_VERSION = "ML-CHAMPION-CHALLENGER-V2.0"
EXECUTABLE_ML_MODELS = (
    "Prior",
    "Logistic",
    "HistGradientBoosting",
    "Extra Trees",
    "Causal MLP",
    "Neural Ensemble",
    "Institutional Blend",
)


@dataclass(frozen=True)
class ModelValidationConfig:
    horizon: int = 20
    n_splits: int = 4
    min_train_rows: int = 80
    min_test_rows: int = 20
    calibration_fraction: float = 0.20
    long_threshold: float = 0.58
    short_threshold: float = 0.42
    transaction_cost_bps: float = 10.0
    random_state: int = 42
    selected_models: tuple[str, ...] = (
        "Prior",
        "Logistic",
        "HistGradientBoosting",
        "Extra Trees",
        "Causal MLP",
    )


def _find_label_series(frame: pd.DataFrame) -> pd.Series:
    lowered = {str(column).lower(): column for column in frame.columns}
    for name in ("tb_label", "label", "target", "binary_target", "triple_barrier_label", "y"):
        if name in lowered:
            return frame[lowered[name]]
    for column in frame.columns:
        if "label" in str(column).lower() or "target" in str(column).lower():
            return frame[column]
    return pd.Series(dtype=float)


def _binary_labels(series: pd.Series) -> pd.Series:
    text = series.astype(str).str.lower()
    result = pd.Series(np.nan, index=series.index, dtype=float)
    result.loc[text.str.contains("tp", regex=False, na=False)] = 1.0
    result.loc[text.str.contains("sl", regex=False, na=False)] = 0.0
    timeout = text.str.contains("timeout", regex=False, na=False)
    numeric = pd.to_numeric(series, errors="coerce")
    numeric_mask = result.isna() & numeric.notna() & ~timeout
    if numeric_mask.any():
        values = numeric.loc[numeric_mask]
        if set(values.unique().tolist()).issubset({-1.0, 0.0, 1.0}) and -1.0 in values.values:
            result.loc[numeric_mask] = (values > 0).astype(float)
        else:
            result.loc[numeric_mask] = values.where(values.isin([0, 1]))
    return result


def _time_axis(frame: pd.DataFrame) -> pd.Series:
    if isinstance(frame.index, pd.DatetimeIndex):
        return pd.Series(pd.to_datetime(frame.index, errors="coerce"), index=frame.index)
    lowered = {str(column).lower(): column for column in frame.columns}
    for name in ("date", "datetime", "timestamp", "time"):
        if name in lowered:
            return pd.Series(pd.to_datetime(frame[lowered[name]], errors="coerce"), index=frame.index)
    return pd.Series(pd.RangeIndex(len(frame)), index=frame.index)


def prepare_causal_ml_dataset(
    labeled_df: pd.DataFrame,
    feature_df: pd.DataFrame,
    minimum_coverage: float = 0.70,
) -> dict[str, Any]:
    causal, quarantined = causal_feature_frame(feature_df)
    numeric = causal.select_dtypes(include=[np.number]).replace([np.inf, -np.inf], np.nan)
    coverage = numeric.notna().mean()
    eligible = [
        column
        for column in numeric.columns
        if float(coverage.get(column, 0.0)) >= float(minimum_coverage)
        and numeric[column].nunique(dropna=True) > 1
    ]
    numeric = numeric.loc[:, eligible].copy()

    labels = _binary_labels(_find_label_series(labeled_df))
    timestamps = _time_axis(labeled_df)
    if len(numeric) != len(labeled_df):
        numeric = numeric.reindex(labeled_df.index)
    else:
        numeric.index = labeled_df.index

    valid = labels.notna() & timestamps.notna()
    X = numeric.loc[valid].copy()
    y = labels.loc[valid].astype(int).to_numpy()
    dates = timestamps.loc[valid].reset_index(drop=True)
    X = X.reset_index(drop=True)

    return {
        "X": X,
        "y": y,
        "dates": dates,
        "feature_columns": list(X.columns),
        "quarantined_columns": quarantined,
        "dropped_low_coverage": [str(column) for column in numeric.columns if column not in eligible],
    }


def purged_expanding_splits(
    n_rows: int,
    horizon: int,
    n_splits: int = 4,
    min_train_rows: int = 80,
    min_test_rows: int = 20,
) -> list[dict[str, Any]]:
    n_rows = int(n_rows)
    purge = max(1, int(horizon))
    folds = max(2, int(n_splits))
    remaining = n_rows - int(min_train_rows) - purge
    if remaining < int(min_test_rows):
        return []
    test_rows = max(int(min_test_rows), remaining // folds)
    results: list[dict[str, Any]] = []
    for fold in range(folds):
        train_end = int(min_train_rows) + fold * test_rows
        test_start = train_end + purge
        test_end = min(test_start + test_rows, n_rows)
        if train_end < int(min_train_rows) or test_end - test_start < int(min_test_rows):
            continue
        train_index = np.arange(0, train_end, dtype=int)
        test_index = np.arange(test_start, test_end, dtype=int)
        results.append(
            {
                "fold": fold + 1,
                "train_index": train_index,
                "test_index": test_index,
                "train_rows": len(train_index),
                "purge_rows": test_start - train_end,
                "test_rows": len(test_index),
            }
        )
    return results


def _standard_pipeline(estimator: Any) -> Pipeline:
    return Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median", add_indicator=True)),
            ("scaler", RobustScaler(quantile_range=(10.0, 90.0))),
            ("model", estimator),
        ]
    )


def _tree_pipeline(estimator: Any) -> Pipeline:
    return Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median", add_indicator=True)),
            ("model", estimator),
        ]
    )


def _estimator(model_name: str, random_state: int) -> Any:
    if model_name == "Prior":
        return _tree_pipeline(DummyClassifier(strategy="prior", random_state=random_state))
    if model_name == "Logistic":
        return _standard_pipeline(
            LogisticRegression(
                C=0.50,
                max_iter=1500,
                class_weight="balanced",
                random_state=random_state,
            )
        )
    if model_name == "HistGradientBoosting":
        return _tree_pipeline(
            HistGradientBoostingClassifier(
                learning_rate=0.04,
                max_iter=220,
                max_leaf_nodes=15,
                min_samples_leaf=10,
                l2_regularization=1.5,
                early_stopping=True,
                random_state=random_state,
            )
        )
    if model_name == "Extra Trees":
        return _tree_pipeline(
            ExtraTreesClassifier(
                n_estimators=400,
                max_depth=8,
                min_samples_leaf=5,
                max_features="sqrt",
                class_weight="balanced_subsample",
                n_jobs=-1,
                random_state=random_state,
            )
        )
    if model_name == "Causal MLP":
        return _standard_pipeline(
            MLPClassifier(
                hidden_layer_sizes=(96, 48, 24),
                activation="relu",
                alpha=2e-3,
                learning_rate_init=8e-4,
                max_iter=350,
                early_stopping=True,
                validation_fraction=0.20,
                n_iter_no_change=18,
                random_state=random_state,
            )
        )
    raise ValueError(f"Unknown executable model: {model_name}")


def _positive_probability(estimator: Any, X: pd.DataFrame) -> np.ndarray:
    if hasattr(estimator, "predict_proba"):
        values = estimator.predict_proba(X)
        classes = list(getattr(estimator, "classes_", []))
        if values.ndim == 2 and values.shape[1] > 1:
            index = classes.index(1) if 1 in classes else values.shape[1] - 1
            return np.asarray(values[:, index], dtype=float)
        only = classes[0] if classes else 0
        return np.repeat(1.0 if int(only) == 1 else 0.0, len(X))
    return np.asarray(estimator.predict(X), dtype=float)


def _single_fit_predict(
    model_name: str,
    X_train: pd.DataFrame,
    y_train: np.ndarray,
    X_predict: pd.DataFrame,
    random_state: int,
) -> tuple[np.ndarray, str]:
    estimator = _estimator(model_name, random_state)
    estimator.fit(X_train, y_train)
    return np.clip(_positive_probability(estimator, X_predict), 1e-6, 1.0 - 1e-6), type(estimator).__name__


def _model_fit_predict(
    model_name: str,
    X_train: pd.DataFrame,
    y_train: np.ndarray,
    X_predict: pd.DataFrame,
    random_state: int,
) -> tuple[np.ndarray, str]:
    if model_name in {"Prior", "Logistic", "HistGradientBoosting", "Extra Trees", "Causal MLP"}:
        return _single_fit_predict(model_name, X_train, y_train, X_predict, random_state)

    if model_name == "Neural Ensemble":
        probabilities = []
        for offset in (0, 17, 41):
            probability, _ = _single_fit_predict(
                "Causal MLP", X_train, y_train, X_predict, random_state + offset
            )
            probabilities.append(probability)
        return np.mean(probabilities, axis=0), "3-seed causal MLP ensemble"

    if model_name == "Institutional Blend":
        components = ("Logistic", "HistGradientBoosting", "Extra Trees", "Causal MLP")
        probabilities = []
        for offset, component in enumerate(components):
            probability, _ = _single_fit_predict(
                component, X_train, y_train, X_predict, random_state + offset * 13
            )
            probabilities.append(probability)
        return np.mean(probabilities, axis=0), "equal-weight diversified blend"

    raise ValueError(f"Unknown executable model: {model_name}")


def _apply_temperature(probability: Sequence[float], temperature: float) -> np.ndarray:
    p = np.clip(np.asarray(probability, dtype=float), 1e-6, 1.0 - 1e-6)
    logits = np.log(p / (1.0 - p)) / max(float(temperature), 1e-6)
    return 1.0 / (1.0 + np.exp(-np.clip(logits, -30.0, 30.0)))


def fit_temperature(y_true: Sequence[int], probability: Sequence[float]) -> float:
    y = np.asarray(y_true, dtype=float)
    p = np.asarray(probability, dtype=float)
    mask = np.isfinite(y) & np.isfinite(p)
    y, p = y[mask], p[mask]
    if len(y) < 15 or len(np.unique(y)) < 2:
        return 1.0
    best_temperature = 1.0
    best_loss = float("inf")
    for temperature in np.geomspace(0.50, 4.00, 41):
        calibrated = np.clip(_apply_temperature(p, temperature), 1e-8, 1.0 - 1e-8)
        loss = -float(np.mean(y * np.log(calibrated) + (1.0 - y) * np.log(1.0 - calibrated)))
        if loss < best_loss:
            best_loss = loss
            best_temperature = float(temperature)
    return best_temperature


def _calibrated_fold_probabilities(
    model_name: str,
    X_train: pd.DataFrame,
    y_train: np.ndarray,
    X_test: pd.DataFrame,
    cfg: ModelValidationConfig,
    fold: int,
) -> tuple[np.ndarray, float, str]:
    calibration_rows = max(20, int(len(X_train) * cfg.calibration_fraction))
    calibration_start = len(X_train) - calibration_rows
    core_end = calibration_start - max(1, int(cfg.horizon))
    temperature = 1.0

    if (
        core_end >= 40
        and calibration_rows >= 15
        and len(np.unique(y_train[:core_end])) == 2
        and len(np.unique(y_train[calibration_start:])) == 2
    ):
        calibration_probability, _ = _model_fit_predict(
            model_name,
            X_train.iloc[:core_end],
            y_train[:core_end],
            X_train.iloc[calibration_start:],
            cfg.random_state + fold * 101,
        )
        temperature = fit_temperature(y_train[calibration_start:], calibration_probability)

    test_probability, backend = _model_fit_predict(
        model_name,
        X_train,
        y_train,
        X_test,
        cfg.random_state + fold * 101,
    )
    return _apply_temperature(test_probability, temperature), temperature, backend


def _classification_metrics(y_true: np.ndarray, probability: np.ndarray) -> dict[str, float]:
    y = np.asarray(y_true, dtype=int)
    p = np.clip(np.asarray(probability, dtype=float), 0.0, 1.0)
    prediction = (p >= 0.50).astype(int)
    auc = float(roc_auc_score(y, p)) if len(np.unique(y)) == 2 else float("nan")
    return {
        "balanced_accuracy": float(balanced_accuracy_score(y, prediction)),
        "roc_auc": auc,
        "brier": float(brier_score_loss(y, p)),
        "ece": float(expected_calibration_error(y, p)),
        "precision": float(precision_score(y, prediction, zero_division=0)),
        "recall": float(recall_score(y, prediction, zero_division=0)),
        "f1": float(f1_score(y, prediction, zero_division=0)),
    }


def _economic_proxy(
    y_true: np.ndarray,
    probability: np.ndarray,
    cfg: ModelValidationConfig,
) -> dict[str, Any]:
    p = np.asarray(probability, dtype=float)
    signal = np.where(p >= cfg.long_threshold, 1.0, np.where(p <= cfg.short_threshold, -1.0, 0.0))
    outcome = np.where(np.asarray(y_true, dtype=int) == 1, 1.0, -1.0)
    turnover = np.abs(np.diff(np.r_[0.0, signal]))
    returns = signal * outcome * 0.01 - turnover * (cfg.transaction_cost_bps / 10000.0)
    curve = np.cumsum(returns)
    peak = np.maximum.accumulate(np.r_[0.0, curve])[1:]
    drawdown = curve - peak
    interval = block_bootstrap_sharpe_interval(returns, simulations=300, seed=cfg.random_state)
    return {
        "selection_rate": float(np.mean(signal != 0.0)),
        "turnover": float(np.sum(turnover)),
        "net_utility": float(np.sum(returns)),
        "net_sharpe": float(interval["sharpe"]),
        "sharpe_lower": float(interval["lower"]),
        "sharpe_upper": float(interval["upper"]),
        "deflated_sharpe_probability": float(deflated_sharpe_probability(returns, trials=7)),
        "max_drawdown": float(np.min(drawdown)) if len(drawdown) else 0.0,
        "signal": signal,
        "returns": returns,
    }


def run_ml_champion_challenger(
    labeled_df: pd.DataFrame,
    feature_df: pd.DataFrame,
    cfg: ModelValidationConfig,
    max_feature_psi: float = 0.0,
) -> dict[str, Any]:
    dataset = prepare_causal_ml_dataset(labeled_df, feature_df)
    X: pd.DataFrame = dataset["X"]
    y: np.ndarray = dataset["y"]
    dates: pd.Series = dataset["dates"]
    splits = purged_expanding_splits(
        len(X),
        cfg.horizon,
        cfg.n_splits,
        cfg.min_train_rows,
        cfg.min_test_rows,
    )
    if not splits:
        return {"ok": False, "reason": "Insufficient rows for purged expanding validation.", "dataset": dataset}

    requested = [name for name in cfg.selected_models if name in EXECUTABLE_ML_MODELS]
    if "Prior" not in requested:
        requested.insert(0, "Prior")
    if "Logistic" not in requested:
        requested.insert(1, "Logistic")

    fold_rows: list[dict[str, Any]] = []
    prediction_rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for split in splits:
        fold = int(split["fold"])
        train_index = split["train_index"]
        test_index = split["test_index"]
        X_train, X_test = X.iloc[train_index], X.iloc[test_index]
        y_train, y_test = y[train_index], y[test_index]
        if len(np.unique(y_train)) < 2:
            errors.append({"Fold": fold, "Model": "all", "Error": "One-class training fold."})
            continue

        for model_name in requested:
            try:
                probability, temperature, backend = _calibrated_fold_probabilities(
                    model_name, X_train, y_train, X_test, cfg, fold
                )
                metrics = _classification_metrics(y_test, probability)
                fold_rows.append(
                    {
                        "Fold": fold,
                        "Model": model_name,
                        "Train rows": len(train_index),
                        "Purge rows": split["purge_rows"],
                        "OOS rows": len(test_index),
                        "Balanced accuracy": metrics["balanced_accuracy"],
                        "ROC AUC": metrics["roc_auc"],
                        "Brier": metrics["brier"],
                        "ECE": metrics["ece"],
                        "Temperature": temperature,
                        "Backend": backend,
                    }
                )
                for position, row_index in enumerate(test_index):
                    prediction_rows.append(
                        {
                            "Date": pd.to_datetime(dates.iloc[row_index], errors="coerce"),
                            "Fold": fold,
                            "Model": model_name,
                            "y_true": int(y_test[position]),
                            "probability": float(probability[position]),
                        }
                    )
            except Exception as exc:
                errors.append({"Fold": fold, "Model": model_name, "Error": str(exc)})

    predictions = pd.DataFrame(prediction_rows)
    fold_metrics = pd.DataFrame(fold_rows)
    if predictions.empty:
        return {
            "ok": False,
            "reason": "Every candidate failed.",
            "dataset": dataset,
            "errors": pd.DataFrame(errors),
        }

    leaderboard_rows: list[dict[str, Any]] = []
    uncertainty_rows: list[dict[str, Any]] = []
    for model_name, group in predictions.groupby("Model", sort=False):
        group = group.sort_values(["Date", "Fold"]).drop_duplicates(["Date"], keep="last")
        y_model = group["y_true"].to_numpy(dtype=int)
        p_model = group["probability"].to_numpy(dtype=float)
        statistical = _classification_metrics(y_model, p_model)
        economic = _economic_proxy(y_model, p_model, cfg)

        calibration_rows = max(30, int(len(group) * 0.40))
        if calibration_rows < len(group) - 10:
            conformal, qhat = conformal_binary_sets(
                y_model[:calibration_rows],
                p_model[:calibration_rows],
                p_model[calibration_rows:],
                alpha=0.10,
            )
            y_evaluation = y_model[calibration_rows:]
            coverage = float(
                np.mean(
                    [
                        str(int(label)) in prediction_set
                        for label, prediction_set in zip(y_evaluation, conformal["Prediction set"])
                    ]
                )
            )
            abstention = float(conformal["Abstain"].mean())
        else:
            qhat, coverage, abstention = float("nan"), float("nan"), float("nan")

        leaderboard_rows.append(
            {
                "Model": model_name,
                "OOS rows": len(group),
                "Balanced accuracy": statistical["balanced_accuracy"],
                "ROC AUC": statistical["roc_auc"],
                "Brier": statistical["brier"],
                "ECE": statistical["ece"],
                "Selection rate": economic["selection_rate"],
                "Net utility": economic["net_utility"],
                "Utility Sharpe": economic["net_sharpe"],
                "Sharpe lower 95%": economic["sharpe_lower"],
                "Deflated Sharpe P": economic["deflated_sharpe_probability"],
                "Max drawdown": economic["max_drawdown"],
            }
        )
        uncertainty_rows.append(
            {
                "Model": model_name,
                "Conformal q": qhat,
                "Empirical coverage": coverage,
                "Abstention rate": abstention,
                "Target coverage": 0.90,
            }
        )

    leaderboard = pd.DataFrame(leaderboard_rows).sort_values(
        ["Balanced accuracy", "Brier"], ascending=[False, True]
    )
    uncertainty = pd.DataFrame(uncertainty_rows)
    candidates = leaderboard.loc[~leaderboard["Model"].isin(["Prior", "Logistic"])]
    champion = str(candidates.iloc[0]["Model"]) if not candidates.empty else "Logistic"
    champion_row = leaderboard.loc[leaderboard["Model"] == champion].iloc[0]
    baseline_rows = leaderboard.loc[leaderboard["Model"] == "Logistic"]
    baseline_row = baseline_rows.iloc[0] if not baseline_rows.empty else leaderboard.iloc[-1]
    decision = promotion_decision(
        {
            "oos_rows": float(champion_row["OOS rows"]),
            "balanced_accuracy": float(champion_row["Balanced accuracy"]),
            "brier": float(champion_row["Brier"]),
            "ece": float(champion_row["ECE"]),
            "max_feature_psi": float(max_feature_psi),
            "net_sharpe": float(champion_row["Utility Sharpe"]),
            "max_drawdown": float(champion_row["Max drawdown"]),
        },
        {
            "balanced_accuracy": float(baseline_row["Balanced accuracy"]),
            "brier": float(baseline_row["Brier"]),
        },
    )

    split_audit = pd.DataFrame(
        [
            {
                "Fold": split["fold"],
                "Train rows": split["train_rows"],
                "Purge rows": split["purge_rows"],
                "OOS rows": split["test_rows"],
                "Train end": int(split["train_index"][-1]),
                "Test start": int(split["test_index"][0]),
            }
            for split in splits
        ]
    )
    return {
        "ok": True,
        "engine_version": ML_ENGINE_VERSION,
        "config": asdict(cfg),
        "dataset": dataset,
        "splits": split_audit,
        "fold_metrics": fold_metrics,
        "leaderboard": leaderboard.reset_index(drop=True),
        "predictions": predictions.sort_values(["Date", "Model", "Fold"]).reset_index(drop=True),
        "uncertainty": uncertainty,
        "errors": pd.DataFrame(errors),
        "champion": champion,
        "decision": decision,
    }


def _result_key(ticker: str, dataset_id: str, cfg: ModelValidationConfig) -> str:
    payload = json.dumps({"ticker": ticker, "dataset": dataset_id, "cfg": asdict(cfg)}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def render_ml_validation_engine(
    ticker: str,
    labeled_df: pd.DataFrame,
    feature_df: pd.DataFrame,
    horizon: int,
    control_report: dict[str, Any],
) -> None:
    import streamlit as st

    st.markdown("#### Executable ML validation engine")
    st.caption(
        "Purged expanding folds, temporal calibration, conformal abstention, "
        "cost-aware utility and champion–challenger gates on the causal matrix."
    )

    with st.expander("Validation configuration", expanded=False):
        models = st.multiselect(
            "Executable models",
            list(EXECUTABLE_ML_MODELS),
            default=["Prior", "Logistic", "HistGradientBoosting", "Extra Trees", "Causal MLP"],
            key=f"ml_exec_models_{ticker}",
        )
        c1, c2, c3 = st.columns(3)
        n_splits = c1.selectbox("Purged folds", [3, 4, 5], index=1, key=f"ml_exec_folds_{ticker}")
        cost_bps = c2.number_input(
            "Transaction cost (bps)",
            min_value=0.0,
            max_value=100.0,
            value=10.0,
            step=1.0,
            key=f"ml_exec_cost_{ticker}",
        )
        threshold = c3.slider(
            "Directional threshold",
            min_value=0.52,
            max_value=0.70,
            value=0.58,
            step=0.01,
            key=f"ml_exec_threshold_{ticker}",
        )

    cfg = ModelValidationConfig(
        horizon=int(horizon),
        n_splits=int(n_splits),
        transaction_cost_bps=float(cost_bps),
        long_threshold=float(threshold),
        short_threshold=float(1.0 - threshold),
        selected_models=tuple(models or ["Prior", "Logistic"]),
    )
    dataset_id = str(control_report.get("model_matrix_id") or control_report.get("dataset_id"))
    state_key = f"ml_exec_result_{_result_key(ticker, dataset_id, cfg)}"
    run = st.button(
        "Run governed champion–challenger validation",
        type="primary",
        key=f"ml_exec_run_{_result_key(ticker, dataset_id, cfg)}",
    )
    if run:
        with st.spinner("Running purged OOS validation..."):
            st.session_state[state_key] = run_ml_champion_challenger(
                labeled_df,
                feature_df,
                cfg,
                max_feature_psi=float(control_report.get("drift", {}).get("max_psi", np.inf)),
            )

    result = st.session_state.get(state_key)
    if not isinstance(result, dict):
        st.info("Run the engine to produce a fresh, dataset-bound leaderboard. No cached result is implied.")
        return
    if not result.get("ok"):
        st.error(str(result.get("reason", "Validation unavailable.")))
        errors = result.get("errors")
        if isinstance(errors, pd.DataFrame) and not errors.empty:
            st.dataframe(errors, width="stretch", hide_index=True)
        return

    leaderboard = result["leaderboard"]
    champion_row = leaderboard.loc[leaderboard["Model"] == result["champion"]].iloc[0]
    decision = result["decision"]
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Research champion", result["champion"])
    k2.metric("OOS balanced accuracy", f"{champion_row['Balanced accuracy']:.3f}")
    k3.metric("OOS Brier", f"{champion_row['Brier']:.3f}")
    k4.metric("Promotion", decision["status"].replace("_", " ").title())

    lead_tab, folds_tab, predictions_tab, uncertainty_tab, evidence_tab = st.tabs(
        ["Leaderboard", "Purged folds", "OOS predictions", "Uncertainty", "Evidence & export"]
    )
    with lead_tab:
        st.dataframe(leaderboard, width="stretch", hide_index=True, height=360)
    with folds_tab:
        st.dataframe(result["splits"], width="stretch", hide_index=True)
        st.dataframe(result["fold_metrics"], width="stretch", hide_index=True, height=330)
    with predictions_tab:
        st.dataframe(result["predictions"].tail(300), width="stretch", hide_index=True, height=420)
    with uncertainty_tab:
        st.dataframe(result["uncertainty"], width="stretch", hide_index=True)
        st.caption("Ambiguous conformal sets are abstentions, not forced trades.")
    with evidence_tab:
        checks = pd.DataFrame(
            [
                {"Control": name, "Status": "PASS" if passed else "BLOCKED"}
                for name, passed in decision["checks"].items()
            ]
        )
        st.dataframe(checks, width="stretch", hide_index=True)
        if decision["status"] == "BLOCKED":
            st.warning("Champion promotion is blocked. Research results remain shadow-only.")
        registry = LocalExperimentRegistry(".quant_terminal/ml_registry.jsonl")
        if st.button("Register ML validation result", key=f"register_ml_result_{state_key}"):
            entry = registry.append(
                {
                    "ticker": str(ticker).upper(),
                    "dataset_id": dataset_id,
                    "engine_version": result["engine_version"],
                    "champion": result["champion"],
                    "promotion": decision,
                    "leaderboard": leaderboard.to_dict(orient="records"),
                }
            )
            st.success(f"Validation registered: {entry['run_id']}")
        st.download_button(
            "Download ML leaderboard CSV",
            data=leaderboard.to_csv(index=False),
            file_name=f"{str(ticker).upper()}_ml_leaderboard.csv",
            mime="text/csv",
            key=f"download_ml_leaderboard_{state_key}",
        )
        st.download_button(
            "Download OOS predictions CSV",
            data=result["predictions"].to_csv(index=False),
            file_name=f"{str(ticker).upper()}_ml_oos_predictions.csv",
            mime="text/csv",
            key=f"download_ml_predictions_{state_key}",
        )
