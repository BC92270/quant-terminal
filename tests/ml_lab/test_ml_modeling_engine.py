import numpy as np
import pandas as pd

from ml_lab.modeling_engine import (
    ModelValidationConfig,
    prepare_causal_ml_dataset,
    purged_expanding_splits,
    run_ml_champion_challenger,
)


def _synthetic_market(n: int = 180):
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    phase = np.arange(n, dtype=float)
    signal = np.sin(phase / 8.0) + 0.15 * np.cos(phase / 3.0)
    features = pd.DataFrame(
        {
            "signal": signal,
            "momentum": np.r_[0.0, np.diff(signal)],
            "volatility": pd.Series(signal).rolling(8, min_periods=1).std().fillna(0.0).to_numpy(),
            "forward_return_20": np.roll(signal, -20),
        },
        index=dates,
    )
    labels = pd.DataFrame({"target": (signal > 0.0).astype(int)}, index=dates)
    return labels, features


def test_causal_dataset_quarantines_forward_features():
    labels, features = _synthetic_market()
    dataset = prepare_causal_ml_dataset(labels, features)

    assert dataset["X"].shape[0] == len(labels)
    assert "forward_return_20" in dataset["quarantined_columns"]
    assert "forward_return_20" not in dataset["feature_columns"]
    assert set(dataset["feature_columns"]) == {"signal", "momentum", "volatility"}


def test_purged_expanding_splits_are_strictly_separated():
    horizon = 5
    splits = purged_expanding_splits(
        n_rows=180,
        horizon=horizon,
        n_splits=3,
        min_train_rows=60,
        min_test_rows=20,
    )

    assert len(splits) == 3
    for split in splits:
        train_idx = split["train_index"]
        test_idx = split["test_index"]
        assert train_idx[-1] < test_idx[0]
        assert test_idx[0] - train_idx[-1] - 1 >= horizon
        assert not set(train_idx).intersection(test_idx)


def test_champion_challenger_produces_unique_oos_and_blocks_drift():
    labels, features = _synthetic_market()
    cfg = ModelValidationConfig(
        horizon=5,
        n_splits=3,
        min_train_rows=60,
        min_test_rows=20,
        selected_models=("Prior", "Logistic", "HistGradientBoosting"),
    )
    result = run_ml_champion_challenger(labels, features, cfg, max_feature_psi=0.90)

    assert result["ok"] is True
    assert not result["leaderboard"].empty
    assert not result["predictions"].empty
    assert not result["uncertainty"].empty
    assert not result["predictions"].duplicated(["Date", "Model"]).any()
    assert result["decision"]["status"] == "BLOCKED"
    assert result["decision"]["checks"]["Feature drift"] is False
    assert result["decision"]["autonomous_trading"] is False
