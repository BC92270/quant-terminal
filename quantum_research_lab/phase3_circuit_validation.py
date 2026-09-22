"""Validation and immutable sealing for the V3.2 reversible gate compiler.

The validation ladder combines exhaustive low-width arithmetic checks,
exhaustive small-oracle equivalence, all eight frozen N=40 witnesses and
adversarial controls, and an independent second family compilation.  The
result is a deterministic proof manifest.  Timestamps are deliberately kept
outside every scientific identity hash.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from .phase3_artifact_guard import (
    EXPECTED_PARENT_RAW_SHA256,
    SEALED_SEEDS,
    load_and_validate_dyadic_artifact,
)
from .phase3_gate_compiler import (
    COMPILER_VERSION,
    DOMAIN_EXACT_K,
    DOMAIN_FULL_BINARY,
    SUPPORTED_DOMAINS,
    CircuitIR,
    Gate,
    analyze_circuit,
    canonical_json_bytes,
    canonical_json_sha256,
    classical_constraint_value,
    classical_predicate,
    compare_inclusive,
    compile_seed_circuit,
    compiler_source_sha256,
    controlled_add_constant,
    factor_range_certificate,
    load_compiler_spec,
    reversible_increment,
    simulate_basis_state,
)


VALIDATION_VERSION = "PHASE III · GATE COMPILER VALIDATION LADDER · V1"
ARTIFACT_VERSION = "PHASE III · SEALED PROOF-CARRYING GATE COMPILER · V1"
EXPECTED_PHASE2_SOURCE_SHA256 = (
    "30c2cb35444afeeff669b9772d5577e89f32dbead762a09fb90fde70c9b653ce"
)
DEFAULT_SEAL_NAME = "SEALED_GATE_COMPILER_ARTIFACT.json"
ProgressCallback = Callable[[str], None]


def _notify(callback: ProgressCallback | None, message: str) -> None:
    if callback is not None:
        callback(message)


def _apply_gates(state: Sequence[int], gates: Iterable[Gate]) -> list[int]:
    result = [int(value) for value in state]
    for gate in gates:
        if all(
            result[index] == expected
            for index, expected in zip(gate.controls, gate.control_values)
        ):
            result[gate.target] ^= 1
    return result


def _decode_unsigned(bits: Sequence[int]) -> int:
    return sum(int(bit) << index for index, bit in enumerate(bits))


def _encode(value: int, width: int) -> list[int]:
    encoded = int(value) & ((1 << width) - 1)
    return [(encoded >> index) & 1 for index in range(width)]


def _decode_signed(bits: Sequence[int]) -> int:
    unsigned = _decode_unsigned(bits)
    return unsigned - (1 << len(bits)) if bits[-1] else unsigned


def run_arithmetic_validation() -> dict[str, Any]:
    """Exhaustively validate arithmetic primitives for widths through five."""

    failures: list[dict[str, Any]] = []
    increment_cases = 0
    addition_cases = 0
    comparator_cases = 0

    for width in range(1, 6):
        modulus = 1 << width
        register = tuple(range(1, width + 1))
        for control in (0, 1):
            for value in range(modulus):
                initial = [control] + _encode(value, width)
                forward = _apply_gates(
                    initial, reversible_increment(0, register)
                )
                expected = (value + control) % modulus
                increment_cases += 1
                if _decode_unsigned(forward[1:]) != expected:
                    failures.append(
                        {
                            "case": "INCREMENT",
                            "control": control,
                            "expected": expected,
                            "got": _decode_unsigned(forward[1:]),
                            "value": value,
                            "width": width,
                        }
                    )
                reverse = _apply_gates(
                    forward, reversible_increment(0, register, inverse=True)
                )
                if reverse != initial:
                    failures.append(
                        {"case": "INCREMENT_INVERSE", "value": value, "width": width}
                    )

                for constant in range(-modulus, modulus + 1):
                    added = _apply_gates(
                        initial,
                        controlled_add_constant(0, register, constant),
                    )
                    expected_add = (value + control * constant) % modulus
                    addition_cases += 1
                    if _decode_unsigned(added[1:]) != expected_add:
                        failures.append(
                            {
                                "case": "ADD_CONSTANT",
                                "constant": constant,
                                "control": control,
                                "expected": expected_add,
                                "got": _decode_unsigned(added[1:]),
                                "value": value,
                                "width": width,
                            }
                        )
                    restored = _apply_gates(
                        added,
                        controlled_add_constant(
                            0, register, constant, inverse=True
                        ),
                    )
                    if restored != initial:
                        failures.append(
                            {
                                "case": "ADD_CONSTANT_INVERSE",
                                "constant": constant,
                                "control": control,
                                "value": value,
                                "width": width,
                            }
                        )

    for signed in (False, True):
        first_width = 2 if signed else 1
        for width in range(first_width, 6):
            minimum = -(1 << (width - 1)) if signed else 0
            maximum = (1 << (width - 1)) - 1 if signed else (1 << width) - 1
            register = tuple(range(width))
            target = width
            for encoded in range(1 << width):
                bits = _encode(encoded, width)
                value = _decode_signed(bits) if signed else encoded
                for constant in range(minimum - 1, maximum + 2):
                    for relation in ("GE", "LE"):
                        initial = bits + [0]
                        forward = _apply_gates(
                            initial,
                            compare_inclusive(
                                register,
                                constant,
                                target,
                                relation=relation,
                                signed=signed,
                            ),
                        )
                        expected = int(
                            value >= constant if relation == "GE" else value <= constant
                        )
                        comparator_cases += 1
                        if forward[target] != expected:
                            failures.append(
                                {
                                    "case": "COMPARATOR",
                                    "constant": constant,
                                    "expected": expected,
                                    "got": forward[target],
                                    "relation": relation,
                                    "signed": signed,
                                    "value": value,
                                    "width": width,
                                }
                            )
                        restored = _apply_gates(
                            forward,
                            compare_inclusive(
                                register,
                                constant,
                                target,
                                relation=relation,
                                signed=signed,
                                inverse=True,
                            ),
                        )
                        if restored != initial:
                            failures.append(
                                {
                                    "case": "COMPARATOR_INVERSE",
                                    "constant": constant,
                                    "relation": relation,
                                    "signed": signed,
                                    "value": value,
                                    "width": width,
                                }
                            )

    return {
        "addition_cases": addition_cases,
        "comparator_cases": comparator_cases,
        "failure_count": len(failures),
        "failures": failures[:20],
        "increment_cases": increment_cases,
        "passed": not failures,
        "widths": [1, 2, 3, 4, 5],
    }


def _synthetic_certificate() -> dict[str, Any]:
    n = 4
    k = 2
    factors = [
        ("FACTOR_1", (-2, 1, 3, -1), -1, 3),
        ("FACTOR_2", (1, -3, 2, 2), -1, 3),
        ("FACTOR_3", (-1, -1, 1, 1), -2, 1),
    ]
    factor_rows: list[dict[str, Any]] = []
    for name, coefficients, lower, upper in factors:
        proof = factor_range_certificate(
            coefficients,
            lower,
            upper,
            n=n,
            k=k,
            domain_mode=DOMAIN_EXACT_K,
        )
        factor_rows.append(
            {
                "accumulator_signed_bits": proof["width"],
                "coefficients_int": list(coefficients),
                "lower_int": lower,
                "name": name,
                "upper_int": upper,
            }
        )
    return {
        "K": k,
        "N": n,
        "factor_bands": factor_rows,
        "group_bands": [
            {
                "counter_bits": 1,
                "indices": [index],
                "lower": 0,
                "name": f"GROUP_{index + 1}",
                "upper": 1,
            }
            for index in range(n)
        ],
        "instance_id": "SYNTHETIC-N004-BANDS-S032",
        "seed": 32,
    }


def _compile_synthetic(mode: str) -> CircuitIR:
    return compile_seed_circuit(
        _synthetic_certificate(),
        mode,
        parent_dyadic_oracle_sha="SYNTHETIC_PARENT",
        parent_artifact_file_sha256="0" * 64,
    )


def run_small_n_validation() -> dict[str, Any]:
    """Exhaustively compare circuit and classical predicates at small N."""

    mode_rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    total_cases = 0
    for mode in SUPPORTED_DOMAINS:
        circuit = _compile_synthetic(mode)
        evaluated_inputs = 0
        feasible_inputs = 0
        inclusive_boundary_hits = 0
        for bits_tuple in product((0, 1), repeat=circuit.n):
            bits = list(bits_tuple)
            if mode == DOMAIN_EXACT_K and sum(bits) != circuit.k:
                continue
            expected = classical_predicate(bits, circuit)
            evaluated_inputs += 1
            feasible_inputs += int(expected)
            for constraint in circuit.constraints:
                value = classical_constraint_value(bits, constraint)
                if value in (constraint.lower, constraint.upper):
                    inclusive_boundary_hits += 1
            for target in (0, 1):
                result = simulate_basis_state(circuit, bits, target=target)
                total_cases += 1
                passed = bool(
                    result["data_preserved"]
                    and result["ancilla_clean"]
                    and result["target_after"] == (target ^ int(expected))
                )
                if not passed:
                    failures.append(
                        {
                            "bits": bits,
                            "expected": expected,
                            "mode": mode,
                            "result": result,
                            "target": target,
                        }
                    )
        ledger = analyze_circuit(circuit)
        mode_rows.append(
            {
                "domain_input_count": evaluated_inputs,
                "feasible_input_count": feasible_inputs,
                "gate_ir_sha256": ledger["gate_ir_sha256"],
                "inclusive_boundary_hits": inclusive_boundary_hits,
                "mode": mode,
                "resource_ledger": ledger,
            }
        )
    return {
        "failure_count": len(failures),
        "failures": failures[:20],
        "modes": mode_rows,
        "negative_coefficients_present": True,
        "passed": not failures and total_cases == 44,
        "target_zero_and_one_checked": True,
        "total_basis_state_cases": total_cases,
    }


def _read_verified_parent(path: str | Path) -> tuple[dict[str, Any], dict[str, Any]]:
    guard = load_and_validate_dyadic_artifact(
        path, expected_raw_sha256=EXPECTED_PARENT_RAW_SHA256
    )
    if not guard["valid"]:
        raise ValueError(
            "Frozen V3.1 parent failed the artifact guard: "
            + ", ".join(guard.get("failed_checks", []))
        )
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return payload, guard


def _first_infeasible_swap(bits: Sequence[int], circuit: CircuitIR) -> list[int] | None:
    ones = [index for index, value in enumerate(bits) if value]
    zeros = [index for index, value in enumerate(bits) if not value]
    for remove in ones:
        for add in zeros:
            candidate = list(bits)
            candidate[remove] = 0
            candidate[add] = 1
            if not classical_predicate(candidate, circuit):
                return candidate
    return None


def _indices(bits: Sequence[int]) -> list[int]:
    return [index for index, value in enumerate(bits) if int(value)]


def _control_result(
    circuit: CircuitIR, bits: Sequence[int], expected: bool
) -> dict[str, Any]:
    simulation = simulate_basis_state(circuit, bits, target=0)
    passed = bool(
        simulation["ancilla_clean"]
        and simulation["data_preserved"]
        and simulation["target_after"] == int(expected)
    )
    return {
        "ancilla_clean": simulation["ancilla_clean"],
        "data_preserved": simulation["data_preserved"],
        "expected_predicate": bool(expected),
        "input_sha256": canonical_json_sha256(list(bits)),
        "passed": passed,
        "selected_indices": _indices(bits),
        "target_after": simulation["target_after"],
    }


def _compact_compilation_entry(circuit: CircuitIR, ledger: Mapping[str, Any]) -> dict[str, Any]:
    constraints = [
        {
            "certified": bool(constraint.range_certificate["certified"]),
            "kind": constraint.kind,
            "name": constraint.name,
            "range_certificate_sha256": canonical_json_sha256(
                dict(constraint.range_certificate)
            ),
            "width": constraint.width,
        }
        for constraint in circuit.constraints
    ]
    return {
        "constraints": constraints,
        "domain_mode": circuit.domain_mode,
        "gate_ir_sha256": ledger["gate_ir_sha256"],
        "instance_id": circuit.instance_id,
        "resource_ledger": ledger,
        "seed": circuit.seed,
    }


def _compile_family_pass(
    parent: Mapping[str, Any],
    *,
    include_controls: bool,
    progress: ProgressCallback | None,
    pass_name: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    entries: list[dict[str, Any]] = []
    controls: list[dict[str, Any]] = []
    certificates = {
        int(certificate["seed"]): certificate
        for certificate in parent["seed_certificates"]
    }

    phase2_path = Path(__file__).with_name("phase2_qhardness.py")
    source_sha = hashlib.sha256(phase2_path.read_bytes()).hexdigest()
    if source_sha != EXPECTED_PHASE2_SOURCE_SHA256:
        raise ValueError("Frozen Phase-II generator source SHA-256 mismatch.")
    build_hard_instance = None
    if include_controls:
        from .phase2_qhardness import build_hard_instance as _builder

        build_hard_instance = _builder

    for seed in SEALED_SEEDS:
        certificate = certificates[seed]
        seed_circuits: dict[str, CircuitIR] = {}
        for mode in SUPPORTED_DOMAINS:
            _notify(progress, f"{pass_name} · compile/analyse seed {seed} · {mode}")
            circuit = compile_seed_circuit(
                certificate,
                mode,
                parent_dyadic_oracle_sha=str(parent["dyadic_oracle_sha"]),
                parent_artifact_file_sha256=EXPECTED_PARENT_RAW_SHA256,
            )
            ledger = analyze_circuit(circuit)
            entries.append(_compact_compilation_entry(circuit, ledger))
            seed_circuits[mode] = circuit

        if include_controls:
            assert build_hard_instance is not None
            instance = build_hard_instance(40, "BANDS", seed)
            if str(instance.instance_id) != str(certificate["instance_id"]):
                raise ValueError(f"Regenerated instance identity mismatch for seed {seed}.")
            witness = [int(value) for value in instance.witness.tolist()]
            exact_circuit = seed_circuits[DOMAIN_EXACT_K]
            full_circuit = seed_circuits[DOMAIN_FULL_BINARY]
            if not classical_predicate(witness, exact_circuit):
                raise ValueError(f"Authoritative witness failed exact-K predicate for seed {seed}.")
            if not classical_predicate(witness, full_circuit):
                raise ValueError(f"Authoritative witness failed full predicate for seed {seed}.")

            adversarial = _first_infeasible_swap(witness, exact_circuit)
            if adversarial is None:
                raise ValueError(f"No deterministic infeasible swap found for seed {seed}.")
            off_cardinality = list(witness)
            off_cardinality[_indices(witness)[0]] = 0
            _notify(progress, f"{pass_name} · basis controls seed {seed}")
            witness_exact = _control_result(exact_circuit, witness, True)
            witness_full = _control_result(full_circuit, witness, True)
            adversarial_exact = _control_result(exact_circuit, adversarial, False)
            off_cardinality_full = _control_result(
                full_circuit, off_cardinality, False
            )
            truth_vector = {
                constraint.name: bool(
                    constraint.lower
                    <= classical_constraint_value(witness, constraint)
                    <= constraint.upper
                )
                for constraint in exact_circuit.constraints
            }
            controls.append(
                {
                    "adversarial_exact_k": adversarial_exact,
                    "all_witness_constraint_flags_true": all(truth_vector.values()),
                    "authoritative_witness_exact_k": witness_exact,
                    "authoritative_witness_full_binary": witness_full,
                    "instance_id": exact_circuit.instance_id,
                    "off_cardinality_full_binary": off_cardinality_full,
                    "seed": seed,
                    "witness_constraint_truth": truth_vector,
                }
            )
    return entries, controls


def _resource_summary(entries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    exact_entries = [
        entry for entry in entries if entry["domain_mode"] == DOMAIN_EXACT_K
    ]
    full_entries = [
        entry for entry in entries if entry["domain_mode"] == DOMAIN_FULL_BINARY
    ]

    def level(entry: Mapping[str, Any], name: str) -> Mapping[str, Any]:
        return entry["resource_ledger"]["levels"][name]

    def maximum(rows: Sequence[Mapping[str, Any]], level_name: str, key: str) -> int:
        return max(int(level(row, level_name)[key]) for row in rows)

    full_width_69_seeds = [
        int(entry["seed"])
        for entry in full_entries
        if max(
            int(item["width"])
            for item in entry["constraints"]
            if item["kind"] == "FACTOR"
        )
        == 69
    ]
    return {
        "EXACT_K_SUBSPACE": {
            "abstract_depth_max": maximum(
                exact_entries, "GATE_LEVEL_ABSTRACT", "abstract_depth"
            ),
            "abstract_gate_count_max": maximum(
                exact_entries, "GATE_LEVEL_ABSTRACT", "gate_count"
            ),
            "fault_tolerant_t_count_max": maximum(
                exact_entries, "FAULT_TOLERANT_ESTIMATE", "t_count"
            ),
            "logical_qubits_max": maximum(
                exact_entries, "LOGICAL_IR", "logical_qubits_total"
            ),
            "max_factor_width": max(
                int(item["width"])
                for entry in exact_entries
                for item in entry["constraints"]
                if item["kind"] == "FACTOR"
            ),
        },
        "FULL_BINARY": {
            "abstract_depth_max": maximum(
                full_entries, "GATE_LEVEL_ABSTRACT", "abstract_depth"
            ),
            "abstract_gate_count_max": maximum(
                full_entries, "GATE_LEVEL_ABSTRACT", "gate_count"
            ),
            "fault_tolerant_t_count_max": maximum(
                full_entries, "FAULT_TOLERANT_ESTIMATE", "t_count"
            ),
            "logical_qubits_max": maximum(
                full_entries, "LOGICAL_IR", "logical_qubits_total"
            ),
            "max_factor_width": max(
                int(item["width"])
                for entry in full_entries
                for item in entry["constraints"]
                if item["kind"] == "FACTOR"
            ),
            "seeds_requiring_69_factor_bits": full_width_69_seeds,
        },
        "claim": "RESOURCE ESTIMATE · PROVIDER-NEUTRAL ABSTRACT GATES",
    }


def run_validation_ladder(
    parent_path: str | Path,
    *,
    progress: ProgressCallback | None = None,
    full_reproducibility: bool = True,
) -> dict[str, Any]:
    """Run the complete deterministic V3.2 validation ladder."""

    parent, guard = _read_verified_parent(parent_path)
    spec = load_compiler_spec()
    _notify(progress, "A · exhaustive arithmetic")
    arithmetic_first = run_arithmetic_validation()
    _notify(progress, "C · exhaustive small-N oracles")
    small_first = run_small_n_validation()
    _notify(progress, "B/D · canonical N=40 family")
    first_entries, controls = _compile_family_pass(
        parent,
        include_controls=True,
        progress=progress,
        pass_name="PASS 1",
    )

    first_compilation_sha = canonical_json_sha256(first_entries)
    small_first_sha = canonical_json_sha256(
        {"arithmetic": arithmetic_first, "small_n": small_first}
    )
    if full_reproducibility:
        _notify(progress, "E · independent second family compilation")
        arithmetic_second = run_arithmetic_validation()
        small_second = run_small_n_validation()
        second_entries, _ = _compile_family_pass(
            parent,
            include_controls=False,
            progress=progress,
            pass_name="PASS 2",
        )
        second_compilation_sha = canonical_json_sha256(second_entries)
        small_second_sha = canonical_json_sha256(
            {"arithmetic": arithmetic_second, "small_n": small_second}
        )
        reproducibility_pass = bool(
            first_entries == second_entries
            and first_compilation_sha == second_compilation_sha
            and small_first_sha == small_second_sha
        )
    else:
        second_compilation_sha = None
        small_second_sha = None
        reproducibility_pass = False

    controls_pass = bool(
        len(controls) == 8
        and all(
            row["all_witness_constraint_flags_true"]
            and row["authoritative_witness_exact_k"]["passed"]
            and row["authoritative_witness_full_binary"]["passed"]
            and row["adversarial_exact_k"]["passed"]
            and row["off_cardinality_full_binary"]["passed"]
            for row in controls
        )
    )
    family_shape_pass = bool(
        len(first_entries) == 16
        and {int(entry["seed"]) for entry in first_entries} == set(SEALED_SEEDS)
        and {
            str(entry["domain_mode"]) for entry in first_entries
        } == set(SUPPORTED_DOMAINS)
        and all(
            entry["resource_ledger"]["claim_boundary"]["hardware_executable"]
            is False
            and all(item["certified"] for item in entry["constraints"])
            for entry in first_entries
        )
    )
    phase2_source_sha = hashlib.sha256(
        Path(__file__).with_name("phase2_qhardness.py").read_bytes()
    ).hexdigest()
    checks = {
        "A_ARITHMETIC": bool(arithmetic_first["passed"]),
        "B_SEED": controls_pass,
        "C_SMALL_N_EXHAUSTIVE": bool(small_first["passed"]),
        "D_N40_CONTROLS": controls_pass and family_shape_pass,
        "E_REPRODUCIBILITY": reproducibility_pass,
        "COMPILER_SPEC_SELF_HASH": (
            spec["gate_compiler_spec_sha256"]
            == canonical_json_sha256(
                {
                    key: value
                    for key, value in spec.items()
                    if key
                    not in {
                        "gate_compiler_spec_sha",
                        "gate_compiler_spec_sha256",
                    }
                }
            )
        ),
        "FROZEN_PARENT_GUARD": bool(guard["valid"]),
        "PHASE2_GENERATOR_SOURCE_FROZEN": (
            phase2_source_sha == EXPECTED_PHASE2_SOURCE_SHA256
        ),
        "RESOURCE_RANGES_CERTIFIED": family_shape_pass,
    }
    validation_core = {
        "arithmetic": arithmetic_first,
        "canonical_controls": controls,
        "checks": checks,
        "compilation_entries": first_entries,
        "compiler_source_sha256": compiler_source_sha256(),
        "compiler_spec_sha256": spec["gate_compiler_spec_sha256"],
        "family_compilation_sha256": first_compilation_sha,
        "parent_guard": {
            "canonical_json_sha256": guard["hashes"]["canonical_json_sha256"],
            "checks": guard["checks"],
            "legacy_dyadic_oracle_sha": guard["hashes"][
                "computed_dyadic_oracle_sha"
            ],
            "raw_file_sha256": guard["hashes"]["raw_file_sha256"],
            "valid": guard["valid"],
        },
        "phase2_generator_source_sha256": phase2_source_sha,
        "reproducibility": {
            "family_first_sha256": first_compilation_sha,
            "family_second_sha256": second_compilation_sha,
            "full_family_second_pass": bool(full_reproducibility),
            "passed": reproducibility_pass,
            "small_suite_first_sha256": small_first_sha,
            "small_suite_second_sha256": small_second_sha,
        },
        "resource_summary": _resource_summary(first_entries),
        "small_n_exhaustive": small_first,
        "validation_version": VALIDATION_VERSION,
    }
    validation_sha = canonical_json_sha256(validation_core)
    result = {
        **validation_core,
        "overall_pass": all(checks.values()),
        "validation_manifest_sha256": validation_sha,
    }
    return result


def build_compiler_artifact(
    parent_path: str | Path,
    *,
    progress: ProgressCallback | None = None,
    full_reproducibility: bool = True,
) -> dict[str, Any]:
    parent, _ = _read_verified_parent(parent_path)
    spec = load_compiler_spec()
    validation = run_validation_ladder(
        parent_path,
        progress=progress,
        full_reproducibility=full_reproducibility,
    )
    if not validation["overall_pass"]:
        raise ValueError("Validation ladder did not pass; compiler seal is blocked.")
    artifact_core = {
        "artifact_version": ARTIFACT_VERSION,
        "claim_boundary": {
            "allowed": spec["claim_boundary"]["allowed"],
            "forbidden": spec["claim_boundary"]["forbidden"],
            "hardware_executable": False,
            "qpu_submission_enabled": False,
        },
        "compiler": {
            "compiler_source_sha256": compiler_source_sha256(),
            "compiler_spec_sha": spec["gate_compiler_spec_sha"],
            "compiler_spec_sha256": spec["gate_compiler_spec_sha256"],
            "compiler_version": COMPILER_VERSION,
            "gate_set": ["X", "CX", "CCX", "MCX"],
            "status": "SEALED PROVIDER-NEUTRAL REVERSIBLE GATE IR",
        },
        "family": parent["family"],
        "limitations": [
            "No backend-native transpilation has been run.",
            "No QPU execution is authorised by this artifact.",
            "No quantum speedup or advantage is claimed.",
            "The XY mixer preserves cardinality only; it does not prove preservation of the seven BANDS constraints.",
            "The exact dyadic predicate represents strict hard-band semantics; the Phase-II 1e-8 post-processing tolerance remains a separate convention.",
        ],
        "oracle_variants": {
            DOMAIN_EXACT_K: {
                "cardinality_compiled": False,
                "contract_domain": "popcount(x)=K",
                "constraint_count": 7,
            },
            DOMAIN_FULL_BINARY: {
                "cardinality_compiled": True,
                "contract_domain": "all x in {0,1}^N",
                "constraint_count": 8,
            },
        },
        "parent": {
            "dyadic_oracle_sha": parent["dyadic_oracle_sha"],
            "dyadic_spec_sha": parent["dyadic_spec_sha"],
            "raw_file_sha256": EXPECTED_PARENT_RAW_SHA256,
        },
        "resource_summary": validation["resource_summary"],
        "validation": validation,
    }
    artifact_sha = canonical_json_sha256(artifact_core)
    return {
        **artifact_core,
        "artifact_sha256": artifact_sha,
        "created_utc": datetime.now(timezone.utc).isoformat(),
    }


def validate_compiler_artifact(payload: Mapping[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return {"valid": False, "errors": ["Artifact must be a JSON object."]}
    try:
        core = {
            key: value
            for key, value in payload.items()
            if key not in {"artifact_sha256", "created_utc"}
        }
        computed = canonical_json_sha256(core)
    except (TypeError, ValueError, OverflowError) as exc:
        return {"valid": False, "errors": [str(exc)]}
    if payload.get("artifact_sha256") != computed:
        errors.append("Artifact SHA-256 mismatch.")
    if payload.get("artifact_version") != ARTIFACT_VERSION:
        errors.append("Artifact version mismatch.")
    if payload.get("claim_boundary", {}).get("hardware_executable") is not False:
        errors.append("Hardware execution boundary violated.")
    validation = payload.get("validation")
    if not isinstance(validation, dict) or validation.get("overall_pass") is not True:
        errors.append("Validation manifest is not passing.")
    elif validation.get("validation_manifest_sha256") != canonical_json_sha256(
        {
            key: value
            for key, value in validation.items()
            if key not in {"validation_manifest_sha256", "overall_pass"}
        }
    ):
        errors.append("Validation manifest SHA-256 mismatch.")
    return {
        "artifact_sha256_computed": computed,
        "artifact_sha256_stored": payload.get("artifact_sha256"),
        "errors": errors,
        "valid": not errors,
    }


def load_compiler_artifact(path: str | Path) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    report = validate_compiler_artifact(payload)
    return payload, report


def seal_compiler_artifact(payload: Mapping[str, Any], path: str | Path) -> dict[str, Any]:
    """Write once, or accept an existing byte-independent identical seal."""

    validation = validate_compiler_artifact(payload)
    if not validation["valid"]:
        raise ValueError("Refusing to seal an invalid compiler artifact.")
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        existing, existing_report = load_compiler_artifact(destination)
        if not existing_report["valid"]:
            raise FileExistsError("Existing compiler seal is invalid and will not be overwritten.")
        if existing.get("artifact_sha256") != payload.get("artifact_sha256"):
            raise FileExistsError("Existing non-identical compiler seal will not be overwritten.")
        return existing

    encoded = json.dumps(
        dict(payload), indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False
    ).encode("utf-8") + b"\n"
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=destination.parent, prefix=".gate-compiler-", delete=False
        ) as temporary:
            temporary.write(encoded)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_name = temporary.name
        try:
            os.link(temporary_name, destination)
        except FileExistsError:
            existing, existing_report = load_compiler_artifact(destination)
            if not existing_report["valid"] or existing.get("artifact_sha256") != payload.get(
                "artifact_sha256"
            ):
                raise FileExistsError(
                    "Concurrent non-identical compiler seal will not be overwritten."
                )
            return existing
    finally:
        if temporary_name is not None:
            try:
                Path(temporary_name).unlink()
            except FileNotFoundError:
                pass
    return dict(payload)


def default_compiler_root() -> Path:
    return Path("outputs/quantum_phase3/gate_compiler")


def compiler_worker_status(root: str | Path | None = None) -> dict[str, Any]:
    """Return a bounded, read-only snapshot of the background compiler audit."""

    worker_root = Path(root) if root is not None else default_compiler_root()
    seal_path = worker_root / DEFAULT_SEAL_NAME
    launch_path = worker_root / "COMPILER_WORKER.json"
    log_path = worker_root / "COMPILER_WORKER.log"
    if seal_path.exists():
        try:
            artifact, report = load_compiler_artifact(seal_path)
        except Exception as exc:
            return {
                "artifact_path": str(seal_path),
                "reason": str(exc),
                "sealed": False,
                "status": "INVALID_SEAL",
            }
        return {
            "artifact": artifact,
            "artifact_path": str(seal_path),
            "integrity": report,
            "sealed": bool(report["valid"]),
            "status": "SEALED" if report["valid"] else "INVALID_SEAL",
        }
    if not launch_path.exists():
        return {"sealed": False, "status": "IDLE"}
    try:
        launch = json.loads(launch_path.read_text(encoding="utf-8"))
        pid = int(launch["pid"])
    except Exception as exc:
        return {"reason": str(exc), "sealed": False, "status": "INVALID_WORKER_STATE"}
    alive = True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        alive = False
    except PermissionError:
        # Existence is confirmed even when the runtime forbids signalling it.
        alive = True
    log_tail = ""
    if log_path.exists():
        try:
            log_tail = "\n".join(
                log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-24:]
            )
        except OSError:
            log_tail = ""
    return {
        "launched_utc": launch.get("launched_utc"),
        "log_tail": log_tail,
        "pid": pid,
        "sealed": False,
        "status": "RUNNING" if alive else "FAILED",
    }


def launch_compiler_worker(
    parent_path: str | Path,
    root: str | Path | None = None,
) -> dict[str, Any]:
    """Launch the full two-pass audit without blocking a Streamlit rerun."""

    worker_root = Path(root) if root is not None else default_compiler_root()
    worker_root.mkdir(parents=True, exist_ok=True)
    current = compiler_worker_status(worker_root)
    if current.get("status") in {"RUNNING", "SEALED"}:
        return {
            "launched": False,
            "reason": f"Compiler worker is already {current.get('status')}.",
            **current,
        }
    # Fail before launch if the parent cannot be authenticated.
    _read_verified_parent(parent_path)
    log_path = worker_root / "COMPILER_WORKER.log"
    launch_path = worker_root / "COMPILER_WORKER.json"
    seal_path = worker_root / DEFAULT_SEAL_NAME
    log_handle = log_path.open("wb")
    try:
        process = subprocess.Popen(
            [
                sys.executable,
                "-u",
                "-m",
                "quantum_research_lab.phase3_circuit_validation",
                str(Path(parent_path)),
                "--output",
                str(seal_path),
            ],
            cwd=Path.cwd(),
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    finally:
        log_handle.close()
    launch = {
        "launched_utc": datetime.now(timezone.utc).isoformat(),
        "parent_path": str(Path(parent_path)),
        "pid": process.pid,
        "seal_path": str(seal_path),
    }
    launch_path.write_text(
        json.dumps(launch, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return {"launched": True, "sealed": False, "status": "RUNNING", **launch}


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate and seal the V3.2 proof-carrying gate compiler."
    )
    parser.add_argument("parent", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=default_compiler_root() / DEFAULT_SEAL_NAME,
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Skip the independent second family pass; cannot produce a seal.",
    )
    args = parser.parse_args(argv)
    if args.quick:
        report = run_validation_ladder(
            args.parent,
            progress=lambda message: print(message, flush=True),
            full_reproducibility=False,
        )
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
        return 0 if report["overall_pass"] else 1
    artifact = build_compiler_artifact(
        args.parent,
        progress=lambda message: print(message, flush=True),
        full_reproducibility=True,
    )
    sealed = seal_compiler_artifact(artifact, args.output)
    print(
        json.dumps(
            {
                "artifact_sha256": sealed["artifact_sha256"],
                "output": str(args.output),
                "resource_summary": sealed["resource_summary"],
                "status": sealed["compiler"]["status"],
                "validation_manifest_sha256": sealed["validation"][
                    "validation_manifest_sha256"
                ],
            },
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI integration path.
    raise SystemExit(_main())


__all__ = [
    "ARTIFACT_VERSION",
    "DEFAULT_SEAL_NAME",
    "EXPECTED_PHASE2_SOURCE_SHA256",
    "VALIDATION_VERSION",
    "build_compiler_artifact",
    "compiler_worker_status",
    "default_compiler_root",
    "launch_compiler_worker",
    "load_compiler_artifact",
    "run_arithmetic_validation",
    "run_small_n_validation",
    "run_validation_ladder",
    "seal_compiler_artifact",
    "validate_compiler_artifact",
]
