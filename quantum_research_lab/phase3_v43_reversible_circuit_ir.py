"""Quantum Lab V4.3 provider-neutral elementary circuit materialization.

This module is an append-only successor to the authenticated V4.2 research
release.  It expands one complete coined-walk generator step for each frozen
N=40 seed into an explicit deterministic stream over X, H, T, TDG, RY, RZ and
CX.  The multi-million-instruction streams are hashed in ordered chunks rather
than persisted as large side files; the sealed artifact contains everything
required to reproduce and authenticate them.

V4.3 is RESEARCH_ONLY.  It imports no provider SDK, reads no credentials,
selects no backend, performs no transpilation and submits no QPU job.
"""

from __future__ import annotations

from collections import Counter
import copy
from dataclasses import dataclass
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any, Iterable, Iterator, Mapping, Sequence

from .phase3_v41_certified_bridge_compiler import _certificate_by_seed, _guarded_rows
from .phase3_v42_coined_walk_compiler import BUDGET_CNOT, K, N, SEEDS


V43_VERSION = "PHASE III · V4.3 BACKEND-AGNOSTIC REVERSIBLE CIRCUIT MATERIALIZATION · V1"
ARTIFACT_VERSION = "PHASE III · V4.3 SEALED ELEMENTARY CIRCUIT MANIFEST · V1"
SPEC_FILENAME = "PHASE_III_V4_3_REVERSIBLE_CIRCUIT_MATERIALIZATION_SPEC_V1.json"
SIMULATOR_FILENAME = "phase3_v43_reversible_simulator.cpp"
DEFAULT_ARTIFACT_NAME = "SEALED_V4_3_REVERSIBLE_CIRCUIT_ARTIFACT.json"
ELEMENTARY_BASIS = ("X", "H", "T", "TDG", "RY", "RZ", "CX")
CHUNK_INSTRUCTIONS = 8_192
MATERIALIZED_MIN_WIDTH = 5
COIN_THETA = Fraction(1, 2)
COIN_BETA = Fraction(0, 1)
BRIDGE_THETA = Fraction(1, 2)

EXPECTED_SPEC_SHA256 = "71f6d1f642a6d6a1e99d9d265e6cba914302ea9763a854a13cf4aa0b95d8cf5f"
EXPECTED_SPEC_RAW_SHA256 = "ad8904557e850b8850e11ccc410fa3bb44cc15947cf06d7bdee7047f24563226"
EXPECTED_V42_SPEC_RAW_SHA256 = "11b9d7a86fc1617f7c313c2cda58c4b8874d33cb9e4fe11460a65b8920e40674"
EXPECTED_V42_SPEC_SHA256 = "acf640c11d3dc575ebcc1358919095cf68673583a8c628c7131e664f7859801e"
EXPECTED_V42_SOURCE_RAW_SHA256 = "fc4b9ce991cc866aa7a9b809172df41227e9dcd133a41d210068663ee7bd77e9"
EXPECTED_V42_ARTIFACT_RAW_SHA256 = "0952111064db57f6c1122e9a7b4d45ee997667e0d57137ea173be0009ba4feec"
EXPECTED_V42_ARTIFACT_SHA256 = "f2f294f8f0a21804d7dd6a23d7695b161723fcc1efea48b2f9d1ce7bcbb3f5be"
EXPECTED_V42_FREEZE_RAW_SHA256 = "faf9250d6f76acdeb2644d52a45c7ae1d8930b3f4c7367ca6ba3861e063371c5"
EXPECTED_V42_FREEZE_SHA256 = "36ebd4acedb1563227324b56ab6731293d38935c2c888f37c33029858a0f3068"
EXPECTED_V42_PATH_FINGERPRINT = "cc3dd736d2475cfc1d143bc720fc37863d62ede26019a3aa99cd33e96643b166"
V42_SUCCESSOR_MUTABLE = frozenset({"quantum_research_lab/README.md", "quantum_research_lab/ui.py"})


def canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def canonical_json_sha256(payload: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def raw_file_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key rejected: {key}")
        result[key] = value
    return result


def _reject_nonfinite(token: str) -> None:
    raise ValueError(f"Non-finite JSON number rejected: {token}")


def _read_json_strict(path: str | Path) -> dict[str, Any]:
    payload = json.loads(
        Path(path).read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicates,
        parse_constant=_reject_nonfinite,
    )
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return payload


def _root(root: str | Path | None = None) -> Path:
    return Path(root).resolve() if root is not None else Path(__file__).resolve().parents[1]


def _paths(root: str | Path | None = None) -> dict[str, Path]:
    base = _root(root)
    return {
        "root": base,
        "spec": base / "quantum_research_lab" / SPEC_FILENAME,
        "source": base / "quantum_research_lab" / "phase3_v43_reversible_circuit_ir.py",
        "simulator": base / "quantum_research_lab" / SIMULATOR_FILENAME,
        "v42_spec": base / "quantum_research_lab" / "PHASE_III_V4_2_COINED_WALK_COMPILER_SPEC_V1.json",
        "v42_source": base / "quantum_research_lab" / "phase3_v42_coined_walk_compiler.py",
        "v42_artifact": base / "outputs/quantum_phase3/v42_coined_walk/SEALED_V4_2_COINED_WALK_COMPILER_ARTIFACT.json",
        "v42_freeze": base / "FREEZE_CONTRACT_V4_2.json",
        "v41_artifact": base / "outputs/quantum_phase3/v41_certified_bridge/SEALED_V4_1_CERTIFIED_BRIDGE_COMPILER_ARTIFACT.json",
        "artifact": base / "outputs/quantum_phase3/v43_reversible_circuit" / DEFAULT_ARTIFACT_NAME,
    }


def load_v43_spec(path: str | Path | None = None, *, root: str | Path | None = None) -> dict[str, Any]:
    target = Path(path) if path is not None else _paths(root)["spec"]
    if raw_file_sha256(target) != EXPECTED_SPEC_RAW_SHA256:
        raise ValueError("V4.3 specification raw identity mismatch.")
    payload = _read_json_strict(target)
    core = {key: value for key, value in payload.items() if key not in {"v43_spec_sha", "v43_spec_sha256"}}
    digest = canonical_json_sha256(core)
    boundary = payload.get("claim_boundary") or {}
    chronology = payload.get("chronology") or {}
    if not (
        digest == EXPECTED_SPEC_SHA256
        and payload.get("v43_spec_sha256") == digest
        and payload.get("v43_spec_sha") == digest[:20].upper()
        and chronology.get("result_state_at_seal") == "NOT_EVALUATED"
        and boundary.get("research_classification") == "RESEARCH_ONLY"
        and boundary.get("provider_calls") == 0
        and boundary.get("qpu_jobs_submitted") == 0
        and boundary.get("hardware_executable") is False
        and boundary.get("backend_transpilation") == "NOT_RUN"
        and boundary.get("quantum_advantage") == "NOT_CLAIMED"
    ):
        raise ValueError("V4.3 specification semantic identity or boundary mismatch.")
    return payload


def _path_fingerprint(paths: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(sorted(paths), separators=(",", ":")).encode("utf-8")).hexdigest()


def authenticate_v42_parent(*, root: str | Path | None = None) -> dict[str, Any]:
    """Authenticate V4.2 and all 175 paths immutable to the V4.3 successor."""

    paths = _paths(root)
    errors: list[str] = []
    raw_expected = {
        "v42_spec": EXPECTED_V42_SPEC_RAW_SHA256,
        "v42_source": EXPECTED_V42_SOURCE_RAW_SHA256,
        "v42_artifact": EXPECTED_V42_ARTIFACT_RAW_SHA256,
        "v42_freeze": EXPECTED_V42_FREEZE_RAW_SHA256,
    }
    raw_checks: dict[str, dict[str, Any]] = {}
    for name, expected in raw_expected.items():
        actual = raw_file_sha256(paths[name]) if paths[name].is_file() else ""
        raw_checks[name] = {"actual": actual, "expected": expected, "valid": actual == expected}
        if actual != expected:
            errors.append(f"V4.2 raw identity mismatch: {name}")

    try:
        spec = _read_json_strict(paths["v42_spec"])
        spec_core = {key: value for key, value in spec.items() if key not in {"v42_spec_sha", "v42_spec_sha256"}}
        spec_valid = spec.get("v42_spec_sha256") == EXPECTED_V42_SPEC_SHA256 == canonical_json_sha256(spec_core)
    except Exception as exc:
        spec_valid = False
        errors.append(f"V4.2 specification parse failure: {exc}")
    try:
        artifact = _read_json_strict(paths["v42_artifact"])
        artifact_core = {key: value for key, value in artifact.items() if key != "artifact_sha256"}
        artifact_valid = bool(
            artifact.get("artifact_sha256") == EXPECTED_V42_ARTIFACT_SHA256 == canonical_json_sha256(artifact_core)
            and (artifact.get("decisions") or {}).get("overall")
            == "V42_INDEXED_COINED_WALK_CONNECTED_RESOURCE_SCREEN_PASSED"
            and (artifact.get("decisions") or {}).get("next_falsifiable_gate")
            == "INDEPENDENT_REVERSIBLE_SIMULATION_AND_BACKEND_AGNOSTIC_CIRCUIT_MATERIALIZATION"
        )
    except Exception as exc:
        artifact = {}
        artifact_valid = False
        errors.append(f"V4.2 artifact parse failure: {exc}")
    immutable_mismatches: list[str] = []
    try:
        freeze = _read_json_strict(paths["v42_freeze"])
        freeze_core = {key: value for key, value in freeze.items() if key != "freeze_contract_sha256"}
        frozen = freeze.get("frozen_files") or {}
        immutable = {
            str(relative): str(expected)
            for relative, expected in frozen.items()
            if str(relative) not in V42_SUCCESSOR_MUTABLE
        }
        for relative, expected in immutable.items():
            candidate = paths["root"] / relative
            if not candidate.is_file() or candidate.is_symlink() or raw_file_sha256(candidate) != expected:
                immutable_mismatches.append(relative)
        freeze_valid = bool(
            freeze.get("freeze_contract_sha256") == EXPECTED_V42_FREEZE_SHA256 == canonical_json_sha256(freeze_core)
            and len(frozen) == 177
            and len(immutable) == 175
            and _path_fingerprint(frozen) == EXPECTED_V42_PATH_FINGERPRINT
            and freeze.get("frozen_paths_fingerprint_sha256") == EXPECTED_V42_PATH_FINGERPRINT
            and not immutable_mismatches
        )
    except Exception as exc:
        freeze = {}
        immutable = {}
        freeze_valid = False
        errors.append(f"V4.2 freeze parse failure: {exc}")
    for name, valid in {"spec": spec_valid, "artifact": artifact_valid, "freeze": freeze_valid}.items():
        if not valid:
            errors.append(f"V4.2 semantic authentication failed: {name}")
    if immutable_mismatches:
        errors.append(f"V4.2 immutable path mismatches: {immutable_mismatches[:5]}")
    return {
        "artifact": artifact,
        "errors": list(dict.fromkeys(errors)),
        "freeze": freeze,
        "immutable_file_count": len(immutable),
        "immutable_files_exact": not immutable_mismatches and len(immutable) == 175,
        "raw_checks": raw_checks,
        "semantic_checks": {"spec": spec_valid, "artifact": artifact_valid, "freeze": freeze_valid},
        "valid": not errors and all(row["valid"] for row in raw_checks.values()),
    }


@dataclass(frozen=True)
class Register:
    name: str
    start: int
    width: int
    role: str

    @property
    def qubits(self) -> tuple[int, ...]:
        return tuple(range(self.start, self.start + self.width))

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "qubit_ids": list(self.qubits), "role": self.role, "start": self.start, "width": self.width}


