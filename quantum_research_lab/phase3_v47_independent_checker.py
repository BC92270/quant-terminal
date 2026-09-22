"""Standard-library independent checker for Quantum Lab V4.7.

This module deliberately does not import the V4.7 compiler, Qiskit or a
provider SDK.  It authenticates the frozen V4.6 parent and every V4.7 input,
reconstructs the fault-excluded path objective, checks all nested hashes and
recomputes the duration, reported-error-mass, resource, Pareto, lower-bound and
decision ledgers from the sealed artifact.

The dated FakeMarrakesh properties are historical evidence only.  Nothing in
this checker turns an offline replay into a hardware run, a fidelity estimate,
or evidence about a current backend.
"""

from __future__ import annotations

import argparse
from collections import Counter, deque
from decimal import Decimal, InvalidOperation, localcontext
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence


ARTIFACT_VERSION = "PHASE III · V4.7 SEALED DATED PROPERTIES OPTIMIZATION ARTIFACT · V1"
CANDIDATE_NAME = "FAULT_EXCLUDED_SHORTEST_HOP_RELIABILITY_TIEBREAK_V1"
BASELINE_NAME = "V4_6_EXACT_BASIC_SWAP_BASELINE"
EXPECTED_SEEDS = (1103, 2207, 3301, 4409, 5501, 6607, 7703, 8807)
EXPECTED_WIDTHS = (135, 137, 133, 135, 137, 137, 145, 139)
TARGET_QUBITS = 156
SUCCESSOR_MUTABLE = {"quantum_research_lab/README.md", "quantum_research_lab/ui.py"}

EXPECTED_SPEC_RAW_SHA256 = "07cd0b0be907e417f5dbe1df62defb90322828e9181a81016b78432e8b5e9644"
EXPECTED_SPEC_SHA256 = "c5b0b294f00a002cf351774c6e91fe17c02896f1517444a42d9dd1b63995574b"
EXPECTED_RAW_PROPERTIES_SHA256 = "d49d7ae07deb95947ea10e5b9b9c5cbab6df21f98610543817f35ade2b1aece6"
EXPECTED_RAW_PROPERTIES_SIZE = 565_487
EXPECTED_PROPERTIES_RAW_SHA256 = "46203d513fc295639a314cdb4b95aa1eb407f6a303be28c5033086aa2a210a99"
EXPECTED_PROPERTIES_SHA256 = "0e436981a23bd6e75679752f4c139658ef811acc94adc6758b0dc99075e75fe7"
EXPECTED_PATH_ORACLE_RAW_SHA256 = "585df824749a55a7217dca134b4f30c2395c8ee980ea1d8148e3a4c2bddea386"
EXPECTED_PATH_ORACLE_SHA256 = "a725e3d5746c5ccc9821d25db1decebe583e110b09a02404b5b9455613c0f8ab"
EXPECTED_MODEL_RAW_SHA256 = "eb242116e47da51e737571f70163d640eab2eb84e430fa9499155ce93f1a27f6"
EXPECTED_MODEL_SHA256 = "7c22bc90483c1bb02365f65564adcfc6e90952ded3062519c05fb2a4bc40d285"

EXPECTED_V46_FREEZE_RAW_SHA256 = "2a025b3a67fd56287deca8d793745a6a3a6b8db5063f85a5af4057cb8b29e5bd"
EXPECTED_V46_FREEZE_SHA256 = "178e60504085130b774d60bff794f6d5602400b87b13aa28f5308e33ce417104"
EXPECTED_V46_FROZEN_FILE_COUNT = 249
EXPECTED_V46_IMMUTABLE_FILE_COUNT = 247
EXPECTED_V46_PATH_FINGERPRINT = "6be1cbbc2d414298b4907878eac9e3924152679dfeb20e71079f409a0e22ccac"
EXPECTED_V46_ARTIFACT_RAW_SHA256 = "24a55be0ea90242318642b3db7fd00997a71bd8ce896a73e7118f12e65ce6694"
EXPECTED_V46_ARTIFACT_SHA256 = "cbf478af42b35502d4788f70aa96df836145d8e34dadf0c14f2426c241323832"
EXPECTED_V46_ROUTE_ROOT_SHA256 = "e3552ceff09d10237f6000c75c39acb276745526c7f663b1778b5c07a3300d8f"
EXPECTED_V46_SEED_ROOT_SHA256 = "4a3b069472814606134e82aa17823102a028093876cf45a2fad29e45dc3290e7"

# Increment this only when an independently meaningful check is added or
# removed.  Artifact hashes are intentionally optional parameters because the
# checker is sealed before the first V4.7 result artifact.
EXPECTED_CHECK_COUNT = 51


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
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _rows(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(row, Mapping) for row in value):
        return []
    return list(value)


def _is_sha(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text)


def _self_hash(payload: Mapping[str, Any], field: str) -> bool:
    return bool(
        _is_sha(payload.get(field))
        and payload.get(field)
        == canonical_json_sha256({key: value for key, value in payload.items() if key != field})
    )


def _spec_hash(payload: Mapping[str, Any]) -> bool:
    core = {key: value for key, value in payload.items() if key not in {"v47_spec_sha", "v47_spec_sha256"}}
    semantic = canonical_json_sha256(core)
    return bool(
        semantic == payload.get("v47_spec_sha256") == EXPECTED_SPEC_SHA256
        and payload.get("v47_spec_sha") == semantic[:20].upper()
    )


def _path_fingerprint(paths: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(sorted(paths), separators=(",", ":")).encode("utf-8")).hexdigest()


def _decimal(value: Any) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"Invalid decimal value: {value!r}") from exc
    if not result.is_finite():
        raise ValueError(f"Non-finite decimal value: {value!r}")
    return result


def _format_decimal(value: Decimal) -> str:
    return format(value, "f")


def _paths(root: Path) -> dict[str, Path]:
    module = root / "quantum_research_lab"
    return {
        "spec": module / "PHASE_III_V4_7_PINNED_DATED_PROPERTIES_OPTIMIZATION_SPEC_V1.json",
        "properties": module / "PHASE_III_V4_7_NORMALIZED_PROPERTIES_ORACLE_V1.json",
        "raw_properties": module / "PHASE_III_V4_7_FAKEMARRAKESH_PROPERTIES_2025_02_26_RAW.json",
        "path_oracle": module / "PHASE_III_V4_7_FAULT_EXCLUDED_PATH_ORACLE_V1.json",
        "model": module / "PHASE_III_V4_7_DURATION_ERROR_MODEL_CONTRACT_V1.json",
        "source": module / "phase3_v47_dated_properties_optimizer.py",
        "checker": module / "phase3_v47_independent_checker.py",
        "v46_freeze": root / "FREEZE_CONTRACT_V4_6.json",
        "v46_artifact": root / "outputs/quantum_phase3/v46_full_stream_routing/SEALED_V4_6_FULL_STREAM_FAKEMARRAKESH_ROUTING_ARTIFACT.json",
    }


