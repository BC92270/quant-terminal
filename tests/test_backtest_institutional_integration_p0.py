from __future__ import annotations

from io import BytesIO
import json
from types import SimpleNamespace
from zipfile import ZipFile

import numpy as np
import pandas as pd
import pytest

from backtest_institutional.dashboard import (
    _EVIDENCE_METADATA,
    _canonical_evidence_manifest,
    _candidate_matrix,
    _candidate_template,
    _config_payload,
    _factor_matrix,
)
from backtest_institutional.engine import run_institutional_stack
from backtest_institutional.execution import ExecutionModelConfig
from backtest_institutional.evidence import SIGNATURE_ALGORITHM
from backtest_institutional.registry import data_hash, stable_hash
from backtest_institutional.scenarios import ScenarioConfig
from backtest_lab import (
    _align_custom_signal_to_prices,
    _custom_signal_safety_gate_v26_pack,
    _extract_ohlc,
    _extract_trades,
    _infer_periods_per_year,
    publish_backtest_owner_certificate_v1,
)


def _market(n: int = 180) -> pd.DataFrame:
    index = pd.bdate_range("2023-01-03", periods=n)
    wave = np.sin(np.linspace(0.0, 14.0, n))
    close = 100.0 * np.cumprod(1.0 + 0.0004 + 0.006 * wave)
    frame = pd.DataFrame(
        {
            "Open": close * 0.999,
            "High": close * 1.004,
            "Low": close * 0.996,
            "Close": close,
            "Volume": 5_000_000.0,
        },
        index=index,
    )
    frame.attrs["price_basis"] = "adjusted_total_return"
    frame.attrs["periods_per_year"] = 252
    frame.attrs["interval_label"] = "1d"
    return frame


def _legacy(bars: pd.DataFrame, *, fake_return: float = 0.25) -> dict[str, object]:
    exposure = pd.Series(0.0, index=bars.index)
    exposure.iloc[25:85] = 0.65
    exposure.iloc[110:160] = 0.40
    return {
        "data": pd.DataFrame(
            {
                "exposure": exposure,
                # Intentionally impossible: this must never become the V7 source.
                "strategy_return": fake_return,
                "equity": 1_000_000.0 * (1.0 + fake_return) ** np.arange(len(bars)),
            },
            index=bars.index,
        )
    }


def test_candidate_import_requires_timestamp_identity() -> None:
    index = pd.bdate_range("2024-01-02", periods=40)
    valid = pd.DataFrame(
        {
            "timestamp": index,
            "base": np.linspace(-0.01, 0.01, len(index)),
            "challenger": np.linspace(0.01, -0.01, len(index)),
        }
    )
    aligned = _candidate_matrix(BytesIO(valid.to_csv(index=False).encode()), index)
    assert aligned is not None
    assert aligned.index.equals(index)
    assert aligned.attrs["alignment"]["policy"] == "timestamp_exact_no_positional_fallback"

    positional = valid.drop(columns="timestamp")
    with pytest.raises(ValueError, match="timestamp/date column is required"):
        _candidate_matrix(BytesIO(positional.to_csv(index=False).encode()), index)

    duplicate = valid.copy()
    duplicate.loc[1, "timestamp"] = duplicate.loc[0, "timestamp"]
    with pytest.raises(ValueError, match="duplicate timestamps"):
        _candidate_matrix(BytesIO(duplicate.to_csv(index=False).encode()), index)

    hidden_abandoned = valid.copy()
    hidden_abandoned["abandoned_trial"] = np.nan
    hidden_abandoned.loc[:19, "abandoned_trial"] = 0.001
    with pytest.raises(ValueError, match="silently discarded"):
        _candidate_matrix(BytesIO(hidden_abandoned.to_csv(index=False).encode()), index)