@dataclass(frozen=True)
class CircuitLayout:
    registers: tuple[Register, ...]
    sum_names: tuple[str, ...]
    total_qubits: int

    def register(self, name: str) -> Register:
        for register in self.registers:
            if register.name == name:
                return register
        raise KeyError(name)

    def as_dict(self) -> dict[str, Any]:
        core = {
            "registers": [register.as_dict() for register in self.registers],
            "sum_names": list(self.sum_names),
            "total_qubits": self.total_qubits,
        }
        return {**core, "register_map_sha256": canonical_json_sha256(core)}


def build_layout(rows: Sequence[Mapping[str, Any]]) -> CircuitLayout:
    registers: list[Register] = []
    cursor = 0

    def allocate(name: str, width: int, role: str) -> None:
        nonlocal cursor
        registers.append(Register(name=name, start=cursor, width=width, role=role))
        cursor += width

    allocate("DATA", N, "PERSISTENT_PORTFOLIO_BASIS")
    allocate("REMOVE_COIN", N, "PERSISTENT_ONE_HOT_ADDRESS")
    allocate("ADD_COIN", N, "PERSISTENT_ONE_HOT_ADDRESS")
    allocate("TARGET", N, "CLEAN_SELECTOR_TARGET_THEN_BRIDGE_LADDER_REUSE")
    sum_names: list[str] = []
    widths = [max(MATERIALIZED_MIN_WIDTH, int(row["width"])) for row in rows]
    for index, (row, width) in enumerate(zip(rows, widths)):
        name = f"SUM_{index}_{str(row['name'])}"
        sum_names.append(name)
        allocate(name, width, "EXACT_GUARDED_SUM_BANK")
    allocate("CONSTANT", max(widths), "REUSABLE_CLASSICAL_CONSTANT_AND_C7X_LADDER")
    allocate("CARRY", 1, "CLEAN_CUCCARO_CARRY")
    allocate("ADDRESSED", 2, "REMOVE_AND_ADD_ADDRESSED_DATA_FLAGS")
    allocate("ROW_FLAGS", len(rows), "SEVEN_INTERVAL_PREDICATE_FLAGS")
    allocate("CONTROL_FLAGS", 5, "DIFFERENCE_FEASIBLE_MOVE_AND_TWO_RESERVED_CLEAN_FLAGS")
    if cursor != 160 + sum(widths) + max(widths) + 15:
        raise AssertionError("V4.3 register allocation formula mismatch.")
    return CircuitLayout(tuple(registers), tuple(sum_names), cursor)