def _authenticate_parent(root: Path, *, verify_immutable_files: bool) -> tuple[dict[str, Any], bool, list[str]]:
    paths = _paths(root)
    errors: list[str] = []
    freeze: dict[str, Any] = {}
    artifact: dict[str, Any] = {}
    try:
        freeze = read_json_strict(paths["v46_freeze"])
        frozen = _mapping(freeze.get("frozen_files"))
        freeze_ok = bool(
            raw_file_sha256(paths["v46_freeze"]) == EXPECTED_V46_FREEZE_RAW_SHA256
            and freeze.get("freeze_contract_sha256") == EXPECTED_V46_FREEZE_SHA256
            and _self_hash(freeze, "freeze_contract_sha256")
            and len(frozen) == freeze.get("frozen_file_count") == EXPECTED_V46_FROZEN_FILE_COUNT
            and _path_fingerprint(frozen) == EXPECTED_V46_PATH_FINGERPRINT
        )
        if not freeze_ok:
            errors.append("V4.6 freeze raw, semantic or inventory identity mismatch.")
        immutable = {
            str(relative): str(expected)
            for relative, expected in frozen.items()
            if str(relative) not in SUCCESSOR_MUTABLE
        }
        if len(immutable) != EXPECTED_V46_IMMUTABLE_FILE_COUNT:
            errors.append(f"V4.6 immutable inventory count mismatch: {len(immutable)}")
        if verify_immutable_files:
            mismatches = [
                relative
                for relative, expected in sorted(immutable.items())
                if not (root / relative).is_file()
                or (root / relative).is_symlink()
                or raw_file_sha256(root / relative) != expected
            ]
            if mismatches:
                errors.append(f"V4.6 immutable path mismatch: {mismatches[:5]}")
    except Exception as exc:
        errors.append(f"V4.6 freeze authentication failed: {exc}")

    try:
        artifact = read_json_strict(paths["v46_artifact"])
        aggregate = _mapping(artifact.get("aggregate"))
        decisions = _mapping(artifact.get("decisions"))
        artifact_ok = bool(
            raw_file_sha256(paths["v46_artifact"]) == EXPECTED_V46_ARTIFACT_RAW_SHA256
            and artifact.get("artifact_sha256") == EXPECTED_V46_ARTIFACT_SHA256
            and _self_hash(artifact, "artifact_sha256")
            and aggregate.get("ordered_route_ir_root_sha256") == EXPECTED_V46_ROUTE_ROOT_SHA256
            and aggregate.get("ordered_seed_routing_root_sha256") == EXPECTED_V46_SEED_ROOT_SHA256
            and decisions.get("next_falsifiable_gate")
            == "PINNED_DATED_PROPERTIES_DURATION_ERROR_AND_OPTIMIZATION_FEASIBILITY_OF_V46_ROUTED_STREAMS"
        )
        if not artifact_ok:
            errors.append("V4.6 artifact identity, route root or decision mismatch.")
    except Exception as exc:
        errors.append(f"V4.6 artifact authentication failed: {exc}")
    return artifact, not errors, list(dict.fromkeys(errors))


def _components(adjacency: Mapping[int, set[int]]) -> list[list[int]]:
    unseen = set(adjacency)
    result: list[list[int]] = []
    while unseen:
        start = min(unseen)
        queue = deque([start])
        unseen.remove(start)
        component: list[int] = []
        while queue:
            node = queue.popleft()
            component.append(node)
            for neighbour in sorted(adjacency[node]):
                if neighbour in unseen:
                    unseen.remove(neighbour)
                    queue.append(neighbour)
        result.append(sorted(component))
    return sorted(result, key=lambda row: (-len(row), row))


def _property_index(payload: Mapping[str, Any]) -> tuple[dict[tuple[str, tuple[int, ...]], Mapping[str, Any]], bool]:
    lookup: dict[tuple[str, tuple[int, ...]], Mapping[str, Any]] = {}
    valid = True
    counts: Counter[str] = Counter()
    for row in _rows(payload.get("native_properties")):
        gate = str(row.get("gate", ""))
        qubits = tuple(int(value) for value in row.get("qubits") or [])
        key = (gate, qubits)
        error = _decimal(row.get("gate_error"))
        duration = row.get("duration_ticks")
        duration_seconds = row.get("duration_seconds")
        expected_arity = 2 if gate == "cz" else 1
        row_valid = bool(
            gate in {"cz", "id", "rz", "sx", "x"}
            and len(qubits) == expected_arity
            and all(0 <= qubit < TARGET_QUBITS for qubit in qubits)
            and key not in lookup
            and Decimal(0) <= error <= Decimal(1)
            and isinstance(duration, int)
            and not isinstance(duration, bool)
            and duration >= 0
            and isinstance(duration_seconds, (int, float))
            and not isinstance(duration_seconds, bool)
            and math.isfinite(float(duration_seconds))
            and math.isclose(float(duration_seconds), duration * 4e-9, rel_tol=0.0, abs_tol=1e-18)
        )
        valid = valid and row_valid
        if key not in lookup:
            lookup[key] = row
            counts[gate] += 1
    expected_counts = {"cz": 352, "id": 156, "rz": 156, "sx": 156, "x": 156}
    valid = valid and dict(counts) == expected_counts and len(lookup) == 976
    valid = valid and all(
        (gate, (qubit,)) in lookup
        for gate in ("id", "rz", "sx", "x")
        for qubit in range(TARGET_QUBITS)
    )
    return lookup, valid


def _validate_properties(payload: Mapping[str, Any]) -> tuple[dict[tuple[str, tuple[int, ...]], Mapping[str, Any]], dict[str, bool]]:
    lookup, tuples_valid = _property_index(payload)
    backend = _mapping(payload.get("backend"))
    coverage = _mapping(payload.get("coverage"))
    boundary = _mapping(payload.get("claim_boundary"))
    fault = _mapping(payload.get("fault_screen"))
    qubits = _rows(payload.get("qubit_properties"))
    qubit_valid = len(qubits) == TARGET_QUBITS and [row.get("qubit") for row in qubits] == list(range(TARGET_QUBITS))
    for row in qubits:
        values = [
            row.get("t1_seconds"),
            row.get("t2_seconds"),
            row.get("readout_error"),
            row.get("readout_length_seconds"),
            row.get("prob_meas0_prep1"),
            row.get("prob_meas1_prep0"),
        ]
        qubit_valid = qubit_valid and all(
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
            and float(value) >= 0
            for value in values
        )

    directed_healthy: dict[int, set[int]] = {qubit: set() for qubit in range(TARGET_QUBITS)}
    excluded: list[list[int]] = []
    for (gate, qargs), row in lookup.items():
        if gate != "cz":
            continue
        left, right = qargs
        if _decimal(row.get("gate_error")) >= Decimal(1):
            excluded.append([left, right])
        else:
            directed_healthy[left].add(right)
    adjacency = {qubit: set(neighbours) for qubit, neighbours in directed_healthy.items()}
    for left in range(TARGET_QUBITS):
        adjacency[left] = {right for right in adjacency[left] if left in adjacency[right]}
    components = _components(adjacency)
    fault_valid = bool(
        sorted(excluded) == fault.get("excluded_directed_cz_edges")
        and len(excluded) == fault.get("excluded_directed_cz_edge_count") == 26
        and len({tuple(sorted(row)) for row in excluded}) == fault.get("excluded_undirected_cz_edge_count") == 13
        and [len(row) for row in components] == fault.get("fault_excluded_component_sizes") == [153, 1, 1, 1]
        and [row[0] for row in components[1:]] == fault.get("isolated_qubits") == [24, 102, 113]
        and components[0] == fault.get("largest_component_qubits")
        and fault.get("largest_component_size") == 153
    )
    return lookup, {
        "properties_backend_contract": bool(
            backend.get("backend_name") == "fake_marrakesh"
            and backend.get("source_backend_name") == "ibm_marrakesh"
            and backend.get("num_qubits") == TARGET_QUBITS
            and backend.get("dt_nanoseconds") == 4
            and backend.get("basis_gates") == ["cz", "id", "rz", "sx", "x"]
        ),
        "properties_tuple_coverage": bool(
            tuples_valid
            and coverage.get("all_required_gate_tuples_complete") is True
            and coverage.get("native_gate_tuple_count") == 976
            and coverage.get("required_property_value_count") == 1952
            and coverage.get("expected_gate_counts") == {"cz": 352, "id": 156, "rz": 156, "sx": 156, "x": 156}
        ),
        "properties_qubit_coverage": qubit_valid,
        "properties_fault_screen_recomputed": fault_valid,
        "properties_claim_boundary": bool(
            boundary.get("research_classification") == "RESEARCH_ONLY"
            and boundary.get("hardware_executable") is False
            and boundary.get("snapshot_is_current_hardware_evidence") is False
            and boundary.get("provider_calls") == boundary.get("network_calls") == boundary.get("qpu_jobs_submitted") == 0
        ),
    }


