from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from backtest_sandbox import (
    DockerStrategyRunner,
    SandboxLimits,
    StrategyLanguage,
    template_for,
    validate_source,
)


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