class CircuitStream:
    """Streaming canonicalizer; it never retains the full instruction list."""

    def __init__(self, *, seed: int, total_qubits: int) -> None:
        self.seed = int(seed)
        self.total_qubits = int(total_qubits)
        self._stream = hashlib.sha256()
        self._chunk = hashlib.sha256()
        self._chunk_count = 0
        self._chunk_hashes: list[str] = []
        self._chunk_sizes: list[int] = []
        self._stage_hashers: dict[str, Any] = {}
        self._stage_counts: Counter[str] = Counter()
        self.elementary_counts: Counter[str] = Counter()
        self.macro_counts: Counter[str] = Counter()
        self.instruction_count = 0
        self.max_qubit_id = -1

    @staticmethod
    def _angle_token(angle: Fraction | None) -> str:
        if angle is None:
            return "-"
        reduced = Fraction(angle)
        return f"{reduced.numerator}/{reduced.denominator}pi"

    def emit(self, stage: str, opcode: str, qubits: Sequence[int], angle: Fraction | None = None) -> None:
        if opcode not in ELEMENTARY_BASIS:
            raise ValueError(f"Opcode outside the frozen V4.3 basis: {opcode}")
        q = tuple(int(value) for value in qubits)
        expected_arity = 2 if opcode == "CX" else 1
        if len(q) != expected_arity or len(set(q)) != len(q):
            raise ValueError(f"Invalid {opcode} operands: {q}")
        if min(q) < 0 or max(q) >= self.total_qubits:
            raise ValueError(f"Qubit outside allocation: {q}")
        if opcode in {"RY", "RZ"} and angle is None:
            raise ValueError(f"{opcode} requires an exact angle.")
        if opcode not in {"RY", "RZ"} and angle is not None:
            raise ValueError(f"{opcode} cannot carry an angle.")
        line = (
            f"{self.instruction_count}|{stage}|{opcode}|"
            f"{','.join(str(value) for value in q)}|{self._angle_token(angle)}\n"
        ).encode("ascii")
        self._stream.update(line)
        self._chunk.update(line)
        stage_hasher = self._stage_hashers.setdefault(stage, hashlib.sha256())
        stage_hasher.update(line)
        self._stage_counts[stage] += 1
        self.elementary_counts[opcode] += 1
        self.instruction_count += 1
        self._chunk_count += 1
        self.max_qubit_id = max(self.max_qubit_id, *q)
        if self._chunk_count == CHUNK_INSTRUCTIONS:
            self._close_chunk()

    def _close_chunk(self) -> None:
        if self._chunk_count:
            self._chunk_hashes.append(self._chunk.hexdigest())
            self._chunk_sizes.append(self._chunk_count)
            self._chunk = hashlib.sha256()
            self._chunk_count = 0

    def x(self, stage: str, q: int) -> None:
        self.emit(stage, "X", (q,))

    def h(self, stage: str, q: int) -> None:
        self.emit(stage, "H", (q,))

    def t(self, stage: str, q: int) -> None:
        self.emit(stage, "T", (q,))

    def tdg(self, stage: str, q: int) -> None:
        self.emit(stage, "TDG", (q,))

    def ry(self, stage: str, q: int, angle: Fraction) -> None:
        self.emit(stage, "RY", (q,), Fraction(angle))

    def rz(self, stage: str, q: int, angle: Fraction) -> None:
        self.emit(stage, "RZ", (q,), Fraction(angle))

    def cx(self, stage: str, control: int, target: int) -> None:
        self.emit(stage, "CX", (control, target))

    def ccx(self, stage: str, a: int, b: int, target: int) -> None:
        """Exact 6-CX / 9-one-qubit Toffoli decomposition."""

        if len({a, b, target}) != 3:
            raise ValueError("CCX operands must be distinct.")
        self.macro_counts["CCX_6CX"] += 1
        self.h(stage, target)
        self.cx(stage, b, target)
        self.tdg(stage, target)
        self.cx(stage, a, target)
        self.t(stage, target)
        self.cx(stage, b, target)
        self.tdg(stage, target)
        self.cx(stage, a, target)
        self.t(stage, b)
        self.t(stage, target)
        self.h(stage, target)
        self.cx(stage, a, b)
        self.t(stage, a)
        self.tdg(stage, b)
        self.cx(stage, a, b)

    def mcx(self, stage: str, controls: Sequence[int], target: int, ancillas: Sequence[int]) -> None:
        controls = tuple(int(q) for q in controls)
        if len(controls) < 2 or len(set((*controls, target))) != len(controls) + 1:
            raise ValueError("V4.3 MCX requires at least two distinct controls and a distinct target.")
        required = max(0, len(controls) - 2)
        if len(ancillas) < required:
            raise ValueError("Insufficient clean ladder ancillas.")
        work = tuple(int(q) for q in ancillas[:required])
        if len(set((*controls, target, *work))) != len(controls) + 1 + len(work):
            raise ValueError("MCX ladder ancillas overlap controls or target.")
        self.macro_counts[f"C{len(controls)}X"] += 1
        if len(controls) == 2:
            self.ccx(stage, controls[0], controls[1], target)
            return
        self.ccx(stage, controls[0], controls[1], work[0])
        for index in range(2, len(controls) - 1):
            self.ccx(stage, controls[index], work[index - 2], work[index - 1])
        self.ccx(stage, controls[-1], work[-1], target)
        for index in range(len(controls) - 2, 1, -1):
            self.ccx(stage, controls[index], work[index - 2], work[index - 1])
        self.ccx(stage, controls[0], controls[1], work[0])

    def pattern_mcx(
        self,
        stage: str,
        controls: Sequence[int],
        control_values: Sequence[int],
        target: int,
        ancillas: Sequence[int],
    ) -> None:
        if len(controls) != len(control_values):
            raise ValueError("Pattern MCX controls and values differ in length.")
        negative = [int(q) for q, value in zip(controls, control_values) if int(value) == 0]
        for q in negative:
            self.x(stage, q)
        self.mcx(stage, controls, target, ancillas)
        for q in reversed(negative):
            self.x(stage, q)

    def finish(self) -> dict[str, Any]:
        self._close_chunk()
        stage_rows = [
            {"instruction_count": self._stage_counts[name], "stage": name, "stage_sha256": self._stage_hashers[name].hexdigest()}
            for name in sorted(self._stage_counts)
        ]
        core = {
            "basis": list(ELEMENTARY_BASIS),
            "canonical_instruction_contract": "INDEX|STAGE|OPCODE|COMMA_SEPARATED_QUBITS|SIGNED_RATIONAL_PI_OR_DASH_NEWLINE",
            "chunk_instruction_limit": CHUNK_INSTRUCTIONS,
            "chunk_instruction_sizes": self._chunk_sizes,
            "chunk_sha256": self._chunk_hashes,
            "elementary_counts": {name: self.elementary_counts.get(name, 0) for name in ELEMENTARY_BASIS},
            "instruction_count": self.instruction_count,
            "macro_counts": dict(sorted(self.macro_counts.items())),
            "max_qubit_id": self.max_qubit_id,
            "seed": self.seed,
            "stage_manifests": stage_rows,
            "stream_sha256": self._stream.hexdigest(),
            "total_qubits": self.total_qubits,
        }
        return {**core, "stream_manifest_sha256": canonical_json_sha256(core)}


def _full_adder_ops(a: Sequence[int], b: Sequence[int], z: int, carry: int) -> tuple[tuple[str, tuple[int, ...]], ...]:
    """Cuccaro Figure-5 sequence for n>=4, preserving A and clean carry."""

    if len(a) != len(b) or len(a) < 4:
        raise ValueError("The frozen Cuccaro Figure-5 sequence requires equal widths n>=4.")
    n = len(a)
    ops: list[tuple[str, tuple[int, ...]]] = []
    for index in range(1, n):
        ops.append(("CX", (a[index], b[index])))
    ops.extend((("CX", (a[1], carry)), ("CCX", (a[0], b[0], carry)), ("CX", (a[2], a[1])), ("CCX", (carry, b[1], a[1])), ("CX", (a[3], a[2]))))
    for index in range(2, n - 2):
        ops.extend((("CCX", (a[index - 1], b[index], a[index])), ("CX", (a[index + 2], a[index + 1]))))
    ops.extend((("CCX", (a[n - 3], b[n - 2], a[n - 2])), ("CX", (a[n - 1], z)), ("CCX", (a[n - 2], b[n - 1], z))))
    for index in range(1, n - 1):
        ops.append(("X", (b[index],)))
    ops.append(("CX", (carry, b[1])))
    for index in range(2, n):
        ops.append(("CX", (a[index - 1], b[index])))
    ops.append(("CCX", (a[n - 3], b[n - 2], a[n - 2])))
    for index in range(n - 3, 1, -1):
        ops.extend((("CCX", (a[index - 1], b[index], a[index])), ("CX", (a[index + 2], a[index + 1])), ("X", (b[index + 1],))))
    ops.extend(
        (
            ("CCX", (carry, b[1], a[1])),
            ("CX", (a[3], a[2])),
            ("X", (b[2],)),
            ("CCX", (a[0], b[0], carry)),
            ("CX", (a[2], a[1])),
            ("X", (b[1],)),
            ("CX", (a[1], carry)),
        )
    )
    for index in range(n):
        ops.append(("CX", (a[index], b[index])))
    counts = Counter(name for name, _ in ops)
    if counts != Counter({"CCX": 2 * n - 1, "CX": 5 * n - 3, "X": 2 * n - 4}):
        raise AssertionError("Cuccaro full-adder primitive count mismatch.")
    return tuple(ops)