def _shortest_distances(adjacency: Mapping[int, set[int]], destination: int) -> dict[int, int]:
    distances = {destination: 0}
    queue = deque([destination])
    while queue:
        node = queue.popleft()
        for neighbour in sorted(adjacency[node]):
            if neighbour not in distances:
                distances[neighbour] = distances[node] + 1
                queue.append(neighbour)
    return distances


def _swap_cost(
    left: int,
    right: int,
    properties: Mapping[tuple[str, tuple[int, ...]], Mapping[str, Any]],
) -> tuple[Decimal, int]:
    cz = properties[("cz", (left, right))]
    sx_left = properties[("sx", (left,))]
    sx_right = properties[("sx", (right,))]
    return (
        Decimal(3) * (_decimal(cz["gate_error"]) + _decimal(sx_left["gate_error"]) + _decimal(sx_right["gate_error"])),
        3 * int(cz["duration_ticks"]) + 3 * max(int(sx_left["duration_ticks"]), int(sx_right["duration_ticks"])),
    )


def _cx_cost(
    control: int,
    target: int,
    properties: Mapping[tuple[str, tuple[int, ...]], Mapping[str, Any]],
) -> tuple[Decimal, int]:
    cz = properties[("cz", (control, target))]
    sx = properties[("sx", (target,))]
    return (
        _decimal(cz["gate_error"]) + Decimal(2) * _decimal(sx["gate_error"]),
        int(cz["duration_ticks"]) + 2 * int(sx["duration_ticks"]),
    )


def _validate_path_oracle(
    payload: Mapping[str, Any],
    properties: Mapping[tuple[str, tuple[int, ...]], Mapping[str, Any]],
) -> dict[str, bool]:
    component = [int(value) for value in payload.get("component_qubits") or []]
    component_set = set(component)
    adjacency: dict[int, set[int]] = {qubit: set() for qubit in component}
    for left in component:
        for right in component:
            if left == right:
                continue
            forward = properties.get(("cz", (left, right)))
            reverse = properties.get(("cz", (right, left)))
            if (
                forward is not None
                and reverse is not None
                and _decimal(forward.get("gate_error")) < Decimal(1)
                and _decimal(reverse.get("gate_error")) < Decimal(1)
            ):
                adjacency[left].add(right)

    parsed: dict[tuple[int, int], tuple[int, ...]] = {}
    stream_lines: list[str] = []
    rows_valid = True
    for line in str(payload.get("ordered_paths_compact", "")).splitlines():
        try:
            source_text, destination_text, route_text = line.split("|", 2)
            source, destination = int(source_text), int(destination_text)
            route = tuple(int(value) for value in route_text.split(","))
            key = (source, destination)
            valid = bool(
                source != destination
                and source in component_set
                and destination in component_set
                and key not in parsed
                and route[0] == source
                and route[-1] == destination
                and set(route) <= component_set
                and len(route) == len(set(route))
                and all(right in adjacency[left] for left, right in zip(route, route[1:]))
            )
        except Exception:
            rows_valid = False
            continue
        rows_valid = rows_valid and valid
        if valid:
            parsed[key] = route
        stream_lines.append(line + "\n")

    expected_order = [
        (source, destination)
        for destination in component
        for source in component
        if source != destination
    ]
    order_valid = list(parsed) == expected_order
    objective_valid = True
    maximum_hops = 0
    for destination in component:
        distances = _shortest_distances(adjacency, destination)
        best_paths: dict[int, tuple[int, ...]] = {destination: (destination,)}
        costs: dict[int, tuple[Decimal, int]] = {destination: (Decimal(0), 0)}
        for node in sorted(distances, key=lambda value: (distances[value], value)):
            if node == destination:
                continue
            candidates: list[tuple[Decimal, int, tuple[int, ...]]] = []
            for neighbour in sorted(adjacency[node]):
                if distances.get(neighbour) != distances[node] - 1 or neighbour not in best_paths:
                    continue
                local = _cx_cost(node, neighbour, properties) if neighbour == destination else _swap_cost(node, neighbour, properties)
                tail = costs[neighbour]
                candidates.append((local[0] + tail[0], local[1] + tail[1], (node,) + best_paths[neighbour]))
            if not candidates:
                objective_valid = False
                continue
            error_mass, duration, route = min(candidates)
            costs[node] = (error_mass, duration)
            best_paths[node] = route
            maximum_hops = max(maximum_hops, len(route) - 1)
            objective_valid = objective_valid and parsed.get((node, destination)) == route

    return {
        "path_oracle_contract": bool(
            payload.get("candidate_name") == CANDIDATE_NAME
            and component == sorted(component)
            and len(component) == payload.get("component_size") == 153
            and payload.get("ordered_path_count") == 153 * 152
            and payload.get("properties_snapshot_sha256") == EXPECTED_PROPERTIES_SHA256
            and payload.get("research_classification") == "RESEARCH_ONLY"
        ),
        "path_oracle_stream_hash": bool(
            hashlib.sha256("".join(stream_lines).encode("ascii")).hexdigest()
            == payload.get("ordered_paths_stream_sha256")
        ),
        "path_oracle_rows_complete": bool(rows_valid and order_valid and len(parsed) == 153 * 152),
        "path_oracle_objective_recomputed": bool(objective_valid and maximum_hops == payload.get("maximum_hops") == 43),
    }


def _native_algebra(manifest: Mapping[str, Any], native: Mapping[str, Any]) -> bool:
    counts = _mapping(manifest.get("elementary_counts"))
    native_counts = _mapping(native.get("native_operation_counts"))
    input_cx = int(counts.get("CX", -1))
    swaps = int(native.get("swap_count", -1))
    expected = {
        "cz": input_cx + 3 * swaps,
        "id": 0,
        "rz": 2 * int(counts.get("H", 0)) + int(counts.get("T", 0)) + int(counts.get("TDG", 0)) + 3 * int(counts.get("RY", 0)) + int(counts.get("RZ", 0)) + 4 * input_cx,
        "sx": int(counts.get("H", 0)) + 2 * int(counts.get("RY", 0)) + 2 * input_cx + 6 * swaps,
        "x": int(counts.get("X", 0)),
    }
    return bool(
        dict(native_counts) == expected
        and native.get("direct_translated_cx_count") == input_cx
        and native.get("native_instruction_count") == sum(expected.values())
    )


