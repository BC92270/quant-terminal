"""Independent standard-library checker for Quantum Lab V4.5.

This module intentionally does not import the V4.5 generator (or any earlier
compiler module).  It authenticates JSON and frozen files directly, rebuilds
the allocation arithmetic, verifies the ordered clean-borrow ledger, and
replays the classical promise-subspace SELECT relation from certificate data.
It imports no provider SDK and performs no network or job operation.
"""

from __future__ import annotations

import argparse
import cmath
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence


EXPECTED_SEEDS = (1103, 2207, 3301, 4409, 5501, 6607, 7703, 8807)
EXPECTED_V45_WIDTHS = (135, 137, 133, 135, 137, 137, 145, 139)
EXPECTED_V43_WIDTHS = (330, 331, 327, 328, 329, 331, 339, 334)
EXPECTED_SPEC_RAW_SHA256 = "fca97bae23543fccb04ba7ca606fa2abb9e4c6e4ebeae3c1501031967a3bfea2"
EXPECTED_SPEC_SHA256 = "ba0c41d1bd0d43817a46c9d66d84eb2ba517bf8dd3975387324726d24487e4e6"
EXPECTED_V44_FREEZE_RAW_SHA256 = "f7b4507410aee41e409b3a0a1ce36ba1adff38299dc8a2d424e13885598ada13"
EXPECTED_V44_FREEZE_SHA256 = "e17aa8ce04c97416f7f0565f2eda4f16b739c5c921fb58ee25752a546ffe95b3"
EXPECTED_V44_PATH_FINGERPRINT = "eb4fda2c2b862fa279a7f0d60f0a2694e50f9c63bf89f60de9d0af52638c0516"
EXPECTED_V44_ARTIFACT_RAW_SHA256 = "3b6824965fa7b2829981d6d35eec5413a24f7340719613e7cd2e8512d6285488"
EXPECTED_V44_ARTIFACT_SHA256 = "de1ba4194a0f7220b1cfcb0c61f8faed3f187c0e9c7712775cba53fa79ed98bb"
EXPECTED_V43_ARTIFACT_RAW_SHA256 = "626123fda2ee6561fe74cbb073a03f9987ccbd4e3d01c84b4f2815023e8271e3"
EXPECTED_V43_ARTIFACT_SHA256 = "36a7a63410da87ce7f98bb10e6d3af3c3d784d9f8e520a6771e42cda9ee593ce"
EXPECTED_V44_FROZEN_FILE_COUNT = 211
EXPECTED_V44_IMMUTABLE_FILE_COUNT = 209
TARGET_QUBITS = 156
DESIGN_CEILING_QUBITS = 145
CNOT_BUDGET = 2_500_000
N = 40
K = 10
SUCCESSOR_MUTABLE = frozenset({"quantum_research_lab/README.md", "quantum_research_lab/ui.py"})
EXPECTED_REGISTER_NAMES = (
    "DATA",
    "REMOVE_ADDR",
    "ADD_ADDR",
    "SUM_WORK",
    "CONSTANT",
    "CARRY",
    "ADDRESSED",
    "ROW_FLAGS",
    "CONTROL_FLAGS",
)


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
        "spec": base / "quantum_research_lab/PHASE_III_V4_5_PROOF_CARRYING_WIDTH_REDUCTION_SPEC_V1.json",
        "source": base / "quantum_research_lab/phase3_v45_proof_carrying_width_reduction.py",
        "checker": base / "quantum_research_lab/phase3_v45_width_proof_checker.py",
        "certificate": base / "quantum_research_lab/PHASE_III_V4_5_REGISTER_LIVENESS_CERTIFICATE_V1.json",
        "v44_freeze": base / "FREEZE_CONTRACT_V4_4.json",
        "v44_artifact": base / "outputs/quantum_phase3/v44_named_backend/SEALED_V4_4_NAMED_BACKEND_ZERO_JOB_ARTIFACT.json",
        "v43_artifact": base / "outputs/quantum_phase3/v43_reversible_circuit/SEALED_V4_3_REVERSIBLE_CIRCUIT_ARTIFACT.json",
        "v41_artifact": base / "outputs/quantum_phase3/v41_certified_bridge/SEALED_V4_1_CERTIFIED_BRIDGE_COMPILER_ARTIFACT.json",
        "artifact": base / "outputs/quantum_phase3/v45_width_reduction/SEALED_V4_5_PROOF_CARRYING_WIDTH_REDUCTION_ARTIFACT.json",
    }


def _path_fingerprint(paths: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(sorted(paths), separators=(",", ":")).encode("utf-8")).hexdigest()


def _self_hash(payload: Mapping[str, Any], field: str) -> bool:
    return payload.get(field) == canonical_json_sha256({key: value for key, value in payload.items() if key != field})


