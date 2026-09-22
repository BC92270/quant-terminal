"""Quantum Lab V4.5 proof-carrying logical-width reduction.

V4.5 is an append-only research successor to the authenticated V4.4 release.
It replaces the two forty-qubit one-hot coin registers with exact six-qubit
binary-address encodings, streams each proposed target bit through one clean
flag, and uses Bennett compute/copy/uncompute to recycle one arithmetic bank
across all seven constraint rows.  The resulting allocation is ``67 + 2*w``
logical qubits, where ``w`` is the largest authenticated row width (145
qubits at the observed maximum ``w=39``).

The compiler is provider neutral.  It imports no provider SDK, reads no
credentials, performs no network operation, selects no live backend and
submits no simulator or QPU job.  Its output remains RESEARCH_ONLY and is not
evidence of current hardware calibration, routed performance, fidelity,
utility or quantum advantage.
"""

from __future__ import annotations

import argparse
import copy
from dataclasses import dataclass
from fractions import Fraction
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .phase3_v41_certified_bridge_compiler import _certificate_by_seed, _guarded_rows
from .phase3_v42_coined_walk_compiler import BUDGET_CNOT, K, N, SEEDS
from .phase3_v43_reversible_circuit_ir import (
    BRIDGE_THETA,
    COIN_THETA,
    CircuitStream,
    emit_controlled_constant_add,
    emit_interval_oracle,
)


V45_VERSION = "PHASE III · V4.5 PROOF-CARRYING WIDTH REDUCTION · V1"
ARTIFACT_VERSION = "PHASE III · V4.5 SEALED PROOF-CARRYING WIDTH REDUCTION · V1"
SPEC_FILENAME = "PHASE_III_V4_5_PROOF_CARRYING_WIDTH_REDUCTION_SPEC_V1.json"
LIVENESS_CERTIFICATE_FILENAME = "PHASE_III_V4_5_REGISTER_LIVENESS_CERTIFICATE_V1.json"
DEFAULT_ARTIFACT_NAME = "SEALED_V4_5_PROOF_CARRYING_WIDTH_REDUCTION_ARTIFACT.json"

# These two preregistration identities are deliberately patched only after the
# result-blind V4.5 specification is sealed.  Artifact construction fails
# closed while either placeholder remains.
EXPECTED_SPEC_RAW_SHA256 = "fca97bae23543fccb04ba7ca606fa2abb9e4c6e4ebeae3c1501031967a3bfea2"
EXPECTED_SPEC_SHA256 = "ba0c41d1bd0d43817a46c9d66d84eb2ba517bf8dd3975387324726d24487e4e6"

EXPECTED_V44_FREEZE_RAW_SHA256 = "f7b4507410aee41e409b3a0a1ce36ba1adff38299dc8a2d424e13885598ada13"
EXPECTED_V44_FREEZE_SHA256 = "e17aa8ce04c97416f7f0565f2eda4f16b739c5c921fb58ee25752a546ffe95b3"
EXPECTED_V44_PATH_FINGERPRINT = "eb4fda2c2b862fa279a7f0d60f0a2694e50f9c63bf89f60de9d0af52638c0516"
EXPECTED_V44_FROZEN_FILE_COUNT = 211
EXPECTED_V44_IMMUTABLE_FILE_COUNT = 209
EXPECTED_V44_ARTIFACT_RAW_SHA256 = "3b6824965fa7b2829981d6d35eec5413a24f7340719613e7cd2e8512d6285488"
EXPECTED_V44_ARTIFACT_SHA256 = "de1ba4194a0f7220b1cfcb0c61f8faed3f187c0e9c7712775cba53fa79ed98bb"
EXPECTED_V43_ARTIFACT_RAW_SHA256 = "626123fda2ee6561fe74cbb073a03f9987ccbd4e3d01c84b4f2815023e8271e3"
EXPECTED_V43_ARTIFACT_SHA256 = "36a7a63410da87ce7f98bb10e6d3af3c3d784d9f8e520a6771e42cda9ee593ce"

TARGET_LOGICAL_QUBITS = 156
ADDRESS_WIDTH = 6
VALID_ADDRESS_COUNT = 40
ROW_COUNT = 7
CONTROL_FLAG_COUNT = 5
MIN_ARITHMETIC_WIDTH = 5
BRIDGE_LADDER_QUBITS = N - 3
SUCCESSOR_MUTABLE = frozenset({"quantum_research_lab/README.md", "quantum_research_lab/ui.py"})


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


def read_json_strict(path: str | Path) -> dict[str, Any]:
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
        "liveness_certificate": base / "quantum_research_lab" / LIVENESS_CERTIFICATE_FILENAME,
        "source": base / "quantum_research_lab" / "phase3_v45_proof_carrying_width_reduction.py",
        "checker": base / "quantum_research_lab" / "phase3_v45_width_proof_checker.py",
        "v44_freeze": base / "FREEZE_CONTRACT_V4_4.json",
        "v44_artifact": base / "outputs/quantum_phase3/v44_named_backend/SEALED_V4_4_NAMED_BACKEND_ZERO_JOB_ARTIFACT.json",
        "v43_artifact": base / "outputs/quantum_phase3/v43_reversible_circuit/SEALED_V4_3_REVERSIBLE_CIRCUIT_ARTIFACT.json",
        "v41_artifact": base / "outputs/quantum_phase3/v41_certified_bridge/SEALED_V4_1_CERTIFIED_BRIDGE_COMPILER_ARTIFACT.json",
        "artifact": base / "outputs/quantum_phase3/v45_width_reduction" / DEFAULT_ARTIFACT_NAME,
    }


def _path_fingerprint(paths: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(sorted(paths), separators=(",", ":")).encode("utf-8")).hexdigest()


def _is_finalized_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def load_v45_spec(path: str | Path | None = None, *, root: str | Path | None = None) -> dict[str, Any]:
    """Load the result-blind preregistration, failing closed before hash patching."""

    if not (_is_finalized_sha256(EXPECTED_SPEC_RAW_SHA256) and _is_finalized_sha256(EXPECTED_SPEC_SHA256)):
        raise RuntimeError("V4.5 preregistration identities have not been finalized.")
    target = Path(path) if path is not None else _paths(root)["spec"]
    if raw_file_sha256(target) != EXPECTED_SPEC_RAW_SHA256:
        raise ValueError("V4.5 specification raw identity mismatch.")
    payload = read_json_strict(target)
    core = {key: value for key, value in payload.items() if key not in {"v45_spec_sha", "v45_spec_sha256"}}
    digest = canonical_json_sha256(core)
    boundary = payload.get("claim_boundary") or {}
    chronology = payload.get("chronology") or {}
    if not (
        digest == EXPECTED_SPEC_SHA256
        and payload.get("v45_spec_sha256") == digest
        and payload.get("v45_spec_sha") == digest[:20].upper()
        and chronology.get("result_state_at_seal") == "NOT_EVALUATED"
        and boundary.get("research_classification") == "RESEARCH_ONLY"
        and boundary.get("provider_calls") == 0
        and boundary.get("network_calls") == 0
        and boundary.get("qpu_jobs_submitted") == 0
        and boundary.get("hardware_executable") is False
        and boundary.get("quantum_advantage") == "NOT_CLAIMED"
    ):
        raise ValueError("V4.5 specification semantic identity or claim boundary mismatch.")
    return payload