def _layout_valid(layout: Mapping[str, Any], width: int, expected_initial: list[int]) -> bool:
    logical_to_physical = layout.get("final_logical_to_physical") or []
    physical_to_logical = layout.get("final_physical_to_logical") or []
    valid = bool(
        layout.get("logical_qubits") == width
        and layout.get("physical_qubits") == TARGET_QUBITS
        and layout.get("initial_layout") == expected_initial
        and layout.get("initial_layout_contract")
        == (
            "TRIVIAL_LOGICAL_Q_TO_PHYSICAL_Q"
            if expected_initial == list(range(width))
            else "LOGICAL_ORDER_TO_ASCENDING_FAULT_EXCLUDED_COMPONENT_PREFIX"
        )
        and layout.get("output_interpretation")
        == "FINAL_LAYOUT_IS_THE_PERMUTATION_REQUIRED_TO_INTERPRET_LOGICAL_OUTPUTS"
        and len(logical_to_physical) == width
        and len(physical_to_logical) == TARGET_QUBITS
        and len(set(logical_to_physical)) == width
        and all(isinstance(value, int) and 0 <= value < TARGET_QUBITS for value in logical_to_physical)
    )
    if valid:
        valid = all(physical_to_logical[physical] == logical for logical, physical in enumerate(logical_to_physical))
        valid = valid and all(
            value is None or (isinstance(value, int) and 0 <= value < width)
            for value in physical_to_logical
        )
        used = layout.get("used_physical_qubits") or []
        valid = valid and used == sorted(set(used)) and all(
            isinstance(value, int) and 0 <= value < TARGET_QUBITS for value in used
        )
    return valid


def _validate_routed(
    routed: Mapping[str, Any],
    *,
    expected_manifest: Mapping[str, Any],
    expected_initial: list[int],
    width: int,
    properties: Mapping[tuple[str, tuple[int, ...]], Mapping[str, Any]],
) -> tuple[dict[str, bool], dict[str, Any]]:
    manifest = _mapping(routed.get("input_stream_manifest"))
    route = _mapping(routed.get("route_ir"))
    native = _mapping(routed.get("native_ledger"))
    routing = _mapping(routed.get("routing_ledger"))
    layout = _mapping(routed.get("layout"))
    usage = _mapping(routed.get("physical_property_usage"))
    error = _mapping(routed.get("error_screen"))
    stages = _mapping(routed.get("stage_property_usage"))
    timing = _mapping(routed.get("timing_ledger"))

    nested_hashes = all(
        (
            _self_hash(manifest, "stream_manifest_sha256"),
            _self_hash(route, "route_ir_sha256"),
            _self_hash(native, "native_ledger_sha256"),
            _self_hash(routing, "routing_ledger_sha256"),
            _self_hash(layout, "layout_sha256"),
            _self_hash(usage, "physical_property_usage_sha256"),
            _self_hash(error, "error_screen_sha256"),
            _self_hash(stages, "stage_property_usage_sha256"),
            _self_hash(timing, "timing_ledger_sha256"),
        )
    )
    instruction_count = int(manifest.get("instruction_count", -1))
    chunk_sizes = route.get("chunk_instruction_sizes") or []
    route_stages = _rows(route.get("stage_manifests"))
    swaps = int(native.get("swap_count", -1))
    route_valid = bool(
        route.get("input_instruction_count") == instruction_count
        and sum(int(value) for value in chunk_sizes) == instruction_count
        and len(chunk_sizes) == len(route.get("chunk_sha256") or [])
        and all(0 < int(value) <= 8192 for value in chunk_sizes)
        and all(_is_sha(value) for value in route.get("chunk_sha256") or [])
        and _is_sha(route.get("route_record_stream_sha256"))
        and sum(int(row.get("input_instruction_count", 0)) for row in route_stages) == instruction_count
        and sum(int(row.get("swap_count", 0)) for row in route_stages) == swaps
        and all(_is_sha(row.get("route_record_sha256")) for row in route_stages)
    )
    histogram = _mapping(routing.get("distance_histogram_before_each_cx"))
    input_cx = int(_mapping(manifest.get("elementary_counts")).get("CX", -1))
    distance_valid = bool(
        sum(int(value) for value in histogram.values()) == input_cx
        and sum((int(distance) - 1) * int(count) for distance, count in histogram.items()) == swaps
        and routing.get("maximum_distance_before_routing") == max((int(value) for value in histogram), default=0)
    )

    usage_rows = _rows(usage.get("exact_gate_qargs_occurrences"))
    usage_valid = True
    seen: set[tuple[str, tuple[int, ...]]] = set()
    previous_usage: tuple[str, tuple[int, ...]] | None = None
    occurrence_by_gate: Counter[str] = Counter()
    mass_by_gate = {name: Decimal(0) for name in ("cz", "id", "rz", "sx", "x")}
    total_mass = Decimal(0)
    unit_occurrences = 0
    diagnostic_log10 = 0.0
    diagnostic_defined = True
    for row in usage_rows:
        gate = str(row.get("gate", ""))
        qargs = tuple(int(value) for value in row.get("qubits") or [])
        key = (gate, qargs)
        prop = properties.get(key)
        count = row.get("occurrence_count")
        row_valid = bool(
            prop is not None
            and isinstance(count, int)
            and not isinstance(count, bool)
            and count > 0
            and key not in seen
            and (previous_usage is None or previous_usage < key)
        )
        usage_valid = usage_valid and row_valid
        previous_usage = key
        if not row_valid or prop is None:
            continue
        seen.add(key)
        reported_error = _decimal(prop.get("gate_error"))
        duration = int(prop.get("duration_ticks", -1))
        occurrence_by_gate[gate] += count
        mass = reported_error * count
        mass_by_gate[gate] += mass
        total_mass += mass
        if reported_error >= 1:
            unit_occurrences += count
            diagnostic_defined = False
        else:
            diagnostic_log10 += count * math.log10(1.0 - float(reported_error))
        usage_valid = usage_valid and bool(
            row.get("duration_ticks_each") == duration
            and row.get("reported_error_each") == str(prop.get("gate_error"))
            and row.get("reported_error_mass") == _format_decimal(mass)
            and row.get("serial_duration_ticks") == duration * count
        )
    native_counts = _mapping(native.get("native_operation_counts"))
    usage_valid = usage_valid and bool(
        usage.get("property_tuple_count_used") == len(usage_rows) == len(seen)
        and usage.get("gate_occurrence_count") == sum(occurrence_by_gate.values())
        and dict(occurrence_by_gate) == {key: int(value) for key, value in native_counts.items() if int(value) > 0}
    )
    diagnostic = error.get("diagnostic_independent_product_log10")
    diagnostic_valid = diagnostic is None if not diagnostic_defined else isinstance(diagnostic, (int, float)) and math.isclose(float(diagnostic), diagnostic_log10, rel_tol=1e-12, abs_tol=1e-9)
    error_valid = bool(
        error.get("reported_gate_error_mass") == _format_decimal(total_mass)
        and error.get("reported_gate_error_mass_by_gate")
        == {gate: _format_decimal(value) for gate, value in sorted(mass_by_gate.items())}
        and error.get("unit_error_gate_occurrences") == unit_occurrences
        and error.get("missing_property_occurrences") == 0
        and error.get("calibration_aware_circuit_fidelity") == "NOT_CLAIMED"
        and error.get("independent_product_is_acceptance_metric") is False
        and error.get("reported_gate_error_mass_interpretation")
        == "DESCRIPTIVE_SUM_NOT_FIDELITY_SUCCESS_PROBABILITY_OR_EXPECTED_FAILURE_COUNT"
        and diagnostic_valid
    )
    stage_rows = _rows(stages.get("rows"))
    stage_counts: Counter[str] = Counter()
    stages_valid = True
    previous: tuple[str, str] | None = None
    for row in stage_rows:
        key = (str(row.get("stage", "")), str(row.get("gate", "")))
        count = row.get("occurrence_count")
        stages_valid = stages_valid and bool(
            previous is None or previous < key
        ) and isinstance(count, int) and not isinstance(count, bool) and count > 0
        previous = key
        if isinstance(count, int) and not isinstance(count, bool):
            stage_counts[key[1]] += count
    stages_valid = stages_valid and dict(stage_counts) == dict(occurrence_by_gate)

    clocks = timing.get("final_physical_clock_ticks") or []
    makespan = max(clocks, default=-1) if all(isinstance(value, int) and not isinstance(value, bool) for value in clocks) else -1
    timing_valid = bool(
        len(clocks) == TARGET_QUBITS
        and all(isinstance(value, int) and not isinstance(value, bool) and value >= 0 for value in clocks)
        and timing.get("dt_nanoseconds") == 4
        and timing.get("makespan_ticks") == makespan
        and timing.get("makespan_nanoseconds") == makespan * 4
        and isinstance(timing.get("makespan_seconds"), (int, float))
        and math.isclose(float(timing.get("makespan_seconds")), makespan * 4e-9, rel_tol=1e-15, abs_tol=1e-18)
        and timing.get("model_name") == "PROPERTIES_CONDITIONED_PER_QUBIT_ASAP_INTEGER_DT"
        and timing.get("not_hardware_job_or_pulse_runtime") is True
    )
    return {
        "nested_self_hashes": nested_hashes,
        "manifest_exact_parent": bool(routed.get("input_manifest_exact_parent") is True and manifest == expected_manifest),
        "route_accounting": route_valid,
        "distance_swap_identity": distance_valid,
        "native_count_algebra": _native_algebra(manifest, native),
        "native_structural_boundary": bool(
            native.get("coupling_violations") == 0
            and native.get("isa_violations") == 0
            and native.get("native_basis") == ["cz", "id", "rz", "sx", "x"]
        ),
        "layout_bijection": _layout_valid(layout, width, expected_initial),
        "property_usage_recomputed": usage_valid,
        "error_screen_recomputed": error_valid,
        "stage_usage_recomputed": stages_valid,
        "timing_ledger_recomputed": timing_valid,
    }, {
        "cz": int(native_counts.get("cz", -1)),
        "depth": int(native.get("asap_structural_depth", -1)),
        "direct_cx": int(native.get("direct_translated_cx_count", -1)),
        "error_mass": total_mass,
        "makespan_ticks": makespan,
        "unit_occurrences": unit_occurrences,
    }


