"""Quantum Lab V4.7 historical-property replay and routing experiment.

The experiment replays every authenticated V4.6 input instruction twice:

* the exact V4.6 BasicSwap baseline, whose route/native/layout commitments must
  reproduce byte-for-byte; and
* one preregistered fault-excluded, shortest-hop reliability-tiebreak routing
  candidate with a deterministic non-trivial initial layout.

Both streams are evaluated with an integer-dt per-qubit ASAP model and exact
physical gate-property occurrence ledgers.  Reported gate-error mass is a
descriptive sum, not circuit fidelity, success probability or expected failure
count.  The entire module is offline and imports no provider SDK or Qiskit.
"""

from __future__ import annotations

import argparse
import copy
from collections import Counter
from decimal import Decimal, localcontext
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import socket
import sys
from typing import Any, Mapping, Sequence
from unittest import mock

from .phase3_v41_certified_bridge_compiler import _certificate_by_seed, _guarded_rows
from .phase3_v42_coined_walk_compiler import SEEDS
from .phase3_v43_reversible_circuit_ir import CircuitStream
from .phase3_v44_named_backend_routing import parse_coupling_edges
from .phase3_v45_proof_carrying_width_reduction import (
    SUCCESSOR_MUTABLE,
    build_layout,
    emit_binary_coin_rings,
    emit_binary_selector,
    emit_bridge,
)
from .phase3_v46_full_stream_routing import (
    FullStreamRouter,
    TARGET_QUBITS,
    canonical_json_sha256,
    load_path_oracle,
    raw_file_sha256,
    read_json_strict,
)


V47_VERSION = "PHASE III · V4.7 DATED PROPERTIES / FAULT-EXCLUDED ROUTING · V1"
ARTIFACT_VERSION = "PHASE III · V4.7 SEALED DATED PROPERTIES OPTIMIZATION ARTIFACT · V1"
SPEC_FILENAME = "PHASE_III_V4_7_PINNED_DATED_PROPERTIES_OPTIMIZATION_SPEC_V1.json"
PROPERTIES_FILENAME = "PHASE_III_V4_7_NORMALIZED_PROPERTIES_ORACLE_V1.json"
RAW_PROPERTIES_FILENAME = "PHASE_III_V4_7_FAKEMARRAKESH_PROPERTIES_2025_02_26_RAW.json"
PATH_ORACLE_FILENAME = "PHASE_III_V4_7_FAULT_EXCLUDED_PATH_ORACLE_V1.json"
MODEL_FILENAME = "PHASE_III_V4_7_DURATION_ERROR_MODEL_CONTRACT_V1.json"
DEFAULT_ARTIFACT_NAME = "SEALED_V4_7_DATED_PROPERTIES_OPTIMIZATION_ARTIFACT.json"
CANDIDATE_NAME = "FAULT_EXCLUDED_SHORTEST_HOP_RELIABILITY_TIEBREAK_V1"
INPUT_NATIVE_COUNTS: dict[str, tuple[tuple[str, int], ...]] = {
    "X": (("x", 1),),
    "H": (("rz", 2), ("sx", 1)),
    "T": (("rz", 1),),
    "TDG": (("rz", 1),),
    "RY": (("rz", 3), ("sx", 2)),
    "RZ": (("rz", 1),),
}

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
EXPECTED_V44_SNAPSHOT_RAW_SHA256 = "816814f383c7b9890a137ead7799c28f3fbfc0cac188ab274dfb65050e2b7fbd"


def _root(root: str | Path | None = None) -> Path:
    return Path(root).resolve() if root is not None else Path(__file__).resolve().parents[1]


def _paths(root: str | Path | None = None) -> dict[str, Path]:
    base = _root(root)
    module = base / "quantum_research_lab"
    return {
        "root": base,
        "spec": module / SPEC_FILENAME,
        "properties": module / PROPERTIES_FILENAME,
        "raw_properties": module / RAW_PROPERTIES_FILENAME,
        "candidate_paths": module / PATH_ORACLE_FILENAME,
        "model": module / MODEL_FILENAME,
        "source": module / "phase3_v47_dated_properties_optimizer.py",
        "checker": module / "phase3_v47_independent_checker.py",
        "v46_freeze": base / "FREEZE_CONTRACT_V4_6.json",
        "v46_artifact": base / "outputs/quantum_phase3/v46_full_stream_routing/SEALED_V4_6_FULL_STREAM_FAKEMARRAKESH_ROUTING_ARTIFACT.json",
        "v44_snapshot": module / "PHASE_III_V4_4_FROZEN_BACKEND_SNAPSHOT_V1.json",
        "v41_artifact": base / "outputs/quantum_phase3/v41_certified_bridge/SEALED_V4_1_CERTIFIED_BRIDGE_COMPILER_ARTIFACT.json",
        "artifact": base / "outputs/quantum_phase3/v47_dated_properties" / DEFAULT_ARTIFACT_NAME,
    }


def _path_fingerprint(paths: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(sorted(paths), separators=(",", ":")).encode("utf-8")).hexdigest()


def _self_hashed(path: Path, field: str, expected_raw: str, expected_semantic: str) -> dict[str, Any]:
    if raw_file_sha256(path) != expected_raw:
        raise ValueError(f"Raw identity mismatch: {path.name}")
    payload = read_json_strict(path)
    semantic = canonical_json_sha256({key: value for key, value in payload.items() if key != field})
    if payload.get(field) != semantic or semantic != expected_semantic:
        raise ValueError(f"Semantic identity mismatch: {path.name}")
    return payload


def load_v47_spec(*, root: str | Path | None = None) -> dict[str, Any]:
    path = _paths(root)["spec"]
    if raw_file_sha256(path) != EXPECTED_SPEC_RAW_SHA256:
        raise ValueError("V4.7 preregistration raw identity mismatch.")
    payload = read_json_strict(path)
    core = {key: value for key, value in payload.items() if key not in {"v47_spec_sha", "v47_spec_sha256"}}
    semantic = canonical_json_sha256(core)
    boundary = payload.get("claim_boundary") or {}
    chronology = payload.get("chronology") or {}
    if not (
        semantic == payload.get("v47_spec_sha256") == EXPECTED_SPEC_SHA256
        and payload.get("v47_spec_sha") == semantic[:20].upper()
        and chronology.get("result_state_at_seal") == "NOT_EVALUATED"
        and chronology.get("dated_properties_inspected_before_seal") is True
        and boundary.get("research_classification") == "RESEARCH_ONLY"
        and boundary.get("hardware_executable") is False
        and boundary.get("provider_calls") == 0
        and boundary.get("network_calls") == 0
        and boundary.get("qpu_jobs_submitted") == 0
    ):
        raise ValueError("V4.7 preregistration semantics or boundary mismatch.")
    return payload


