from __future__ import annotations

from copy import copy
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from streamlit.testing.v1 import AppTest

from market_intelligence.demo import build_workspace_snapshot
from market_intelligence.evidence import canonical_hash
from market_intelligence.patterns import (
    GateState,
    PatternBridgeState,
    PatternCandidateState,
    PatternDiscoveryConfig,
    PatternDiscoveryReport,
    PatternGate,
    PatternRunState,
    build_pattern_feature_bundle,
    build_pattern_strategy_bridge,
    causal_pattern_features,
    discover_market_patterns,
    normalize_price_history,
    pattern_report_json,
)
from market_intelligence.patterns.engine import _benjamini_yekutieli, _train_feature_manifest


def _market_frame(n: int = 320, *, start: str = "2024-01-01") -> pd.DataFrame:
    rng = np.random.default_rng(42)
    phase = np.arange(n, dtype=float)
    regime = np.sign(np.sin(phase / 14.0))
    returns = 0.0015 * regime + 0.008 * rng.normal(size=n)
    close = 100.0 * np.exp(np.cumsum(returns))
    dates = pd.date_range(start, periods=n, freq="D")
    frame = pd.DataFrame(
        {
            "date": dates,
            "open": close * (1.0 + rng.normal(0.0, 0.002, n)),
            "high": close * (1.0 + np.abs(rng.normal(0.0, 0.006, n))),
            "low": close * (1.0 - np.abs(rng.normal(0.0, 0.006, n))),
            "close": close,
            "adj_close": close,
            "volume": rng.lognormal(14.0, 0.35, n),
            "known_at": dates + pd.Timedelta(days=1),
            "revision_id": "r1",
        }
    )
    frame.attrs["data_context"] = {
        "provider": "SYNTHETIC_TEST_FIXTURE",
        "symbol": "NVDA",
        "status": "test",
        "recency": "fixed",
        "point_in_time": True,
        "known_at": "2025-01-01T00:00:00Z",
        "revision_policy": "IMMUTABLE",
        "fallback_used": False,
    }
    return frame


@pytest.fixture(scope="module")
def governed_run() -> tuple[pd.DataFrame, PatternDiscoveryReport]:
    frame = _market_frame()
    report = discover_market_patterns(frame, "NVDA", PatternDiscoveryConfig())
    return frame, report


def _rehash_legacy_report(report: PatternDiscoveryReport) -> PatternDiscoveryReport:
    content_hash = canonical_hash(report.hash_material())
    object.__setattr__(report, "content_hash", content_hash)
    object.__setattr__(report, "report_id", "MI-PAT-" + content_hash[:20].upper())
    assert report.verify_hash()
    return report


def test_price_normalization_is_deterministic_and_causal_features_have_no_targets() -> None:
    frame = _market_frame(220)
    duplicated = pd.concat([frame.iloc[::-1], frame.iloc[[20]]], ignore_index=True)
    duplicated.attrs = frame.attrs.copy()
    market, audit = normalize_price_history(duplicated, "nvda")

    assert audit.symbol == "NVDA"
    assert audit.chronological is True
    assert audit.unique_timestamps is True
    assert "INPUT_REORDERED_CHRONOLOGICALLY" in audit.quality_flags
    assert "DUPLICATE_TIMESTAMPS_DEDUPLICATED" in audit.quality_flags
    assert len(market) == len(frame)
    features = causal_pattern_features(market)
    assert features.index.is_monotonic_increasing
    assert not any(
        token in str(column).lower()
        for column in features.columns
        for token in ("forward", "future", "target", "label", "outcome")
    )


def test_feature_rows_do_not_change_when_only_a_later_bar_is_mutated() -> None:
    market, _ = normalize_price_history(_market_frame(220), "NVDA")
    original = causal_pattern_features(market)
    changed = market.copy()
    for column in ("open", "high", "low", "close", "adj_close"):
        changed.loc[changed.index[-1], column] *= 1.75
    mutated = causal_pattern_features(changed)

    assert_frame_equal(original.iloc[:-1], mutated.iloc[:-1], check_exact=True)


def test_adjusted_ohlcv_geometry_does_not_create_a_split_pattern() -> None:
    dates = pd.date_range("2024-01-01", periods=120, freq="D", tz="UTC")
    before_split = np.arange(120) < 80
    raw_close = np.where(before_split, 100.0, 10.0)
    adjustment = np.where(before_split, 0.10, 1.0)
    market = pd.DataFrame(
        {
            "open": raw_close,
            "high": raw_close * 1.02,
            "low": raw_close * 0.98,
            "close": raw_close,
            "adj_close": raw_close * adjustment,
            "volume": np.where(before_split, 1_000_000.0, 10_000_000.0),
        },
        index=dates,
    )

    features = causal_pattern_features(market)
    split_row = features.iloc[80]

    assert split_row["return_lag_0"] == pytest.approx(0.0)
    assert split_row["opening_gap"] == pytest.approx(0.0)
    assert split_row["intrabar_range"] == pytest.approx(0.04)
    assert split_row["close_location"] == pytest.approx(0.5)