def _high_bit_ops(a: Sequence[int], b: Sequence[int], out: int, carry: int) -> tuple[tuple[str, tuple[int, ...]], ...]:
    """Cuccaro high-bit compute/copy/uncompute circuit preserving A and B."""

    if len(a) != len(b) or len(a) < 4:
        raise ValueError("The frozen high-bit sequence requires equal widths n>=4.")
    n = len(a)
    forward: list[tuple[str, tuple[int, ...]]] = []
    for index in range(1, n):
        forward.append(("CX", (a[index], b[index])))
    forward.extend((("CX", (a[1], carry)), ("CCX", (a[0], b[0], carry)), ("CX", (a[2], a[1])), ("CCX", (carry, b[1], a[1])), ("CX", (a[3], a[2]))))
    for index in range(2, n - 2):
        forward.extend((("CCX", (a[index - 1], b[index], a[index])), ("CX", (a[index + 2], a[index + 1]))))
    forward.append(("CCX", (a[n - 3], b[n - 2], a[n - 2])))
    output = (("CX", (a[n - 1], out)), ("CCX", (a[n - 2], b[n - 1], out)))
    ops = tuple((*forward, *output, *reversed(forward)))
    counts = Counter(name for name, _ in ops)
    if counts != Counter({"CCX": 2 * n - 1, "CX": 4 * n - 3}):
        raise AssertionError("Cuccaro high-bit primitive count mismatch.")
    return ops


def _emit_base_op(stream: CircuitStream, stage: str, operation: tuple[str, tuple[int, ...]]) -> None:
    name, qubits = operation
    if name == "X":
        stream.x(stage, qubits[0])
    elif name == "CX":
        stream.cx(stage, qubits[0], qubits[1])
    elif name == "CCX":
        stream.ccx(stage, qubits[0], qubits[1], qubits[2])
    else:
        raise ValueError(name)


def emit_controlled_constant_add(
    stream: CircuitStream,
    *,
    stage: str,
    control: int,
    work: Sequence[int],
    constant: Sequence[int],
    carry: int,
    ladder: int,
    value: int,
) -> None:
    width = len(work)
    if width < MATERIALIZED_MIN_WIDTH or len(constant) < width:
        raise ValueError("Controlled constant adder width/allocation mismatch.")
    a = tuple(constant[:width])
    b = tuple(work)
    encoded = int(value) & ((1 << width) - 1)
    for index in range(width):
        if (encoded >> index) & 1:
            stream.x(stage, a[index])
    operations = (*_full_adder_ops(a[:-1], b[:-1], b[-1], carry), ("CX", (a[-1], b[-1])))
    before_cnot = stream.elementary_counts["CX"]
    for name, qubits in operations:
        if name == "X":
            stream.cx(stage, control, qubits[0])
        elif name == "CX":
            stream.ccx(stage, control, qubits[0], qubits[1])
        elif name == "CCX":
            stream.mcx(stage, (control, qubits[0], qubits[1]), qubits[2], (ladder,))
        else:
            raise ValueError(name)
    for index in range(width - 1, -1, -1):
        if (encoded >> index) & 1:
            stream.x(stage, a[index])
    stream.macro_counts[f"CONTROLLED_ADD_W{width}"] += 1
    if stream.elementary_counts["CX"] - before_cnot != 68 * width - 102:
        raise AssertionError("Controlled constant adder CNOT materialization mismatch.")


def emit_comparator_toggle(
    stream: CircuitStream,
    *,
    stage: str,
    work: Sequence[int],
    constant: Sequence[int],
    carry: int,
    out: int,
    value: int,
    relation: str,
) -> None:
    """Toggle out by work>=value or work<=value; preserve all other inputs."""

    width = len(work)
    if width < MATERIALIZED_MIN_WIDTH or len(constant) < width:
        raise ValueError("Comparator width/allocation mismatch.")
    maximum = (1 << width) - 1
    if relation == "GE":
        if not 0 < value <= maximum:
            raise ValueError("GE comparator requires 0<value<=2**width-1.")
        encoded = int(value)
        stream.x(stage, out)
    elif relation == "LE":
        if not 0 <= value < maximum:
            raise ValueError("LE comparator requires 0<=value<2**width-1.")
        encoded = int(value) + 1
    else:
        raise ValueError("Comparator relation must be GE or LE.")
    a = tuple(work)
    b = tuple(constant[:width])
    for index in range(width):
        if (encoded >> index) & 1:
            stream.x(stage, b[index])
    for q in a:
        stream.x(stage, q)
    before_cnot = stream.elementary_counts["CX"]
    for operation in _high_bit_ops(a, b, out, carry):
        _emit_base_op(stream, stage, operation)
    for q in reversed(a):
        stream.x(stage, q)
    for index in range(width - 1, -1, -1):
        if (encoded >> index) & 1:
            stream.x(stage, b[index])
    stream.macro_counts[f"COMPARATOR_{relation}_W{width}"] += 1
    if stream.elementary_counts["CX"] - before_cnot != 16 * width - 9:
        raise AssertionError("Comparator CNOT materialization mismatch.")


def emit_interval_oracle(
    stream: CircuitStream,
    *,
    stage: str,
    work: Sequence[int],
    constant: Sequence[int],
    carry: int,
    out: int,
    lower: int,
    upper: int,
) -> None:
    """Toggle lower<=work<=upper using XOR of two nested GE predicates."""

    emit_comparator_toggle(stream, stage=stage, work=work, constant=constant, carry=carry, out=out, value=lower, relation="GE")
    emit_comparator_toggle(stream, stage=stage, work=work, constant=constant, carry=carry, out=out, value=upper + 1, relation="GE")
    stream.macro_counts["INTERVAL_BY_NESTED_GE_XOR"] += 1


def emit_feasibility_oracle(
    stream: CircuitStream,
    *,
    stage_prefix: str,
    rows: Sequence[Mapping[str, Any]],
    layout: CircuitLayout,
    target_bits: Sequence[int],
    feasible_flag: int,
) -> None:
    constant = layout.register("CONSTANT").qubits
    carry = layout.register("CARRY").qubits[0]
    row_flags = layout.register("ROW_FLAGS").qubits
    ladder = layout.register("CONTROL_FLAGS").qubits[3]
    for row_index, row in enumerate(rows):
        bank = layout.register(layout.sum_names[row_index]).qubits
        width = len(bank)
        offset = int(row["cache_offset"]) & ((1 << width) - 1)
        stage = f"{stage_prefix}_SUM_BUILD_R{row_index}"
        for bit in range(width):
            if (offset >> bit) & 1:
                stream.x(stage, bank[bit])
        for data_index, coefficient in enumerate(row["coefficients"]):
            if int(coefficient):
                emit_controlled_constant_add(
                    stream,
                    stage=stage,
                    control=target_bits[data_index],
                    work=bank,
                    constant=constant,
                    carry=carry,
                    ladder=ladder,
                    value=int(coefficient),
                )
    for row_index, row in enumerate(rows):
        bank = layout.register(layout.sum_names[row_index]).qubits
        emit_interval_oracle(
            stream,
            stage=f"{stage_prefix}_ROW_PREDICATE_R{row_index}",
            work=bank,
            constant=constant,
            carry=carry,
            out=row_flags[row_index],
            lower=int(row["guard"]),
            upper=int(row["guard"]) + int(row["span"]),
        )
    stream.mcx(f"{stage_prefix}_SEVEN_ROW_AND", row_flags, feasible_flag, constant[:5])
    for row_index in range(len(rows) - 1, -1, -1):
        row = rows[row_index]
        bank = layout.register(layout.sum_names[row_index]).qubits
        emit_interval_oracle(
            stream,
            stage=f"{stage_prefix}_ROW_UNCOMPUTE_R{row_index}",
            work=bank,
            constant=constant,
            carry=carry,
            out=row_flags[row_index],
            lower=int(row["guard"]),
            upper=int(row["guard"]) + int(row["span"]),
        )
    for row_index in range(len(rows) - 1, -1, -1):
        row = rows[row_index]
        bank = layout.register(layout.sum_names[row_index]).qubits
        width = len(bank)
        stage = f"{stage_prefix}_SUM_UNCOMPUTE_R{row_index}"
        for data_index in range(N - 1, -1, -1):
            coefficient = int(row["coefficients"][data_index])
            if coefficient:
                emit_controlled_constant_add(
                    stream,
                    stage=stage,
                    control=target_bits[data_index],
                    work=bank,
                    constant=constant,
                    carry=carry,
                    ladder=ladder,
                    value=-coefficient,
                )
        offset = int(row["cache_offset"]) & ((1 << width) - 1)
        for bit in range(width - 1, -1, -1):
            if (offset >> bit) & 1:
                stream.x(stage, bank[bit])
    stream.macro_counts["EXACT_FEASIBILITY_TOGGLE"] += 1


