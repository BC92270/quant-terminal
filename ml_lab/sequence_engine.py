"""Causal full-sequence neural models and uncertainty controls for the DL lab.

The module deliberately targets the repository's guaranteed scikit-learn runtime.
Every model consumes only historical windows supplied by the purged walk-forward
runner. TensorFlow architectures remain optional extensions in the host lab.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable
import warnings

import numpy as np
import pandas as pd
from sklearn.calibration import calibration_curve
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.exceptions import ConvergenceWarning


MODULE_VERSION = "ML-SEQUENCE-ENGINE-V2.0"
SEQUENCE_MODEL_NAMES = ("Sequence MLP", "Deep MLP Ensemble", "Temporal Ensemble")


@dataclass(frozen=True)
class SequenceFitConfig:
    calibration_fraction: float = 0.20
    minimum_calibration_rows: int = 18
    mlp_max_iter: int = 180
    ensemble_seeds: int = 3


def _as_sequence(values: np.ndarray) -> np.ndarray:
    sequence = np.asarray(values, dtype=float)
    if sequence.ndim != 3:
        raise ValueError("Sequence inputs must have shape (samples, lookback, features).")
    if sequence.shape[0] == 0 or sequence.shape[1] < 2 or sequence.shape[2] < 1:
        raise ValueError("Sequence inputs need samples, at least two lags, and features.")
    return sequence


def flatten_sequence(values: np.ndarray) -> np.ndarray:
    sequence = _as_sequence(values)
    return sequence.reshape(sequence.shape[0], sequence.shape[1] * sequence.shape[2])


def temporal_summary(values: np.ndarray) -> np.ndarray:
    """Encode level, dispersion, extrema and trend without looking forward."""
    sequence = _as_sequence(values)
    n_steps = sequence.shape[1]
    time_axis = np.linspace(-1.0, 1.0, n_steps, dtype=float)
    denominator = float(np.sum(time_axis**2))
    centered = sequence - np.nanmean(sequence, axis=1, keepdims=True)
    slope = np.nansum(centered * time_axis[None, :, None], axis=1) / max(denominator, 1e-12)
    return np.concatenate(
        [
            sequence[:, -1, :],
            np.nanmean(sequence, axis=1),
            np.nanstd(sequence, axis=1),
            np.nanmin(sequence, axis=1),
            np.nanmax(sequence, axis=1),
            slope,
        ],
        axis=1,
    )


def _positive_probability(model: Any, values: np.ndarray) -> np.ndarray:
    raw = np.asarray(model.predict_proba(values), dtype=float)
    classes = np.asarray(getattr(model, "classes_", [0, 1]))
    if raw.ndim != 2:
        return np.full(len(values), 0.5, dtype=float)
    positions = np.where(classes == 1)[0]
    if positions.size == 0:
        return np.zeros(len(values), dtype=float)
    return np.clip(raw[:, int(positions[0])], 1e-6, 1.0 - 1e-6)


def _safe_pipeline(estimator: Any) -> Pipeline:
    return Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            ("model", estimator),
        ]
    )


def _make_mlp(seed: int, deep: bool, max_iter: int) -> Pipeline:
    hidden = (128, 64, 32) if deep else (96, 48, 24)
    estimator = MLPClassifier(
        hidden_layer_sizes=hidden,
        activation="relu",
        solver="adam",
        alpha=1e-3,
        batch_size=32,
        learning_rate_init=7.5e-4,
        max_iter=int(max_iter),
        early_stopping=True,
        validation_fraction=0.15,
        n_iter_no_change=12,
        random_state=int(seed),
    )
    return _safe_pipeline(estimator)


def _fit_single(
    builder: Callable[[], Any],
    train_values: np.ndarray,
    labels: np.ndarray,
    prediction_values: list[np.ndarray],
) -> list[np.ndarray]:
    labels = np.asarray(labels, dtype=int)
    if len(np.unique(labels)) < 2:
        model = DummyClassifier(strategy="prior")
    else:
        model = builder()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=ConvergenceWarning)
        model.fit(train_values, labels)
    return [_positive_probability(model, values) for values in prediction_values]


def _fit_raw_bundle(
    model_name: str,
    train_sequence: np.ndarray,
    labels: np.ndarray,
    prediction_sequences: list[np.ndarray],
    random_state: int,
    config: SequenceFitConfig,
) -> tuple[list[np.ndarray], dict[str, Any]]:
    flat_train = flatten_sequence(train_sequence)
    flat_predictions = [flatten_sequence(values) for values in prediction_sequences]

    if model_name == "Sequence MLP":
        probabilities = _fit_single(
            lambda: _make_mlp(random_state, deep=False, max_iter=config.mlp_max_iter),
            flat_train,
            labels,
            flat_predictions,
        )
        return probabilities, {
            "architecture": "full-window MLP (96, 48, 24)",
            "lookback_consumed": int(train_sequence.shape[1]),
            "members": 1,
        }

    if model_name == "Deep MLP Ensemble":
        member_predictions: list[list[np.ndarray]] = []
        for offset in range(int(config.ensemble_seeds)):
            member_predictions.append(
                _fit_single(
                    lambda offset=offset: _make_mlp(
                        random_state + 101 * offset,
                        deep=True,
                        max_iter=config.mlp_max_iter,
                    ),
                    flat_train,
                    labels,
                    flat_predictions,
                )
            )
        probabilities = [
            np.mean([member[target] for member in member_predictions], axis=0)
            for target in range(len(prediction_sequences))
        ]
        return probabilities, {
            "architecture": "deep full-window MLP ensemble (128, 64, 32)",
            "lookback_consumed": int(train_sequence.shape[1]),
            "members": int(config.ensemble_seeds),
        }

    if model_name == "Temporal Ensemble":
        last_train = train_sequence[:, -1, :]
        last_predictions = [values[:, -1, :] for values in prediction_sequences]
        summary_train = temporal_summary(train_sequence)
        summary_predictions = [temporal_summary(values) for values in prediction_sequences]

        logistic = _fit_single(
            lambda: _safe_pipeline(
                LogisticRegression(C=0.5, class_weight="balanced", max_iter=1000, random_state=random_state)
            ),
            last_train,
            labels,
            last_predictions,
        )
        tree = _fit_single(
            lambda: Pipeline(
                [
                    ("imputer", SimpleImputer(strategy="median")),
                    (
                        "model",
                        HistGradientBoostingClassifier(
                            learning_rate=0.045,
                            max_iter=180,
                            max_leaf_nodes=15,
                            min_samples_leaf=12,
                            l2_regularization=0.2,
                            random_state=random_state,
                        ),
                    ),
                ]
            ),
            summary_train,
            labels,
            summary_predictions,
        )
        neural = _fit_single(
            lambda: _make_mlp(random_state + 503, deep=False, max_iter=config.mlp_max_iter),
            flat_train,
            labels,
            flat_predictions,
        )
        probabilities = [
            np.clip(0.20 * logistic[i] + 0.30 * tree[i] + 0.50 * neural[i], 1e-6, 1.0 - 1e-6)
            for i in range(len(prediction_sequences))
        ]
        return probabilities, {
            "architecture": "last-step logistic + temporal-stat tree + full-window MLP",
            "lookback_consumed": int(train_sequence.shape[1]),
            "members": 3,
            "weights": {"logistic": 0.20, "tree": 0.30, "sequence_mlp": 0.50},
        }

    raise ValueError(f"Unsupported sequence model: {model_name}")


def fit_temperature(labels: np.ndarray, probabilities: np.ndarray) -> float:
    labels = np.asarray(labels, dtype=float)
    probabilities = np.clip(np.asarray(probabilities, dtype=float), 1e-6, 1.0 - 1e-6)
    if len(labels) < 8 or len(np.unique(labels)) < 2:
        return 1.0
    logits = np.log(probabilities / (1.0 - probabilities))
    candidates = np.exp(np.linspace(np.log(0.25), np.log(4.0), 121))
    losses = []
    for temperature in candidates:
        calibrated = 1.0 / (1.0 + np.exp(-np.clip(logits / temperature, -35.0, 35.0)))
        loss = -np.mean(labels * np.log(calibrated) + (1.0 - labels) * np.log(1.0 - calibrated))
        losses.append(float(loss))
    return float(candidates[int(np.argmin(losses))])


def apply_temperature(probabilities: np.ndarray, temperature: float) -> np.ndarray:
    probabilities = np.clip(np.asarray(probabilities, dtype=float), 1e-6, 1.0 - 1e-6)
    logits = np.log(probabilities / (1.0 - probabilities))
    calibrated = 1.0 / (1.0 + np.exp(-np.clip(logits / max(float(temperature), 1e-3), -35.0, 35.0)))
    return np.clip(calibrated, 1e-6, 1.0 - 1e-6)


def predict_sequence_model(
    model_name: str,
    X_train_sequence: np.ndarray,
    y_train: np.ndarray,
    X_test_sequence: np.ndarray,
    random_state: int = 42,
    purge_bars: int = 20,
    config: SequenceFitConfig | None = None,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Fit a causal full-window model with purged inner temporal calibration."""
    config = config or SequenceFitConfig()
    X_train_sequence = _as_sequence(X_train_sequence)
    X_test_sequence = _as_sequence(X_test_sequence)
    y_train = np.asarray(y_train, dtype=int)
    if len(X_train_sequence) != len(y_train):
        raise ValueError("Training sequences and labels must have equal length.")

    calibration_rows = max(
        int(config.minimum_calibration_rows),
        int(np.ceil(len(y_train) * float(config.calibration_fraction))),
    )
    fit_end = len(y_train) - calibration_rows - max(1, int(purge_bars))
    temperature = 1.0
    calibration_rows_used = 0
    if fit_end >= 40 and len(np.unique(y_train[:fit_end])) >= 2:
        calibration_start = fit_end + max(1, int(purge_bars))
        raw_calibration, _ = _fit_raw_bundle(
            model_name,
            X_train_sequence[:fit_end],
            y_train[:fit_end],
            [X_train_sequence[calibration_start:]],
            int(random_state) + 17,
            config,
        )
        if len(raw_calibration[0]) >= 8:
            temperature = fit_temperature(y_train[calibration_start:], raw_calibration[0])
            calibration_rows_used = int(len(raw_calibration[0]))

    raw, detail = _fit_raw_bundle(
        model_name,
        X_train_sequence,
        y_train,
        [X_train_sequence, X_test_sequence],
        int(random_state),
        config,
    )
    train_probability = apply_temperature(raw[0], temperature)
    test_probability = apply_temperature(raw[1], temperature)
    detail.update(
        {
            "engine_version": MODULE_VERSION,
            "calibration": "purged inner temporal temperature scaling",
            "temperature": float(temperature),
            "calibration_rows": int(calibration_rows_used),
            "purge_bars": int(max(1, int(purge_bars))),
        }
    )
    return train_probability, test_probability, detail


