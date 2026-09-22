"""Quantum Lab V4.8 exact architecture-level CZ reduction experiment.

V4.8 changes one authenticated V4.5 compiler primitive: instead of making
every gate of a Cuccaro constant adder conditional, it coherently loads the
classical constant into a clean register, runs the exact uncontrolled Cuccaro
adder, and unloads the constant.  The construction is an exact controlled
modular addition because the Cuccaro circuit preserves the constant register
and returns its carry ancilla clean.

Every candidate stream is materially emitted and then replayed through the
unchanged V4.6 frozen BasicSwap path oracle.  The module is standard-library
only, imports no provider client, performs no network operation, reads no
credentials, and submits no simulator or QPU job.  Its historical properties
screen is a necessary-condition diagnostic, never a fidelity or hardware
readiness claim.
"""

from __future__ import annotations

import argparse
from collections import Counter
from decimal import Decimal
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import random
from typing import Any, Mapping, Sequence

from .phase3_v42_coined_walk_compiler import SEEDS
from .phase3_v43_reversible_circuit_ir import (
    CircuitStream,
    _emit_base_op,
    _full_adder_ops,
)
from .phase3_v44_named_backend_routing import parse_coupling_edges
from .phase3_v45_proof_carrying_width_reduction import (
    MIN_ARITHMETIC_WIDTH,
    N,
    _emit_addressed_data_update,
    _emit_addressed_read,
    _emit_streamed_target_bit,
    _emit_streamed_target_bit_clear,
    build_layout,
    emit_binary_coin_rings,
    emit_bridge,
)
from .phase3_v43_reversible_circuit_ir import emit_interval_oracle
from .phase3_v46_full_stream_routing import (
    FullStreamRouter,
    TARGET_QUBITS,
    authenticate_v45_parent,
    load_path_oracle,
)
from .phase3_v48_reference_builder import (
    CURRENT_BLOCKED_DECISION,
    NEXT_GATE as SNAPSHOT_NEXT_GATE,
    canonical_json_sha256,
    raw_file_sha256,
    read_json_strict,
)


V48_VERSION = "PHASE III · V4.8 CONTROL-LOADED CUCCARO ARCHITECTURE · V1"
ARTIFACT_VERSION = "PHASE III · V4.8 SEALED MULTI-SNAPSHOT / ARCHITECTURE ARTIFACT · V1"
ARCHITECTURE_ID = "CONTROL_LOADED_CONSTANT_CUCCARO_V1"
ORACLE_FILENAME = "PHASE_III_V4_8_ARCHITECTURE_CANDIDATE_ORACLE_V1.json"
SPEC_FILENAME = "PHASE_III_V4_8_MULTI_SNAPSHOT_CZ_REDUCTION_SPEC_V1.json"
CATALOG_FILENAME = "PHASE_III_V4_8_SNAPSHOT_CATALOG_V1.json"
SNAPSHOTS_FILENAME = "PHASE_III_V4_8_NORMALIZED_SNAPSHOTS_ORACLE_V1.json"
MODEL_FILENAME = "PHASE_III_V4_8_ROBUSTNESS_COST_MODEL_V1.json"
DEFAULT_ARTIFACT_NAME = "SEALED_V4_8_MULTI_SNAPSHOT_ARCHITECTURE_ARTIFACT.json"
DEFAULT_OUTPUT_DIRECTORY = "outputs/quantum_phase3/v48_multi_snapshot_architecture"

V41_ARTIFACT_PATH = (
    "outputs/quantum_phase3/v41_certified_bridge/"
    "SEALED_V4_1_CERTIFIED_BRIDGE_COMPILER_ARTIFACT.json"
)
V44_SNAPSHOT_PATH = "quantum_research_lab/PHASE_III_V4_4_FROZEN_BACKEND_SNAPSHOT_V1.json"
V45_ARTIFACT_PATH = (
    "outputs/quantum_phase3/v45_width_reduction/"
    "SEALED_V4_5_PROOF_CARRYING_WIDTH_REDUCTION_ARTIFACT.json"
)
V46_ARTIFACT_PATH = (
    "outputs/quantum_phase3/v46_full_stream_routing/"
    "SEALED_V4_6_FULL_STREAM_FAKEMARRAKESH_ROUTING_ARTIFACT.json"
)
V47_ARTIFACT_PATH = (
    "outputs/quantum_phase3/v47_dated_properties/"
    "SEALED_V4_7_DATED_PROPERTIES_OPTIMIZATION_ARTIFACT.json"
)
V47_FREEZE_PATH = "FREEZE_CONTRACT_V4_7.json"