def test_forward_outcome_crossing_a_split_uses_adjusted_entry_and_exit() -> None:
    n = 180
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    before_split = np.arange(n) < 80
    raw_close = np.where(before_split, 100.0, 10.0)
    adjustment = np.where(before_split, 0.10, 1.0)
    frame = pd.DataFrame(
        {
            "date": dates,
            "open": raw_close,
            "high": raw_close * 1.02,
            "low": raw_close * 0.98,
            "close": raw_close,
            "adj_close": raw_close * adjustment,
            "volume": np.where(before_split, 1_000_000.0, 10_000_000.0),
            "known_at": dates + pd.Timedelta(days=1),
            "revision_id": "r1",
        }
    )
    frame.attrs["data_context"] = {
        "provider": "SYNTHETIC_SPLIT_FIXTURE",
        "symbol": "NVDA",
        "status": "test",
        "recency": "fixed",
        "point_in_time": True,
        "known_at": "2025-01-01T00:00:00Z",
        "revision_policy": "IMMUTABLE",
        "fallback_used": False,
    }

    bundle = build_pattern_feature_bundle(frame, "NVDA", PatternDiscoveryConfig())

    # Row 78 enters at row 79 and exits at row 83, crossing the 10:1 split.
    assert bundle.forward_returns.loc[pd.Timestamp(dates[78], tz="UTC")] == pytest.approx(0.0)


def test_holdout_missingness_cannot_select_the_feature_manifest() -> None:
    config = PatternDiscoveryConfig()
    complete = build_pattern_feature_bundle(_market_frame(), "NVDA", config)
    holdout_changed_frame = _market_frame()
    holdout_changed_frame.loc[holdout_changed_frame.index[-80:], "volume"] = np.nan
    holdout_changed = build_pattern_feature_bundle(holdout_changed_frame, "NVDA", config)
    usable_rows = len(complete.features)
    holdout_rows = max(config.min_holdout_rows, int(np.ceil(usable_rows * config.holdout_fraction)))
    train_rows = usable_rows - config.horizon_bars - holdout_rows

    first = _train_feature_manifest(complete.features, train_rows)
    second = _train_feature_manifest(holdout_changed.features, train_rows)

    assert first == second
    assert "volume_robust_z_20" in first


def test_insufficient_history_fails_closed_without_fitting_or_execution() -> None:
    report = discover_market_patterns(_market_frame(90), "NVDA", PatternDiscoveryConfig())

    assert report.state == PatternRunState.WAITING_DATA
    assert report.selected_clusters is None
    assert not report.candidates
    assert not report.model_scores
    assert report.supervised_promotion_status == "NOT_RUN"
    assert report.autonomous_trading is False
    assert report.execution_allowed is False
    assert report.order_payload is None
    assert report.verify_hash()


def test_future_availability_clock_blocks_before_model_fit() -> None:
    before = pd.Timestamp.now(tz="UTC")
    future_clock = (pd.Timestamp.now(tz="UTC") + pd.Timedelta(days=2)).to_pydatetime()
    report = discover_market_patterns(
        _market_frame(),
        "NVDA",
        PatternDiscoveryConfig(),
        evaluation_clock=future_clock,
    )

    assert report.state == PatternRunState.BLOCKED_DATA_QUALITY
    assert "Future-dated availability clock" in report.reason
    assert report.selected_clusters is None
    assert not report.candidates
    assert report.execution_allowed is False
    assert before <= pd.Timestamp(report.evaluated_at) <= pd.Timestamp.now(tz="UTC")


