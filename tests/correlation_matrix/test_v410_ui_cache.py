from __future__ import annotations

import numpy as np
import pandas as pd

from correlation_matrix_section.correlation_intelligence_v3.ui import _analysis_signature


def _provider_one():
    return None


def _provider_two():
    return None


def test_analysis_signature_is_deterministic_for_equivalent_inputs():
    frame = pd.DataFrame(
        {"NVDA": [100.0, 101.0], "SMH": [200.0, 202.0]},
        index=pd.to_datetime(["2026-01-02", "2026-01-05"]),
    )
    left = {
        "portfolio_weights": {"NVDA": 0.6, "SMH": 0.4},
        "provider": _provider_one,
        "scenario": np.array([0.1, -0.2]),
        "frame": frame,
    }
    right = {
        "frame": frame.copy(deep=True),
        "scenario": np.array([0.1, -0.2]),
        "provider": _provider_one,
        "portfolio_weights": {"SMH": 0.4, "NVDA": 0.6},
    }

    assert _analysis_signature(left) == _analysis_signature(right)


def test_analysis_signature_invalidates_material_engine_inputs():
    base = {
        "correlation_tail_mode": "Adaptive",
        "portfolio_weights": {"NVDA": 0.6, "SMH": 0.4},
        "provider": _provider_one,
    }

    changed_weight = {**base, "portfolio_weights": {"NVDA": 0.5, "SMH": 0.5}}
    changed_provider = {**base, "provider": _provider_two}

    assert _analysis_signature(base) != _analysis_signature(changed_weight)
    assert _analysis_signature(base) != _analysis_signature(changed_provider)
