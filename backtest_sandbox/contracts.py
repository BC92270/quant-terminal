"""Versioned contracts shared by the Backtest Lab sandbox controller."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from hashlib import sha256
import json
from typing import Any, Mapping

import pandas as pd

from backtest_universal.strategy import SandboxAttestation


LEGACY_SANDBOX_PROTOCOL_VERSION = "quant-strategy-jsonl-1"
PORTFOLIOLESS_SANDBOX_PROTOCOL_VERSION = "quant-strategy-jsonl-2"
SANDBOX_PROTOCOL_VERSION = "quant-strategy-jsonl-3"
SUPPORTED_SANDBOX_PROTOCOL_VERSIONS = (
    LEGACY_SANDBOX_PROTOCOL_VERSION,
    PORTFOLIOLESS_SANDBOX_PROTOCOL_VERSION,
    SANDBOX_PROTOCOL_VERSION,
)
SANDBOX_POLICY_VERSION = "polyglot-policy-2"


class StrategyLanguage(str, Enum):
    PYTHON = "python"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    CPP = "cpp"
    RUST = "rust"
    CSHARP = "csharp"

    @property
    def label(self) -> str:
        return {
            self.PYTHON: "Python 3",
            self.JAVASCRIPT: "JavaScript",
            self.TYPESCRIPT: "TypeScript",
            self.CPP: "C++20",
            self.RUST: "Rust",
            self.CSHARP: "C#",
        }[self]

    @property
    def extension(self) -> str:
        return {
            self.PYTHON: ".py",
            self.JAVASCRIPT: ".js",
            self.TYPESCRIPT: ".ts",
            self.CPP: ".cpp",
            self.RUST: ".rs",
            self.CSHARP: ".cs",
        }[self]

    @classmethod
    def parse(cls, value: str | "StrategyLanguage") -> "StrategyLanguage":
        if isinstance(value, cls):
            return value
        normalized = str(value).strip().lower().replace(" ", "")
        aliases = {
            "py": cls.PYTHON,
            "python3": cls.PYTHON,
            "js": cls.JAVASCRIPT,
            "node": cls.JAVASCRIPT,
            "ts": cls.TYPESCRIPT,
            "c++": cls.CPP,
            "cpp20": cls.CPP,
            "rs": cls.RUST,
            "c#": cls.CSHARP,
            "cs": cls.CSHARP,
            "dotnet": cls.CSHARP,
        }
        if normalized in aliases:
            return aliases[normalized]
        return cls(normalized)


def canonical_json(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str
    )


def stable_sha256(value: Any) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SandboxLimits:
    wall_seconds: int = 120
    compile_seconds: int = 30
    callback_seconds: int = 5
    memory_mib: int = 768
    cpu_cores: float = 1.0
    pids: int = 64
    tmp_mib: int = 256
    output_mib: int = 16
    max_bars: int = 2_000_000
    max_source_kib: int = 128

    def __post_init__(self) -> None:
        integer_ranges = {
            "wall_seconds": (1, 900),
            "compile_seconds": (1, 180),
            "callback_seconds": (1, 60),
            "memory_mib": (128, 4096),
            "pids": (8, 256),
            "tmp_mib": (32, 2048),
            "output_mib": (1, 128),
            "max_bars": (1, 10_000_000),
            "max_source_kib": (1, 512),
        }
        for name, (low, high) in integer_ranges.items():
            value = int(getattr(self, name))
            if not low <= value <= high:
                raise ValueError(f"{name} must be between {low} and {high}")
        if not 0.10 <= float(self.cpu_cores) <= 8.0:
            raise ValueError("cpu_cores must be between 0.10 and 8.0")

    def evidence(self) -> dict[str, int | float]:
        return asdict(self)


@dataclass(frozen=True)
class CompileResult:
    status: str
    language: StrategyLanguage
    source_sha256: str
    image_digest: str = ""
    compiler: str = ""
    duration_ms: int = 0
    diagnostics: tuple[str, ...] = ()
    protocol_version: str = SANDBOX_PROTOCOL_VERSION

    @property
    def passed(self) -> bool:
        return self.status == "PASS"


@dataclass
class SandboxRunResult:
    status: str
    language: StrategyLanguage
    source_sha256: str
    targets: pd.DataFrame
    target_available_at: pd.Series
    attestation: SandboxAttestation
    image_digest: str
    compiler: str
    duration_ms: int
    bars_processed: int
    signals_emitted: int
    slices_processed: int = 0
    callback_mode: str = "on_bar"
    logs: tuple[Mapping[str, Any], ...] = ()
    diagnostics: Mapping[str, Any] = field(default_factory=dict)
    signature: str = ""
    public_key: str = ""
    signed_payload_sha256: str = ""

    @property
    def passed(self) -> bool:
        return self.status == "PASS" and self.attestation.passed

    def evidence(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "language": self.language.value,
            "source_sha256": self.source_sha256,
            "image_digest": self.image_digest,
            "compiler": self.compiler,
            "duration_ms": int(self.duration_ms),
            "bars_processed": int(self.bars_processed),
            "slices_processed": int(self.slices_processed),
            "signals_emitted": int(self.signals_emitted),
            "callback_mode": str(self.callback_mode),
            "diagnostics": dict(self.diagnostics),
            "signature": self.signature,
            "public_key": self.public_key,
            "signed_payload_sha256": self.signed_payload_sha256,
            "protocol_version": SANDBOX_PROTOCOL_VERSION,
        }
