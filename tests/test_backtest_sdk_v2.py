from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pandas as pd
import pytest

from backtest_sandbox import DockerStrategyRunner, StrategyLanguage, validate_source
from backtest_sdk import Bar, PortfolioSnapshot, SDK_CONTRACT_VERSION, Slice


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "backtest_sandbox" / "runtime" / "runner.py"
UTC = timezone.utc
T0 = datetime(2025, 1, 2, tzinfo=UTC)


def _runtime(messages: list[dict[str, object]]) -> list[dict[str, object]]:
    result = subprocess.run(
        [sys.executable, str(RUNTIME)],
        input="".join(json.dumps(item) + "\n" for item in messages),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]


def _bar(symbol: str, close: float) -> dict[str, object]:
    return {
        "event_time": T0.isoformat(),
        "available_at": T0.isoformat(),
        "symbol": symbol,
        "open": close,
        "high": close + 1.0,
        "low": close - 1.0,
        "close": close,
        "volume": 1_000.0,
    }


def test_public_slice_is_frozen_atomic_and_symbol_addressable() -> None:
    first = Bar("AAA", T0, T0, 10, 11, 9, 10.5, 100)
    second = Bar("BBB", T0, T0, 20, 21, 19, 20.5, 200)
    market_slice = Slice(T0, T0, {"BBB": second, "AAA": first})

    assert SDK_CONTRACT_VERSION == "2"
    assert market_slice.symbols == ("AAA", "BBB")
    assert market_slice["aaa"] is first
    with pytest.raises(TypeError):
        market_slice.bars["CCC"] = first  # type: ignore[index]


def test_portfolio_snapshot_never_misrepresents_unconnected_state_as_flat() -> None:
    snapshot = PortfolioSnapshot()
    assert snapshot.available is False
    assert snapshot.positions == {}
    assert snapshot.reason == "AUTHORITATIVE_PORTFOLIO_NOT_CONNECTED"


def test_python_on_slice_receives_all_simultaneous_bars_after_atomic_history_update() -> None:
    source = '''def initialize(ctx):
    ctx.state.calls = 0

def on_slice(ctx, slice):
    ctx.state.calls += 1
    for symbol, bar in slice.bars.items():
        seen = len(ctx.history(symbol, "close", 20))
        ctx.target_percent(symbol, float(seen + len(slice.bars)), reason_code="ATOMIC")
'''
    messages: list[dict[str, object]] = [
        {
            "type": "prepare",
            "language": "python",
            "source": source,
            "parameters": {},
            "seed": 41,
            "compile_only": False,
            "compile_seconds": 10,
            "callback_seconds": 3,
            "protocol_version": "quant-strategy-jsonl-2",
        },
        {
            "type": "slice",
            "sequence": 0,
            "event_time": T0.isoformat(),
            "available_at": T0.isoformat(),
            "bars": [_bar("BBB", 20.0), _bar("AAA", 10.0)],
        },
        {"type": "stop"},
    ]

    output = _runtime(messages)

    assert output[0]["callback_mode"] == "on_slice"
    signals = next(item["signals"] for item in output if item["type"] == "signals")
    assert [item["symbol"] for item in signals] == ["AAA", "BBB"]
    assert [item["target"] for item in signals] == [3.0, 3.0]


def test_controller_groups_only_identical_event_and_availability_clocks() -> None:
    same = pd.Timestamp(T0)
    later = same + pd.Timedelta(seconds=1)
    rows = [
        {**_bar("AAA", 10.0), "event_time": same, "available_at": same},
        {**_bar("BBB", 20.0), "event_time": same, "available_at": same},
        {**_bar("CCC", 30.0), "event_time": same, "available_at": later},
    ]

    slices = DockerStrategyRunner._slices(rows)

    assert [len(item["bars"]) for item in slices] == [2, 1]
    assert [bar["symbol"] for bar in slices[0]["bars"]] == ["AAA", "BBB"]


@pytest.mark.parametrize(
    ("language", "source"),
    [
        ("python", "def on_slice(ctx, slice):\n    ctx.log(str(len(slice.bars)))\n"),
        ("javascript", "function onSlice(ctx, slice) { ctx.log(String(slice.symbols.length)); }"),
        ("typescript", "function onSlice(ctx: any, slice: any): void { ctx.log(String(slice.symbols.length)); }"),
        ("cpp", "void on_slice(Context& ctx, const Slice& slice) { ctx.log(std::to_string(slice.bars.size())); }"),
        ("rust", "fn on_slice(ctx: &mut Context, slice: &Slice) { ctx.log(&slice.bars.len().to_string(), \"INFO\"); }"),
        ("csharp", "public static void OnSlice(Context ctx, Slice slice) { ctx.Log(slice.Bars.Count.ToString()); }"),
    ],
)
def test_every_language_policy_accepts_atomic_slice_entrypoint(
    language: str, source: str
) -> None:
    report = validate_source(source, StrategyLanguage.parse(language))
    assert report.passed, report.issues


@pytest.mark.parametrize(
    ("language", "binary", "source"),
    [
        (
            "python",
            "python3",
            "def on_slice(ctx, slice):\n    ctx.target_percent('AAA', 1.0, reason_code='SLICE')\n",
        ),
        (
            "javascript",
            "node",
            "function onSlice(ctx, slice) { ctx.targetPercent('AAA', 1.0, 'SLICE'); }",
        ),
        (
            "typescript",
            "tsc",
            "function onSlice(ctx: any, slice: any): void { ctx.targetPercent('AAA', 1.0, 'SLICE'); }",
        ),
        (
            "cpp",
            "g++",
            "void initialize(Context& ctx) {}\nvoid on_slice(Context& ctx, const Slice& slice) { ctx.target_percent(\"AAA\", 1.0, \"SLICE\"); }",
        ),
        (
            "rust",
            "rustc",
            "fn initialize(ctx: &mut Context) {}\nfn on_slice(ctx: &mut Context, slice: &Slice) { ctx.target_percent(\"AAA\", 1.0, \"SLICE\"); }",
        ),
        (
            "csharp",
            "mcs",
            "public static void Initialize(Context ctx) {}\npublic static void OnSlice(Context ctx, Slice slice) { ctx.TargetPercent(\"AAA\", 1.0, \"SLICE\"); }",
        ),
    ],
)
def test_installed_language_runtime_executes_atomic_slice(
    language: str, binary: str, source: str
) -> None:
    if shutil.which(binary) is None:
        pytest.skip(f"{binary} is installed in the Docker image, not this host")
    output = _runtime(
        [
            {
                "type": "prepare",
                "language": language,
                "source": source,
                "parameters": {},
                "seed": 41,
                "compile_only": False,
                "compile_seconds": 30,
                "callback_seconds": 5,
                "protocol_version": "quant-strategy-jsonl-2",
            },
            {
                "type": "slice",
                "sequence": 0,
                "event_time": T0.isoformat(),
                "available_at": T0.isoformat(),
                "bars": [_bar("BBB", 20.0), _bar("AAA", 10.0)],
            },
            {"type": "stop"},
        ]
    )
    assert output[0]["callback_mode"] == "on_slice"
    signals = next(item["signals"] for item in output if item["type"] == "signals")
    assert signals == [{"reason": "SLICE", "symbol": "AAA", "target": 1.0}]