def _authenticate_v44(root: Path) -> tuple[bool, list[str], dict[str, Any]]:
    paths = _paths(root)
    errors: list[str] = []
    try:
        freeze = read_json_strict(paths["v44_freeze"])
        frozen = freeze.get("frozen_files") or {}
        freeze_valid = bool(
            raw_file_sha256(paths["v44_freeze"]) == EXPECTED_V44_FREEZE_RAW_SHA256
            and _self_hash(freeze, "freeze_contract_sha256")
            and freeze.get("freeze_contract_sha256") == EXPECTED_V44_FREEZE_SHA256
            and isinstance(frozen, dict)
            and len(frozen) == freeze.get("frozen_file_count") == EXPECTED_V44_FROZEN_FILE_COUNT
            and _path_fingerprint(frozen)
            == freeze.get("frozen_paths_fingerprint_sha256")
            == EXPECTED_V44_PATH_FINGERPRINT
        )
    except Exception as exc:
        freeze, frozen, freeze_valid = {}, {}, False
        errors.append(f"V4.4 freeze parse/authentication failure: {exc}")
    if not freeze_valid:
        errors.append("V4.4 freeze identity mismatch.")
    immutable = {
        str(relative): str(expected)
        for relative, expected in frozen.items()
        if str(relative) not in SUCCESSOR_MUTABLE
    } if isinstance(frozen, Mapping) else {}
    mismatches = []
    for relative, expected in sorted(immutable.items()):
        candidate = root / relative
        if not candidate.is_file() or candidate.is_symlink() or raw_file_sha256(candidate) != expected:
            mismatches.append(relative)
    if len(immutable) != EXPECTED_V44_IMMUTABLE_FILE_COUNT or mismatches:
        errors.append(f"V4.4 immutable closure mismatch: count={len(immutable)} paths={mismatches[:5]}")
    try:
        artifact = read_json_strict(paths["v44_artifact"])
        artifact_valid = bool(
            raw_file_sha256(paths["v44_artifact"]) == EXPECTED_V44_ARTIFACT_RAW_SHA256
            and _self_hash(artifact, "artifact_sha256")
            and artifact.get("artifact_sha256") == EXPECTED_V44_ARTIFACT_SHA256
            and (artifact.get("decisions") or {}).get("overall")
            == "V44_FAKE_MARRAKESH_CAPACITY_REJECTED_CANARY_PIPELINE_VALIDATED_ZERO_JOB"
        )
    except Exception as exc:
        artifact, artifact_valid = {}, False
        errors.append(f"V4.4 artifact parse/authentication failure: {exc}")
    if not artifact_valid:
        errors.append("V4.4 artifact identity mismatch.")
    return not errors, errors, artifact


def _load_v43(root: Path) -> tuple[bool, dict[str, Any], str]:
    try:
        path = _paths(root)["v43_artifact"]
        payload = read_json_strict(path)
        valid = bool(
            raw_file_sha256(path) == EXPECTED_V43_ARTIFACT_RAW_SHA256
            and _self_hash(payload, "artifact_sha256")
            and payload.get("artifact_sha256") == EXPECTED_V43_ARTIFACT_SHA256
        )
        return valid, payload, "" if valid else "V4.3 artifact identity mismatch."
    except Exception as exc:
        return False, {}, f"V4.3 artifact parse/authentication failure: {exc}"


def _register_layout_checks(row: Mapping[str, Any], expected_width: int) -> dict[str, bool]:
    layout = row.get("register_layout") or {}
    registers = layout.get("registers") or []
    arithmetic_width = int(layout.get("arithmetic_width", -1))
    expected_widths = (40, 6, 6, arithmetic_width, arithmetic_width, 1, 2, 7, 5)
    cursor = 0
    contiguous = True
    ids: list[int] = []
    for register, name, width in zip(registers, EXPECTED_REGISTER_NAMES, expected_widths):
        actual_ids = register.get("qubit_ids") or []
        contiguous &= bool(
            register.get("name") == name
            and int(register.get("start", -1)) == cursor
            and int(register.get("width", -1)) == width
            and actual_ids == list(range(cursor, cursor + width))
        )
        ids.extend(int(value) for value in actual_ids)
        cursor += width
    return {
        "register_count_and_names": len(registers) == len(EXPECTED_REGISTER_NAMES),
        "contiguous_allocation": contiguous,
        "nonoverlapping_qubit_ids": len(ids) == len(set(ids)) == cursor,
        "allocation_formula": cursor == 67 + 2 * arithmetic_width,
        "total_width": cursor == layout.get("total_qubits") == expected_width,
        "capacity": cursor <= TARGET_QUBITS and cursor <= DESIGN_CEILING_QUBITS,
        "register_map_self_hash": _self_hash(layout, "register_map_sha256"),
    }


