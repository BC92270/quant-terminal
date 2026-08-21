from datetime import datetime, timezone

import pandas as pd
import pytest

from fixed_income.contracts import (
    BasisPoints,
    DataClassification,
    DataPoint,
    Money,
    Percent,
    validate_weight_bounds,
)
from fixed_income.data.quality import inspect_frame


def test_unit_conversions_are_explicit() -> None:
    assert BasisPoints(125.0).decimal == pytest.approx(0.0125)
    assert BasisPoints(125.0).percent == pytest.approx(1.25)
    assert Percent(5.0).decimal == pytest.approx(0.05)
    assert Percent.from_decimal(0.05).value == pytest.approx(5.0)
    assert Money(10.0, "usd").currency == "USD"


def test_invalid_units_fail_closed() -> None:
    with pytest.raises(ValueError):
        BasisPoints(float("nan"))
    with pytest.raises(ValueError):
        Money(10.0, "US")


def test_data_point_enforces_publication_order() -> None:
    observation = datetime(2026, 1, 1, tzinfo=timezone.utc)
    available = datetime(2026, 1, 2, tzinfo=timezone.utc)
    point = DataPoint(
        series_id="TEST",
        value=1.0,
        observation_time=observation,
        available_time=available,
        source="unit-test",
        classification=DataClassification.OBSERVED,
        unit="bp",
    )
    assert point.available_at(datetime(2026, 1, 3, tzinfo=timezone.utc))
    with pytest.raises(ValueError):
        DataPoint(
            series_id="TEST",
            value=1.0,
            observation_time=available,
            available_time=observation,
            source="unit-test",
            classification=DataClassification.OBSERVED,
        )


def test_quality_gate_detects_duplicates_and_bad_timestamps() -> None:
    frame = pd.DataFrame(
        {
            "series": ["A", "A"],
            "observation": ["2026-01-02", "2026-01-02"],
            "available": ["2026-01-01", "not-a-date"],
            "value": [1.0, float("nan")],
        }
    )
    report = inspect_frame(
        frame,
        required_columns=["series", "observation", "available", "value"],
        unique_columns=["series", "observation"],
        finite_columns=["value"],
        observation_column="observation",
        available_column="available",
    )
    codes = {issue.code for issue in report.issues}
    assert not report.ok
    assert {"DUPLICATES", "NON_FINITE", "AVAILABLE_PARSE", "NEGATIVE_PUBLICATION_LAG"} <= codes


def test_weight_bound_validation() -> None:
    valid = validate_weight_bounds([0.0, 0.0], [0.6, 0.6])
    invalid = validate_weight_bounds([0.7, 0.4], [0.8, 0.5])
    assert valid.ok
    assert not invalid.ok
