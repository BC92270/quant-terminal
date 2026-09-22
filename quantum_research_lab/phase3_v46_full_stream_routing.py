"""Quantum Lab V4.6 full-stream FakeMarrakesh routing compiler.

V4.6 consumes every elementary instruction of each authenticated V4.5 stream,
reproduces its canonical stream commitment, translates it to an exact compact
native-macro IR and routes every CX with the frozen Qiskit 2.5.2 BasicSwap path
oracle.  The compiler never retains a monolithic circuit or native instruction
list: every input instruction is processed once and committed to a chunked,
deterministically expandable route transcript.

This is an offline structural compilation experiment.  It imports neither
Qiskit nor a provider SDK, reads no credentials, performs no network access and
submits no simulator or QPU job.  Passing the structural and preregistered
resource gates is not evidence of current calibration, fidelity, duration,
utility, hardware executability or quantum advantage.
"""

from __future__ import annotations

import argparse
import copy
from collections import Counter, defaultdict, deque
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import socket
import sys
from typing import Any, Mapping, Sequence
from unittest import mock

from .phase3_v41_certified_bridge_compiler import _certificate_by_seed, _guarded_rows
from .phase3_v42_coined_walk_compiler import BUDGET_CNOT, SEEDS
from .phase3_v43_reversible_circuit_ir import CircuitStream
from .phase3_v44_named_backend_routing import parse_coupling_edges
from .phase3_v45_proof_carrying_width_reduction import (
    SUCCESSOR_MUTABLE,
    build_layout,
    emit_binary_coin_rings,
    emit_binary_selector,
    emit_bridge,
)


V46_VERSION = "PHASE III · V4.6 FULL-STREAM FAKEMARRAKESH ROUTING · V1"
ARTIFACT_VERSION = "PHASE III · V4.6 SEALED FULL-STREAM ROUTING ARTIFACT · V1"
SPEC_FILENAME = "PHASE_III_V4_6_FULL_STREAM_FAKEMARRAKESH_ROUTING_SPEC_V1.json"
PATH_ORACLE_FILENAME = "PHASE_III_V4_6_FAKEMARRAKESH_BASIC_PATH_ORACLE_V1.json"
TRANSLATION_FILENAME = "PHASE_III_V4_6_NATIVE_TRANSLATION_CONTRACT_V1.json"
DEFAULT_ARTIFACT_NAME = "SEALED_V4_6_FULL_STREAM_FAKEMARRAKESH_ROUTING_ARTIFACT.json"
ROUTE_CHUNK_INSTRUCTIONS = 8192
TARGET_QUBITS = 156
TRANSPILER_SEED = 4505

# Patched only after the V4.6 preregistration is sealed.
EXPECTED_SPEC_RAW_SHA256 = "81ab1238a4623d334da31a686d676ddd5a6f01696f0ded271ecbd0de6b693e95"
EXPECTED_SPEC_SHA256 = "2a2480f6932f3ef41ff94b1450467a703ed260767370a6dc75304f55820addf8"

EXPECTED_PATH_ORACLE_RAW_SHA256 = "faf9573fa7fe7c50e0a872e0d989a8d8938f181a9c136e6138121a53a7e55a5b"
EXPECTED_PATH_ORACLE_SHA256 = "0956cfa11e6a507cf8e4197e8c054b0bd90f4ca2a37ac895b61265e95d91ecf7"
EXPECTED_TRANSLATION_RAW_SHA256 = "7600a95edce3af75fda671f836585e99b837a04527a2f3e29dca8812b0f008dc"
EXPECTED_TRANSLATION_SHA256 = "e0ab1b7612f7dac1ee9946ff296ee82ab603ed069a228d0dbffd537621f266a7"

EXPECTED_V45_FREEZE_RAW_SHA256 = "1f20e7c3c82c9441132d530a9204b0db19ad0d31c43b867cc029394bda276cd7"
EXPECTED_V45_FREEZE_SHA256 = "05197d460b076275a3c7712aa895959d9d1916b09e1999750e1e36cc0c27a218"
EXPECTED_V45_PATH_FINGERPRINT = "1c81474eee596a857d099c7882ddb02d409a620a2ddf311f25c783c491370d14"
EXPECTED_V45_FROZEN_FILE_COUNT = 229
EXPECTED_V45_IMMUTABLE_FILE_COUNT = 227
EXPECTED_V45_ARTIFACT_RAW_SHA256 = "f28f2975b83d38e32b285cac8c2b7506a07f6341739f3153bde01d42e1219257"
EXPECTED_V45_ARTIFACT_SHA256 = "9ab980071cc247cdbc70e8f964ccfbb09c48997d1d14cc26148c39518facda45"
EXPECTED_V44_SNAPSHOT_RAW_SHA256 = "816814f383c7b9890a137ead7799c28f3fbfc0cac188ab274dfb65050e2b7fbd"
EXPECTED_V44_SNAPSHOT_SHA256 = "3a604026627653e697fba1b2b9b06d84298a13ca7a7f2c2f9f2ed551bdbfdaf3"


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
        "path_oracle": base / "quantum_research_lab" / PATH_ORACLE_FILENAME,
        "translation": base / "quantum_research_lab" / TRANSLATION_FILENAME,
        "source": base / "quantum_research_lab/phase3_v46_full_stream_routing.py",
        "checker": base / "quantum_research_lab/phase3_v46_independent_checker.py",
        "v45_freeze": base / "FREEZE_CONTRACT_V4_5.json",
        "v45_artifact": base / "outputs/quantum_phase3/v45_width_reduction/SEALED_V4_5_PROOF_CARRYING_WIDTH_REDUCTION_ARTIFACT.json",
        "v44_snapshot": base / "quantum_research_lab/PHASE_III_V4_4_FROZEN_BACKEND_SNAPSHOT_V1.json",
        "v41_artifact": base / "outputs/quantum_phase3/v41_certified_bridge/SEALED_V4_1_CERTIFIED_BRIDGE_COMPILER_ARTIFACT.json",
        "artifact": base / "outputs/quantum_phase3/v46_full_stream_routing" / DEFAULT_ARTIFACT_NAME,
    }


