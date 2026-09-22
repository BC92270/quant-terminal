"""Provider-free reversible incremental-exposure prototype for Quantum Lab V3.7.

This module closes exactly one narrow V3.6 evidence gap: it constructs and
exhaustively verifies a coherent, state-augmented swap mixer on a registered
``N=4, K=2`` synthetic fixture.  Each feasible portfolio is embedded together
with its exact cached exposure values.  A feasible swap is compiled as a
two-level ``RX`` rotation between the two *complete* embedded basis states, so
the portfolio and cache registers move coherently on both branches.

The compiler emits a deterministic logical gate IR made from signed-pattern
``MCX`` and ``MCRX`` gates.  A Gray path computes the target two-level address,
rotates it, and reverses the path.  Exhaustive simulation verifies that every
intermediate address is restored and every non-target computational basis
state is unchanged.  The IR allocates no ancilla or scratch qubits.

This is deliberately not a production compiler.  The full-width controlled
gates are logical primitives: no elementary one-/two-qubit decomposition and
no CNOT estimate is supplied.  Consequently this module makes no claim about
the frozen ``N=40`` instances, backend executability, QPU execution, resource
admission, optimization performance, or quantum advantage.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from itertools import combinations, product
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .phase3_v36_algorithmic_reduction import (
    canonical_json_sha256,
    raw_file_sha256,
    validate_v36_artifact,
)


V37_VERSION = "PHASE III · V3.7 REVERSIBLE INCREMENTAL EXPOSURE · V1"
ARTIFACT_VERSION = "PHASE III · V3.7 PROOF-CARRYING REVERSIBLE PROTOTYPE · V1"
SPEC_FILENAME = "PHASE_III_V3_7_REVERSIBLE_PROTOTYPE_SPEC_V1.json"
DEFAULT_ARTIFACT_NAME = "SEALED_V3_7_REVERSIBLE_PROTOTYPE_ARTIFACT.json"
EXPECTED_V37_SPEC_SHA256 = (
    "69fd43383554108709960b145436304cc8b687104fd68dc3ffd713e1bcd1cf2c"
)
EXPECTED_V37_SPEC_RAW_SHA256 = (
    "dd90f5177a2183da202df5c1d9e6b8e3b6d26a3cf63afadfa02530d5bceb6e68"
)
EXPECTED_V36_ARTIFACT_SHA256 = (
    "52b9b98a36bf8f6d661b42cdc63f3cc0f6476c207f273a171dcc0516c4c0a54d"
)
EXPECTED_V36_ARTIFACT_RAW_SHA256 = (
    "147e81ebb891f61ec47dd9b46ab0adfc6a7a73e2e21f5b91e42d99b25de7c26c"
)
VALIDATION_BETAS = (0.0, 0.2718281828459045, 0.7853981633974483)
NUMERIC_TOLERANCE = 1.0e-12
_COMPILER_VALIDATION_CACHE: dict[tuple[str, tuple[float, ...]], dict[str, Any]] = {}


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key rejected: {key}")
        result[key] = value
    return result


def _reject_non_finite(token: str) -> None:
    raise ValueError(f"Non-finite JSON number rejected: {token}")


def _read_json_strict(path: Path) -> dict[str, Any]:
    payload = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicates,
        parse_constant=_reject_non_finite,
    )
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def source_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def load_v37_spec(path: str | Path | None = None) -> dict[str, Any]:
    """Load and strictly authenticate the V3.7 preregistration contract."""

    target = Path(path) if path is not None else Path(__file__).with_name(SPEC_FILENAME)

    payload = _read_json_strict(target)
    core = {
        key: value
        for key, value in payload.items()
        if key not in {"v37_spec_sha", "v37_spec_sha256"}
    }
    digest = canonical_json_sha256(core)
    if raw_file_sha256(target) != EXPECTED_V37_SPEC_RAW_SHA256:
        raise ValueError("V3.7 specification raw-file identity mismatch.")
    if digest != EXPECTED_V37_SPEC_SHA256:
        raise ValueError("V3.7 specification registered semantic identity mismatch.")
    if payload.get("v37_spec_sha256") != digest:
        raise ValueError("V3.7 specification SHA-256 mismatch.")
    if payload.get("v37_spec_sha") != digest[:20].upper():
        raise ValueError("V3.7 specification short SHA mismatch.")

    fixture = prototype_fixture()
    fixture_core = {key: value for key, value in fixture.items() if key != "fixture_sha256"}
    if payload.get("fixture_contract") != fixture_core:
        raise ValueError("V3.7 fixture differs from the preregistered fixture contract.")
    acceptance = payload.get("acceptance_contract") or {}
    expected_acceptance = {
        "register_width_qubits": 10,
        "full_domain_basis_state_count": 1024,
        "exact_k_state_count": 6,
        "portfolio_edge_case_count": 36,
        "constraint_row_case_count": 72,
        "coherent_two_level_pair_count": 4,
        "scratch_residual_required": 0,
        "prototype_pass_decision": "SMALL_INSTANCE_REVERSIBLE_PROTOTYPE_PASSED",
    }
    if any(acceptance.get(key) != value for key, value in expected_acceptance.items()):
        raise ValueError("V3.7 acceptance cardinality contract mismatch.")
    if tuple(float(value) for value in acceptance.get("canonical_beta_values") or ()) != VALIDATION_BETAS:
        raise ValueError("V3.7 validation beta contract mismatch.")
    if float(acceptance.get("numeric_tolerance", -1.0)) != NUMERIC_TOLERANCE:
        raise ValueError("V3.7 numeric tolerance contract mismatch.")

    parent = payload.get("parent_contract") or {}
    if parent.get("expected_v36_artifact_sha256") != EXPECTED_V36_ARTIFACT_SHA256:
        raise ValueError("V3.7 semantic V3.6 parent commitment mismatch.")
    if parent.get("expected_v36_artifact_raw_file_sha256") != EXPECTED_V36_ARTIFACT_RAW_SHA256:
        raise ValueError("V3.7 raw V3.6 parent commitment mismatch.")
    gate_ir = payload.get("gate_ir_contract") or {}
    if not (
        gate_ir.get("logical_primitives") == ["PATTERN_MCX", "PATTERN_MCRX"]
        and gate_ir.get("ancilla_qubits") == 0
        and gate_ir.get("scratch_qubits") == 0
        and gate_ir.get("elementary_basis_decomposition") == "NOT_IMPLEMENTED"
    ):
        raise ValueError("V3.7 gate-IR boundary mismatch.")
    boundary = payload.get("claim_boundary") or {}
    if not (
        boundary.get("research_classification") == "RESEARCH_ONLY"
        and boundary.get("scope") == "REGISTERED_SYNTHETIC_N4_K2_FIXTURE_ONLY"
        and boundary.get("production_n40_equivalence") == "NOT_CLAIMED"
        and boundary.get("selected_model_cnot") == "NOT_ESTIMATED"
        and boundary.get("provider_calls") == 0
        and boundary.get("hardware_executable") is False
        and boundary.get("qpu_submission_enabled") is False
        and boundary.get("qpu_jobs_submitted") == 0
        and boundary.get("quantum_advantage") == "NOT_CLAIMED"
    ):
        raise ValueError("V3.7 specification claim boundary mismatch.")
    return payload


def prototype_fixture() -> dict[str, Any]:
    """Return the immutable synthetic fixture used by the V3.7 prototype.

    The fixture is intentionally small enough for exhaustive full-register
    simulation.  It is not sampled from, calibrated to, or asserted equivalent
    to any frozen V3.4 production instance.
    """

    core = {
        "fixture_id": "V37_SYNTHETIC_EXACT_K_N4_K2_V1",
        "classification": "SYNTHETIC_COMPILER_FIXTURE · PROTOTYPE_ONLY",
        "n": 4,
        "k": 2,
        "portfolio_register_order": ["x0", "x1", "x2", "x3"],
        "edges": [[i, j] for i in range(4) for j in range(i + 1, 4)],
        "constraint_rows": [
            {
                "name": "EXPOSURE_U",
                "encoding": "UNSIGNED_BINARY",
                "width": 3,
                "coefficients": [0, 1, 2, 3],
                "lower": 1,
                "upper": 4,
            },
            {
                "name": "EXPOSURE_S",
                "encoding": "TWOS_COMPLEMENT",
                "width": 3,
                "coefficients": [-1, 0, 1, 2],
                "lower": 0,
                "upper": 2,
            },
        ],
        "initial_state_contract": (
            "Support is restricted to exact-K feasible portfolios embedded "
            "with caches equal to full integer exposure recomputation."
        ),
    }
    return {**core, "fixture_sha256": canonical_json_sha256(core)}


def _validate_bits(bits: Sequence[int], n: int) -> tuple[int, ...]:
    values = tuple(int(value) for value in bits)
    if len(values) != n or any(value not in (0, 1) for value in values):
        raise ValueError(f"Expected {n} binary portfolio bits.")
    return values


def exact_k_states(fixture: Mapping[str, Any] | None = None) -> tuple[tuple[int, ...], ...]:
    contract = dict(fixture) if fixture is not None else prototype_fixture()
    n = int(contract["n"])
    k = int(contract["k"])
    return tuple(
        tuple(1 if index in selected else 0 for index in range(n))
        for selected in combinations(range(n), k)
    )


def exposure_values(
    bits: Sequence[int], fixture: Mapping[str, Any] | None = None
) -> tuple[int, ...]:
    contract = dict(fixture) if fixture is not None else prototype_fixture()
    values = _validate_bits(bits, int(contract["n"]))
    return tuple(
        sum(int(coefficient) * bit for coefficient, bit in zip(row["coefficients"], values))
        for row in contract["constraint_rows"]
    )


def values_feasible(
    values: Sequence[int], fixture: Mapping[str, Any] | None = None
) -> bool:
    contract = dict(fixture) if fixture is not None else prototype_fixture()
    rows = contract["constraint_rows"]
    if len(values) != len(rows):
        raise ValueError("Exposure vector width mismatch.")
    return all(
        int(row["lower"]) <= int(value) <= int(row["upper"])
        for value, row in zip(values, rows)
    )


def portfolio_feasible(
    bits: Sequence[int], fixture: Mapping[str, Any] | None = None
) -> bool:
    contract = dict(fixture) if fixture is not None else prototype_fixture()
    values = _validate_bits(bits, int(contract["n"]))
    return bool(
        sum(values) == int(contract["k"])
        and values_feasible(exposure_values(values, contract), contract)
    )


def prospective_exposure_values(
    bits: Sequence[int],
    edge: tuple[int, int],
    cached_values: Sequence[int] | None = None,
    fixture: Mapping[str, Any] | None = None,
) -> tuple[int, ...]:
    """Apply ``A(S_ij x)=A(x)+(x_j-x_i)(c_i-c_j)`` over integers."""

    contract = dict(fixture) if fixture is not None else prototype_fixture()
    values = _validate_bits(bits, int(contract["n"]))
    i, j = int(edge[0]), int(edge[1])
    if i == j or i < 0 or j < 0 or i >= len(values) or j >= len(values):
        raise ValueError("Swap edge is invalid.")
    cached = (
        tuple(int(value) for value in cached_values)
        if cached_values is not None
        else exposure_values(values, contract)
    )
    if len(cached) != len(contract["constraint_rows"]):
        raise ValueError("Cached exposure width mismatch.")
    direction = values[j] - values[i]
    return tuple(
        current
        + direction
        * (int(row["coefficients"][i]) - int(row["coefficients"][j]))
        for current, row in zip(cached, contract["constraint_rows"])
    )


def swap_bits(bits: Sequence[int], edge: tuple[int, int]) -> tuple[int, ...]:
    values = list(int(value) for value in bits)
    i, j = int(edge[0]), int(edge[1])
    if i == j or i < 0 or j < 0 or i >= len(values) or j >= len(values):
        raise ValueError("Swap edge is invalid.")
    values[i], values[j] = values[j], values[i]
    return tuple(values)


def register_contract(fixture: Mapping[str, Any] | None = None) -> dict[str, Any]:
    contract = dict(fixture) if fixture is not None else prototype_fixture()
    n = int(contract["n"])
    registers: list[dict[str, Any]] = [
        {
            "name": "portfolio",
            "offset": 0,
            "width": n,
            "encoding": "BINARY_BITS_LSB_POSITION_ORDER",
        }
    ]
    offset = n
    for row in contract["constraint_rows"]:
        width = int(row["width"])
        registers.append(
            {
                "name": str(row["name"]),
                "offset": offset,
                "width": width,
                "encoding": str(row["encoding"]),
            }
        )
        offset += width
    core = {
        "bit_order": "LITTLE_ENDIAN_INTEGER_INDEX",
        "registers": registers,
        "data_qubits": offset,
        "ancilla_qubits": 0,
        "scratch_qubits": 0,
        "full_domain_basis_states": 1 << offset,
        "inconsistent_cache_policy": "IDENTITY_OUTSIDE_COMPILED_ENDPOINTS",
    }
    return {**core, "register_contract_sha256": canonical_json_sha256(core)}


def _encode_integer(value: int, width: int, encoding: str) -> int:
    minimum = -(1 << (width - 1)) if encoding == "TWOS_COMPLEMENT" else 0
    maximum = (1 << (width - 1)) - 1 if encoding == "TWOS_COMPLEMENT" else (1 << width) - 1
    if value < minimum or value > maximum:
        raise ValueError(f"Value {value} does not fit {encoding} width {width}.")
    return value % (1 << width)


def _decode_integer(encoded: int, width: int, encoding: str) -> int:
    if encoded < 0 or encoded >= (1 << width):
        raise ValueError("Encoded register value is outside its width.")
    if encoding == "TWOS_COMPLEMENT" and encoded >= (1 << (width - 1)):
        return encoded - (1 << width)
    return encoded


def encode_basis_state(
    bits: Sequence[int],
    caches: Sequence[int] | None = None,
    fixture: Mapping[str, Any] | None = None,
) -> int:
    contract = dict(fixture) if fixture is not None else prototype_fixture()
    values = _validate_bits(bits, int(contract["n"]))
    exposures = (
        tuple(int(value) for value in caches)
        if caches is not None
        else exposure_values(values, contract)
    )
    rows = contract["constraint_rows"]
    if len(exposures) != len(rows):
        raise ValueError("Cache register count mismatch.")
    encoded = sum(bit << position for position, bit in enumerate(values))
    offset = int(contract["n"])
    for exposure, row in zip(exposures, rows):
        width = int(row["width"])
        encoded |= _encode_integer(exposure, width, str(row["encoding"])) << offset
        offset += width
    return encoded


def decode_basis_state(
    basis_index: int, fixture: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    contract = dict(fixture) if fixture is not None else prototype_fixture()
    registers = register_contract(contract)
    width = int(registers["data_qubits"])
    index = int(basis_index)
    if index < 0 or index >= (1 << width):
        raise ValueError("Basis index is outside the compiled register.")
    n = int(contract["n"])
    bits = tuple((index >> position) & 1 for position in range(n))
    caches: list[int] = []
    offset = n
    for row in contract["constraint_rows"]:
        row_width = int(row["width"])
        mask = (1 << row_width) - 1
        caches.append(
            _decode_integer(
                (index >> offset) & mask,
                row_width,
                str(row["encoding"]),
            )
        )
        offset += row_width
    expected = exposure_values(bits, contract)
    return {
        "basis_index": index,
        "portfolio_bits": list(bits),
        "cached_exposures": caches,
        "recomputed_exposures": list(expected),
        "cache_consistent": tuple(caches) == expected,
        "exact_k": sum(bits) == int(contract["k"]),
        "feasible": portfolio_feasible(bits, contract),
    }


def transition_pairs(
    edge: tuple[int, int], fixture: Mapping[str, Any] | None = None
) -> tuple[dict[str, Any], ...]:
    contract = dict(fixture) if fixture is not None else prototype_fixture()
    i, j = int(edge[0]), int(edge[1])
    declared_edges = {tuple(int(value) for value in item) for item in contract["edges"]}
    if (i, j) not in declared_edges:
        raise ValueError("Edge is not in the registered fixture.")
    rows: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()
    for bits in exact_k_states(contract):
        if not portfolio_feasible(bits, contract) or bits[i] == bits[j]:
            continue
        swapped = swap_bits(bits, (i, j))
        if not portfolio_feasible(swapped, contract):
            continue
        left = encode_basis_state(bits, fixture=contract)
        right = encode_basis_state(swapped, fixture=contract)
        key = tuple(sorted((left, right)))
        if key in seen:
            continue
        seen.add(key)
        first_bits = bits if left == key[0] else swapped
        second_bits = swapped if left == key[0] else bits
        first_caches = exposure_values(first_bits, contract)
        second_caches = exposure_values(second_bits, contract)
        rows.append(
            {
                "left_basis": key[0],
                "right_basis": key[1],
                "left_portfolio": list(first_bits),
                "right_portfolio": list(second_bits),
                "left_caches": list(first_caches),
                "right_caches": list(second_caches),
                "cache_delta": [
                    right_value - left_value
                    for left_value, right_value in zip(first_caches, second_caches)
                ],
            }
        )
    return tuple(sorted(rows, key=lambda row: (row["left_basis"], row["right_basis"])))


def _integer_bits(value: int, width: int) -> tuple[int, ...]:
    return tuple((int(value) >> position) & 1 for position in range(width))


def _hamming_distance(left: int, right: int) -> int:
    return (int(left) ^ int(right)).bit_count()


def gray_path(left: int, right: int, width: int) -> tuple[int, ...]:
    """Return a deterministic least-significant-difference-first Gray path."""

    if left == right:
        raise ValueError("A two-level pair requires two distinct basis states.")
    if min(left, right) < 0 or max(left, right) >= (1 << width):
        raise ValueError("Gray-path endpoint is outside the register width.")
    current = int(left)
    path = [current]
    for target in range(width):
        if ((left >> target) & 1) != ((right >> target) & 1):
            current ^= 1 << target
            path.append(current)
    if current != right or any(_hamming_distance(a, b) != 1 for a, b in zip(path, path[1:])):
        raise AssertionError("Internal Gray-path construction failed.")
    return tuple(path)


def _pattern_controlled_gate(
    left: int,
    right: int,
    width: int,
    *,
    kind: str,
    angle_multiplier: int | None = None,
) -> dict[str, Any]:
    if _hamming_distance(left, right) != 1:
        raise ValueError("Pattern-controlled gate endpoints must be adjacent.")
    target = (left ^ right).bit_length() - 1
    pattern = _integer_bits(left, width)
    controls = [
        {"qubit": position, "value": pattern[position]}
        for position in range(width)
        if position != target
    ]
    gate = {
        "kind": kind,
        "target": target,
        "controls": controls,
        "control_count": len(controls),
        "negative_control_count": sum(row["value"] == 0 for row in controls),
    }
    if angle_multiplier is not None:
        gate["angle_symbol"] = "beta"
        gate["angle_multiplier"] = angle_multiplier
    return gate


def compile_two_level_pair(
    left: int, right: int, width: int
) -> dict[str, Any]:
    """Compile an ideal two-level ``exp(-i beta X)`` through a Gray path."""

    path = gray_path(left, right, width)
    forward = [
        _pattern_controlled_gate(a, b, width, kind="PATTERN_MCX")
        for a, b in zip(path[:-2], path[1:-1])
    ]
    rotation = _pattern_controlled_gate(
        path[-2],
        path[-1],
        width,
        kind="PATTERN_MCRX",
        angle_multiplier=2,
    )
    gates = [*forward, rotation, *reversed(forward)]
    core = {
        "left_basis": int(left),
        "right_basis": int(right),
        "hamming_distance": _hamming_distance(left, right),
        "gray_path": list(path),
        "gates": gates,
        "logical_gate_count": len(gates),
        "pattern_mcx_count": 2 * len(forward),
        "pattern_mcrx_count": 1,
        "ancilla_qubits": 0,
        "scratch_qubits": 0,
    }
    return {**core, "pair_ir_sha256": canonical_json_sha256(core)}


def compile_edge(
    edge: tuple[int, int], fixture: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    contract = dict(fixture) if fixture is not None else prototype_fixture()
    width = int(register_contract(contract)["data_qubits"])
    pairs = transition_pairs(edge, contract)
    pair_circuits = [
        compile_two_level_pair(int(row["left_basis"]), int(row["right_basis"]), width)
        for row in pairs
    ]
    gates = [gate for circuit in pair_circuits for gate in circuit["gates"]]
    core = {
        "edge": [int(edge[0]), int(edge[1])],
        "semantic_primitive": "TWO_LEVEL_COHERENT_PORTFOLIO_PLUS_CACHE_RX",
        "pairs": list(pairs),
        "pair_circuits": pair_circuits,
        "gates": gates,
        "pair_count": len(pairs),
        "logical_gate_count": len(gates),
        "pattern_mcx_count": sum(item["pattern_mcx_count"] for item in pair_circuits),
        "pattern_mcrx_count": len(pair_circuits),
        "ancilla_qubits": 0,
        "scratch_qubits": 0,
    }
    return {**core, "edge_ir_sha256": canonical_json_sha256(core)}


def _controls_match(basis: int, controls: Sequence[Mapping[str, Any]]) -> bool:
    return all(
        ((int(basis) >> int(control["qubit"])) & 1) == int(control["value"])
        for control in controls
    )


def _accumulate(target: dict[int, complex], basis: int, amplitude: complex) -> None:
    if abs(amplitude) > 1.0e-15:
        target[basis] = target.get(basis, 0.0j) + amplitude


def apply_gate(
    amplitudes: Mapping[int, complex], gate: Mapping[str, Any], beta: float
) -> dict[int, complex]:
    """Apply one logical pattern-controlled gate to a sparse state vector."""

    kind = str(gate["kind"])
    target = int(gate["target"])
    controls = gate["controls"]
    output: dict[int, complex] = {}
    if kind == "PATTERN_MCX":
        for basis, amplitude in amplitudes.items():
            destination = int(basis) ^ (1 << target) if _controls_match(int(basis), controls) else int(basis)
            _accumulate(output, destination, complex(amplitude))
        return output
    if kind != "PATTERN_MCRX":
        raise ValueError(f"Unsupported logical gate: {kind}")
    theta_over_two = float(beta) * int(gate["angle_multiplier"]) / 2.0
    cosine = math.cos(theta_over_two)
    sine = math.sin(theta_over_two)
    for basis, amplitude in amplitudes.items():
        index = int(basis)
        value = complex(amplitude)
        if not _controls_match(index, controls):
            _accumulate(output, index, value)
            continue
        _accumulate(output, index, cosine * value)
        _accumulate(output, index ^ (1 << target), -1.0j * sine * value)
    return output


def apply_gate_sequence(
    amplitudes: Mapping[int, complex],
    gates: Sequence[Mapping[str, Any]],
    beta: float,
) -> dict[int, complex]:
    state = {int(index): complex(value) for index, value in amplitudes.items()}
    for gate in gates:
        state = apply_gate(state, gate, beta)
    return state


def apply_adjoint_gate_sequence(
    amplitudes: Mapping[int, complex],
    gates: Sequence[Mapping[str, Any]],
    beta: float,
) -> dict[int, complex]:
    state = {int(index): complex(value) for index, value in amplitudes.items()}
    for gate in reversed(gates):
        state = apply_gate(state, gate, -beta if gate["kind"] == "PATTERN_MCRX" else beta)
    return state


def ideal_edge_action(
    basis: int,
    pairs: Sequence[Mapping[str, Any]],
    beta: float,
) -> dict[int, complex]:
    cosine = math.cos(float(beta))
    sine = math.sin(float(beta))
    index = int(basis)
    for row in pairs:
        left, right = int(row["left_basis"]), int(row["right_basis"])
        if index == left:
            return {left: complex(cosine), right: complex(0.0, -sine)}
        if index == right:
            return {left: complex(0.0, -sine), right: complex(cosine)}
    return {index: 1.0 + 0.0j}


def apply_ideal_edge_action(
    amplitudes: Mapping[int, complex],
    pairs: Sequence[Mapping[str, Any]],
    beta: float,
) -> dict[int, complex]:
    """Apply the independent recompute-from-pairs reference edge action."""

    cosine = math.cos(float(beta))
    sine = math.sin(float(beta))
    pair_by_basis: dict[int, tuple[int, int]] = {}
    for row in pairs:
        left, right = int(row["left_basis"]), int(row["right_basis"])
        pair_by_basis[left] = (left, right)
        pair_by_basis[right] = (left, right)
    output: dict[int, complex] = {}
    for basis, amplitude in amplitudes.items():
        index = int(basis)
        value = complex(amplitude)
        pair = pair_by_basis.get(index)
        if pair is None:
            _accumulate(output, index, value)
            continue
        left, right = pair
        if index == left:
            _accumulate(output, left, cosine * value)
            _accumulate(output, right, -1.0j * sine * value)
        else:
            _accumulate(output, left, -1.0j * sine * value)
            _accumulate(output, right, cosine * value)
    return output


def _state_error(left: Mapping[int, complex], right: Mapping[int, complex]) -> float:
    return max(
        (abs(complex(left.get(index, 0.0j)) - complex(right.get(index, 0.0j))) for index in set(left) | set(right)),
        default=0.0,
    )


def differential_audit(
    fixture: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    contract = dict(fixture) if fixture is not None else prototype_fixture()
    rows: list[dict[str, Any]] = []
    row_cases = 0
    all_delta_exact = True
    all_predicates_exact = True
    all_exact_k = True
    for bits in exact_k_states(contract):
        cached = exposure_values(bits, contract)
        for edge_raw in contract["edges"]:
            edge = (int(edge_raw[0]), int(edge_raw[1]))
            prospective = prospective_exposure_values(bits, edge, cached, contract)
            swapped = swap_bits(bits, edge)
            recomputed = exposure_values(swapped, contract)
            delta_exact = prospective == recomputed
            predicate_exact = values_feasible(prospective, contract) == values_feasible(recomputed, contract)
            exact_k = sum(swapped) == int(contract["k"])
            compiled_active = any(
                encode_basis_state(bits, fixture=contract)
                in (int(pair["left_basis"]), int(pair["right_basis"]))
                for pair in transition_pairs(edge, contract)
            )
            expected_active = bool(
                portfolio_feasible(bits, contract)
                and bits[edge[0]] != bits[edge[1]]
                and portfolio_feasible(swapped, contract)
            )
            rows.append(
                {
                    "portfolio": list(bits),
                    "edge": list(edge),
                    "cached": list(cached),
                    "prospective": list(prospective),
                    "full_recompute": list(recomputed),
                    "delta_exact": delta_exact,
                    "predicate_exact": predicate_exact,
                    "exact_k_preserved": exact_k,
                    "compiled_active": compiled_active,
                    "expected_active": expected_active,
                    "guard_exact": compiled_active == expected_active,
                }
            )
            row_cases += len(contract["constraint_rows"])
            all_delta_exact = all_delta_exact and delta_exact
            all_predicates_exact = all_predicates_exact and predicate_exact
            all_exact_k = all_exact_k and exact_k
    core = {
        "arithmetic_identity": "A_r(S_ij x) = A_r(x) + (x_j - x_i)(c_ri - c_rj)",
        "portfolio_edge_cases": len(rows),
        "constraint_row_cases": row_cases,
        "rows": rows,
        "checks": {
            "all_36_exact_k_portfolio_edge_cases_present": len(rows) == 36,
            "all_72_constraint_row_cases_present": row_cases == 72,
            "all_integer_deltas_equal_full_recompute": all_delta_exact,
            "all_feasibility_predicates_equal_full_recompute": all_predicates_exact,
            "every_swap_preserves_exact_k": all_exact_k,
            "compiled_guard_equals_registered_support_rule": all(row["guard_exact"] for row in rows),
        },
    }
    return {
        **core,
        "passed": all(core["checks"].values()),
        "differential_manifest_sha256": canonical_json_sha256(core),
    }


def _feasible_connectivity(fixture: Mapping[str, Any]) -> dict[str, Any]:
    feasible = [state for state in exact_k_states(fixture) if portfolio_feasible(state, fixture)]
    encoded = {encode_basis_state(state, fixture=fixture): state for state in feasible}
    adjacency: dict[int, set[int]] = {index: set() for index in encoded}
    for edge_raw in fixture["edges"]:
        for pair in transition_pairs((int(edge_raw[0]), int(edge_raw[1])), fixture):
            left, right = int(pair["left_basis"]), int(pair["right_basis"])
            adjacency[left].add(right)
            adjacency[right].add(left)
    visited: set[int] = set()
    frontier = [next(iter(adjacency))] if adjacency else []
    while frontier:
        node = frontier.pop()
        if node in visited:
            continue
        visited.add(node)
        frontier.extend(sorted(adjacency[node] - visited))
    undirected_edges = sum(len(neighbors) for neighbors in adjacency.values()) // 2
    return {
        "feasible_node_count": len(feasible),
        "feasible_portfolios": [list(state) for state in feasible],
        "undirected_transition_count": undirected_edges,
        "connected": len(visited) == len(feasible) and bool(feasible),
    }


def exhaustive_compiler_validation(
    fixture: Mapping[str, Any] | None = None,
    betas: Sequence[float] = VALIDATION_BETAS,
) -> dict[str, Any]:
    contract = dict(fixture) if fixture is not None else prototype_fixture()
    cache_key = (
        canonical_json_sha256(contract),
        tuple(float(beta) for beta in betas),
    )
    if cache_key in _COMPILER_VALIDATION_CACHE:
        return copy.deepcopy(_COMPILER_VALIDATION_CACHE[cache_key])
    registers = register_contract(contract)
    width = int(registers["data_qubits"])
    domain_size = 1 << width
    edge_reports: list[dict[str, Any]] = []
    global_action_error = 0.0
    global_roundtrip_error = 0.0
    global_norm_error = 0.0
    total_columns = 0
    total_pair_beta_checks = 0
    all_support_consistent = True
    all_off_target_identity = True
    for edge_raw in contract["edges"]:
        edge = (int(edge_raw[0]), int(edge_raw[1]))
        compiled = compile_edge(edge, contract)
        pairs = compiled["pairs"]
        target_indices = {
            int(value)
            for pair in pairs
            for value in (pair["left_basis"], pair["right_basis"])
        }
        edge_action_error = 0.0
        edge_roundtrip_error = 0.0
        edge_norm_error = 0.0
        edge_off_target = True
        for beta in betas:
            for basis in range(domain_size):
                initial = {basis: 1.0 + 0.0j}
                actual = apply_gate_sequence(initial, compiled["gates"], float(beta))
                expected = ideal_edge_action(basis, pairs, float(beta))
                error = _state_error(actual, expected)
                edge_action_error = max(edge_action_error, error)
                norm = sum(abs(value) ** 2 for value in actual.values())
                edge_norm_error = max(edge_norm_error, abs(norm - 1.0))
                restored = apply_adjoint_gate_sequence(actual, compiled["gates"], float(beta))
                edge_roundtrip_error = max(edge_roundtrip_error, _state_error(restored, initial))
                if basis not in target_indices:
                    edge_off_target = edge_off_target and error <= NUMERIC_TOLERANCE
                for destination, amplitude in actual.items():
                    if abs(amplitude) <= NUMERIC_TOLERANCE or destination not in target_indices:
                        continue
                    decoded = decode_basis_state(destination, contract)
                    all_support_consistent = all_support_consistent and bool(
                        decoded["cache_consistent"] and decoded["exact_k"] and decoded["feasible"]
                    )
                total_columns += 1
            total_pair_beta_checks += len(pairs)
        global_action_error = max(global_action_error, edge_action_error)
        global_roundtrip_error = max(global_roundtrip_error, edge_roundtrip_error)
        global_norm_error = max(global_norm_error, edge_norm_error)
        all_off_target_identity = all_off_target_identity and edge_off_target
        edge_reports.append(
            {
                "edge": list(edge),
                "pair_count": len(pairs),
                "basis_columns_checked": domain_size * len(betas),
                "maximum_action_error": edge_action_error,
                "maximum_roundtrip_error": edge_roundtrip_error,
                "maximum_norm_error": edge_norm_error,
                "off_target_identity_exact_within_tolerance": edge_off_target,
                "edge_ir_sha256": compiled["edge_ir_sha256"],
            }
        )

    layer_norm_error = 0.0
    layer_action_error = 0.0
    layer_roundtrip_error = 0.0
    layer_gram_error = 0.0
    layer_columns_checked = 0
    layer_gram_entries_checked = 0
    layer_support_consistent = True
    compiled_edges = [
        compile_edge((int(edge[0]), int(edge[1])), contract)
        for edge in contract["edges"]
    ]
    ir_replay = [
        compile_edge((int(edge[0]), int(edge[1])), contract)
        for edge in contract["edges"]
    ]
    ir_replay_deterministic = [row["edge_ir_sha256"] for row in compiled_edges] == [
        row["edge_ir_sha256"] for row in ir_replay
    ]
    for beta in betas:
        layer_columns: list[dict[int, complex]] = []
        for basis in range(domain_size):
            initial: dict[int, complex] = {basis: 1.0 + 0.0j}
            compiled_state = initial
            reference_state = initial
            for compiled in compiled_edges:
                compiled_state = apply_gate_sequence(compiled_state, compiled["gates"], float(beta))
                reference_state = apply_ideal_edge_action(reference_state, compiled["pairs"], float(beta))
            layer_action_error = max(
                layer_action_error,
                _state_error(compiled_state, reference_state),
            )
            norm = sum(abs(value) ** 2 for value in compiled_state.values())
            layer_norm_error = max(layer_norm_error, abs(norm - 1.0))
            restored = compiled_state
            for compiled in reversed(compiled_edges):
                restored = apply_adjoint_gate_sequence(
                    restored, compiled["gates"], float(beta)
                )
            layer_roundtrip_error = max(
                layer_roundtrip_error,
                _state_error(restored, initial),
            )
            for destination, amplitude in compiled_state.items():
                if abs(amplitude) <= NUMERIC_TOLERANCE:
                    continue
                decoded = decode_basis_state(destination, contract)
                if basis in {
                    encode_basis_state(state, fixture=contract)
                    for state in exact_k_states(contract)
                    if portfolio_feasible(state, contract)
                }:
                    layer_support_consistent = layer_support_consistent and bool(
                        decoded["cache_consistent"]
                        and decoded["exact_k"]
                        and decoded["feasible"]
                    )
            layer_columns.append(compiled_state)
            layer_columns_checked += 1

        # Explicit full Gram audit, not only a norm proxy.  The sparse columns
        # keep the 1024×1024 comparison tractable and expose any off-diagonal
        # leakage introduced by a broken compute/rotate/uncompute scaffold.
        for left_index, left_column in enumerate(layer_columns):
            for right_index, right_column in enumerate(layer_columns):
                inner = sum(
                    complex(amplitude).conjugate()
                    * complex(right_column.get(row, 0.0j))
                    for row, amplitude in left_column.items()
                )
                expected = 1.0 + 0.0j if left_index == right_index else 0.0j
                layer_gram_error = max(layer_gram_error, abs(inner - expected))
                layer_gram_entries_checked += 1

    connectivity = _feasible_connectivity(contract)
    checks = {
        "compiled_action_matches_ideal_on_every_basis_column": global_action_error <= NUMERIC_TOLERANCE,
        "compiled_adjoint_restores_every_basis_column": global_roundtrip_error <= NUMERIC_TOLERANCE,
        "every_basis_column_preserves_norm": global_norm_error <= NUMERIC_TOLERANCE,
        "all_non_target_basis_states_are_identity": all_off_target_identity,
        "all_nonzero_target_support_has_consistent_cache": all_support_consistent,
        "complete_ordered_layer_matches_independent_reference_multi_beta": layer_action_error
        <= NUMERIC_TOLERANCE,
        "complete_ordered_layer_adjoint_restores_every_basis_column": layer_roundtrip_error
        <= NUMERIC_TOLERANCE,
        "complete_ordered_layer_gram_is_identity": layer_gram_error <= NUMERIC_TOLERANCE,
        "complete_ordered_layer_preserves_norm": layer_norm_error <= NUMERIC_TOLERANCE,
        "complete_ordered_layer_preserves_feasible_consistent_support": layer_support_consistent,
        "feasible_fixture_graph_is_connected": connectivity["connected"],
        "logical_ir_replay_is_deterministic": ir_replay_deterministic,
        "zero_ancilla_and_zero_scratch_allocated": registers["ancilla_qubits"] == 0
        and registers["scratch_qubits"] == 0,
    }
    core = {
        "numeric_tolerance": NUMERIC_TOLERANCE,
        "validation_betas": [float(beta) for beta in betas],
        "register_width": width,
        "full_domain_basis_states": domain_size,
        "basis_columns_checked": total_columns,
        "two_level_pair_beta_checks": total_pair_beta_checks,
        "maximum_action_error": global_action_error,
        "maximum_roundtrip_error": global_roundtrip_error,
        "maximum_norm_error": global_norm_error,
        "complete_layer_basis_columns_checked": layer_columns_checked,
        "complete_layer_gram_entries_checked": layer_gram_entries_checked,
        "complete_layer_maximum_action_error": layer_action_error,
        "complete_layer_maximum_roundtrip_error": layer_roundtrip_error,
        "complete_layer_maximum_gram_error": layer_gram_error,
        "complete_layer_maximum_norm_error": layer_norm_error,
        "logical_ir_replay_sha256": canonical_json_sha256(
            [row["edge_ir_sha256"] for row in ir_replay]
        ),
        "edge_reports": edge_reports,
        "feasible_connectivity": connectivity,
        "checks": checks,
        "scratch_cleanup_proof": {
            "method": "GRAY_PATH_COMPUTE · MCRX(2β) · REVERSE_GRAY_PATH",
            "allocated_ancilla_qubits": 0,
            "allocated_scratch_qubits": 0,
            "evidence": (
                "Every complete compiled block was compared with the ideal two-level "
                "operator on every computational-basis column; all off-target columns "
                "return exactly within the registered numeric tolerance."
            ),
        },
    }
    result = {
        **core,
        "passed": all(checks.values()),
        "compiler_validation_sha256": canonical_json_sha256(core),
    }
    _COMPILER_VALIDATION_CACHE[cache_key] = copy.deepcopy(result)
    return result


def resource_ledger(fixture: Mapping[str, Any] | None = None) -> dict[str, Any]:
    contract = dict(fixture) if fixture is not None else prototype_fixture()
    rows: list[dict[str, Any]] = []
    total_pairs = 0
    total_mcx = 0
    total_mcrx = 0
    total_logical = 0
    total_negative_controls = 0
    max_hamming = 0
    for edge_raw in contract["edges"]:
        compiled = compile_edge((int(edge_raw[0]), int(edge_raw[1])), contract)
        distances = [int(row["hamming_distance"]) for row in compiled["pair_circuits"]]
        negative = sum(int(gate["negative_control_count"]) for gate in compiled["gates"])
        row = {
            "edge": compiled["edge"],
            "two_level_pair_count": compiled["pair_count"],
            "endpoint_hamming_distances": distances,
            "pattern_mcx_count": compiled["pattern_mcx_count"],
            "pattern_mcrx_count": compiled["pattern_mcrx_count"],
            "logical_gate_count": compiled["logical_gate_count"],
            "negative_control_literals": negative,
            "conservative_serial_logical_depth": compiled["logical_gate_count"],
            "edge_ir_sha256": compiled["edge_ir_sha256"],
        }
        rows.append(row)
        total_pairs += int(compiled["pair_count"])
        total_mcx += int(compiled["pattern_mcx_count"])
        total_mcrx += int(compiled["pattern_mcrx_count"])
        total_logical += int(compiled["logical_gate_count"])
        total_negative_controls += negative
        max_hamming = max(max_hamming, *distances) if distances else max_hamming
    register_width = int(register_contract(contract)["data_qubits"])
    core = {
        "ir_basis": ["PATTERN_MCX", "PATTERN_MCRX"],
        "control_semantics": "SIGNED_0_OR_1_CONTROL_ON_EVERY_NON_TARGET_QUBIT",
        "rotation_convention": "MCRX(2β) REALIZES exp(-i β X) ON THE ADDRESSED PAIR",
        "rows": rows,
        "complete_edge_scan": {
            "edge_count": len(rows),
            "two_level_pair_count": total_pairs,
            "pattern_mcx_count": total_mcx,
            "pattern_mcrx_count": total_mcrx,
            "logical_gate_count": total_logical,
            "negative_control_literals": total_negative_controls,
            "conservative_serial_logical_depth": total_logical,
            "maximum_endpoint_hamming_distance": max_hamming,
            "maximum_control_count": register_width - 1,
            "data_qubits": register_width,
            "ancilla_qubits": 0,
            "scratch_qubits": 0,
        },
        "elementary_basis_decomposition": "NOT_IMPLEMENTED",
        "one_qubit_gate_count": "NOT_ESTIMATED",
        "two_qubit_gate_count": "NOT_ESTIMATED",
        "selected_model_cnot": "NOT_ESTIMATED",
        "n40_projection": "NOT_RUN",
        "selected_model_budget_gate": "NOT_EVALUATED",
        "hardware_executable": False,
        "ledger_boundary": (
            "Counts are exact only in the declared full-width logical IR. Pattern-controlled "
            "gates are not hardware-native and are not assigned a CNOT equivalent. No V3.4 "
            "resource reduction is booked from this prototype."
        ),
    }
    return {**core, "resource_ledger_sha256": canonical_json_sha256(core)}


def coherent_transition_ledger(
    fixture: Mapping[str, Any] | None = None,
    compiler_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Seal the four actually compiled coherent portfolio/cache transitions."""

    contract = dict(fixture) if fixture is not None else prototype_fixture()
    evidence = (
        dict(compiler_evidence)
        if compiler_evidence is not None
        else exhaustive_compiler_validation(contract)
    )
    edge_reports = {
        tuple(int(value) for value in row["edge"]): row
        for row in evidence["edge_reports"]
    }
    rows: list[dict[str, Any]] = []
    for edge_raw in contract["edges"]:
        edge = (int(edge_raw[0]), int(edge_raw[1]))
        compiled = compile_edge(edge, contract)
        report = edge_reports[edge]
        for pair, circuit in zip(compiled["pairs"], compiled["pair_circuits"]):
            rows.append(
                {
                    "edge": list(edge),
                    "source_portfolio": pair["left_portfolio"],
                    "target_portfolio": pair["right_portfolio"],
                    "source_caches": pair["left_caches"],
                    "target_caches": pair["right_caches"],
                    "cache_delta": pair["cache_delta"],
                    "source_basis": pair["left_basis"],
                    "target_basis": pair["right_basis"],
                    "endpoint_hamming_distance": circuit["hamming_distance"],
                    "pair_ir_sha256": circuit["pair_ir_sha256"],
                    "logical_gate_count": circuit["logical_gate_count"],
                    "reference_action_state": (
                        "PASSED_ALL_REGISTERED_BETAS"
                        if report["maximum_action_error"] <= NUMERIC_TOLERANCE
                        else "REJECTED"
                    ),
                    "roundtrip_state": (
                        "PASSED_ALL_1024_BASIS_COLUMNS_PER_BETA"
                        if report["maximum_roundtrip_error"] <= NUMERIC_TOLERANCE
                        else "REJECTED"
                    ),
                    "off_target_identity_state": (
                        "PASSED"
                        if report["off_target_identity_exact_within_tolerance"]
                        else "REJECTED"
                    ),
                    "clean_scratch_state": "PASSED_ZERO_ANCILLA_ZERO_SCRATCH",
                }
            )
    core = {
        "transition_count": len(rows),
        "ordering": "EDGE_LEXICOGRAPHIC_THEN_ASCENDING_BASIS_ENDPOINTS",
        "rows": rows,
    }
    return {**core, "coherent_transition_ledger_sha256": canonical_json_sha256(core)}


