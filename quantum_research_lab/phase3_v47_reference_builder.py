"""Build the pinned Quantum Lab V4.7 FakeMarrakesh property oracles.

The builder consumes one exact, caller-supplied qiskit-ibm-runtime 0.49.0
wheel.  It never imports Qiskit, contacts a provider, reads credentials or
submits a simulator/QPU job.  Three deterministic files are emitted:

* the byte-exact bundled properties JSON;
* a normalized, self-hashed native-property oracle; and
* a self-hashed fault-excluded shortest-hop path oracle.

These are historical offline inputs.  They are not current calibration or
hardware evidence.
"""

from __future__ import annotations

import argparse
from collections import Counter, deque
from datetime import datetime, timezone
from decimal import Decimal, localcontext
import hashlib
import json
from pathlib import Path
import statistics
from typing import Any, Iterable, Mapping, Sequence
import zipfile


BUILDER_VERSION = "PHASE III · V4.7 PROPERTY REFERENCE BUILDER · V1"
SNAPSHOT_VERSION = "PHASE III · V4.7 NORMALIZED FAKEMARRAKESH DATED PROPERTIES · V1"
PATH_ORACLE_VERSION = "PHASE III · V4.7 FAULT-EXCLUDED RELIABILITY PATH ORACLE · V1"
WHEEL_NAME = "qiskit_ibm_runtime-0.49.0-py3-none-any.whl"
WHEEL_SHA256 = "b29b4a0a5e013b6e6fd6556158fd34a05e2930dea870c60edef738b834977f2b"
PROPERTIES_MEMBER = "qiskit_ibm_runtime/fake_provider/backends/marrakesh/props_marrakesh.json"
PROPERTIES_RAW_SHA256 = "d49d7ae07deb95947ea10e5b9b9c5cbab6df21f98610543817f35ade2b1aece6"
PROPERTIES_RAW_SIZE = 565_487
V44_SNAPSHOT_RAW_SHA256 = "816814f383c7b9890a137ead7799c28f3fbfc0cac188ab274dfb65050e2b7fbd"
V44_SNAPSHOT_SHA256 = "3a604026627653e697fba1b2b9b06d84298a13ca7a7f2c2f9f2ed551bdbfdaf3"
DT_NS = 4
NUM_QUBITS = 156
REQUIRED_GATES = ("cz", "id", "rz", "sx", "x")
ONE_QUBIT_GATES = ("id", "rz", "sx", "x")
RAW_OUTPUT = "PHASE_III_V4_7_FAKEMARRAKESH_PROPERTIES_2025_02_26_RAW.json"
NORMALIZED_OUTPUT = "PHASE_III_V4_7_NORMALIZED_PROPERTIES_ORACLE_V1.json"
PATH_OUTPUT = "PHASE_III_V4_7_FAULT_EXCLUDED_PATH_ORACLE_V1.json"


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


def read_json_bytes_strict(raw: bytes) -> dict[str, Any]:
    payload = json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=_reject_duplicates,
        parse_float=Decimal,
        parse_constant=lambda token: (_ for _ in ()).throw(
            ValueError(f"Non-finite JSON number rejected: {token}")
        ),
    )
    if not isinstance(payload, dict):
        raise ValueError("Expected a JSON object.")
    return payload