def test_train_state_absent_from_oos_returns_a_hash_valid_quarantined_report() -> None:
    n = 500
    dates = pd.date_range("2023-01-01", periods=n, freq="D")
    rng = np.random.default_rng(0)
    returns = np.empty(n)
    for index in range(380):
        returns[index] = [0.02, -0.02, 0.001, -0.001][(index // 20) % 4] + rng.normal(
            0.0, 0.002
        )
    returns[380:] = 0.001
    close = 100.0 * np.exp(np.cumsum(returns))
    open_price = close / (1.0 + returns) * 1.0001
    frame = pd.DataFrame(
        {
            "date": dates,
            "open": open_price,
            "high": np.maximum(open_price, close) * 1.002,
            "low": np.minimum(open_price, close) * 0.998,
            "close": close,
            "adj_close": close,
            "volume": np.where(
                np.arange(n) < 380,
                1_000_000.0 * (1.0 + np.abs(returns) * 10.0),
                1_000_000.0,
            ),
            "known_at": dates + pd.Timedelta(days=1),
            "revision_id": "r1",
        }
    )
    frame.attrs["data_context"] = {
        "provider": "SYNTHETIC_REGIME_FIXTURE",
        "symbol": "NVDA",
        "status": "test",
        "recency": "fixed",
        "point_in_time": True,
        "known_at": "2026-01-01T00:00:00Z",
        "revision_policy": "IMMUTABLE",
        "fallback_used": False,
    }

    report = discover_market_patterns(
        frame,
        "NVDA",
        PatternDiscoveryConfig(selected_models=("Prior", "Logistic")),
    )

    assert report.state == PatternRunState.COMPLETED_RESEARCH_ONLY
    assert report.verify_hash()
    after_cost_gate = next(gate for gate in report.gates if gate.gate_id == "AFTER_COST_OOS")
    assert after_cost_gate.state in {GateState.PASS, GateState.WAITING_EVIDENCE}
    if any(candidate.oos_occurrences == 0 for candidate in report.candidates):
        assert after_cost_gate.state == GateState.WAITING_EVIDENCE


def test_real_discovery_uses_selection_purge_locked_oos_and_ml_challenge(
    governed_run: tuple[pd.DataFrame, PatternDiscoveryReport],
) -> None:
    _, report = governed_run

    assert report.state == PatternRunState.COMPLETED_RESEARCH_ONLY
    assert report.train_rows + report.purge_rows + report.holdout_rows == report.usable_rows
    assert report.purge_rows == report.config.horizon_bars
    assert report.holdout_rows >= report.config.min_holdout_rows
    assert report.selected_clusters is not None
    assert len(report.candidates) == report.selected_clusters
    assert report.nearest_pattern_id in {candidate.pattern_id for candidate in report.candidates}
    if report.current_assignment_status == "ASSIGNED_IN_DISTRIBUTION":
        assert report.current_pattern_id in {candidate.pattern_id for candidate in report.candidates}
    else:
        assert report.current_assignment_status == "UNASSIGNED_OOD"
        assert report.current_pattern_id is None
    assert report.supervised_champion is not None
    assert {"Prior", "Logistic"}.issubset({score.model for score in report.model_scores})
    assert any(score.model not in {"Prior", "Logistic"} for score in report.model_scores)
    assert report.supervised_promotion_status == "CLASSIFICATION_DIAGNOSTIC_ONLY"
    assert dict(report.runtime_versions)
    assert report.fit_artifact is not None
    assert report.fit_artifact.feature_names == report.feature_names
    assert len(report.fit_artifact.cluster_centers) == report.selected_clusters
    assert len(report.fit_artifact.cluster_ood_thresholds) == report.selected_clusters
    assert len(report.fit_artifact.current_scaled_features) == len(report.feature_names)
    assert len(report.fit_artifact.current_distances) == report.selected_clusters
    assert report.fit_artifact.current_nearest_distance == pytest.approx(
        min(report.fit_artifact.current_distances)
    )
    assert report.evaluated_at >= report.input_audit.source_known_at
    assert report.evaluated_at >= report.input_audit.latest_row_known_at
    assert report.verify_hash()
    assert report.execution_allowed is False
    assert all(candidate.execution_allowed is False for candidate in report.candidates)

    gates = {gate.gate_id: gate for gate in report.gates}
    assert gates["CAUSAL_FEATURES"].state == GateState.PASS
    assert gates["PURGED_LOCKED_HOLDOUT"].state == GateState.PASS
    assert gates["UNSUPERVISED_DISCOVERY"].state == GateState.PASS
    assert gates["CURRENT_STATE_OOD"].state == GateState.WAITING_EVIDENCE
    assert gates["FDR_CORRECTION"].state == GateState.WAITING_EVIDENCE
    assert gates["FULL_EXPERIMENT_CORRECTION"].state == GateState.WAITING_EVIDENCE
    assert gates["SHADOW_HISTORY"].state == GateState.WAITING_EVIDENCE
    assert gates["AUTONOMOUS_EXECUTION"].state == GateState.PASS
    for candidate in report.candidates:
        assert candidate.oos_nonoverlap_occurrences <= candidate.oos_occurrences
        if candidate.raw_p_value is not None and candidate.fdr_q_value is not None:
            assert candidate.fdr_q_value + 1e-12 >= candidate.raw_p_value
        assert candidate.state != PatternCandidateState.OOS_SUPPORTED_HYPOTHESIS


def test_dataset_identity_changes_when_the_source_values_change() -> None:
    frame = _market_frame(220)
    _, first = normalize_price_history(frame, "NVDA")
    changed = frame.copy()
    changed.attrs = frame.attrs.copy()
    changed.loc[50, "close"] *= 1.01
    _, second = normalize_price_history(changed, "NVDA")

    assert first.dataset_id != second.dataset_id

    lineage_changed = frame.copy()
    lineage_changed.attrs = frame.attrs.copy()
    lineage_changed.attrs["data_context"] = dict(frame.attrs["data_context"])
    lineage_changed.attrs["data_context"]["revision_policy"] = "as-revised"
    _, third = normalize_price_history(lineage_changed, "NVDA")
    assert first.dataset_id != third.dataset_id

    pit_changed = frame.copy()
    pit_changed.attrs = frame.attrs.copy()
    pit_changed.attrs["data_context"] = dict(frame.attrs["data_context"])
    pit_changed.attrs["data_context"]["point_in_time"] = False
    _, fourth = normalize_price_history(pit_changed, "NVDA")
    assert first.dataset_id != fourth.dataset_id

    fallback_changed = frame.copy()
    fallback_changed.attrs = frame.attrs.copy()
    fallback_changed.attrs["data_context"] = dict(frame.attrs["data_context"])
    fallback_changed.attrs["data_context"]["fallback_used"] = True
    _, fifth = normalize_price_history(fallback_changed, "NVDA")
    assert first.dataset_id != fifth.dataset_id


def test_source_subject_mismatch_blocks_discovery() -> None:
    frame = _market_frame(220)
    frame.attrs["data_context"] = dict(frame.attrs["data_context"])
    frame.attrs["data_context"]["symbol"] = "AAPL"

    _, audit = normalize_price_history(frame, "NVDA")
    report = discover_market_patterns(frame, "NVDA", PatternDiscoveryConfig())

    assert audit.source_symbol == "AAPL"
    assert audit.subject_match is False
    assert "DATASET_SUBJECT_MISMATCH" in audit.quality_flags
    assert audit.blocking_reasons
    assert report.state == PatternRunState.BLOCKED_DATA_QUALITY
    assert report.input_audit.subject_match is False


def test_missing_adjusted_close_blocks_equity_economic_evaluation() -> None:
    original = _market_frame(220)
    frame = original.drop(columns=["adj_close"])
    frame.attrs["data_context"] = dict(original.attrs["data_context"])

    _, audit = normalize_price_history(frame, "NVDA")
    report = discover_market_patterns(frame, "NVDA", PatternDiscoveryConfig())

    assert audit.adjusted_close_observed is False
    assert audit.corporate_action_safe is False
    assert "CORPORATE_ACTION_ADJUSTMENT_UNVERIFIED" in audit.quality_flags
    assert report.state == PatternRunState.BLOCKED_DATA_QUALITY


def test_synthesized_or_partial_provider_fields_cannot_masquerade_as_observed() -> None:
    frame = _market_frame(220)
    frame.loc[20, "open"] = np.nan
    frame.loc[30, "adj_close"] = np.nan
    frame.attrs["data_context"] = dict(frame.attrs["data_context"])
    frame.attrs["data_context"].update(
        {
            "market_field_provenance": {
                "open_complete": False,
                "open_synthesized": True,
                "adj_close_complete": False,
                "adj_close_synthesized": True,
            },
            "price_adjustment_policy": "UNVERIFIED_RAW_CLOSE",
        }
    )

    _, audit = normalize_price_history(frame, "NVDA")
    report = discover_market_patterns(frame, "NVDA", PatternDiscoveryConfig())

    assert audit.open_price_observed is False
    assert audit.adjusted_close_observed is False
    assert "OPEN_PRICE_NOT_OBSERVED" in audit.quality_flags
    assert "PARTIAL_ADJUSTED_CLOSE" in audit.quality_flags
    assert report.state == PatternRunState.BLOCKED_DATA_QUALITY


def test_rows_known_after_the_next_open_never_pass_pit_lineage() -> None:
    frame = _market_frame(220)
    frame["known_at"] = pd.to_datetime(frame["date"], utc=True) + pd.Timedelta(days=30)
    frame.attrs["data_context"] = dict(frame.attrs["data_context"])
    frame.attrs["data_context"]["known_at"] = "2025-12-31T00:00:00Z"

    _, audit = normalize_price_history(frame, "NVDA")
    report = discover_market_patterns(frame, "NVDA", PatternDiscoveryConfig())

    assert audit.row_lineage_complete is False
    assert audit.pit_lineage_complete is False
    assert "ROW_KNOWN_AFTER_NEXT_OPEN" in audit.quality_flags
    assert "PIT_LINEAGE_INCOMPLETE" in audit.quality_flags
    assert report.state == PatternRunState.BLOCKED_DATA_QUALITY
    assert report.selected_clusters is None


def test_rows_known_before_the_market_observation_block_model_fit() -> None:
    frame = _market_frame(220)
    frame["known_at"] = pd.to_datetime(frame["date"], utc=True) - pd.Timedelta(days=1)
    frame.attrs["data_context"] = dict(frame.attrs["data_context"])

    report = discover_market_patterns(frame, "NVDA", PatternDiscoveryConfig())

    assert report.state == PatternRunState.BLOCKED_DATA_QUALITY
    assert "ROW_KNOWN_BEFORE_OBSERVATION" in report.input_audit.quality_flags
    assert report.selected_clusters is None


def test_non_point_in_time_revision_policy_never_passes_lineage() -> None:
    frame = _market_frame(220)
    frame.attrs["data_context"] = dict(frame.attrs["data_context"])
    frame.attrs["data_context"]["revision_policy"] = "AS_REVISED"

    _, audit = normalize_price_history(frame, "NVDA")

    assert audit.row_lineage_complete is True
    assert audit.point_in_time_declared is True
    assert audit.revision_policy == "AS_REVISED"
    assert audit.pit_lineage_complete is False
    assert "PIT_LINEAGE_INCOMPLETE" in audit.quality_flags


def test_by_correction_counts_missing_hypotheses_and_arbitrary_dependence() -> None:
    corrected = _benjamini_yekutieli([0.01, None, 0.04])

    assert corrected[0] == pytest.approx(0.055)
    # Missing evidence remains undisplayed, but it still occupies its p=1
    # position in the family; the harmonic factor makes BY conservative under
    # arbitrary dependence.
    assert corrected[1] is None
    assert corrected[2] == pytest.approx(0.11)


def test_forward_outcome_enters_at_next_open_and_exits_after_horizon() -> None:
    frame = _market_frame(140)
    config = PatternDiscoveryConfig(horizon_bars=5, execution_lag_bars=1)
    bundle = build_pattern_feature_bundle(frame, "NVDA", config)
    timestamp = bundle.forward_returns.index[3]
    location = bundle.market.index.get_loc(timestamp)

    expected = (
        bundle.market["adj_close"].iloc[location + config.horizon_bars]
        / bundle.market["open"].iloc[location + config.execution_lag_bars]
        - 1.0
    )
    same_close_return = (
        bundle.market["adj_close"].iloc[location + config.horizon_bars]
        / bundle.market["adj_close"].iloc[location]
        - 1.0
    )

    assert bundle.forward_returns.loc[timestamp] == pytest.approx(expected)
    assert bundle.forward_returns.loc[timestamp] != pytest.approx(same_close_return)


def test_extreme_current_observation_is_left_unassigned_as_ood() -> None:
    frame = _market_frame()
    for column, multiplier in {
        "open": 35.0,
        "high": 50.0,
        "low": 25.0,
        "close": 40.0,
    }.items():
        frame.loc[frame.index[-1], column] *= multiplier

    report = discover_market_patterns(frame, "NVDA", PatternDiscoveryConfig())

    assert report.state == PatternRunState.COMPLETED_RESEARCH_ONLY
    assert report.current_assignment_status == "UNASSIGNED_OOD"
    assert report.current_pattern_id is None
    assert report.nearest_pattern_id in {candidate.pattern_id for candidate in report.candidates}
    assert any(gate.gate_id == "CURRENT_STATE_OOD" for gate in report.gates)


def test_completed_report_contract_rejects_a_missing_mandatory_gate(
    governed_run: tuple[pd.DataFrame, PatternDiscoveryReport],
) -> None:
    _, report = governed_run
    material = report.hash_material()
    material["gates"] = tuple(
        gate for gate in report.gates if gate.gate_id != "FULL_EXPERIMENT_CORRECTION"
    )
    content_hash = canonical_hash(material)

    with pytest.raises(ValueError, match="missing mandatory gates"):
        PatternDiscoveryReport(
            report_id="MI-PAT-" + content_hash[:20].upper(),
            content_hash=content_hash,
            **material,
        )


def test_bridge_independently_quarantines_a_legacy_report_missing_a_mandatory_gate(
    governed_run: tuple[pd.DataFrame, PatternDiscoveryReport],
) -> None:
    _, report = governed_run
    # Simulate a hash-valid legacy/deserialized object which did not pass
    # today's dataclass constructor. The bridge is a separate trust boundary.
    legacy_report = copy(report)
    object.__setattr__(
        legacy_report,
        "gates",
        tuple(gate for gate in report.gates if gate.gate_id != "INDEPENDENT_REVIEW"),
    )
    content_hash = canonical_hash(legacy_report.hash_material())
    object.__setattr__(legacy_report, "content_hash", content_hash)
    object.__setattr__(legacy_report, "report_id", "MI-PAT-" + content_hash[:20].upper())
    assert legacy_report.verify_hash()

    snapshot = replace(
        build_workspace_snapshot("NVDA"),
        as_of=report.evaluated_at + pd.Timedelta(days=1),
    )
    bridge = build_pattern_strategy_bridge(
        snapshot,
        legacy_report,
        current_dataset_id=legacy_report.input_audit.dataset_id,
        memo_id="MI-SDM-LEGACY-GATE-TEST",
    )

    assert bridge.state == PatternBridgeState.WAITING_VALIDATION
    assert bridge.admissible_for_governed_rebuild is False
    assert "missing INDEPENDENT_REVIEW" in bridge.reason


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("autonomous_trading", True),
        ("execution_allowed", True),
        ("order_payload", {"side": "BUY"}),
        ("human_review_required", False),
    ),
)
def test_bridge_independently_rejects_every_legacy_authority_mutation(
    governed_run: tuple[pd.DataFrame, PatternDiscoveryReport],
    field: str,
    value: object,
) -> None:
    _, report = governed_run
    legacy_report = copy(report)
    object.__setattr__(legacy_report, field, value)
    _rehash_legacy_report(legacy_report)
    snapshot = replace(
        build_workspace_snapshot("NVDA"),
        as_of=legacy_report.evaluated_at + pd.Timedelta(days=1),
    )

    bridge = build_pattern_strategy_bridge(
        snapshot,
        legacy_report,
        current_dataset_id=legacy_report.input_audit.dataset_id,
        memo_id="MI-SDM-AUTHORITY-TEST",
    )

    assert bridge.state == PatternBridgeState.WAITING_VALIDATION
    assert bridge.status_label == "AUTHORITY QUARANTINE"
    assert bridge.admissible_for_governed_rebuild is False