def load_property_oracle(*, root: str | Path | None = None) -> dict[str, Any]:
    paths = _paths(root)
    if not (
        paths["raw_properties"].stat().st_size == EXPECTED_RAW_PROPERTIES_SIZE
        and raw_file_sha256(paths["raw_properties"]) == EXPECTED_RAW_PROPERTIES_SHA256
    ):
        raise ValueError("V4.7 raw property evidence identity mismatch.")
    payload = _self_hashed(
        paths["properties"],
        "properties_snapshot_sha256",
        EXPECTED_PROPERTIES_RAW_SHA256,
        EXPECTED_PROPERTIES_SHA256,
    )
    coverage = payload.get("coverage") or {}
    fault = payload.get("fault_screen") or {}
    if not (
        coverage.get("all_required_gate_tuples_complete") is True
        and coverage.get("native_gate_tuple_count") == 976
        and coverage.get("required_property_value_count") == 1952
        and fault.get("excluded_directed_cz_edge_count") == 26
        and fault.get("fault_excluded_component_sizes") == [153, 1, 1, 1]
        and fault.get("isolated_qubits") == [24, 102, 113]
        and (payload.get("claim_boundary") or {}).get("snapshot_is_current_hardware_evidence") is False
    ):
        raise ValueError("V4.7 normalized property coverage or fault screen mismatch.")
    return payload


def load_model_contract(*, root: str | Path | None = None) -> dict[str, Any]:
    payload = _self_hashed(
        _paths(root)["model"],
        "model_contract_sha256",
        EXPECTED_MODEL_RAW_SHA256,
        EXPECTED_MODEL_SHA256,
    )
    if not (
        (payload.get("duration_model") or {}).get("dt_nanoseconds") == 4
        and (payload.get("error_model") or {}).get("decimal_precision") == 50
        and (payload.get("optimization_model") or {}).get("candidate_name") == CANDIDATE_NAME
    ):
        raise ValueError("V4.7 duration/error model contract mismatch.")
    return payload


def authenticate_v46_parent(*, root: str | Path | None = None) -> dict[str, Any]:
    paths = _paths(root)
    errors: list[str] = []
    try:
        freeze = read_json_strict(paths["v46_freeze"])
        frozen = freeze.get("frozen_files") or {}
        semantic = canonical_json_sha256({key: value for key, value in freeze.items() if key != "freeze_contract_sha256"})
        valid_freeze = bool(
            raw_file_sha256(paths["v46_freeze"]) == EXPECTED_V46_FREEZE_RAW_SHA256
            and semantic == freeze.get("freeze_contract_sha256") == EXPECTED_V46_FREEZE_SHA256
            and isinstance(frozen, dict)
            and len(frozen) == freeze.get("frozen_file_count") == EXPECTED_V46_FROZEN_FILE_COUNT
            and _path_fingerprint(frozen) == freeze.get("frozen_paths_fingerprint_sha256") == EXPECTED_V46_PATH_FINGERPRINT
        )
    except Exception as exc:
        freeze, frozen, valid_freeze = {}, {}, False
        errors.append(f"V4.6 freeze authentication failed: {exc}")
    if not valid_freeze:
        errors.append("V4.6 freeze raw, semantic or inventory identity mismatch.")
    immutable = {
        str(relative): str(expected)
        for relative, expected in frozen.items()
        if str(relative) not in SUCCESSOR_MUTABLE
    } if isinstance(frozen, Mapping) else {}
    mismatches: list[str] = []
    for relative, expected in sorted(immutable.items()):
        path = paths["root"] / relative
        if not path.is_file() or path.is_symlink() or raw_file_sha256(path) != expected:
            mismatches.append(relative)
    if len(immutable) != EXPECTED_V46_IMMUTABLE_FILE_COUNT or mismatches:
        errors.append(f"V4.6 immutable path mismatch: count={len(immutable)} mismatches={mismatches[:5]}")
    try:
        artifact = read_json_strict(paths["v46_artifact"])
        artifact_semantic = canonical_json_sha256({key: value for key, value in artifact.items() if key != "artifact_sha256"})
        aggregate = artifact.get("aggregate") or {}
        artifact_valid = bool(
            raw_file_sha256(paths["v46_artifact"]) == EXPECTED_V46_ARTIFACT_RAW_SHA256
            and artifact_semantic == artifact.get("artifact_sha256") == EXPECTED_V46_ARTIFACT_SHA256
            and aggregate.get("ordered_route_ir_root_sha256") == EXPECTED_V46_ROUTE_ROOT_SHA256
            and aggregate.get("ordered_seed_routing_root_sha256") == EXPECTED_V46_SEED_ROOT_SHA256
            and (artifact.get("decisions") or {}).get("next_falsifiable_gate")
            == "PINNED_DATED_PROPERTIES_DURATION_ERROR_AND_OPTIMIZATION_FEASIBILITY_OF_V46_ROUTED_STREAMS"
        )
    except Exception as exc:
        artifact, artifact_valid = {}, False
        errors.append(f"V4.6 artifact authentication failed: {exc}")
    if not artifact_valid:
        errors.append("V4.6 artifact raw, semantic, route-root or decision mismatch.")
    return {
        "artifact": artifact,
        "errors": list(dict.fromkeys(errors)),
        "freeze": freeze,
        "immutable_file_count": len(immutable),
        "immutable_files_exact": len(immutable) == EXPECTED_V46_IMMUTABLE_FILE_COUNT and not mismatches,
        "valid": not errors,
    }


