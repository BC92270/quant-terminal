import numpy as np
import pytest

from ml_lab.deep_learning_lab import DLExperimentConfig, _predict_tensorflow_model
from ml_lab.neural_backends import (
    TORCH_MODEL_NAMES,
    TorchSequenceConfig,
    neural_runtime_status,
    predict_torch_sequence_model,
)


def _synthetic_sequences(n=64, lookback=10, features=5):
    rng = np.random.default_rng(21)
    X = rng.normal(size=(n, lookback, features)).astype(np.float32)
    latent = X[:, -1, 0] + 0.6 * X[:, -4:, 1].mean(axis=1) - 0.2 * X[:, :, 2].std(axis=1)
    y = (latent >= np.median(latent)).astype(int)
    return X, y


def test_runtime_status_contract():
    status = neural_runtime_status()
    assert set(status) == {"pytorch", "tensorflow"}
    assert all(isinstance(value, bool) for value in status.values())


@pytest.mark.parametrize("model_name", TORCH_MODEL_NAMES)
def test_pytorch_sequence_architectures_execute(model_name):
    pytest.importorskip("torch")
    X, y = _synthetic_sequences()
    train_probability, test_probability, detail = predict_torch_sequence_model(
        model_name,
        X[:52],
        y[:52],
        X[52:],
        random_state=9,
        purge_bars=2,
        config=TorchSequenceConfig(
            epochs=2,
            batch_size=16,
            minimum_validation_rows=8,
            patience=2,
        ),
    )
    assert train_probability.shape == (52,)
    assert test_probability.shape == (12,)
    assert np.isfinite(train_probability).all()
    assert ((test_probability >= 0.0) & (test_probability <= 1.0)).all()
    assert detail["lookback_consumed"] == X.shape[1]
    assert detail["architecture"] in {"LSTM", "GRU", "Conv1D"}
    assert detail["device"] in {"cpu", "cuda"}


@pytest.mark.parametrize("model_name", ("TF LSTM", "TF GRU", "TF Conv1D"))
def test_tensorflow_sequence_architectures_execute(model_name):
    pytest.importorskip("tensorflow")
    X, y = _synthetic_sequences()
    cfg = DLExperimentConfig(
        horizon=2,
        lookback=X.shape[1],
        max_epochs=2,
        batch_size=16,
        random_state=13,
        selected_models=(model_name,),
    )
    train_probability, test_probability, backend = _predict_tensorflow_model(
        model_name,
        X[:52],
        y[:52],
        X[52:],
        cfg,
    )
    assert train_probability.shape == (52,)
    assert test_probability.shape == (12,)
    assert np.isfinite(train_probability).all()
    assert ((test_probability >= 0.0) & (test_probability <= 1.0)).all()
    assert "TensorFlow" in backend
