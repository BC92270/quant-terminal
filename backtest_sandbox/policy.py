"""Defense-in-depth source policies for every supported strategy language.

These checks improve diagnostics and reject obvious escape primitives.  They
are not the security boundary: untrusted code is still accepted only by the
locked-down Docker runner.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import re

from backtest_universal.strategy import validate_strategy_source

from .contracts import SANDBOX_POLICY_VERSION, StrategyLanguage


MAX_SOURCE_BYTES = 128 * 1024


@dataclass(frozen=True)
class PolyglotPolicyReport:
    status: str
    language: StrategyLanguage
    policy_version: str
    source_sha256: str
    source_bytes: int
    issues: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return self.status == "PASS"


_COMMON_FORBIDDEN = (
    (
        r"\b(?:fork|execve|system|popen|spawn|shell_exec)\b",
        "process execution is forbidden",
    ),
    (
        r"\b(?:socket|websocket|fetch|XMLHttpRequest|HttpClient|TcpClient|UdpClient)\b",
        "network access is forbidden",
    ),
    (r"(?:/etc/|/proc/|/sys/|\.\./)", "filesystem escape path is forbidden"),
)

_RULES: dict[StrategyLanguage, tuple[tuple[str, str], ...]] = {
    StrategyLanguage.JAVASCRIPT: (
        (r"\b(?:require|import|export)\b", "module loading is forbidden"),
        (
            r"\b(?:process|Deno|Bun|child_process|fs|net|http|https|worker_threads)\b",
            "host runtime APIs are forbidden",
        ),
        (r"\b(?:eval|Function)\s*\(", "dynamic code evaluation is forbidden"),
        (r"\bconsole\s*\.", "use ctx.log instead of console output"),
    ),
    StrategyLanguage.TYPESCRIPT: (
        (r"\b(?:require|import|export)\b", "module loading is forbidden"),
        (
            r"\b(?:process|Deno|Bun|child_process|fs|net|http|https|worker_threads)\b",
            "host runtime APIs are forbidden",
        ),
        (r"\b(?:eval|Function)\s*\(", "dynamic code evaluation is forbidden"),
        (r"\bconsole\s*\.", "use ctx.log instead of console output"),
    ),
    StrategyLanguage.CPP: (
        (r"^\s*#\s*(?:include|import|pragma)", "preprocessor directives are forbidden"),
        (
            r"\b(?:fstream|ifstream|ofstream|filesystem|dlopen|dlsym|asm)\b",
            "filesystem or native escape API is forbidden",
        ),
        (
            r"\b(?:printf|puts|std::cout|std::cerr)\b",
            "use ctx.log instead of direct output",
        ),
    ),
    StrategyLanguage.RUST: (
        (
            r"\b(?:extern\s+crate|unsafe|include!|include_bytes!|include_str!)\b",
            "unsafe or external loading is forbidden",
        ),
        (r"\bstd::(?:fs|net|process|thread)\b", "host runtime APIs are forbidden"),
        (
            r"\b(?:println|eprintln|print|eprint)!",
            "use ctx.log instead of direct output",
        ),
    ),
    StrategyLanguage.CSHARP: (
        (
            r"^\s*using\s+(?:System\.)?(?:IO|Net|Diagnostics|Reflection|Runtime\.InteropServices)",
            "host namespaces are forbidden",
        ),
        (
            r"\b(?:File|Directory|Process|Socket|WebClient|DllImport|Assembly)\b",
            "host runtime APIs are forbidden",
        ),
        (r"\bConsole\s*\.", "use ctx.Log instead of direct output"),
    ),
    StrategyLanguage.PYTHON: (),
}

_ENTRYPOINTS: dict[StrategyLanguage, tuple[str, ...]] = {
    StrategyLanguage.JAVASCRIPT: (r"\bfunction\s+(?:onSlice|onBar)\s*\(",),
    StrategyLanguage.TYPESCRIPT: (r"\bfunction\s+(?:onSlice|onBar)\s*\(",),
    StrategyLanguage.CPP: (r"\bvoid\s+(?:on_slice|on_bar)\s*\(",),
    StrategyLanguage.RUST: (r"\bfn\s+(?:on_slice|on_bar)\s*\(",),
    StrategyLanguage.CSHARP: (r"\b(?:static\s+)?void\s+(?:OnSlice|OnBar)\s*\(",),
}


def validate_source(
    source: str, language: str | StrategyLanguage
) -> PolyglotPolicyReport:
    lang = StrategyLanguage.parse(language)
    raw = str(source or "")
    encoded = raw.encode("utf-8")
    digest = sha256(encoded).hexdigest()
    if lang is StrategyLanguage.PYTHON:
        report = validate_strategy_source(raw)
        issues = list(report.issues)
        if len(encoded) > MAX_SOURCE_BYTES and not any(
            "128 KiB" in item for item in issues
        ):
            issues.append("source exceeds 128 KiB")
        return PolyglotPolicyReport(
            "PASS" if not issues else "POLICY_REJECTED",
            lang,
            SANDBOX_POLICY_VERSION,
            digest,
            len(encoded),
            tuple(issues),
        )

    issues: list[str] = []
    if not raw.strip():
        issues.append("source is empty")
    if len(encoded) > MAX_SOURCE_BYTES:
        issues.append("source exceeds 128 KiB")
    if "\x00" in raw:
        issues.append("NUL bytes are forbidden")
    for pattern, message in (*_COMMON_FORBIDDEN, *_RULES[lang]):
        if re.search(pattern, raw, flags=re.IGNORECASE | re.MULTILINE):
            issues.append(message)
    for pattern in _ENTRYPOINTS.get(lang, ()):
        if not re.search(pattern, raw, flags=re.MULTILINE):
            issues.append("required on_slice/onSlice or on_bar/onBar entrypoint is missing")
    if len(raw.splitlines()) > 10_000:
        issues.append("source exceeds 10,000 lines")
    unique = tuple(dict.fromkeys(issues))
    return PolyglotPolicyReport(
        "PASS" if not unique else "POLICY_REJECTED",
        lang,
        SANDBOX_POLICY_VERSION,
        digest,
        len(encoded),
        unique,
    )
