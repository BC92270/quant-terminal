import numpy as np
import pandas as pd
import pytest

from ml_lab.sequence_engine import (
    SEQUENCE_MODEL_NAMES,
    SequenceFitConfig,
    build_sequence_uncertainty,
    flatten_sequence,
    predict_sequence_model,
    temporal_summary,
)


def _sequence_data(n: int = 78, lookback: int = 8, features: int = 4):
    rng = np.random.default_rng(7)
    X = rng.normal(size=(n, lookback, features))
    latent = X[:, -1, 0] + 0.55 * X[:, -4:, 1].mean(axis=1) - 0.25 * X[:, :, 2].std(axis=1)
    y = (latent > np.median(latent)).astype(int)
    return X, y


def test_full_sequence_transforms_retain_temporal_information():
    X, _ = _sequence_data(n=12)
    flat = flatten_sequence(X)
    summary = temporal_summary(X)

    assert flat.shape == (12, 8 * 4)
    assert summary.shape == (12, 6 * 4)
    np.testing.assert_allclose(flat[0, :4], X[0, 0, :])
    np.testing.assert_allclose(flat[0, -4:], X[0, -1, :])
    np.testing.assert_allclose(summary[:, :4], X[:, -1, :])


@pytest.mark.parametrize("model_name", SEQUENCE_MODEL_NAMES)
def test_sequence_models_emit_calibrated_probabilities(model_name):
    X, y = _sequence_data()
    cfg = SequenceFitConfig(
        calibration_fraction=0.20,
        minimum_calibration_rows=12,
        mlp_max_iter=32,
        ensemble_seeds=2,
    )
    train_probability, test_probability, detail = predict_sequence_model(
        model_name,
        X[:62],
        y[:62],
        X[62:],
        random_state=11,
        purge_bars=3,
        config=cfg,
    )

    assert train_probability.shape == (62,)
    assert test_probability.shape == (16,)
    assert np.isfinite(train_probability).all()
    assert np.isfinite(test_probability).all()
    assert ((test_probability >= 0.0) & (test_probability <= 1.0)).all()
    assert detail["lookback_consumed"] == X.shape[1]
    assert detail["calibration"] == "purged inner temporal temperature scaling"
    assert detail["purge_bars"] == 3


def test_split_conformal_uncertainty_is_strictly_oos():
    n = 90
    probability = np.linspace(0.05, 0.95, n)
    predictions = pd.DataFrame(
        {
            "date": pd.date_range("2025-01-01", periods=n, freq="D"),
            "model": ["Sequence MLP"] * n,
            "probability": probability,
            "y_true": (probability >= 0.5).astype(int),
        }
    )
    result = build_sequence_uncertainty(predictions, alpha=0.10)

    assert result["ok"] is True
    assert "ordered split conformal" in result["method"]
    assert not result["summary"].empty
    assert not result["rows"].empty
    row = result["summary"].iloc[0]
    assert row["calibration_rows"] < n
    assert row["evaluation_rows"] == len(result["rows"])
    assert 0.0 <= row["empirical_coverage"] <= 1.0
    assert 0.0 <= row["abstention_rate"] <= 1.0