def default_v36_artifact_path() -> Path:
    return (
        Path(__file__).resolve().parents[1]
        / "outputs"
        / "quantum_phase3"
        / "v36_reduction"
        / "SEALED_V3_6_ALGORITHMIC_REDUCTION_ARTIFACT.json"
    )


def authenticate_v36_parent(path: str | Path | None = None) -> dict[str, Any]:
    target = Path(path) if path is not None else default_v36_artifact_path()
    errors: list[str] = []
    try:
        payload = _read_json_strict(target)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {"valid": False, "errors": [str(exc)], "path": str(target)}
    integrity = validate_v36_artifact(payload)
    actual_raw = raw_file_sha256(target)
    comparisons = {
        "semantic_artifact_sha256": {
            "actual": payload.get("artifact_sha256"),
            "expected": EXPECTED_V36_ARTIFACT_SHA256,
        },
        "raw_file_sha256": {
            "actual": actual_raw,
            "expected": EXPECTED_V36_ARTIFACT_RAW_SHA256,
        },
        "predecessor_decision": {
            "actual": (payload.get("decisions") or {}).get("next_falsifiable_gate"),
            "expected": "CLEAN_REVERSIBLE_INCREMENTAL_EXPOSURE_COMPILER",
        },
        "predecessor_compiler_state": {
            "actual": (payload.get("incremental_exposure_audit") or {}).get(
                "reversible_compiler_status"
            ),
            "expected": "BLOCKED_PENDING_REVERSIBLE_COMPILER",
        },
    }
    for label, comparison in comparisons.items():
        comparison["valid"] = comparison["actual"] == comparison["expected"]
        if not comparison["valid"]:
            errors.append(f"{label} mismatch")
    if not integrity.get("valid"):
        errors.extend(f"V3.6 integrity: {error}" for error in integrity.get("errors") or [])
    boundary = payload.get("claim_boundary") or {}
    if not (
        boundary.get("hardware_executable") is False
        and boundary.get("qpu_submission_enabled") is False
        and boundary.get("qpu_jobs_submitted") == 0
        and boundary.get("quantum_advantage") == "NOT_CLAIMED"
    ):
        errors.append("V3.6 zero-job claim boundary mismatch")
    return {
        "path": str(target),
        "comparisons": comparisons,
        "v36_integrity": integrity,
        "errors": errors,
        "valid": not errors,
    }