def _liveness_checks(row: Mapping[str, Any]) -> dict[str, bool]:
    layout = row.get("register_layout") or {}
    registers = {register.get("name"): register for register in layout.get("registers") or []}
    liveness = row.get("liveness") or {}
    events = liveness.get("events") or []
    expected_phases = [
        "BINARY_COIN_RINGS",
        "SELECT_ADDRESS_READ_AND_DATA_UPDATE",
        "STREAMED_TARGET_ROW_ARITHMETIC",
        "CERTIFIED_DATA_BRIDGES",
    ]
    constant = list((registers.get("CONSTANT") or {}).get("qubit_ids") or [])
    sum_work = list((registers.get("SUM_WORK") or {}).get("qubit_ids") or [])
    data = set((registers.get("DATA") or {}).get("qubit_ids") or [])
    bridge_pool = (sum_work + constant)[:37]
    relative = liveness.get("relative_phase_compute_use_uncompute") or {}
    event_borrows = [event.get("borrowed_clean_qubits") for event in events]
    clean_contracts = [
        (event.get("clean_before"), event.get("clean_after"))
        for event in events
    ]
    return {
        "liveness_self_hash": _self_hash(liveness, "liveness_certificate_sha256"),
        "ordered_phases": [event.get("phase") for event in events] == expected_phases,
        "borrow_sets_exact": event_borrows == [constant[:3], constant[:5], constant[:5], bridge_pool],
        "phase_clean_contracts": clean_contracts == [
            (["CONSTANT"], ["CONSTANT"]),
            (["CONSTANT"], ["CONSTANT"]),
            (["SUM_WORK", "CONSTANT", "CARRY", "CONTROL_FLAGS[3:5]"], ["SUM_WORK", "CONSTANT", "CARRY", "CONTROL_FLAGS[3:5]"]),
            (["SUM_WORK", "CONSTANT", "CARRY", "ADDRESSED", "ROW_FLAGS", "CONTROL_FLAGS"], ["SUM_WORK", "CONSTANT", "CARRY", "ADDRESSED", "ROW_FLAGS", "CONTROL_FLAGS"]),
        ],
        "row_flag_lifecycle": len(events) == 4
        and events[2].get("row_flag_lifecycle")
        == "ROW_FLAG_I_BECOMES_LIVE_AFTER_ITS_PREDICATE;_ALL_SEVEN_REMAIN_LIVE_THROUGH_AND;_REVERSE_RECOMPUTATION_CLEARS_I",
        "bridge_pool_sufficient_and_disjoint": len(bridge_pool) == 37 and not data.intersection(bridge_pool),
        "reset_forbidden": liveness.get("reset_instruction_count") == 0,
        "relative_phase_scope": relative.get("scope")
        == "ONLY_FOUR_ADDRESS_EQUALITY_TOGGLES_AROUND_EACH_STREAMED_CONTROLLED_ADD",
        "explicit_adjoint": relative.get("uncompute") == "EXPLICIT_EXACT_ADJOINT_IN_REVERSE_ORDER",
        "clean_exit": liveness.get("clean_exit_registers")
        == ["SUM_WORK", "CONSTANT", "CARRY", "ADDRESSED", "ROW_FLAGS", "CONTROL_FLAGS"],
        "liveness_decision": liveness.get("liveness_decision")
        == "PASSED_STATIC_PHASE_LOCAL_BORROW_AND_CLEAN_EXIT_CONTRACT",
    }


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


