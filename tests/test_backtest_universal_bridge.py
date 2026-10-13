from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile

import pandas as pd
import pytest

from backtest_institutional.universal_bridge import (
    build_universal_institutional_envelope,
)
from backtest_universal import (
    AssetClass,
    Instrument,
    SecurityMaster,
    UniversalBacktestEngine,
    UniversalEngineConfig,
)


def _run() -> (
    tuple[
        object,
        SecurityMaster,
        dict[str, pd.DataFrame],
        pd.DataFrame,
        UniversalEngineConfig,
    ]
):
    index = pd.date_range("2025-01-02", periods=6, freq="B", tz="UTC")
    bars = pd.DataFrame(
        {
            "open": [100, 101, 102, 103, 104, 105],
            "high": [101, 102, 103, 104, 105, 106],
            "low": [99, 100, 101, 102, 103, 104],
            "close": [100.5, 101.5, 102.5, 103.5, 104.5, 105.5],
            "volume": [1_000_000.0] * 6,
        },
        index=index,
    )
    instrument = Instrument(
        "SPY",
        AssetClass.ETF,
        "USD",
        instrument_id="ARCX:SPY",
        lot_size=1e-8,
        settlement_days=1,
    )
    master = SecurityMaster([instrument])
    targets = pd.DataFrame(
        {instrument.key: [0.0, 0.5, 0.5, 0.0, 0.0, 0.0]}, index=index
    )
    config = UniversalEngineConfig(
        initial_cash=100_000.0,
        commission_bps=0.0,
        spread_bps=0.0,
        slippage_bps=0.0,
        impact_bps_at_full_participation=0.0,
        fx_conversion_bps=0.0,
    )
    market = {instrument.key: bars}
    result = UniversalBacktestEngine(security_master=master, config=config).run(
        market_data=market,
        target_weights=targets,
        cash_rates={"USD": pd.Series(0.0, index=index)},
    )
    return result, master, market, targets, config


def _envelope(
    *,
    pit: bool,
    mode: str = "native",
    sandbox: bool = False,
    complete_evidence: bool = False,
):
    result, master, market, targets, config = _run()
    return build_universal_institutional_envelope(
        result=result,
        security_master=master,
        market_data=market,
        target_weights=targets,
        fx_rates={},
        cash_rates={"USD": pd.Series(0.0, index=next(iter(market.values())).index)},
        config=config,
        strategy_name="Causal target test",
        strategy_mode=mode,
        strategy_artifact={"source_sha256": "a" * 64} if mode == "python" else {},
        point_in_time_authenticated=pit,
        sandbox_attested=sandbox,
        calendar_authenticated=complete_evidence,
        execution_calibrated=complete_evidence,
        statistical_validation=(
            {
                "purged_oos_pass": True,
                "multiple_testing_pass": True,
                "scenario_resilience_pass": True,
            }
            if complete_evidence
            else None
        ),
    )


def test_bridge_fails_closed_without_point_in_time_evidence() -> None:
    envelope = _envelope(pit=False)
    assert envelope.gate["decision"] == "HOLD — DATA REQUIRED"
    assert "Point-in-time data contract" in envelope.gate["blocking_gates"]
    assert envelope.gate["automatic_production_authorization"] is False
    assert envelope.authoritative_source == "oms_execution_ledger"


def test_bridge_can_approve_research_but_never_production() -> None:
    envelope = _envelope(pit=True, complete_evidence=True)
    assert envelope.execution.status == "AVAILABLE"
    assert envelope.gate["decision"] == "RESEARCH APPROVED"
    assert envelope.gate["research_only"] is True
    assert envelope.model_card["authoritative_source"] == "oms_execution_ledger"


@pytest.mark.parametrize(
    "mode",
    [
        "python",
        "code:python",
        "code:javascript",
        "code:typescript",
        "code:cpp",
        "code:rust",
        "code:csharp",
    ],
)
def test_code_modes_require_attested_sandbox(mode: str) -> None:
    blocked = _envelope(pit=True, mode=mode, sandbox=False, complete_evidence=True)
    assert blocked.gate["decision"] == "HOLD — DATA REQUIRED"
    assert "Strategy sandbox" in blocked.gate["blocking_gates"]
    accepted = _envelope(pit=True, mode=mode, sandbox=True, complete_evidence=True)
    assert accepted.gate["decision"] == "HOLD — DATA REQUIRED"
    assert "Causal portfolio feedback" in accepted.gate["blocking_gates"]


def test_manifest_identity_and_bundle_are_complete() -> None:
    first = _envelope(pit=False)
    second = _envelope(pit=False)
    assert first.manifest.run_id == second.manifest.run_id
    inventory = first.manifest.metadata["code_inventory"]
    assert "backtest_universal/engine.py" in inventory
    assert "backtest_sdk/__init__.py" in inventory
    with ZipFile(BytesIO(first.bundle)) as archive:
        names = set(archive.namelist())
    assert {
        "manifest.json",
        "gate.json",
        "model_card.json",
        "tables/valuations.csv",
        "tables/orders.csv",
        "tables/fills.csv",
        "tables/events.csv",
        "tables/positions.csv",
        "tables/cashbook.csv",
    }.issubset(names)