def test_candidate_template_uses_canonical_returns_and_never_fabricates_a_trial() -> None:
    index = pd.bdate_range("2024-01-02", periods=40)
    canonical = pd.Series(np.linspace(-0.01, 0.01, len(index)), index=index)

    template = _candidate_template(index, canonical)

    assert template["timestamp"].tolist() == index.astype(str).tolist()
    np.testing.assert_allclose(template["selected"], canonical)
    assert template["candidate_A"].isna().all()


def test_config_payload_is_always_a_mapping() -> None:
    payload = _config_payload(SimpleNamespace(capital=1_000_000, custom_signal_df=pd.DataFrame()))
    assert payload == {"capital": 1_000_000}


def test_factor_import_requires_signed_per_observation_vintage_clock() -> None:
    index = pd.bdate_range("2024-01-02", periods=40)
    factors = pd.DataFrame(
        {
            "factor_A": np.linspace(-0.01, 0.01, len(index)),
            "factor_B": np.linspace(0.006, -0.004, len(index)),
        },
        index=index,
    )
    raw = pd.DataFrame({"timestamp": index.astype(str)})
    ledger_rows = []
    for factor in factors.columns:
        raw[factor] = factors[factor].to_numpy()
        raw[f"available_at__{factor}"] = index.astype(str)
        raw[f"vintage_id__{factor}"] = [f"v-{stamp.date()}" for stamp in index]
        for stamp in index:
            ledger_rows.append({
                "observation_at": pd.Timestamp(stamp).isoformat(),
                "factor": factor,
                "available_at": pd.Timestamp(stamp, tz="UTC").isoformat(),
                "vintage_id": f"v-{stamp.date()}",
            })
    vintage_ledger = pd.DataFrame(ledger_rows).sort_values(
        ["observation_at", "factor"], kind="stable", ignore_index=True
    )
    wire = pd.read_csv(BytesIO(raw.to_csv(index=False).encode()))
    wire_factors = wire[["factor_A", "factor_B"]].copy()
    wire_factors.index = index
    payload_hash = data_hash(wire_factors)
    now = pd.Timestamp.now(tz="UTC").isoformat()
    metadata = {
        "meta_schema_version": "institutional_returns_v1",
        "meta_dataset_kind": "factor_returns",
        "meta_frequency": "1d",
        "meta_periods_per_year": "252",
        "meta_return_convention": "simple",
        "meta_return_unit": "decimal",
        "meta_currency": "USD",
        "meta_net_of_costs": "false",
        "meta_evidence_id": "FACTOR-UNIT-1",
        "meta_evidence_authority": "unit-vintage-store",
        "meta_manifest_timestamp": now,
        "meta_payload_sha256": payload_hash,
        "meta_point_in_time": "true",
        "meta_source_snapshot_id": "FACTOR-SNAPSHOT-1",
        "meta_source_snapshot_sha256": payload_hash,
        "meta_market_data_snapshot_sha256": "a" * 64,
        "meta_knowledge_cutoff": now,
        "meta_revision_policy": "vintage_locked",
        "meta_vintage_ledger_sha256": data_hash(vintage_ledger),
        "meta_trial_ids_json": json.dumps({"factor_A": "fa", "factor_B": "fb"}),
        "meta_trial_config_sha256_json": json.dumps({
            "factor_A": stable_hash({"factor": "A"}),
            "factor_B": stable_hash({"factor": "B"}),
        }),
        "meta_complete_trial_ledger": "false",
        "meta_signing_key_id": "unit-control",
        "meta_signature_algorithm": SIGNATURE_ALGORITHM,
        "meta_signature_base64": "c2ln",
        "meta_manifest_sha256": "PENDING",
    }
    manifest = _canonical_evidence_manifest(
        metadata, columns=list(factors.columns), label="factor returns"
    )
    metadata["meta_manifest_sha256"] = stable_hash(manifest)
    for name in _EVIDENCE_METADATA:
        raw[name] = metadata[name]

    parsed = _factor_matrix(
        BytesIO(raw.to_csv(index=False).encode()),
        index,
        expected_frequency="1d",
        expected_periods_per_year=252,
        expected_currency="USD",
        require_metadata=True,
    )
    assert parsed is not None
    assert data_hash(parsed.attrs["factor_vintage_ledger"]) == metadata[
        "meta_vintage_ledger_sha256"
    ]

    lookahead = raw.copy()
    lookahead.loc[0, "available_at__factor_A"] = (
        index[0] + pd.Timedelta(days=1)
    ).isoformat()
    with pytest.raises(ValueError, match="available_at"):
        _factor_matrix(
            BytesIO(lookahead.to_csv(index=False).encode()),
            index,
            expected_frequency="1d",
            expected_periods_per_year=252,
            expected_currency="USD",
            require_metadata=True,
        )