def test_bridge_rejects_candidate_execution_and_unknown_gates(
    governed_run: tuple[pd.DataFrame, PatternDiscoveryReport],
) -> None:
    _, report = governed_run
    snapshot = replace(
        build_workspace_snapshot("NVDA"),
        as_of=report.evaluated_at + pd.Timedelta(days=1),
    )

    candidate_report = copy(report)
    authority_candidate = copy(candidate_report.candidates[0])
    object.__setattr__(authority_candidate, "execution_allowed", True)
    object.__setattr__(
        candidate_report,
        "candidates",
        (authority_candidate,) + candidate_report.candidates[1:],
    )
    _rehash_legacy_report(candidate_report)
    candidate_bridge = build_pattern_strategy_bridge(
        snapshot,
        candidate_report,
        current_dataset_id=candidate_report.input_audit.dataset_id,
        memo_id="MI-SDM-CANDIDATE-AUTHORITY-TEST",
    )
    assert candidate_bridge.status_label == "AUTHORITY QUARANTINE"

    gate_report = copy(report)
    object.__setattr__(
        gate_report,
        "gates",
        gate_report.gates
        + (
            PatternGate(
                "UNRECOGNIZED_POLICY_GATE",
                GateState.FAIL,
                "A legacy extension reports an unresolved blocker.",
                "Unknown to the active bridge policy.",
                blocks_strategic_admission=True,
            ),
        ),
    )
    _rehash_legacy_report(gate_report)
    gate_bridge = build_pattern_strategy_bridge(
        snapshot,
        gate_report,
        current_dataset_id=gate_report.input_audit.dataset_id,
        memo_id="MI-SDM-UNKNOWN-GATE-TEST",
    )
    assert gate_bridge.state == PatternBridgeState.WAITING_VALIDATION
    assert "unknown UNRECOGNIZED_POLICY_GATE" in gate_bridge.reason

    claim_report = copy(report)
    unsupported_candidate = copy(claim_report.candidates[0])
    object.__setattr__(
        unsupported_candidate,
        "state",
        PatternCandidateState.OOS_SUPPORTED_HYPOTHESIS,
    )
    object.__setattr__(
        claim_report,
        "candidates",
        (unsupported_candidate,) + claim_report.candidates[1:],
    )
    _rehash_legacy_report(claim_report)
    claim_bridge = build_pattern_strategy_bridge(
        snapshot,
        claim_report,
        current_dataset_id=claim_report.input_audit.dataset_id,
        memo_id="MI-SDM-UNSUPPORTED-CLAIM-TEST",
    )
    assert claim_bridge.state == PatternBridgeState.WAITING_VALIDATION
    assert claim_bridge.status_label == "POLICY CLAIM QUARANTINE"