def authenticate_v44_parent(*, root: str | Path | None = None) -> dict[str, Any]:
    """Authenticate V4.4 plus every path immutable to this successor."""

    paths = _paths(root)
    errors: list[str] = []
    try:
        freeze = read_json_strict(paths["v44_freeze"])
        frozen = freeze.get("frozen_files") or {}
        freeze_core = {key: value for key, value in freeze.items() if key != "freeze_contract_sha256"}
        freeze_valid = bool(
            raw_file_sha256(paths["v44_freeze"]) == EXPECTED_V44_FREEZE_RAW_SHA256
            and canonical_json_sha256(freeze_core)
            == freeze.get("freeze_contract_sha256")
            == EXPECTED_V44_FREEZE_SHA256
            and isinstance(frozen, dict)
            and len(frozen) == freeze.get("frozen_file_count") == EXPECTED_V44_FROZEN_FILE_COUNT
            and _path_fingerprint(frozen)
            == freeze.get("frozen_paths_fingerprint_sha256")
            == EXPECTED_V44_PATH_FINGERPRINT
        )
    except Exception as exc:
        freeze, frozen, freeze_valid = {}, {}, False
        errors.append(f"V4.4 freeze authentication failed: {exc}")
    if not freeze_valid:
        errors.append("V4.4 freeze raw, semantic or inventory identity mismatch.")

    immutable = {
        str(relative): str(expected)
        for relative, expected in frozen.items()
        if str(relative) not in SUCCESSOR_MUTABLE
    } if isinstance(frozen, Mapping) else {}
    mismatches: list[str] = []
    for relative, expected in sorted(immutable.items()):
        candidate = paths["root"] / relative
        if not candidate.is_file() or candidate.is_symlink() or raw_file_sha256(candidate) != expected:
            mismatches.append(relative)
    if len(immutable) != EXPECTED_V44_IMMUTABLE_FILE_COUNT or mismatches:
        errors.append(
            "V4.4 immutable path authentication failed: "
            f"count={len(immutable)} mismatches={mismatches[:5]}"
        )

    try:
        artifact = read_json_strict(paths["v44_artifact"])
        artifact_core = {key: value for key, value in artifact.items() if key != "artifact_sha256"}
        decisions = artifact.get("decisions") or {}
        artifact_valid = bool(
            raw_file_sha256(paths["v44_artifact"]) == EXPECTED_V44_ARTIFACT_RAW_SHA256
            and canonical_json_sha256(artifact_core)
            == artifact.get("artifact_sha256")
            == EXPECTED_V44_ARTIFACT_SHA256
            and decisions.get("overall")
            == "V44_FAKE_MARRAKESH_CAPACITY_REJECTED_CANARY_PIPELINE_VALIDATED_ZERO_JOB"
            and decisions.get("next_falsifiable_gate")
            == "PROOF_CARRYING_WIDTH_REDUCTION_TO_156_QUBITS_OR_LOWER_WITH_EXACT_PROMISE_PARITY"
        )
    except Exception as exc:
        artifact, artifact_valid = {}, False
        errors.append(f"V4.4 artifact authentication failed: {exc}")
    if not artifact_valid:
        errors.append("V4.4 artifact raw, semantic or scientific-decision mismatch.")

    try:
        v43 = read_json_strict(paths["v43_artifact"])
        v43_core = {key: value for key, value in v43.items() if key != "artifact_sha256"}
        v43_valid = bool(
            raw_file_sha256(paths["v43_artifact"]) == EXPECTED_V43_ARTIFACT_RAW_SHA256
            and canonical_json_sha256(v43_core)
            == v43.get("artifact_sha256")
            == EXPECTED_V43_ARTIFACT_SHA256
        )
    except Exception as exc:
        v43, v43_valid = {}, False
        errors.append(f"V4.3 artifact authentication failed: {exc}")
    if not v43_valid:
        errors.append("V4.3 artifact identity mismatch inside the V4.4 frozen closure.")

    return {
        "artifact": artifact,
        "errors": list(dict.fromkeys(errors)),
        "freeze": freeze,
        "immutable_file_count": len(immutable),
        "immutable_files_exact": len(immutable) == EXPECTED_V44_IMMUTABLE_FILE_COUNT and not mismatches,
        "v43_artifact": v43,
        "valid": not errors,
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
        return {
            "name": self.name,
            "qubit_ids": list(self.qubits),
            "role": self.role,
            "start": self.start,
            "width": self.width,
        }


@dataclass(frozen=True)
class CircuitLayout:
    registers: tuple[Register, ...]
    total_qubits: int
    arithmetic_width: int

    def register(self, name: str) -> Register:
        for register in self.registers:
            if register.name == name:
                return register
        raise KeyError(name)

    def bridge_pool(self) -> tuple[int, ...]:
        pool = self.register("SUM_WORK").qubits + self.register("CONSTANT").qubits
        if len(pool) < BRIDGE_LADDER_QUBITS:
            raise ValueError("The cleaned arithmetic workspace cannot supply the bridge ladder.")
        return pool[:BRIDGE_LADDER_QUBITS]

    def as_dict(self) -> dict[str, Any]:
        core = {
            "allocation_formula": "67+2W",
            "arithmetic_width": self.arithmetic_width,
            "registers": [register.as_dict() for register in self.registers],
            "total_qubits": self.total_qubits,
        }
        return {**core, "register_map_sha256": canonical_json_sha256(core)}


def build_layout(rows: Sequence[Mapping[str, Any]]) -> CircuitLayout:
    if len(rows) != ROW_COUNT:
        raise ValueError("V4.5 requires exactly seven authenticated constraint rows.")
    width = max(max(MIN_ARITHMETIC_WIDTH, int(row["width"])) for row in rows)
    registers: list[Register] = []
    cursor = 0

    def allocate(name: str, register_width: int, role: str) -> None:
        nonlocal cursor
        registers.append(Register(name=name, start=cursor, width=register_width, role=role))
        cursor += register_width

    allocate("DATA", N, "PERSISTENT_PORTFOLIO_BASIS")
    allocate("REMOVE_ADDR", ADDRESS_WIDTH, "PERSISTENT_BINARY_ADDRESS_VALID_0_TO_39")
    allocate("ADD_ADDR", ADDRESS_WIDTH, "PERSISTENT_BINARY_ADDRESS_VALID_0_TO_39")
    allocate("SUM_WORK", width, "BENNETT_RECYCLED_SEVEN_ROW_SUM_BANK_AND_POST_SELECTOR_BRIDGE_POOL")
    allocate("CONSTANT", width, "REUSABLE_CLASSICAL_CONSTANT_MCX_LADDER_AND_POST_SELECTOR_BRIDGE_POOL")
    allocate("CARRY", 1, "CLEAN_CUCCARO_CARRY")
    allocate("ADDRESSED", 2, "REMOVE_AND_ADD_ADDRESSED_DATA_FLAGS")
    allocate("ROW_FLAGS", ROW_COUNT, "SEVEN_INTERVAL_PREDICATE_FLAGS")
    allocate("CONTROL_FLAGS", CONTROL_FLAG_COUNT, "DIFFERENCE_FEASIBLE_MOVE_STREAM_BIT_AND_ADDER_LADDER")
    if cursor != 67 + 2 * width:
        raise AssertionError("V4.5 register allocation formula mismatch.")
    if cursor > TARGET_LOGICAL_QUBITS:
        raise ValueError(f"V4.5 layout exceeds the {TARGET_LOGICAL_QUBITS}-qubit target: {cursor}")
    layout = CircuitLayout(tuple(registers), cursor, width)
    if len(layout.bridge_pool()) != BRIDGE_LADDER_QUBITS:
        raise AssertionError("Bridge pool width mismatch.")
    return layout


def build_liveness_certificate(layout: CircuitLayout) -> dict[str, Any]:
    """Describe every intentional alias as a phase-local clean borrow."""

    constant = list(layout.register("CONSTANT").qubits)
    sum_work = list(layout.register("SUM_WORK").qubits)
    events = [
        {
            "phase": "BINARY_COIN_RINGS",
            "borrowed_clean_qubits": constant[:3],
            "borrow_reason": "C5X_LADDER_FOR_EXACT_TWO_LEVEL_RX",
            "clean_before": ["CONSTANT"],
            "clean_after": ["CONSTANT"],
        },
        {
            "phase": "SELECT_ADDRESS_READ_AND_DATA_UPDATE",
            "borrowed_clean_qubits": constant[:5],
            "borrow_reason": "C7X_BINARY_ADDRESS_MATCH_LADDER",
            "clean_before": ["CONSTANT"],
            "clean_after": ["CONSTANT"],
        },
        {
            "phase": "STREAMED_TARGET_ROW_ARITHMETIC",
            "borrowed_clean_qubits": constant[:5],
            "borrow_reason": "RELATIVE_PHASE_ADDRESS_MATCH_ONLY_WHILE_CONSTANT_IS_ZERO;_EXACT_ADJOINT_AFTER_ADDER_CLEARS_PHASE_AND_BOOLEAN_TEMPORARIES",
            "clean_before": ["SUM_WORK", "CONSTANT", "CARRY", "CONTROL_FLAGS[3:5]"],
            "clean_after": ["SUM_WORK", "CONSTANT", "CARRY", "CONTROL_FLAGS[3:5]"],
            "row_flag_lifecycle": "ROW_FLAG_I_BECOMES_LIVE_AFTER_ITS_PREDICATE;_ALL_SEVEN_REMAIN_LIVE_THROUGH_AND;_REVERSE_RECOMPUTATION_CLEARS_I",
        },
        {
            "phase": "CERTIFIED_DATA_BRIDGES",
            "borrowed_clean_qubits": list(layout.bridge_pool()),
            "borrow_reason": "C39X_LADDER_AFTER_SELECTOR_CLEAN_EXIT",
            "clean_before": ["SUM_WORK", "CONSTANT", "CARRY", "ADDRESSED", "ROW_FLAGS", "CONTROL_FLAGS"],
            "clean_after": ["SUM_WORK", "CONSTANT", "CARRY", "ADDRESSED", "ROW_FLAGS", "CONTROL_FLAGS"],
        },
    ]
    core = {
        "bridge_pool_disjoint_from_data": not set(layout.bridge_pool()) & set(layout.register("DATA").qubits),
        "clean_exit_registers": ["SUM_WORK", "CONSTANT", "CARRY", "ADDRESSED", "ROW_FLAGS", "CONTROL_FLAGS"],
        "events": events,
        "liveness_decision": "PASSED_STATIC_PHASE_LOCAL_BORROW_AND_CLEAN_EXIT_CONTRACT",
        "relative_phase_compute_use_uncompute": {
            "exactness_argument": "FOR_B_MONOMIAL_AND_U_PRESERVING_ALL_B_INPUTS_AND_TEMPORARIES,_B_DAGGER_U_B_CANCELS_EVERY_RELATIVE_PHASE_EXACTLY",
            "scope": "ONLY_FOUR_ADDRESS_EQUALITY_TOGGLES_AROUND_EACH_STREAMED_CONTROLLED_ADD",
            "temporary_restoration": "RCCX_LADDER_ANCILLAS_RETURN_TO_ZERO_INSIDE_EACH_B_OR_B_DAGGER",
            "uncompute": "EXPLICIT_EXACT_ADJOINT_IN_REVERSE_ORDER",
        },
        "reset_instruction_count": 0,
    }
    return {**core, "liveness_certificate_sha256": canonical_json_sha256(core)}


def _address_values(index: int) -> tuple[int, ...]:
    if not 0 <= int(index) < VALID_ADDRESS_COUNT:
        raise ValueError(f"Address outside the V4.5 valid domain: {index}")
    return tuple((int(index) >> bit) & 1 for bit in range(ADDRESS_WIDTH))


def _emit_address_match_toggle(
    stream: CircuitStream,
    *,
    stage: str,
    address: Sequence[int],
    index: int,
    target: int,
    ancillas: Sequence[int],
    positive_controls: Sequence[int] = (),
) -> None:
    controls = (*tuple(positive_controls), *tuple(address))
    values = (*((1,) * len(tuple(positive_controls))), *_address_values(index))
    stream.pattern_mcx(stage, controls, values, target, ancillas)


def _emit_rccx(
    stream: CircuitStream,
    *,
    stage: str,
    a: int,
    b: int,
    target: int,
    adjoint: bool = False,
) -> None:
    """Emit the three-CX relative-phase Toffoli or its exact adjoint.

    The forward gate is a self-inverse monomial RCCX, but the adjoint is
    deliberately emitted by reversing the primitive list and inverting T/TDG
    so the compute/use/uncompute proof does not depend on that simplification.
    """

    if len({a, b, target}) != 3:
        raise ValueError("RCCX operands must be distinct.")
    operations: tuple[tuple[str, int | tuple[int, int]], ...] = (
        ("H", target),
        ("T", target),
        ("CX", (b, target)),
        ("TDG", target),
        ("CX", (a, target)),
        ("T", target),
        ("CX", (b, target)),
        ("TDG", target),
        ("H", target),
    )
    selected = reversed(operations) if adjoint else operations
    for opcode, operands in selected:
        actual = {"T": "TDG", "TDG": "T"}.get(opcode, opcode) if adjoint else opcode
        if actual == "H":
            stream.h(stage, int(operands))
        elif actual == "T":
            stream.t(stage, int(operands))
        elif actual == "TDG":
            stream.tdg(stage, int(operands))
        elif actual == "CX":
            control, destination = operands  # type: ignore[misc]
            stream.cx(stage, int(control), int(destination))
        else:
            raise AssertionError(actual)
    stream.macro_counts["RCCX_DAGGER_3CX" if adjoint else "RCCX_3CX"] += 1


def _emit_relative_phase_mcx(
    stream: CircuitStream,
    *,
    stage: str,
    controls: Sequence[int],
    target: int,
    ancillas: Sequence[int],
    adjoint: bool = False,
) -> None:
    """Relative-phase CnX with a clean ladder, or its exact adjoint."""

    controls = tuple(int(qubit) for qubit in controls)
    target = int(target)
    if len(controls) < 2 or len(set((*controls, target))) != len(controls) + 1:
        raise ValueError("Relative-phase MCX requires distinct controls and target.")
    required = len(controls) - 2
    if len(ancillas) < required:
        raise ValueError("Insufficient clean relative-phase ladder ancillas.")
    work = tuple(int(qubit) for qubit in ancillas[:required])
    if len(set((*controls, target, *work))) != len(controls) + 1 + len(work):
        raise ValueError("Relative-phase ladder overlaps controls or target.")
    gates: list[tuple[int, int, int]] = [(controls[0], controls[1], work[0])]
    for index in range(2, len(controls) - 1):
        gates.append((controls[index], work[index - 2], work[index - 1]))
    gates.append((controls[-1], work[-1], target))
    for index in range(len(controls) - 2, 1, -1):
        gates.append((controls[index], work[index - 2], work[index - 1]))
    gates.append((controls[0], controls[1], work[0]))
    selected = reversed(gates) if adjoint else gates
    for a, b, destination in selected:
        _emit_rccx(
            stream,
            stage=stage,
            a=a,
            b=b,
            target=destination,
            adjoint=adjoint,
        )
    stream.macro_counts[
        f"RELATIVE_PHASE_C{len(controls)}X_DAGGER" if adjoint else f"RELATIVE_PHASE_C{len(controls)}X"
    ] += 1


def _emit_relative_phase_address_match_toggle(
    stream: CircuitStream,
    *,
    stage: str,
    address: Sequence[int],
    index: int,
    target: int,
    ancillas: Sequence[int],
    positive_controls: Sequence[int],
    adjoint: bool,
) -> None:
    """Pattern-controlled relative-phase toggle used only inside B† U B."""

    controls = (*tuple(positive_controls), *tuple(address))
    values = (*((1,) * len(tuple(positive_controls))), *_address_values(index))
    negative = [int(qubit) for qubit, value in zip(controls, values) if int(value) == 0]
    for qubit in negative:
        stream.x(stage, qubit)
    _emit_relative_phase_mcx(
        stream,
        stage=stage,
        controls=controls,
        target=target,
        ancillas=ancillas,
        adjoint=adjoint,
    )
    for qubit in reversed(negative):
        stream.x(stage, qubit)


def _emit_pattern_mcrz(
    stream: CircuitStream,
    *,
    stage: str,
    controls: Sequence[int],
    values: Sequence[int],
    target: int,
    ancillas: Sequence[int],
    angle: Fraction,
) -> None:
    stream.rz(stage, target, angle / 2)
    stream.pattern_mcx(stage, controls, values, target, ancillas)
    stream.rz(stage, target, -angle / 2)
    stream.pattern_mcx(stage, controls, values, target, ancillas)


def _emit_pattern_mcry(
    stream: CircuitStream,
    *,
    stage: str,
    controls: Sequence[int],
    values: Sequence[int],
    target: int,
    ancillas: Sequence[int],
    angle: Fraction,
) -> None:
    stream.ry(stage, target, angle / 2)
    stream.pattern_mcx(stage, controls, values, target, ancillas)
    stream.ry(stage, target, -angle / 2)
    stream.pattern_mcx(stage, controls, values, target, ancillas)


def _emit_pattern_mcrx(
    stream: CircuitStream,
    *,
    stage: str,
    controls: Sequence[int],
    values: Sequence[int],
    target: int,
    ancillas: Sequence[int],
    angle: Fraction,
) -> None:
    # RZ(-pi/2) RY(angle) RZ(pi/2) = RX(angle), read right-to-left;
    # therefore the circuit emits +pi/2, RY, -pi/2 in time order.
    _emit_pattern_mcrz(
        stream, stage=stage, controls=controls, values=values, target=target,
        ancillas=ancillas, angle=Fraction(1, 2),
    )
    _emit_pattern_mcry(
        stream, stage=stage, controls=controls, values=values, target=target,
        ancillas=ancillas, angle=angle,
    )
    _emit_pattern_mcrz(
        stream, stage=stage, controls=controls, values=values, target=target,
        ancillas=ancillas, angle=Fraction(-1, 2),
    )
    stream.macro_counts["PATTERN_MCRX"] += 1


def _gray_path(source: int, target: int) -> tuple[tuple[int, ...], tuple[int, ...]]:
    differing = tuple(bit for bit in range(ADDRESS_WIDTH) if ((source ^ target) >> bit) & 1)
    if not differing:
        raise ValueError("Two-level rotation endpoints must be distinct.")
    states = [int(source)]
    current = int(source)
    for bit in differing:
        current ^= 1 << bit
        states.append(current)
    if current != int(target):
        raise AssertionError("Gray path construction failed.")
    return tuple(states), differing


def _edge_pattern(address: Sequence[int], state: int, target_bit: int) -> tuple[tuple[int, ...], tuple[int, ...]]:
    controls = tuple(address[bit] for bit in range(ADDRESS_WIDTH) if bit != target_bit)
    values = tuple((state >> bit) & 1 for bit in range(ADDRESS_WIDTH) if bit != target_bit)
    return controls, values


def emit_binary_two_level_rx(
    stream: CircuitStream,
    *,
    stage: str,
    address: Sequence[int],
    source: int,
    target: int,
    ancillas: Sequence[int],
    angle: Fraction = COIN_THETA,
) -> None:
    """Exact two-level RX, identity on all other six-bit basis states."""

    states, differing = _gray_path(source, target)
    for edge in range(len(differing) - 1):
        controls, values = _edge_pattern(address, states[edge], differing[edge])
        stream.pattern_mcx(stage, controls, values, address[differing[edge]], ancillas)
    controls, values = _edge_pattern(address, states[-2], differing[-1])
    _emit_pattern_mcrx(
        stream,
        stage=stage,
        controls=controls,
        values=values,
        target=address[differing[-1]],
        ancillas=ancillas,
        angle=angle,
    )
    for edge in range(len(differing) - 2, -1, -1):
        controls, values = _edge_pattern(address, states[edge], differing[edge])
        stream.pattern_mcx(stage, controls, values, address[differing[edge]], ancillas)
    stream.macro_counts["BINARY_TWO_LEVEL_RX"] += 1


def emit_binary_coin_rings(stream: CircuitStream, layout: CircuitLayout) -> None:
    ancillas = layout.register("CONSTANT").qubits[:3]
    for register_name in ("REMOVE_ADDR", "ADD_ADDR"):
        address = layout.register(register_name).qubits
        for source in range(VALID_ADDRESS_COUNT):
            emit_binary_two_level_rx(
                stream,
                stage=f"COIN_RING_{register_name}",
                address=address,
                source=source,
                target=(source + 1) % VALID_ADDRESS_COUNT,
                ancillas=ancillas,
            )


def build_coin_isometry_certificate() -> dict[str, Any]:
    """Seal the exact ordered conjugacy from one-hot edges to binary edges."""

    edges: list[dict[str, Any]] = []
    for rank in range(VALID_ADDRESS_COUNT):
        target = (rank + 1) % VALID_ADDRESS_COUNT
        states, differing = _gray_path(rank, target)
        edge_core = {
            "binary_source": rank,
            "binary_target": target,
            "gray_flip_bits_little_endian": list(differing),
            "gray_states": list(states),
            "one_hot_source_qubit": rank,
            "one_hot_target_qubit": target,
            "ordered_edge_rank": rank,
            "restricted_action": "RX_PI_OVER_2_EXACTLY_MATCHES_V43_XX_PLUS_YY_THETA_PI_OVER_2_BETA_ZERO_ON_ONE_EXCITATION_SUBSPACE",
        }
        edges.append({**edge_core, "edge_sha256": canonical_json_sha256(edge_core)})
    core = {
        "address_bit_order": "LITTLE_ENDIAN",
        "edge_count": len(edges),
        "invalid_address_action": "IDENTITY_FOR_40_TO_63_FOR_EVERY_CONJUGATED_TWO_LEVEL_EDGE",
        "isometry": "V43_ONE_HOT_BASIS_E_I_MAPS_TO_V45_SIX_QUBIT_BINARY_BASIS_I_FOR_I_IN_0_TO_39",
        "ordered_edge_root_sha256": canonical_json_sha256([edge["edge_sha256"] for edge in edges]),
        "ordered_edges": edges,
        "physical_conversion_circuit": "NOT_PROVIDED_NEW_COMPILED_INTERFACE_REQUIRES_BINARY_INITIALIZATION",
        "registers": ["REMOVE_ADDR", "ADD_ADDR"],
    }
    return {**core, "coin_isometry_certificate_sha256": canonical_json_sha256(core)}


def _emit_streamed_target_bit(
    stream: CircuitStream,
    *,
    stage: str,
    data_bit: int,
    remove_address: Sequence[int],
    add_address: Sequence[int],
    index: int,
    difference: int,
    stream_bit: int,
    ancillas: Sequence[int],
) -> None:
    stream.cx(stage, data_bit, stream_bit)
    _emit_relative_phase_address_match_toggle(
        stream, stage=stage, address=remove_address, index=index, target=stream_bit,
        ancillas=ancillas, positive_controls=(difference,), adjoint=False,
    )
    _emit_relative_phase_address_match_toggle(
        stream, stage=stage, address=add_address, index=index, target=stream_bit,
        ancillas=ancillas, positive_controls=(difference,), adjoint=False,
    )


def _emit_streamed_target_bit_clear(
    stream: CircuitStream,
    *,
    stage: str,
    data_bit: int,
    remove_address: Sequence[int],
    add_address: Sequence[int],
    index: int,
    difference: int,
    stream_bit: int,
    ancillas: Sequence[int],
) -> None:
    _emit_relative_phase_address_match_toggle(
        stream, stage=stage, address=add_address, index=index, target=stream_bit,
        ancillas=ancillas, positive_controls=(difference,), adjoint=True,
    )
    _emit_relative_phase_address_match_toggle(
        stream, stage=stage, address=remove_address, index=index, target=stream_bit,
        ancillas=ancillas, positive_controls=(difference,), adjoint=True,
    )
    stream.cx(stage, data_bit, stream_bit)


def _emit_streamed_row_sum(
    stream: CircuitStream,
    *,
    stage: str,
    row: Mapping[str, Any],
    layout: CircuitLayout,
    direction: int,
) -> None:
    if direction not in {-1, 1}:
        raise ValueError("Streamed row direction must be +1 or -1.")
    data = layout.register("DATA").qubits
    remove_address = layout.register("REMOVE_ADDR").qubits
    add_address = layout.register("ADD_ADDR").qubits
    row_width = max(MIN_ARITHMETIC_WIDTH, int(row["width"]))
    work = layout.register("SUM_WORK").qubits[:row_width]
    constant = layout.register("CONSTANT").qubits
    carry = layout.register("CARRY").qubits[0]
    difference, _, _, stream_bit, adder_ladder = layout.register("CONTROL_FLAGS").qubits
    width = row_width
    mask = (1 << width) - 1
    offset = int(row["cache_offset"]) & mask
    indices = range(N) if direction == 1 else range(N - 1, -1, -1)
    if direction == 1:
        for bit in range(width):
            if (offset >> bit) & 1:
                stream.x(stage, work[bit])
    for index in indices:
        coefficient = int(row["coefficients"][index])
        if not coefficient:
            continue
        _emit_streamed_target_bit(
            stream,
            stage=stage,
            data_bit=data[index],
            remove_address=remove_address,
            add_address=add_address,
            index=index,
            difference=difference,
            stream_bit=stream_bit,
            ancillas=constant[:5],
        )
        emit_controlled_constant_add(
            stream,
            stage=stage,
            control=stream_bit,
            work=work,
            constant=constant,
            carry=carry,
            ladder=adder_ladder,
            value=direction * coefficient,
        )
        _emit_streamed_target_bit_clear(
            stream,
            stage=stage,
            data_bit=data[index],
            remove_address=remove_address,
            add_address=add_address,
            index=index,
            difference=difference,
            stream_bit=stream_bit,
            ancillas=constant[:5],
        )
    if direction == -1:
        for bit in range(width - 1, -1, -1):
            if (offset >> bit) & 1:
                stream.x(stage, work[bit])


def emit_streamed_feasibility_oracle(
    stream: CircuitStream,
    *,
    stage_prefix: str,
    rows: Sequence[Mapping[str, Any]],
    layout: CircuitLayout,
    feasible_flag: int,
) -> None:
    """Toggle feasibility with one sum bank and Bennett recomputation."""

    constant = layout.register("CONSTANT").qubits
    carry = layout.register("CARRY").qubits[0]
    row_flags = layout.register("ROW_FLAGS").qubits
    for row_index, row in enumerate(rows):
        row_width = max(MIN_ARITHMETIC_WIDTH, int(row["width"]))
        work = layout.register("SUM_WORK").qubits[:row_width]
        _emit_streamed_row_sum(
            stream, stage=f"{stage_prefix}_ROW_{row_index}_BUILD", row=row, layout=layout, direction=1,
        )
        emit_interval_oracle(
            stream,
            stage=f"{stage_prefix}_ROW_{row_index}_PREDICATE",
            work=work,
            constant=constant,
            carry=carry,
            out=row_flags[row_index],
            lower=int(row["guard"]),
            upper=int(row["guard"]) + int(row["span"]),
        )
        _emit_streamed_row_sum(
            stream, stage=f"{stage_prefix}_ROW_{row_index}_CLEAR", row=row, layout=layout, direction=-1,
        )
    stream.mcx(f"{stage_prefix}_SEVEN_ROW_AND", row_flags, feasible_flag, constant[:5])
    for row_index in range(len(rows) - 1, -1, -1):
        row = rows[row_index]
        row_width = max(MIN_ARITHMETIC_WIDTH, int(row["width"]))
        work = layout.register("SUM_WORK").qubits[:row_width]
        _emit_streamed_row_sum(
            stream, stage=f"{stage_prefix}_ROW_{row_index}_REBUILD", row=row, layout=layout, direction=1,
        )
        emit_interval_oracle(
            stream,
            stage=f"{stage_prefix}_ROW_{row_index}_PREDICATE_CLEAR",
            work=work,
            constant=constant,
            carry=carry,
            out=row_flags[row_index],
            lower=int(row["guard"]),
            upper=int(row["guard"]) + int(row["span"]),
        )
        _emit_streamed_row_sum(
            stream, stage=f"{stage_prefix}_ROW_{row_index}_RECLEAR", row=row, layout=layout, direction=-1,
        )
    stream.macro_counts["EXACT_STREAMED_BENNETT_FEASIBILITY_TOGGLE"] += 1


def _emit_addressed_read(
    stream: CircuitStream,
    *,
    stage: str,
    data: Sequence[int],
    address: Sequence[int],
    out: int,
    ancillas: Sequence[int],
) -> None:
    for index in range(N):
        _emit_address_match_toggle(
            stream,
            stage=stage,
            address=address,
            index=index,
            target=out,
            ancillas=ancillas,
            positive_controls=(data[index],),
        )


def _emit_addressed_data_update(
    stream: CircuitStream,
    *,
    stage: str,
    data: Sequence[int],
    address: Sequence[int],
    move: int,
    ancillas: Sequence[int],
) -> None:
    for index in range(N):
        _emit_address_match_toggle(
            stream,
            stage=stage,
            address=address,
            index=index,
            target=data[index],
            ancillas=ancillas,
            positive_controls=(move,),
        )


def emit_binary_selector(stream: CircuitStream, rows: Sequence[Mapping[str, Any]], layout: CircuitLayout) -> None:
    data = layout.register("DATA").qubits
    remove_address = layout.register("REMOVE_ADDR").qubits
    add_address = layout.register("ADD_ADDR").qubits
    constant = layout.register("CONSTANT").qubits
    addressed_remove, addressed_add = layout.register("ADDRESSED").qubits
    difference, feasible, move, _, _ = layout.register("CONTROL_FLAGS").qubits
    _emit_addressed_read(
        stream, stage="SELECT_ADDRESS_READ_REMOVE", data=data, address=remove_address,
        out=addressed_remove, ancillas=constant[:5],
    )
    _emit_addressed_read(
        stream, stage="SELECT_ADDRESS_READ_ADD", data=data, address=add_address,
        out=addressed_add, ancillas=constant[:5],
    )
    stream.cx("SELECT_DIFFERENCE_COMPUTE", addressed_remove, difference)
    stream.cx("SELECT_DIFFERENCE_COMPUTE", addressed_add, difference)
    emit_streamed_feasibility_oracle(
        stream, stage_prefix="SELECT_FORWARD_ORACLE", rows=rows, layout=layout, feasible_flag=feasible,
    )
    stream.ccx("SELECT_MOVE_COMPUTE", difference, feasible, move)
    _emit_addressed_data_update(
        stream, stage="SELECT_DATA_UPDATE_REMOVE", data=data, address=remove_address,
        move=move, ancillas=constant[:5],
    )
    _emit_addressed_data_update(
        stream, stage="SELECT_DATA_UPDATE_ADD", data=data, address=add_address,
        move=move, ancillas=constant[:5],
    )
    stream.cx("SELECT_ADDRESS_UPDATE", move, addressed_remove)
    stream.cx("SELECT_ADDRESS_UPDATE", move, addressed_add)
    stream.ccx("SELECT_MOVE_CLEAR", difference, feasible, move)
    emit_streamed_feasibility_oracle(
        stream, stage_prefix="SELECT_REVERSE_ORACLE", rows=rows, layout=layout, feasible_flag=feasible,
    )
    stream.cx("SELECT_DIFFERENCE_CLEAR", addressed_remove, difference)
    stream.cx("SELECT_DIFFERENCE_CLEAR", addressed_add, difference)
    _emit_addressed_read(
        stream, stage="SELECT_ADDRESS_CLEAR_ADD", data=data, address=add_address,
        out=addressed_add, ancillas=constant[:5],
    )
    _emit_addressed_read(
        stream, stage="SELECT_ADDRESS_CLEAR_REMOVE", data=data, address=remove_address,
        out=addressed_remove, ancillas=constant[:5],
    )
    stream.macro_counts["PROMISE_SUBSPACE_BINARY_SELECT"] += 1


def _emit_pattern_mcry_bridge(
    stream: CircuitStream,
    *,
    stage: str,
    controls: Sequence[int],
    values: Sequence[int],
    target: int,
    ancillas: Sequence[int],
    angle: Fraction,
) -> None:
    _emit_pattern_mcry(
        stream, stage=stage, controls=controls, values=values, target=target,
        ancillas=ancillas, angle=angle,
    )
    stream.macro_counts["PATTERN_MCRY"] += 1


def emit_bridge(stream: CircuitStream, *, bridge: Mapping[str, Any], layout: CircuitLayout, rank: int) -> None:
    data = layout.register("DATA").qubits
    ancillas = layout.bridge_pool()
    source = int(str(bridge["source_mask_hex"]), 16)
    target_mask = int(str(bridge["target_mask_hex"]), 16)
    differing = [index for index in range(N) if ((source ^ target_mask) >> index) & 1]
    if len(differing) != 4:
        raise ValueError("V4.5 preserves only authenticated Hamming-distance-four bridges.")
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
    _emit_pattern_mcry_bridge(
        stream,
        stage=stage,
        controls=controls,
        values=values,
        target=data[differing[-1]],
        ancillas=ancillas,
        angle=BRIDGE_THETA,
    )
    for edge in range(len(differing) - 2, -1, -1):
        controls, values = edge_pattern(path[edge], differing[edge])
        stream.pattern_mcx(stage, controls, values, data[differing[edge]], ancillas)
    stream.macro_counts["TWO_LEVEL_BRIDGE_RY"] += 1


def _row_payload(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
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
            "v43_materialized_width": max(MIN_ARITHMETIC_WIDTH, int(row["width"])),
        }
        for row in rows
    ]


