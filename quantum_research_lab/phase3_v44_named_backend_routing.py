"""Quantum Lab V4.4 named offline-backend zero-job routing protocol.

V4.4 authenticates the complete V4.3 release, projects the pinned structural
configuration of ``FakeMarrakesh`` into a Qiskit ``Target`` and evaluates the
frozen capacity rule before attempting any full-workload transpilation.  The
V4.3 circuit widths are all greater than the target's 156 physical qubits, so
the full workload is rejected before circuit reconstruction, translation or
routing.  Small deterministic canaries exercise the pinned Qiskit translation
and routing mechanics; they are explicitly not evidence for the rejected full
workload.

The module imports Qiskit lazily only for an explicit canary replay or artifact
seal.  Loading and authenticating the deployed artifact remains dependency
free.  It imports no provider service, reads no credentials, performs no
network operation and submits no simulator or QPU job.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import socket
import subprocess
import sys
from typing import Any, Mapping, Sequence
from unittest import mock


V44_VERSION = "PHASE III · V4.4 NAMED OFFLINE BACKEND ZERO-JOB ROUTING · V1"
ARTIFACT_VERSION = "PHASE III · V4.4 SEALED NAMED-BACKEND ZERO-JOB NEGATIVE RESULT · V1"
SPEC_FILENAME = "PHASE_III_V4_4_NAMED_BACKEND_ZERO_JOB_ROUTING_SPEC_V1.json"
SNAPSHOT_FILENAME = "PHASE_III_V4_4_FROZEN_BACKEND_SNAPSHOT_V1.json"
TOOLCHAIN_FILENAME = "PHASE_III_V4_4_TOOLCHAIN_MANIFEST_V1.json"
DEFAULT_ARTIFACT_NAME = "SEALED_V4_4_NAMED_BACKEND_ZERO_JOB_ARTIFACT.json"

EXPECTED_SPEC_SHA256 = "3cd04dee5a8cc5ce760c9fcf1fabd116841356641ffbab1a0727fcdfd26bae52"
EXPECTED_SPEC_RAW_SHA256 = "634530aa6b2e4f770fb960f571e1f1f96b66f300dd2172fc07f91979a558c9f9"
EXPECTED_SNAPSHOT_SHA256 = "3a604026627653e697fba1b2b9b06d84298a13ca7a7f2c2f9f2ed551bdbfdaf3"
EXPECTED_SNAPSHOT_RAW_SHA256 = "816814f383c7b9890a137ead7799c28f3fbfc0cac188ab274dfb65050e2b7fbd"
EXPECTED_TOOLCHAIN_SHA256 = "4077ec3268c80eace3cc7f96e7b1db4be052dce07d8ab659563cd566738e2860"
EXPECTED_TOOLCHAIN_RAW_SHA256 = "d95ad52fdd53d8f5711d338270a12e5203c3f62eeebad36e6e7d27e2c2ccff15"

EXPECTED_V43_FREEZE_RAW_SHA256 = "950dc3eb7c9887bff7d7c6516942389fccb77f753291a158d18f407fea17efd7"
EXPECTED_V43_FREEZE_SHA256 = "d058a2545e8a9e4788360663d36ae7f451e1fe126c290d60d173910b83441a49"
EXPECTED_V43_PATH_FINGERPRINT = "3bc4c8805cf38d5e55c8cc4d1c99cfc3950f9b7faa2cb85fa891fb42987467fc"
EXPECTED_V43_ARTIFACT_RAW_SHA256 = "626123fda2ee6561fe74cbb073a03f9987ccbd4e3d01c84b4f2815023e8271e3"
EXPECTED_V43_ARTIFACT_SHA256 = "36a7a63410da87ce7f98bb10e6d3af3c3d784d9f8e520a6771e42cda9ee593ce"

EXPECTED_SEEDS = (1103, 2207, 3301, 4409, 5501, 6607, 7703, 8807)
EXPECTED_WIDTHS = (330, 331, 327, 328, 329, 331, 339, 334)
TARGET_QUBITS = 156
PERSISTENT_REGISTER_FLOOR = 160
TARGET_BASIS = ("cz", "id", "rz", "sx", "x")
TRANSPILER_SEED = 4404
V43_SUCCESSOR_MUTABLE = frozenset(
    {"quantum_research_lab/README.md", "quantum_research_lab/ui.py"}
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
        "spec": base / "quantum_research_lab" / SPEC_FILENAME,
        "snapshot": base / "quantum_research_lab" / SNAPSHOT_FILENAME,
        "toolchain": base / "quantum_research_lab" / TOOLCHAIN_FILENAME,
        "source": base / "quantum_research_lab" / "phase3_v44_named_backend_routing.py",
        "parent_freeze": base / "FREEZE_CONTRACT_V4_3.json",
        "parent_artifact": base / "outputs/quantum_phase3/v43_reversible_circuit/SEALED_V4_3_REVERSIBLE_CIRCUIT_ARTIFACT.json",
        "artifact": base / "outputs/quantum_phase3/v44_named_backend" / DEFAULT_ARTIFACT_NAME,
    }


def _path_fingerprint(paths: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(sorted(paths), separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _load_self_hashed(
    path: Path,
    *,
    raw_sha256: str,
    semantic_sha256: str,
    hash_fields: Sequence[str],
) -> dict[str, Any]:
    if raw_file_sha256(path) != raw_sha256:
        raise ValueError(f"Raw identity mismatch: {path.name}")
    payload = read_json_strict(path)
    core = {key: value for key, value in payload.items() if key not in set(hash_fields)}
    digest = canonical_json_sha256(core)
    if digest != semantic_sha256:
        raise ValueError(f"Semantic identity mismatch: {path.name}")
    if not all(payload.get(field) in {digest, digest[:20].upper()} for field in hash_fields):
        raise ValueError(f"Registered self-hash mismatch: {path.name}")
    return payload


def load_v44_spec(path: str | Path | None = None, *, root: str | Path | None = None) -> dict[str, Any]:
    target = Path(path) if path is not None else _paths(root)["spec"]
    payload = _load_self_hashed(
        target,
        raw_sha256=EXPECTED_SPEC_RAW_SHA256,
        semantic_sha256=EXPECTED_SPEC_SHA256,
        hash_fields=("v44_spec_sha", "v44_spec_sha256"),
    )
    chronology = payload.get("chronology") or {}
    boundary = payload.get("claim_boundary") or {}
    if not (
        chronology.get("result_state_at_seal") == "NOT_EVALUATED"
        and boundary.get("research_classification") == "RESEARCH_ONLY"
        and boundary.get("provider_calls") == 0
        and boundary.get("network_calls") == 0
        and boundary.get("qpu_jobs_submitted") == 0
        and boundary.get("hardware_executable") is False
        and boundary.get("quantum_advantage") == "NOT_CLAIMED"
    ):
        raise ValueError("V4.4 specification chronology or claim boundary mismatch.")
    return payload


def load_v44_snapshot(path: str | Path | None = None, *, root: str | Path | None = None) -> dict[str, Any]:
    target = Path(path) if path is not None else _paths(root)["snapshot"]
    payload = _load_self_hashed(
        target,
        raw_sha256=EXPECTED_SNAPSHOT_RAW_SHA256,
        semantic_sha256=EXPECTED_SNAPSHOT_SHA256,
        hash_fields=("snapshot_sha256",),
    )
    target_data = payload.get("target") or {}
    boundary = payload.get("evidence_boundary") or {}
    edges = parse_coupling_edges(payload)
    if not (
        (payload.get("identity") or {}).get("target_kind") == "PINNED_OFFLINE_FAKE_BACKEND_SNAPSHOT"
        and target_data.get("num_qubits") == TARGET_QUBITS
        and target_data.get("basis_gates") == list(TARGET_BASIS)
        and target_data.get("directed_coupling_edge_count") == len(edges) == 352
        and boundary.get("snapshot_is_current_hardware_evidence") is False
        and boundary.get("network_calls") == 0
        and boundary.get("provider_jobs_submitted") == 0
        and boundary.get("hardware_executable") is False
    ):
        raise ValueError("V4.4 offline target snapshot contract mismatch.")
    return payload


def load_v44_toolchain(path: str | Path | None = None, *, root: str | Path | None = None) -> dict[str, Any]:
    target = Path(path) if path is not None else _paths(root)["toolchain"]
    payload = _load_self_hashed(
        target,
        raw_sha256=EXPECTED_TOOLCHAIN_RAW_SHA256,
        semantic_sha256=EXPECTED_TOOLCHAIN_SHA256,
        hash_fields=("manifest_sha256",),
    )
    transpilation = payload.get("canary_transpilation_contract") or {}
    boundary = payload.get("provider_boundary") or {}
    if not (
        (payload.get("environment") or {}).get("qiskit") == "2.5.2"
        and transpilation.get("optimization_level") == 0
        and transpilation.get("layout_method") == "trivial"
        and transpilation.get("routing_method") == "basic"
        and transpilation.get("translation_method") == "translator"
        and transpilation.get("seed_transpiler") == TRANSPILER_SEED
        and boundary.get("provider_client_instantiated") is False
        and boundary.get("runtime_service_imported_by_confirmatory_runner") is False
        and boundary.get("network_calls") == 0
        and boundary.get("qpu_jobs_submitted") == 0
    ):
        raise ValueError("V4.4 pinned toolchain contract mismatch.")
    return payload


def authenticate_v43_parent(*, root: str | Path | None = None) -> dict[str, Any]:
    """Authenticate V4.3 and exactly its 191 successor-immutable paths."""

    paths = _paths(root)
    errors: list[str] = []
    try:
        freeze_path = paths["parent_freeze"]
        freeze = read_json_strict(freeze_path)
        frozen = freeze.get("frozen_files") or {}
        freeze_core = {key: value for key, value in freeze.items() if key != "freeze_contract_sha256"}
        freeze_valid = bool(
            raw_file_sha256(freeze_path) == EXPECTED_V43_FREEZE_RAW_SHA256
            and canonical_json_sha256(freeze_core) == freeze.get("freeze_contract_sha256") == EXPECTED_V43_FREEZE_SHA256
            and isinstance(frozen, dict)
            and len(frozen) == freeze.get("frozen_file_count") == 193
            and _path_fingerprint(frozen) == freeze.get("frozen_paths_fingerprint_sha256") == EXPECTED_V43_PATH_FINGERPRINT
        )
    except Exception as exc:
        freeze = {}
        frozen = {}
        freeze_valid = False
        errors.append(f"V4.3 freeze authentication failed: {exc}")
    if not freeze_valid:
        errors.append("V4.3 freeze raw, semantic or inventory identity mismatch.")

    immutable = {
        str(relative): str(expected)
        for relative, expected in frozen.items()
        if str(relative) not in V43_SUCCESSOR_MUTABLE
    } if isinstance(frozen, Mapping) else {}
    mismatches: list[str] = []
    for relative, expected in sorted(immutable.items()):
        candidate = paths["root"] / relative
        if not candidate.is_file() or candidate.is_symlink() or raw_file_sha256(candidate) != expected:
            mismatches.append(relative)
    if len(immutable) != 191 or mismatches:
        errors.append(f"V4.3 immutable path authentication failed: count={len(immutable)} mismatches={mismatches[:5]}")

    try:
        artifact_path = paths["parent_artifact"]
        artifact = read_json_strict(artifact_path)
        artifact_core = {key: value for key, value in artifact.items() if key != "artifact_sha256"}
        artifact_valid = bool(
            raw_file_sha256(artifact_path) == EXPECTED_V43_ARTIFACT_RAW_SHA256
            and canonical_json_sha256(artifact_core) == artifact.get("artifact_sha256") == EXPECTED_V43_ARTIFACT_SHA256
            and (artifact.get("decisions") or {}).get("overall")
            == "V43_BACKEND_AGNOSTIC_CIRCUIT_MATERIALIZED_PROMISE_SIMULATION_PASSED"
        )
    except Exception as exc:
        artifact = {}
        artifact_valid = False
        errors.append(f"V4.3 artifact authentication failed: {exc}")
    if not artifact_valid:
        errors.append("V4.3 artifact raw or semantic identity mismatch.")

    return {
        "artifact": artifact,
        "errors": list(dict.fromkeys(errors)),
        "freeze": freeze,
        "freeze_raw_file_sha256": EXPECTED_V43_FREEZE_RAW_SHA256 if freeze_valid else None,
        "freeze_sha256": EXPECTED_V43_FREEZE_SHA256 if freeze_valid else None,
        "immutable_file_count": len(immutable),
        "immutable_files_exact": len(immutable) == 191 and not mismatches,
        "valid": not errors,
    }


def parse_coupling_edges(snapshot: Mapping[str, Any]) -> tuple[tuple[int, int], ...]:
    compact = str((snapshot.get("target") or {}).get("directed_coupling_edges_compact", ""))
    edges: list[tuple[int, int]] = []
    for token in compact.split(","):
        if not token:
            continue
        left, separator, right = token.partition(">")
        if separator != ">":
            raise ValueError(f"Malformed coupling token: {token}")
        edge = (int(left), int(right))
        if edge[0] == edge[1] or min(edge) < 0 or max(edge) >= TARGET_QUBITS:
            raise ValueError(f"Invalid coupling edge: {edge}")
        edges.append(edge)
    if len(edges) != len(set(edges)):
        raise ValueError("Duplicate directed coupling edge rejected.")
    return tuple(edges)


def capacity_precheck(*, root: str | Path | None = None) -> dict[str, Any]:
    parent = authenticate_v43_parent(root=root)
    if parent.get("valid") is not True:
        raise ValueError("Cannot evaluate V4.4 capacity against an unauthenticated V4.3 parent.")
    rows = (parent.get("artifact") or {}).get("seed_materializations") or []
    if [row.get("seed") for row in rows] != list(EXPECTED_SEEDS):
        raise ValueError("V4.3 seed order mismatch.")
    results: list[dict[str, Any]] = []
    for row, expected_width in zip(rows, EXPECTED_WIDTHS):
        width = int(((row.get("register_layout") or {}).get("total_qubits")) or -1)
        if width != expected_width:
            raise ValueError(f"V4.3 logical width mismatch for seed {row.get('seed')}.")
        core = {
            "backend_capacity_qubits": TARGET_QUBITS,
            "capacity_deficit_qubits": TARGET_QUBITS - width,
            "capacity_fit": False,
            "full_workload_circuit_reconstruction": "NOT_RUN_CAPACITY_PRECHECK_REJECTED",
            "full_workload_native_gate_counts": "NOT_RUN_CAPACITY_PRECHECK_REJECTED",
            "full_workload_routed_depth": "NOT_RUN_CAPACITY_PRECHECK_REJECTED",
            "full_workload_routing": "NOT_RUN_CAPACITY_PRECHECK_REJECTED",
            "full_workload_scheduling": "NOT_RUN_CAPACITY_PRECHECK_REJECTED",
            "full_workload_transpilation": "NOT_RUN_CAPACITY_PRECHECK_REJECTED",
            "instance_id": row.get("instance_id"),
            "logical_qubits": width,
            "seed": row.get("seed"),
            "status": "REJECTED_LOGICAL_WIDTH_EXCEEDS_156_QUBIT_TARGET",
        }
        results.append({**core, "capacity_row_sha256": canonical_json_sha256(core)})
    floor = {
        "backend_capacity_qubits": TARGET_QUBITS,
        "capacity_deficit_qubits": TARGET_QUBITS - PERSISTENT_REGISTER_FLOOR,
        "persistent_registers": {"ADD_COIN": 40, "DATA": 40, "REMOVE_COIN": 40, "TARGET": 40},
        "persistent_register_floor_qubits": PERSISTENT_REGISTER_FLOOR,
        "status": "REJECTED_BEFORE_SCRATCH_THE_PERSISTENT_REGISTER_FLOOR_EXCEEDS_TARGET",
    }
    core = {
        "all_eight_full_workloads_rejected_before_transpilation": True,
        "backend_capacity_qubits": TARGET_QUBITS,
        "capacity_deficit_definition": "BACKEND_CAPACITY_MINUS_LOGICAL_QUBITS",
        "capacity_rows": results,
        "full_workload_routing_attempts": 0,
        "full_workload_transpilation_attempts": 0,
        "maximum_capacity_deficit_qubits": min(row["capacity_deficit_qubits"] for row in results),
        "maximum_logical_qubits": max(row["logical_qubits"] for row in results),
        "minimum_logical_qubits": min(row["logical_qubits"] for row in results),
        "persistent_register_floor": floor,
        "rejected_seed_count": len(results),
        "seed_count": len(results),
    }
    return {**core, "capacity_precheck_sha256": canonical_json_sha256(core)}


def _make_target(snapshot: Mapping[str, Any]) -> Any:
    from qiskit.circuit import Parameter
    from qiskit.circuit.library import CZGate, IGate, RZGate, SXGate, XGate
    from qiskit.transpiler import Target

    target = Target(num_qubits=TARGET_QUBITS, dt=float((snapshot.get("target") or {}).get("dt_seconds")))
    one_qubit = {(qubit,): None for qubit in range(TARGET_QUBITS)}
    target.add_instruction(IGate(), one_qubit)
    target.add_instruction(XGate(), one_qubit)
    target.add_instruction(SXGate(), one_qubit)
    target.add_instruction(RZGate(Parameter("theta")), one_qubit)
    target.add_instruction(CZGate(), {edge: None for edge in parse_coupling_edges(snapshot)})
    return target


def _emit_coin_edge(circuit: Any, q0: int, q1: int) -> None:
    circuit.rz(-math.pi / 2, q1)
    circuit.h(q1)
    circuit.rz(math.pi / 2, q1)
    circuit.h(q1)
    circuit.rz(math.pi / 2, q1)
    circuit.rz(math.pi / 2, q0)
    circuit.cx(q1, q0)
    circuit.ry(-math.pi / 4, q1)
    circuit.ry(-math.pi / 4, q0)
    circuit.cx(q1, q0)
    circuit.rz(-math.pi / 2, q0)
    circuit.rz(-math.pi / 2, q1)
    circuit.h(q1)
    circuit.rz(-math.pi / 2, q1)
    circuit.h(q1)
    circuit.rz(math.pi / 2, q1)


def _canary_circuits() -> tuple[tuple[str, Any, str], ...]:
    from qiskit import QuantumCircuit

    isa = QuantumCircuit(3, name="ISA_TRANSLATION_3Q")
    isa.h(0)
    isa.t(0)
    isa.ry(math.pi / 7, 1)
    isa.cx(0, 1)
    isa.cx(1, 2)
    isa.rz(math.pi / 11, 2)
    isa.x(2)

    arithmetic = QuantumCircuit(5, name="REVERSIBLE_ARITHMETIC_MCX_5Q")
    arithmetic.ccx(0, 1, 2)
    arithmetic.mcx([0, 1, 2, 3], 4)

    remove_ring = QuantumCircuit(40, name="REMOVE_COIN_RING_40Q")
    for edge in range(40):
        _emit_coin_edge(remove_ring, edge, (edge + 1) % 40)

    dual_ring = QuantumCircuit(80, name="DUAL_COIN_RINGS_80Q")
    for offset in (0, 40):
        for edge in range(40):
            _emit_coin_edge(dual_ring, offset + edge, offset + ((edge + 1) % 40))

    capacity = QuantumCircuit(TARGET_QUBITS, name="EXACT_CAPACITY_BOUNDARY_156Q")
    for qubit in range(TARGET_QUBITS):
        capacity.x(qubit)

    return (
        ("ISA_TRANSLATION_3Q", isa, "TRANSLATION_ONLY_ON_CONNECTED_THREE_QUBIT_PATH"),
        ("REVERSIBLE_ARITHMETIC_MCX_5Q", arithmetic, "TOFFOLI_AND_FOUR_CONTROL_X_TRANSLATION_ROUTING_MOTIF"),
        ("REMOVE_COIN_RING_40Q", remove_ring, "ONE_LITERAL_V4_3_XX_PLUS_YY_COIN_RING"),
        ("DUAL_COIN_RINGS_80Q", dual_ring, "BOTH_LITERAL_V4_3_COIN_RINGS_WITHOUT_DATA_TARGET_OR_SCRATCH"),
        ("EXACT_CAPACITY_BOUNDARY_156Q", capacity, "TARGET_WIDTH_BOUNDARY_ONLY"),
    )


def _parameter_token(value: Any) -> str:
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError("Non-finite transpiled parameter rejected.")
    if numeric == 0.0:
        numeric = 0.0
    return format(numeric, ".17g")


def _canonical_circuit_result(name: str, purpose: str, source: Any, output: Any, snapshot: Mapping[str, Any]) -> dict[str, Any]:
    target_edges = set(parse_coupling_edges(snapshot))
    lines: list[str] = []
    used: set[int] = set()
    isa_valid = True
    coupling_valid = True
    for index, instruction in enumerate(output.data):
        operation = instruction.operation
        qubits = tuple(output.find_bit(qubit).index for qubit in instruction.qubits)
        used.update(qubits)
        parameters = tuple(_parameter_token(value) for value in operation.params)
        lines.append(
            f"{index}|{operation.name}|{','.join(str(value) for value in qubits)}|{','.join(parameters) or '-'}\n"
        )
        isa_valid = isa_valid and operation.name in TARGET_BASIS
        if len(qubits) == 2:
            coupling_valid = coupling_valid and qubits in target_edges and operation.name == "cz"
        elif len(qubits) != 1:
            isa_valid = False
    counts = {str(key): int(value) for key, value in sorted(output.count_ops().items())}
    global_phase = _parameter_token(output.global_phase)
    stream_sha256 = hashlib.sha256("".join(lines).encode("ascii")).hexdigest()
    core = {
        "canary": name,
        "coupling_valid": coupling_valid,
        "input_depth": int(source.depth()),
        "input_instruction_count": int(source.size()),
        "input_logical_qubits": int(source.num_qubits),
        "isa_valid": isa_valid,
        "output_depth": int(output.depth()),
        "output_global_phase_radians": global_phase,
        "output_instruction_count": int(output.size()),
        "output_num_qubits": int(output.num_qubits),
        "output_operation_counts": counts,
        "output_stream_sha256": stream_sha256,
        "purpose": purpose,
        "status": "PASS" if isa_valid and coupling_valid else "FAIL",
        "used_physical_qubits": sorted(used),
    }
    return {**core, "canary_result_sha256": canonical_json_sha256(core)}


def _blocked_network(*args: Any, **kwargs: Any) -> Any:
    del args, kwargs
    raise RuntimeError("V4.4 confirmatory canary runner prohibits network access.")


def run_canary_bundle(*, root: str | Path | None = None) -> dict[str, Any]:
    """Run all canaries locally without provider objects, simulators or jobs."""

    snapshot = load_v44_snapshot(root=root)
    toolchain = load_v44_toolchain(root=root)
    network_attempts: list[str] = []

    def deny_connect(*args: Any, **kwargs: Any) -> Any:
        network_attempts.append("socket.connect")
        return _blocked_network(*args, **kwargs)

    with mock.patch.object(socket.socket, "connect", deny_connect), mock.patch(
        "socket.create_connection", side_effect=_blocked_network
    ):
        import qiskit
        from qiskit import QuantumCircuit
        from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager

        if str(qiskit.__version__) != str((toolchain.get("environment") or {}).get("qiskit")):
            raise RuntimeError(
                f"Pinned Qiskit version required: {(toolchain.get('environment') or {}).get('qiskit')}; got {qiskit.__version__}"
            )
        target = _make_target(snapshot)
        results: list[dict[str, Any]] = []
        for name, circuit, purpose in _canary_circuits():
            manager = generate_preset_pass_manager(
                optimization_level=0,
                target=target,
                layout_method="trivial",
                routing_method="basic",
                translation_method="translator",
                seed_transpiler=TRANSPILER_SEED,
            )
            output = manager.run(circuit)
            results.append(_canonical_circuit_result(name, purpose, circuit, output, snapshot))

        overflow = QuantumCircuit(TARGET_QUBITS + 1, name="CAPACITY_OVERFLOW_157Q")
        for qubit in range(TARGET_QUBITS + 1):
            overflow.x(qubit)
        manager = generate_preset_pass_manager(
            optimization_level=0,
            target=target,
            layout_method="trivial",
            routing_method="basic",
            translation_method="translator",
            seed_transpiler=TRANSPILER_SEED,
        )
        try:
            manager.run(overflow)
        except Exception as exc:
            rejection = {
                "canary": "CAPACITY_OVERFLOW_157Q",
                "exception_class": type(exc).__name__,
                "input_logical_qubits": TARGET_QUBITS + 1,
                "message_contract": "NUMBER_OF_QUBITS_GREATER_THAN_DEVICE",
                "status": "EXPECTED_REJECTION" if type(exc).__name__ == "TranspilerError" and "Number of qubits greater than device" in str(exc) else "UNEXPECTED_REJECTION",
            }
        else:
            rejection = {
                "canary": "CAPACITY_OVERFLOW_157Q",
                "exception_class": None,
                "input_logical_qubits": TARGET_QUBITS + 1,
                "message_contract": "NUMBER_OF_QUBITS_GREATER_THAN_DEVICE",
                "status": "UNEXPECTED_ACCEPTANCE",
            }
        rejection["canary_result_sha256"] = canonical_json_sha256(rejection)

    result_hashes = [row["canary_result_sha256"] for row in results] + [rejection["canary_result_sha256"]]
    core = {
        "accepted_canary_count": len(results),
        "accepted_canaries": results,
        "all_accepted_canaries_isa_and_coupling_valid": all(
            row.get("status") == "PASS" and row.get("isa_valid") is True and row.get("coupling_valid") is True
            for row in results
        ),
        "backend_run_calls": 0,
        "canonical_result_root_sha256": canonical_json_sha256(result_hashes),
        "credential_reads": 0,
        "full_workload_circuits_constructed": 0,
        "local_simulator_jobs_submitted": 0,
        "mandatory_negative_canary": rejection,
        "network_attempts": len(network_attempts),
        "network_calls": 0,
        "provider_calls": 0,
        "provider_sdk_imported": False,
        "qiskit_version": str(qiskit.__version__),
        "qpu_jobs_submitted": 0,
        "snapshot_sha256": snapshot.get("snapshot_sha256"),
        "status": "PASS" if all(row.get("status") == "PASS" for row in results) and rejection.get("status") == "EXPECTED_REJECTION" and not network_attempts else "FAIL",
        "target_basis": list(TARGET_BASIS),
        "target_directed_coupling_edges": len(parse_coupling_edges(snapshot)),
        "target_qubits": TARGET_QUBITS,
        "toolchain_manifest_sha256": toolchain.get("manifest_sha256"),
    }
    return {**core, "canary_bundle_sha256": canonical_json_sha256(core)}


def _clean_environment(root: Path) -> dict[str, str]:
    environment = os.environ.copy()
    for key in tuple(environment):
        upper = key.upper()
        if any(token in upper for token in ("IBM_QUANTUM", "QISKIT_IBM", "QISKIT_TOKEN", "API_TOKEN")):
            environment.pop(key, None)
    environment["PYTHONPATH"] = str(root)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return environment


def _clean_process_canary(root: Path) -> dict[str, Any]:
    command = [
        sys.executable,
        "-m",
        "quantum_research_lab.phase3_v44_named_backend_routing",
        "--root",
        str(root),
        "--canary-json",
    ]
    completed = subprocess.run(
        command,
        cwd=root,
        env=_clean_environment(root),
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"V4.4 clean-process canary failed: {completed.stderr.strip()[-2000:]}")
    payload = json.loads(completed.stdout)
    if not isinstance(payload, dict) or payload.get("status") != "PASS":
        raise RuntimeError(f"V4.4 clean-process canary did not pass: {payload}")
    return payload


def build_v44_artifact(*, root: str | Path | None = None, replay_bundles: Sequence[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    paths = _paths(root)
    parent = authenticate_v43_parent(root=paths["root"])
    if parent.get("valid") is not True:
        raise RuntimeError(f"V4.3 parent authentication failed: {parent.get('errors')}")
    spec = load_v44_spec(root=paths["root"])
    snapshot = load_v44_snapshot(root=paths["root"])
    toolchain = load_v44_toolchain(root=paths["root"])
    capacity = capacity_precheck(root=paths["root"])
    bundles = list(replay_bundles) if replay_bundles is not None else [
        _clean_process_canary(paths["root"]),
        _clean_process_canary(paths["root"]),
    ]
    if len(bundles) != 2:
        raise ValueError("Exactly two clean-process replay bundles are required.")
    replay_hashes = [str(bundle.get("canary_bundle_sha256")) for bundle in bundles]
    replay_stable = bool(
        replay_hashes[0] == replay_hashes[1]
        and all(bundle.get("status") == "PASS" for bundle in bundles)
    )
    if not replay_stable:
        raise RuntimeError(f"V4.4 canary replay mismatch: {replay_hashes}")
    canary_evidence = {
        "canonical_canary_bundle": dict(bundles[0]),
        "clean_process_replay_count": 2,
        "clean_process_replay_sha256": replay_hashes,
        "replay_stable": replay_stable,
        "scope_boundary": "CANARY_SUCCESS_VALIDATES_ONLY_PINNED_TOOLCHAIN_MECHANICS_NOT_THE_REJECTED_FULL_WORKLOAD",
    }
    canary_evidence["canary_evidence_sha256"] = canonical_json_sha256(canary_evidence)

    parent_artifact = parent.get("artifact") or {}
    core = {
        "artifact_version": ARTIFACT_VERSION,
        "canary_evidence": canary_evidence,
        "capacity_precheck": capacity,
        "claim_boundary": {
            "backend_name": "fake_marrakesh",
            "backend_selection_kind": "PINNED_OFFLINE_FAKE_BACKEND_SNAPSHOT",
            "calibration_aware_fidelity": "NOT_TESTED",
            "credential_reads": 0,
            "full_workload_native_gate_counts": "NOT_RUN_CAPACITY_PRECHECK_REJECTED",
            "full_workload_routed_depth": "NOT_RUN_CAPACITY_PRECHECK_REJECTED",
            "full_workload_routing": "NOT_RUN_CAPACITY_PRECHECK_REJECTED",
            "full_workload_transpilation": "NOT_RUN_CAPACITY_PRECHECK_REJECTED",
            "hardware_executable": False,
            "network_calls": 0,
            "optimization_performance": "NOT_TESTED",
            "provider_calls": 0,
            "provider_credentials_read": False,
            "provider_sdk_imported": False,
            "qpu_jobs_submitted": 0,
            "qpu_submission_enabled": False,
            "quantum_advantage": "NOT_CLAIMED",
            "snapshot_is_current_hardware_evidence": False,
        },
        "decisions": {
            "canary_toolchain": "VALIDATED_ON_FIVE_ACCEPTED_CANARIES_AND_ONE_157Q_NEGATIVE_CONTROL",
            "full_workload": "REJECTED_AT_CAPACITY_PRECHECK_BEFORE_TRANSPILATION_AND_ROUTING",
            "next_falsifiable_gate": "PROOF_CARRYING_WIDTH_REDUCTION_TO_156_QUBITS_OR_LOWER_WITH_EXACT_PROMISE_PARITY",
            "overall": "V44_FAKE_MARRAKESH_CAPACITY_REJECTED_CANARY_PIPELINE_VALIDATED_ZERO_JOB",
            "production_admission": "REJECTED_RESEARCH_ARCHITECTURE_REQUIRES_PROOF_CARRYING_WIDTH_REDUCTION",
        },
        "parent": {
            "artifact_raw_file_sha256": EXPECTED_V43_ARTIFACT_RAW_SHA256,
            "artifact_sha256": EXPECTED_V43_ARTIFACT_SHA256,
            "freeze_raw_file_sha256": EXPECTED_V43_FREEZE_RAW_SHA256,
            "freeze_sha256": EXPECTED_V43_FREEZE_SHA256,
            "immutable_file_count": 191,
            "immutable_files_exact": True,
            "maximum_logical_qubits": (parent_artifact.get("aggregate") or {}).get("maximum_logical_qubits_with_recycled_workspace"),
            "overall_decision": (parent_artifact.get("decisions") or {}).get("overall"),
            "seed_count": len(parent_artifact.get("seed_materializations") or []),
        },
        "research_classification": "RESEARCH_ONLY",
        "snapshot_raw_file_sha256": raw_file_sha256(paths["snapshot"]),
        "snapshot_sha256": snapshot.get("snapshot_sha256"),
        "source_raw_file_sha256": raw_file_sha256(paths["source"]),
        "spec_raw_file_sha256": raw_file_sha256(paths["spec"]),
        "spec_sha256": spec.get("v44_spec_sha256"),
        "toolchain_manifest_raw_file_sha256": raw_file_sha256(paths["toolchain"]),
        "toolchain_manifest_sha256": toolchain.get("manifest_sha256"),
        "v44_version": V44_VERSION,
    }
    return {**core, "artifact_sha256": canonical_json_sha256(core)}


def seal_v44_artifact(*, root: str | Path | None = None, output: str | Path | None = None) -> dict[str, Any]:
    paths = _paths(root)
    artifact = build_v44_artifact(root=paths["root"])
    target = Path(output) if output is not None else paths["artifact"]
    if not target.is_absolute():
        target = paths["root"] / target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(artifact, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return artifact


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--canary-json", action="store_true")
    mode.add_argument("--capacity-json", action="store_true")
    mode.add_argument("--seal", action="store_true")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)
    if args.canary_json:
        result = run_canary_bundle(root=args.root)
    elif args.capacity_json:
        result = capacity_precheck(root=args.root)
    else:
        result = seal_v44_artifact(root=args.root, output=args.output)
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "ARTIFACT_VERSION",
    "DEFAULT_ARTIFACT_NAME",
    "EXPECTED_SEEDS",
    "EXPECTED_WIDTHS",
    "TARGET_QUBITS",
    "V44_VERSION",
    "authenticate_v43_parent",
    "build_v44_artifact",
    "canonical_json_sha256",
    "capacity_precheck",
    "load_v44_snapshot",
    "load_v44_spec",
    "load_v44_toolchain",
    "raw_file_sha256",
    "read_json_strict",
    "run_canary_bundle",
    "seal_v44_artifact",
]
