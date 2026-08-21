from __future__ import annotations

import pathlib
import sys

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from monte_carlo.tail_event import assess_evt_threshold_stability
from monte_carlo.utils import _rate_delta_pp


def test_decimal_rate_delta_formats_as_percentage_points():
    assert _rate_delta_pp(-0.1149) == "-11.49 pp"
    assert _rate_delta_pp(0.085, signed=True) == "+8.50 pp"


def test_evt_threshold_stability_warns_on_shape_instability():
    stability = pd.DataFrame(
        {
            "Threshold quantile": [0.90, 0.925, 0.95, 0.975],
            "Status": ["ELIGIBLE", "ELIGIBLE", "ELIGIBLE", "ELIGIBLE"],
            "Shape xi": [0.11, 0.10, 0.094, 0.30],
            "ES 99% loss": [0.1106, 0.1106, 0.1108, 0.1098],
        }
    )
    result = assess_evt_threshold_stability(stability)
    assert result["status"] == "WARNING"
    assert result["shape_range"] > 0.15
    assert any("shape range" in reason for reason in result["reasons"])


def test_evt_threshold_stability_passes_when_local_fits_are_stable():
    stability = pd.DataFrame(
        {
            "Threshold quantile": [0.90, 0.925, 0.95, 0.975],
            "Status": ["ELIGIBLE", "ELIGIBLE", "ELIGIBLE", "WARNING"],
            "Shape xi": [0.08, 0.09, 0.10, 0.11],
            "ES 99% loss": [0.108, 0.109, 0.110, 0.111],
        }
    )
    result = assess_evt_threshold_stability(stability)
    assert result["status"] == "ELIGIBLE"
    assert result["valid_thresholds"] == 4