@pytest.mark.parametrize(
    ("audit_field", "value", "expected_status"),
    (
        ("source_identified", False, "LINEAGE QUARANTINE"),
        ("row_lineage_complete", False, "LINEAGE QUARANTINE"),
        ("open_price_observed", False, "PRICE / INPUT CONTRACT QUARANTINE"),
        ("corporate_action_safe", False, "PRICE / INPUT CONTRACT QUARANTINE"),
    ),
)
def test_bridge_recomputes_legacy_input_and_lineage_invariants(
    governed_run: tuple[pd.DataFrame, PatternDiscoveryReport],
    audit_field: str,
    value: object,
    expected_status: str,
) -> None:
    _, report = governed_run
    legacy_report = copy(report)
    legacy_audit = copy(report.input_audit)
    object.__setattr__(legacy_audit, audit_field, value)
    object.__setattr__(legacy_report, "input_audit", legacy_audit)
    _rehash_legacy_report(legacy_report)
    snapshot = replace(
        build_workspace_snapshot("NVDA"),
        as_of=report.evaluated_at + pd.Timedelta(days=1),
    )

    bridge = build_pattern_strategy_bridge(
        snapshot,
        legacy_report,
        current_dataset_id=legacy_report.input_audit.dataset_id,
        memo_id="MI-SDM-LEGACY-AUDIT-TEST",
    )

    assert bridge.state == PatternBridgeState.WAITING_LINEAGE
    assert bridge.status_label == expected_status
    assert bridge.admissible_for_governed_rebuild is False


