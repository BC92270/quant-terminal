import numpy as np
import pandas as pd
import pyarrow as pa

from ml_lab.institutional_ui import (
    INTEGRATION_PROTOCOL,
    MODEL_CATALOG,
    compute_research_readiness,
    is_dl_protocol_compatible,
    safe_display_frame,
)
from ml_lab.deep_learning_lab import (
    INTEGRATION_PROTOCOL as DL_INTEGRATION_PROTOCOL,
    _predict_dummy_or_logistic,
)


def test_safe_display_frame_handles_mixed_arrow_columns():
    source = pd.DataFrame(
        {
            "Metric": ["coverage", "gate", "score"],
            "Value": [0.97, "Blocked", 42],
            "When": pd.to_datetime(["2026-01-01", None, "2026-01-03"]),
        }
    )

    displayed = safe_display_frame(source)

    assert source.loc[1, "Value"] == "Blocked"
    assert displayed["Value"].tolist() == ["0.97", "Blocked", "42"]
    assert displayed.loc[1, "When"] == ""
    pa.Table.from_pandas(displayed, preserve_index=False)


def test_readiness_is_explicitly_research_only_without_governance_evidence():
    rows = 300
    labels = pd.DataFrame({"tb_label": np.tile([0, 1], rows // 2)})
    features = pd.DataFrame(
        {
            "momentum": np.linspace(-1.0, 1.0, rows),
            "volatility": np.linspace(0.1, 0.3, rows),
        }
    )

    result = compute_research_readiness(labels, features, horizon=20)

    assert result["observations"] == rows
    assert result["minority_share"] == 0.5
    assert result["feature_coverage"] == 1.0
    assert result["score"] == 60
    assert result["status"] == "Controlled research"
    assert result["gates"]["Point-in-time controls"] is False
    assert result["gates"]["Locked temporal holdout"] is False


def test_triple_barrier_timeout_is_not_treated_as_directional_minority():
    labels = pd.DataFrame(
        {"tb_label": ["TP first"] * 107 + ["SL first"] * 105 + ["Timeout"] * 6}
    )

    result = compute_research_readiness(labels, pd.DataFrame({"x": np.ones(218)}), horizon=20)

    assert result["observations"] == 218
    assert result["minority_share"] == 105 / 212
    assert result["gates"]["Class balance"] is True


def test_sparse_one_class_dataset_fails_core_readiness_gates():
    labels = pd.DataFrame({"label": np.ones(40)})
    features = pd.DataFrame({"feature": [np.nan] * 40})

    result = compute_research_readiness(labels, features, horizon=20)

    assert result["score"] == 10
    assert result["status"] == "Research only"
    assert result["gates"]["Sample size"] is False
    assert result["gates"]["Class balance"] is False
    assert result["gates"]["Feature coverage"] is False


def test_protocol_contract_and_catalog_nomenclature():
    names = [row["Model"] for row in MODEL_CATALOG]

    assert INTEGRATION_PROTOCOL == DL_INTEGRATION_PROTOCOL == 2
    assert is_dl_protocol_compatible(2)
    assert is_dl_protocol_compatible("3")
    assert not is_dl_protocol_compatible(1)
    assert not is_dl_protocol_compatible("unknown")
    assert len(names) == len(set(names))
    assert {"Prior / naive", "Regularized logistic", "HistGradientBoosting", "Extra Trees"} <= set(names)


def test_native_tree_challengers_return_probabilities():
    rng = np.random.default_rng(7)
    x_train = rng.normal(size=(80, 5))
    y_train = np.tile([0, 1], 40)
    x_test = rng.normal(size=(12, 5))

    for name in ("HistGradientBoosting", "Extra Trees"):
        train_probability, test_probability, backend = _predict_dummy_or_logistic(
            name,
            x_train,
            y_train,
            x_test,
            random_state=19,
        )

        assert train_probability.shape == (80,)
        assert test_probability.shape == (12,)
        assert np.isfinite(train_probability).all()
        assert np.isfinite(test_probability).all()
        assert ((test_probability >= 0.0) & (test_probability <= 1.0)).all()
        assert backend in {"HistGradientBoostingClassifier", "ExtraTreesClassifier"}