def load_candidate_path_oracle(
    *, root: str | Path | None = None
) -> tuple[dict[str, Any], list[list[tuple[int, ...] | None]], list[int]]:
    payload = _self_hashed(
        _paths(root)["candidate_paths"],
        "path_oracle_sha256",
        EXPECTED_PATH_ORACLE_RAW_SHA256,
        EXPECTED_PATH_ORACLE_SHA256,
    )
    component = [int(value) for value in payload.get("component_qubits") or []]
    if not (
        payload.get("candidate_name") == CANDIDATE_NAME
        and len(component) == payload.get("component_size") == 153
        and payload.get("ordered_path_count") == 153 * 152
        and payload.get("properties_snapshot_sha256") == EXPECTED_PROPERTIES_SHA256
    ):
        raise ValueError("V4.7 candidate path-oracle contract mismatch.")
    component_set = set(component)
    table: list[list[tuple[int, ...] | None]] = [
        [None for _ in range(TARGET_QUBITS)] for _ in range(TARGET_QUBITS)
    ]
    lines: list[str] = []
    for line in str(payload.get("ordered_paths_compact", "")).splitlines():
        source_text, destination_text, route_text = line.split("|", 2)
        source, destination = int(source_text), int(destination_text)
        route = tuple(int(value) for value in route_text.split(","))
        if not (
            source != destination
            and source in component_set
            and destination in component_set
            and route[0] == source
            and route[-1] == destination
            and set(route) <= component_set
            and len(set(route)) == len(route)
            and table[source][destination] is None
        ):
            raise ValueError(f"Invalid V4.7 path row: {line[:120]}")
        table[source][destination] = route
        lines.append(line + "\n")
    if not (
        len(lines) == 153 * 152
        and hashlib.sha256("".join(lines).encode("ascii")).hexdigest()
        == payload.get("ordered_paths_stream_sha256")
        and all(table[left][right] is not None for left in component for right in component if left != right)
    ):
        raise ValueError("V4.7 candidate path-oracle completeness mismatch.")
    return payload, table, component


class PropertyOracle:
    """Strict native property lookup with no missing/reverse-edge fallback."""

    def __init__(self, payload: Mapping[str, Any]) -> None:
        self.dt_ns = int((payload.get("backend") or {}).get("dt_nanoseconds", 0))
        self.gates: dict[tuple[str, tuple[int, ...]], dict[str, Any]] = {}
        for row in payload.get("native_properties") or []:
            gate = str(row.get("gate", ""))
            qubits = tuple(int(value) for value in row.get("qubits") or [])
            key = (gate, qubits)
            if key in self.gates:
                raise ValueError(f"Duplicate property tuple: {key}")
            error = row.get("gate_error")
            duration = row.get("duration_ticks")
            try:
                error_decimal = Decimal(str(error))
            except Exception as exc:
                raise ValueError(f"Invalid decimal gate error for {key}.") from exc
            if (
                isinstance(error, bool)
                or not isinstance(error, (int, float, str))
                or not error_decimal.is_finite()
                or not Decimal(0) <= error_decimal <= Decimal(1)
                or (isinstance(error, str) and format(error_decimal, "f") != error)
                or isinstance(duration, bool)
                or not isinstance(duration, int)
                or duration < 0
            ):
                raise ValueError(f"Invalid native property tuple: {key}")
            normalized_row = dict(row)
            normalized_row["_error_decimal"] = error_decimal
            normalized_row["_unit_error"] = error_decimal >= 1
            self.gates[key] = normalized_row
        self.qubits = {
            int(row["qubit"]): dict(row) for row in payload.get("qubit_properties") or []
        }
        if self.dt_ns != 4 or len(self.gates) != 976 or len(self.qubits) != TARGET_QUBITS:
            raise ValueError("Property oracle cardinality mismatch.")

    def gate(self, name: str, qubits: tuple[int, ...]) -> dict[str, Any]:
        key = (name, qubits)
        if key not in self.gates:
            raise KeyError(f"Missing exact native property tuple: {key}")
        return self.gates[key]