def _semantic_checks(
    row: Mapping[str, Any],
    *,
    expected_representatives: Sequence[Mapping[str, Any]],
    expected_v43_row_digest: str,
) -> dict[str, bool]:
    rows = row.get("constraint_rows") or []
    certificate = row.get("semantic_trace_certificate") or {}
    samples = certificate.get("samples") or []
    samples_valid = True
    sample_hashes: list[str] = []
    for sample in samples:
        mask = int(str(sample.get("representative_mask_hex", "-1")), 16)
        trace_hashes: list[str] = []
        moves = 0
        for remove in range(N):
            for add in range(N):
                trace = _select_trace(mask, remove, add, rows)
                trace_hashes.append(canonical_json_sha256(trace))
                moves += int(trace["move"])
        sample_core = {key: value for key, value in sample.items() if key != "sample_sha256"}
        samples_valid &= bool(
            _is_feasible(mask, rows)
            and sample.get("address_pair_count") == 1600
            and sample.get("all_valid_binary_address_pairs_exhausted") is True
            and sample.get("accepted_move_count") == moves
            and sample.get("trace_root_sha256") == canonical_json_sha256(trace_hashes)
            and sample.get("sample_sha256") == canonical_json_sha256(sample_core)
        )
        sample_hashes.append(str(sample.get("sample_sha256")))
    algebraic_rows = all(
        len(row_data.get("coefficients") or []) == N
        and int(row_data.get("cache_offset", 0)) == -int(row_data.get("lower", 0)) + int(row_data.get("guard", 0))
        and int(row_data.get("span", -1)) == int(row_data.get("upper", 0)) - int(row_data.get("lower", 0))
        for row_data in rows
    )
    registered_samples = [
        (str(sample.get("representative_mask_hex")), str(sample.get("representative_sha256")))
        for sample in samples
    ]
    expected_samples = [
        (f"{int(str(representative.get('mask_hex')), 16):010x}", str(representative.get("representative_sha256")))
        for representative in expected_representatives
    ]
    return {
        "seven_constraint_rows": len(rows) == 7,
        "sequential_row_algebra": algebraic_rows,
        "semantic_certificate_self_hash": _self_hash(certificate, "semantic_trace_certificate_sha256"),
        "sample_count": len(samples) == certificate.get("sample_count") and len(samples) >= 1,
        "all_1600_pair_roots": samples_valid,
        "aggregate_trace_root": certificate.get("trace_root_sha256") == canonical_json_sha256(sample_hashes),
        "binary_domain": certificate.get("binary_domain")
        == {"address_width": 6, "invalid_encodings": list(range(40, 64)), "valid": [0, 39]},
        "authenticated_component_representatives": registered_samples == expected_samples,
        "v43_constraint_row_crosslink": row.get("constraint_rows_sha256")
        == canonical_json_sha256(rows)
        == expected_v43_row_digest,
    }


def _exhaustive_local_boolean_identity() -> bool:
    for data in (0, 1):
        for difference in (0, 1):
            for remove_match in (0, 1):
                for add_match in (0, 1):
                    one_hot_target = data ^ (difference & remove_match) ^ (difference & add_match)
                    streamed_target = data ^ (difference and remove_match) ^ (difference and add_match)
                    if int(one_hot_target) != int(streamed_target):
                        return False
    return True


def _exhaustive_small_select_parity() -> bool:
    """Exhaust all 64 N=6 data masks and all 36 valid address pairs."""

    feasible = {mask for mask in range(1 << 6) if mask.bit_count() == 3 and ((mask & 0b11).bit_count() == 1)}
    for start in range(1 << 6):
        for remove in range(6):
            for add in range(6):
                remove_value = (start >> remove) & 1
                add_value = (start >> add) & 1
                difference = remove_value ^ add_value
                one_hot_target = start ^ ((1 << remove) | (1 << add)) if difference else start
                binary_target = start ^ ((1 << remove) | (1 << add)) if difference else start
                one_hot_move = difference & int(one_hot_target in feasible)
                binary_move = difference & int(binary_target in feasible)
                if (one_hot_target, one_hot_move) != (binary_target, binary_move):
                    return False
    return True


def _off_promise_witness_valid(payload: Mapping[str, Any], v43: Mapping[str, Any]) -> bool:
    parent = v43.get("mandatory_off_promise_control") or {}
    return bool(
        payload == parent
        and _self_hash(payload, "witness_sha256")
        and payload.get("status") == "OFF_PROMISE_CLEANUP_REJECTED_WITH_WITNESS"
        and payload.get("witness_detected") is True
        and payload.get("retained_feasible_flag_after_reverse") == 1
    )


def _certificate_checks(
    payload: Mapping[str, Any],
    path: Path,
    artifact_rows: Sequence[Mapping[str, Any]],
) -> dict[str, bool]:
    link = payload.get("standalone_liveness_certificate") or {}
    try:
        certificate = read_json_strict(path)
        rows = certificate.get("seed_rows") or []
        cleanup = certificate.get("cleanup_obligations") or {}
        row_hashes = all(_self_hash(row, "seed_liveness_sha256") for row in rows)
        nested = all(
            _self_hash(row.get("register_layout") or {}, "register_map_sha256")
            and _self_hash(row.get("liveness") or {}, "liveness_certificate_sha256")
            and _self_hash(row.get("width") or {}, "width_row_sha256")
            for row in rows
        )
        return {
            "certificate_self_hash": _self_hash(certificate, "certificate_sha256"),
            "certificate_raw_crosslink": link.get("certificate_raw_file_sha256") == raw_file_sha256(path),
            "certificate_semantic_crosslink": link.get("certificate_sha256") == certificate.get("certificate_sha256"),
            "certificate_seed_order": [row.get("seed") for row in rows] == list(EXPECTED_SEEDS),
            "certificate_seed_self_hashes": row_hashes and nested,
            "certificate_widths": [row.get("register_layout", {}).get("total_qubits") for row in rows]
            == list(EXPECTED_V45_WIDTHS),
            "certificate_boundary": certificate.get("maximum_logical_qubits") == 145
            and certificate.get("minimum_capacity_margin_qubits") == 11,
            "certificate_artifact_crosslinks": len(rows) == len(artifact_rows)
            and all(
                certificate_row.get("register_layout") == artifact_row.get("register_layout")
                and certificate_row.get("liveness") == artifact_row.get("liveness")
                for certificate_row, artifact_row in zip(rows, artifact_rows)
            ),
            "certificate_cleanup_contract": cleanup.get("forbidden")
            == ["RESET", "MEASUREMENT", "DISCARD", "DEPENDENCY_DESTRUCTION_BEFORE_UNCOMPUTE"]
            and cleanup.get("selector_exit")
            == ["SUM_WORK", "CONSTANT", "CARRY", "ADDRESSED", "ROW_FLAGS", "CONTROL_FLAGS"]
            and cleanup.get("relative_phase")
            == "B_DAGGER_U_B_WITH_EXPLICIT_ADJOINT;_U_PRESERVES_B_INPUTS_STREAM_BIT_AND_LADDER_SO_ALL_MONOMIAL_PHASES_CANCEL",
        }
    except Exception:
        return {
            "certificate_self_hash": False,
            "certificate_raw_crosslink": False,
            "certificate_semantic_crosslink": False,
            "certificate_seed_order": False,
            "certificate_seed_self_hashes": False,
            "certificate_widths": False,
            "certificate_boundary": False,
            "certificate_artifact_crosslinks": False,
            "certificate_cleanup_contract": False,
        }


