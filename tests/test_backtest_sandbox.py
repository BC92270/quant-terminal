from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pandas as pd
import pytest

from backtest_sdk import Bar, PortfolioSnapshot, Slice

from backtest_sandbox import (
    DockerStrategyRunner,
    SandboxLimits,
    StrategyLanguage,
    template_for,
    validate_source,
)
from backtest_sandbox.runtime.runner import javascript_postlude


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "backtest_sandbox" / "runtime" / "runner.py"


def _runtime(
    messages: list[dict[str, object]], timeout: int = 30
) -> tuple[int, list[dict[str, object]], str]:
    result = subprocess.run(
        [sys.executable, str(RUNTIME)],
        input="".join(json.dumps(item) + "\n" for item in messages),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    output = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    return result.returncode, output, result.stderr


def test_every_language_template_passes_its_policy() -> None:
    for language in StrategyLanguage:
        report = validate_source(template_for(language), language)
        assert report.passed, (language, report.issues)
        assert report.source_bytes > 100


def test_typescript_gateway_does_not_require_optional_initialize() -> None:
    source_without_initializer = (
        "function onSlice(ctx: any, slice: any): void { "
        "ctx.targetPercent('AAA', 1.0); }"
    )
    source_with_initializer = (
        "function initialize(ctx: any): void { ctx.state.ready = true; }\n"
        + source_without_initializer
    )

    without_initializer = javascript_postlude(
        "typescript", source_without_initializer, "on_slice"
    )
    with_initializer = javascript_postlude(
        "typescript", source_with_initializer, "on_slice"
    )

    assert "initialize(ctx);" not in without_initializer
    assert "initialize(ctx);" in with_initializer
    assert 'typeof initialize === "function"' not in without_initializer


@pytest.mark.parametrize(
    ("language", "source"),
    [
        ("python", "import os\ndef on_bar(ctx, bar):\n    os.system('id')\n"),
        (
            "javascript",
            "function onBar(ctx, bar) { require('fs').readFileSync('/etc/passwd'); }",
        ),
        ("typescript", "function onBar(ctx: any, bar: any) { process.exit(1); }"),
        ("cpp", "#include <fstream>\nvoid on_bar(Context& c, const Bar& b) {}"),
        ("rust", "fn on_bar(c: &mut Context, b: &Bar) { unsafe {} }"),
        (
            "csharp",
            'public static void OnBar(Context c, Bar b) { System.IO.File.ReadAllText("/etc/passwd"); }',
        ),
    ],
)
def test_polyglot_policy_rejects_obvious_escape_apis(
    language: str, source: str
) -> None:
    assert not validate_source(source, language).passed


def test_docker_command_enforces_the_security_boundary() -> None:
    runner = DockerStrategyRunner(
        limits=SandboxLimits(memory_mib=512, cpu_cores=0.5, pids=32),
        docker_binary="docker",
    )
    command = runner.docker_command("qt-bt-evidence")
    joined = " ".join(command)
    assert "--network=none" in command
    assert "--read-only" in command
    assert "--cap-drop=ALL" in command
    assert "--security-opt=no-new-privileges:true" in command
    assert "--user=65532:65532" in command
    assert "--pids-limit=32" in command
    assert "--memory=512m" in command
    assert "--memory-swap=512m" in command
    assert "--cpus=0.5" in command
    assert "--pull=never" in command
    assert "--ulimit=fsize=16777216:16777216" in command
    assert "--tmpfs=/tmp:rw,exec,nosuid,nodev" in joined
    assert not any("--volume" in item or item == "-v" for item in command)


def test_controller_attestation_is_signed_for_an_immutable_image(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = DockerStrategyRunner(docker_binary="docker")
    monkeypatch.setattr(runner, "image_digest", lambda: "sha256:" + "a" * 64)
    attestation = runner.attestation()
    assert attestation.passed
    assert attestation.network_disabled
    assert attestation.read_only_root
    assert attestation.no_secrets_mounted


def test_run_waits_for_the_configured_compile_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cold Rust/TypeScript compilers may legitimately need over ten seconds."""

    class _Process:
        def poll(self) -> int:
            return 0

    class _Session:
        process = _Process()
        stderr: list[str] = []

        def __init__(self) -> None:
            self.timeouts: list[float] = []

        def send(self, payload: object) -> None:
            return None

        def receive(self, timeout: float) -> dict[str, object]:
            self.timeouts.append(timeout)
            if len(self.timeouts) == 1:
                return {
                    "type": "ready",
                    "status": "PASS",
                    "compiler": "test",
                    "callback_mode": "on_slice",
                }
            if len(self.timeouts) == 2:
                return {"type": "signals", "sequence": 0, "signals": []}
            return {"type": "stopped", "status": "PASS"}

        def close(self, *, force: bool = False) -> None:
            return None

    runner = DockerStrategyRunner(
        limits=SandboxLimits(
            wall_seconds=90,
            compile_seconds=45,
            callback_seconds=5,
            max_bars=10,
        )
    )
    session = _Session()
    monkeypatch.setattr(runner, "image_digest", lambda: "sha256:" + "a" * 64)
    monkeypatch.setattr(runner, "_session", lambda: session)
    index = pd.date_range("2025-01-01", periods=1, tz="UTC")
    market = {
        "SPY": pd.DataFrame(
            {
                "open": [100.0],
                "high": [101.0],
                "low": [99.0],
                "close": [100.0],
                "volume": [1_000_000.0],
            },
            index=index,
        )
    }

    result = runner.run(
        source="def on_slice(ctx, slice):\n    pass\n",
        language=StrategyLanguage.PYTHON,
        market_data=market,
    )

    assert result.passed
    assert session.timeouts[0] > 50.0


def test_python_runtime_reveals_history_only_incrementally() -> None:
    source = """def initialize(ctx):
    ctx.state.count = 0

def on_bar(ctx, bar):
    observed = ctx.history(bar.symbol, "close", 100)
    ctx.target_percent(bar.symbol, float(len(observed)), reason_code="OBSERVED")
"""
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
        }
    ]
    for sequence, close in enumerate((100.0, 101.0, 102.0)):
        timestamp = f"2025-01-0{sequence + 1}T00:00:00+00:00"
        messages.append(
            {
                "type": "bar",
                "sequence": sequence,
                "event_time": timestamp,
                "available_at": timestamp,
                "symbol": "SPY",
                "open": close,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": 1_000_000.0,
            }
        )
    messages.append({"type": "stop"})
    code, output, stderr = _runtime(messages)
    assert code == 0, stderr
    assert output[0]["type"] == "ready"
    targets = [
        item["signals"][0]["target"] for item in output if item["type"] == "signals"
    ]
    assert targets == [1.0, 2.0, 3.0]
    assert output[-1] == {"status": "PASS", "type": "stopped"}


@pytest.mark.parametrize(
    ("language", "binary"),
    [
        (StrategyLanguage.PYTHON, "python3"),
        (StrategyLanguage.JAVASCRIPT, "node"),
        (StrategyLanguage.TYPESCRIPT, "tsc"),
        (StrategyLanguage.CPP, "g++"),
        (StrategyLanguage.RUST, "rustc"),
        (StrategyLanguage.CSHARP, "mcs"),
    ],
)
def test_installed_language_runtime_compiles_reference_template(
    language: StrategyLanguage,
    binary: str,
) -> None:
    if shutil.which(binary) is None:
        pytest.skip(f"{binary} is installed in the Docker image, not this host")
    code, output, stderr = _runtime(
        [
            {
                "type": "prepare",
                "language": language.value,
                "source": template_for(language),
                "parameters": {},
                "seed": 41,
                "compile_only": True,
                "compile_seconds": 30,
                "callback_seconds": 3,
            }
        ],
        timeout=45,
    )
    assert code == 0, stderr + repr(output)
    assert output[-1]["type"] == "compiled"
    assert output[-1]["status"] == "PASS"


@pytest.mark.parametrize("language", list(StrategyLanguage))
def test_docker_executes_every_reference_language_causally(
    language: StrategyLanguage,
) -> None:
    """The release image must execute, not merely compile, every public SDK."""
    runner = DockerStrategyRunner(
        limits=SandboxLimits(
            wall_seconds=90,
            compile_seconds=45,
            callback_seconds=5,
            memory_mib=768,
            max_bars=100,
        )
    )
    if not runner.available:
        pytest.skip("the immutable release image is not installed on this host")
    index = pd.date_range("2025-01-01", periods=5, freq="D", tz="UTC")
    market = {
        "SPY": pd.DataFrame(
            {
                "open": [100.0, 101.0, 102.0, 103.0, 104.0],
                "high": [101.0, 102.0, 103.0, 104.0, 105.0],
                "low": [99.0, 100.0, 101.0, 102.0, 103.0],
                "close": [100.0, 101.0, 102.0, 103.0, 104.0],
                "volume": [1_000_000.0] * 5,
            },
            index=index,
        ),
        "QQQ": pd.DataFrame(
            {
                "open": [200.0, 202.0, 204.0, 206.0, 208.0],
                "high": [201.0, 203.0, 205.0, 207.0, 209.0],
                "low": [199.0, 201.0, 203.0, 205.0, 207.0],
                "close": [200.0, 202.0, 204.0, 206.0, 208.0],
                "volume": [2_000_000.0] * 5,
            },
            index=index,
        ),
    }

    result = runner.run(
        source=template_for(language),
        language=language,
        market_data=market,
        parameters={"fast": 2, "slow": 3},
        seed=41,
    )

    assert result.passed
    assert result.bars_processed == 10
    assert result.slices_processed == 5
    assert result.callback_mode == "on_slice"
    assert result.signals_emitted == 10
    assert result.diagnostics["causal_streaming"] is True
    assert result.diagnostics["atomic_market_slices"] is True
    assert result.diagnostics["future_data_exposed"] is False
    assert result.attestation.network_disabled
    assert result.attestation.read_only_root
    assert result.attestation.no_secrets_mounted
    assert result.targets.iloc[-1]["SPY"] == 1.0
    assert result.targets.iloc[-1]["QQQ"] == 1.0


@pytest.mark.parametrize(
    ("language", "source"),
    [
        (
            StrategyLanguage.PYTHON,
            "def on_slice(ctx, slice):\n    ctx.target_percent('AAA', ctx.portfolio.nav_base / 1000000.0, reason_code=ctx.portfolio.source)\n",
        ),
        (
            StrategyLanguage.JAVASCRIPT,
            "function onSlice(ctx, slice) { ctx.targetPercent('AAA', ctx.portfolio.navBase / 1000000.0, ctx.portfolio.source); }",
        ),
        (
            StrategyLanguage.TYPESCRIPT,
            "function onSlice(ctx: any, slice: any): void { ctx.targetPercent('AAA', ctx.portfolio.navBase / 1000000.0, ctx.portfolio.source); }",
        ),
        (
            StrategyLanguage.CPP,
            'void initialize(Context& ctx) {}\nvoid on_slice(Context& ctx, const Slice& slice) { ctx.target_percent("AAA", ctx.portfolio.nav_base / 1000000.0, ctx.portfolio.source); }',
        ),
        (
            StrategyLanguage.RUST,
            'fn initialize(ctx: &mut Context) {}\nfn on_slice(ctx: &mut Context, slice: &Slice) { let target=ctx.portfolio.nav_base/1000000.0; let reason=ctx.portfolio.source.clone(); ctx.target_percent("AAA",target,&reason); }',
        ),
        (
            StrategyLanguage.CSHARP,
            'public static void Initialize(Context ctx) {}\npublic static void OnSlice(Context ctx, Slice slice) { ctx.TargetPercent("AAA", ctx.Portfolio.NavBase / 1000000.0, ctx.Portfolio.Source); }',
        ),
    ],
)
def test_docker_causal_runtime_receives_authoritative_portfolio_in_every_language(
    language: StrategyLanguage,
    source: str,
) -> None:
    """Protocol v3 must transport the OMS snapshot inside the OCI boundary."""

    runner = DockerStrategyRunner(
        limits=SandboxLimits(
            wall_seconds=90,
            compile_seconds=45,
            callback_seconds=5,
            memory_mib=768,
            max_bars=100,
        )
    )
    if not runner.available:
        pytest.skip("the immutable release image is not installed on this host")
    timestamp = datetime(2025, 1, 2, tzinfo=timezone.utc)
    portfolio = PortfolioSnapshot(
        available=True,
        as_of=timestamp,
        positions={
            "AAA": {
                "quantity": 10.0,
                "average_price": 9.0,
                "last_price": 10.0,
                "market_value_base": 100.0,
            }
        },
        cash={"USD": 999_900.0},
        base_currency="USD",
        nav_base=1_000_000.0,
        sequence=7,
        ledger_sha256="a" * 64,
        source="OMS_EXECUTION_LEDGER",
        reason="",
    )
    market_slice = Slice(
        event_time=timestamp,
        available_at=timestamp,
        bars={
            "AAA": Bar(
                symbol="AAA",
                event_time=timestamp,
                available_at=timestamp,
                open=10.0,
                high=11.0,
                low=9.0,
                close=10.0,
                volume=1_000.0,
            )
        },
    )

    with runner.causal_runtime(
        source=source,
        language=language,
        parameters={},
        seed=41,
    ) as runtime:
        targets = runtime.on_slice(
            portfolio=portfolio,
            market_slice=market_slice,
        )

    result = runtime.result()
    assert targets == {"AAA": 1.0}
    assert result.passed
    assert result.slices_processed == 1
    assert result.diagnostics["portfolio_feedback_connected"] is True
    assert result.diagnostics["portfolio_authority"] == "OMS_EXECUTION_LEDGER"