def test_execution_ledger_is_the_only_performance_source() -> None:
    bars = _market()
    common = dict(
        bars=bars,
        strategy="Unit trend",
        symbol="TEST",
        config_payload={"capital": 1_000_000.0, "periods_per_year": 252, "interval_label": "1d"},
        execution_config=ExecutionModelConfig(
            model="constant",
            commission_bps=1.0,
            spread_bps=2.0,
            slippage_bps=1.0,
        ),
        scenario_config=ScenarioConfig(horizon_days=20, paths=20, seed=13),
        point_in_time=True,
        seed=13,
    )
    first = run_institutional_stack(legacy_result=_legacy(bars, fake_return=0.25), **common)
    second = run_institutional_stack(legacy_result=_legacy(bars, fake_return=-0.25), **common)

    pd.testing.assert_series_equal(first.authoritative_returns, first.execution.daily["return"])
    pd.testing.assert_series_equal(first.authoritative_returns, second.authoritative_returns)
    assert first.validation["sharpe"] == pytest.approx(second.validation["sharpe"])
    assert first.authoritative_source == "execution_ledger"
    assert first.gate["authoritative_source"] == "execution_ledger"
    with ZipFile(BytesIO(first.bundle)) as archive:
        names = set(archive.namelist())
    assert {
        "tables/market_data_input.csv",
        "tables/orders.csv",
        "tables/fills.csv",
        "artifacts/market_data_attrs.json",
        "artifacts/data_catalog_fingerprint.json",
    }.issubset(names)


def test_official_performance_changes_with_execution_costs() -> None:
    bars = _market()
    kwargs = dict(
        bars=bars,
        legacy_result=_legacy(bars, fake_return=0.10),
        strategy="Cost oracle",
        symbol="TEST",
        config_payload={"capital": 1_000_000.0, "periods_per_year": 252, "interval_label": "1d"},
        scenario_config=ScenarioConfig(horizon_days=12, paths=12, seed=5),
        point_in_time=True,
        seed=5,
    )
    free = run_institutional_stack(
        execution_config=ExecutionModelConfig(
            model="constant", commission_bps=0.0, spread_bps=0.0, slippage_bps=0.0
        ),
        **kwargs,
    )
    costly = run_institutional_stack(
        execution_config=ExecutionModelConfig(
            model="constant", commission_bps=100.0, spread_bps=100.0, slippage_bps=100.0
        ),
        **kwargs,
    )
    assert costly.execution.diagnostics["total_cost"] > free.execution.diagnostics["total_cost"]
    assert not costly.authoritative_returns.equals(free.authoritative_returns)
    assert costly.validation["sharpe"] != pytest.approx(free.validation["sharpe"])