def _coin_isometry_checks(payload: Mapping[str, Any]) -> dict[str, bool]:
    certificate = payload.get("coin_isometry_certificate") or {}
    edges = certificate.get("ordered_edges") or []
    edge_hashes: list[str] = []
    edges_valid = len(edges) == 40
    for rank, edge in enumerate(edges):
        source = rank
        target = (rank + 1) % 40
        differing = [bit for bit in range(6) if ((source ^ target) >> bit) & 1]
        states = [source]
        current = source
        for bit in differing:
            current ^= 1 << bit
            states.append(current)
        edge_core = {key: value for key, value in edge.items() if key != "edge_sha256"}
        edges_valid &= bool(
            edge.get("ordered_edge_rank") == rank
            and edge.get("one_hot_source_qubit") == source
            and edge.get("one_hot_target_qubit") == target
            and edge.get("binary_source") == source
            and edge.get("binary_target") == target
            and edge.get("gray_flip_bits_little_endian") == differing
            and edge.get("gray_states") == states
            and edge.get("edge_sha256") == canonical_json_sha256(edge_core)
        )
        edge_hashes.append(str(edge.get("edge_sha256")))
    return {
        "coin_certificate_self_hash": _self_hash(certificate, "coin_isometry_certificate_sha256"),
        "coin_ordered_edges": edges_valid,
        "coin_edge_root": certificate.get("ordered_edge_root_sha256") == canonical_json_sha256(edge_hashes),
        "coin_valid_isometry": certificate.get("isometry")
        == "V43_ONE_HOT_BASIS_E_I_MAPS_TO_V45_SIX_QUBIT_BINARY_BASIS_I_FOR_I_IN_0_TO_39",
        "coin_invalid_identity": certificate.get("invalid_address_action")
        == "IDENTITY_FOR_40_TO_63_FOR_EVERY_CONJUGATED_TWO_LEVEL_EDGE",
        "coin_conversion_boundary": certificate.get("physical_conversion_circuit")
        == "NOT_PROVIDED_NEW_COMPILED_INTERFACE_REQUIRES_BINARY_INITIALIZATION",
    }