def test_strategic_bridge_blocks_stale_tampered_future_and_incomplete_evidence(
    governed_run: tuple[pd.DataFrame, PatternDiscoveryReport],
) -> None:
    _, report = governed_run
    snapshot = build_workspace_snapshot("NVDA")

    bridge = build_pattern_strategy_bridge(
        snapshot,
        report,
        current_dataset_id=report.input_audit.dataset_id,
        memo_id="MI-SDM-TEST",
    )
    assert bridge.state in {
        PatternBridgeState.CLOCK_MISMATCH,
        PatternBridgeState.WAITING_VALIDATION,
    }
    assert bridge.admitted_to_current_memo is False
    assert bridge.capital_authority is False
    assert bridge.execution_allowed is False

    stale = build_pattern_strategy_bridge(
        snapshot,
        report,
        current_dataset_id="0" * 64,
        memo_id="MI-SDM-TEST",
    )
    assert stale.state == PatternBridgeState.STALE_DATASET

    tampered = replace(report, reason="altered after hashing")
    assert not tampered.verify_hash()
    integrity = build_pattern_strategy_bridge(
        snapshot,
        tampered,
        current_dataset_id=report.input_audit.dataset_id,
        memo_id="MI-SDM-TEST",
    )
    assert integrity.state == PatternBridgeState.WAITING_VALIDATION
    assert integrity.status_label == "REPORT INTEGRITY BLOCK"
    assert integrity.admissible_for_governed_rebuild is False
    assert integrity.admitted_to_current_memo is False
    assert integrity.capital_authority is False
    assert integrity.execution_allowed is False

    future_cutoff = snapshot.as_of + pd.Timedelta(days=1)
    future_audit = replace(
        report.input_audit,
        data_cutoff=future_cutoff,
        source_known_at=future_cutoff,
        latest_row_known_at=future_cutoff,
    )
    future_material = report.hash_material()
    future_material["input_audit"] = future_audit
    future_material["evaluated_at"] = future_cutoff
    future_hash = canonical_hash(future_material)
    future_report = PatternDiscoveryReport(
        report_id="MI-PAT-" + future_hash[:20].upper(),
        content_hash=future_hash,
        **future_material,
    )
    future = build_pattern_strategy_bridge(
        snapshot,
        future_report,
        current_dataset_id=future_audit.dataset_id,
        memo_id="MI-SDM-TEST",
    )
    assert future.state == PatternBridgeState.CLOCK_MISMATCH
    assert future.admitted_to_current_memo is False

    wall_future_cutoff = pd.Timestamp.now(tz="UTC").to_pydatetime() + pd.Timedelta(days=2)
    wall_future_audit = replace(
        report.input_audit,
        data_cutoff=wall_future_cutoff,
        source_known_at=wall_future_cutoff,
        latest_row_known_at=wall_future_cutoff,
    )
    wall_future_material = report.hash_material()
    wall_future_material["input_audit"] = wall_future_audit
    wall_future_material["evaluated_at"] = wall_future_cutoff
    wall_future_hash = canonical_hash(wall_future_material)
    wall_future_report = PatternDiscoveryReport(
        report_id="MI-PAT-" + wall_future_hash[:20].upper(),
        content_hash=wall_future_hash,
        **wall_future_material,
    )
    wall_future_snapshot = replace(
        snapshot,
        as_of=wall_future_cutoff + pd.Timedelta(days=1),
    )
    wall_future_bridge = build_pattern_strategy_bridge(
        wall_future_snapshot,
        wall_future_report,
        current_dataset_id=wall_future_audit.dataset_id,
        memo_id="MI-SDM-FUTURE-WALL-CLOCK-TEST",
    )
    assert wall_future_bridge.state == PatternBridgeState.CLOCK_MISMATCH
    assert wall_future_bridge.status_label == "FUTURE CLOCK QUARANTINE"


