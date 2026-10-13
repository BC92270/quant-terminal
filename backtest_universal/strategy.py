"""Governed strategy-code contracts.

Static validation reduces the attack surface but is deliberately not presented
as a security boundary.  Execution remains unavailable until an external OCI
sandbox supplies a verifiable attestation.
"""
from __future__ import annotations

import ast
from dataclasses import asdict, dataclass, field
from hashlib import sha256
import json
import math
import re
from typing import Any, Mapping, Protocol

from backtest_sdk import PortfolioSnapshot, Slice


POLICY_VERSION = "strategy-policy-2"
CONTRACT_VERSION = "StrategyJobV1"
MAX_SOURCE_BYTES = 128 * 1024
MAX_AST_NODES = 20_000
MAX_AST_DEPTH = 64
MAX_STRING_LITERAL = 8 * 1024
MAX_COLLECTION_LITERAL = 10_000

_ALLOWED_IMPORTS = {"math", "statistics", "numpy", "backtest_sdk"}
_FORBIDDEN_ROOTS = {
    "os", "sys", "subprocess", "socket", "pathlib", "shutil", "tempfile",
    "importlib", "pkgutil", "ctypes", "pickle", "marshal", "multiprocessing",
    "threading", "asyncio", "inspect", "builtins", "requests", "urllib", "httpx",
}
_FORBIDDEN_NAMES = {
    "eval", "exec", "compile", "open", "__import__", "getattr", "setattr",
    "delattr", "globals", "locals", "vars", "dir", "breakpoint", "input",
    "help", "type", "object", "memoryview",
}
_FORBIDDEN_IO_METHOD = re.compile(
    r"^(?:read_|fromfile|genfromtxt|loadtxt|to_(?:csv|pickle|parquet|excel|sql|feather|hdf)|load|save|savez|savetxt|memmap|ctypeslib)"
)
_FORBIDDEN_NODES = (
    ast.ClassDef,
    ast.Lambda,
    ast.AsyncFunctionDef,
    ast.Await,
    ast.Yield,
    ast.YieldFrom,
    ast.Global,
    ast.Nonlocal,
    ast.With,
    ast.AsyncWith,
    ast.Delete,
    ast.While,
)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


@dataclass(frozen=True)
class StrategyPolicyReport:
    status: str
    policy_version: str
    source_sha256: str
    node_count: int
    issues: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return self.status == "PASS"


@dataclass(frozen=True)
class SandboxAttestation:
    available: bool = False
    runner_image_digest: str = ""
    network_disabled: bool = False
    read_only_root: bool = False
    no_secrets_mounted: bool = False
    non_root: bool = False
    signature_verified: bool = False
    reason: str = "SANDBOX REQUIRED"

    @property
    def passed(self) -> bool:
        return bool(
            self.available
            and self.runner_image_digest.startswith("sha256:")
            and self.network_disabled
            and self.read_only_root
            and self.no_secrets_mounted
            and self.non_root
            and self.signature_verified
        )


@dataclass(frozen=True)
class StrategyJobV1:
    contract_version: str
    policy_version: str
    source_sha256: str
    parameters: Mapping[str, Any]
    parameters_sha256: str
    seed: int
    dataset_sha256: str
    security_master_sha256: str
    calendar_sha256: str
    runner_image_digest: str
    base_currency: str
    symbols: tuple[str, ...]
    research_only: bool = True
    automatic_promotion_authorized: bool = False
    limits: Mapping[str, int] = field(
        default_factory=lambda: {
            "wall_seconds": 120,
            "cpu_seconds": 120,
            "memory_mib": 1024,
            "pids": 32,
            "output_mib": 64,
        }
    )

    @property
    def job_id(self) -> str:
        return "SJ-" + sha256(_canonical_json(asdict(self)).encode("utf-8")).hexdigest()[:24].upper()


