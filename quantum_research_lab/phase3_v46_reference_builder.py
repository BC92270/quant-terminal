"""Build the sealed Qiskit 2.5.2 references used by Quantum Lab V4.6.

This utility is deliberately separate from the confirmatory V4.6 compiler.
It imports the locally installed Qiskit SDK only to freeze (1) every ordered
shortest path selected by ``CouplingMap.shortest_undirected_path`` for the
authenticated FakeMarrakesh snapshot and (2) bounded native-translation
canaries.  Socket access is denied for the complete reference build.  No IBM
provider package is imported, no credentials are inspected and no backend,
simulator or QPU job is created.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import socket
from typing import Any, Mapping, Sequence
from unittest import mock

from .phase3_v44_named_backend_routing import (
    _make_target,
    load_v44_snapshot,
    load_v44_toolchain,
    raw_file_sha256,
)


PATH_ORACLE_FILENAME = "PHASE_III_V4_6_FAKEMARRAKESH_BASIC_PATH_ORACLE_V1.json"
TRANSLATION_FILENAME = "PHASE_III_V4_6_NATIVE_TRANSLATION_CONTRACT_V1.json"
REFERENCE_BUILDER_VERSION = "PHASE III · V4.6 QISKIT REFERENCE BUILDER · V1"
EXPECTED_QISKIT_VERSION = "2.5.2"
TARGET_QUBITS = 156
TRANSPILER_SEED = 4505


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


def _root(root: str | Path | None = None) -> Path:
    return Path(root).resolve() if root is not None else Path(__file__).resolve().parents[1]


def _canonical_output(circuit: Any, output: Any) -> dict[str, Any]:
    lines: list[str] = []
    operations: list[dict[str, Any]] = []
    for index, instruction in enumerate(output.data):
        operation = instruction.operation
        qubits = [output.find_bit(qubit).index for qubit in instruction.qubits]
        parameters = [format(float(value), ".17g") for value in operation.params]
        lines.append(
            f"{index}|{operation.name}|{','.join(str(value) for value in qubits)}|"
            f"{','.join(parameters) or '-'}\n"
        )
        operations.append(
            {
                "name": str(operation.name),
                "parameters_radians": parameters,
                "physical_qubits": qubits,
            }
        )
    core = {
        "input_instruction_count": int(circuit.size()),
        "input_logical_qubits": int(circuit.num_qubits),
        "output_depth": int(output.depth()),
        "output_global_phase_radians": format(float(output.global_phase), ".17g"),
        "output_instruction_count": int(output.size()),
        "output_num_qubits": int(output.num_qubits),
        "output_operation_counts": {
            str(key): int(value) for key, value in sorted(output.count_ops().items())
        },
        "output_operations": operations,
        "output_stream_sha256": hashlib.sha256("".join(lines).encode("ascii")).hexdigest(),
    }
    return {**core, "canary_sha256": canonical_json_sha256(core)}


def _build_canaries(target: Any) -> dict[str, dict[str, Any]]:
    from qiskit import QuantumCircuit
    from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager

    builders = {
        "X": lambda circuit: circuit.x(0),
        "H": lambda circuit: circuit.h(0),
        "T": lambda circuit: circuit.t(0),
        "TDG": lambda circuit: circuit.tdg(0),
        "RY_PLUS_PI_OVER_4": lambda circuit: circuit.ry(math.pi / 4, 0),
        "RY_MINUS_PI_OVER_4": lambda circuit: circuit.ry(-math.pi / 4, 0),
        "RZ_PI_OVER_11": lambda circuit: circuit.rz(math.pi / 11, 0),
        "CX_ADJACENT": lambda circuit: circuit.cx(0, 1),
        "SWAP_ADJACENT": lambda circuit: circuit.swap(0, 1),
    }
    results: dict[str, dict[str, Any]] = {}
    for name, builder in builders.items():
        circuit = QuantumCircuit(2, name=name)
        builder(circuit)
        manager = generate_preset_pass_manager(
            optimization_level=0,
            target=target,
            layout_method="trivial",
            routing_method="basic",
            translation_method="translator",
            seed_transpiler=TRANSPILER_SEED,
        )
        results[name] = _canonical_output(circuit, manager.run(circuit))
    return results


def _validate_canary_shapes(canaries: Mapping[str, Mapping[str, Any]]) -> None:
    expected = {
        "X": ({"x": 1}, "0"),
        "H": ({"rz": 2, "sx": 1}, format(math.pi / 4, ".17g")),
        "T": ({"rz": 1}, format(math.pi / 8, ".17g")),
        "TDG": ({"rz": 1}, format(15 * math.pi / 8, ".17g")),
        "RY_PLUS_PI_OVER_4": ({"rz": 3, "sx": 2}, format(3 * math.pi / 2, ".17g")),
        "RY_MINUS_PI_OVER_4": ({"rz": 3, "sx": 2}, format(3 * math.pi / 2, ".17g")),
        "RZ_PI_OVER_11": ({"rz": 1}, "0"),
        "CX_ADJACENT": ({"cz": 1, "rz": 4, "sx": 2}, format(math.pi / 2, ".17g")),
        "SWAP_ADJACENT": ({"cz": 3, "sx": 6}, format(3 * math.pi / 2, ".17g")),
    }
    for name, (counts, phase) in expected.items():
        row = canaries.get(name) or {}
        if row.get("output_operation_counts") != counts:
            raise RuntimeError(f"Unexpected Qiskit translation counts for {name}: {row}")
        observed_phase = float(str(row.get("output_global_phase_radians")))
        if not math.isclose(observed_phase, float(phase), rel_tol=0.0, abs_tol=2e-14):
            raise RuntimeError(f"Unexpected Qiskit translation phase for {name}: {row}")


def build_reference_payloads(*, root: str | Path | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return the path oracle and native macro contract under a network denylist."""

    base = _root(root)
    snapshot = load_v44_snapshot(root=base)
    toolchain = load_v44_toolchain(root=base)
    attempts: list[str] = []

    def deny(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        attempts.append("socket")
        raise RuntimeError("V4.6 reference generation prohibits network access.")

    with mock.patch.object(socket.socket, "connect", deny), mock.patch(
        "socket.create_connection", side_effect=deny
    ):
        import qiskit

        if str(qiskit.__version__) != EXPECTED_QISKIT_VERSION:
            raise RuntimeError(
                f"Pinned Qiskit {EXPECTED_QISKIT_VERSION} required; got {qiskit.__version__}."
            )
        target = _make_target(snapshot)
        coupling = target.build_coupling_map()
        path_lines: list[str] = []
        maximum_distance = 0
        for source in range(TARGET_QUBITS):
            for destination in range(TARGET_QUBITS):
                if source == destination:
                    continue
                path = tuple(int(value) for value in coupling.shortest_undirected_path(source, destination))
                if not path or path[0] != source or path[-1] != destination:
                    raise RuntimeError(f"Malformed Qiskit path {source}->{destination}: {path}")
                maximum_distance = max(maximum_distance, len(path) - 1)
                path_lines.append(
                    f"{source}|{destination}|{','.join(str(value) for value in path)}\n"
                )
        canaries = _build_canaries(target)
        _validate_canary_shapes(canaries)

    if attempts:
        raise RuntimeError(f"Blocked network attempts during V4.6 reference generation: {attempts}")

    snapshot_path = base / "quantum_research_lab/PHASE_III_V4_4_FROZEN_BACKEND_SNAPSHOT_V1.json"
    toolchain_path = base / "quantum_research_lab/PHASE_III_V4_4_TOOLCHAIN_MANIFEST_V1.json"
    path_core = {
        "backend_name": "fake_marrakesh",
        "backend_snapshot_raw_file_sha256": raw_file_sha256(snapshot_path),
        "backend_snapshot_sha256": snapshot.get("snapshot_sha256"),
        "coupling_is_bidirectional": True,
        "directed_coupling_edge_count": int((snapshot.get("target") or {}).get("directed_coupling_edge_count", -1)),
        "generation_boundary": {
            "backend_run_calls": 0,
            "credential_reads": 0,
            "network_attempts": 0,
            "network_calls": 0,
            "provider_calls": 0,
            "provider_sdk_imported": False,
            "qpu_jobs_submitted": 0,
        },
        "maximum_shortest_path_distance": maximum_distance,
        "ordered_path_contract": "SOURCE|DESTINATION|COMMA_SEPARATED_QISKIT_2_5_2_SHORTEST_UNDIRECTED_PATH_NEWLINE",
        "ordered_path_count": len(path_lines),
        "ordered_paths_compact": "".join(path_lines),
        "ordered_paths_stream_sha256": hashlib.sha256("".join(path_lines).encode("ascii")).hexdigest(),
        "oracle_version": "PHASE III · V4.6 FAKEMARRAKESH BASIC PATH ORACLE · V1",
        "qiskit_version": EXPECTED_QISKIT_VERSION,
        "reference_builder_version": REFERENCE_BUILDER_VERSION,
        "routing_method": "basic",
        "target_qubits": TARGET_QUBITS,
        "toolchain_manifest_raw_file_sha256": raw_file_sha256(toolchain_path),
        "toolchain_manifest_sha256": toolchain.get("manifest_sha256"),
        "transpiler_seed": TRANSPILER_SEED,
    }
    path_payload = {**path_core, "path_oracle_sha256": canonical_json_sha256(path_core)}

    translation_core = {
        "backend_name": "fake_marrakesh",
        "backend_snapshot_sha256": snapshot.get("snapshot_sha256"),
        "canary_count": len(canaries),
        "canary_result_root_sha256": canonical_json_sha256(
            [canaries[name]["canary_sha256"] for name in sorted(canaries)]
        ),
        "canaries": canaries,
        "equivalence_scope": "EXACT_UNITARY_UP_TO_THE_RECORDED_GLOBAL_PHASE",
        "generation_boundary": {
            "backend_run_calls": 0,
            "credential_reads": 0,
            "network_attempts": 0,
            "network_calls": 0,
            "provider_calls": 0,
            "provider_sdk_imported": False,
            "qpu_jobs_submitted": 0,
        },
        "native_basis": ["cz", "id", "rz", "sx", "x"],
        "native_macro_contract": {
            "CX": {
                "global_phase_pi": "1/2",
                "operations": ["RZ(1/2pi)@TARGET", "SX@TARGET", "RZ(1/2pi)@TARGET", "CZ@CONTROL,TARGET", "RZ(1/2pi)@TARGET", "SX@TARGET", "RZ(1/2pi)@TARGET"],
            },
            "H": {
                "global_phase_pi": "1/4",
                "operations": ["RZ(1/2pi)@Q", "SX@Q", "RZ(1/2pi)@Q"],
            },
            "RY(theta_pi)": {
                "global_phase_pi": "3/2",
                "operations": ["RZ(0pi)@Q", "SX@Q", "RZ((1+theta_pi)pi)@Q", "SX@Q", "RZ(3pi)@Q"],
            },
            "RZ(theta_pi)": {"global_phase_pi": "0/1", "operations": ["RZ(theta_pi)@Q"]},
            "SWAP": {
                "global_phase_pi": "3/2",
                "operations": ["SX@A", "SX@B", "CZ@A,B", "SX@A", "SX@B", "CZ@A,B", "SX@A", "SX@B", "CZ@A,B"],
            },
            "T": {"global_phase_pi": "1/8", "operations": ["RZ(1/4pi)@Q"]},
            "TDG": {"global_phase_pi": "-1/8", "operations": ["RZ(-1/4pi)@Q"]},
            "X": {"global_phase_pi": "0/1", "operations": ["X@Q"]},
        },
        "optimization_level": 0,
        "qiskit_version": EXPECTED_QISKIT_VERSION,
        "reference_builder_version": REFERENCE_BUILDER_VERSION,
        "routing_method": "basic",
        "target_qubits": TARGET_QUBITS,
        "translation_method": "translator",
        "transpiler_seed": TRANSPILER_SEED,
        "translation_version": "PHASE III · V4.6 NATIVE TRANSLATION CONTRACT · V1",
    }
    translation_payload = {
        **translation_core,
        "translation_contract_sha256": canonical_json_sha256(translation_core),
    }
    return path_payload, translation_payload


def seal_reference_payloads(*, root: str | Path | None = None) -> dict[str, Any]:
    base = _root(root)
    path_payload, translation_payload = build_reference_payloads(root=base)
    path_target = base / "quantum_research_lab" / PATH_ORACLE_FILENAME
    translation_target = base / "quantum_research_lab" / TRANSLATION_FILENAME
    path_target.write_text(
        json.dumps(path_payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    translation_target.write_text(
        json.dumps(translation_payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return {
        "path_oracle": str(path_target),
        "path_oracle_raw_file_sha256": raw_file_sha256(path_target),
        "path_oracle_sha256": path_payload["path_oracle_sha256"],
        "translation_contract": str(translation_target),
        "translation_contract_raw_file_sha256": raw_file_sha256(translation_target),
        "translation_contract_sha256": translation_payload["translation_contract_sha256"],
    }


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=None)
    args = parser.parse_args(argv)
    print(json.dumps(seal_reference_payloads(root=args.root), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "PATH_ORACLE_FILENAME",
    "REFERENCE_BUILDER_VERSION",
    "TRANSLATION_FILENAME",
    "build_reference_payloads",
    "seal_reference_payloads",
]