def _resource_valid(
    resource: Mapping[str, Any],
    metrics: Mapping[str, Any],
    width: int,
    *,
    layout_bijective: bool,
    manifest_exact: bool,
    native_boundary: bool,
) -> tuple[bool, bool]:
    parent_cx = int(resource.get("v45_input_cx", -1))
    if parent_cx <= 0:
        return False, False
    ratio = Fraction(int(metrics["cz"]), parent_cx)
    accepted = bool(
        manifest_exact
        and native_boundary
        and layout_bijective
        and width <= TARGET_QUBITS
        and int(metrics["cz"]) <= 250_000_000
        and int(metrics["depth"]) <= 250_000_000
        and ratio <= 100
        and int(metrics["unit_occurrences"]) == 0
    )
    valid = bool(
        _self_hash(resource, "resource_gate_sha256")
        and resource.get("cz_expansion_ratio_exact") == f"{ratio.numerator}/{ratio.denominator}"
        and resource.get("final_layout_bijective") is layout_bijective
        and resource.get("logical_capacity_margin") == TARGET_QUBITS - width
        and resource.get("maximum_native_cz") == 250_000_000
        and resource.get("maximum_native_cz_expansion_over_v45_cx") == 100
        and resource.get("maximum_structural_depth") == 250_000_000
        and resource.get("status")
        == ("PASS_V47_RESEARCH_FEASIBILITY_GATE" if accepted else "REJECT_V47_RESEARCH_FEASIBILITY_GATE")
    )
    return valid, accepted