def expected_calibration_error(labels: np.ndarray, probabilities: np.ndarray, bins: int = 10) -> float:
    labels = np.asarray(labels, dtype=int)
    probabilities = np.clip(np.asarray(probabilities, dtype=float), 0.0, 1.0)
    if len(labels) == 0:
        return float("nan")
    edges = np.linspace(0.0, 1.0, int(bins) + 1)
    total = float(len(labels))
    error = 0.0
    for lower, upper in zip(edges[:-1], edges[1:]):
        mask = (probabilities >= lower) & (probabilities < upper if upper < 1.0 else probabilities <= upper)
        if np.any(mask):
            error += float(np.sum(mask)) / total * abs(float(np.mean(probabilities[mask])) - float(np.mean(labels[mask])))
    return float(error)


def _split_conformal_sets(
    calibration_labels: np.ndarray,
    calibration_probability: np.ndarray,
    test_probability: np.ndarray,
    alpha: float = 0.10,
) -> tuple[pd.DataFrame, float]:
    labels = np.asarray(calibration_labels, dtype=int)
    cal_probability = np.clip(np.asarray(calibration_probability, dtype=float), 0.0, 1.0)
    test_probability = np.clip(np.asarray(test_probability, dtype=float), 0.0, 1.0)
    true_probability = np.where(labels == 1, cal_probability, 1.0 - cal_probability)
    scores = 1.0 - true_probability
    n = len(scores)
    rank = min(n, int(np.ceil((n + 1) * (1.0 - float(alpha)))))
    qhat = float(np.sort(scores)[max(0, rank - 1)])
    include_zero = test_probability <= qhat
    include_one = (1.0 - test_probability) <= qhat
    sets = np.where(
        include_zero & include_one,
        "{0,1}",
        np.where(include_zero, "{0}", np.where(include_one, "{1}", "{}")),
    )
    return pd.DataFrame(
        {
            "prediction_set": sets,
            "set_size": include_zero.astype(int) + include_one.astype(int),
            "abstain": (include_zero.astype(int) + include_one.astype(int)) != 1,
        }
    ), qhat