def build_v37_artifact(
    *, v36_artifact_path: str | Path | None = None
) -> dict[str, Any]:
    spec = load_v37_spec()
    parent = authenticate_v36_parent(v36_artifact_path)
    if not parent["valid"]:
        raise ValueError("V3.7 parent authentication failed: " + "; ".join(parent["errors"]))
    # ``authenticate_v36_parent`` returns a path for interactive diagnostics,
    # but sealed science must be byte-identical in the local archive and the
    # Codespace.  Only content-derived evidence enters the artifact.
    portable_parent = {key: value for key, value in parent.items() if key != "path"}
    fixture = prototype_fixture()
    registers = register_contract(fixture)
    differential = differential_audit(fixture)
    compiler = exhaustive_compiler_validation(fixture)
    ledger = resource_ledger(fixture)
    transitions = coherent_transition_ledger(fixture, compiler)
    prototype_pass = bool(differential["passed"] and compiler["passed"])
    core = {
        "artifact_version": ARTIFACT_VERSION,
        "v37_version": V37_VERSION,
        "research_classification": "RESEARCH_ONLY",
        "prototype_classification": "PROTOTYPE_ONLY",
        "spec_sha256": spec["v37_spec_sha256"],
        "spec_raw_file_sha256": raw_file_sha256(Path(__file__).with_name(SPEC_FILENAME)),
        "source_sha256": source_sha256(),
        "parent": {
            "v36_artifact_sha256": EXPECTED_V36_ARTIFACT_SHA256,
            "v36_artifact_raw_file_sha256": EXPECTED_V36_ARTIFACT_RAW_SHA256,
            "authentication": portable_parent,
        },
        "fixture": fixture,
        "register_contract": registers,
        "differential_evidence": differential,
        "compiler_evidence": compiler,
        "coherent_transition_ledger": transitions,
        "resource_ledger": ledger,
        "decisions": {
            "overall": (
                "SMALL_INSTANCE_REVERSIBLE_PROTOTYPE_PASSED"
                if prototype_pass
                else "SMALL_INSTANCE_REVERSIBLE_PROTOTYPE_REJECTED"
            ),
            "incremental_exposure_prototype": (
                "PASSED_ON_REGISTERED_N4_K2_FIXTURE"
                if prototype_pass
                else "REJECTED_ON_REGISTERED_N4_K2_FIXTURE"
            ),
            "coherent_cache_update": "PASSED_EXHAUSTIVE_SMALL_INSTANCE" if prototype_pass else "REJECTED",
            "scratch_cleanup": "PASSED_ZERO_ANCILLA_GRAY_UNCOMPUTE" if prototype_pass else "REJECTED",
            "production_n40_compiler": "N40_REWRITE_ADMISSION_BLOCKED",
            "n40_rewrite_admission": "N40_REWRITE_ADMISSION_BLOCKED",
            "elementary_basis_decomposition": "BLOCKED_NOT_BUILT",
            "selected_model_budget": "NOT_EVALUATED",
            "backend_native": "NOT_RUN_PROVIDER_FREE_PHASE",
            "next_falsifiable_gate": "ELEMENTARY_BASIS_DECOMPOSITION_AND_N40_RESOURCE_LEDGER",
        },
        "claim_boundary": {
            "prototype_scope": "REGISTERED_SYNTHETIC_N4_K2_FIXTURE_ONLY",
            "v34_exact_successor_equivalence": "NOT_CLAIMED",
            "production_n40_equivalence": "NOT_CLAIMED",
            "selected_model_cnot": "NOT_ESTIMATED",
            "provider_sdk_imported": False,
            "provider_credentials_read": False,
            "provider_calls": 0,
            "backend_transpilation": "NOT_RUN",
            "hardware_executable": False,
            "qpu_submission_enabled": False,
            "qpu_jobs_submitted": 0,
            "optimization_performance": "NOT_TESTED",
            "global_impossibility": "NOT_CLAIMED",
            "quantum_advantage": "NOT_CLAIMED",
        },
    }
    return {**core, "artifact_sha256": canonical_json_sha256(core)}