def test_legacy_intrabar_risk_overlay_is_fail_closed_until_event_replay() -> None:
    bars = _market()
    legacy = _legacy(bars, fake_return=0.10)
    legacy_frame = legacy["data"].copy()
    event_day = bars.index[60]
    legacy_frame["risk_exit_reason"] = ""
    legacy_frame.loc[event_day, "risk_exit_reason"] = "Risk stop loss hit (-8.00%)"
    legacy["data"] = legacy_frame
    legacy["risk_events"] = pd.DataFrame([
        {
            "Trigger Date": str(event_day.date()),
            "Trigger Type": "Stop loss",
            "Effective Exit": "Same bar",
            "Fill Price": float(bars.loc[event_day, "Low"]),
        }
    ])

    stack_kwargs = dict(
        bars=bars,
        strategy="Risk-overlay oracle",
        symbol="TEST",
        config_payload={
            "capital": 1_000_000.0,
            "periods_per_year": 252,
            "interval_label": "1d",
            "risk_layer_enabled": True,
        },
        execution_config=ExecutionModelConfig(
            model="constant", commission_bps=0.0, spread_bps=0.0, slippage_bps=0.0
        ),
        scenario_config=ScenarioConfig(horizon_days=12, paths=12, seed=17),
        point_in_time=True,
        seed=17,
    )
    run = run_institutional_stack(legacy_result=legacy, **stack_kwargs)

    check = run.gate["checks"].set_index("gate").loc["Risk-order event replay"]
    assert check["state"] == "UNAVAILABLE"
    assert run.execution.diagnostics["risk_order_replay_available"] is False
    assert run.authoritative_source == "UNAVAILABLE — risk-order replay required"
    assert "Risk-order event replay" in run.gate["blocking_gates"]

    altered_legacy = dict(legacy)
    altered_legacy["data"] = legacy["data"].copy()
    altered_legacy["risk_events"] = legacy["risk_events"].copy()
    altered_legacy["risk_events"].loc[0, "Fill Price"] = 999.0
    altered_run = run_institutional_stack(legacy_result=altered_legacy, **stack_kwargs)
    assert altered_run.manifest.run_id != run.manifest.run_id
    assert altered_run.bundle != run.bundle


def test_certificate_cannot_pass_without_canonical_gate() -> None:
    base_diagnostics = {
        "oos_v2": {"level": "ROBUST", "score": 90.0},
        "pbo_proxy": 0.01,
        "dsr_proxy": 0.99,
        "custom_signal_safety_v26": {"status": "PASS"},
    }
    common = dict(
        ticker="TEST",
        cfg=SimpleNamespace(strategy="SMA Trend"),
        metrics={"Trades": 80},
        integrity=95,
        verdict="VALIDATED",
        research_label="PAPER-TEST READY",
    )
    held = publish_backtest_owner_certificate_v1(
        diagnostics=base_diagnostics,
        state={},
        **common,
    )
    assert held["status"] == "WARN"
    assert held["size_multiplier"] == 0.0

    approved = publish_backtest_owner_certificate_v1(
        diagnostics=base_diagnostics | {
            "institutional_v7": {
                "decision": "RESEARCH APPROVED",
                "run_id": "BT-ORACLE",
                "authoritative_source": "execution_ledger",
                "fail_closed": True,
                "production_authorized": False,
                "blocking_gates": [],
                "pbo": 0.10,
                "dsr": 0.98,
            }
        },
        state={},
        **common,
    )
    assert approved["status"] == "PASS"
    assert approved["production_authorized"] is False