def _rccx_and_adjoint_check() -> bool:
    """Numerically verify the frozen 3-CX RCCX and explicit reverse adjoint."""

    size = 8

    def apply_one(vector: list[complex], qubit: int, matrix: tuple[tuple[complex, complex], tuple[complex, complex]]) -> list[complex]:
        output = vector[:]
        bit = 1 << (2 - qubit)
        for base in range(size):
            if base & bit:
                continue
            partner = base | bit
            a, b = vector[base], vector[partner]
            output[base] = matrix[0][0] * a + matrix[0][1] * b
            output[partner] = matrix[1][0] * a + matrix[1][1] * b
        return output

    def apply_cx(vector: list[complex], control: int, target: int) -> list[complex]:
        output = [0j] * size
        control_bit, target_bit = 1 << (2 - control), 1 << (2 - target)
        for index, amplitude in enumerate(vector):
            destination = index ^ target_bit if index & control_bit else index
            output[destination] += amplitude
        return output

    h = ((1 / math.sqrt(2), 1 / math.sqrt(2)), (1 / math.sqrt(2), -1 / math.sqrt(2)))
    t = ((1, 0), (0, cmath.exp(1j * math.pi / 4)))
    tdg = ((1, 0), (0, cmath.exp(-1j * math.pi / 4)))
    forward = (
        ("H", 2), ("T", 2), ("CX", (1, 2)), ("TDG", 2), ("CX", (0, 2)),
        ("T", 2), ("CX", (1, 2)), ("TDG", 2), ("H", 2),
    )

    def run(vector: list[complex], adjoint: bool) -> list[complex]:
        operations = reversed(forward) if adjoint else forward
        result = vector
        for opcode, operands in operations:
            actual = {"T": "TDG", "TDG": "T"}.get(opcode, opcode) if adjoint else opcode
            if actual == "CX":
                control, target = operands  # type: ignore[misc]
                result = apply_cx(result, int(control), int(target))
            else:
                result = apply_one(result, int(operands), {"H": h, "T": t, "TDG": tdg}[actual])
        return result

    tolerance = 1e-12
    for basis in range(size):
        initial = [0j] * size
        initial[basis] = 1 + 0j
        forward_state = run(initial, False)
        expected_destination = basis ^ 1 if basis & 0b110 == 0b110 else basis
        nonzero = [index for index, amplitude in enumerate(forward_state) if abs(amplitude) > tolerance]
        if nonzero != [expected_destination] or abs(abs(forward_state[expected_destination]) - 1) > tolerance:
            return False
        restored = run(forward_state, True)
        if max(abs(amplitude - initial[index]) for index, amplitude in enumerate(restored)) > tolerance:
            return False
    return True


def _v43_xxplusyy_matches_two_level_rx() -> bool:
    """Independently evaluate the frozen V4.3 beta-zero gate sequence."""

    size = 4

    def one(vector: list[complex], qubit: int, matrix: tuple[tuple[complex, complex], tuple[complex, complex]]) -> list[complex]:
        output = vector[:]
        bit = 1 << (1 - qubit)
        for base in range(size):
            if base & bit:
                continue
            partner = base | bit
            a, b = vector[base], vector[partner]
            output[base] = matrix[0][0] * a + matrix[0][1] * b
            output[partner] = matrix[1][0] * a + matrix[1][1] * b
        return output

    def cx(vector: list[complex], control: int, target: int) -> list[complex]:
        output = [0j] * size
        cbit, tbit = 1 << (1 - control), 1 << (1 - target)
        for index, amplitude in enumerate(vector):
            destination = index ^ tbit if index & cbit else index
            output[destination] += amplitude
        return output

    def rz(angle: float) -> tuple[tuple[complex, complex], tuple[complex, complex]]:
        return ((cmath.exp(-0.5j * angle), 0), (0, cmath.exp(0.5j * angle)))

    def ry(angle: float) -> tuple[tuple[complex, complex], tuple[complex, complex]]:
        return ((math.cos(angle / 2), -math.sin(angle / 2)), (math.sin(angle / 2), math.cos(angle / 2)))

    h = ((1 / math.sqrt(2), 1 / math.sqrt(2)), (1 / math.sqrt(2), -1 / math.sqrt(2)))
    sequence: tuple[tuple[str, int | tuple[int, int], float], ...] = (
        ("RZ", 1, -math.pi / 2), ("H", 1, 0), ("RZ", 1, math.pi / 2),
        ("H", 1, 0), ("RZ", 1, math.pi / 2), ("RZ", 0, math.pi / 2),
        ("CX", (1, 0), 0), ("RY", 1, -math.pi / 4), ("RY", 0, -math.pi / 4),
        ("CX", (1, 0), 0), ("RZ", 0, -math.pi / 2), ("RZ", 1, -math.pi / 2),
        ("H", 1, 0), ("RZ", 1, -math.pi / 2), ("H", 1, 0),
        ("RZ", 1, math.pi / 2),
    )
    tolerance = 1e-12
    cosine, sine = math.cos(math.pi / 4), math.sin(math.pi / 4)
    for basis in range(size):
        state = [0j] * size
        state[basis] = 1 + 0j
        for opcode, operands, angle in sequence:
            if opcode == "CX":
                control, target = operands  # type: ignore[misc]
                state = cx(state, int(control), int(target))
            else:
                matrix = h if opcode == "H" else rz(angle) if opcode == "RZ" else ry(angle)
                state = one(state, int(operands), matrix)
        expected = [0j] * size
        if basis in {0, 3}:
            expected[basis] = 1
        elif basis == 1:
            expected[1], expected[2] = cosine, -1j * sine
        else:
            expected[1], expected[2] = -1j * sine, cosine
        if max(abs(actual - wanted) for actual, wanted in zip(state, expected)) > tolerance:
            return False
    return True