def _validate_v47_artifact(
    artifact: Mapping[str, Any],
    *,
    root: str | Path,
    authenticate_parent: bool = True,
    expected_artifact_sha256: str | None = None,
    artifact_raw_file_sha256: str | None = None,
    expected_artifact_raw_sha256: str | None = None,
) -> dict[str, Any]:
    """Validate a V4.7 artifact without importing the implementation.

    ``authenticate_parent=False`` skips hashing all 247 V4.6 immutable paths,
    but still requires the exact V4.6 freeze and artifact identities.  Optional
    artifact pins support the post-result release verifier without introducing
    a pre-result circular hash constant into this checker.
    """

    base = Path(root).resolve()
    paths = _paths(base)
    errors: list[str] = []
    try:
        spec = read_json_strict(paths["spec"])
        properties_payload = read_json_strict(paths["properties"])
        path_oracle = read_json_strict(paths["path_oracle"])
        model = read_json_strict(paths["model"])
        parent, parent_ok, parent_errors = _authenticate_parent(base, verify_immutable_files=authenticate_parent)
        errors.extend(parent_errors)
    except Exception as exc:
        spec = properties_payload = path_oracle = model = parent = {}
        parent_ok = False
        errors.append(f"Input authentication failed: {exc}")

    try:
        properties, property_checks = _validate_properties(properties_payload)
    except Exception as exc:
        properties, property_checks = {}, {
            "properties_backend_contract": False,
            "properties_tuple_coverage": False,
            "properties_qubit_coverage": False,
            "properties_fault_screen_recomputed": False,
            "properties_claim_boundary": False,
        }
        errors.append(f"Property-oracle validation failed: {exc}")
    try:
        path_checks = _validate_path_oracle(path_oracle, properties)
    except Exception as exc:
        path_checks = {
            "path_oracle_contract": False,
            "path_oracle_stream_hash": False,
            "path_oracle_rows_complete": False,
            "path_oracle_objective_recomputed": False,
        }
        errors.append(f"Path-oracle validation failed: {exc}")

    if expected_artifact_sha256 is not None and artifact.get("artifact_sha256") != expected_artifact_sha256:
        errors.append("Pinned V4.7 artifact semantic identity mismatch.")
    if expected_artifact_raw_sha256 is not None and artifact_raw_file_sha256 != expected_artifact_raw_sha256:
        errors.append("Pinned V4.7 artifact raw identity mismatch.")

    parent_rows = {
        int(row.get("seed", -1)): row
        for row in _rows(parent.get("seed_routings"))
    }
    seed_rows = _rows(artifact.get("seed_evaluations"))
    component = [int(value) for value in path_oracle.get("component_qubits") or []]
    all_seed_hashes = True
    all_nested_hashes = True
    all_manifest = True
    all_routes = True
    all_distances = True
    all_native_algebra = True
    all_native_boundary = True
    all_layouts = True
    all_usage = True
    all_errors = True
    all_stages = True
    all_timing = True
    all_resources = True
    all_baseline_exact = True
    all_lower_bounds = True
    all_comparisons = True
    candidate_feasible_flags: list[bool] = []
    pareto_flags: list[bool] = []
    architecture_fail_flags: list[bool] = []
    baseline_units: list[int] = []
    candidate_units: list[int] = []
    baseline_makespans: list[int] = []
    candidate_makespans: list[int] = []

    cz_rows = [row for (gate, _), row in properties.items() if gate == "cz"]
    min_cz_error = min((_decimal(row.get("gate_error")) for row in cz_rows), default=Decimal("NaN"))
    min_cz_ticks = min((int(row.get("duration_ticks", -1)) for row in cz_rows), default=-1)
    qubit_rows = _rows(properties_payload.get("qubit_properties"))
    max_t2_seconds = max((float(row.get("t2_seconds", 0)) for row in qubit_rows), default=0.0)
    maximum_t2_ticks = math.floor(max_t2_seconds / 4e-9) if max_t2_seconds > 0 else -1

    for row in seed_rows:
        seed = int(row.get("seed", -1))
        width = int(row.get("logical_qubits", -1))
        parent_row = _mapping(parent_rows.get(seed))
        parent_routed = _mapping(parent_row.get("routed_compilation"))
        parent_manifest = _mapping(parent_routed.get("input_stream_manifest"))
        baseline_wrapper = _mapping(row.get("baseline_v46"))
        candidate_wrapper = _mapping(row.get("candidate"))
        baseline = _mapping(baseline_wrapper.get("routed_compilation"))
        candidate = _mapping(candidate_wrapper.get("routed_compilation"))
        baseline_checks, baseline_metrics = _validate_routed(
            baseline,
            expected_manifest=parent_manifest,
            expected_initial=list(range(width)),
            width=width,
            properties=properties,
        )
        candidate_checks, candidate_metrics = _validate_routed(
            candidate,
            expected_manifest=parent_manifest,
            expected_initial=component[:width],
            width=width,
            properties=properties,
        )
        all_seed_hashes = all_seed_hashes and _self_hash(row, "seed_evaluation_sha256")
        all_nested_hashes = all_nested_hashes and baseline_checks["nested_self_hashes"] and candidate_checks["nested_self_hashes"]
        all_manifest = all_manifest and baseline_checks["manifest_exact_parent"] and candidate_checks["manifest_exact_parent"]
        all_routes = all_routes and baseline_checks["route_accounting"] and candidate_checks["route_accounting"]
        all_distances = all_distances and baseline_checks["distance_swap_identity"] and candidate_checks["distance_swap_identity"]
        all_native_algebra = all_native_algebra and baseline_checks["native_count_algebra"] and candidate_checks["native_count_algebra"]
        all_native_boundary = all_native_boundary and baseline_checks["native_structural_boundary"] and candidate_checks["native_structural_boundary"]
        all_layouts = all_layouts and baseline_checks["layout_bijection"] and candidate_checks["layout_bijection"]
        all_usage = all_usage and baseline_checks["property_usage_recomputed"] and candidate_checks["property_usage_recomputed"]
        all_errors = all_errors and baseline_checks["error_screen_recomputed"] and candidate_checks["error_screen_recomputed"]
        all_stages = all_stages and baseline_checks["stage_usage_recomputed"] and candidate_checks["stage_usage_recomputed"]
        all_timing = all_timing and baseline_checks["timing_ledger_recomputed"] and candidate_checks["timing_ledger_recomputed"]

        baseline_resource_valid, baseline_feasible = _resource_valid(
            _mapping(baseline_wrapper.get("resource_gate")),
            baseline_metrics,
            width,
            layout_bijective=baseline_checks["layout_bijection"],
            manifest_exact=baseline_checks["manifest_exact_parent"],
            native_boundary=baseline_checks["native_structural_boundary"],
        )
        candidate_resource_valid, candidate_feasible = _resource_valid(
            _mapping(candidate_wrapper.get("resource_gate")),
            candidate_metrics,
            width,
            layout_bijective=candidate_checks["layout_bijection"],
            manifest_exact=candidate_checks["manifest_exact_parent"],
            native_boundary=candidate_checks["native_structural_boundary"],
        )
        all_resources = all_resources and baseline_resource_valid and candidate_resource_valid
        candidate_feasible_flags.append(candidate_feasible)
        baseline_units.append(int(baseline_metrics["unit_occurrences"]))
        candidate_units.append(int(candidate_metrics["unit_occurrences"]))
        baseline_makespans.append(int(baseline_metrics["makespan_ticks"]))
        candidate_makespans.append(int(candidate_metrics["makespan_ticks"]))

        baseline_commitment = bool(
            row.get("baseline_v46_commitments_exact") is True
            and baseline.get("route_ir") == parent_routed.get("route_ir")
            and baseline.get("native_ledger") == parent_routed.get("native_ledger")
            and baseline.get("v46_compatible_layout_commitment") == parent_routed.get("layout")
            and baseline.get("routing_ledger") == parent_routed.get("routing_ledger")
            and _mapping(baseline.get("input_stream_manifest")) == parent_manifest
            and baseline_wrapper.get("candidate_name") == BASELINE_NAME
            and baseline_wrapper.get("status")
            == ("REJECT_DATED_PROPERTIES_UNIT_ERROR_USAGE" if baseline_metrics["unit_occurrences"] else "MODELED_ONLY_NO_HARDWARE_ADMISSION")
        )
        all_baseline_exact = all_baseline_exact and baseline_commitment
        expected_candidate_status = "PASS_RESEARCH_OPTIMIZATION_FEASIBILITY" if candidate_feasible else "REJECT_RESEARCH_OPTIMIZATION_FEASIBILITY"
        all_resources = all_resources and bool(
            candidate_wrapper.get("candidate_name") == CANDIDATE_NAME
            and candidate_wrapper.get("status") == expected_candidate_status
            and candidate.get("v46_compatible_layout_commitment") is None
            and _mapping(candidate.get("routing_ledger")).get("candidate_name") == CANDIDATE_NAME
            and _mapping(candidate.get("routing_ledger")).get("path_oracle_sha256") == EXPECTED_PATH_ORACLE_SHA256
            and _mapping(candidate.get("routing_ledger")).get("routing_method")
            == "FAULT_EXCLUDED_MINIMUM_HOP_REPORTED_ERROR_DURATION_LEXICOGRAPHIC_STATIC_ORACLE"
            and _mapping(candidate.get("routing_ledger")).get("transpiler_seed") is None
        )

        lower = _mapping(row.get("architecture_lower_bound"))
        direct_cx = int(baseline_metrics["direct_cx"])
        lower_ticks = math.ceil(direct_cx / 78) * min_cz_ticks
        lower_mass = Decimal(direct_cx) * min_cz_error
        duration_pass = lower_ticks <= maximum_t2_ticks
        error_pass = lower_mass < Decimal(1)
        lower_valid = bool(
            _self_hash(lower, "architecture_lower_bound_sha256")
            and lower.get("direct_translated_cx") == direct_cx
            and lower.get("idealized_parallel_cz_capacity") == 78
            and lower.get("minimum_cz_duration_ticks") == min_cz_ticks
            and lower.get("minimum_cz_reported_error") == _format_decimal(min_cz_error)
            and lower.get("optimistic_cz_duration_lower_bound_ticks") == lower_ticks
            and isinstance(lower.get("optimistic_cz_duration_over_maximum_snapshot_t2"), (int, float))
            and math.isclose(float(lower.get("optimistic_cz_duration_over_maximum_snapshot_t2")), lower_ticks / maximum_t2_ticks, rel_tol=1e-15, abs_tol=1e-15)
            and lower.get("optimistic_reported_error_mass_lower_bound") == _format_decimal(lower_mass)
            and lower.get("passes_duration_screen") is duration_pass
            and lower.get("passes_reported_error_mass_screen") is error_pass
            and lower.get("scope") == "ZERO_SWAP_ZERO_1Q_IDEALIZED_NECESSARY_CONDITION_NOT_A_SUFFICIENT_HARDWARE_MODEL"
        )
        all_lower_bounds = all_lower_bounds and lower_valid
        architecture_fail_flags.append(not duration_pass and not error_pass)

        comparison = _mapping(row.get("comparison"))
        pareto = bool(
            candidate_feasible
            and candidate_metrics["error_mass"] < baseline_metrics["error_mass"]
            and candidate_metrics["makespan_ticks"] <= baseline_metrics["makespan_ticks"]
            and candidate_metrics["cz"] <= baseline_metrics["cz"]
        )
        comparison_valid = bool(
            _self_hash(comparison, "comparison_sha256")
            and comparison.get("candidate_minus_baseline_makespan_ticks") == candidate_metrics["makespan_ticks"] - baseline_metrics["makespan_ticks"]
            and comparison.get("candidate_minus_baseline_native_cz") == candidate_metrics["cz"] - baseline_metrics["cz"]
            and comparison.get("candidate_minus_baseline_reported_error_mass") == _format_decimal(candidate_metrics["error_mass"] - baseline_metrics["error_mass"])
            and comparison.get("pareto_safe_for_seed") is pareto
            and comparison.get("pareto_status") == ("PARETO_DOMINATES_BASELINE" if pareto else "PARETO_SAFE_REPLACEMENT_NOT_DEMONSTRATED_FOR_SEED")
        )
        all_comparisons = all_comparisons and comparison_valid
        pareto_flags.append(pareto)
        all_seed_hashes = all_seed_hashes and bool(
            row.get("instance_id") == parent_row.get("instance_id")
            and width == parent_row.get("logical_qubits")
        )

    aggregate = _mapping(artifact.get("aggregate"))
    all_candidate_feasible = len(candidate_feasible_flags) == 8 and all(candidate_feasible_flags)
    all_pareto = len(pareto_flags) == 8 and all(pareto_flags)
    all_architecture_fail = len(architecture_fail_flags) == 8 and all(architecture_fail_flags)
    aggregate_valid = bool(
        _self_hash(aggregate, "aggregate_sha256")
        and aggregate.get("seed_count") == len(seed_rows) == 8
        and aggregate.get("all_eight_architecture_lower_bounds_fail_both_screens") is all_architecture_fail
        and aggregate.get("all_eight_baseline_commitments_exact_v46") is all_baseline_exact
        and aggregate.get("all_eight_candidate_research_feasible") is all_candidate_feasible
        and aggregate.get("all_eight_pareto_safe") is all_pareto
        and aggregate.get("baseline_total_unit_error_gate_occurrences") == sum(baseline_units)
        and aggregate.get("candidate_total_unit_error_gate_occurrences") == sum(candidate_units)
        and aggregate.get("maximum_baseline_makespan_ticks") == max(baseline_makespans, default=-1)
        and aggregate.get("maximum_candidate_makespan_ticks") == max(candidate_makespans, default=-1)
        and aggregate.get("ordered_seed_evaluation_root_sha256")
        == canonical_json_sha256([row.get("seed_evaluation_sha256") for row in seed_rows])
    )

    decisions = _mapping(artifact.get("decisions"))
    decisions_valid = bool(
        decisions.get("fixed_architecture_historical_stress_screen")
        == (
            "FIXED_V46_ARCHITECTURE_REJECTED_BY_PREREGISTERED_HISTORICAL_PROPERTIES_STRESS_SCREEN"
            if all_architecture_fail
            else "FIXED_V46_ARCHITECTURE_NOT_UNIFORMLY_REJECTED_BY_HISTORICAL_PROPERTIES_STRESS_SCREEN"
        )
        and decisions.get("baseline_dated_properties")
        == ("REJECT_DATED_PROPERTIES_UNIT_ERROR_USAGE" if sum(baseline_units) else "MODELED_ONLY_NO_HARDWARE_ADMISSION")
        and decisions.get("candidate_research_routing")
        == ("V47_FAULT_EXCLUDED_RESEARCH_ROUTING_FEASIBLE_UNDER_HISTORICAL_PROPERTIES" if all_candidate_feasible else "V47_FAULT_EXCLUDED_RESEARCH_ROUTING_REJECTED")
        and decisions.get("pareto_safe_replacement")
        == ("PARETO_SAFE_REPLACEMENT_DEMONSTRATED_WITHIN_V47_MODEL" if all_pareto else "PARETO_SAFE_REPLACEMENT_NOT_DEMONSTRATED")
        and decisions.get("overall")
        == (
            "V47_HISTORICAL_PROPERTIES_STRESS_SCREEN_REJECTS_FIXED_V46_ARCHITECTURE_NO_CURRENT_HARDWARE_INFERENCE"
            if all_architecture_fail
            else "V47_DATED_PROPERTIES_AUDIT_COMPLETED_NO_HARDWARE_ADMISSION"
        )
        and decisions.get("production_admission") == "OFFLINE_HISTORICAL_PROPERTIES_ONLY_HARDWARE_EXECUTION_REJECTED"
        and decisions.get("next_falsifiable_gate") == "MULTI_SNAPSHOT_ROBUSTNESS_AND_ARCHITECTURE_LEVEL_CZ_REDUCTION_BEFORE_ANY_CURRENT_PROVIDER_DISCOVERY"
    )

    boundary = _mapping(artifact.get("claim_boundary"))
    parent_link = _mapping(artifact.get("parent"))
    snapshot = _mapping(artifact.get("properties_snapshot"))
    model_link = _mapping(artifact.get("model_contract"))
    candidate_link = _mapping(artifact.get("candidate_contract"))
    property_dates = _mapping(properties_payload.get("property_time_range"))
    model_boundary = _mapping(model.get("claim_boundary"))
    checks: dict[str, bool] = {
        "artifact_self_hash": _self_hash(artifact, "artifact_sha256"),
        "artifact_version": artifact.get("artifact_version") == ARTIFACT_VERSION,
        "spec_raw_identity": paths["spec"].is_file() and raw_file_sha256(paths["spec"]) == EXPECTED_SPEC_RAW_SHA256,
        "spec_semantic_identity": _spec_hash(spec),
        "spec_chronology_and_boundary": bool(
            _mapping(spec.get("chronology")).get("result_state_at_seal") == "NOT_EVALUATED"
            and _mapping(spec.get("chronology")).get("dated_properties_inspected_before_seal") is True
            and _mapping(spec.get("claim_boundary")).get("research_classification") == "RESEARCH_ONLY"
            and _mapping(spec.get("claim_boundary")).get("hardware_executable") is False
        ),
        "raw_properties_identity": bool(paths["raw_properties"].is_file() and paths["raw_properties"].stat().st_size == EXPECTED_RAW_PROPERTIES_SIZE and raw_file_sha256(paths["raw_properties"]) == EXPECTED_RAW_PROPERTIES_SHA256),
        "normalized_properties_raw_identity": paths["properties"].is_file() and raw_file_sha256(paths["properties"]) == EXPECTED_PROPERTIES_RAW_SHA256,
        "normalized_properties_semantic_identity": bool(properties_payload.get("properties_snapshot_sha256") == EXPECTED_PROPERTIES_SHA256 and _self_hash(properties_payload, "properties_snapshot_sha256")),
        **property_checks,
        "path_oracle_raw_identity": paths["path_oracle"].is_file() and raw_file_sha256(paths["path_oracle"]) == EXPECTED_PATH_ORACLE_RAW_SHA256,
        "path_oracle_semantic_identity": bool(path_oracle.get("path_oracle_sha256") == EXPECTED_PATH_ORACLE_SHA256 and _self_hash(path_oracle, "path_oracle_sha256")),
        **path_checks,
        "model_raw_identity": paths["model"].is_file() and raw_file_sha256(paths["model"]) == EXPECTED_MODEL_RAW_SHA256,
        "model_semantic_identity": bool(model.get("model_contract_sha256") == EXPECTED_MODEL_SHA256 and _self_hash(model, "model_contract_sha256")),
        "model_contract_boundary": bool(
            _mapping(model.get("duration_model")).get("dt_nanoseconds") == 4
            and _mapping(model.get("error_model")).get("decimal_precision") == 50
            and _mapping(model.get("optimization_model")).get("candidate_name") == CANDIDATE_NAME
            and model_boundary.get("research_classification") == "RESEARCH_ONLY"
            and model_boundary.get("hardware_executable") is False
        ),
        "parent_authentication": parent_ok,
        "parent_crosslinks": bool(
            parent_link.get("freeze_raw_file_sha256") == EXPECTED_V46_FREEZE_RAW_SHA256
            and parent_link.get("freeze_sha256") == EXPECTED_V46_FREEZE_SHA256
            and parent_link.get("artifact_raw_file_sha256") == EXPECTED_V46_ARTIFACT_RAW_SHA256
            and parent_link.get("artifact_sha256") == EXPECTED_V46_ARTIFACT_SHA256
            and parent_link.get("immutable_file_count") == EXPECTED_V46_IMMUTABLE_FILE_COUNT
            and parent_link.get("immutable_files_exact") is True
            and parent_link.get("ordered_route_ir_root_sha256") == EXPECTED_V46_ROUTE_ROOT_SHA256
        ),
        "source_crosslink": paths["source"].is_file() and artifact.get("source_raw_file_sha256") == raw_file_sha256(paths["source"]),
        "checker_crosslink": paths["checker"].is_file() and artifact.get("independent_checker_raw_file_sha256") == raw_file_sha256(paths["checker"]),
        "artifact_input_crosslinks": bool(
            artifact.get("spec_raw_file_sha256") == EXPECTED_SPEC_RAW_SHA256
            and artifact.get("spec_sha256") == EXPECTED_SPEC_SHA256
            and model_link.get("model_contract_raw_file_sha256") == EXPECTED_MODEL_RAW_SHA256
            and model_link.get("model_contract_sha256") == EXPECTED_MODEL_SHA256
            and candidate_link.get("candidate_name") == CANDIDATE_NAME
            and candidate_link.get("component_size") == 153
            and candidate_link.get("path_oracle_raw_file_sha256") == EXPECTED_PATH_ORACLE_RAW_SHA256
            and candidate_link.get("path_oracle_sha256") == EXPECTED_PATH_ORACLE_SHA256
        ),
        "properties_snapshot_crosslink": bool(
            snapshot.get("properties_raw_file_sha256") == EXPECTED_RAW_PROPERTIES_SHA256
            and snapshot.get("properties_snapshot_raw_file_sha256") == EXPECTED_PROPERTIES_RAW_SHA256
            and snapshot.get("properties_snapshot_sha256") == EXPECTED_PROPERTIES_SHA256
            and snapshot.get("global_last_update_date") == property_dates.get("global_last_update_date")
            and snapshot.get("maximum_embedded_property_date") == property_dates.get("maximum_embedded_property_date")
            and snapshot.get("snapshot_is_current_hardware_evidence") is False
        ),
        "seed_order": [row.get("seed") for row in seed_rows] == list(EXPECTED_SEEDS),
        "widths_exact": [row.get("logical_qubits") for row in seed_rows] == list(EXPECTED_WIDTHS),
        "seed_self_hashes_and_parent_rows": all_seed_hashes,
        "nested_self_hashes": all_nested_hashes,
        "manifests_exact_v46": all_manifest,
        "route_accounting": all_routes,
        "distance_swap_identity": all_distances,
        "native_count_algebra": all_native_algebra,
        "native_structural_boundary": all_native_boundary,
        "layout_bijections": all_layouts,
        "property_usage_recomputed": all_usage,
        "error_screens_recomputed": all_errors,
        "stage_usage_recomputed": all_stages,
        "timing_ledgers_recomputed": all_timing,
        "resource_gates_recomputed": all_resources,
        "baseline_commitments_exact_v46": all_baseline_exact,
        "architecture_lower_bounds_recomputed": all_lower_bounds,
        "comparisons_recomputed": all_comparisons,
        "aggregate_recomputed": aggregate_valid,
        "decisions_recomputed": decisions_valid,
        "research_classification": artifact.get("research_classification") == "RESEARCH_ONLY" and boundary.get("research_classification") == "RESEARCH_ONLY",
        "provider_network_job_zero": bool(
            boundary.get("provider_sdk_imported") is False
            and boundary.get("provider_credentials_read") is False
            and boundary.get("credential_reads") == 0
            and boundary.get("provider_calls") == 0
            and boundary.get("network_calls") == 0
            and boundary.get("backend_run_calls") == 0
            and boundary.get("local_simulator_jobs_submitted") == 0
            and boundary.get("qpu_jobs_submitted") == 0
        ),
        "hardware_and_claim_boundary": bool(
            boundary.get("hardware_executable") is False
            and boundary.get("snapshot_is_current_hardware_evidence") is False
            and boundary.get("calibration_aware_circuit_fidelity") == "NOT_CLAIMED"
            and boundary.get("quantum_advantage") == "NOT_CLAIMED"
            and boundary.get("properties_conditioned_asap_duration_estimate") == "EVALUATED_OFFLINE"
            and boundary.get("reported_gate_error_mass") == "EVALUATED_DESCRIPTIVE_NOT_FIDELITY"
        ),
    }
    if len(checks) != EXPECTED_CHECK_COUNT:
        raise AssertionError(f"V4.7 independent checker count drifted: {len(checks)} != {EXPECTED_CHECK_COUNT}")
    failed = [name for name, passed in checks.items() if passed is not True]
    return {
        "check_count": len(checks),
        "checks": checks,
        "errors": list(dict.fromkeys(errors)),
        "failed_checks": failed,
        "parent_file_authentication_requested": authenticate_parent,
        "valid": not failed and not errors,
        "verifier": "QUANTUM LAB V4.7 STANDARD-LIBRARY INDEPENDENT CHECKER · V1",
    }