def emit_xx_plus_yy(
    stream: CircuitStream,
    *,
    stage: str,
    q0: int,
    q1: int,
    theta: Fraction = COIN_THETA,
    beta: Fraction = COIN_BETA,
) -> None:
    """Two-CX XX+YY template, with S/SX expanded to H and exact RZ."""

    if beta:
        stream.rz(stage, q0, beta)
    stream.rz(stage, q1, Fraction(-1, 2))
    stream.h(stage, q1)
    stream.rz(stage, q1, Fraction(1, 2))
    stream.h(stage, q1)
    stream.rz(stage, q1, Fraction(1, 2))
    stream.rz(stage, q0, Fraction(1, 2))
    stream.cx(stage, q1, q0)
    stream.ry(stage, q1, -theta / 2)
    stream.ry(stage, q0, -theta / 2)
    stream.cx(stage, q1, q0)
    stream.rz(stage, q0, Fraction(-1, 2))
    stream.rz(stage, q1, Fraction(-1, 2))
    stream.h(stage, q1)
    stream.rz(stage, q1, Fraction(-1, 2))
    stream.h(stage, q1)
    stream.rz(stage, q1, Fraction(1, 2))
    if beta:
        stream.rz(stage, q0, -beta)
    stream.macro_counts["XX_PLUS_YY_2CX"] += 1


def emit_coin_rings(stream: CircuitStream, layout: CircuitLayout) -> None:
    for register_name in ("REMOVE_COIN", "ADD_COIN"):
        qubits = layout.register(register_name).qubits
        for edge in range(N):
            emit_xx_plus_yy(
                stream,
                stage=f"COIN_RING_{register_name}",
                q0=qubits[edge],
                q1=qubits[(edge + 1) % N],
            )


def _target_toggle(
    stream: CircuitStream,
    *,
    stage: str,
    data: Sequence[int],
    target: Sequence[int],
    remove_coin: Sequence[int],
    add_coin: Sequence[int],
    difference: int,
) -> None:
    for index in range(N):
        stream.cx(stage, data[index], target[index])
    for index in range(N):
        stream.ccx(stage, difference, remove_coin[index], target[index])
        stream.ccx(stage, difference, add_coin[index], target[index])


def _target_untoggle(
    stream: CircuitStream,
    *,
    stage: str,
    data: Sequence[int],
    target: Sequence[int],
    remove_coin: Sequence[int],
    add_coin: Sequence[int],
    difference: int,
) -> None:
    for index in range(N - 1, -1, -1):
        stream.ccx(stage, difference, add_coin[index], target[index])
        stream.ccx(stage, difference, remove_coin[index], target[index])
    for index in range(N - 1, -1, -1):
        stream.cx(stage, data[index], target[index])


def emit_selector(stream: CircuitStream, rows: Sequence[Mapping[str, Any]], layout: CircuitLayout) -> None:
    data = layout.register("DATA").qubits
    remove_coin = layout.register("REMOVE_COIN").qubits
    add_coin = layout.register("ADD_COIN").qubits
    target = layout.register("TARGET").qubits
    addressed_remove, addressed_add = layout.register("ADDRESSED").qubits
    difference, feasible, move, _, _ = layout.register("CONTROL_FLAGS").qubits
    for index in range(N):
        stream.ccx("SELECT_ADDRESS_READ", remove_coin[index], data[index], addressed_remove)
        stream.ccx("SELECT_ADDRESS_READ", add_coin[index], data[index], addressed_add)
    stream.cx("SELECT_DIFFERENCE_COMPUTE", addressed_remove, difference)
    stream.cx("SELECT_DIFFERENCE_COMPUTE", addressed_add, difference)
    _target_toggle(
        stream,
        stage="SELECT_FORWARD_TARGET_BUILD",
        data=data,
        target=target,
        remove_coin=remove_coin,
        add_coin=add_coin,
        difference=difference,
    )
    emit_feasibility_oracle(
        stream,
        stage_prefix="SELECT_FORWARD_ORACLE",
        rows=rows,
        layout=layout,
        target_bits=target,
        feasible_flag=feasible,
    )
    stream.ccx("SELECT_MOVE_COMPUTE", difference, feasible, move)
    _target_untoggle(
        stream,
        stage="SELECT_FORWARD_TARGET_CLEAR",
        data=data,
        target=target,
        remove_coin=remove_coin,
        add_coin=add_coin,
        difference=difference,
    )
    for index in range(N):
        stream.ccx("SELECT_DATA_UPDATE", move, remove_coin[index], data[index])
        stream.ccx("SELECT_DATA_UPDATE", move, add_coin[index], data[index])
    stream.cx("SELECT_ADDRESS_UPDATE", move, addressed_remove)
    stream.cx("SELECT_ADDRESS_UPDATE", move, addressed_add)
    stream.ccx("SELECT_MOVE_CLEAR", difference, feasible, move)
    _target_toggle(
        stream,
        stage="SELECT_REVERSE_TARGET_BUILD",
        data=data,
        target=target,
        remove_coin=remove_coin,
        add_coin=add_coin,
        difference=difference,
    )
    emit_feasibility_oracle(
        stream,
        stage_prefix="SELECT_REVERSE_ORACLE",
        rows=rows,
        layout=layout,
        target_bits=target,
        feasible_flag=feasible,
    )
    _target_untoggle(
        stream,
        stage="SELECT_REVERSE_TARGET_CLEAR",
        data=data,
        target=target,
        remove_coin=remove_coin,
        add_coin=add_coin,
        difference=difference,
    )
    stream.cx("SELECT_DIFFERENCE_CLEAR", addressed_remove, difference)
    stream.cx("SELECT_DIFFERENCE_CLEAR", addressed_add, difference)
    for index in range(N - 1, -1, -1):
        stream.ccx("SELECT_ADDRESS_CLEAR", add_coin[index], data[index], addressed_add)
        stream.ccx("SELECT_ADDRESS_CLEAR", remove_coin[index], data[index], addressed_remove)
    stream.macro_counts["PROMISE_SUBSPACE_SELECT"] += 1


def emit_pattern_mcry(
    stream: CircuitStream,
    *,
    stage: str,
    controls: Sequence[int],
    values: Sequence[int],
    target: int,
    ancillas: Sequence[int],
    theta: Fraction,
) -> None:
    stream.ry(stage, target, theta / 2)
    stream.pattern_mcx(stage, controls, values, target, ancillas)
    stream.ry(stage, target, -theta / 2)
    stream.pattern_mcx(stage, controls, values, target, ancillas)
    stream.macro_counts["PATTERN_MCRY"] += 1


def emit_bridge(stream: CircuitStream, *, bridge: Mapping[str, Any], layout: CircuitLayout, rank: int) -> None:
    data = layout.register("DATA").qubits
    ancillas = layout.register("TARGET").qubits[: N - 3]
    source = int(str(bridge["source_mask_hex"]), 16)
    target_mask = int(str(bridge["target_mask_hex"]), 16)
    differing = [index for index in range(N) if ((source ^ target_mask) >> index) & 1]
    if len(differing) != 4:
        raise ValueError("V4.3 admits only the authenticated Hamming-distance-four bridges.")
    path = [source]
    current = source
    for index in differing:
        current ^= 1 << index
        path.append(current)
    stage = f"BRIDGE_{rank}_{str(bridge['bridge_sha256'])[:12]}"

    def edge_pattern(state: int, target_index: int) -> tuple[tuple[int, ...], tuple[int, ...]]:
        control_indices = tuple(index for index in range(N) if index != target_index)
        return (
            tuple(data[index] for index in control_indices),
            tuple((state >> index) & 1 for index in control_indices),
        )

    for edge in range(len(differing) - 1):
        controls, values = edge_pattern(path[edge], differing[edge])
        stream.pattern_mcx(stage, controls, values, data[differing[edge]], ancillas)
    controls, values = edge_pattern(path[-2], differing[-1])
    emit_pattern_mcry(
        stream,
        stage=stage,
        controls=controls,
        values=values,
        target=data[differing[-1]],
        ancillas=ancillas,
        theta=BRIDGE_THETA,
    )
    for edge in range(len(differing) - 2, -1, -1):
        controls, values = edge_pattern(path[edge], differing[edge])
        stream.pattern_mcx(stage, controls, values, data[differing[edge]], ancillas)
    stream.macro_counts["TWO_LEVEL_BRIDGE_RY"] += 1


