from __future__ import annotations

from io import BytesIO
from hashlib import sha256
import json
from types import SimpleNamespace
from zipfile import ZipFile

import numpy as np
import pandas as pd
import pytest

from correlation_matrix_section.correlation_intelligence_v3.config import CorrelationConfig
from correlation_matrix_section.correlation_intelligence_v3.data import build_quality
from correlation_matrix_section.correlation_intelligence_v3.export import research_pack_zip
from correlation_matrix_section.correlation_intelligence_v3.provenance import (
    DATAFRAME_HASH_SCHEMA,
    MANIFEST_SCHEMA_NAME,
    MANIFEST_SCHEMA_VERSION,
    dataframe_sha256,
)


def _frames(periods: int = 12) -> tuple[pd.DataFrame, pd.DataFrame]:
    index = pd.bdate_range("2025-01-02", periods=periods, name="date")
    levels = pd.DataFrame(
        {
            "AAA": 100.0 * np.exp(np.linspace(0.00, 0.11, periods)),
            "BBB": 80.0 * np.exp(np.linspace(0.00, -0.04, periods)),
        },
        index=index,
    )
    return levels, np.log(levels / levels.shift(1))


def _bundle(levels: pd.DataFrame, changes: pd.DataFrame) -> SimpleNamespace:
    empty = pd.DataFrame()
    quality = build_quality(
        levels,
        changes,
        {"AAA": "log_return", "BBB": "log_return"},
        {"AAA": "fixture-primary", "BBB": "fixture-peer"},
        "offline fixture",
        requested_period="1mo",
    )
    return SimpleNamespace(
        primary="AAA",
        selected_days=10,
        data_source="offline fixture",
        provider_map={"AAA": "fixture-primary", "BBB": "fixture-peer"},
        levels=levels,
        changes=changes,
        quality=quality,
        ranking=empty,
        term_structure=empty,
        factor_table=empty,
        tail_table=empty,
        regime_table=empty,
        stress_table=empty,
        rmt_eigen=empty,
        rmt_loadings=empty,
        mst_table=empty,
        hedges=empty,
        portfolio_table=empty,
        corr_raw=levels.corr(),
        corr_shrunk=levels.corr(),
        corr_partial=levels.corr(),
        corr_rmt_cleaned=levels.corr(),
        summary={"status": "fixture"},
    )


def test_uniformly_truncated_universe_is_not_absolute_perfect_coverage() -> None:
    # Both assets have identical history, so the former relative-only metric is 100%.
    # The request asks for two years but the fixture contains roughly one year.
    levels, changes = _frames(periods=252)
    quality = build_quality(
        levels,
        changes,
        {"AAA": "log_return", "BBB": "log_return"},
        {"AAA": "fixture", "BBB": "fixture"},
        "fixture",
        requested_period="2y",
    ).set_index("Ticker")

    assert (quality["Relative history depth %"] == 1.0).all()
    assert (quality["Observed grid coverage %"] == 1.0).all()
    assert (quality["Requested period depth %"] < 0.60).all()
    assert (quality["Coverage %"] < 0.60).all()
    assert (quality["Coverage status"] == "Backfill required").all()
    assert quality.loc["AAA", "Coverage basis"] == "min(observed grid, requested period depth)"


def test_quality_exposes_every_missing_location_without_calling_it_prehistory() -> None:
    levels, _ = _frames(periods=10)
    levels.loc[levels.index[:2], "BBB"] = np.nan
    levels.loc[levels.index[5], "BBB"] = np.nan
    levels.loc[levels.index[-2:], "BBB"] = np.nan
    changes = np.log(levels / levels.shift(1))
    row = build_quality(
        levels,
        changes,
        {"AAA": "log_return", "BBB": "log_return"},
        {"AAA": "fixture", "BBB": "fixture"},
        "fixture",
    ).set_index("Ticker").loc["BBB"]

    assert row["Total missing obs"] == 5
    assert row["Leading missing obs"] == 2
    assert row["Internal missing obs"] == 1
    assert row["Trailing missing obs"] == 2
    assert row["Observed grid coverage %"] == 0.5
    assert row["Within-history coverage %"] == pytest.approx(5 / 6)
    assert row["Coverage %"] == 0.5


def test_research_pack_manifest_hashes_and_zip_are_reproducible() -> None:
    levels, changes = _frames()
    bundle = _bundle(levels, changes)
    config = CorrelationConfig()
    metadata = {"ticker": "AAA", "selected_days": 10, "engine_version": "4.1.0"}

    first = research_pack_zip(bundle, config, metadata)
    second = research_pack_zip(bundle, config, metadata)
    assert first == second

    with ZipFile(BytesIO(first)) as archive:
        assert archive.testzip() is None
        assert "manifest.json" in archive.namelist()
        assert all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in archive.infolist())
        manifest = json.loads(archive.read("manifest.json"))
        legacy_meta = json.loads(archive.read("metadata.json"))
        levels_payload = archive.read("levels.csv")

    assert manifest["schema"] == {"name": MANIFEST_SCHEMA_NAME, "version": MANIFEST_SCHEMA_VERSION}
    assert manifest["as_of"] == levels.index.max().isoformat()
    assert manifest["shape"]["levels.csv"] == [12, 2]
    assert manifest["ranges"]["levels.csv"]["start"] == levels.index.min().isoformat()
    assert manifest["provider_map"] == {"AAA": "fixture-primary", "BBB": "fixture-peer"}
    assert manifest["transforms"] == {"AAA": "log_return", "BBB": "log_return"}
    assert manifest["hashes"]["levels.csv"] == {
        "algorithm": "sha256",
        "canonicalization": DATAFRAME_HASH_SCHEMA,
        "value": dataframe_sha256(levels),
    }
    assert manifest["hashes"]["changes.csv"]["value"] == dataframe_sha256(changes)
    assert manifest["export_artifacts"]["levels.csv"] == {
        "shape": [12, 2],
        "dataframe_sha256": dataframe_sha256(levels),
        "csv_sha256": sha256(levels_payload).hexdigest(),
        "csv_bytes": len(levels_payload),
    }
    assert manifest["archive_policy"]["ordering"].startswith("lexicographic")
    assert legacy_meta["research_manifest"] == manifest


def test_dataframe_hash_changes_on_value_change_but_not_copy() -> None:
    levels, _ = _frames()
    assert dataframe_sha256(levels) == dataframe_sha256(levels.copy(deep=True))

    changed = levels.copy(deep=True)
    changed.iloc[-1, -1] = np.nextafter(changed.iloc[-1, -1], np.inf)
    assert dataframe_sha256(changed) != dataframe_sha256(levels)
