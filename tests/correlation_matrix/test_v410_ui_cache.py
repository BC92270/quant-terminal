from __future__ import annotations

import ast
from pathlib import Path

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


def test_matrix_controls_have_a_focused_fragment_boundary():
    ui_path = Path(__file__).parents[2] / "correlation_matrix_section" / "correlation_intelligence_v3" / "ui.py"
    tree = ast.parse(ui_path.read_text(encoding="utf-8"))
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    matrix_tab = functions["_render_matrix_tab"]
    section = functions["render_correlation_intelligence_v3"]
    assert [ast.unparse(d) for d in matrix_tab.decorator_list] == ["_section_fragment"]
    assert section.decorator_list == []
    assert "_render_matrix_tab(bundle, ticker, int(selected_days), estimator, cfg)" in ast.unparse(section)