EXPECTED_V45_ARTIFACT_RAW_SHA256 = "f28f2975b83d38e32b285cac8c2b7506a07f6341739f3153bde01d42e1219257"
EXPECTED_V45_ARTIFACT_SHA256 = "9ab980071cc247cdbc70e8f964ccfbb09c48997d1d14cc26148c39518facda45"
EXPECTED_V46_ARTIFACT_RAW_SHA256 = "24a55be0ea90242318642b3db7fd00997a71bd8ce896a73e7118f12e65ce6694"
EXPECTED_V46_ARTIFACT_SHA256 = "cbf478af42b35502d4788f70aa96df836145d8e34dadf0c14f2426c241323832"
EXPECTED_V47_ARTIFACT_RAW_SHA256 = "ddb8dae96c1d5fe1040f92731c995315e04232da645fed0b2d34cf7575a06185"
EXPECTED_V47_ARTIFACT_SHA256 = "fa1b8a2be1471080134f34ada7ba8cff488c87077a4e5f271fd29828f1fffbaf"
EXPECTED_V47_FREEZE_RAW_SHA256 = "89dfc8f614955d4fe1c92cfd286ab04f4022d9eb69e566edf46a65e84aa81a3a"
EXPECTED_V47_FREEZE_SHA256 = "3f870a5ff89368d2000a58533fba395b0d077cc377cdc830fdc4b362f6465858"

EQUIVALENCE_EXHAUSTIVE_WIDTHS = (5, 6)
EQUIVALENCE_WIDE_WIDTHS = (7, 8, 16, 31, 33, 34, 35, 36, 39)
EQUIVALENCE_RANDOM_CASES_PER_WIDTH = 2_000
EQUIVALENCE_RANDOM_SEED = 480_048

OVERALL_DECISION = (
    "V48_EXACT_ARCHITECTURE_CX_AND_BASICSWAP_CZ_REDUCTION_DEMONSTRATED_"
    "MULTI_SNAPSHOT_ROBUSTNESS_NOT_EVALUABLE_HARDWARE_REJECTED"
)
PRODUCTION_DECISION = "RESEARCH_ONLY_HARDWARE_EXECUTION_REJECTED"
NEXT_GATE = (
    "ACQUIRE_TWO_ADDITIONAL_AUTHENTIC_OFFLINE_SNAPSHOT_EPOCHS_AND_REDUCE_"
    "DIRECT_CX_BELOW_BOTH_HISTORICAL_NECESSARY_THRESHOLDS_BEFORE_ANY_"
    "CURRENT_PROVIDER_DISCOVERY"
)


def _root(root: str | Path | None = None) -> Path:
    return Path(root).resolve() if root is not None else Path(__file__).resolve().parents[1]


def _is_self_hashed(payload: Mapping[str, Any], field: str) -> bool:
    return bool(
        isinstance(payload.get(field), str)
        and payload.get(field)
        == canonical_json_sha256({key: value for key, value in payload.items() if key != field})
    )


def _authenticate_json(
    path: Path,
    *,
    raw_sha256: str,
    semantic_sha256: str,
    field: str,
) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink() or raw_file_sha256(path) != raw_sha256:
        raise ValueError(f"Raw identity mismatch: {path}")
    payload = read_json_strict(path)
    if payload.get(field) != semantic_sha256 or not _is_self_hashed(payload, field):
        raise ValueError(f"Semantic identity mismatch: {path}")
    return payload


def authenticate_v47_parent(*, root: str | Path | None = None) -> dict[str, Any]:
    """Authenticate the exact V4.5/V4.6/V4.7 artifacts and V4.7 freeze."""

    base = _root(root)
    v45_auth = authenticate_v45_parent(root=base)
    if v45_auth.get("valid") is not True:
        raise ValueError(f"V4.5 parent authentication failed: {v45_auth.get('errors')}")
    v45 = _authenticate_json(
        base / V45_ARTIFACT_PATH,
        raw_sha256=EXPECTED_V45_ARTIFACT_RAW_SHA256,
        semantic_sha256=EXPECTED_V45_ARTIFACT_SHA256,
        field="artifact_sha256",
    )
    v46 = _authenticate_json(
        base / V46_ARTIFACT_PATH,
        raw_sha256=EXPECTED_V46_ARTIFACT_RAW_SHA256,
        semantic_sha256=EXPECTED_V46_ARTIFACT_SHA256,
        field="artifact_sha256",
    )
    v47 = _authenticate_json(
        base / V47_ARTIFACT_PATH,
        raw_sha256=EXPECTED_V47_ARTIFACT_RAW_SHA256,
        semantic_sha256=EXPECTED_V47_ARTIFACT_SHA256,
        field="artifact_sha256",
    )
    freeze = _authenticate_json(
        base / V47_FREEZE_PATH,
        raw_sha256=EXPECTED_V47_FREEZE_RAW_SHA256,
        semantic_sha256=EXPECTED_V47_FREEZE_SHA256,
        field="freeze_contract_sha256",
    )
    if not (
        len(freeze.get("frozen_files") or {})
        == freeze.get("frozen_file_count")
        == 272
    ):
        raise ValueError("V4.7 freeze inventory mismatch.")
    return {"freeze": freeze, "v45": v45, "v46": v46, "v47": v47}