def _parameter_map(rows: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(rows, list):
        raise ValueError("Property parameter rows must be a list.")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("Property parameter row must be an object.")
        name = str(row.get("name", ""))
        if not name or name in result:
            raise ValueError(f"Missing or duplicate property parameter: {name!r}")
        value = row.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
            raise ValueError(f"Non-numeric property value: {name}")
        result[name] = {
            "date": str(row.get("date", "")),
            "unit": str(row.get("unit", "")),
            "value": value,
        }
    return result


def _seconds(value: int | float, unit: str) -> float:
    factors = {"s": 1.0, "ms": 1e-3, "us": 1e-6, "ns": 1e-9}
    if unit not in factors:
        raise ValueError(f"Unsupported time unit: {unit!r}")
    return float(value) * factors[unit]


def _duration_ticks(value: int | float, unit: str) -> int:
    duration_ns = _seconds(value, unit) * 1e9
    ticks = round(duration_ns / DT_NS)
    if abs(duration_ns - ticks * DT_NS) > 1e-9:
        raise ValueError(f"Gate duration {value} {unit} is not an integer multiple of {DT_NS} ns.")
    return int(ticks)


def _iso_utc(value: str) -> str:
    return datetime.fromisoformat(value).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _stats(values: Iterable[float]) -> dict[str, float]:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        raise ValueError("Cannot summarize an empty property vector.")
    return {
        "maximum": ordered[-1],
        "median": statistics.median(ordered),
        "minimum": ordered[0],
    }


def _components(adjacency: Mapping[int, set[int]]) -> list[list[int]]:
    unseen = set(adjacency)
    groups: list[list[int]] = []
    while unseen:
        start = min(unseen)
        queue: deque[int] = deque([start])
        unseen.remove(start)
        group: list[int] = []
        while queue:
            node = queue.popleft()
            group.append(node)
            for neighbour in sorted(adjacency[node]):
                if neighbour in unseen:
                    unseen.remove(neighbour)
                    queue.append(neighbour)
        groups.append(sorted(group))
    return sorted(groups, key=lambda row: (-len(row), tuple(row)))


def _shortest_distances(adjacency: Mapping[int, set[int]], destination: int) -> dict[int, int]:
    distances = {destination: 0}
    queue: deque[int] = deque([destination])
    while queue:
        node = queue.popleft()
        for neighbour in sorted(adjacency[node]):
            if neighbour not in distances:
                distances[neighbour] = distances[node] + 1
                queue.append(neighbour)
    return distances


def _native_error_cost(
    gate_lookup: Mapping[tuple[str, tuple[int, ...]], Mapping[str, Any]],
    gate: str,
    qubits: tuple[int, ...],
    multiplier: int = 1,
) -> Decimal:
    return Decimal(multiplier) * Decimal(str(gate_lookup[(gate, qubits)]["gate_error"]))


def _native_ticks(
    gate_lookup: Mapping[tuple[str, tuple[int, ...]], Mapping[str, Any]],
    gate: str,
    qubits: tuple[int, ...],
    multiplier: int = 1,
) -> int:
    return multiplier * int(gate_lookup[(gate, qubits)]["duration_ticks"])


def _swap_cost(
    left: int,
    right: int,
    gate_lookup: Mapping[tuple[str, tuple[int, ...]], Mapping[str, Any]],
) -> tuple[Decimal, int]:
    return (
        _native_error_cost(gate_lookup, "cz", (left, right), 3)
        + _native_error_cost(gate_lookup, "sx", (left,), 3)
        + _native_error_cost(gate_lookup, "sx", (right,), 3),
        _native_ticks(gate_lookup, "cz", (left, right), 3)
        + max(
            _native_ticks(gate_lookup, "sx", (left,), 3),
            _native_ticks(gate_lookup, "sx", (right,), 3),
        ),
    )


def _cx_cost(
    control: int,
    target: int,
    gate_lookup: Mapping[tuple[str, tuple[int, ...]], Mapping[str, Any]],
) -> tuple[Decimal, int]:
    return (
        _native_error_cost(gate_lookup, "cz", (control, target))
        + _native_error_cost(gate_lookup, "sx", (target,), 2),
        _native_ticks(gate_lookup, "cz", (control, target))
        + _native_ticks(gate_lookup, "sx", (target,), 2),
    )


def _best_shortest_paths(
    destination: int,
    adjacency: Mapping[int, set[int]],
    distances: Mapping[int, int],
    gate_lookup: Mapping[tuple[str, tuple[int, ...]], Mapping[str, Any]],
) -> dict[int, tuple[int, ...]]:
    memo: dict[int, tuple[int, ...]] = {destination: (destination,)}
    costs: dict[int, tuple[Decimal, int]] = {destination: (Decimal(0), 0)}
    by_distance = sorted(distances, key=lambda node: (distances[node], node))
    for node in by_distance:
        if node == destination:
            continue
        candidates: list[tuple[Decimal, int, tuple[int, ...]]] = []
        for neighbour in sorted(adjacency[node]):
            if distances.get(neighbour) == distances[node] - 1 and neighbour in memo:
                path = (node,) + memo[neighbour]
                local = (
                    _cx_cost(node, neighbour, gate_lookup)
                    if neighbour == destination
                    else _swap_cost(node, neighbour, gate_lookup)
                )
                tail = costs[neighbour]
                candidates.append((local[0] + tail[0], local[1] + tail[1], path))
        if not candidates:
            raise ValueError(f"No shortest-path successor for {node}->{destination}.")
        error_mass, duration_ticks, path = min(candidates)
        memo[node] = path
        costs[node] = (error_mass, duration_ticks)
    return memo


def build_references(*, wheel: str | Path, root: str | Path, created_utc: str) -> dict[str, Any]:
    wheel_path = Path(wheel).resolve(strict=True)
    root_path = Path(root).resolve(strict=True)
    module_root = root_path / "quantum_research_lab"
    if wheel_path.name != WHEEL_NAME or raw_file_sha256(wheel_path) != WHEEL_SHA256:
        raise ValueError("Exact qiskit-ibm-runtime 0.49.0 wheel identity required.")
    v44_path = module_root / "PHASE_III_V4_4_FROZEN_BACKEND_SNAPSHOT_V1.json"
    if raw_file_sha256(v44_path) != V44_SNAPSHOT_RAW_SHA256:
        raise ValueError("V4.4 structural snapshot raw identity mismatch.")
    v44 = read_json_bytes_strict(v44_path.read_bytes())
    if not (
        v44.get("snapshot_sha256") == V44_SNAPSHOT_SHA256
        and (v44.get("properties_provenance") or {}).get("raw_properties_file_sha256")
        == PROPERTIES_RAW_SHA256
        and (v44.get("source_provenance") or {}).get("qiskit_ibm_runtime_wheel_sha256")
        == WHEEL_SHA256
    ):
        raise ValueError("V4.4 property provenance mismatch.")

    with zipfile.ZipFile(wheel_path) as archive:
        raw = archive.read(PROPERTIES_MEMBER)
    if len(raw) != PROPERTIES_RAW_SIZE or hashlib.sha256(raw).hexdigest() != PROPERTIES_RAW_SHA256:
        raise ValueError("Bundled FakeMarrakesh properties raw identity mismatch.")
    source = read_json_bytes_strict(raw)
    if not (
        source.get("backend_name") == "ibm_marrakesh"
        and source.get("backend_version") == "1.0.7"
        and source.get("last_update_date") == "2025-02-26T14:52:45-05:00"
        and len(source.get("qubits") or []) == NUM_QUBITS
        and len(source.get("gates") or []) == 1640
    ):
        raise ValueError("Unexpected FakeMarrakesh properties schema or identity.")

    qubit_rows: list[dict[str, Any]] = []
    all_dates: list[str] = []
    for index, parameters in enumerate(source["qubits"]):
        props = _parameter_map(parameters)
        if set(props) != {
            "T1", "T2", "prob_meas0_prep1", "prob_meas1_prep0", "readout_error", "readout_length"
        }:
            raise ValueError(f"Unexpected qubit property schema at {index}.")
        all_dates.extend(str(row["date"]) for row in props.values())
        qubit_rows.append(
            {
                "prob_meas0_prep1": float(props["prob_meas0_prep1"]["value"]),
                "prob_meas1_prep0": float(props["prob_meas1_prep0"]["value"]),
                "property_dates": {name: row["date"] for name, row in sorted(props.items())},
                "qubit": index,
                "readout_error": float(props["readout_error"]["value"]),
                "readout_length_seconds": _seconds(
                    props["readout_length"]["value"], props["readout_length"]["unit"]
                ),
                "t1_seconds": _seconds(props["T1"]["value"], props["T1"]["unit"]),
                "t2_seconds": _seconds(props["T2"]["value"], props["T2"]["unit"]),
            }
        )

    native_rows: list[dict[str, Any]] = []
    seen: set[tuple[str, tuple[int, ...]]] = set()
    raw_gate_counts: Counter[str] = Counter()
    for gate in source["gates"]:
        name = str(gate.get("gate", ""))
        raw_gate_counts[name] += 1
        if name not in REQUIRED_GATES:
            continue
        qubits = tuple(int(value) for value in gate.get("qubits") or [])
        expected_arity = 2 if name == "cz" else 1
        if len(qubits) != expected_arity or any(value < 0 or value >= NUM_QUBITS for value in qubits):
            raise ValueError(f"Invalid {name} qargs: {qubits}")
        key = (name, qubits)
        if key in seen:
            raise ValueError(f"Duplicate native property tuple: {key}")
        seen.add(key)
        props = _parameter_map(gate.get("parameters"))
        if set(props) != {"gate_error", "gate_length"}:
            raise ValueError(f"Incomplete native properties for {key}.")
        if props["gate_error"]["unit"] != "" or props["gate_length"]["unit"] != "ns":
            raise ValueError(f"Unexpected native property units for {key}.")
        error = Decimal(str(props["gate_error"]["value"]))
        if not Decimal(0) <= error <= Decimal(1):
            raise ValueError(f"Out-of-range gate error for {key}.")
        all_dates.extend((str(props["gate_error"]["date"]), str(props["gate_length"]["date"])))
        native_rows.append(
            {
                "duration_seconds": _seconds(props["gate_length"]["value"], "ns"),
                "duration_ticks": _duration_ticks(props["gate_length"]["value"], "ns"),
                "gate": name,
                "gate_error": format(error, "f"),
                "gate_error_date": props["gate_error"]["date"],
                "gate_length_date": props["gate_length"]["date"],
                "qubits": list(qubits),
            }
        )
    native_rows.sort(key=lambda row: (row["gate"], row["qubits"]))
    expected_counts = {"cz": 352, "id": 156, "rz": 156, "sx": 156, "x": 156}
    observed_counts = Counter(str(row["gate"]) for row in native_rows)
    if dict(observed_counts) != expected_counts or len(native_rows) != 976:
        raise ValueError(f"Native property coverage mismatch: {observed_counts}")

    gate_lookup = {
        (str(row["gate"]), tuple(int(value) for value in row["qubits"])): row
        for row in native_rows
    }
    for gate in ONE_QUBIT_GATES:
        for qubit in range(NUM_QUBITS):
            if (gate, (qubit,)) not in gate_lookup:
                raise ValueError(f"Missing {gate} property on q{qubit}.")

    healthy_adjacency: dict[int, set[int]] = {qubit: set() for qubit in range(NUM_QUBITS)}
    excluded_directed: list[list[int]] = []
    for row in native_rows:
        if row["gate"] != "cz":
            continue
        left, right = (int(value) for value in row["qubits"])
        if Decimal(str(row["gate_error"])) >= 1:
            excluded_directed.append([left, right])
        else:
            healthy_adjacency[left].add(right)
    # The candidate treats connectivity as undirected only where both native
    # CZ orientations have valid sub-unit-error properties.
    for left in range(NUM_QUBITS):
        for right in list(healthy_adjacency[left]):
            if left not in healthy_adjacency[right]:
                healthy_adjacency[left].remove(right)
    components = _components(healthy_adjacency)
    largest = components[0]
    if [len(row) for row in components] != [153, 1, 1, 1] or [row[0] for row in components[1:]] != [24, 102, 113]:
        raise ValueError("Fault-excluded component structure drifted.")

    stats_by_gate: dict[str, dict[str, Any]] = {}
    for name in REQUIRED_GATES:
        rows = [row for row in native_rows if row["gate"] == name]
        stats_by_gate[name] = {
            "count": len(rows),
            "duration_seconds": _stats(float(row["duration_seconds"]) for row in rows),
            "duration_ticks": _stats(float(row["duration_ticks"]) for row in rows),
            "gate_error": _stats(float(Decimal(str(row["gate_error"]))) for row in rows),
            "unit_error_tuple_count": sum(Decimal(str(row["gate_error"])) >= 1 for row in rows),
        }
    normalized_core: dict[str, Any] = {
        "backend": {
            "backend_name": "fake_marrakesh",
            "source_backend_name": source["backend_name"],
            "source_backend_version": source["backend_version"],
            "basis_gates": list(REQUIRED_GATES),
            "dt_nanoseconds": DT_NS,
            "dt_seconds": DT_NS * 1e-9,
            "num_qubits": NUM_QUBITS,
        },
        "claim_boundary": {
            "hardware_executable": False,
            "provider_calls": 0,
            "network_calls": 0,
            "qpu_jobs_submitted": 0,
            "research_classification": "RESEARCH_ONLY",
            "snapshot_is_current_hardware_evidence": False,
        },
        "coverage": {
            "all_required_gate_tuples_complete": True,
            "expected_gate_counts": expected_counts,
            "native_gate_tuple_count": len(native_rows),
            "required_property_value_count": 2 * len(native_rows),
            "source_gate_counts": dict(sorted(raw_gate_counts.items())),
        },
        "created_utc": created_utc,
        "fault_screen": {
            "excluded_directed_cz_edges": sorted(excluded_directed),
            "excluded_directed_cz_edge_count": len(excluded_directed),
            "excluded_undirected_cz_edge_count": len({tuple(sorted(row)) for row in excluded_directed}),
            "fault_excluded_component_sizes": [len(row) for row in components],
            "isolated_qubits": [row[0] for row in components[1:]],
            "largest_component_qubits": largest,
            "largest_component_size": len(largest),
            "maximum_v46_logical_width": 145,
            "width_margin": len(largest) - 145,
        },
        "native_properties": native_rows,
        "property_time_range": {
            "global_last_update_date": source["last_update_date"],
            "global_last_update_utc": _iso_utc(str(source["last_update_date"])),
            "maximum_embedded_property_date": max(all_dates, key=lambda value: datetime.fromisoformat(value)),
            "minimum_embedded_property_date": min(all_dates, key=lambda value: datetime.fromisoformat(value)),
            "global_date_is_not_asserted_as_strict_cutoff": True,
        },
        "qubit_properties": qubit_rows,
        "snapshot_version": SNAPSHOT_VERSION,
        "source_provenance": {
            "archive_member": PROPERTIES_MEMBER,
            "bundled_fake_backend_not_live_provider_export": True,
            "qiskit_ibm_runtime_version": "0.49.0",
            "raw_properties_file_sha256": PROPERTIES_RAW_SHA256,
            "raw_properties_file_size": PROPERTIES_RAW_SIZE,
            "v44_snapshot_raw_file_sha256": V44_SNAPSHOT_RAW_SHA256,
            "v44_snapshot_sha256": V44_SNAPSHOT_SHA256,
            "wheel_filename": WHEEL_NAME,
            "wheel_sha256": WHEEL_SHA256,
        },
        "statistics": {
            "gate_properties": stats_by_gate,
            "qubits": {
                "readout_error": _stats(float(row["readout_error"]) for row in qubit_rows),
                "t1_seconds": _stats(float(row["t1_seconds"]) for row in qubit_rows),
                "t2_seconds": _stats(float(row["t2_seconds"]) for row in qubit_rows),
            },
        },
    }
    normalized = {
        **normalized_core,
        "properties_snapshot_sha256": canonical_json_sha256(normalized_core),
    }

    ordered_lines: list[str] = []
    maximum_hops = 0
    path_count = 0
    with localcontext() as decimal_context:
        decimal_context.prec = 50
        for destination in largest:
            distances = _shortest_distances(healthy_adjacency, destination)
            if set(distances) != set(largest):
                raise ValueError("Largest fault-excluded component is not connected.")
            best_paths = _best_shortest_paths(
                destination,
                healthy_adjacency,
                distances,
                gate_lookup,
            )
            for source_qubit in largest:
                if source_qubit == destination:
                    continue
                path = best_paths[source_qubit]
                maximum_hops = max(maximum_hops, len(path) - 1)
                path_count += 1
                ordered_lines.append(
                    f"{source_qubit}|{destination}|{','.join(str(value) for value in path)}\n"
                )
    ordered_stream = "".join(ordered_lines)
    path_core: dict[str, Any] = {
        "candidate_name": "FAULT_EXCLUDED_SHORTEST_HOP_RELIABILITY_TIEBREAK_V1",
        "component_qubits": largest,
        "component_size": len(largest),
        "cost_contract": {
            "cx_error_mass": "p_cz(control,target)+2*p_sx(target)",
            "cx_nominal_ticks": "d_cz(control,target)+2*d_sx(target)",
            "objective_order": ["minimum_hops", "reported_gate_error_mass", "nominal_duration_ticks", "full_path_tuple"],
            "scope": "STATIC_PER_ORDERED_PAIR_NO_LOOKAHEAD_NO_GLOBAL_OPTIMALITY_CLAIM",
            "swap_error_mass": "3*p_cz(left,right)+3*p_sx(left)+3*p_sx(right)",
            "swap_nominal_ticks": "3*d_cz(left,right)+3*max(d_sx(left),d_sx(right))",
        },
        "created_utc": created_utc,
        "excluded_edge_rule": "REJECT_MISSING_INVALID_OR_GATE_ERROR_GREATER_THAN_OR_EQUAL_TO_ONE_IN_EITHER_DIRECTION",
        "initial_layout_rule": "LOGICAL_ORDER_TO_ASCENDING_COMPONENT_QUBITS_PREFIX",
        "maximum_hops": maximum_hops,
        "ordered_path_count": path_count,
        "ordered_paths_compact": ordered_stream.rstrip("\n"),
        "ordered_paths_stream_sha256": hashlib.sha256(ordered_stream.encode("ascii")).hexdigest(),
        "path_oracle_version": PATH_ORACLE_VERSION,
        "properties_snapshot_sha256": normalized["properties_snapshot_sha256"],
        "research_classification": "RESEARCH_ONLY",
    }
    path_oracle = {**path_core, "path_oracle_sha256": canonical_json_sha256(path_core)}

    module_root.mkdir(parents=True, exist_ok=True)
    raw_path = module_root / RAW_OUTPUT
    normalized_path = module_root / NORMALIZED_OUTPUT
    path_oracle_path = module_root / PATH_OUTPUT
    raw_path.write_bytes(raw)
    normalized_path.write_text(
        json.dumps(normalized, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    path_oracle_path.write_text(
        json.dumps(path_oracle, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return {
        "builder_version": BUILDER_VERSION,
        "normalized": str(normalized_path),
        "normalized_raw_file_sha256": raw_file_sha256(normalized_path),
        "normalized_semantic_sha256": normalized["properties_snapshot_sha256"],
        "path_oracle": str(path_oracle_path),
        "path_oracle_raw_file_sha256": raw_file_sha256(path_oracle_path),
        "path_oracle_semantic_sha256": path_oracle["path_oracle_sha256"],
        "raw": str(raw_path),
        "raw_file_sha256": raw_file_sha256(raw_path),
        "raw_file_size": raw_path.stat().st_size,
    }


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", required=True)
    parser.add_argument("--root", required=True)
    parser.add_argument("--created-utc", required=True)
    args = parser.parse_args(argv)
    print(
        json.dumps(
            build_references(wheel=args.wheel, root=args.root, created_utc=args.created_utc),
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "NORMALIZED_OUTPUT",
    "PATH_OUTPUT",
    "PROPERTIES_RAW_SHA256",
    "RAW_OUTPUT",
    "WHEEL_SHA256",
    "build_references",
    "canonical_json_sha256",
    "raw_file_sha256",
]