def validate_v45_artifact(
    payload: Mapping[str, Any],
    *,
    root: str | Path | None = None,
    authenticate_parent: bool = True,
) -> dict[str, Any]:
    release_root = _root(root)
    paths = _paths(release_root)
    errors: list[str] = []
    parent_valid, parent_errors, _ = _authenticate_v44(release_root) if authenticate_parent else (True, [], {})
    v43_valid, v43, v43_error = _load_v43(release_root)
    if parent_errors:
        errors.extend(parent_errors)
    if v43_error:
        errors.append(v43_error)
    try:
        spec = read_json_strict(paths["spec"])
        spec_valid = bool(
            raw_file_sha256(paths["spec"]) == EXPECTED_SPEC_RAW_SHA256
            and spec.get("v45_spec_sha256") == EXPECTED_SPEC_SHA256
            and canonical_json_sha256(
                {key: value for key, value in spec.items() if key not in {"v45_spec_sha", "v45_spec_sha256"}}
            ) == EXPECTED_SPEC_SHA256
        )
    except Exception as exc:
        spec, spec_valid = {}, False
        errors.append(f"V4.5 specification authentication failure: {exc}")
    rows = payload.get("seed_materializations") or []
    v43_seed_rows = {int(row["seed"]): row for row in v43.get("seed_materializations") or []}
    try:
        v41 = read_json_strict(paths["v41_artifact"])
        representatives_by_seed = {
            int(row["seed"]): row.get("authenticated_v40_component_representatives") or []
            for row in (v41.get("connectivity_evidence") or {}).get("seed_rows") or []
        }
    except Exception as exc:
        representatives_by_seed = {}
        errors.append(f"V4.1 representative evidence parse failure: {exc}")
    per_seed: list[dict[str, Any]] = []
    for position, row in enumerate(rows):
        expected_width = EXPECTED_V45_WIDTHS[position] if position < len(EXPECTED_V45_WIDTHS) else -1
        layout_checks = _register_layout_checks(row, expected_width)
        liveness_checks = _liveness_checks(row)
        seed = int(row.get("seed", -1))
        semantic_checks = _semantic_checks(
            row,
            expected_representatives=representatives_by_seed.get(seed, ()),
            expected_v43_row_digest=str(v43_seed_rows.get(seed, {}).get("constraint_rows_sha256", "")),
        )
        stream = row.get("stream_manifest") or {}
        width = row.get("width_certificate") or {}
        cnot = int((stream.get("elementary_counts") or {}).get("CX", -1))
        checks = {
            **layout_checks,
            **liveness_checks,
            **semantic_checks,
            "seed_self_hash": _self_hash(row, "seed_materialization_sha256"),
            "stream_self_hash": _self_hash(stream, "stream_manifest_sha256"),
            "width_self_hash": _self_hash(width, "width_certificate_sha256"),
            "width_crosslinks": bool(
                width.get("seed") == row.get("seed")
                and width.get("new_logical_qubits") == expected_width
                and width.get("old_logical_qubits") == EXPECTED_V43_WIDTHS[position]
                and width.get("capacity_margin_qubits") == TARGET_QUBITS - expected_width
            ),
            "cnot_budget": 0 <= cnot <= CNOT_BUDGET,
            "coin_isometry_macro_count": (stream.get("macro_counts") or {}).get("BINARY_TWO_LEVEL_RX") == 80,
            "relative_phase_scope_count": bool(
                int((stream.get("macro_counts") or {}).get("RELATIVE_PHASE_C7X", 0))
                == int((stream.get("macro_counts") or {}).get("RELATIVE_PHASE_C7X_DAGGER", 0))
                and int((stream.get("macro_counts") or {}).get("RELATIVE_PHASE_C7X", 0)) > 0
            ),
            "no_reset_or_measure_basis": not {"RESET", "MEASURE"}.intersection(stream.get("basis") or []),
        }
        per_seed.append({"checks": checks, "seed": row.get("seed"), "valid": all(checks.values())})
    aggregate = payload.get("aggregate") or {}
    boundary = payload.get("claim_boundary") or {}
    decisions = payload.get("decisions") or {}
    parent_link = payload.get("parent") or {}
    global_checks: dict[str, bool] = {
        "artifact_self_hash": _self_hash(payload, "artifact_sha256"),
        "artifact_version": payload.get("artifact_version")
        == "PHASE III · V4.5 SEALED PROOF-CARRYING WIDTH REDUCTION · V1",
        "spec_identity": spec_valid
        and payload.get("spec_raw_file_sha256") == EXPECTED_SPEC_RAW_SHA256
        and payload.get("spec_sha256") == EXPECTED_SPEC_SHA256,
        "parent_authentication": parent_valid and v43_valid,
        "parent_crosslinks": bool(
            parent_link.get("artifact_raw_file_sha256") == EXPECTED_V44_ARTIFACT_RAW_SHA256
            and parent_link.get("artifact_sha256") == EXPECTED_V44_ARTIFACT_SHA256
            and parent_link.get("freeze_raw_file_sha256") == EXPECTED_V44_FREEZE_RAW_SHA256
            and parent_link.get("freeze_sha256") == EXPECTED_V44_FREEZE_SHA256
            and parent_link.get("immutable_file_count") == EXPECTED_V44_IMMUTABLE_FILE_COUNT
            and parent_link.get("immutable_files_exact") is True
        ),
        "eight_seed_order": [row.get("seed") for row in rows] == list(EXPECTED_SEEDS),
        "all_seed_checks": len(per_seed) == 8 and all(row["valid"] for row in per_seed),
        "aggregate_self_hash": _self_hash(aggregate, "aggregate_sha256"),
        "aggregate_width": aggregate.get("maximum_logical_qubits") == 145
        and aggregate.get("minimum_capacity_margin_qubits") == 11
        and aggregate.get("all_eight_widths") == list(EXPECTED_V45_WIDTHS)
        and aggregate.get("all_eight_widths_fit_156") is True,
        "aggregate_budget": aggregate.get("all_eight_materialized_cnot_counts_at_or_below_2500000") is True
        and aggregate.get("cnot_budget_pass_count") == 8
        and int(aggregate.get("maximum_materialized_cnot", CNOT_BUDGET + 1)) <= CNOT_BUDGET,
        "boundary_zero_job": bool(
            boundary.get("research_classification") == "RESEARCH_ONLY"
            and boundary.get("provider_calls") == 0
            and boundary.get("network_calls") == 0
            and boundary.get("credential_reads") == 0
            and boundary.get("qpu_jobs_submitted") == 0
            and boundary.get("hardware_executable") is False
            and boundary.get("quantum_advantage") == "NOT_CLAIMED"
            and boundary.get("full_workload_routing") == "NOT_RUN_IN_V4_5"
            and boundary.get("full_workload_transpilation") == "NOT_RUN_IN_V4_5"
        ),
        "decision": decisions.get("overall") == "V45_PROOF_CARRYING_WIDTH_REDUCTION_PASSED_EXACT_PROMISE_PARITY"
        and decisions.get("materialized_cnot_budget") == "PASSED_AT_OR_BELOW_2500000_ALL_EIGHT_SEEDS"
        and decisions.get("next_falsifiable_gate")
        == "PINNED_FAKEMARRAKESH_FULL_RECONSTRUCTION_TRANSLATION_AND_ROUTING_OF_WIDTH_ADMITTED_V4_5_STREAMS"
        and decisions.get("production_admission")
        == "WIDTH_PROOF_ADMITTED_TO_NEXT_OFFLINE_GATE_ONLY_HARDWARE_EXECUTION_REJECTED",
        "exhaustive_streamed_target_boolean_identity": _exhaustive_local_boolean_identity(),
        "exhaustive_small_select_parity": _exhaustive_small_select_parity(),
        "off_promise_witness_retained": _off_promise_witness_valid(
            payload.get("mandatory_off_promise_control") or {}, v43
        ),
        "source_identity": paths["source"].is_file()
        and payload.get("source_raw_file_sha256") == raw_file_sha256(paths["source"]),
        "checker_identity": paths["checker"].is_file()
        and payload.get("width_proof_checker_raw_file_sha256") == raw_file_sha256(paths["checker"]),
        "rccx_exact_adjoint": _rccx_and_adjoint_check(),
        "v43_xxplusyy_binary_rx_parity": _v43_xxplusyy_matches_two_level_rx(),
    }
    global_checks.update(_coin_isometry_checks(payload))
    global_checks.update(_certificate_checks(payload, paths["certificate"], rows))
    failed = [name for name, valid in global_checks.items() if not valid]
    for seed_row in per_seed:
        failed.extend(
            f"seed_{seed_row['seed']}:{name}"
            for name, valid in seed_row["checks"].items()
            if not valid
        )
    if failed:
        errors.append(f"Failed checks: {failed}")
    result_core = {
        "check_count": len(global_checks) + sum(len(row["checks"]) for row in per_seed),
        "errors": list(dict.fromkeys(errors)),
        "global_checks": global_checks,
        "per_seed": per_seed,
        "valid": not errors and all(global_checks.values()) and all(row["valid"] for row in per_seed),
        "verifier": "QUANTUM LAB V4.5 INDEPENDENT WIDTH PROOF CHECKER · V1",
    }
    return {**result_core, "verification_sha256": canonical_json_sha256(result_core)}


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--artifact", type=Path, default=None)
    args = parser.parse_args(argv)
    paths = _paths(args.root)
    target = args.artifact or paths["artifact"]
    if not target.is_absolute():
        target = args.root / target
    result = validate_v45_artifact(read_json_strict(target), root=args.root)
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "canonical_json_sha256",
    "read_json_strict",
    "validate_v45_artifact",
]