def test_custom_signal_uses_available_at_and_blocks_uncertified_provenance() -> None:
    index = pd.bdate_range("2024-01-02", periods=12)
    signal = pd.DataFrame({
        "date": [index[1], index[5]],
        "available_at": [index[4] + pd.Timedelta(hours=14), index[7] + pd.Timedelta(hours=14)],
        "signal": [1.0, 0.0],
    })
    signal.attrs.update({
        "source_columns": ["date", "available_at", "signal"],
        "date_col": "date",
        "available_at_col": "available_at",
        "signal_col": "signal",
        "raw_rows": 2,
        "raw_invalid_dates": 0,
        "raw_invalid_available_at": 0,
    })

    aligned = _align_custom_signal_to_prices(signal, index)
    executed = aligned.shift(1).fillna(0.0)
    assert float(executed.loc[: index[4]].abs().sum()) == 0.0
    assert executed.loc[index[5]] == pytest.approx(1.0)
    safety = _custom_signal_safety_gate_v26_pack(signal, index, allow_short=False)
    assert safety["decision_gate"] == "PASS"

    no_availability = signal.drop(columns="available_at")
    no_availability.attrs = dict(signal.attrs) | {
        "source_columns": ["date", "signal"],
        "available_at_col": "",
    }
    unsafe = _custom_signal_safety_gate_v26_pack(no_availability, index, allow_short=False)
    assert unsafe["decision_gate"] == "BLOCKED"

    bars = _market()
    run = run_institutional_stack(
        bars=bars,
        legacy_result=_legacy(bars),
        strategy="Custom Signal Import",
        symbol="TEST",
        config_payload={
            "capital": 1_000_000.0,
            "periods_per_year": 252,
            "interval_label": "1d",
            "custom_signal_safety_decision": "MANUAL REVIEW",
        },
        execution_config=ExecutionModelConfig(
            model="constant", commission_bps=0.0, spread_bps=0.0, slippage_bps=0.0
        ),
        scenario_config=ScenarioConfig(horizon_days=12, paths=12, seed=19),
        point_in_time=True,
        seed=19,
    )
    provenance = run.gate["checks"].set_index("gate").loc[
        "Custom-signal availability provenance"
    ]
    assert provenance["state"] == "UNAVAILABLE"
    assert run.authoritative_source == "UNAVAILABLE — custom-signal provenance required"


def test_adjusted_ohlc_frequency_and_trade_accounting_contracts() -> None:
    index = pd.bdate_range("2024-01-02", periods=70)
    raw = pd.DataFrame(
        {
            "Open": np.linspace(90.0, 110.0, len(index)),
            "High": np.linspace(91.0, 111.0, len(index)),
            "Low": np.linspace(89.0, 109.0, len(index)),
            "Close": np.linspace(90.0, 110.0, len(index)),
            "Adj Close": np.linspace(45.0, 55.0, len(index)),
            "Volume": 1_000_000,
            "Shortable": "true",
            "Locate Available": "yes",
        },
        index=index,
    )
    raw.attrs["data_quality_issues"] = ["vendor timestamp inferred"]
    extracted = _extract_ohlc(raw)
    assert extracted.attrs["price_basis"] == "adjusted_total_return"
    assert extracted["open"].iloc[0] == pytest.approx(45.0)
    assert bool(extracted["shortable"].all())
    assert bool(extracted["locate_available"].all())
    assert "vendor timestamp inferred" in extracted.attrs["data_quality_issues"]

    weekly = pd.date_range("2024-01-05", periods=20, freq="W-FRI")
    monthly = pd.date_range("2023-01-31", periods=20, freq="ME")
    intraday = pd.date_range("2024-01-02 09:30", periods=78, freq="5min").append(
        pd.date_range("2024-01-03 09:30", periods=78, freq="5min")
    )
    assert _infer_periods_per_year(weekly) == (52, "1wk")
    assert _infer_periods_per_year(monthly) == (12, "1mo")
    assert _infer_periods_per_year(intraday) == (252 * 78, "intraday")

    bt_index = pd.bdate_range("2024-02-01", periods=5)
    bt = pd.DataFrame(
        {
            "exposure": [0.0, 0.5, 0.7, 0.4, 0.0],
            "equity": [100.0, 100.0, 101.0, 102.0, 102.0],
            "close": [10.0, 10.0, 10.1, 10.2, 10.2],
        },
        index=bt_index,
    )
    trades = _extract_trades(bt, SimpleNamespace(strategy="SMA Trend", capital=100.0))
    assert len(trades) == 1
    assert trades.iloc[0]["Status"] == "CLOSED"
    assert int(trades.iloc[0]["Rebalances"]) == 2