_EXPECTED_ARTIFACT_CACHE: tuple[tuple[str, str, str], dict[str, Any]] | None = None


def _recomputed_v37_artifact() -> dict[str, Any]:
    """Rebuild the complete registered evidence contract from trusted local inputs.

    A top-level self-hash proves only that a document is internally consistent;
    it cannot prove that nested scientific claims are true.  The validation
    boundary therefore recomputes every fixture, compiler, transition, ledger,
    decision and parent field.  The cache is keyed by the three mutable input
    commitments, so changing source, specification or predecessor bytes forces
    a complete rebuild while repeated checks in one process remain practical.
    """

    global _EXPECTED_ARTIFACT_CACHE
    spec_path = Path(__file__).with_name(SPEC_FILENAME)
    parent_path = default_v36_artifact_path()
    key = (
        source_sha256(),
        raw_file_sha256(spec_path),
        raw_file_sha256(parent_path),
    )
    if _EXPECTED_ARTIFACT_CACHE is None or _EXPECTED_ARTIFACT_CACHE[0] != key:
        _EXPECTED_ARTIFACT_CACHE = (key, build_v37_artifact())
    return _EXPECTED_ARTIFACT_CACHE[1]


def validate_v37_artifact(payload: Mapping[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if not isinstance(payload, Mapping):
        return {"valid": False, "errors": ["Artifact must be an object."]}
    core = {key: value for key, value in payload.items() if key != "artifact_sha256"}
    try:
        computed = canonical_json_sha256(core)
    except (TypeError, ValueError, OverflowError) as exc:
        return {"valid": False, "errors": [str(exc)]}
    if payload.get("artifact_sha256") != computed:
        errors.append("Artifact SHA-256 mismatch.")
    if payload.get("artifact_version") != ARTIFACT_VERSION:
        errors.append("Artifact version mismatch.")
    if payload.get("research_classification") != "RESEARCH_ONLY":
        errors.append("Research classification mismatch.")
    if payload.get("prototype_classification") != "PROTOTYPE_ONLY":
        errors.append("Prototype classification mismatch.")
    try:
        expected_artifact = _recomputed_v37_artifact()
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        expected_artifact = {}
        errors.append(f"Trusted V3.7 evidence recomputation failed: {exc}")
    if expected_artifact:
        if set(payload) != set(expected_artifact):
            errors.append("Artifact schema differs from the registered evidence contract.")
        for key, expected_value in expected_artifact.items():
            if key == "artifact_sha256":
                continue
            if payload.get(key) != expected_value:
                errors.append(f"Recomputed V3.7 evidence mismatch: {key}.")
        if payload.get("artifact_sha256") != expected_artifact.get("artifact_sha256"):
            errors.append("Artifact identity differs from recomputed registered evidence.")
    try:
        spec = load_v37_spec()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"V3.7 specification invalid: {exc}")
        spec = {}
    if payload.get("spec_sha256") != spec.get("v37_spec_sha256"):
        errors.append("V3.7 specification commitment mismatch.")
    expected_spec_raw = raw_file_sha256(Path(__file__).with_name(SPEC_FILENAME))
    if payload.get("spec_raw_file_sha256") != expected_spec_raw:
        errors.append("V3.7 raw specification commitment mismatch.")
    parent = (payload.get("parent") or {}).get("authentication") or {}
    differential = payload.get("differential_evidence") or {}
    compiler = payload.get("compiler_evidence") or {}
    transitions = payload.get("coherent_transition_ledger") or {}
    ledger = payload.get("resource_ledger") or {}
    decisions = payload.get("decisions") or {}
    boundary = payload.get("claim_boundary") or {}
    if parent.get("valid") is not True:
        errors.append("V3.6 parent authentication is not valid.")
    if differential.get("passed") is not True:
        errors.append("Differential audit is not passing.")
    if compiler.get("passed") is not True:
        errors.append("Exhaustive compiler validation is not passing.")
    if compiler.get("full_domain_basis_states") != 1024:
        errors.append("Full-domain validation width mismatch.")
    if not (
        transitions.get("transition_count") == 4
        and len(transitions.get("rows") or []) == 4
        and all(
            row.get("reference_action_state") == "PASSED_ALL_REGISTERED_BETAS"
            and row.get("roundtrip_state") == "PASSED_ALL_1024_BASIS_COLUMNS_PER_BETA"
            and row.get("clean_scratch_state") == "PASSED_ZERO_ANCILLA_ZERO_SCRATCH"
            for row in transitions.get("rows") or []
        )
    ):
        errors.append("Coherent transition ledger is incomplete or not passing.")
    if (ledger.get("complete_edge_scan") or {}).get("ancilla_qubits") != 0:
        errors.append("Ancilla ledger is not zero.")
    if ledger.get("selected_model_cnot") != "NOT_ESTIMATED":
        errors.append("Prototype improperly claims a selected-model CNOT estimate.")
    if decisions.get("overall") != "SMALL_INSTANCE_REVERSIBLE_PROTOTYPE_PASSED":
        errors.append("Prototype pass decision is absent.")
    if decisions.get("production_n40_compiler") != "N40_REWRITE_ADMISSION_BLOCKED":
        errors.append("N40 production barrier is absent.")
    if not (
        boundary.get("prototype_scope") == "REGISTERED_SYNTHETIC_N4_K2_FIXTURE_ONLY"
        and boundary.get("production_n40_equivalence") == "NOT_CLAIMED"
        and boundary.get("provider_calls") == 0
        and boundary.get("hardware_executable") is False
        and boundary.get("qpu_submission_enabled") is False
        and boundary.get("qpu_jobs_submitted") == 0
        and boundary.get("quantum_advantage") == "NOT_CLAIMED"
    ):
        errors.append("Fail-closed claim boundary mismatch.")
    return {
        "valid": not errors,
        "errors": errors,
        "artifact_sha256_computed": computed,
        "artifact_sha256_stored": payload.get("artifact_sha256"),
    }


def default_v37_artifact_path() -> Path:
    return (
        Path(__file__).resolve().parents[1]
        / "outputs"
        / "quantum_phase3"
        / "v37_reversible"
        / DEFAULT_ARTIFACT_NAME
    )


def load_v37_artifact(
    path: str | Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load the sealed V3.7 artifact and return its fail-closed integrity report."""

    target = Path(path) if path is not None else default_v37_artifact_path()
    payload = _read_json_strict(target)
    return payload, validate_v37_artifact(payload)


def seal_v37_artifact(
    path: str | Path | None = None,
    *,
    v36_artifact_path: str | Path | None = None,
) -> dict[str, Any]:
    target = Path(path) if path is not None else default_v37_artifact_path()
    artifact = build_v37_artifact(v36_artifact_path=v36_artifact_path)
    report = validate_v37_artifact(artifact)
    if not report["valid"]:
        raise ValueError("Refusing to seal invalid V3.7 artifact: " + "; ".join(report["errors"]))
    encoded = json.dumps(artifact, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8") + b"\n"
    if target.exists():
        if target.read_bytes() != encoded:
            raise FileExistsError(f"Refusing to overwrite non-identical V3.7 artifact: {target}")
        return {"artifact": artifact, "created": False, "path": str(target)}
    target.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(target, flags, 0o644)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            target.unlink()
        except OSError:
            pass
        raise
    return {"artifact": artifact, "created": True, "path": str(target)}


__all__ = [
    "ARTIFACT_VERSION",
    "DEFAULT_ARTIFACT_NAME",
    "EXPECTED_V36_ARTIFACT_RAW_SHA256",
    "EXPECTED_V36_ARTIFACT_SHA256",
    "NUMERIC_TOLERANCE",
    "SPEC_FILENAME",
    "VALIDATION_BETAS",
    "V37_VERSION",
    "apply_adjoint_gate_sequence",
    "apply_gate",
    "apply_gate_sequence",
    "apply_ideal_edge_action",
    "authenticate_v36_parent",
    "build_v37_artifact",
    "compile_edge",
    "compile_two_level_pair",
    "coherent_transition_ledger",
    "decode_basis_state",
    "default_v37_artifact_path",
    "differential_audit",
    "encode_basis_state",
    "exact_k_states",
    "exhaustive_compiler_validation",
    "exposure_values",
    "gray_path",
    "ideal_edge_action",
    "load_v37_spec",
    "load_v37_artifact",
    "portfolio_feasible",
    "prospective_exposure_values",
    "prototype_fixture",
    "register_contract",
    "resource_ledger",
    "seal_v37_artifact",
    "source_sha256",
    "swap_bits",
    "transition_pairs",
    "validate_v37_artifact",
    "values_feasible",
]