class StrategySandboxClient(Protocol):
    def attestation(self) -> SandboxAttestation: ...

    def submit(self, job: StrategyJobV1, source: str) -> Mapping[str, Any]: ...


class SandboxRequiredError(RuntimeError):
    pass


class StrategyRuntimeError(ValueError):
    """Fail-closed error raised by the causal strategy/ledger bridge."""


class CausalStrategyRuntime(Protocol):
    """Synchronous slice-by-slice strategy orchestration contract.

    The universal engine calls ``on_slice`` only after all OMS fills and
    accounting events through ``market_slice.available_at`` have been applied.
    The returned sparse mapping is interpreted as target-weight changes known
    at that same timestamp and therefore remains ineligible for execution
    until a strictly later market bar.

    A Docker controller can implement this protocol by sending ``portfolio``
    and ``market_slice`` to an already-running sandbox process and waiting for
    its target response.  The strategy process never receives the ledger
    object itself.
    """

    def on_slice(
        self,
        *,
        portfolio: PortfolioSnapshot,
        market_slice: Slice,
    ) -> Mapping[str, float] | None: ...


def request_causal_targets(
    runtime: CausalStrategyRuntime,
    *,
    portfolio: PortfolioSnapshot,
    market_slice: Slice,
) -> dict[str, float]:
    """Invoke a runtime against an authoritative, non-future snapshot.

    This validation lives outside the sandbox transport so every orchestrator
    receives identical fail-closed semantics.
    """

    if not portfolio.available:
        raise StrategyRuntimeError(
            portfolio.reason or "authoritative portfolio snapshot unavailable"
        )
    if portfolio.as_of is None or portfolio.as_of > market_slice.available_at:
        raise StrategyRuntimeError("portfolio snapshot is not causal for this slice")
    if portfolio.source != "OMS_EXECUTION_LEDGER" or not portfolio.ledger_sha256:
        raise StrategyRuntimeError("portfolio snapshot lacks OMS ledger authority")
    callback = getattr(runtime, "on_slice", None)
    if not callable(callback):
        raise StrategyRuntimeError("strategy runtime must implement on_slice")
    try:
        raw = callback(portfolio=portfolio, market_slice=market_slice)
    except Exception as exc:
        raise StrategyRuntimeError(
            f"strategy runtime callback failed: {type(exc).__name__}: {exc}"
        ) from exc
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise StrategyRuntimeError("strategy runtime must return a target mapping or None")
    targets: dict[str, float] = {}
    for raw_symbol, raw_value in raw.items():
        symbol = str(raw_symbol).strip().upper()
        if not symbol:
            raise StrategyRuntimeError("strategy runtime returned a blank symbol")
        if isinstance(raw_value, bool):
            raise StrategyRuntimeError(f"target for {symbol} must be numeric, not boolean")
        try:
            value = float(raw_value)
        except (TypeError, ValueError) as exc:
            raise StrategyRuntimeError(f"target for {symbol} must be numeric") from exc
        if not math.isfinite(value):
            raise StrategyRuntimeError(f"target for {symbol} must be finite")
        targets[symbol] = value
    return dict(sorted(targets.items()))


def _depth(node: ast.AST) -> int:
    children = list(ast.iter_child_nodes(node))
    return 1 if not children else 1 + max(_depth(child) for child in children)