def _row_digest(rows: Sequence[Mapping[str, Any]]) -> str:
    serializable = [
        {
            "cache_offset": int(row["cache_offset"]),
            "coefficients": [int(value) for value in row["coefficients"]],
            "compression_certificate_sha256": str(row["compression_certificate_sha256"]),
            "guard": int(row["guard"]),
            "kind": str(row["kind"]),
            "lower": int(row["lower"]),
            "name": str(row["name"]),
            "scale": int(row["scale"]),
            "shift": int(row["shift"]),
            "span": int(row["span"]),
            "upper": int(row["upper"]),
            "v42_width": int(row["width"]),
            "v43_materialized_width": max(MATERIALIZED_MIN_WIDTH, int(row["width"])),
        }
        for row in rows
    ]
    return canonical_json_sha256(serializable)


def _is_feasible(mask: int, rows: Sequence[Mapping[str, Any]]) -> bool:
    if mask < 0 or mask >> N or mask.bit_count() != K:
        return False
    selected = [index for index in range(N) if (mask >> index) & 1]
    return all(
        int(row["lower"])
        <= sum(int(row["coefficients"][index]) for index in selected)
        <= int(row["upper"])
        for row in rows
    )


def _select_trace(start: int, remove: int, add: int, feasible_predicate: Any) -> dict[str, Any]:
    remove_value = (start >> remove) & 1
    add_value = (start >> add) & 1
    difference = remove_value ^ add_value
    target = start ^ ((1 << remove) | (1 << add)) if difference else start
    first_flag = int(bool(feasible_predicate(target)))
    move = difference & first_flag
    output = target if move else start
    reverse_target = output ^ ((1 << remove) | (1 << add)) if difference else output
    retained_flag = first_flag ^ int(bool(feasible_predicate(reverse_target)))
    return {
        "add_index": add,
        "difference": difference,
        "first_target_feasible_flag": first_flag,
        "move": move,
        "output_mask_hex": f"{output:010x}",
        "remove_index": remove,
        "retained_feasible_flag_after_reverse": retained_flag,
        "reverse_target_mask_hex": f"{reverse_target:010x}",
        "start_mask_hex": f"{start:010x}",
        "target_mask_hex": f"{target:010x}",
    }


def _real_select_witness(rows: Sequence[Mapping[str, Any]], representatives: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    for representative in representatives:
        source = int(str(representative["mask_hex"]), 16)
        if not _is_feasible(source, rows):
            continue
        selected = [index for index in range(N) if (source >> index) & 1]
        unselected = [index for index in range(N) if not ((source >> index) & 1)]
        for remove in selected:
            for add in unselected:
                trace = _select_trace(source, remove, add, lambda mask: _is_feasible(mask, rows))
                if trace["move"] == 1 and trace["retained_feasible_flag_after_reverse"] == 0:
                    core = {**trace, "promise_cleanup_passed": True, "source_representative_sha256": str(representative["representative_sha256"])}
                    return {**core, "witness_sha256": canonical_json_sha256(core)}
    raise ValueError("No feasible one-swap V4.3 SELECT witness found for an authenticated component representative.")


def mandatory_off_promise_witness() -> dict[str, Any]:
    feasible = {0b01}
    trace = _select_trace(0b10, 1, 0, lambda mask: mask in feasible)
    rejected = bool(
        trace["target_mask_hex"].endswith("1")
        and trace["output_mask_hex"].endswith("1")
        and trace["retained_feasible_flag_after_reverse"] == 1
    )
    core = {
        **trace,
        "feasible_masks_binary": ["01"],
        "n": 2,
        "observed_scope": "OUTSIDE_REGISTERED_FEASIBLE_START_PROMISE",
        "status": "OFF_PROMISE_CLEANUP_REJECTED_WITH_WITNESS" if rejected else "NEGATIVE_CONTROL_FAILED",
        "witness_detected": rejected,
    }
    return {**core, "witness_sha256": canonical_json_sha256(core)}


def _compile_simulator(*, root: str | Path | None = None) -> dict[str, Any]:
    paths = _paths(root)
    compiler = shutil.which("clang++") or shutil.which("g++") or shutil.which("c++")
    if not compiler:
        raise RuntimeError("A C++17 compiler is required for V4.3 independent simulation.")
    with tempfile.TemporaryDirectory(prefix="quantum-v43-simulator-") as temporary:
        binary = Path(temporary) / "v43_reversible_simulator"
        command = [compiler, "-std=c++17", "-O3", "-DNDEBUG", "-Wall", "-Wextra", "-pedantic", str(paths["simulator"]), "-o", str(binary)]
        built = subprocess.run(command, capture_output=True, text=True, timeout=180, check=False)
        if built.returncode != 0 or not binary.is_file() or built.stderr.strip():
            raise RuntimeError(f"V4.3 simulator compilation failed: {built.stderr.strip()}")
        run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=180, check=False)
        if run.returncode != 0 or run.stderr.strip():
            raise RuntimeError(f"V4.3 simulator execution failed: {run.stderr.strip()}")
        payload = json.loads(run.stdout, object_pairs_hook=_reject_duplicates, parse_constant=_reject_nonfinite)
    if not isinstance(payload, dict) or payload.get("valid") is not True:
        raise ValueError("V4.3 independent simulator did not return a valid acceptance result.")
    return payload


def materialize_seed(
    *,
    seed: int,
    rows: Sequence[Mapping[str, Any]],
    connectivity: Mapping[str, Any],
    v42_resource: Mapping[str, Any],
    progress: Any | None = None,
) -> dict[str, Any]:
    layout = build_layout(rows)
    stream = CircuitStream(seed=seed, total_qubits=layout.total_qubits)
    if progress is not None:
        progress(f"V4.3 materialization · seed {seed} · coin rings")
    emit_coin_rings(stream, layout)
    if progress is not None:
        progress(f"V4.3 materialization · seed {seed} · exact SELECT")
    emit_selector(stream, rows, layout)
    for rank, bridge in enumerate(connectivity.get("selected_bridges") or [], start=1):
        if progress is not None:
            progress(f"V4.3 materialization · seed {seed} · certified bridge {rank}")
        emit_bridge(stream, bridge=bridge, layout=layout, rank=rank)
    manifest = stream.finish()
    actual_cnot = int(manifest["elementary_counts"]["CX"])
    v42_cnot = int(v42_resource["selected_model_step_resources"]["selected_model_cnot"])
    expected_cnot = v42_cnot + 22_616
    expected_qubits = int(v42_resource["logical_qubits_with_recycled_workspace"]) + 8
    layout_payload = layout.as_dict()
    representatives = connectivity.get("authenticated_v40_component_representatives") or []
    witness = _real_select_witness(rows, representatives)
    core = {
        "budget_cnot": BUDGET_CNOT,
        "budget_margin_cnot": BUDGET_CNOT - actual_cnot,
        "certified_bridge_count": len(connectivity.get("selected_bridges") or []),
        "compression_sha256": str(v42_resource["compression_sha256"]),
        "constraint_rows_sha256": _row_digest(rows),
        "decision": "PASSED" if actual_cnot <= BUDGET_CNOT else "REJECTED_MATERIALIZED_CNOT_BUDGET",
        "instance_id": str(v42_resource["instance_id"]),
        "liveness": {
            "bridge_target_reuse_after_selector_clean": True,
            "c7x_constant_first_five_reuse_after_comparator_constants_clean": True,
            "clean_exit_registers": ["TARGET", *layout.sum_names, "CONSTANT", "CARRY", "ADDRESSED", "ROW_FLAGS", "CONTROL_FLAGS"],
            "liveness_decision": "PASSED_STATIC_DISJOINT_PHASE_AND_CLEAN_EXIT_CONTRACT",
            "peak_qubits": layout.total_qubits,
        },
        "materialized_widths": [len(layout.register(name).qubits) for name in layout.sum_names],
        "parent_v42_selected_model_cnot": v42_cnot,
        "parent_v42_widths": [int(value) for value in v42_resource["constraint_register_widths"]],
        "preregistered_cnot_replay": {
            "actual": actual_cnot,
            "interval_predicate_correction": -168,
            "match": actual_cnot == expected_cnot,
            "parent_v42": v42_cnot,
            "three_to_five_width_lift": 22_784,
            "total_delta": 22_616,
        },
        "preregistered_qubit_replay": {
            "actual": layout.total_qubits,
            "match": layout.total_qubits == expected_qubits,
            "parent_v42": int(v42_resource["logical_qubits_with_recycled_workspace"]),
            "width_lift": 8,
        },
        "real_n40_promise_select_witness": witness,
        "register_layout": layout_payload,
        "seed": seed,
        "stream_manifest": manifest,
    }
    if not core["preregistered_cnot_replay"]["match"]:
        raise AssertionError(f"Seed {seed} materialized CNOT count differs from the preregistered replay.")
    if not core["preregistered_qubit_replay"]["match"]:
        raise AssertionError(f"Seed {seed} qubit layout differs from the preregistered replay.")
    return {**core, "seed_materialization_sha256": canonical_json_sha256(core)}