def _record_adder(
    stream: CircuitStream,
    *,
    stage: str,
    width: int,
    encoded: int,
    candidate_cx: int,
    legacy_cx: int,
) -> None:
    line = f"{stage}|{width}|{encoded}|{encoded.bit_count()}|{candidate_cx}|{legacy_cx}\n".encode("ascii")
    hasher = getattr(stream, "_v48_adder_hasher", None)
    if hasher is None:
        hasher = hashlib.sha256()
        setattr(stream, "_v48_adder_hasher", hasher)
        setattr(stream, "_v48_adder_invocations", 0)
        setattr(stream, "_v48_adder_candidate_cx", 0)
        setattr(stream, "_v48_adder_legacy_cx", 0)
        setattr(stream, "_v48_adder_widths", Counter())
    hasher.update(line)
    setattr(stream, "_v48_adder_invocations", int(getattr(stream, "_v48_adder_invocations")) + 1)
    setattr(stream, "_v48_adder_candidate_cx", int(getattr(stream, "_v48_adder_candidate_cx")) + candidate_cx)
    setattr(stream, "_v48_adder_legacy_cx", int(getattr(stream, "_v48_adder_legacy_cx")) + legacy_cx)
    getattr(stream, "_v48_adder_widths")[width] += 1


def adder_evidence(stream: CircuitStream) -> dict[str, Any]:
    hasher = getattr(stream, "_v48_adder_hasher", hashlib.sha256())
    core = {
        "adder_invocation_count": int(getattr(stream, "_v48_adder_invocations", 0)),
        "candidate_adder_cx": int(getattr(stream, "_v48_adder_candidate_cx", 0)),
        "invocation_record_sha256": hasher.hexdigest(),
        "legacy_adder_cx": int(getattr(stream, "_v48_adder_legacy_cx", 0)),
        "width_histogram": {
            str(key): value
            for key, value in sorted(getattr(stream, "_v48_adder_widths", Counter()).items())
        },
    }
    core["adder_cx_reduction"] = core["legacy_adder_cx"] - core["candidate_adder_cx"]
    return {**core, "adder_evidence_sha256": canonical_json_sha256(core)}