class _PolicyVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.issues: list[str] = []
        self.function_stack: list[str] = []

    def issue(self, node: ast.AST, message: str) -> None:
        line = getattr(node, "lineno", 0)
        self.issues.append(f"line {line}: {message}")

    def generic_visit(self, node: ast.AST) -> None:
        if isinstance(node, _FORBIDDEN_NODES):
            self.issue(node, f"{type(node).__name__} is forbidden")
            return
        super().generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            root = alias.name.split(".", 1)[0]
            if root not in _ALLOWED_IMPORTS:
                self.issue(node, f"import {alias.name} is not allowed")

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        root = (node.module or "").split(".", 1)[0]
        if node.level or root not in _ALLOWED_IMPORTS:
            self.issue(node, f"import from {node.module!r} is not allowed")
        if any(alias.name == "*" for alias in node.names):
            self.issue(node, "wildcard imports are forbidden")

    def visit_Name(self, node: ast.Name) -> None:
        if node.id in _FORBIDDEN_NAMES or node.id in _FORBIDDEN_ROOTS:
            self.issue(node, f"name {node.id!r} is forbidden")

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr.startswith("_"):
            self.issue(node, "private and dunder attributes are forbidden")
        if _FORBIDDEN_IO_METHOD.match(node.attr):
            self.issue(node, f"I/O method {node.attr!r} is forbidden")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name):
            if node.func.id in _FORBIDDEN_NAMES or node.func.id in self.function_stack:
                self.issue(node, f"call to {node.func.id!r} is forbidden")
        elif isinstance(node.func, ast.Attribute):
            if node.func.attr.startswith("_") or _FORBIDDEN_IO_METHOD.match(node.func.attr):
                self.issue(node, f"call to {node.func.attr!r} is forbidden")
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node.decorator_list:
            self.issue(node, "decorators are forbidden")
        # Defaults and annotations execute or resolve at function-definition
        # time.  They must receive the same capability checks as the body.
        self.visit(node.args)
        if node.returns is not None:
            self.visit(node.returns)
        for type_parameter in getattr(node, "type_params", ()):  # Python 3.12+
            self.visit(type_parameter)
        self.function_stack.append(node.name)
        for child in node.body:
            self.visit(child)
        self.function_stack.pop()

    def visit_For(self, node: ast.For) -> None:
        allowed = False
        if isinstance(node.iter, ast.Call) and isinstance(node.iter.func, ast.Name):
            if node.iter.func.id == "range" and 1 <= len(node.iter.args) <= 3:
                constants = [arg.value for arg in node.iter.args if isinstance(arg, ast.Constant)]
                allowed = len(constants) == len(node.iter.args) and all(
                    isinstance(value, int) and abs(value) <= 10_000 for value in constants
                )
        if isinstance(node.iter, ast.Call) and isinstance(node.iter.func, ast.Attribute):
            allowed = node.iter.func.attr == "history"
            if node.iter.func.attr in {"items", "values"}:
                owner = node.iter.func.value
                allowed = (
                    isinstance(owner, ast.Attribute)
                    and owner.attr == "bars"
                    and isinstance(owner.value, ast.Name)
                )
        if not allowed:
            self.issue(node, "for-loop iterator must be bounded range() or ctx.history()")
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, (str, bytes)) and len(node.value) > MAX_STRING_LITERAL:
            self.issue(node, "literal exceeds the size limit")

    def visit_List(self, node: ast.List) -> None:
        if len(node.elts) > MAX_COLLECTION_LITERAL:
            self.issue(node, "list literal exceeds the size limit")
        self.generic_visit(node)

    visit_Tuple = visit_List
    visit_Set = visit_List

    def visit_Dict(self, node: ast.Dict) -> None:
        if len(node.keys) > MAX_COLLECTION_LITERAL:
            self.issue(node, "dict literal exceeds the size limit")
        self.generic_visit(node)