def validate_v47_artifact(
    artifact: Mapping[str, Any],
    *,
    root: str | Path,
    authenticate_parent: bool = True,
    expected_artifact_sha256: str | None = None,
    artifact_raw_file_sha256: str | None = None,
    expected_artifact_raw_sha256: str | None = None,
) -> dict[str, Any]:
    """Run the independent audit without mutating process-global Decimal state."""

    with localcontext() as context:
        context.prec = 50
        return _validate_v47_artifact(
            artifact,
            root=root,
            authenticate_parent=authenticate_parent,
            expected_artifact_sha256=expected_artifact_sha256,
            artifact_raw_file_sha256=artifact_raw_file_sha256,
            expected_artifact_raw_sha256=expected_artifact_raw_sha256,
        )


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact")
    parser.add_argument("--root", default=None)
    parser.add_argument("--skip-parent-files", action="store_true")
    parser.add_argument("--expected-artifact-sha256", default=None)
    parser.add_argument("--expected-artifact-raw-sha256", default=None)
    args = parser.parse_args(argv)
    artifact_path = Path(args.artifact).resolve()
    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parents[1]
    report = validate_v47_artifact(
        read_json_strict(artifact_path),
        root=root,
        authenticate_parent=not args.skip_parent_files,
        expected_artifact_sha256=args.expected_artifact_sha256,
        artifact_raw_file_sha256=raw_file_sha256(artifact_path),
        expected_artifact_raw_sha256=args.expected_artifact_raw_sha256,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("valid") is True else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = ["EXPECTED_CHECK_COUNT", "validate_v47_artifact"]