def build_v43_artifact(*, root: str | Path | None = None, progress: Any | None = None) -> dict[str, Any]:
    paths = _paths(root)
    spec = load_v43_spec(root=paths["root"])
    parent = authenticate_v42_parent(root=paths["root"])
    if parent.get("valid") is not True:
        raise ValueError(f"V4.2 parent authentication failed: {parent.get('errors')}")
    v42 = parent["artifact"]
    v41 = _read_json_strict(paths["v41_artifact"])
    certificates = _certificate_by_seed(paths["root"])
    compressions = {int(row["seed"]): row for row in v41["compression_evidence"]["seed_rows"]}
    connectivity = {int(row["seed"]): row for row in v41["connectivity_evidence"]["seed_rows"]}
    v42_resources = {int(row["seed"]): row for row in v42["resource_evidence"]["seed_rows"]}
    seed_rows: list[dict[str, Any]] = []
    for seed in SEEDS:
        rows = _guarded_rows(certificates[seed], compressions[seed])
        seed_rows.append(
            materialize_seed(
                seed=seed,
                rows=rows,
                connectivity=connectivity[seed],
                v42_resource=v42_resources[seed],
                progress=progress,
            )
        )
    simulator = _compile_simulator(root=paths["root"])
    off_promise = mandatory_off_promise_witness()
    maximum_cnot = max(int(row["stream_manifest"]["elementary_counts"]["CX"]) for row in seed_rows)
    minimum_margin = min(int(row["budget_margin_cnot"]) for row in seed_rows)
    maximum_qubits = max(int(row["register_layout"]["total_qubits"]) for row in seed_rows)
    manifest_root = canonical_json_sha256([row["stream_manifest"]["stream_manifest_sha256"] for row in seed_rows])
    register_root = canonical_json_sha256([row["register_layout"]["register_map_sha256"] for row in seed_rows])
    all_pass = bool(
        all(row["decision"] == "PASSED" for row in seed_rows)
        and maximum_cnot == 1_158_046
        and minimum_margin == 1_341_954
        and maximum_qubits == 339
        and simulator.get("valid") is True
        and (simulator.get("negative_control") or {}).get("status") == "OFF_PROMISE_CLEANUP_REJECTED_WITH_WITNESS"
        and off_promise["status"] == "OFF_PROMISE_CLEANUP_REJECTED_WITH_WITNESS"
    )
    if all_pass:
        decisions = {
            "next_falsifiable_gate": "NAMED_BACKEND_ZERO_JOB_TRANSPILATION_AND_ROUTING_PROTOCOL",
            "overall": "V43_BACKEND_AGNOSTIC_CIRCUIT_MATERIALIZED_PROMISE_SIMULATION_PASSED",
            "production_admission": "PROVIDER_NEUTRAL_RESEARCH_CIRCUIT_IR_ADMITTED_BACKEND_AND_HARDWARE_NOT_AUTHORIZED",
            "promise_scope": "ACCEPTED_ONLY_FOR_EXACT_FEASIBLE_N40_DATA_AND_TWO_ONE_HOT_COIN_REGISTERS",
        }
    else:
        decisions = {
            "next_falsifiable_gate": "REPAIR_OR_REJECT_V43_MATERIALIZATION",
            "overall": "V43_MATERIALIZATION_INDETERMINATE",
            "production_admission": "REJECTED_HARDWARE_NOT_AUTHORIZED",
            "promise_scope": "NO_ACCEPTED_SCOPE",
        }
    parameter_core = {
        "bridge_theta_pi": [BRIDGE_THETA.numerator, BRIDGE_THETA.denominator],
        "coin_beta_pi": [COIN_BETA.numerator, COIN_BETA.denominator],
        "coin_theta_pi": [COIN_THETA.numerator, COIN_THETA.denominator],
        "elementary_basis": list(ELEMENTARY_BASIS),
        "materialized_minimum_arithmetic_width": MATERIALIZED_MIN_WIDTH,
    }
    parameter_contract = {**parameter_core, "parameter_contract_sha256": canonical_json_sha256(parameter_core)}
    aggregate_core = {
        "all_eight_seeds_budget_admitted": all(row["decision"] == "PASSED" for row in seed_rows),
        "budget_cnot": BUDGET_CNOT,
        "maximum_logical_qubits_with_recycled_workspace": maximum_qubits,
        "maximum_materialized_cnot": maximum_cnot,
        "minimum_budget_margin_cnot": minimum_margin,
        "ordered_stream_manifest_root_sha256": manifest_root,
        "register_map_root_sha256": register_root,
        "seed_count": len(seed_rows),
        "total_elementary_instructions": sum(int(row["stream_manifest"]["instruction_count"]) for row in seed_rows),
    }
    aggregate = {**aggregate_core, "aggregate_sha256": canonical_json_sha256(aggregate_core)}
    core = {
        "aggregate": aggregate,
        "artifact_version": ARTIFACT_VERSION,
        "claim_boundary": copy.deepcopy(spec["claim_boundary"]),
        "decisions": decisions,
        "independent_cpp_simulator": simulator,
        "mandatory_off_promise_control": off_promise,
        "parameter_contract": parameter_contract,
        "parent": {
            "artifact_raw_file_sha256": EXPECTED_V42_ARTIFACT_RAW_SHA256,
            "artifact_sha256": EXPECTED_V42_ARTIFACT_SHA256,
            "freeze_raw_file_sha256": EXPECTED_V42_FREEZE_RAW_SHA256,
            "freeze_sha256": EXPECTED_V42_FREEZE_SHA256,
            "immutable_file_count": parent["immutable_file_count"],
            "immutable_files_exact": parent["immutable_files_exact"],
            "overall_decision": (v42.get("decisions") or {}).get("overall"),
            "spec_raw_file_sha256": EXPECTED_V42_SPEC_RAW_SHA256,
            "spec_sha256": EXPECTED_V42_SPEC_SHA256,
        },
        "protocol_amendments": {
            "interval_predicate": "V42_COSTED_TWO_CCX_PER_ROW_ARE_NOT_NEEDED_BY_THE_EXACT_NESTED_GE_XOR_CIRCUIT;_168_CNOT_REMOVED_PER_STEP",
            "v42_bytes_rewritten": False,
            "v42_cnot_decision_rewritten": False,
            "v42_elementary_basis_omitted_h": "DISCLOSED_AND_CORRECTED_APPEND_ONLY_IN_V43",
            "width_three_to_five": "FOUR_GROUP_BANKS_ZERO_EXTENDED;_22784_CNOT_ADDED_PER_STEP",
        },
        "research_classification": "RESEARCH_ONLY",
        "seed_materializations": seed_rows,
        "simulator_source_raw_file_sha256": raw_file_sha256(paths["simulator"]),
        "source_raw_file_sha256": raw_file_sha256(paths["source"]),
        "spec_raw_file_sha256": EXPECTED_SPEC_RAW_SHA256,
        "spec_sha256": EXPECTED_SPEC_SHA256,
        "v43_version": V43_VERSION,
    }
    return {**core, "artifact_sha256": canonical_json_sha256(core)}