def _is_sha256(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text)


def _path_fingerprint(paths: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(sorted(paths), separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _load_self_hashed(path: Path, field: str) -> tuple[dict[str, Any], str]:
    payload = read_json_strict(path)
    core = {key: value for key, value in payload.items() if key != field}
    semantic = canonical_json_sha256(core)
    if payload.get(field) != semantic:
        raise ValueError(f"Self-hash mismatch for {path.name}.")
    return payload, semantic


def authenticate_v45_parent(*, root: str | Path | None = None) -> dict[str, Any]:
    """Authenticate the V4.5 freeze and all 227 successor-immutable paths."""

    paths = _paths(root)
    errors: list[str] = []
    try:
        freeze = read_json_strict(paths["v45_freeze"])
        frozen = freeze.get("frozen_files") or {}
        freeze_core = {key: value for key, value in freeze.items() if key != "freeze_contract_sha256"}
        freeze_valid = bool(
            raw_file_sha256(paths["v45_freeze"]) == EXPECTED_V45_FREEZE_RAW_SHA256
            and canonical_json_sha256(freeze_core)
            == freeze.get("freeze_contract_sha256")
            == EXPECTED_V45_FREEZE_SHA256
            and isinstance(frozen, dict)
            and len(frozen) == freeze.get("frozen_file_count") == EXPECTED_V45_FROZEN_FILE_COUNT
            and _path_fingerprint(frozen)
            == freeze.get("frozen_paths_fingerprint_sha256")
            == EXPECTED_V45_PATH_FINGERPRINT
        )
    except Exception as exc:
        freeze, frozen, freeze_valid = {}, {}, False
        errors.append(f"V4.5 freeze authentication failed: {exc}")
    if not freeze_valid:
        errors.append("V4.5 freeze raw, semantic or inventory identity mismatch.")

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
    if len(immutable) != EXPECTED_V45_IMMUTABLE_FILE_COUNT or mismatches:
        errors.append(
            "V4.5 immutable path authentication failed: "
            f"count={len(immutable)} mismatches={mismatches[:5]}"
        )

    try:
        artifact = read_json_strict(paths["v45_artifact"])
        artifact_core = {key: value for key, value in artifact.items() if key != "artifact_sha256"}
        decisions = artifact.get("decisions") or {}
        artifact_valid = bool(
            raw_file_sha256(paths["v45_artifact"]) == EXPECTED_V45_ARTIFACT_RAW_SHA256
            and canonical_json_sha256(artifact_core)
            == artifact.get("artifact_sha256")
            == EXPECTED_V45_ARTIFACT_SHA256
            and decisions.get("overall")
            == "V45_PROOF_CARRYING_WIDTH_REDUCTION_PASSED_EXACT_PROMISE_PARITY"
            and decisions.get("next_falsifiable_gate")
            == "PINNED_FAKEMARRAKESH_FULL_RECONSTRUCTION_TRANSLATION_AND_ROUTING_OF_WIDTH_ADMITTED_V4_5_STREAMS"
        )
    except Exception as exc:
        artifact, artifact_valid = {}, False
        errors.append(f"V4.5 artifact authentication failed: {exc}")
    if not artifact_valid:
        errors.append("V4.5 artifact raw, semantic or scientific-decision mismatch.")

    return {
        "artifact": artifact,
        "errors": list(dict.fromkeys(errors)),
        "freeze": freeze,
        "immutable_file_count": len(immutable),
        "immutable_files_exact": len(immutable) == EXPECTED_V45_IMMUTABLE_FILE_COUNT and not mismatches,
        "valid": not errors,
    }


def load_v46_spec(path: str | Path | None = None, *, root: str | Path | None = None) -> dict[str, Any]:
    if not (_is_sha256(EXPECTED_SPEC_RAW_SHA256) and _is_sha256(EXPECTED_SPEC_SHA256)):
        raise RuntimeError("V4.6 preregistration identities have not been finalized.")
    target = Path(path) if path is not None else _paths(root)["spec"]
    if raw_file_sha256(target) != EXPECTED_SPEC_RAW_SHA256:
        raise ValueError("V4.6 specification raw identity mismatch.")
    payload = read_json_strict(target)
    core = {key: value for key, value in payload.items() if key not in {"v46_spec_sha", "v46_spec_sha256"}}
    semantic = canonical_json_sha256(core)
    boundary = payload.get("claim_boundary") or {}
    chronology = payload.get("chronology") or {}
    if not (
        semantic == EXPECTED_SPEC_SHA256
        and payload.get("v46_spec_sha256") == semantic
        and payload.get("v46_spec_sha") == semantic[:20].upper()
        and chronology.get("result_state_at_seal") == "NOT_EVALUATED"
        and boundary.get("research_classification") == "RESEARCH_ONLY"
        and boundary.get("provider_calls") == 0
        and boundary.get("network_calls") == 0
        and boundary.get("qpu_jobs_submitted") == 0
        and boundary.get("hardware_executable") is False
        and boundary.get("quantum_advantage") == "NOT_CLAIMED"
    ):
        raise ValueError("V4.6 specification semantic identity or claim boundary mismatch.")
    return payload


def load_path_oracle(*, root: str | Path | None = None) -> tuple[dict[str, Any], list[list[tuple[int, ...] | None]]]:
    paths = _paths(root)
    if raw_file_sha256(paths["path_oracle"]) != EXPECTED_PATH_ORACLE_RAW_SHA256:
        raise ValueError("V4.6 path oracle raw identity mismatch.")
    payload, semantic = _load_self_hashed(paths["path_oracle"], "path_oracle_sha256")
    if not (
        semantic == EXPECTED_PATH_ORACLE_SHA256
        and payload.get("target_qubits") == TARGET_QUBITS
        and payload.get("qiskit_version") == "2.5.2"
        and payload.get("routing_method") == "basic"
        and payload.get("transpiler_seed") == TRANSPILER_SEED
        and payload.get("ordered_path_count") == TARGET_QUBITS * (TARGET_QUBITS - 1)
    ):
        raise ValueError("V4.6 path oracle semantic contract mismatch.")

    snapshot = read_json_strict(paths["v44_snapshot"])
    if not (
        raw_file_sha256(paths["v44_snapshot"]) == EXPECTED_V44_SNAPSHOT_RAW_SHA256
        and snapshot.get("snapshot_sha256") == EXPECTED_V44_SNAPSHOT_SHA256
    ):
        raise ValueError("V4.4 target snapshot identity mismatch.")
    edges = set(parse_coupling_edges(snapshot))
    undirected = edges | {(right, left) for left, right in edges}
    adjacency: list[list[int]] = [[] for _ in range(TARGET_QUBITS)]
    for left, right in undirected:
        adjacency[left].append(right)
    distances: list[list[int]] = []
    for source in range(TARGET_QUBITS):
        distance = [-1] * TARGET_QUBITS
        distance[source] = 0
        queue: deque[int] = deque([source])
        while queue:
            node = queue.popleft()
            for neighbour in adjacency[node]:
                if distance[neighbour] < 0:
                    distance[neighbour] = distance[node] + 1
                    queue.append(neighbour)
        distances.append(distance)

    table: list[list[tuple[int, ...] | None]] = [
        [None for _ in range(TARGET_QUBITS)] for _ in range(TARGET_QUBITS)
    ]
    canonical_lines: list[str] = []
    compact = str(payload.get("ordered_paths_compact", ""))
    for raw_line in compact.splitlines():
        source_text, destination_text, route_text = raw_line.split("|", 2)
        source, destination = int(source_text), int(destination_text)
        route = tuple(int(value) for value in route_text.split(","))
        if not (
            source != destination
            and 0 <= source < TARGET_QUBITS
            and 0 <= destination < TARGET_QUBITS
            and table[source][destination] is None
            and route[0] == source
            and route[-1] == destination
            and len(route) - 1 == distances[source][destination]
            and len(set(route)) == len(route)
            and all(edge in undirected for edge in zip(route, route[1:]))
        ):
            raise ValueError(f"Invalid V4.6 path-oracle row: {raw_line[:160]}")
        table[source][destination] = route
        canonical_lines.append(raw_line + "\n")
    if not (
        len(canonical_lines) == TARGET_QUBITS * (TARGET_QUBITS - 1)
        and hashlib.sha256("".join(canonical_lines).encode("ascii")).hexdigest()
        == payload.get("ordered_paths_stream_sha256")
        and all(table[source][destination] is not None for source in range(TARGET_QUBITS) for destination in range(TARGET_QUBITS) if source != destination)
    ):
        raise ValueError("V4.6 path-oracle completeness or stream hash mismatch.")
    return payload, table


def load_translation_contract(*, root: str | Path | None = None) -> dict[str, Any]:
    path = _paths(root)["translation"]
    if raw_file_sha256(path) != EXPECTED_TRANSLATION_RAW_SHA256:
        raise ValueError("V4.6 native translation contract raw identity mismatch.")
    payload, semantic = _load_self_hashed(path, "translation_contract_sha256")
    macros = payload.get("native_macro_contract") or {}
    if not (
        semantic == EXPECTED_TRANSLATION_SHA256
        and payload.get("qiskit_version") == "2.5.2"
        and payload.get("routing_method") == "basic"
        and payload.get("translation_method") == "translator"
        and payload.get("optimization_level") == 0
        and payload.get("transpiler_seed") == TRANSPILER_SEED
        and payload.get("native_basis") == ["cz", "id", "rz", "sx", "x"]
        and set(macros) == {"CX", "H", "RY(theta_pi)", "RZ(theta_pi)", "SWAP", "T", "TDG", "X"}
        and payload.get("canary_count") == 9
    ):
        raise ValueError("V4.6 native translation contract mismatch.")
    return payload


class FullStreamRouter(CircuitStream):
    """Stream-preserving BasicSwap router with compact exact native macros."""

    def __init__(
        self,
        *,
        seed: int,
        total_qubits: int,
        paths: list[list[tuple[int, ...] | None]],
        target_edges: set[tuple[int, int]],
    ) -> None:
        super().__init__(seed=seed, total_qubits=total_qubits)
        self._paths = paths
        self._target_edges = target_edges
        self.logical_to_physical = list(range(total_qubits))
        self.physical_to_logical: list[int | None] = list(range(total_qubits)) + [
            None for _ in range(TARGET_QUBITS - total_qubits)
        ]
        self._route_stream = hashlib.sha256()
        self._route_chunk = hashlib.sha256()
        self._route_chunk_count = 0
        self._route_chunk_hashes: list[str] = []
        self._route_chunk_sizes: list[int] = []
        self._route_stage_hashers: dict[str, Any] = {}
        self._route_stage_counts: Counter[str] = Counter()
        self._route_stage_swaps: Counter[str] = Counter()
        self.native_counts: Counter[str] = Counter()
        self.depth_last_layer = [0] * TARGET_QUBITS
        self.used_physical_qubits: set[int] = set()
        self.distance_histogram: Counter[int] = Counter()
        self.swap_count = 0
        self.direct_cx_count = 0
        self.coupling_violations = 0
        self.isa_violations = 0
        self.global_phase_pi = Fraction(0, 1)

    @staticmethod
    def _angle_token(angle: Fraction | None) -> str:
        if angle is None:
            return "-"
        value = Fraction(angle)
        return f"{value.numerator}/{value.denominator}pi"

    def _close_route_chunk(self) -> None:
        if self._route_chunk_count:
            self._route_chunk_hashes.append(self._route_chunk.hexdigest())
            self._route_chunk_sizes.append(self._route_chunk_count)
            self._route_chunk = hashlib.sha256()
            self._route_chunk_count = 0

    def _commit_route_record(self, stage: str, line: bytes) -> None:
        self._route_stream.update(line)
        self._route_chunk.update(line)
        self._route_stage_hashers.setdefault(stage, hashlib.sha256()).update(line)
        self._route_stage_counts[stage] += 1
        self._route_chunk_count += 1
        if self._route_chunk_count == ROUTE_CHUNK_INSTRUCTIONS:
            self._close_route_chunk()

    def _one_qubit_depth(self, physical: int, count: int) -> None:
        self.depth_last_layer[physical] += count
        self.used_physical_qubits.add(physical)

    def _native_swap(self, left: int, right: int, stage: str) -> None:
        if (left, right) not in self._target_edges:
            self.coupling_violations += 1
        self.native_counts["sx"] += 6
        self.native_counts["cz"] += 3
        self.global_phase_pi += Fraction(3, 2)
        for _ in range(3):
            left_sx = self.depth_last_layer[left] + 1
            right_sx = self.depth_last_layer[right] + 1
            cz_layer = max(left_sx, right_sx) + 1
            self.depth_last_layer[left] = cz_layer
            self.depth_last_layer[right] = cz_layer
        self.used_physical_qubits.update((left, right))
        self.swap_count += 1
        self._route_stage_swaps[stage] += 1
        logical_left = self.physical_to_logical[left]
        logical_right = self.physical_to_logical[right]
        self.physical_to_logical[left], self.physical_to_logical[right] = logical_right, logical_left
        if logical_left is not None:
            self.logical_to_physical[logical_left] = right
        if logical_right is not None:
            self.logical_to_physical[logical_right] = left

    def _native_cx(self, control: int, target: int) -> None:
        if (control, target) not in self._target_edges:
            self.coupling_violations += 1
        self.native_counts["rz"] += 4
        self.native_counts["sx"] += 2
        self.native_counts["cz"] += 1
        self.global_phase_pi += Fraction(1, 2)
        self.depth_last_layer[target] += 3
        cz_layer = max(self.depth_last_layer[control], self.depth_last_layer[target]) + 1
        self.depth_last_layer[control] = cz_layer
        self.depth_last_layer[target] = cz_layer + 3
        self.used_physical_qubits.update((control, target))
        self.direct_cx_count += 1

    def emit(self, stage: str, opcode: str, qubits: Sequence[int], angle: Fraction | None = None) -> None:
        index = self.instruction_count
        logical = tuple(int(value) for value in qubits)
        physical_before = tuple(self.logical_to_physical[value] for value in logical)
        route: tuple[int, ...] | None = None
        swap_before = self.swap_count

        if opcode == "CX":
            route = self._paths[physical_before[0]][physical_before[1]]
            if route is None:
                raise ValueError(f"Missing V4.6 route for {physical_before}.")
            self.distance_histogram[len(route) - 1] += 1
            for left, right in zip(route[:-2], route[1:-1]):
                self._native_swap(left, right, stage)
            routed_control = self.logical_to_physical[logical[0]]
            routed_target = self.logical_to_physical[logical[1]]
            if (routed_control, routed_target) != (route[-2], route[-1]):
                raise AssertionError("BasicSwap layout update diverged from the frozen path.")
            self._native_cx(routed_control, routed_target)
        elif opcode == "X":
            self.native_counts["x"] += 1
            self._one_qubit_depth(physical_before[0], 1)
        elif opcode == "H":
            self.native_counts["rz"] += 2
            self.native_counts["sx"] += 1
            self.global_phase_pi += Fraction(1, 4)
            self._one_qubit_depth(physical_before[0], 3)
        elif opcode == "T":
            self.native_counts["rz"] += 1
            self.global_phase_pi += Fraction(1, 8)
            self._one_qubit_depth(physical_before[0], 1)
        elif opcode == "TDG":
            self.native_counts["rz"] += 1
            self.global_phase_pi -= Fraction(1, 8)
            self._one_qubit_depth(physical_before[0], 1)
        elif opcode == "RY":
            self.native_counts["rz"] += 3
            self.native_counts["sx"] += 2
            self.global_phase_pi += Fraction(3, 2)
            self._one_qubit_depth(physical_before[0], 5)
        elif opcode == "RZ":
            self.native_counts["rz"] += 1
            self._one_qubit_depth(physical_before[0], 1)
        else:
            self.isa_violations += 1
            raise ValueError(f"Unsupported V4.6 input opcode: {opcode}")

        swap_added = self.swap_count - swap_before
        route_token = ",".join(str(value) for value in route) if route is not None else "-"
        line = (
            f"{index}|{stage}|{opcode}|{','.join(str(value) for value in logical)}|"
            f"{','.join(str(value) for value in physical_before)}|{self._angle_token(angle)}|"
            f"{route_token}|{swap_added}\n"
        ).encode("ascii")
        self._commit_route_record(stage, line)
        super().emit(stage, opcode, logical, angle)

    def finish_routing(self, expected_parent_manifest: Mapping[str, Any]) -> dict[str, Any]:
        input_manifest = super().finish()
        self._close_route_chunk()
        stage_rows = [
            {
                "input_instruction_count": self._route_stage_counts[name],
                "route_record_sha256": self._route_stage_hashers[name].hexdigest(),
                "stage": name,
                "swap_count": self._route_stage_swaps.get(name, 0),
            }
            for name in sorted(self._route_stage_counts)
        ]
        route_core = {
            "chunk_instruction_limit": ROUTE_CHUNK_INSTRUCTIONS,
            "chunk_instruction_sizes": self._route_chunk_sizes,
            "chunk_sha256": self._route_chunk_hashes,
            "input_instruction_count": self.instruction_count,
            "record_contract": "INDEX|STAGE|INPUT_OPCODE|LOGICAL_QUBITS|PHYSICAL_BEFORE|ANGLE|FULL_ORDERED_PATH_OR_DASH|INSERTED_SWAP_COUNT_NEWLINE",
            "route_record_stream_sha256": self._route_stream.hexdigest(),
            "stage_manifests": stage_rows,
        }
        route_ir = {**route_core, "route_ir_sha256": canonical_json_sha256(route_core)}
        phase = self.global_phase_pi % 2
        native_core = {
            "asap_structural_depth": max(self.depth_last_layer),
            "coupling_violations": self.coupling_violations,
            "direct_translated_cx_count": self.direct_cx_count,
            "global_phase_pi_mod_2": f"{phase.numerator}/{phase.denominator}",
            "isa_violations": self.isa_violations,
            "native_basis": ["cz", "id", "rz", "sx", "x"],
            "native_instruction_count": sum(self.native_counts.values()),
            "native_operation_counts": {
                name: self.native_counts.get(name, 0) for name in ("cz", "id", "rz", "sx", "x")
            },
            "native_representation": "EXACT_DETERMINISTICALLY_EXPANDABLE_MACRO_IR_ONE_ROUTE_RECORD_PER_INPUT_INSTRUCTION",
            "swap_count": self.swap_count,
            "translation_equivalence": "EXACT_UNITARY_UP_TO_RECORDED_GLOBAL_PHASE",
        }
        native = {**native_core, "native_ledger_sha256": canonical_json_sha256(native_core)}
        layout_core = {
            "final_logical_to_physical": self.logical_to_physical,
            "final_physical_to_logical": self.physical_to_logical,
            "initial_layout": "TRIVIAL_LOGICAL_Q_TO_PHYSICAL_Q",
            "logical_qubits": self.total_qubits,
            "output_interpretation": "FINAL_LAYOUT_IS_THE_COMES_FROM_PERMUTATION_REQUIRED_TO_INTERPRET_LOGICAL_OUTPUTS",
            "physical_qubits": TARGET_QUBITS,
            "used_physical_qubits": sorted(self.used_physical_qubits),
        }
        layout = {**layout_core, "layout_sha256": canonical_json_sha256(layout_core)}
        routing_core = {
            "distance_histogram_before_each_cx": {
                str(distance): count for distance, count in sorted(self.distance_histogram.items())
            },
            "maximum_distance_before_routing": max(self.distance_histogram, default=0),
            "routing_method": "QISKIT_2_5_2_BASIC_SWAP_FROZEN_ORDERED_SHORTEST_PATH_ORACLE",
            "transpiler_seed": TRANSPILER_SEED,
        }
        routing = {**routing_core, "routing_ledger_sha256": canonical_json_sha256(routing_core)}
        return {
            "input_manifest_exact_parent": input_manifest == dict(expected_parent_manifest),
            "input_stream_manifest": input_manifest,
            "layout": layout,
            "native_ledger": native,
            "route_ir": route_ir,
            "routing_ledger": routing,
        }


def route_seed(
    *,
    seed: int,
    rows: Sequence[Mapping[str, Any]],
    connectivity: Mapping[str, Any],
    parent_row: Mapping[str, Any],
    path_table: list[list[tuple[int, ...] | None]],
    target_edges: set[tuple[int, int]],
    thresholds: Mapping[str, Any],
    progress: Any | None = None,
) -> dict[str, Any]:
    layout = build_layout(rows)
    stream = FullStreamRouter(
        seed=seed,
        total_qubits=layout.total_qubits,
        paths=path_table,
        target_edges=target_edges,
    )
    if progress is not None:
        progress(f"V4.6 · seed {seed} · full binary coin reconstruction")
    emit_binary_coin_rings(stream, layout)
    if progress is not None:
        progress(f"V4.6 · seed {seed} · full streamed SELECT reconstruction and routing")
    emit_binary_selector(stream, rows, layout)
    for rank, bridge in enumerate(connectivity.get("selected_bridges") or [], start=1):
        if progress is not None:
            progress(f"V4.6 · seed {seed} · bridge {rank} reconstruction and routing")
        emit_bridge(stream, bridge=bridge, layout=layout, rank=rank)
    routed = stream.finish_routing(parent_row.get("stream_manifest") or {})
    native = routed["native_ledger"]
    parent_cx = int(((parent_row.get("stream_manifest") or {}).get("elementary_counts") or {}).get("CX", 0))
    routed_cz = int((native.get("native_operation_counts") or {}).get("cz", -1))
    ratio = Fraction(routed_cz, parent_cx)
    maximum_ratio = int(thresholds["maximum_native_cz_expansion_over_v45_cnot"])
    maximum_cz = int(thresholds["maximum_routed_cz_per_seed"])
    maximum_depth = int(thresholds["maximum_routed_depth_per_seed"])
    accepted = bool(
        routed["input_manifest_exact_parent"] is True
        and layout.total_qubits <= TARGET_QUBITS
        and native.get("coupling_violations") == 0
        and native.get("isa_violations") == 0
        and routed_cz <= maximum_cz
        and int(native.get("asap_structural_depth", maximum_depth + 1)) <= maximum_depth
        and ratio <= maximum_ratio
    )
    resource_core = {
        "cz_expansion_ratio_exact": f"{ratio.numerator}/{ratio.denominator}",
        "cz_expansion_ratio_maximum": maximum_ratio,
        "depth_margin": maximum_depth - int(native["asap_structural_depth"]),
        "maximum_routed_cz": maximum_cz,
        "maximum_routed_depth": maximum_depth,
        "routed_cz_margin": maximum_cz - routed_cz,
        "status": "PASS_PREREGISTERED_V45_ROUTING_RESOURCE_GATE" if accepted else "REJECT_PREREGISTERED_V45_ROUTING_RESOURCE_GATE",
        "v45_input_cx": parent_cx,
    }
    resource = {**resource_core, "resource_gate_sha256": canonical_json_sha256(resource_core)}
    core = {
        "instance_id": parent_row.get("instance_id"),
        "logical_qubits": layout.total_qubits,
        "parent_seed_materialization_sha256": parent_row.get("seed_materialization_sha256"),
        "resource_gate": resource,
        "routed_compilation": routed,
        "seed": seed,
        "status": "PASS_FULL_STREAM_STRUCTURAL_AND_RESOURCE_ROUTING" if accepted else "REJECT_FULL_STREAM_ROUTING",
    }
    return {**core, "seed_routing_sha256": canonical_json_sha256(core)}


def build_v46_artifact(*, root: str | Path | None = None, progress: Any | None = None) -> dict[str, Any]:
    paths = _paths(root)
    spec = load_v46_spec(root=paths["root"])
    parent = authenticate_v45_parent(root=paths["root"])
    if parent.get("valid") is not True:
        raise RuntimeError(f"V4.5 parent authentication failed: {parent.get('errors')}")
    path_oracle, path_table = load_path_oracle(root=paths["root"])
    translation = load_translation_contract(root=paths["root"])
    snapshot = read_json_strict(paths["v44_snapshot"])
    target_edges = set(parse_coupling_edges(snapshot))
    v45 = parent.get("artifact") or {}
    parent_rows = {int(row["seed"]): row for row in v45.get("seed_materializations") or []}
    if list(parent_rows) != list(SEEDS):
        raise ValueError("Authenticated V4.5 seed order mismatch.")

    v41 = read_json_strict(paths["v41_artifact"])
    certificates = _certificate_by_seed(paths["root"])
    compressions = {
        int(row["seed"]): row
        for row in (v41.get("compression_evidence") or {}).get("seed_rows") or []
    }
    connectivity = {
        int(row["seed"]): row
        for row in (v41.get("connectivity_evidence") or {}).get("seed_rows") or []
    }
    thresholds = ((v45.get("claim_boundary") or {}) and ((spec.get("inherited_preregistered_resource_contract") or {})))
    if not isinstance(thresholds, Mapping):
        raise ValueError("V4.6 preregistered threshold contract unavailable.")

    if any(name == "qiskit" or name.startswith("qiskit.") or name.startswith("qiskit_ibm_runtime") for name in sys.modules):
        raise RuntimeError("V4.6 confirmatory compiler must run without Qiskit or provider SDK imports.")
    network_attempts: list[str] = []

    def deny_network(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        network_attempts.append("socket")
        raise RuntimeError("V4.6 confirmatory compiler prohibits network access.")

    seed_rows: list[dict[str, Any]] = []
    with mock.patch.object(socket.socket, "connect", deny_network), mock.patch(
        "socket.create_connection", side_effect=deny_network
    ):
        for seed in SEEDS:
            rows = _guarded_rows(certificates[seed], compressions[seed])
            seed_rows.append(
                route_seed(
                    seed=seed,
                    rows=rows,
                    connectivity=connectivity[seed],
                    parent_row=parent_rows[seed],
                    path_table=path_table,
                    target_edges=target_edges,
                    thresholds=thresholds,
                    progress=progress,
                )
            )
    if network_attempts:
        raise RuntimeError(f"Network attempts blocked during V4.6: {network_attempts}")

    all_pass = all(row.get("status") == "PASS_FULL_STREAM_STRUCTURAL_AND_RESOURCE_ROUTING" for row in seed_rows)
    native_ledgers = [((row.get("routed_compilation") or {}).get("native_ledger") or {}) for row in seed_rows]
    aggregate_core = {
        "all_eight_input_streams_exact_v45": all(((row.get("routed_compilation") or {}).get("input_manifest_exact_parent") is True) for row in seed_rows),
        "all_eight_preregistered_resource_gates_pass": all(((row.get("resource_gate") or {}).get("status") == "PASS_PREREGISTERED_V45_ROUTING_RESOURCE_GATE") for row in seed_rows),
        "all_eight_structural_routes_pass": all_pass,
        "aggregate_native_cz": sum(int((ledger.get("native_operation_counts") or {}).get("cz", 0)) for ledger in native_ledgers),
        "aggregate_native_instructions": sum(int(ledger.get("native_instruction_count", 0)) for ledger in native_ledgers),
        "aggregate_swaps": sum(int(ledger.get("swap_count", 0)) for ledger in native_ledgers),
        "maximum_logical_qubits": max(int(row.get("logical_qubits", 0)) for row in seed_rows),
        "maximum_native_cz": max(int((ledger.get("native_operation_counts") or {}).get("cz", 0)) for ledger in native_ledgers),
        "maximum_routed_depth": max(int(ledger.get("asap_structural_depth", 0)) for ledger in native_ledgers),
        "minimum_logical_capacity_margin": min(TARGET_QUBITS - int(row.get("logical_qubits", TARGET_QUBITS + 1)) for row in seed_rows),
        "ordered_route_ir_root_sha256": canonical_json_sha256([((row.get("routed_compilation") or {}).get("route_ir") or {}).get("route_ir_sha256") for row in seed_rows]),
        "ordered_seed_routing_root_sha256": canonical_json_sha256([row.get("seed_routing_sha256") for row in seed_rows]),
        "seed_count": len(seed_rows),
        "total_input_instructions": sum(int((((row.get("routed_compilation") or {}).get("input_stream_manifest") or {}).get("instruction_count", 0))) for row in seed_rows),
    }
    aggregate = {**aggregate_core, "aggregate_sha256": canonical_json_sha256(aggregate_core)}
    if all_pass:
        overall = "V46_FAKEMARRAKESH_FULL_STREAM_ROUTING_PASSED_STRUCTURAL_AND_PREREGISTERED_RESOURCE_GATES"
        next_gate = "PINNED_DATED_PROPERTIES_DURATION_ERROR_AND_OPTIMIZATION_FEASIBILITY_OF_V46_ROUTED_STREAMS"
    else:
        overall = "V46_FAKEMARRAKESH_FULL_STREAM_ROUTING_REJECTED"
        next_gate = "REPAIR_OR_REDESIGN_V46_ROUTING_ARCHITECTURE"
    core = {
        "aggregate": aggregate,
        "artifact_version": ARTIFACT_VERSION,
        "claim_boundary": copy.deepcopy(spec["claim_boundary"]),
        "decisions": {
            "full_stream_routing": "PASSED_ALL_EIGHT_ZERO_ISA_AND_COUPLING_VIOLATIONS" if all_pass else "REJECTED",
            "next_falsifiable_gate": next_gate,
            "overall": overall,
            "production_admission": "OFFLINE_STRUCTURAL_COMPILATION_ONLY_HARDWARE_EXECUTION_REJECTED",
            "resource_gate": "PASSED_INHERITED_V45_PREREGISTERED_LIMITS_ALL_EIGHT" if all_pass else "REJECTED_INHERITED_V45_PREREGISTERED_LIMITS",
        },
        "parent": {
            "artifact_raw_file_sha256": EXPECTED_V45_ARTIFACT_RAW_SHA256,
            "artifact_sha256": EXPECTED_V45_ARTIFACT_SHA256,
            "freeze_raw_file_sha256": EXPECTED_V45_FREEZE_RAW_SHA256,
            "freeze_sha256": EXPECTED_V45_FREEZE_SHA256,
            "immutable_file_count": parent["immutable_file_count"],
            "immutable_files_exact": parent["immutable_files_exact"],
            "overall_decision": ((parent.get("artifact") or {}).get("decisions") or {}).get("overall"),
        },
        "reference_contracts": {
            "path_oracle_raw_file_sha256": EXPECTED_PATH_ORACLE_RAW_SHA256,
            "path_oracle_sha256": path_oracle.get("path_oracle_sha256"),
            "translation_contract_raw_file_sha256": EXPECTED_TRANSLATION_RAW_SHA256,
            "translation_contract_sha256": translation.get("translation_contract_sha256"),
        },
        "research_classification": "RESEARCH_ONLY",
        "seed_routings": seed_rows,
        "source_raw_file_sha256": raw_file_sha256(paths["source"]),
        "independent_checker_raw_file_sha256": raw_file_sha256(paths["checker"]),
        "spec_raw_file_sha256": EXPECTED_SPEC_RAW_SHA256,
        "spec_sha256": EXPECTED_SPEC_SHA256,
        "v46_version": V46_VERSION,
    }
    candidate = {**core, "artifact_sha256": canonical_json_sha256(core)}
    from .phase3_v46_independent_checker import validate_v46_artifact

    report = validate_v46_artifact(candidate, root=paths["root"], authenticate_parent=False)
    if report.get("valid") is not True:
        raise RuntimeError(f"Independent V4.6 checker rejected the candidate: {report}")
    return candidate


def seal_v46_artifact(*, root: str | Path | None = None, output: str | Path | None = None) -> dict[str, Any]:
    paths = _paths(root)
    artifact = build_v46_artifact(root=paths["root"], progress=lambda message: print(message, flush=True))
    target = Path(output) if output is not None else paths["artifact"]
    if not target.is_absolute():
        target = paths["root"] / target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(artifact, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return {
        "artifact": str(target),
        "artifact_raw_file_sha256": raw_file_sha256(target),
        "artifact_sha256": artifact["artifact_sha256"],
        "overall": (artifact.get("decisions") or {}).get("overall"),
    }


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=None)
    parser.add_argument("--output", default=None)
    args = parser.parse_args(argv)
    print(json.dumps(seal_v46_artifact(root=args.root, output=args.output), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "ARTIFACT_VERSION",
    "DEFAULT_ARTIFACT_NAME",
    "EXPECTED_PATH_ORACLE_RAW_SHA256",
    "EXPECTED_PATH_ORACLE_SHA256",
    "EXPECTED_SPEC_RAW_SHA256",
    "EXPECTED_SPEC_SHA256",
    "EXPECTED_TRANSLATION_RAW_SHA256",
    "EXPECTED_TRANSLATION_SHA256",
    "FullStreamRouter",
    "SPEC_FILENAME",
    "V46_VERSION",
    "authenticate_v45_parent",
    "build_v46_artifact",
    "canonical_json_sha256",
    "load_path_oracle",
    "load_translation_contract",
    "load_v46_spec",
    "raw_file_sha256",
    "read_json_strict",
    "route_seed",
    "seal_v46_artifact",
]