def test_report_export_is_canonical_and_declares_non_authority(
    governed_run: tuple[pd.DataFrame, PatternDiscoveryReport],
) -> None:
    _, report = governed_run
    payload = pattern_report_json(report)

    assert report.report_id in payload
    assert report.content_hash in payload
    assert '"content_hash_valid":true' in payload
    assert '"autonomous_trading":false' in payload
    assert '"capital_authority":false' in payload
    assert '"execution_allowed":false' in payload


def test_pattern_workspace_runs_real_engine_and_surfaces_strategic_quarantine() -> None:
    app = AppTest.from_string(
        """
import numpy as np
import pandas as pd
import streamlit as st
from market_intelligence import render_market_intelligence_lab

n = 300
rng = np.random.default_rng(42)
phase = np.arange(n, dtype=float)
returns = 0.0015 * np.sign(np.sin(phase / 14.0)) + 0.008 * rng.normal(size=n)
close = 100.0 * np.exp(np.cumsum(returns))
prices = pd.DataFrame({
    "date": pd.date_range("2024-01-01", periods=n, freq="D"),
    "open": close * (1.0 + rng.normal(0.0, 0.002, n)),
    "high": close * (1.0 + np.abs(rng.normal(0.0, 0.006, n))),
    "low": close * (1.0 - np.abs(rng.normal(0.0, 0.006, n))),
    "close": close,
    "adj_close": close,
    "volume": rng.lognormal(14.0, 0.35, n),
    "known_at": pd.date_range("2024-01-02", periods=n, freq="D"),
    "revision_id": "r1",
})
prices.attrs["data_context"] = {
    "provider": "SYNTHETIC_TEST_FIXTURE",
    "symbol": "NVDA",
    "status": "test",
    "recency": "fixed",
    "point_in_time": True,
    "known_at": "2025-01-01T00:00:00Z",
    "revision_policy": "IMMUTABLE",
    "fallback_used": False,
}
st.set_page_config(layout="wide")
render_market_intelligence_lab(ticker="NVDA", price_data=prices)
"""
    )
    app.session_state["mi_active_view"] = "patterns"
    app.session_state["mi_selected_symbol"] = "NVDA"
    app.session_state["mi_context_initialized"] = True
    app.session_state["mi_horizon"] = "30m"
    app.run(timeout=45)

    assert not app.exception
    assert app.button(key="mi_pattern_run_engine")
    app.button(key="mi_pattern_run_engine").click().run(timeout=90)
    assert not app.exception
    assert not app.error
    report = app.session_state["mi_pattern_discovery_report"]
    assert isinstance(report, PatternDiscoveryReport)
    assert report.state == PatternRunState.COMPLETED_RESEARCH_ONLY
    rendered = "\n".join(str(item.value) for item in app.markdown)
    assert "ML Pattern Discovery &amp; Strategic Evidence Lab" in rendered
    assert "NEAREST TRAINED STATE" in rendered or "CURRENT MACHINE STATE" in rendered
    assert "Current memo admission: NO" in rendered
    assert "EXECUTION DISABLED" in rendered
    assert "NOT RUN · NOT ADMITTED" not in rendered

    app.button(key="mi_desk_now").click().run(timeout=45)
    assert app.session_state["mi_active_view"] == "live"
    assert not app.exception
    rendered = "\n".join(str(item.value) for item in app.markdown)
    assert "ML pattern addendum" in rendered
    assert "QUARANTINE" in rendered
    assert "Separate session evidence · memo unchanged" in rendered

    app.button(key="mi_desk_govern").click().run(timeout=45)
    assert app.session_state["mi_active_view"] == "patterns"
    app.selectbox(key="mi_pattern_horizon_bars").set_value(10).run(timeout=45)
    assert not app.exception
    assert any("detached" in str(item.value).lower() for item in app.warning)
    rendered = "\n".join(str(item.value) for item in app.markdown)
    assert "NOT RUN · NOT ADMITTED" in rendered

    app.selectbox(key="mi_pattern_horizon_bars").set_value(5)
    app.session_state["mi_pattern_discovery_report"] = replace(report, reason="tampered")
    app.run(timeout=45)
    assert not app.exception
    assert any("content-hash" in str(item.value).lower() for item in app.error)
    rendered = "\n".join(str(item.value) for item in app.markdown)
    assert "DECISION COCKPIT" not in rendered