class DatedPropertyRouter(FullStreamRouter):
    """V4.6 router plus exact property usage and integer-dt ASAP clocks."""

    def __init__(
        self,
        *,
        seed: int,
        total_qubits: int,
        paths: list[list[tuple[int, ...] | None]],
        target_edges: set[tuple[int, int]],
        properties: PropertyOracle,
        initial_physical_qubits: Sequence[int] | None = None,
        candidate_name: str,
    ) -> None:
        super().__init__(seed=seed, total_qubits=total_qubits, paths=paths, target_edges=target_edges)
        self.properties = properties
        self.candidate_name = candidate_name
        self.clock_ticks = [0] * TARGET_QUBITS
        self.property_usage: Counter[tuple[str, tuple[int, ...]]] = Counter()
        self.stage_usage: Counter[tuple[str, str]] = Counter()
        self.unit_error_occurrences = 0
        self._active_stage = "UNSET"
        self._initial_physical_qubits = list(initial_physical_qubits or range(total_qubits))
        if len(self._initial_physical_qubits) != total_qubits or len(set(self._initial_physical_qubits)) != total_qubits:
            raise ValueError("Initial layout must be a unique physical-qubit list matching logical width.")
        if any(value < 0 or value >= TARGET_QUBITS for value in self._initial_physical_qubits):
            raise ValueError("Initial layout physical qubit out of range.")
        self.logical_to_physical = list(self._initial_physical_qubits)
        self.physical_to_logical = [None] * TARGET_QUBITS
        for logical, physical in enumerate(self.logical_to_physical):
            self.physical_to_logical[physical] = logical

    def _record_gate(self, gate: str, qubits: tuple[int, ...], count: int = 1) -> dict[str, Any]:
        if count < 1:
            raise ValueError("Native property occurrence count must be positive.")
        row = self.properties.gate(gate, qubits)
        self.property_usage[(gate, qubits)] += count
        self.stage_usage[(self._active_stage, gate)] += count
        if row["_unit_error"]:
            self.unit_error_occurrences += count
        return row

    def _schedule_one(self, gate: str, qubit: int, count: int = 1) -> None:
        row = self._record_gate(gate, (qubit,), count)
        self.clock_ticks[qubit] += count * int(row["duration_ticks"])

    def _schedule_cz(self, left: int, right: int) -> None:
        row = self._record_gate("cz", (left, right))
        end = max(self.clock_ticks[left], self.clock_ticks[right]) + int(row["duration_ticks"])
        self.clock_ticks[left] = end
        self.clock_ticks[right] = end

    def _native_swap(self, left: int, right: int, stage: str) -> None:
        self._active_stage = stage
        left_sx = self._record_gate("sx", (left,), 3)
        right_sx = self._record_gate("sx", (right,), 3)
        cz = self._record_gate("cz", (left, right), 3)
        left_ticks = int(left_sx["duration_ticks"])
        right_ticks = int(right_sx["duration_ticks"])
        cz_ticks = int(cz["duration_ticks"])
        for _ in range(3):
            left_end = self.clock_ticks[left] + left_ticks
            right_end = self.clock_ticks[right] + right_ticks
            end = max(left_end, right_end) + cz_ticks
            self.clock_ticks[left] = end
            self.clock_ticks[right] = end
        super()._native_swap(left, right, stage)

    def _native_cx(self, control: int, target: int) -> None:
        rz = self._record_gate("rz", (target,), 4)
        sx = self._record_gate("sx", (target,), 2)
        cz = self._record_gate("cz", (control, target))
        half_h_ticks = 2 * int(rz["duration_ticks"]) + int(sx["duration_ticks"])
        self.clock_ticks[target] += half_h_ticks
        end = max(self.clock_ticks[control], self.clock_ticks[target]) + int(cz["duration_ticks"])
        self.clock_ticks[control] = end
        self.clock_ticks[target] = end + half_h_ticks
        super()._native_cx(control, target)

    def emit(self, stage: str, opcode: str, qubits: Sequence[int], angle: Fraction | None = None) -> None:
        self._active_stage = stage
        if opcode != "CX":
            physical = self.logical_to_physical[int(qubits[0])]
            if opcode not in INPUT_NATIVE_COUNTS:
                raise ValueError(f"Unsupported V4.7 input opcode: {opcode}")
            for gate, count in INPUT_NATIVE_COUNTS[opcode]:
                self._schedule_one(gate, physical, count)
        super().emit(stage, opcode, qubits, angle)

    def finish_property_routing(self, expected_parent_manifest: Mapping[str, Any]) -> dict[str, Any]:
        routed = super().finish_routing(expected_parent_manifest)
        inherited_v46_layout = copy.deepcopy(routed.get("layout") or {})
        if self.candidate_name == CANDIDATE_NAME:
            inherited_routing = routed.get("routing_ledger") or {}
            routing_core = {
                "candidate_name": CANDIDATE_NAME,
                "distance_histogram_before_each_cx": inherited_routing.get("distance_histogram_before_each_cx") or {},
                "maximum_distance_before_routing": inherited_routing.get("maximum_distance_before_routing"),
                "path_oracle_sha256": EXPECTED_PATH_ORACLE_SHA256,
                "routing_method": "FAULT_EXCLUDED_MINIMUM_HOP_REPORTED_ERROR_DURATION_LEXICOGRAPHIC_STATIC_ORACLE",
                "transpiler_seed": None,
            }
            routed["routing_ledger"] = {
                **routing_core,
                "routing_ledger_sha256": canonical_json_sha256(routing_core),
            }
        layout_core = {
            "final_logical_to_physical": self.logical_to_physical,
            "final_physical_to_logical": self.physical_to_logical,
            "initial_layout": self._initial_physical_qubits,
            "initial_layout_contract": (
                "TRIVIAL_LOGICAL_Q_TO_PHYSICAL_Q"
                if self._initial_physical_qubits == list(range(self.total_qubits))
                else "LOGICAL_ORDER_TO_ASCENDING_FAULT_EXCLUDED_COMPONENT_PREFIX"
            ),
            "logical_qubits": self.total_qubits,
            "output_interpretation": "FINAL_LAYOUT_IS_THE_PERMUTATION_REQUIRED_TO_INTERPRET_LOGICAL_OUTPUTS",
            "physical_qubits": TARGET_QUBITS,
            "used_physical_qubits": sorted(self.used_physical_qubits),
        }
        routed["layout"] = {**layout_core, "layout_sha256": canonical_json_sha256(layout_core)}

        usage_rows: list[dict[str, Any]] = []
        independent_log10 = 0.0
        error_mass = Decimal(0)
        error_mass_by_gate: dict[str, Decimal] = {
            name: Decimal(0) for name in ("cz", "id", "rz", "sx", "x")
        }
        with localcontext() as decimal_context:
            decimal_context.prec = 50
            for (gate, qubits), count in sorted(self.property_usage.items()):
                prop = self.properties.gate(gate, qubits)
                error = prop["_error_decimal"]
                contribution = error * count
                error_mass += contribution
                error_mass_by_gate[gate] += contribution
                if error < 1:
                    independent_log10 += count * math.log10(1.0 - float(error))
                usage_rows.append(
                    {
                        "duration_ticks_each": int(prop["duration_ticks"]),
                        "gate": gate,
                        "occurrence_count": count,
                        "qubits": list(qubits),
                        "reported_error_each": str(prop["gate_error"]),
                        "reported_error_mass": format(contribution, "f"),
                        "serial_duration_ticks": int(prop["duration_ticks"]) * count,
                    }
                )
        usage_core = {
            "exact_gate_qargs_occurrences": usage_rows,
            "gate_occurrence_count": sum(self.property_usage.values()),
            "property_tuple_count_used": len(usage_rows),
        }
        usage = {**usage_core, "physical_property_usage_sha256": canonical_json_sha256(usage_core)}
        error_core = {
            "calibration_aware_circuit_fidelity": "NOT_CLAIMED",
            "diagnostic_independent_product_log10": None if self.unit_error_occurrences else independent_log10,
            "independent_product_is_acceptance_metric": False,
            "missing_property_occurrences": 0,
            "reported_gate_error_mass": format(error_mass, "f"),
            "reported_gate_error_mass_by_gate": {
                gate: format(value, "f") for gate, value in sorted(error_mass_by_gate.items())
            },
            "reported_gate_error_mass_interpretation": "DESCRIPTIVE_SUM_NOT_FIDELITY_SUCCESS_PROBABILITY_OR_EXPECTED_FAILURE_COUNT",
            "unit_error_gate_occurrences": self.unit_error_occurrences,
        }
        error = {**error_core, "error_screen_sha256": canonical_json_sha256(error_core)}
        stage_core = {
            "rows": [
                {"gate": gate, "occurrence_count": count, "stage": stage}
                for (stage, gate), count in sorted(self.stage_usage.items())
            ]
        }
        stage = {**stage_core, "stage_property_usage_sha256": canonical_json_sha256(stage_core)}
        makespan = max(self.clock_ticks)
        timing_core = {
            "dt_nanoseconds": self.properties.dt_ns,
            "final_physical_clock_ticks": self.clock_ticks,
            "makespan_nanoseconds": makespan * self.properties.dt_ns,
            "makespan_seconds": makespan * self.properties.dt_ns * 1e-9,
            "makespan_ticks": makespan,
            "model_name": "PROPERTIES_CONDITIONED_PER_QUBIT_ASAP_INTEGER_DT",
            "not_hardware_job_or_pulse_runtime": True,
        }
        timing = {**timing_core, "timing_ledger_sha256": canonical_json_sha256(timing_core)}
        routed.update(
            {
                "error_screen": error,
                "physical_property_usage": usage,
                "stage_property_usage": stage,
                "timing_ledger": timing,
                "v46_compatible_layout_commitment": (
                    inherited_v46_layout
                    if self.candidate_name == "V4_6_EXACT_BASIC_SWAP_BASELINE"
                    else None
                ),
            }
        )
        return routed