def _v43_row_digest(rows: Sequence[Mapping[str, Any]]) -> str:
    return canonical_json_sha256(_row_payload(rows))


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


def _select_trace(mask: int, remove: int, add: int, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not (0 <= remove < N and 0 <= add < N):
        return {
            "add_index": add,
            "difference": 0,
            "first_target_feasible_flag": 0,
            "move": 0,
            "output_mask_hex": f"{mask:010x}",
            "remove_index": remove,
            "retained_feasible_flag_after_reverse": 0,
            "start_mask_hex": f"{mask:010x}",
            "target_mask_hex": f"{mask:010x}",
        }
    remove_value = (mask >> remove) & 1
    add_value = (mask >> add) & 1
    difference = remove_value ^ add_value
    target = mask ^ ((1 << remove) | (1 << add)) if difference else mask
    feasible = int(_is_feasible(target, rows))
    move = difference & feasible
    output = target if move else mask
    reverse_target = output ^ ((1 << remove) | (1 << add)) if difference else output
    retained = feasible ^ int(_is_feasible(reverse_target, rows))
    return {
        "add_index": add,
        "difference": difference,
        "first_target_feasible_flag": feasible,
        "move": move,
        "output_mask_hex": f"{output:010x}",
        "remove_index": remove,
        "retained_feasible_flag_after_reverse": retained,
        "start_mask_hex": f"{mask:010x}",
        "target_mask_hex": f"{target:010x}",
    }


def _semantic_trace_certificate(
    *,
    seed: int,
    rows: Sequence[Mapping[str, Any]],
    representatives: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    samples: list[dict[str, Any]] = []
    trace_hashes: list[str] = []
    for representative in representatives:
        mask = int(str(representative["mask_hex"]), 16)
        if not _is_feasible(mask, rows):
            raise ValueError(f"Seed {seed} contains a non-feasible authenticated representative.")
        row_hashes: list[str] = []
        accepted_moves = 0
        for remove in range(N):
            for add in range(N):
                trace = _select_trace(mask, remove, add, rows)
                row_hashes.append(canonical_json_sha256(trace))
                accepted_moves += int(trace["move"])
        sample_core = {
            "accepted_move_count": accepted_moves,
            "address_pair_count": N * N,
            "all_valid_binary_address_pairs_exhausted": True,
            "representative_mask_hex": f"{mask:010x}",
            "representative_sha256": str(representative["representative_sha256"]),
            "trace_root_sha256": canonical_json_sha256(row_hashes),
        }
        sample = {**sample_core, "sample_sha256": canonical_json_sha256(sample_core)}
        samples.append(sample)
        trace_hashes.append(sample["sample_sha256"])
    core = {
        "binary_domain": {"address_width": ADDRESS_WIDTH, "invalid_encodings": list(range(40, 64)), "valid": [0, 39]},
        "isometry": "ONE_HOT_BASIS_E_I_MAPS_TO_SIX_BIT_LITTLE_ENDIAN_BINARY_I_FOR_I_0_TO_39",
        "sample_count": len(samples),
        "samples": samples,
        "seed": seed,
        "trace_root_sha256": canonical_json_sha256(trace_hashes),
        "v43_promise_relation": "EXACT_SELECT_TRACE_PARITY_FOR_ALL_1600_ADDRESS_PAIRS_OF_EACH_AUTHENTICATED_COMPONENT_REPRESENTATIVE",
    }
    return {**core, "semantic_trace_certificate_sha256": canonical_json_sha256(core)}


def build_v45_liveness_certificate(*, root: str | Path | None = None) -> dict[str, Any]:
    """Build the result-independent eight-seed allocation/liveness ledger."""

    paths = _paths(root)
    spec = load_v45_spec(root=paths["root"])
    parent = authenticate_v44_parent(root=paths["root"])
    if parent.get("valid") is not True:
        raise RuntimeError(f"V4.4 parent authentication failed: {parent.get('errors')}")
    v43 = parent.get("v43_artifact") or {}
    v43_rows = {int(row["seed"]): row for row in v43.get("seed_materializations") or []}
    certificates = _certificate_by_seed(paths["root"])
    v41 = read_json_strict(paths["v41_artifact"])
    compressions = {
        int(row["seed"]): row
        for row in (v41.get("compression_evidence") or {}).get("seed_rows") or []
    }
    expected_parent_widths = list((spec.get("frozen_instances") or {}).get("parent_v43_logical_widths") or [])
    expected_row_widths = list((spec.get("frozen_instances") or {}).get("v43_materialized_row_widths") or [])
    seed_rows: list[dict[str, Any]] = []
    for position, seed in enumerate(SEEDS):
        rows = _guarded_rows(certificates[seed], compressions[seed])
        layout = build_layout(rows)
        actual_row_widths = [max(MIN_ARITHMETIC_WIDTH, int(row["width"])) for row in rows]
        parent_width = int((v43_rows[seed].get("register_layout") or {}).get("total_qubits", -1))
        if position >= len(expected_parent_widths) or parent_width != int(expected_parent_widths[position]):
            raise ValueError(f"Seed {seed} parent width differs from the sealed V4.5 protocol.")
        if position >= len(expected_row_widths) or actual_row_widths != [int(value) for value in expected_row_widths[position]]:
            raise ValueError(f"Seed {seed} row widths differ from the sealed V4.5 protocol.")
        width_core = {
            "capacity_fit": layout.total_qubits <= TARGET_LOGICAL_QUBITS,
            "capacity_margin_qubits": TARGET_LOGICAL_QUBITS - layout.total_qubits,
            "maximum_row_width": layout.arithmetic_width,
            "new_logical_qubits": layout.total_qubits,
            "old_logical_qubits": parent_width,
            "reduction_qubits": parent_width - layout.total_qubits,
            "seed": seed,
        }
        row_core = {
            "liveness": build_liveness_certificate(layout),
            "register_layout": layout.as_dict(),
            "row_widths": actual_row_widths,
            "seed": seed,
            "width": {**width_core, "width_row_sha256": canonical_json_sha256(width_core)},
        }
        seed_rows.append({**row_core, "seed_liveness_sha256": canonical_json_sha256(row_core)})
    widths = [int(row["register_layout"]["total_qubits"]) for row in seed_rows]
    core = {
        "certificate_version": "QUANTUM LAB V4.5 REGISTER LIVENESS AND CLEANUP CERTIFICATE · V1",
        "cleanup_obligations": {
            "address_ladder": "EVERY_EXACT_OR_RELATIVE_PHASE_MCX_LADDER_RETURNS_ITS_CLEAN_ANCILLAS_TO_ZERO",
            "bennett_rows": "BUILD_SUM_COMPUTE_FLAG_UNCOMPUTE_SUM;_AFTER_AND_REBUILD_SUM_CLEAR_FLAG_UNCOMPUTE_SUM",
            "bridge_alias": "FIRST_37_SUM_WORK_THEN_CONSTANT_QUBITS_BORROWED_ONLY_AFTER_SELECT_CLEAN_EXIT",
            "forbidden": ["RESET", "MEASUREMENT", "DISCARD", "DEPENDENCY_DESTRUCTION_BEFORE_UNCOMPUTE"],
            "relative_phase": "B_DAGGER_U_B_WITH_EXPLICIT_ADJOINT;_U_PRESERVES_B_INPUTS_STREAM_BIT_AND_LADDER_SO_ALL_MONOMIAL_PHASES_CANCEL",
            "selector_exit": ["SUM_WORK", "CONSTANT", "CARRY", "ADDRESSED", "ROW_FLAGS", "CONTROL_FLAGS"],
        },
        "maximum_logical_qubits": max(widths),
        "minimum_capacity_margin_qubits": min(TARGET_LOGICAL_QUBITS - width for width in widths),
        "parent": {
            "v44_artifact_raw_file_sha256": EXPECTED_V44_ARTIFACT_RAW_SHA256,
            "v44_artifact_sha256": EXPECTED_V44_ARTIFACT_SHA256,
            "v44_freeze_raw_file_sha256": EXPECTED_V44_FREEZE_RAW_SHA256,
            "v44_freeze_sha256": EXPECTED_V44_FREEZE_SHA256,
        },
        "register_formula": "67+2W",
        "seed_rows": seed_rows,
        "spec_raw_file_sha256": EXPECTED_SPEC_RAW_SHA256,
        "spec_sha256": EXPECTED_SPEC_SHA256,
        "target_logical_qubits": TARGET_LOGICAL_QUBITS,
    }
    return {**core, "certificate_sha256": canonical_json_sha256(core)}


def seal_v45_liveness_certificate(
    path: str | Path | None = None,
    *,
    root: str | Path | None = None,
) -> dict[str, Any]:
    """Seal the standalone certificate; callers control when this write occurs."""

    paths = _paths(root)
    certificate = build_v45_liveness_certificate(root=paths["root"])
    target = Path(path) if path is not None else paths["liveness_certificate"]
    if not target.is_absolute():
        target = paths["root"] / target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(certificate, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return certificate


def _load_v45_liveness_certificate(*, root: str | Path | None = None) -> tuple[dict[str, Any], str]:
    paths = _paths(root)
    payload = read_json_strict(paths["liveness_certificate"])
    core = {key: value for key, value in payload.items() if key != "certificate_sha256"}
    semantic = canonical_json_sha256(core)
    if payload.get("certificate_sha256") != semantic:
        raise ValueError("V4.5 liveness certificate self-hash mismatch.")
    expected = build_v45_liveness_certificate(root=paths["root"])
    if payload != expected:
        raise ValueError("V4.5 liveness certificate differs from deterministic reconstruction.")
    return payload, semantic


def materialize_seed(
    *,
    seed: int,
    rows: Sequence[Mapping[str, Any]],
    connectivity: Mapping[str, Any],
    v43_materialization: Mapping[str, Any],
    progress: Any | None = None,
) -> dict[str, Any]:
    layout = build_layout(rows)
    stream = CircuitStream(seed=seed, total_qubits=layout.total_qubits)
    if progress is not None:
        progress(f"V4.5 materialization · seed {seed} · binary coin rings")
    emit_binary_coin_rings(stream, layout)
    if progress is not None:
        progress(f"V4.5 materialization · seed {seed} · streamed Bennett SELECT")
    emit_binary_selector(stream, rows, layout)
    for rank, bridge in enumerate(connectivity.get("selected_bridges") or [], start=1):
        if progress is not None:
            progress(f"V4.5 materialization · seed {seed} · certified bridge {rank}")
        emit_bridge(stream, bridge=bridge, layout=layout, rank=rank)
    manifest = stream.finish()
    v43_layout = v43_materialization.get("register_layout") or {}
    v43_width = int(v43_layout.get("total_qubits", -1))
    row_digest = _v43_row_digest(rows)
    if row_digest != v43_materialization.get("constraint_rows_sha256"):
        raise ValueError(f"Seed {seed} row digest differs from the authenticated V4.3 materialization.")
    semantic = _semantic_trace_certificate(
        seed=seed,
        rows=rows,
        representatives=connectivity.get("authenticated_v40_component_representatives") or [],
    )
    width_core = {
        "backend_capacity_qubits": TARGET_LOGICAL_QUBITS,
        "capacity_fit": layout.total_qubits <= TARGET_LOGICAL_QUBITS,
        "capacity_margin_qubits": TARGET_LOGICAL_QUBITS - layout.total_qubits,
        "maximum_row_width": layout.arithmetic_width,
        "new_logical_qubits": layout.total_qubits,
        "old_logical_qubits": v43_width,
        "reduction_qubits": v43_width - layout.total_qubits,
        "reduction_ratio": f"{v43_width - layout.total_qubits}/{v43_width}",
        "seed": seed,
    }
    width = {**width_core, "width_certificate_sha256": canonical_json_sha256(width_core)}
    cnot = int((manifest.get("elementary_counts") or {}).get("CX", 0))
    core = {
        "budget_cnot": BUDGET_CNOT,
        "budget_margin_cnot": BUDGET_CNOT - cnot,
        "certified_bridge_count": len(connectivity.get("selected_bridges") or []),
        "constraint_rows": _row_payload(rows),
        "constraint_rows_sha256": row_digest,
        "instance_id": str(v43_materialization.get("instance_id")),
        "liveness": build_liveness_certificate(layout),
        "register_layout": layout.as_dict(),
        "resource_decision": "PASSED_LEGACY_CNOT_BUDGET" if cnot <= BUDGET_CNOT else "REJECTED_LEGACY_CNOT_BUDGET",
        "seed": seed,
        "semantic_trace_certificate": semantic,
        "stream_manifest": manifest,
        "width_certificate": width,
    }
    return {**core, "seed_materialization_sha256": canonical_json_sha256(core)}


def build_v45_artifact(*, root: str | Path | None = None, progress: Any | None = None) -> dict[str, Any]:
    paths = _paths(root)
    spec = load_v45_spec(root=paths["root"])
    parent = authenticate_v44_parent(root=paths["root"])
    if parent.get("valid") is not True:
        raise RuntimeError(f"V4.4 parent authentication failed: {parent.get('errors')}")
    v43 = parent.get("v43_artifact") or {}
    v43_rows = {int(row["seed"]): row for row in v43.get("seed_materializations") or []}
    if list(v43_rows) != list(SEEDS):
        raise ValueError("Authenticated V4.3 seed order mismatch.")
    liveness_certificate, liveness_semantic_sha256 = _load_v45_liveness_certificate(root=paths["root"])
    certificates = _certificate_by_seed(paths["root"])
    v41 = read_json_strict(paths["v41_artifact"])
    compressions = {int(row["seed"]): row for row in (v41.get("compression_evidence") or {}).get("seed_rows") or []}
    connectivity = {int(row["seed"]): row for row in (v41.get("connectivity_evidence") or {}).get("seed_rows") or []}
    seed_rows: list[dict[str, Any]] = []
    for seed in SEEDS:
        rows = _guarded_rows(certificates[seed], compressions[seed])
        seed_rows.append(
            materialize_seed(
                seed=seed,
                rows=rows,
                connectivity=connectivity[seed],
                v43_materialization=v43_rows[seed],
                progress=progress,
            )
        )
    widths = [int(row["register_layout"]["total_qubits"]) for row in seed_rows]
    cnot_counts = [int(row["stream_manifest"]["elementary_counts"]["CX"]) for row in seed_rows]
    width_pass = all(width <= TARGET_LOGICAL_QUBITS for width in widths)
    budget_pass = all(count <= BUDGET_CNOT for count in cnot_counts)
    semantic_pass = all(
        int((row.get("semantic_trace_certificate") or {}).get("sample_count", 0)) >= 1
        for row in seed_rows
    )
    aggregate_core = {
        "all_eight_widths_fit_156": width_pass,
        "all_eight_widths": widths,
        "all_eight_materialized_cnot_counts_at_or_below_2500000": budget_pass,
        "cnot_budget_pass_count": sum(count <= BUDGET_CNOT for count in cnot_counts),
        "maximum_logical_qubits": max(widths),
        "maximum_materialized_cnot": max(cnot_counts),
        "minimum_capacity_margin_qubits": min(TARGET_LOGICAL_QUBITS - width for width in widths),
        "ordered_stream_manifest_root_sha256": canonical_json_sha256(
            [row["stream_manifest"]["stream_manifest_sha256"] for row in seed_rows]
        ),
        "register_map_root_sha256": canonical_json_sha256(
            [row["register_layout"]["register_map_sha256"] for row in seed_rows]
        ),
        "seed_count": len(seed_rows),
        "semantic_trace_root_sha256": canonical_json_sha256(
            [row["semantic_trace_certificate"]["semantic_trace_certificate_sha256"] for row in seed_rows]
        ),
    }
    aggregate = {**aggregate_core, "aggregate_sha256": canonical_json_sha256(aggregate_core)}
    if width_pass and semantic_pass and budget_pass:
        overall = "V45_PROOF_CARRYING_WIDTH_REDUCTION_PASSED_EXACT_PROMISE_PARITY"
        next_gate = "PINNED_FAKEMARRAKESH_FULL_RECONSTRUCTION_TRANSLATION_AND_ROUTING_OF_WIDTH_ADMITTED_V4_5_STREAMS"
    else:
        overall = "V45_PROOF_CARRYING_WIDTH_REDUCTION_REJECTED"
        next_gate = "REPAIR_OR_REJECT_V45_WIDTH_OR_SEMANTIC_CERTIFICATE"
    core = {
        "aggregate": aggregate,
        "artifact_version": ARTIFACT_VERSION,
        "claim_boundary": copy.deepcopy(spec["claim_boundary"]),
        "coin_isometry_certificate": build_coin_isometry_certificate(),
        "decisions": {
            "materialized_cnot_budget": "PASSED_AT_OR_BELOW_2500000_ALL_EIGHT_SEEDS" if budget_pass else "REJECTED_ABOVE_2500000",
            "next_falsifiable_gate": next_gate,
            "overall": overall,
            "production_admission": "WIDTH_PROOF_ADMITTED_TO_NEXT_OFFLINE_GATE_ONLY_HARDWARE_EXECUTION_REJECTED" if width_pass and semantic_pass and budget_pass else "REJECTED_RESEARCH_ONLY_NO_HARDWARE_EXECUTION_AUTHORIZED",
            "promise_scope": "EXACT_ONLY_FOR_FEASIBLE_N40_DATA_AND_TWO_VALID_BINARY_ADDRESSES_0_TO_39",
        },
        "parent": {
            "artifact_raw_file_sha256": EXPECTED_V44_ARTIFACT_RAW_SHA256,
            "artifact_sha256": EXPECTED_V44_ARTIFACT_SHA256,
            "freeze_raw_file_sha256": EXPECTED_V44_FREEZE_RAW_SHA256,
            "freeze_sha256": EXPECTED_V44_FREEZE_SHA256,
            "immutable_file_count": parent["immutable_file_count"],
            "immutable_files_exact": parent["immutable_files_exact"],
            "overall_decision": ((parent.get("artifact") or {}).get("decisions") or {}).get("overall"),
        },
        "mandatory_off_promise_control": copy.deepcopy(v43.get("mandatory_off_promise_control") or {}),
        "parameter_contract": {
            "binary_coin_ring": "ORDERED_40_EDGE_TWO_LEVEL_RX_CONJUGATE_OF_V43_ONE_HOT_XX_PLUS_YY_ON_VALID_ADDRESSES",
            "binary_invalid_addresses": "40_TO_63_UNTOUCHED_BY_EACH_TWO_LEVEL_RING_EDGE_AND_REJECTED_OUTSIDE_PROMISE",
            "bridge_theta_pi": [BRIDGE_THETA.numerator, BRIDGE_THETA.denominator],
            "coin_theta_pi": [COIN_THETA.numerator, COIN_THETA.denominator],
            "relative_phase_scope": "ONLY_STREAMED_TARGET_ADDRESS_EQUALITY_B_DAGGER_U_B",
        },
        "research_classification": "RESEARCH_ONLY",
        "seed_materializations": seed_rows,
        "standalone_liveness_certificate": {
            "certificate_raw_file_sha256": raw_file_sha256(paths["liveness_certificate"]),
            "certificate_sha256": liveness_semantic_sha256,
            "maximum_logical_qubits": liveness_certificate.get("maximum_logical_qubits"),
            "minimum_capacity_margin_qubits": liveness_certificate.get("minimum_capacity_margin_qubits"),
        },
        "source_raw_file_sha256": raw_file_sha256(paths["source"]),
        "spec_raw_file_sha256": EXPECTED_SPEC_RAW_SHA256,
        "spec_sha256": EXPECTED_SPEC_SHA256,
        "v45_version": V45_VERSION,
        "width_proof_checker_raw_file_sha256": raw_file_sha256(paths["checker"]),
    }
    candidate = {**core, "artifact_sha256": canonical_json_sha256(core)}
    from .phase3_v45_width_proof_checker import validate_v45_artifact

    independent = validate_v45_artifact(candidate, root=paths["root"], authenticate_parent=False)
    if independent.get("valid") is not True:
        raise RuntimeError(f"Independent V4.5 width proof failed: {independent}")
    return candidate


def seal_v45_artifact(*, root: str | Path | None = None, output: str | Path | None = None) -> dict[str, Any]:
    paths = _paths(root)
    artifact = build_v45_artifact(root=paths["root"])
    target = Path(output) if output is not None else paths["artifact"]
    if not target.is_absolute():
        target = paths["root"] / target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(artifact, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return artifact


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--seal", action="store_true")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)
    if not args.seal:
        parser.error("--seal is required")
    payload = seal_v45_artifact(root=args.root, output=args.output)
    print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "ADDRESS_WIDTH",
    "ARTIFACT_VERSION",
    "CircuitLayout",
    "DEFAULT_ARTIFACT_NAME",
    "EXPECTED_V44_ARTIFACT_RAW_SHA256",
    "EXPECTED_V44_ARTIFACT_SHA256",
    "EXPECTED_V44_FREEZE_RAW_SHA256",
    "EXPECTED_V44_FREEZE_SHA256",
    "Register",
    "TARGET_LOGICAL_QUBITS",
    "V45_VERSION",
    "authenticate_v44_parent",
    "build_layout",
    "build_liveness_certificate",
    "build_coin_isometry_certificate",
    "build_v45_liveness_certificate",
    "build_v45_artifact",
    "canonical_json_sha256",
    "emit_binary_coin_rings",
    "emit_binary_selector",
    "load_v45_spec",
    "materialize_seed",
    "read_json_strict",
    "seal_v45_artifact",
    "seal_v45_liveness_certificate",
]