def validate_strategy_source(source: str) -> StrategyPolicyReport:
    raw = str(source or "")
    source_hash = sha256(raw.encode("utf-8")).hexdigest()
    issues: list[str] = []
    if len(raw.encode("utf-8")) > MAX_SOURCE_BYTES:
        issues.append("source exceeds 128 KiB")
    try:
        tree = ast.parse(raw, mode="exec")
    except SyntaxError as exc:
        return StrategyPolicyReport(
            "POLICY_REJECTED",
            POLICY_VERSION,
            source_hash,
            0,
            (f"line {exc.lineno or 0}: syntax error: {exc.msg}",),
        )
    nodes = list(ast.walk(tree))
    if len(nodes) > MAX_AST_NODES:
        issues.append(f"AST contains {len(nodes)} nodes; {MAX_AST_NODES} maximum")
    if _depth(tree) > MAX_AST_DEPTH:
        issues.append(f"AST depth exceeds {MAX_AST_DEPTH}")
    functions: dict[str, ast.FunctionDef] = {}
    for item in tree.body:
        if isinstance(item, ast.FunctionDef):
            functions[item.name] = item
            if item.name not in {"initialize", "on_bar", "on_slice"}:
                issues.append(f"line {item.lineno}: unsupported entrypoint {item.name!r}")
        elif isinstance(item, (ast.Import, ast.ImportFrom, ast.Assign, ast.AnnAssign)):
            continue
        elif isinstance(item, ast.Expr) and isinstance(item.value, ast.Constant) and isinstance(item.value.value, str):
            continue
        else:
            issues.append(
                f"line {getattr(item, 'lineno', 0)}: module-level {type(item).__name__} is forbidden"
            )
    if "on_bar" not in functions and "on_slice" not in functions:
        issues.append("required entrypoint on_slice(ctx, slice) or on_bar(ctx, bar) is missing")
    for name, expected in (("initialize", 1), ("on_bar", 2), ("on_slice", 2)):
        function = functions.get(name)
        if function is None:
            continue
        positional = len(function.args.posonlyargs) + len(function.args.args)
        if positional != expected or function.args.vararg or function.args.kwarg:
            issues.append(f"line {function.lineno}: {name} has an invalid signature")
    visitor = _PolicyVisitor()
    visitor.visit(tree)
    issues.extend(visitor.issues)
    unique = tuple(dict.fromkeys(issues))
    return StrategyPolicyReport(
        "PASS" if not unique else "POLICY_REJECTED",
        POLICY_VERSION,
        source_hash,
        len(nodes),
        unique,
    )


def build_strategy_job(
    *,
    source: str,
    parameters: Mapping[str, Any],
    seed: int,
    dataset_sha256: str,
    security_master_sha256: str,
    calendar_sha256: str,
    base_currency: str,
    symbols: tuple[str, ...],
    attestation: SandboxAttestation,
) -> StrategyJobV1:
    report = validate_strategy_source(source)
    if not report.passed:
        raise ValueError("strategy policy rejected: " + "; ".join(report.issues[:5]))
    if not attestation.passed:
        raise SandboxRequiredError(attestation.reason or "SANDBOX REQUIRED")
    parameter_payload = json.loads(_canonical_json(dict(parameters)))
    return StrategyJobV1(
        contract_version=CONTRACT_VERSION,
        policy_version=POLICY_VERSION,
        source_sha256=report.source_sha256,
        parameters=parameter_payload,
        parameters_sha256=sha256(_canonical_json(parameter_payload).encode("utf-8")).hexdigest(),
        seed=int(seed),
        dataset_sha256=str(dataset_sha256),
        security_master_sha256=str(security_master_sha256),
        calendar_sha256=str(calendar_sha256),
        runner_image_digest=attestation.runner_image_digest,
        base_currency=str(base_currency).upper(),
        symbols=tuple(str(symbol).upper() for symbol in symbols),
    )


DEFAULT_STRATEGY_TEMPLATE = '''from backtest_sdk import Bar, Context

def initialize(ctx: Context) -> None:
    ctx.state.fast = 20
    ctx.state.slow = 100

def on_bar(ctx: Context, bar: Bar) -> None:
    close = ctx.history(bar.symbol, "close", ctx.state.slow)
    if len(close) < ctx.state.slow:
        ctx.target_percent(bar.symbol, 0.0)
        return
    fast = close[-ctx.state.fast:].mean()
    slow = close.mean()
    ctx.target_percent(bar.symbol, 1.0 if fast > slow else 0.0)
'''