class PairedCircuitStream(CircuitStream):
    """Emit one reconstructed logical stream into two independent routers."""

    def __init__(self, baseline: DatedPropertyRouter, candidate: DatedPropertyRouter) -> None:
        if baseline.seed != candidate.seed or baseline.total_qubits != candidate.total_qubits:
            raise ValueError("Paired V4.7 routers must share seed and logical width.")
        super().__init__(seed=baseline.seed, total_qubits=baseline.total_qubits)
        self.baseline = baseline
        self.candidate = candidate

    def emit(
        self,
        stage: str,
        opcode: str,
        qubits: Sequence[int],
        angle: Fraction | None = None,
    ) -> None:
        self.baseline.emit(stage, opcode, qubits, angle)
        self.candidate.emit(stage, opcode, qubits, angle)
        self.elementary_counts[opcode] += 1
        self.instruction_count += 1
        self.max_qubit_id = max(self.max_qubit_id, *(int(value) for value in qubits))

    def transfer_macro_counts(self) -> None:
        self.baseline.macro_counts = self.macro_counts.copy()
        self.candidate.macro_counts = self.macro_counts.copy()


def _resource_gate(routed: Mapping[str, Any], parent_cx: int, logical_qubits: int) -> dict[str, Any]:
    native = routed.get("native_ledger") or {}
    layout = routed.get("layout") or {}
    logical_to_physical = layout.get("final_logical_to_physical") or []
    physical_to_logical = layout.get("final_physical_to_logical") or []
    final_layout_bijective = bool(
        len(logical_to_physical) == logical_qubits
        and len(set(logical_to_physical)) == logical_qubits
        and all(isinstance(physical, int) and 0 <= physical < TARGET_QUBITS for physical in logical_to_physical)
        and len(physical_to_logical) == TARGET_QUBITS
        and sum(value is not None for value in physical_to_logical) == logical_qubits
        and all(physical_to_logical[physical] == logical for logical, physical in enumerate(logical_to_physical))
    )
    cz = int((native.get("native_operation_counts") or {}).get("cz", -1))
    ratio = Fraction(cz, parent_cx)
    accepted = bool(
        routed.get("input_manifest_exact_parent") is True
        and logical_qubits <= TARGET_QUBITS
        and native.get("coupling_violations") == 0
        and native.get("isa_violations") == 0
        and cz <= 250_000_000
        and int(native.get("asap_structural_depth", 250_000_001)) <= 250_000_000
        and ratio <= 100
        and (routed.get("error_screen") or {}).get("missing_property_occurrences") == 0
        and (routed.get("error_screen") or {}).get("unit_error_gate_occurrences") == 0
        and final_layout_bijective
    )
    core = {
        "cz_expansion_ratio_exact": f"{ratio.numerator}/{ratio.denominator}",
        "final_layout_bijective": final_layout_bijective,
        "logical_capacity_margin": TARGET_QUBITS - logical_qubits,
        "maximum_native_cz": 250_000_000,
        "maximum_native_cz_expansion_over_v45_cx": 100,
        "maximum_structural_depth": 250_000_000,
        "status": "PASS_V47_RESEARCH_FEASIBILITY_GATE" if accepted else "REJECT_V47_RESEARCH_FEASIBILITY_GATE",
        "v45_input_cx": parent_cx,
    }
    return {**core, "resource_gate_sha256": canonical_json_sha256(core)}


def _architecture_lower_bound(
    *, direct_cx: int, properties: PropertyOracle, maximum_t2_seconds: float
) -> dict[str, Any]:
    cz_rows = [row for (gate, _), row in properties.gates.items() if gate == "cz"]
    minimum_error = min(row["_error_decimal"] for row in cz_rows)
    minimum_ticks = min(int(row["duration_ticks"]) for row in cz_rows)
    with localcontext() as decimal_context:
        decimal_context.prec = 50
        error_mass = Decimal(direct_cx) * minimum_error
    duration_ticks = math.ceil(direct_cx / 78) * minimum_ticks
    maximum_t2_ticks = math.floor(maximum_t2_seconds / (properties.dt_ns * 1e-9))
    core = {
        "direct_translated_cx": direct_cx,
        "idealized_parallel_cz_capacity": 78,
        "minimum_cz_duration_ticks": minimum_ticks,
        "minimum_cz_reported_error": format(minimum_error, "f"),
        "optimistic_cz_duration_lower_bound_ticks": duration_ticks,
        "optimistic_cz_duration_over_maximum_snapshot_t2": duration_ticks / maximum_t2_ticks,
        "optimistic_reported_error_mass_lower_bound": format(error_mass, "f"),
        "passes_duration_screen": duration_ticks <= maximum_t2_ticks,
        "passes_reported_error_mass_screen": error_mass < Decimal(1),
        "scope": "ZERO_SWAP_ZERO_1Q_IDEALIZED_NECESSARY_CONDITION_NOT_A_SUFFICIENT_HARDWARE_MODEL",
    }
    return {**core, "architecture_lower_bound_sha256": canonical_json_sha256(core)}


def _run_seed(
    *,
    seed: int,
    rows: Sequence[Mapping[str, Any]],
    connectivity: Mapping[str, Any],
    parent_row: Mapping[str, Any],
    path_table: list[list[tuple[int, ...] | None]],
    target_edges: set[tuple[int, int]],
    properties: PropertyOracle,
    initial_physical_qubits: Sequence[int],
    candidate_name: str,
    progress: Any | None,
) -> dict[str, Any]:
    layout = build_layout(rows)
    stream = DatedPropertyRouter(
        seed=seed,
        total_qubits=layout.total_qubits,
        paths=path_table,
        target_edges=target_edges,
        properties=properties,
        initial_physical_qubits=initial_physical_qubits,
        candidate_name=candidate_name,
    )
    if progress is not None:
        progress(f"V4.7 · {candidate_name} · seed {seed} · coin rings")
    emit_binary_coin_rings(stream, layout)
    if progress is not None:
        progress(f"V4.7 · {candidate_name} · seed {seed} · streamed SELECT")
    emit_binary_selector(stream, rows, layout)
    for rank, bridge in enumerate(connectivity.get("selected_bridges") or [], start=1):
        if progress is not None:
            progress(f"V4.7 · {candidate_name} · seed {seed} · bridge {rank}")
        emit_bridge(stream, bridge=bridge, layout=layout, rank=rank)
    expected_manifest = parent_row.get("stream_manifest") or parent_row.get("input_stream_manifest") or {}
    routed = stream.finish_property_routing(expected_manifest)
    parent_cx = int(((expected_manifest.get("elementary_counts") or {}).get("CX", 0)))
    return {
        "candidate_name": candidate_name,
        "resource_gate": _resource_gate(routed, parent_cx, layout.total_qubits),
        "routed_compilation": routed,
    }