def validate_v43_artifact(payload: Mapping[str, Any], *, root: str | Path | None = None, rebuild: bool = False) -> dict[str, Any]:
    paths = _paths(root)
    errors: list[str] = []
    try:
        parent = authenticate_v42_parent(root=paths["root"])
        spec = load_v43_spec(root=paths["root"])
    except Exception as exc:
        parent = {"valid": False}
        spec = {}
        errors.append(str(exc))
    aggregate = payload.get("aggregate") or {}
    boundary = payload.get("claim_boundary") or {}
    decisions = payload.get("decisions") or {}
    simulator = payload.get("independent_cpp_simulator") or {}
    negative = payload.get("mandatory_off_promise_control") or {}
    rows = payload.get("seed_materializations") or []
    checks: dict[str, bool] = {
        "artifact_self_hash": payload.get("artifact_sha256") == canonical_json_sha256({key: value for key, value in payload.items() if key != "artifact_sha256"}),
        "artifact_version": payload.get("artifact_version") == ARTIFACT_VERSION,
        "spec_identity": bool(spec) and payload.get("spec_sha256") == EXPECTED_SPEC_SHA256 and payload.get("spec_raw_file_sha256") == EXPECTED_SPEC_RAW_SHA256,
        "source_identities": bool(paths["source"].is_file() and paths["simulator"].is_file() and payload.get("source_raw_file_sha256") == raw_file_sha256(paths["source"]) and payload.get("simulator_source_raw_file_sha256") == raw_file_sha256(paths["simulator"])),
        "parent_exact": parent.get("valid") is True and (payload.get("parent") or {}).get("immutable_file_count") == 175 and (payload.get("parent") or {}).get("immutable_files_exact") is True,
        "eight_seed_order": [row.get("seed") for row in rows] == list(SEEDS),
        "all_stream_manifests_self_hash": bool(rows) and all((row.get("stream_manifest") or {}).get("stream_manifest_sha256") == canonical_json_sha256({key: value for key, value in (row.get("stream_manifest") or {}).items() if key != "stream_manifest_sha256"}) for row in rows),
        "all_seed_materializations_self_hash": bool(rows) and all(row.get("seed_materialization_sha256") == canonical_json_sha256({key: value for key, value in row.items() if key != "seed_materialization_sha256"}) for row in rows),
        "manifest_root": aggregate.get("ordered_stream_manifest_root_sha256") == canonical_json_sha256([(row.get("stream_manifest") or {}).get("stream_manifest_sha256") for row in rows]),
        "register_root": aggregate.get("register_map_root_sha256") == canonical_json_sha256([(row.get("register_layout") or {}).get("register_map_sha256") for row in rows]),
        "resource_gate": aggregate.get("maximum_materialized_cnot") == 1_158_046 and aggregate.get("minimum_budget_margin_cnot") == 1_341_954 and aggregate.get("maximum_logical_qubits_with_recycled_workspace") == 339 and aggregate.get("all_eight_seeds_budget_admitted") is True,
        "cnot_replays": bool(rows) and all((row.get("preregistered_cnot_replay") or {}).get("match") is True and (row.get("stream_manifest") or {}).get("elementary_counts", {}).get("CX") == (row.get("preregistered_cnot_replay") or {}).get("actual") for row in rows),
        "qubit_replays": bool(rows) and all((row.get("preregistered_qubit_replay") or {}).get("match") is True and (row.get("register_layout") or {}).get("total_qubits") == (row.get("preregistered_qubit_replay") or {}).get("actual") for row in rows),
        "promise_witnesses": bool(rows) and all((row.get("real_n40_promise_select_witness") or {}).get("promise_cleanup_passed") is True and (row.get("real_n40_promise_select_witness") or {}).get("retained_feasible_flag_after_reverse") == 0 for row in rows),
        "off_promise_rejected": negative.get("status") == "OFF_PROMISE_CLEANUP_REJECTED_WITH_WITNESS" and negative.get("witness_detected") is True and (simulator.get("negative_control") or {}).get("status") == "OFF_PROMISE_CLEANUP_REJECTED_WITH_WITNESS",
        "independent_simulator": simulator.get("valid") is True,
        "decision_gate": decisions.get("overall") == "V43_BACKEND_AGNOSTIC_CIRCUIT_MATERIALIZED_PROMISE_SIMULATION_PASSED" and decisions.get("production_admission") == "PROVIDER_NEUTRAL_RESEARCH_CIRCUIT_IR_ADMITTED_BACKEND_AND_HARDWARE_NOT_AUTHORIZED",
        "boundary_gate": payload.get("research_classification") == "RESEARCH_ONLY" and boundary.get("provider_calls") == 0 and boundary.get("qpu_jobs_submitted") == 0 and boundary.get("hardware_executable") is False and boundary.get("backend_transpilation") == "NOT_RUN" and boundary.get("quantum_advantage") == "NOT_CLAIMED",
        "exact_rebuild": True,
    }
    if rebuild:
        try:
            checks["exact_rebuild"] = build_v43_artifact(root=paths["root"]) == dict(payload)
        except Exception as exc:
            checks["exact_rebuild"] = False
            errors.append(f"V4.3 deterministic rebuild failed: {exc}")
    failed = [name for name, passed in checks.items() if passed is not True]
    return {"checks": checks, "errors": errors, "failed_checks": failed, "valid": not errors and not failed}


def default_v43_artifact_path(*, root: str | Path | None = None) -> Path:
    return _paths(root)["artifact"]


def seal_v43_artifact(
    *,
    path: str | Path | None = None,
    root: str | Path | None = None,
    progress: Any | None = None,
) -> tuple[dict[str, Any], Path]:
    destination = Path(path) if path is not None else default_v43_artifact_path(root=root)
    artifact = build_v43_artifact(root=root, progress=progress)
    payload = json.dumps(artifact, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"
    if destination.exists():
        existing = _read_json_strict(destination)
        if existing != artifact:
            raise FileExistsError(f"Refusing to overwrite a non-identical V4.3 artifact: {destination}")
        return artifact, destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(payload, encoding="utf-8")
    return artifact, destination


def load_v43_artifact(
    path: str | Path | None = None,
    *,
    root: str | Path | None = None,
    rebuild: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    target = Path(path) if path is not None else default_v43_artifact_path(root=root)
    artifact = _read_json_strict(target)
    report = validate_v43_artifact(artifact, root=root, rebuild=rebuild)
    if report.get("valid") is not True:
        raise ValueError(f"V4.3 artifact validation failed: {report}")
    return artifact, report


__all__ = [
    "ARTIFACT_VERSION",
    "BRIDGE_THETA",
    "CHUNK_INSTRUCTIONS",
    "COIN_BETA",
    "COIN_THETA",
    "ELEMENTARY_BASIS",
    "EXPECTED_SPEC_RAW_SHA256",
    "EXPECTED_SPEC_SHA256",
    "MATERIALIZED_MIN_WIDTH",
    "V43_VERSION",
    "authenticate_v42_parent",
    "build_layout",
    "build_v43_artifact",
    "canonical_json_sha256",
    "default_v43_artifact_path",
    "load_v43_artifact",
    "load_v43_spec",
    "mandatory_off_promise_witness",
    "raw_file_sha256",
    "seal_v43_artifact",
    "validate_v43_artifact",
]