def emit_control_loaded_constant_add(
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
    """Exact controlled modular addition via coherent constant load/unload."""

    del ladder  # The architecture removes the legacy C3X ladder from this macro.
    width = len(work)
    if width < MIN_ARITHMETIC_WIDTH or len(constant) < width:
        raise ValueError("V4.8 controlled constant adder width/allocation mismatch.")
    a = tuple(int(qubit) for qubit in constant[:width])
    b = tuple(int(qubit) for qubit in work)
    encoded = int(value) & ((1 << width) - 1)
    popcount = encoded.bit_count()
    before = int(stream.elementary_counts["CX"])
    for index in range(width):
        if (encoded >> index) & 1:
            stream.cx(stage, control, a[index])
    operations = (*_full_adder_ops(a[:-1], b[:-1], b[-1], carry), ("CX", (a[-1], b[-1])))
    for operation in operations:
        _emit_base_op(stream, stage, operation)
    for index in range(width - 1, -1, -1):
        if (encoded >> index) & 1:
            stream.cx(stage, control, a[index])
    candidate_cx = 17 * width - 25 + 2 * popcount
    legacy_cx = 68 * width - 102
    if int(stream.elementary_counts["CX"]) - before != candidate_cx:
        raise AssertionError("V4.8 control-loaded adder CX materialization mismatch.")
    stream.macro_counts[f"CONTROL_LOADED_CONSTANT_ADD_W{width}"] += 1
    _record_adder(
        stream,
        stage=stage,
        width=width,
        encoded=encoded,
        candidate_cx=candidate_cx,
        legacy_cx=legacy_cx,
    )


def _emit_streamed_row_sum_candidate(
    stream: CircuitStream,
    *,
    stage: str,
    row: Mapping[str, Any],
    layout: Any,
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
    mask = (1 << row_width) - 1
    offset = int(row["cache_offset"]) & mask
    indices = range(N) if direction == 1 else range(N - 1, -1, -1)
    if direction == 1:
        for bit in range(row_width):
            if (offset >> bit) & 1:
                stream.x(stage, work[bit])
    for index in indices:
        coefficient = int(row["coefficients"][index])
        if coefficient == 0:
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
        emit_control_loaded_constant_add(
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
        for bit in range(row_width - 1, -1, -1):
            if (offset >> bit) & 1:
                stream.x(stage, work[bit])


def emit_streamed_feasibility_oracle_candidate(
    stream: CircuitStream,
    *,
    stage_prefix: str,
    rows: Sequence[Mapping[str, Any]],
    layout: Any,
    feasible_flag: int,
) -> None:
    constant = layout.register("CONSTANT").qubits
    carry = layout.register("CARRY").qubits[0]
    row_flags = layout.register("ROW_FLAGS").qubits
    for row_index, row in enumerate(rows):
        row_width = max(MIN_ARITHMETIC_WIDTH, int(row["width"]))
        work = layout.register("SUM_WORK").qubits[:row_width]
        _emit_streamed_row_sum_candidate(
            stream, stage=f"{stage_prefix}_ROW_{row_index}_BUILD", row=row, layout=layout, direction=1
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
        _emit_streamed_row_sum_candidate(
            stream, stage=f"{stage_prefix}_ROW_{row_index}_CLEAR", row=row, layout=layout, direction=-1
        )
    stream.mcx(f"{stage_prefix}_SEVEN_ROW_AND", row_flags, feasible_flag, constant[:5])
    for row_index in range(len(rows) - 1, -1, -1):
        row = rows[row_index]
        row_width = max(MIN_ARITHMETIC_WIDTH, int(row["width"]))
        work = layout.register("SUM_WORK").qubits[:row_width]
        _emit_streamed_row_sum_candidate(
            stream, stage=f"{stage_prefix}_ROW_{row_index}_REBUILD", row=row, layout=layout, direction=1
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
        _emit_streamed_row_sum_candidate(
            stream, stage=f"{stage_prefix}_ROW_{row_index}_RECLEAR", row=row, layout=layout, direction=-1
        )
    stream.macro_counts["V48_EXACT_STREAMED_BENNETT_FEASIBILITY_TOGGLE"] += 1


def emit_binary_selector_candidate(
    stream: CircuitStream,
    rows: Sequence[Mapping[str, Any]],
    layout: Any,
) -> None:
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
    emit_streamed_feasibility_oracle_candidate(
        stream, stage_prefix="SELECT_FORWARD_ORACLE", rows=rows, layout=layout,
        feasible_flag=feasible,
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
    emit_streamed_feasibility_oracle_candidate(
        stream, stage_prefix="SELECT_REVERSE_ORACLE", rows=rows, layout=layout,
        feasible_flag=feasible,
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
    stream.macro_counts["PROMISE_SUBSPACE_BINARY_SELECT_V48"] += 1


def _emit_full_candidate(
    stream: CircuitStream,
    *,
    rows: Sequence[Mapping[str, Any]],
    connectivity: Mapping[str, Any],
    progress: Any | None = None,
) -> None:
    layout = build_layout(rows)
    if progress:
        progress("binary coin rings")
    emit_binary_coin_rings(stream, layout)
    if progress:
        progress("control-loaded streamed SELECT")
    emit_binary_selector_candidate(stream, rows, layout)
    for rank, bridge in enumerate(connectivity.get("selected_bridges") or [], start=1):
        if progress:
            progress(f"certified bridge {rank}")
        emit_bridge(stream, bridge=bridge, layout=layout, rank=rank)


def _simulate_base_operations(
    *,
    width: int,
    control: int,
    work: int,
    value: int,
    candidate: bool,
) -> tuple[int, int, int]:
    """Simulate the exact classical permutation of the emitted primitive gates."""

    encoded = int(value) & ((1 << width) - 1)
    # indices: control, A[width], B[width], carry
    a0 = 1
    b0 = 1 + width
    carry_index = 1 + 2 * width
    bits = [0] * (carry_index + 1)
    bits[0] = int(control)
    for index in range(width):
        bits[b0 + index] = (work >> index) & 1

    def x(target: int) -> None:
        bits[target] ^= 1

    def cx(left: int, target: int) -> None:
        bits[target] ^= bits[left]

    def ccx(left: int, right: int, target: int) -> None:
        bits[target] ^= bits[left] & bits[right]

    def c3x(one: int, two: int, three: int, target: int) -> None:
        bits[target] ^= bits[one] & bits[two] & bits[three]

    a = tuple(a0 + index for index in range(width))
    b = tuple(b0 + index for index in range(width))
    operations = (*_full_adder_ops(a[:-1], b[:-1], b[-1], carry_index), ("CX", (a[-1], b[-1])))
    if candidate:
        for index in range(width):
            if (encoded >> index) & 1:
                cx(0, a[index])
        for name, qubits in operations:
            if name == "X":
                x(qubits[0])
            elif name == "CX":
                cx(qubits[0], qubits[1])
            elif name == "CCX":
                ccx(qubits[0], qubits[1], qubits[2])
            else:
                raise AssertionError(name)
        for index in range(width - 1, -1, -1):
            if (encoded >> index) & 1:
                cx(0, a[index])
    else:
        for index in range(width):
            if (encoded >> index) & 1:
                x(a[index])
        for name, qubits in operations:
            if name == "X":
                cx(0, qubits[0])
            elif name == "CX":
                ccx(0, qubits[0], qubits[1])
            elif name == "CCX":
                c3x(0, qubits[0], qubits[1], qubits[2])
            else:
                raise AssertionError(name)
        for index in range(width - 1, -1, -1):
            if (encoded >> index) & 1:
                x(a[index])
    output_work = sum(bits[b0 + index] << index for index in range(width))
    output_constant = sum(bits[a0 + index] << index for index in range(width))
    return output_work, output_constant, bits[carry_index]


def build_equivalence_evidence() -> dict[str, Any]:
    rng = random.Random(EQUIVALENCE_RANDOM_SEED)
    cases: list[tuple[int, int, int, int]] = []
    for width in EQUIVALENCE_EXHAUSTIVE_WIDTHS:
        for control in (0, 1):
            for work in range(1 << width):
                for value in range(1 << width):
                    cases.append((width, control, work, value))
    for width in EQUIVALENCE_WIDE_WIDTHS:
        for _ in range(EQUIVALENCE_RANDOM_CASES_PER_WIDTH):
            cases.append(
                (width, rng.randrange(2), rng.randrange(1 << width), rng.randrange(-(1 << width), 1 << width))
            )
    transcript = hashlib.sha256()
    failures: list[dict[str, int]] = []
    for width, control, work, value in cases:
        legacy = _simulate_base_operations(
            width=width, control=control, work=work, value=value, candidate=False
        )
        candidate = _simulate_base_operations(
            width=width, control=control, work=work, value=value, candidate=True
        )
        expected = ((work + control * value) & ((1 << width) - 1), 0, 0)
        transcript.update(f"{width}|{control}|{work}|{value}|{candidate}\n".encode("ascii"))
        if legacy != candidate or candidate != expected:
            failures.append(
                {"width": width, "control": control, "work": work, "value": value}
            )
            if len(failures) >= 8:
                break
    core = {
        "all_cases_exact": not failures,
        "candidate_construction": "CONTROL_LOAD_CONSTANT_THEN_EXACT_CUCCARO_THEN_CONTROL_UNLOAD",
        "case_count": len(cases),
        "clean_carry_and_constant_exit_all_cases": not failures,
        "deterministic_random_seed": EQUIVALENCE_RANDOM_SEED,
        "exhaustive_case_count": sum(2 * (1 << width) * (1 << width) for width in EQUIVALENCE_EXHAUSTIVE_WIDTHS),
        "exhaustive_widths": list(EQUIVALENCE_EXHAUSTIVE_WIDTHS),
        "failure_examples": failures,
        "reference_construction": "LEGACY_GATE_CONTROLLED_CUCCARO",
        "sampled_wide_case_count": len(EQUIVALENCE_WIDE_WIDTHS) * EQUIVALENCE_RANDOM_CASES_PER_WIDTH,
        "sampled_wide_widths": list(EQUIVALENCE_WIDE_WIDTHS),
        "transcript_sha256": transcript.hexdigest(),
        "unitary_argument": "IDENTICAL_EXACT_COMPUTATIONAL_BASIS_PERMUTATION_WITH_CLEAN_ANCILLAS_AND_NO_RELATIVE_PHASE_IMPLIES_IDENTICAL_LINEAR_UNITARY",
    }
    return {**core, "equivalence_evidence_sha256": canonical_json_sha256(core)}


def _lower_bound(
    direct_cx: int,
    *,
    minimum_error: Decimal,
    minimum_duration_ticks: int,
    maximum_t2_ticks: int,
) -> dict[str, Any]:
    mass = Decimal(direct_cx) * minimum_error
    duration = math.ceil(direct_cx / 78) * minimum_duration_ticks
    core = {
        "direct_translated_cx": direct_cx,
        "idealized_parallel_cz_capacity": 78,
        "minimum_cz_duration_ticks": minimum_duration_ticks,
        "minimum_cz_reported_error": format(minimum_error, "f"),
        "optimistic_cz_duration_lower_bound_ticks": duration,
        "optimistic_cz_duration_over_maximum_snapshot_t2": duration / maximum_t2_ticks,
        "optimistic_reported_error_mass_lower_bound": format(mass, "f"),
        "passes_duration_screen": duration <= maximum_t2_ticks,
        "passes_reported_error_mass_screen": mass < Decimal(1),
        "scope": "ZERO_SWAP_ZERO_1Q_IDEALIZED_NECESSARY_CONDITION_NOT_A_SUFFICIENT_HARDWARE_MODEL",
    }
    return {**core, "architecture_lower_bound_sha256": canonical_json_sha256(core)}


def _seed_inputs(
    parent: Mapping[str, Any],
    *,
    root: Path,
) -> tuple[dict[int, Any], dict[int, Any], dict[int, Any]]:
    v45_rows = {int(row["seed"]): row for row in parent["v45"].get("seed_materializations") or []}
    v46_rows = {int(row["seed"]): row for row in parent["v46"].get("seed_routings") or []}
    v41 = read_json_strict(root / V41_ARTIFACT_PATH)
    connectivity = {
        int(row["seed"]): row
        for row in (v41.get("connectivity_evidence") or {}).get("seed_rows") or []
    }
    if tuple(v45_rows) != tuple(SEEDS) or tuple(v46_rows) != tuple(SEEDS) or tuple(connectivity) != tuple(SEEDS):
        raise ValueError("Authenticated eight-seed input order mismatch.")
    return v45_rows, v46_rows, connectivity


def build_v48_artifact(
    *,
    root: str | Path | None = None,
    progress: Any | None = None,
) -> dict[str, Any]:
    base = _root(root)
    parent = authenticate_v47_parent(root=base)
    oracle_path = base / "quantum_research_lab" / ORACLE_FILENAME
    oracle = read_json_strict(oracle_path)
    if oracle.get("v48_spec_sha256") != canonical_json_sha256(
        {
            key: value
            for key, value in oracle.items()
            if key not in {"v48_spec_sha", "v48_spec_sha256"}
        }
    ):
        raise ValueError("V4.8 architecture candidate oracle identity mismatch.")
    spec_path = base / "quantum_research_lab" / SPEC_FILENAME
    catalog_path = base / "quantum_research_lab" / CATALOG_FILENAME
    snapshots_path = base / "quantum_research_lab" / SNAPSHOTS_FILENAME
    model_path = base / "quantum_research_lab" / MODEL_FILENAME
    for path in (spec_path, catalog_path, snapshots_path, model_path):
        if not path.is_file() or path.is_symlink():
            raise FileNotFoundError(path)
    spec = read_json_strict(spec_path)
    catalog = read_json_strict(catalog_path)
    snapshots = read_json_strict(snapshots_path)
    model = read_json_strict(model_path)
    if int((catalog.get("counts") or {}).get("distinct_epoch_count", -1)) != 1:
        raise ValueError("V4.8 catalog must expose the exact one-snapshot state.")

    v45_rows, v46_rows, connectivity = _seed_inputs(parent, root=base)
    path_oracle, path_table = load_path_oracle(root=base)
    snapshot = read_json_strict(base / V44_SNAPSHOT_PATH)
    target_edges = set(parse_coupling_edges(snapshot))
    normalized = read_json_strict(
        base / "quantum_research_lab/PHASE_III_V4_7_NORMALIZED_PROPERTIES_ORACLE_V1.json"
    )
    cz_stats = normalized["statistics"]["gate_properties"]["cz"]
    minimum_error = Decimal(str(cz_stats["gate_error"]["minimum"]))
    minimum_duration = int(cz_stats["duration_ticks"]["minimum"])
    maximum_t2_ticks = math.floor(
        Decimal(str(normalized["statistics"]["qubits"]["t2_seconds"]["maximum"]))
        / Decimal(str(normalized["backend"]["dt_seconds"]))
    )

    equivalence = build_equivalence_evidence()
    if equivalence.get("all_cases_exact") is not True:
        raise RuntimeError(f"V4.8 adder equivalence failed: {equivalence}")
    seed_evaluations: list[dict[str, Any]] = []
    for seed in SEEDS:
        parent45 = v45_rows[seed]
        parent46 = v46_rows[seed]
        rows = [
            {
                **dict(row),
                "width": int(row.get("v42_width", row.get("v43_materialized_width", -1))),
            }
            for row in (parent45.get("constraint_rows") or [])
        ]
        layout = build_layout(rows)
        if progress:
            progress(f"V4.8 · seed {seed} · candidate stream")
        logical = CircuitStream(seed=seed, total_qubits=layout.total_qubits)
        _emit_full_candidate(logical, rows=rows, connectivity=connectivity[seed])
        manifest = logical.finish()
        logical_adder = adder_evidence(logical)
        parent_manifest = parent45.get("stream_manifest") or {}
        parent_cx = int((parent_manifest.get("elementary_counts") or {}).get("CX", -1))
        candidate_cx = int((manifest.get("elementary_counts") or {}).get("CX", -1))
        if parent_cx - candidate_cx != logical_adder["adder_cx_reduction"]:
            raise AssertionError(f"Seed {seed} CX delta is not fully explained by the adder replacement.")

        if progress:
            progress(f"V4.8 · seed {seed} · frozen BasicSwap route replay")
        router = FullStreamRouter(
            seed=seed,
            total_qubits=layout.total_qubits,
            paths=path_table,
            target_edges=target_edges,
        )
        _emit_full_candidate(router, rows=rows, connectivity=connectivity[seed])
        routed = router.finish_routing(manifest)
        routed_adder = adder_evidence(router)
        if routed_adder != logical_adder or routed.get("input_manifest_exact_parent") is not True:
            raise AssertionError(f"Seed {seed} logical/routing replay drifted.")
        candidate_native = routed["native_ledger"]
        candidate_cz = int(candidate_native["native_operation_counts"]["cz"])
        parent_native = (parent46.get("routed_compilation") or {}).get("native_ledger") or {}
        parent_cz = int((parent_native.get("native_operation_counts") or {}).get("cz", -1))
        lower = _lower_bound(
            candidate_cx,
            minimum_error=minimum_error,
            minimum_duration_ticks=minimum_duration,
            maximum_t2_ticks=maximum_t2_ticks,
        )
        cx_reduction = parent_cx - candidate_cx
        cz_reduction = parent_cz - candidate_cz
        comparison_core = {
            "basic_swap_cz_reduction": cz_reduction,
            "basic_swap_cz_reduction_basis_points": (10_000 * cz_reduction) // parent_cz,
            "basic_swap_cz_reduction_fraction": f"{cz_reduction}/{parent_cz}",
            "candidate_basic_swap_cz": candidate_cz,
            "candidate_cx": candidate_cx,
            "cx_reduction": cx_reduction,
            "cx_reduction_basis_points": (10_000 * cx_reduction) // parent_cx,
            "cx_reduction_fraction": f"{cx_reduction}/{parent_cx}",
            "parent_v45_cx": parent_cx,
            "parent_v46_basic_swap_cz": parent_cz,
            "strict_logical_cx_reduction": candidate_cx < parent_cx,
            "strict_routed_cz_reduction": candidate_cz < parent_cz,
        }
        comparison = {
            **comparison_core,
            "comparison_sha256": canonical_json_sha256(comparison_core),
        }
        routing_core = {
            "adder_evidence": routed_adder,
            "routed_compilation": routed,
            "status": "PASS_EXACT_FROZEN_BASICSWAP_REPLAY_AND_STRICT_CZ_REDUCTION"
            if candidate_cz < parent_cz
            else "REJECT_NO_STRICT_ROUTED_CZ_REDUCTION",
        }
        structural_routing = {
            **routing_core,
            "structural_routing_sha256": canonical_json_sha256(routing_core),
        }
        seed_core = {
            "architecture_lower_bound_v47_comparable": lower,
            "candidate_stream_manifest": manifest,
            "candidate_stream_materialized": True,
            "comparison": comparison,
            "instance_id": parent45.get("instance_id"),
            "logical_qubits": layout.total_qubits,
            "parent_v45_seed_materialization_sha256": parent45.get("seed_materialization_sha256"),
            "parent_v46_seed_routing_sha256": parent46.get("seed_routing_sha256"),
            "seed": seed,
            "structural_routing": structural_routing,
        }
        seed_evaluations.append(
            {**seed_core, "seed_evaluation_sha256": canonical_json_sha256(seed_core)}
        )

    comparisons = [row["comparison"] for row in seed_evaluations]
    lower_bounds = [row["architecture_lower_bound_v47_comparable"] for row in seed_evaluations]
    native_ledgers = [
        row["structural_routing"]["routed_compilation"]["native_ledger"]
        for row in seed_evaluations
    ]
    aggregate_core = {
        "aggregate_candidate_cx": sum(int(row["candidate_cx"]) for row in comparisons),
        "aggregate_candidate_basic_swap_cz": sum(int(row["candidate_basic_swap_cz"]) for row in comparisons),
        "aggregate_cx_reduction": sum(int(row["cx_reduction"]) for row in comparisons),
        "aggregate_parent_v45_cx": sum(int(row["parent_v45_cx"]) for row in comparisons),
        "aggregate_parent_v46_basic_swap_cz": sum(int(row["parent_v46_basic_swap_cz"]) for row in comparisons),
        "aggregate_basic_swap_cz_reduction": sum(int(row["basic_swap_cz_reduction"]) for row in comparisons),
        "all_eight_architecture_lower_bounds_pass_duration_screen": all(row["passes_duration_screen"] for row in lower_bounds),
        "all_eight_architecture_lower_bounds_pass_reported_error_mass_screen": all(row["passes_reported_error_mass_screen"] for row in lower_bounds),
        "all_eight_basic_swap_routes_materialized": all(
            row["structural_routing"]["status"]
            == "PASS_EXACT_FROZEN_BASICSWAP_REPLAY_AND_STRICT_CZ_REDUCTION"
            for row in seed_evaluations
        ),
        "all_eight_candidate_streams_materialized": all(row["candidate_stream_materialized"] for row in seed_evaluations),
        "all_eight_logical_cx_reduced": all(row["strict_logical_cx_reduction"] for row in comparisons),
        "maximum_candidate_basic_swap_cz": max(int(row["candidate_basic_swap_cz"]) for row in comparisons),
        "maximum_candidate_cx": max(int(row["candidate_cx"]) for row in comparisons),
        "maximum_candidate_structural_depth": max(int(row["asap_structural_depth"]) for row in native_ledgers),
        "minimum_candidate_cx": min(int(row["candidate_cx"]) for row in comparisons),
        "minimum_cx_reduction_basis_points": min(int(row["cx_reduction_basis_points"]) for row in comparisons),
        "minimum_basic_swap_cz_reduction_basis_points": min(int(row["basic_swap_cz_reduction_basis_points"]) for row in comparisons),
        "multi_snapshot_distinct_authentic_snapshot_count": int((catalog.get("counts") or {}).get("distinct_epoch_count", 0)),
        "multi_snapshot_robustness_evaluable": False,
        "ordered_seed_evaluation_root_sha256": canonical_json_sha256(
            [row["seed_evaluation_sha256"] for row in seed_evaluations]
        ),
        "seed_count": len(seed_evaluations),
    }
    aggregate = {**aggregate_core, "aggregate_sha256": canonical_json_sha256(aggregate_core)}
    architecture_pass = bool(
        aggregate["all_eight_candidate_streams_materialized"]
        and aggregate["all_eight_logical_cx_reduced"]
        and aggregate["all_eight_basic_swap_routes_materialized"]
    )
    core = {
        "aggregate": aggregate,
        "artifact_version": ARTIFACT_VERSION,
        "candidate_contract": {
            "architecture_id": ARCHITECTURE_ID,
            "candidate_cx_per_add": "17*w-25+2*popcount(c_mod_2_pow_w)",
            "changed_primitive": "CONTROLLED_CONSTANT_ADDER_ONLY",
            "legacy_cx_per_add": "68*w-102",
            "logical_width_and_all_other_v45_primitives": "UNCHANGED",
            "routing_oracle": "EXACT_FROZEN_V4_6_BASICSWAP_PATH_ORACLE",
        },
        "claim_boundary": {
            "backend_run_calls": 0,
            "calibration_aware_circuit_fidelity": "NOT_EVALUATED",
            "credential_reads": 0,
            "hardware_executable": False,
            "local_simulator_jobs_submitted": 0,
            "multi_snapshot_robustness": CURRENT_BLOCKED_DECISION,
            "network_calls": 0,
            "provider_calls": 0,
            "provider_credentials_read": False,
            "provider_sdk_imported": False,
            "qpu_jobs_submitted": 0,
            "quantum_advantage": "NOT_CLAIMED",
            "research_classification": "RESEARCH_ONLY",
            "snapshot_is_current_hardware_evidence": False,
        },
        "decisions": {
            "architecture_candidate": "PASS_EXACT_CONTROL_LOADED_CUCCARO_REDUCTION_ALL_EIGHT" if architecture_pass else "REJECT_ARCHITECTURE_CANDIDATE",
            "exact_stream_materialization": "PASS_ALL_EIGHT" if aggregate["all_eight_candidate_streams_materialized"] else "REJECT",
            "multi_snapshot_robustness": CURRENT_BLOCKED_DECISION,
            "next_falsifiable_gate": NEXT_GATE if architecture_pass else "REPAIR_V48_ARCHITECTURE_CANDIDATE",
            "overall": OVERALL_DECISION if architecture_pass else "V48_ARCHITECTURE_CANDIDATE_REJECTED",
            "production_admission": PRODUCTION_DECISION,
            "structural_routing": "PASS_STRICT_BASICSWAP_CZ_REDUCTION_ALL_EIGHT" if aggregate["all_eight_basic_swap_routes_materialized"] else "REJECT",
            "v47_comparable_lower_bound": "FAIL_BOTH_NECESSARY_SCREENS_ALL_EIGHT" if not any(row["passes_duration_screen"] or row["passes_reported_error_mass_screen"] for row in lower_bounds) else "MIXED_OR_PASSING_SCREEN",
        },
        "equivalence_evidence": equivalence,
        "independent_checker_raw_file_sha256": raw_file_sha256(
            base / "quantum_research_lab/phase3_v48_independent_checker.py"
        ),
        "parent": {
            "v45_artifact_raw_file_sha256": EXPECTED_V45_ARTIFACT_RAW_SHA256,
            "v45_artifact_sha256": EXPECTED_V45_ARTIFACT_SHA256,
            "v46_artifact_raw_file_sha256": EXPECTED_V46_ARTIFACT_RAW_SHA256,
            "v46_artifact_sha256": EXPECTED_V46_ARTIFACT_SHA256,
            "v47_artifact_raw_file_sha256": EXPECTED_V47_ARTIFACT_RAW_SHA256,
            "v47_artifact_sha256": EXPECTED_V47_ARTIFACT_SHA256,
            "v47_freeze_raw_file_sha256": EXPECTED_V47_FREEZE_RAW_SHA256,
            "v47_freeze_sha256": EXPECTED_V47_FREEZE_SHA256,
        },
        "reference_contracts": {
            "architecture_candidate_oracle_raw_file_sha256": raw_file_sha256(oracle_path),
            "architecture_candidate_oracle_sha256": oracle["v48_spec_sha256"],
            "multi_snapshot_spec_raw_file_sha256": raw_file_sha256(spec_path),
            "multi_snapshot_spec_sha256": spec["v48_spec_sha256"],
            "normalized_snapshots_oracle_raw_file_sha256": raw_file_sha256(snapshots_path),
            "normalized_snapshots_oracle_sha256": snapshots["normalized_snapshots_oracle_sha256"],
            "robustness_cost_model_raw_file_sha256": raw_file_sha256(model_path),
            "robustness_cost_model_sha256": model["robustness_cost_model_sha256"],
            "snapshot_catalog_raw_file_sha256": raw_file_sha256(catalog_path),
            "snapshot_catalog_sha256": catalog["snapshot_catalog_sha256"],
            "v46_path_oracle_sha256": path_oracle["path_oracle_sha256"],
        },
        "research_classification": "RESEARCH_ONLY",
        "seed_evaluations": seed_evaluations,
        "source_raw_file_sha256": raw_file_sha256(Path(__file__)),
        "spec_raw_file_sha256": raw_file_sha256(spec_path),
        "spec_sha256": spec["v48_spec_sha256"],
        "v48_version": V48_VERSION,
    }
    return {**core, "artifact_sha256": canonical_json_sha256(core)}


def default_v48_artifact_path(*, root: str | Path | None = None) -> Path:
    return _root(root) / DEFAULT_OUTPUT_DIRECTORY / DEFAULT_ARTIFACT_NAME


def seal_v48_artifact(
    *,
    root: str | Path | None = None,
    output: str | Path | None = None,
    progress: Any | None = None,
) -> dict[str, Any]:
    base = _root(root)
    artifact = build_v48_artifact(root=base, progress=progress)
    target = Path(output) if output is not None else default_v48_artifact_path(root=base)
    if not target.is_absolute():
        target = base / target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(artifact, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return {
        "artifact": str(target),
        "artifact_raw_file_sha256": raw_file_sha256(target),
        "artifact_sha256": artifact["artifact_sha256"],
        "overall": artifact["decisions"]["overall"],
    }


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=None)
    parser.add_argument("--output", default=None)
    parser.add_argument("--equivalence-only", action="store_true")
    args = parser.parse_args(argv)
    if args.equivalence_only:
        result: Any = build_equivalence_evidence()
    else:
        result = seal_v48_artifact(
            root=args.root,
            output=args.output,
            progress=lambda message: print(message, flush=True),
        )
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "ARCHITECTURE_ID",
    "ARTIFACT_VERSION",
    "DEFAULT_ARTIFACT_NAME",
    "NEXT_GATE",
    "OVERALL_DECISION",
    "PRODUCTION_DECISION",
    "V48_VERSION",
    "adder_evidence",
    "authenticate_v47_parent",
    "build_equivalence_evidence",
    "build_v48_artifact",
    "default_v48_artifact_path",
    "emit_control_loaded_constant_add",
    "seal_v48_artifact",
]