def _run_seed_pair(
    *,
    seed: int,
    rows: Sequence[Mapping[str, Any]],
    connectivity: Mapping[str, Any],
    parent_row: Mapping[str, Any],
    baseline_paths: list[list[tuple[int, ...] | None]],
    baseline_edges: set[tuple[int, int]],
    candidate_paths: list[list[tuple[int, ...] | None]],
    candidate_edges: set[tuple[int, int]],
    candidate_component: Sequence[int],
    properties: PropertyOracle,
    progress: Any | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Reconstruct once while retaining fully independent routing states."""

    layout = build_layout(rows)
    baseline_stream = DatedPropertyRouter(
        seed=seed,
        total_qubits=layout.total_qubits,
        paths=baseline_paths,
        target_edges=baseline_edges,
        properties=properties,
        initial_physical_qubits=list(range(layout.total_qubits)),
        candidate_name="V4_6_EXACT_BASIC_SWAP_BASELINE",
    )
    candidate_stream = DatedPropertyRouter(
        seed=seed,
        total_qubits=layout.total_qubits,
        paths=candidate_paths,
        target_edges=candidate_edges,
        properties=properties,
        initial_physical_qubits=list(candidate_component[: layout.total_qubits]),
        candidate_name=CANDIDATE_NAME,
    )
    stream = PairedCircuitStream(baseline_stream, candidate_stream)
    if progress is not None:
        progress(f"V4.7 · paired baseline/candidate · seed {seed} · coin rings")
    emit_binary_coin_rings(stream, layout)
    if progress is not None:
        progress(f"V4.7 · paired baseline/candidate · seed {seed} · streamed SELECT")
    emit_binary_selector(stream, rows, layout)
    for rank, bridge in enumerate(connectivity.get("selected_bridges") or [], start=1):
        if progress is not None:
            progress(f"V4.7 · paired baseline/candidate · seed {seed} · bridge {rank}")
        emit_bridge(stream, bridge=bridge, layout=layout, rank=rank)
    stream.transfer_macro_counts()
    expected_manifest = parent_row.get("stream_manifest") or parent_row.get("input_stream_manifest") or {}
    parent_cx = int(((expected_manifest.get("elementary_counts") or {}).get("CX", 0)))
    baseline_routed = baseline_stream.finish_property_routing(expected_manifest)
    candidate_routed = candidate_stream.finish_property_routing(expected_manifest)
    return (
        {
            "candidate_name": "V4_6_EXACT_BASIC_SWAP_BASELINE",
            "resource_gate": _resource_gate(baseline_routed, parent_cx, layout.total_qubits),
            "routed_compilation": baseline_routed,
        },
        {
            "candidate_name": CANDIDATE_NAME,
            "resource_gate": _resource_gate(candidate_routed, parent_cx, layout.total_qubits),
            "routed_compilation": candidate_routed,
        },
    )


def build_v47_artifact(*, root: str | Path | None = None, progress: Any | None = None) -> dict[str, Any]:
    paths = _paths(root)
    spec = load_v47_spec(root=paths["root"])
    property_payload = load_property_oracle(root=paths["root"])
    model = load_model_contract(root=paths["root"])
    parent = authenticate_v46_parent(root=paths["root"])
    if parent.get("valid") is not True:
        raise RuntimeError(f"V4.6 parent authentication failed: {parent.get('errors')}")
    _, baseline_paths = load_path_oracle(root=paths["root"])
    path_payload, candidate_paths, component = load_candidate_path_oracle(root=paths["root"])
    properties = PropertyOracle(property_payload)
    v44 = read_json_strict(paths["v44_snapshot"])
    if raw_file_sha256(paths["v44_snapshot"]) != EXPECTED_V44_SNAPSHOT_RAW_SHA256:
        raise ValueError("V4.4 snapshot raw identity mismatch.")
    baseline_edges = set(parse_coupling_edges(v44))
    candidate_edges = {
        qubits
        for (gate, qubits), row in properties.gates.items()
        if gate == "cz" and not row["_unit_error"] and qubits[0] in component and qubits[1] in component
    }
    v46 = parent.get("artifact") or {}
    parent_rows = {int(row["seed"]): row for row in v46.get("seed_routings") or []}
    if list(parent_rows) != list(SEEDS):
        raise ValueError("Authenticated V4.6 seed order mismatch.")
    v41 = read_json_strict(paths["v41_artifact"])
    certificates = _certificate_by_seed(paths["root"])
    compressions = {int(row["seed"]): row for row in (v41.get("compression_evidence") or {}).get("seed_rows") or []}
    connectivity = {int(row["seed"]): row for row in (v41.get("connectivity_evidence") or {}).get("seed_rows") or []}
    maximum_t2_seconds = max(float(row["t2_seconds"]) for row in property_payload.get("qubit_properties") or [])

    if any(name == "qiskit" or name.startswith("qiskit.") or name.startswith("qiskit_ibm_runtime") for name in sys.modules):
        raise RuntimeError("V4.7 compiler must run without Qiskit or provider SDK imports.")
    network_attempts: list[str] = []

    def deny_network(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        network_attempts.append("socket")
        raise RuntimeError("V4.7 prohibits network access.")

    seed_evaluations: list[dict[str, Any]] = []
    with mock.patch.object(socket.socket, "connect", deny_network), mock.patch(
        "socket.create_connection", side_effect=deny_network
    ):
        for seed in SEEDS:
            rows = _guarded_rows(certificates[seed], compressions[seed])
            parent_seed = parent_rows[seed]
            logical_qubits = int(parent_seed.get("logical_qubits", 0))
            baseline, candidate = _run_seed_pair(
                seed=seed,
                rows=rows,
                connectivity=connectivity[seed],
                parent_row=(parent_seed.get("routed_compilation") or {}),
                baseline_paths=baseline_paths,
                baseline_edges=baseline_edges,
                candidate_paths=candidate_paths,
                candidate_edges=candidate_edges,
                candidate_component=component,
                properties=properties,
                progress=progress,
            )
            baseline_routed = baseline["routed_compilation"]
            candidate_routed = candidate["routed_compilation"]
            parent_routed = parent_seed.get("routed_compilation") or {}
            baseline_exact = bool(
                baseline_routed.get("route_ir") == parent_routed.get("route_ir")
                and baseline_routed.get("native_ledger") == parent_routed.get("native_ledger")
                and baseline_routed.get("v46_compatible_layout_commitment") == parent_routed.get("layout")
                and baseline_routed.get("routing_ledger") == parent_routed.get("routing_ledger")
                and baseline_routed.get("input_stream_manifest") == parent_routed.get("input_stream_manifest")
            )
            if not baseline_exact:
                raise RuntimeError(f"V4.7 baseline failed exact V4.6 replay for seed {seed}.")
            baseline_error = Decimal((baseline_routed.get("error_screen") or {}).get("reported_gate_error_mass", "NaN"))
            candidate_error = Decimal((candidate_routed.get("error_screen") or {}).get("reported_gate_error_mass", "NaN"))
            baseline_ticks = int((baseline_routed.get("timing_ledger") or {}).get("makespan_ticks", -1))
            candidate_ticks = int((candidate_routed.get("timing_ledger") or {}).get("makespan_ticks", -1))
            baseline_cz = int(((baseline_routed.get("native_ledger") or {}).get("native_operation_counts") or {}).get("cz", -1))
            candidate_cz = int(((candidate_routed.get("native_ledger") or {}).get("native_operation_counts") or {}).get("cz", -1))
            pareto = bool(
                (candidate.get("resource_gate") or {}).get("status")
                == "PASS_V47_RESEARCH_FEASIBILITY_GATE"
                and candidate_error < baseline_error
                and candidate_ticks <= baseline_ticks
                and candidate_cz <= baseline_cz
            )
            direct_cx = int((baseline_routed.get("native_ledger") or {}).get("direct_translated_cx_count", 0))
            lower = _architecture_lower_bound(
                direct_cx=direct_cx,
                properties=properties,
                maximum_t2_seconds=maximum_t2_seconds,
            )
            baseline_unit = int((baseline_routed.get("error_screen") or {}).get("unit_error_gate_occurrences", 0))
            baseline["status"] = (
                "REJECT_DATED_PROPERTIES_UNIT_ERROR_USAGE"
                if baseline_unit
                else "MODELED_ONLY_NO_HARDWARE_ADMISSION"
            )
            candidate["status"] = (
                "PASS_RESEARCH_OPTIMIZATION_FEASIBILITY"
                if (candidate.get("resource_gate") or {}).get("status") == "PASS_V47_RESEARCH_FEASIBILITY_GATE"
                else "REJECT_RESEARCH_OPTIMIZATION_FEASIBILITY"
            )
            comparison_core = {
                "candidate_minus_baseline_makespan_ticks": candidate_ticks - baseline_ticks,
                "candidate_minus_baseline_native_cz": candidate_cz - baseline_cz,
                "candidate_minus_baseline_reported_error_mass": format(candidate_error - baseline_error, "f"),
                "pareto_safe_for_seed": pareto,
                "pareto_status": "PARETO_DOMINATES_BASELINE" if pareto else "PARETO_SAFE_REPLACEMENT_NOT_DEMONSTRATED_FOR_SEED",
            }
            comparison = {**comparison_core, "comparison_sha256": canonical_json_sha256(comparison_core)}
            seed_core = {
                "architecture_lower_bound": lower,
                "baseline_v46": baseline,
                "baseline_v46_commitments_exact": baseline_exact,
                "candidate": candidate,
                "comparison": comparison,
                "instance_id": parent_seed.get("instance_id"),
                "logical_qubits": logical_qubits,
                "seed": seed,
            }
            seed_evaluations.append({**seed_core, "seed_evaluation_sha256": canonical_json_sha256(seed_core)})
    if network_attempts:
        raise RuntimeError(f"Network attempts blocked during V4.7: {network_attempts}")

    baselines = [row["baseline_v46"] for row in seed_evaluations]
    candidates = [row["candidate"] for row in seed_evaluations]
    all_candidate_feasible = all(row.get("status") == "PASS_RESEARCH_OPTIMIZATION_FEASIBILITY" for row in candidates)
    all_pareto = all((row.get("comparison") or {}).get("pareto_safe_for_seed") is True for row in seed_evaluations)
    all_architecture_fail = all(
        not (row.get("architecture_lower_bound") or {}).get("passes_duration_screen", True)
        and not (row.get("architecture_lower_bound") or {}).get("passes_reported_error_mass_screen", True)
        for row in seed_evaluations
    )
    aggregate_core = {
        "all_eight_architecture_lower_bounds_fail_both_screens": all_architecture_fail,
        "all_eight_baseline_commitments_exact_v46": all(row.get("baseline_v46_commitments_exact") is True for row in seed_evaluations),
        "all_eight_candidate_research_feasible": all_candidate_feasible,
        "all_eight_pareto_safe": all_pareto,
        "baseline_total_unit_error_gate_occurrences": sum(int(((row.get("routed_compilation") or {}).get("error_screen") or {}).get("unit_error_gate_occurrences", 0)) for row in baselines),
        "candidate_total_unit_error_gate_occurrences": sum(int(((row.get("routed_compilation") or {}).get("error_screen") or {}).get("unit_error_gate_occurrences", 0)) for row in candidates),
        "maximum_baseline_makespan_ticks": max(int(((row.get("routed_compilation") or {}).get("timing_ledger") or {}).get("makespan_ticks", 0)) for row in baselines),
        "maximum_candidate_makespan_ticks": max(int(((row.get("routed_compilation") or {}).get("timing_ledger") or {}).get("makespan_ticks", 0)) for row in candidates),
        "ordered_seed_evaluation_root_sha256": canonical_json_sha256([row["seed_evaluation_sha256"] for row in seed_evaluations]),
        "seed_count": len(seed_evaluations),
    }
    aggregate = {**aggregate_core, "aggregate_sha256": canonical_json_sha256(aggregate_core)}
    decisions = {
        "fixed_architecture_historical_stress_screen": (
            "FIXED_V46_ARCHITECTURE_REJECTED_BY_PREREGISTERED_HISTORICAL_PROPERTIES_STRESS_SCREEN"
            if all_architecture_fail
            else "FIXED_V46_ARCHITECTURE_NOT_UNIFORMLY_REJECTED_BY_HISTORICAL_PROPERTIES_STRESS_SCREEN"
        ),
        "baseline_dated_properties": (
            "REJECT_DATED_PROPERTIES_UNIT_ERROR_USAGE"
            if aggregate_core["baseline_total_unit_error_gate_occurrences"]
            else "MODELED_ONLY_NO_HARDWARE_ADMISSION"
        ),
        "candidate_research_routing": (
            "V47_FAULT_EXCLUDED_RESEARCH_ROUTING_FEASIBLE_UNDER_HISTORICAL_PROPERTIES"
            if all_candidate_feasible
            else "V47_FAULT_EXCLUDED_RESEARCH_ROUTING_REJECTED"
        ),
        "next_falsifiable_gate": "MULTI_SNAPSHOT_ROBUSTNESS_AND_ARCHITECTURE_LEVEL_CZ_REDUCTION_BEFORE_ANY_CURRENT_PROVIDER_DISCOVERY",
        "overall": (
            "V47_HISTORICAL_PROPERTIES_STRESS_SCREEN_REJECTS_FIXED_V46_ARCHITECTURE_NO_CURRENT_HARDWARE_INFERENCE"
            if all_architecture_fail
            else "V47_DATED_PROPERTIES_AUDIT_COMPLETED_NO_HARDWARE_ADMISSION"
        ),
        "pareto_safe_replacement": (
            "PARETO_SAFE_REPLACEMENT_DEMONSTRATED_WITHIN_V47_MODEL"
            if all_pareto
            else "PARETO_SAFE_REPLACEMENT_NOT_DEMONSTRATED"
        ),
        "production_admission": "OFFLINE_HISTORICAL_PROPERTIES_ONLY_HARDWARE_EXECUTION_REJECTED",
    }
    boundary = copy.deepcopy(spec["claim_boundary"])
    boundary.update(
        {
            "properties_conditioned_asap_duration_estimate": "EVALUATED_OFFLINE",
            "reported_gate_error_mass": "EVALUATED_DESCRIPTIVE_NOT_FIDELITY",
            "provider_sdk_imported": False,
            "provider_credentials_read": False,
            "credential_reads": 0,
            "provider_calls": 0,
            "network_calls": 0,
            "backend_run_calls": 0,
            "local_simulator_jobs_submitted": 0,
            "qpu_jobs_submitted": 0,
            "hardware_executable": False,
        }
    )
    core = {
        "aggregate": aggregate,
        "artifact_version": ARTIFACT_VERSION,
        "candidate_contract": {
            "candidate_name": CANDIDATE_NAME,
            "component_size": len(component),
            "path_oracle_raw_file_sha256": EXPECTED_PATH_ORACLE_RAW_SHA256,
            "path_oracle_sha256": path_payload.get("path_oracle_sha256"),
        },
        "claim_boundary": boundary,
        "decisions": decisions,
        "model_contract": {
            "model_contract_raw_file_sha256": EXPECTED_MODEL_RAW_SHA256,
            "model_contract_sha256": model.get("model_contract_sha256"),
        },
        "parent": {
            "artifact_raw_file_sha256": EXPECTED_V46_ARTIFACT_RAW_SHA256,
            "artifact_sha256": EXPECTED_V46_ARTIFACT_SHA256,
            "freeze_raw_file_sha256": EXPECTED_V46_FREEZE_RAW_SHA256,
            "freeze_sha256": EXPECTED_V46_FREEZE_SHA256,
            "immutable_file_count": parent.get("immutable_file_count"),
            "immutable_files_exact": parent.get("immutable_files_exact"),
            "ordered_route_ir_root_sha256": EXPECTED_V46_ROUTE_ROOT_SHA256,
        },
        "properties_snapshot": {
            "global_last_update_date": ((property_payload.get("property_time_range") or {}).get("global_last_update_date")),
            "maximum_embedded_property_date": ((property_payload.get("property_time_range") or {}).get("maximum_embedded_property_date")),
            "properties_raw_file_sha256": EXPECTED_RAW_PROPERTIES_SHA256,
            "properties_snapshot_raw_file_sha256": EXPECTED_PROPERTIES_RAW_SHA256,
            "properties_snapshot_sha256": property_payload.get("properties_snapshot_sha256"),
            "snapshot_is_current_hardware_evidence": False,
        },
        "research_classification": "RESEARCH_ONLY",
        "seed_evaluations": seed_evaluations,
        "source_raw_file_sha256": raw_file_sha256(paths["source"]),
        "independent_checker_raw_file_sha256": raw_file_sha256(paths["checker"]),
        "spec_raw_file_sha256": EXPECTED_SPEC_RAW_SHA256,
        "spec_sha256": EXPECTED_SPEC_SHA256,
        "v47_version": V47_VERSION,
    }
    return {**core, "artifact_sha256": canonical_json_sha256(core)}


def seal_v47_artifact(*, root: str | Path | None = None, output: str | Path | None = None) -> dict[str, Any]:
    paths = _paths(root)
    artifact = build_v47_artifact(root=paths["root"], progress=lambda message: print(message, flush=True))
    target = Path(output) if output is not None else paths["artifact"]
    if not target.is_absolute():
        target = paths["root"] / target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(artifact, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return {
        "artifact": str(target),
        "artifact_raw_file_sha256": raw_file_sha256(target),
        "artifact_sha256": artifact["artifact_sha256"],
        "decisions": artifact["decisions"],
    }


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=None)
    parser.add_argument("--output", default=None)
    args = parser.parse_args(argv)
    print(json.dumps(seal_v47_artifact(root=args.root, output=args.output), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "ARTIFACT_VERSION",
    "CANDIDATE_NAME",
    "DEFAULT_ARTIFACT_NAME",
    "DatedPropertyRouter",
    "PropertyOracle",
    "V47_VERSION",
    "authenticate_v46_parent",
    "build_v47_artifact",
    "load_candidate_path_oracle",
    "load_model_contract",
    "load_property_oracle",
    "load_v47_spec",
    "seal_v47_artifact",
]