def build_sequence_uncertainty(predictions: pd.DataFrame, alpha: float = 0.10) -> dict[str, Any]:
    """Create strictly ordered split-conformal evidence from OOS predictions."""
    required = {"model", "y_true", "probability"}
    if predictions is None or predictions.empty or not required.issubset(predictions.columns):
        return {"ok": False, "reason": "No compatible OOS predictions.", "summary": pd.DataFrame(), "rows": pd.DataFrame()}

    all_rows: list[pd.DataFrame] = []
    summaries: list[dict[str, Any]] = []
    for model_name, group in predictions.groupby("model", sort=False):
        ordered = group.sort_values("date" if "date" in group.columns else group.index.name or "model").reset_index(drop=True)
        calibration_rows = max(20, int(np.floor(len(ordered) * 0.40)))
        if len(ordered) - calibration_rows < 12:
            continue
        calibration = ordered.iloc[:calibration_rows]
        evaluation = ordered.iloc[calibration_rows:].copy()
        sets, qhat = _split_conformal_sets(
            calibration["y_true"].to_numpy(dtype=int),
            calibration["probability"].to_numpy(dtype=float),
            evaluation["probability"].to_numpy(dtype=float),
            alpha=float(alpha),
        )
        evaluation = pd.concat([evaluation.reset_index(drop=True), sets], axis=1)
        truth = evaluation["y_true"].to_numpy(dtype=int)
        covered = np.where(
            truth == 1,
            evaluation["prediction_set"].isin(["{1}", "{0,1}"]),
            evaluation["prediction_set"].isin(["{0}", "{0,1}"]),
        )
        evaluation["covered"] = covered
        evaluation["conformal_qhat"] = qhat
        all_rows.append(evaluation)
        summaries.append(
            {
                "model": model_name,
                "calibration_rows": int(calibration_rows),
                "evaluation_rows": int(len(evaluation)),
                "target_coverage": float(1.0 - alpha),
                "empirical_coverage": float(np.mean(covered)),
                "abstention_rate": float(evaluation["abstain"].mean()),
                "singleton_rate": float((evaluation["set_size"] == 1).mean()),
                "brier": float(brier_score_loss(truth, evaluation["probability"])),
                "ece": expected_calibration_error(truth, evaluation["probability"].to_numpy(dtype=float)),
                "qhat": float(qhat),
            }
        )
    summary = pd.DataFrame(summaries)
    rows = pd.concat(all_rows, ignore_index=True) if all_rows else pd.DataFrame()
    return {
        "ok": not summary.empty,
        "reason": "" if not summary.empty else "Insufficient ordered OOS rows for conformal evaluation.",
        "summary": summary,
        "rows": rows,
        "alpha": float(alpha),
        "method": "ordered split conformal; first 40% calibration, remaining 60% evaluation",
    }


def render_sequence_uncertainty(uncertainty: dict[str, Any]) -> None:
    import streamlit as st

    st.markdown("#### Calibrated uncertainty")
    st.caption(
        "Split-conformal prediction sets are fitted only on the earliest OOS block. "
        "A singleton is actionable; {0,1} forces abstention."
    )
    if not uncertainty.get("ok"):
        st.info(str(uncertainty.get("reason", "Insufficient OOS evidence.")))
        return

    summary = uncertainty["summary"].copy()
    st.dataframe(
        summary.style.format(
            {
                "target_coverage": "{:.1%}",
                "empirical_coverage": "{:.1%}",
                "abstention_rate": "{:.1%}",
                "singleton_rate": "{:.1%}",
                "brier": "{:.4f}",
                "ece": "{:.4f}",
                "qhat": "{:.4f}",
            }
        ),
        use_container_width=True,
        hide_index=True,
    )
    st.download_button(
        "Download uncertainty evidence",
        data=uncertainty["rows"].to_csv(index=False).encode("utf-8"),
        file_name="dl_conformal_uncertainty.csv",
        mime="text/csv",
        use_container_width=True,
    )
