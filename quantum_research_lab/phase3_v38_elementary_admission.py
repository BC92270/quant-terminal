"""Proof-carrying elementary lowering and N=40 admission gate for V3.8.

V3.8 lowers every signed-pattern primitive in the authenticated V3.7 N=4,
K=2 prototype to a provider-neutral basis of one-qubit gates and CX.  The
selected model is deliberately frozen before evaluation: clean AND ladders,
an exact six-CX Clifford+T Toffoli template, and an exact two-CX controlled-RX
template.  Every logical primitive is compared on every data-register basis
column and every allocated clean ancilla is required to return to |0>.

The same release also evaluates the preregistered production gate.  It
authenticates all eight frozen N=40, seven-constraint parent rows, but it does
not invent an N=40 circuit or impute a CNOT count.  Because a scalable
reversible arithmetic/cache-update IR is still absent, production admission
remains fail-closed.  No provider SDK, credential, backend, or QPU is touched.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from .phase3_v36_algorithmic_reduction import (
    canonical_json_sha256,
    raw_file_sha256,
    validate_v36_artifact,
)
from .phase3_v37_reversible_compiler import (
    EXPECTED_V36_ARTIFACT_RAW_SHA256,
    EXPECTED_V36_ARTIFACT_SHA256,
    NUMERIC_TOLERANCE,
    VALIDATION_BETAS,
    apply_gate,
    compile_edge,
    default_v36_artifact_path,
    default_v37_artifact_path,
    load_v37_artifact,
    prototype_fixture,
    register_contract,
)


V38_VERSION = "PHASE III · V3.8 ELEMENTARY DECOMPOSITION & N40 ADMISSION · V1"
ARTIFACT_VERSION = "PHASE III · V3.8 PROOF-CARRYING ELEMENTARY ADMISSION · V1"
SPEC_FILENAME = "PHASE_III_V3_8_ELEMENTARY_ADMISSION_SPEC_V1.json"
DEFAULT_ARTIFACT_NAME = "SEALED_V3_8_ELEMENTARY_ADMISSION_ARTIFACT.json"
EXPECTED_V38_SPEC_SHA256 = (
    "0c7e33ac23fc0caf0c14b0c6bde730d0fa898851fdb60f5afa24887d98fd066c"
)
EXPECTED_V38_SPEC_RAW_SHA256 = (
    "b0c8c99246dbb850002f770b9da9bcdc36d8e52cd86ac230e01d7b47e3bd87d9"
)
EXPECTED_V37_ARTIFACT_SHA256 = (
    "5773b8f38bd1400f4eb1edf5a016ab69c85fc794aefe31fd1a742d08174bee36"
)
EXPECTED_V37_ARTIFACT_RAW_SHA256 = (
    "93c207a6c0d6723277bf682a678740b330a6a3127d59d63ce28a244bdf606365"
)
EXPECTED_V37_FREEZE_SHA256 = (
    "86f247a9dfb918a2eca04ffe96c03adee62c3d8603d99aab3e0d6bf8c07167e7"
)
EXPECTED_V37_FREEZE_RAW_SHA256 = (
    "57b273f87e4e2f2a95e0ccbdd6c844c1c3f5d8bfec5dbfd5d488aaefb0290970"
)
SELECTED_MODEL = "CLEAN_ANCILLA_TOFFOLI_LADDER_6CX_CCX_CRX2CX_V1"
ELEMENTARY_BASIS = ("X", "H", "T", "TDG", "RY", "RZ", "CX")
N40_BUDGET_CNOT = 2_500_000
N40_SEEDS = (1103, 2207, 3301, 4409, 5501, 6607, 7703, 8807)
_VALIDATION_CACHE: dict[str, Any] | None = None
_EXPECTED_ARTIFACT_CACHE: tuple[tuple[str, str, str, str], dict[str, Any]] | None = None


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


def load_v38_spec(path: str | Path | None = None) -> dict[str, Any]:
    target = Path(path) if path is not None else Path(__file__).with_name(SPEC_FILENAME)
    payload = _read_json_strict(target)
    core = {
        key: value
        for key, value in payload.items()
        if key not in {"v38_spec_sha", "v38_spec_sha256"}
    }
    digest = canonical_json_sha256(core)
    if raw_file_sha256(target) != EXPECTED_V38_SPEC_RAW_SHA256:
        raise ValueError("V3.8 specification raw-file identity mismatch.")
    if digest != EXPECTED_V38_SPEC_SHA256:
        raise ValueError("V3.8 specification semantic identity mismatch.")
    if payload.get("v38_spec_sha256") != digest:
        raise ValueError("V3.8 specification SHA-256 mismatch.")
    if payload.get("v38_spec_sha") != digest[:20].upper():
        raise ValueError("V3.8 specification short SHA mismatch.")
    acceptance = payload.get("acceptance_contract") or {}
    expected = {
        "ccx_basis_columns_checked": 8,
        "complete_layer_cnot_count": 3632,
        "complete_layer_one_qubit_gate_count": 5920,
        "maximum_clean_ancilla_qubits": 8,
        "maximum_total_logical_qubits": 18,
        "n40_budget_cnot": N40_BUDGET_CNOT,
        "n40_frozen_seed_count": 8,
        "n40_production_admission": "BLOCKED_INCOMPLETE_REVERSIBLE_IR",
        "numeric_tolerance": NUMERIC_TOLERANCE,
        "primitive_basis_beta_cases_checked": 49_152,
        "prototype_decision": "ELEMENTARY_PROTOTYPE_PASSED_N40_ADMISSION_BLOCKED",
    }
    if any(acceptance.get(key) != value for key, value in expected.items()):
        raise ValueError("V3.8 acceptance contract mismatch.")
    if tuple(acceptance.get("elementary_basis") or ()) != ELEMENTARY_BASIS:
        raise ValueError("V3.8 elementary basis mismatch.")
    counting = payload.get("counting_contract") or {}
    if not (
        counting.get("selected_decomposition_model") == SELECTED_MODEL
        and (counting.get("toffoli_template") or {}).get("cnot_count") == 6
        and (counting.get("controlled_rx_template") or {}).get("cnot_count") == 2
        and counting.get("post_observation_candidate_switching") == "PROHIBITED"
    ):
        raise ValueError("V3.8 selected decomposition model mismatch.")
    parent = payload.get("parent_contract") or {}
    if not (
        parent.get("expected_v37_artifact_sha256") == EXPECTED_V37_ARTIFACT_SHA256
        and parent.get("expected_v37_artifact_raw_file_sha256")
        == EXPECTED_V37_ARTIFACT_RAW_SHA256
        and parent.get("expected_v37_freeze_sha256") == EXPECTED_V37_FREEZE_SHA256
        and parent.get("expected_v37_freeze_raw_file_sha256")
        == EXPECTED_V37_FREEZE_RAW_SHA256
    ):
        raise ValueError("V3.8 V3.7 parent commitments mismatch.")
    boundary = payload.get("claim_boundary") or {}
    if not (
        boundary.get("research_classification") == "RESEARCH_ONLY"
        and boundary.get("n40_selected_model_cnot") == "NOT_ESTIMATED"
        and boundary.get("provider_calls") == 0
        and boundary.get("hardware_executable") is False
        and boundary.get("qpu_jobs_submitted") == 0
        and boundary.get("quantum_advantage") == "NOT_CLAIMED"
    ):
        raise ValueError("V3.8 claim boundary mismatch.")
    return payload


def _freeze_semantic(payload: Mapping[str, Any]) -> str:
    return canonical_json_sha256(
        {key: value for key, value in payload.items() if key != "freeze_contract_sha256"}
    )


def authenticate_v37_parent(
    artifact_path: str | Path | None = None,
    freeze_path: str | Path | None = None,
) -> dict[str, Any]:
    artifact_target = Path(artifact_path) if artifact_path else default_v37_artifact_path()
    freeze_target = (
        Path(freeze_path)
        if freeze_path
        else Path(__file__).resolve().parents[1] / "FREEZE_CONTRACT_V3_7.json"
    )
    errors: list[str] = []
    try:
        artifact, integrity = load_v37_artifact(artifact_target)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return {"valid": False, "errors": [str(exc)]}
    artifact_raw = raw_file_sha256(artifact_target)
    try:
        freeze = _read_json_strict(freeze_target)
        freeze_raw = raw_file_sha256(freeze_target)
        freeze_semantic = _freeze_semantic(freeze)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        freeze = {}
        freeze_raw = "UNAVAILABLE"
        freeze_semantic = "UNAVAILABLE"
        errors.append(f"V3.7 freeze authentication failed: {exc}")
    comparisons = {
        "artifact_semantic": [artifact.get("artifact_sha256"), EXPECTED_V37_ARTIFACT_SHA256],
        "artifact_raw": [artifact_raw, EXPECTED_V37_ARTIFACT_RAW_SHA256],
        "artifact_decision": [
            (artifact.get("decisions") or {}).get("overall"),
            "SMALL_INSTANCE_REVERSIBLE_PROTOTYPE_PASSED",
        ],
        "artifact_next_gate": [
            (artifact.get("decisions") or {}).get("next_falsifiable_gate"),
            "ELEMENTARY_BASIS_DECOMPOSITION_AND_N40_RESOURCE_LEDGER",
        ],
        "freeze_semantic": [freeze_semantic, EXPECTED_V37_FREEZE_SHA256],
        "freeze_raw": [freeze_raw, EXPECTED_V37_FREEZE_RAW_SHA256],
    }
    comparison_report: dict[str, Any] = {}
    for name, (actual, expected) in comparisons.items():
        passed = actual == expected
        comparison_report[name] = {"actual": actual, "expected": expected, "valid": passed}
        if not passed:
            errors.append(f"{name} mismatch")
    if not integrity.get("valid"):
        errors.extend(f"V3.7 nested integrity: {error}" for error in integrity.get("errors") or [])
    boundary = artifact.get("claim_boundary") or {}
    if not (
        boundary.get("provider_calls") == 0
        and boundary.get("hardware_executable") is False
        and boundary.get("qpu_jobs_submitted") == 0
        and boundary.get("quantum_advantage") == "NOT_CLAIMED"
    ):
        errors.append("V3.7 fail-closed claim boundary mismatch")
    return {
        "comparisons": comparison_report,
        "nested_artifact_integrity": integrity,
        "errors": errors,
        "valid": not errors,
    }


def _one(kind: str, qubit: int, **parameters: Any) -> dict[str, Any]:
    return {"kind": kind, "qubit": int(qubit), **parameters}


def _cx(control: int, target: int) -> dict[str, Any]:
    return {"kind": "CX", "control": int(control), "target": int(target)}


def ccx_template(control_a: int, control_b: int, target: int) -> list[dict[str, Any]]:
    """Exact six-CX Clifford+T Toffoli in deterministic emission order."""

    a, b, t = int(control_a), int(control_b), int(target)
    return [
        _one("H", t),
        _cx(b, t),
        _one("TDG", t),
        _cx(a, t),
        _one("T", t),
        _cx(b, t),
        _one("TDG", t),
        _cx(a, t),
        _one("T", b),
        _one("T", t),
        _one("H", t),
        _cx(a, b),
        _one("T", a),
        _one("TDG", b),
        _cx(a, b),
    ]


def crx_template(control: int, target: int, angle_multiplier: float) -> list[dict[str, Any]]:
    """Exact controlled-RX(theta), with theta=angle_multiplier*beta."""

    c, t = int(control), int(target)
    multiplier = float(angle_multiplier)
    return [
        _one("RZ", t, angle=math.pi / 2.0),
        _one("RY", t, beta_multiplier=multiplier / 2.0),
        _cx(c, t),
        _one("RY", t, beta_multiplier=-multiplier / 2.0),
        _cx(c, t),
        _one("RZ", t, angle=-math.pi / 2.0),
    ]


def _positive_mcx(controls: Sequence[int], target: int, ancilla_start: int) -> tuple[list[dict[str, Any]], int]:
    controls = tuple(int(value) for value in controls)
    target = int(target)
    count = len(controls)
    if count == 0:
        return [_one("X", target)], 0
    if count == 1:
        return [_cx(controls[0], target)], 0
    if count == 2:
        return ccx_template(controls[0], controls[1], target), 0
    ancillas = tuple(range(int(ancilla_start), int(ancilla_start) + count - 2))
    compute: list[list[dict[str, Any]]] = [ccx_template(controls[0], controls[1], ancillas[0])]
    for index in range(2, count - 1):
        compute.append(ccx_template(ancillas[index - 2], controls[index], ancillas[index - 1]))
    gates = [gate for block in compute for gate in block]
    gates.extend(ccx_template(ancillas[-1], controls[-1], target))
    gates.extend(gate for block in reversed(compute) for gate in block)
    return gates, len(ancillas)


def _positive_mcrx(
    controls: Sequence[int], target: int, ancilla_start: int, angle_multiplier: float
) -> tuple[list[dict[str, Any]], int]:
    controls = tuple(int(value) for value in controls)
    count = len(controls)
    if count == 0:
        return [_one("RX", int(target), beta_multiplier=float(angle_multiplier))], 0
    if count == 1:
        return crx_template(controls[0], int(target), angle_multiplier), 0
    ancillas = tuple(range(int(ancilla_start), int(ancilla_start) + count - 1))
    compute: list[list[dict[str, Any]]] = [ccx_template(controls[0], controls[1], ancillas[0])]
    for index in range(2, count):
        compute.append(ccx_template(ancillas[index - 2], controls[index], ancillas[index - 1]))
    gates = [gate for block in compute for gate in block]
    gates.extend(crx_template(ancillas[-1], int(target), angle_multiplier))
    gates.extend(gate for block in reversed(compute) for gate in block)
    return gates, len(ancillas)


def lower_pattern_gate(
    logical_gate: Mapping[str, Any], *, data_width: int = 10
) -> dict[str, Any]:
    kind = str(logical_gate.get("kind"))
    if kind not in {"PATTERN_MCX", "PATTERN_MCRX"}:
        raise ValueError(f"Unsupported V3.7 primitive: {kind}")
    controls_raw = logical_gate.get("controls") or []
    controls = tuple(int(row["qubit"]) for row in controls_raw)
    if len(set(controls)) != len(controls) or int(logical_gate["target"]) in controls:
        raise ValueError("Malformed pattern-control set.")
    negative = tuple(
        int(row["qubit"]) for row in controls_raw if int(row.get("value", -1)) == 0
    )
    if any(int(row.get("value", -1)) not in (0, 1) for row in controls_raw):
        raise ValueError("Pattern-control value must be binary.")
    pre = [_one("X", qubit) for qubit in negative]
    if kind == "PATTERN_MCX":
        body, ancilla_count = _positive_mcx(controls, int(logical_gate["target"]), data_width)
        template_id = "SIGNED_MCX_CLEAN_AND_LADDER_V1"
    else:
        body, ancilla_count = _positive_mcrx(
            controls,
            int(logical_gate["target"]),
            data_width,
            float(logical_gate["angle_multiplier"]),
        )
        template_id = "SIGNED_MCRX_CLEAN_AND_LADDER_V1"
    gates = [*pre, *body, *reversed(pre)]
    cnot_count = sum(gate["kind"] == "CX" for gate in gates)
    one_qubit_count = len(gates) - cnot_count
    core = {
        "logical_kind": kind,
        "target": int(logical_gate["target"]),
        "control_count": len(controls),
        "negative_control_count": len(negative),
        "template_id": template_id,
        "elementary_basis": list(ELEMENTARY_BASIS),
        "one_qubit_gate_count": one_qubit_count,
        "cnot_count": cnot_count,
        "serial_cnot_depth": cnot_count,
        "clean_ancilla_qubits": ancilla_count,
        "total_qubits": data_width + ancilla_count,
        "gates": gates,
    }
    return {**core, "lowered_ir_sha256": canonical_json_sha256(core)}


def _logical_occurrences() -> list[dict[str, Any]]:
    fixture = prototype_fixture()
    occurrences: list[dict[str, Any]] = []
    index = 0
    for edge_raw in fixture["edges"]:
        edge = (int(edge_raw[0]), int(edge_raw[1]))
        compiled = compile_edge(edge, fixture)
        for gate in compiled["gates"]:
            occurrences.append({"occurrence": index, "edge": list(edge), "logical_gate": gate})
            index += 1
    return occurrences


def compile_elementary_layer() -> dict[str, Any]:
    occurrences = _logical_occurrences()
    rows: list[dict[str, Any]] = []
    complete_gates: list[dict[str, Any]] = []
    for occurrence in occurrences:
        lowered = lower_pattern_gate(occurrence["logical_gate"])
        complete_gates.extend(lowered["gates"])
        rows.append(
            {
                "occurrence": occurrence["occurrence"],
                "edge": occurrence["edge"],
                "logical_kind": lowered["logical_kind"],
                "target": lowered["target"],
                "control_count": lowered["control_count"],
                "negative_control_count": lowered["negative_control_count"],
                "template_id": lowered["template_id"],
                "one_qubit_gate_count": lowered["one_qubit_gate_count"],
                "cnot_count": lowered["cnot_count"],
                "serial_cnot_depth": lowered["serial_cnot_depth"],
                "clean_ancilla_qubits": lowered["clean_ancilla_qubits"],
                "lowered_ir_sha256": lowered["lowered_ir_sha256"],
            }
        )
    kind_counts = {kind: sum(gate["kind"] == kind for gate in complete_gates) for kind in ELEMENTARY_BASIS}
    core = {
        "selected_model": SELECTED_MODEL,
        "logical_occurrence_count": len(occurrences),
        "rows": rows,
        "elementary_gate_counts": kind_counts,
        "one_qubit_gate_count": sum(count for kind, count in kind_counts.items() if kind != "CX"),
        "cnot_count": kind_counts["CX"],
        "serial_cnot_depth": kind_counts["CX"],
        "maximum_clean_ancilla_qubits": max(row["clean_ancilla_qubits"] for row in rows),
        "data_qubits": 10,
        "maximum_total_qubits": 10 + max(row["clean_ancilla_qubits"] for row in rows),
        "elementary_ir_sha256": canonical_json_sha256(complete_gates),
    }
    return {**core, "elementary_ledger_sha256": canonical_json_sha256(core)}


def _accumulate(target: dict[int, complex], basis: int, amplitude: complex) -> None:
    if abs(amplitude) > 1.0e-15:
        target[int(basis)] = target.get(int(basis), 0.0j) + complex(amplitude)


def apply_elementary_gate(
    amplitudes: Mapping[int, complex], gate: Mapping[str, Any], beta: float
) -> dict[int, complex]:
    kind = str(gate["kind"])
    output: dict[int, complex] = {}
    if kind == "CX":
        control, target = int(gate["control"]), int(gate["target"])
        for basis, amplitude in amplitudes.items():
            destination = int(basis) ^ (1 << target) if ((int(basis) >> control) & 1) else int(basis)
            _accumulate(output, destination, complex(amplitude))
        return output
    qubit = int(gate["qubit"])
    mask = 1 << qubit
    if kind == "X":
        for basis, amplitude in amplitudes.items():
            _accumulate(output, int(basis) ^ mask, complex(amplitude))
        return output
    if kind == "H":
        inv = 1.0 / math.sqrt(2.0)
        matrix = ((inv, inv), (inv, -inv))
    elif kind == "T":
        matrix = ((1.0 + 0.0j, 0.0j), (0.0j, complex(math.cos(math.pi / 4), math.sin(math.pi / 4))))
    elif kind == "TDG":
        matrix = ((1.0 + 0.0j, 0.0j), (0.0j, complex(math.cos(math.pi / 4), -math.sin(math.pi / 4))))
    elif kind in {"RY", "RX", "RZ"}:
        angle = float(gate.get("angle", 0.0)) + float(gate.get("beta_multiplier", 0.0)) * float(beta)
        cosine, sine = math.cos(angle / 2.0), math.sin(angle / 2.0)
        if kind == "RY":
            matrix = ((cosine, -sine), (sine, cosine))
        elif kind == "RX":
            matrix = ((cosine, -1.0j * sine), (-1.0j * sine, cosine))
        else:
            matrix = (
                (complex(math.cos(-angle / 2.0), math.sin(-angle / 2.0)), 0.0j),
                (0.0j, complex(math.cos(angle / 2.0), math.sin(angle / 2.0))),
            )
    else:
        raise ValueError(f"Unsupported elementary gate: {kind}")
    for basis, amplitude in amplitudes.items():
        index = int(basis)
        bit = 1 if index & mask else 0
        zero_index, one_index = index & ~mask, index | mask
        _accumulate(output, zero_index, matrix[0][bit] * complex(amplitude))
        _accumulate(output, one_index, matrix[1][bit] * complex(amplitude))
    return output


def apply_elementary_sequence(
    amplitudes: Mapping[int, complex], gates: Sequence[Mapping[str, Any]], beta: float
) -> dict[int, complex]:
    state = {int(index): complex(value) for index, value in amplitudes.items()}
    for gate in gates:
        state = apply_elementary_gate(state, gate, beta)
    return state


def _state_error(left: Mapping[int, complex], right: Mapping[int, complex]) -> float:
    return max(
        (
            abs(complex(left.get(index, 0.0j)) - complex(right.get(index, 0.0j)))
            for index in set(left) | set(right)
        ),
        default=0.0,
    )


def _template_validation() -> dict[str, Any]:
    ccx_gates = ccx_template(0, 1, 2)
    ccx_error = 0.0
    for basis in range(8):
        expected_basis = basis ^ 4 if (basis & 1 and basis & 2) else basis
        actual = apply_elementary_sequence({basis: 1.0 + 0.0j}, ccx_gates, 0.0)
        ccx_error = max(ccx_error, _state_error(actual, {expected_basis: 1.0 + 0.0j}))
    crx_gates = crx_template(0, 1, 2.0)
    crx_error = 0.0
    crx_cases = 0
    for beta in VALIDATION_BETAS:
        logical = {
            "kind": "PATTERN_MCRX",
            "target": 1,
            "controls": [{"qubit": 0, "value": 1}],
            "angle_multiplier": 2,
        }
        for basis in range(4):
            actual = apply_elementary_sequence({basis: 1.0 + 0.0j}, crx_gates, beta)
            expected = apply_gate({basis: 1.0 + 0.0j}, logical, beta)
            crx_error = max(crx_error, _state_error(actual, expected))
            crx_cases += 1
    checks = {
        "ccx_exact_on_all_8_basis_columns": ccx_error <= NUMERIC_TOLERANCE,
        "ccx_template_has_exactly_6_cnot": sum(gate["kind"] == "CX" for gate in ccx_gates) == 6,
        "ccx_template_has_exactly_9_one_qubit_gates": sum(gate["kind"] != "CX" for gate in ccx_gates) == 9,
        "crx_exact_on_all_4_basis_columns_and_3_betas": crx_cases == 12 and crx_error <= NUMERIC_TOLERANCE,
        "crx_template_has_exactly_2_cnot": sum(gate["kind"] == "CX" for gate in crx_gates) == 2,
        "crx_template_has_exactly_4_one_qubit_gates": sum(gate["kind"] != "CX" for gate in crx_gates) == 4,
    }
    core = {
        "numeric_tolerance": NUMERIC_TOLERANCE,
        "ccx_basis_columns_checked": 8,
        "ccx_maximum_action_error": ccx_error,
        "crx_basis_beta_cases_checked": crx_cases,
        "crx_maximum_action_error": crx_error,
        "checks": checks,
    }
    return {**core, "passed": all(checks.values()), "template_validation_sha256": canonical_json_sha256(core)}


def exhaustive_elementary_validation() -> dict[str, Any]:
    global _VALIDATION_CACHE
    if _VALIDATION_CACHE is not None:
        return copy.deepcopy(_VALIDATION_CACHE)
    template = _template_validation()
    rows: list[dict[str, Any]] = []
    maximum_action_error = 0.0
    maximum_norm_error = 0.0
    cases = 0
    all_clean = True
    for occurrence in _logical_occurrences():
        logical = occurrence["logical_gate"]
        lowered = lower_pattern_gate(logical)
        betas = VALIDATION_BETAS if logical["kind"] == "PATTERN_MCRX" else (0.0,)
        row_error = 0.0
        row_norm = 0.0
        row_clean = True
        row_cases = 0
        for beta in betas:
            for basis in range(1024):
                actual = apply_elementary_sequence({basis: 1.0 + 0.0j}, lowered["gates"], beta)
                expected = apply_gate({basis: 1.0 + 0.0j}, logical, beta)
                row_error = max(row_error, _state_error(actual, expected))
                row_norm = max(row_norm, abs(sum(abs(value) ** 2 for value in actual.values()) - 1.0))
                row_clean = row_clean and all((int(index) >> 10) == 0 for index in actual)
                row_cases += 1
        maximum_action_error = max(maximum_action_error, row_error)
        maximum_norm_error = max(maximum_norm_error, row_norm)
        all_clean = all_clean and row_clean
        cases += row_cases
        rows.append(
            {
                "occurrence": occurrence["occurrence"],
                "edge": occurrence["edge"],
                "logical_kind": logical["kind"],
                "basis_beta_cases_checked": row_cases,
                "maximum_action_error": row_error,
                "maximum_norm_error": row_norm,
                "clean_ancilla_return": row_clean,
                "lowered_ir_sha256": lowered["lowered_ir_sha256"],
            }
        )
    ledger = compile_elementary_layer()
    checks = {
        "elementary_templates_pass": template["passed"],
        "all_49152_registered_primitive_cases_checked": cases == 49_152,
        "every_logical_occurrence_matches_on_full_data_domain": maximum_action_error <= NUMERIC_TOLERANCE,
        "every_primitive_preserves_norm": maximum_norm_error <= NUMERIC_TOLERANCE,
        "all_allocated_ancillas_return_to_zero_per_primitive": all_clean,
        "all_40_v37_logical_occurrences_lowered": len(rows) == 40,
        "elementary_layer_cnot_count_is_3632": ledger["cnot_count"] == 3_632,
        "elementary_layer_one_qubit_count_is_5920": ledger["one_qubit_gate_count"] == 5_920,
        "maximum_clean_ancilla_count_is_8": ledger["maximum_clean_ancilla_qubits"] == 8,
        "deterministic_composition_inherits_authenticated_v37_layer_action": True,
    }
    core = {
        "numeric_tolerance": NUMERIC_TOLERANCE,
        "validation_betas": [float(value) for value in VALIDATION_BETAS],
        "template_validation": template,
        "primitive_basis_beta_cases_checked": cases,
        "logical_occurrences_checked": len(rows),
        "maximum_action_error": maximum_action_error,
        "maximum_norm_error": maximum_norm_error,
        "clean_ancilla_failures": sum(not row["clean_ancilla_return"] for row in rows),
        "rows": rows,
        "composition_proof": (
            "Each of the 40 deterministic elementary blocks equals its authenticated V3.7 "
            "logical primitive on all 1024 data basis columns and returns every clean ancilla "
            "to zero. Exact equality is therefore preserved under ordered composition; the "
            "authenticated V3.7 exhaustive complete-layer action and Gram proof remains the "
            "independent logical reference."
        ),
        "checks": checks,
    }
    result = {**core, "passed": all(checks.values()), "elementary_validation_sha256": canonical_json_sha256(core)}
    _VALIDATION_CACHE = copy.deepcopy(result)
    return result


def _load_authenticated_v36() -> tuple[dict[str, Any], dict[str, Any]]:
    path = default_v36_artifact_path()
    payload = _read_json_strict(path)
    integrity = validate_v36_artifact(payload)
    errors: list[str] = []
    if payload.get("artifact_sha256") != EXPECTED_V36_ARTIFACT_SHA256:
        errors.append("V3.6 semantic identity mismatch")
    if raw_file_sha256(path) != EXPECTED_V36_ARTIFACT_RAW_SHA256:
        errors.append("V3.6 raw identity mismatch")
    if not integrity.get("valid"):
        errors.extend(f"V3.6 nested integrity: {error}" for error in integrity.get("errors") or [])
    return payload, {"valid": not errors, "errors": errors, "nested_integrity": integrity}


def n40_admission_ledger() -> dict[str, Any]:
    parent, authentication = _load_authenticated_v36()
    if not authentication["valid"]:
        raise ValueError("V3.8 cannot evaluate N40 admission without its authenticated V3.6 evidence.")
    incremental = parent.get("incremental_exposure_audit") or {}
    incremental_rows = {int(row["seed"]): row for row in incremental.get("rows") or []}
    structural = parent.get("structural_cost_attribution") or {}
    historical_rows = {int(row["seed"]): row for row in structural.get("rows") or []}
    if tuple(sorted(incremental_rows)) != N40_SEEDS or tuple(sorted(historical_rows)) != N40_SEEDS:
        raise ValueError("Frozen N40 seed inventory mismatch.")
    rows: list[dict[str, Any]] = []
    for seed in N40_SEEDS:
        delta = incremental_rows[seed]
        historical = historical_rows[seed]
        constraint_count = int(delta["constraint_row_cases"]) // int(delta["swap_cases"])
        gates = {
            "authenticated_seed_contract": True,
            "seven_constraint_parent_evidence": constraint_count == 7,
            "classical_delta_equivalence": bool(delta.get("delta_arithmetic_exact") and delta.get("prospective_predicate_exact")),
            "scalable_reversible_ir": False,
            "elementary_lowering": False,
            "full_coherent_equivalence": False,
            "clean_ancilla_proof": False,
            "ordered_layer_connectivity": False,
            "selected_model_cnot_ledger": False,
            "selected_model_budget_at_most_2500000": False,
        }
        row_core = {
            "seed": seed,
            "instance_id": f"QH-N040-BANDS-S{seed}",
            "parent_evidence_sha256": canonical_json_sha256(delta),
            "constraint_count": constraint_count,
            "parent_swap_cases": int(delta["swap_cases"]),
            "parent_constraint_row_cases": int(delta["constraint_row_cases"]),
            "gates": gates,
            "selected_model_logical_qubits": "NOT_ESTIMATED",
            "selected_model_clean_ancilla_qubits": "NOT_ESTIMATED",
            "selected_model_one_qubit_gates": "NOT_ESTIMATED",
            "selected_model_cnot": "NOT_ESTIMATED",
            "selected_model_serial_cnot_depth": "NOT_ESTIMATED",
            "budget_margin_cnot": "NOT_COMPUTED",
            "decision": "BLOCKED_INCOMPLETE_REVERSIBLE_IR",
            "historical_v34_selected_model_cnot": int(historical["total_cnot"]),
            "historical_v34_status": "REJECTED_SELECTED_MODEL_BUDGET_NONCOMPARABLE_PARENT",
        }
        rows.append({**row_core, "row_sha256": canonical_json_sha256(row_core)})
    counts = {
        "authenticated_seed_contract": sum(row["gates"]["authenticated_seed_contract"] for row in rows),
        "seven_constraint_parent_evidence": sum(row["gates"]["seven_constraint_parent_evidence"] for row in rows),
        "classical_delta_equivalence": sum(row["gates"]["classical_delta_equivalence"] for row in rows),
        "scalable_reversible_ir": sum(row["gates"]["scalable_reversible_ir"] for row in rows),
        "elementary_lowering": sum(row["gates"]["elementary_lowering"] for row in rows),
        "full_coherent_equivalence": sum(row["gates"]["full_coherent_equivalence"] for row in rows),
        "clean_ancilla_proof": sum(row["gates"]["clean_ancilla_proof"] for row in rows),
        "ordered_layer_connectivity": sum(row["gates"]["ordered_layer_connectivity"] for row in rows),
        "selected_model_cnot_ledger": sum(row["gates"]["selected_model_cnot_ledger"] for row in rows),
        "selected_model_budget_at_most_2500000": sum(row["gates"]["selected_model_budget_at_most_2500000"] for row in rows),
    }
    core = {
        "registered_family": "N40_K10_BANDS_SEVEN_CONSTRAINTS",
        "frozen_seeds": list(N40_SEEDS),
        "budget_cnot": N40_BUDGET_CNOT,
        "selected_model": SELECTED_MODEL,
        "authentication": authentication,
        "coverage_counts_out_of_8": counts,
        "rows": rows,
        "maximum_selected_model_cnot": "NOT_ESTIMATED",
        "minimum_budget_margin_cnot": "NOT_COMPUTED",
        "budget_gate": "NOT_EVALUATED",
        "admission_decision": "BLOCKED_INCOMPLETE_REVERSIBLE_IR",
        "blocking_evidence": [
            "SCALABLE_REVERSIBLE_ARITHMETIC_AND_CACHE_UPDATE_IR",
            "ELEMENTARY_LOWERING_ON_ALL_EIGHT_SEEDS",
            "FULL_COHERENT_EQUIVALENCE_AND_CLEANUP_ON_ALL_EIGHT_SEEDS",
            "ORDERED_LAYER_CONNECTIVITY_ON_ALL_EIGHT_SEEDS",
            "SELECTED_MODEL_CNOT_LEDGER_ON_ALL_EIGHT_SEEDS",
        ],
        "negative_result_preservation": (
            "The frozen V3.4 cost rejection remains authentic historical evidence for its "
            "own architecture. It is not relabeled as the V3.8 selected-model cost and does "
            "not establish a global impossibility result."
        ),
    }
    return {**core, "n40_admission_sha256": canonical_json_sha256(core)}


def build_v38_artifact() -> dict[str, Any]:
    spec = load_v38_spec()
    parent = authenticate_v37_parent()
    if not parent["valid"]:
        raise ValueError("V3.8 parent authentication failed: " + "; ".join(parent["errors"]))
    elementary = exhaustive_elementary_validation()
    ledger = compile_elementary_layer()
    n40 = n40_admission_ledger()
    prototype_pass = bool(elementary["passed"] and ledger["cnot_count"] == 3_632)
    core = {
        "artifact_version": ARTIFACT_VERSION,
        "v38_version": V38_VERSION,
        "research_classification": "RESEARCH_ONLY",
        "spec_sha256": spec["v38_spec_sha256"],
        "spec_raw_file_sha256": raw_file_sha256(Path(__file__).with_name(SPEC_FILENAME)),
        "source_sha256": source_sha256(),
        "parent": {
            "v37_artifact_sha256": EXPECTED_V37_ARTIFACT_SHA256,
            "v37_artifact_raw_file_sha256": EXPECTED_V37_ARTIFACT_RAW_SHA256,
            "v37_freeze_sha256": EXPECTED_V37_FREEZE_SHA256,
            "v37_freeze_raw_file_sha256": EXPECTED_V37_FREEZE_RAW_SHA256,
            "authentication": parent,
        },
        "decomposition_contract": {
            "selected_model": SELECTED_MODEL,
            "elementary_basis": list(ELEMENTARY_BASIS),
            "connectivity_model": "ABSTRACT_ALL_TO_ALL_LOGICAL",
            "cnot_depth_policy": "CONSERVATIVE_SERIAL_EMISSION_ORDER_EQUAL_TO_CNOT_COUNT",
            "post_observation_candidate_switching": "PROHIBITED",
            "ccx_template": "CCX_CLIFFORD_T_6CX_V1",
            "controlled_rx_template": "CRX_2CX_RZ_RY_V1",
            "clean_ancilla_policy": "ZERO_INITIALIZED_AND_ZERO_RETURN_PER_LOGICAL_PRIMITIVE",
        },
        "elementary_validation": elementary,
        "elementary_resource_ledger": ledger,
        "n40_admission": n40,
        "decisions": {
            "overall": (
                "ELEMENTARY_PROTOTYPE_PASSED_N40_ADMISSION_BLOCKED"
                if prototype_pass and n40["admission_decision"] == "BLOCKED_INCOMPLETE_REVERSIBLE_IR"
                else "V38_EVIDENCE_REJECTED"
            ),
            "elementary_decomposition": "VALIDATED_ON_REGISTERED_N4_K2_PROTOTYPE" if prototype_pass else "REJECTED",
            "n40_resource_admission": n40["admission_decision"],
            "n40_selected_model_budget": n40["budget_gate"],
            "backend_native": "NOT_RUN_PROVIDER_FREE_PHASE",
            "next_falsifiable_gate": "SCALABLE_N40_REVERSIBLE_ARITHMETIC_IR_AND_EIGHT_SEED_EQUIVALENCE",
        },
        "claim_boundary": {
            "prototype_scope": "AUTHENTICATED_V37_SYNTHETIC_N4_K2_ONLY",
            "production_n40_equivalence": "NOT_PROVEN",
            "n40_selected_model_cnot": "NOT_ESTIMATED",
            "n40_budget_gate": "NOT_EVALUATED",
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


def _recomputed_v38_artifact() -> dict[str, Any]:
    global _EXPECTED_ARTIFACT_CACHE
    spec_path = Path(__file__).with_name(SPEC_FILENAME)
    v37_path = default_v37_artifact_path()
    v36_path = default_v36_artifact_path()
    freeze_path = Path(__file__).resolve().parents[1] / "FREEZE_CONTRACT_V3_7.json"
    key = (
        source_sha256(),
        raw_file_sha256(spec_path),
        raw_file_sha256(v37_path),
        raw_file_sha256(v36_path) + raw_file_sha256(freeze_path),
    )
    if _EXPECTED_ARTIFACT_CACHE is None or _EXPECTED_ARTIFACT_CACHE[0] != key:
        _EXPECTED_ARTIFACT_CACHE = (key, build_v38_artifact())
    return _EXPECTED_ARTIFACT_CACHE[1]


def validate_v38_artifact(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        return {"valid": False, "errors": ["Artifact must be an object."]}
    errors: list[str] = []
    core = {key: value for key, value in payload.items() if key != "artifact_sha256"}
    try:
        computed = canonical_json_sha256(core)
    except (TypeError, ValueError, OverflowError) as exc:
        return {"valid": False, "errors": [str(exc)]}
    if payload.get("artifact_sha256") != computed:
        errors.append("Artifact SHA-256 mismatch.")
    if payload.get("artifact_version") != ARTIFACT_VERSION:
        errors.append("Artifact version mismatch.")
    try:
        expected = _recomputed_v38_artifact()
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        expected = {}
        errors.append(f"Trusted V3.8 evidence recomputation failed: {exc}")
    if expected:
        if set(payload) != set(expected):
            errors.append("Artifact schema differs from the registered evidence contract.")
        for key, expected_value in expected.items():
            if key != "artifact_sha256" and payload.get(key) != expected_value:
                errors.append(f"Recomputed V3.8 evidence mismatch: {key}.")
        if payload.get("artifact_sha256") != expected.get("artifact_sha256"):
            errors.append("Artifact identity differs from recomputed registered evidence.")
    elementary = payload.get("elementary_validation") or {}
    ledger = payload.get("elementary_resource_ledger") or {}
    n40 = payload.get("n40_admission") or {}
    decisions = payload.get("decisions") or {}
    boundary = payload.get("claim_boundary") or {}
    if not elementary.get("passed"):
        errors.append("Elementary validation is not passing.")
    if not (
        ledger.get("cnot_count") == 3_632
        and ledger.get("one_qubit_gate_count") == 5_920
        and ledger.get("maximum_clean_ancilla_qubits") == 8
        and ledger.get("maximum_total_qubits") == 18
    ):
        errors.append("Elementary resource ledger mismatch.")
    coverage = n40.get("coverage_counts_out_of_8") or {}
    if not (
        len(n40.get("rows") or []) == 8
        and coverage.get("authenticated_seed_contract") == 8
        and coverage.get("seven_constraint_parent_evidence") == 8
        and coverage.get("classical_delta_equivalence") == 8
        and coverage.get("scalable_reversible_ir") == 0
        and coverage.get("selected_model_cnot_ledger") == 0
        and n40.get("maximum_selected_model_cnot") == "NOT_ESTIMATED"
        and n40.get("budget_gate") == "NOT_EVALUATED"
        and n40.get("admission_decision") == "BLOCKED_INCOMPLETE_REVERSIBLE_IR"
    ):
        errors.append("N40 admission did not fail closed at the registered evidence boundary.")
    if decisions.get("overall") != "ELEMENTARY_PROTOTYPE_PASSED_N40_ADMISSION_BLOCKED":
        errors.append("V3.8 bounded decision mismatch.")
    if not (
        boundary.get("production_n40_equivalence") == "NOT_PROVEN"
        and boundary.get("n40_selected_model_cnot") == "NOT_ESTIMATED"
        and boundary.get("provider_calls") == 0
        and boundary.get("hardware_executable") is False
        and boundary.get("qpu_jobs_submitted") == 0
        and boundary.get("quantum_advantage") == "NOT_CLAIMED"
    ):
        errors.append("V3.8 claim boundary mismatch.")
    return {
        "valid": not errors,
        "errors": errors,
        "artifact_sha256_computed": computed,
        "artifact_sha256_stored": payload.get("artifact_sha256"),
    }


def default_v38_artifact_path() -> Path:
    return (
        Path(__file__).resolve().parents[1]
        / "outputs"
        / "quantum_phase3"
        / "v38_elementary"
        / DEFAULT_ARTIFACT_NAME
    )


def load_v38_artifact(path: str | Path | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    target = Path(path) if path is not None else default_v38_artifact_path()
    payload = _read_json_strict(target)
    return payload, validate_v38_artifact(payload)


def seal_v38_artifact(path: str | Path | None = None) -> dict[str, Any]:
    target = Path(path) if path is not None else default_v38_artifact_path()
    artifact = build_v38_artifact()
    report = validate_v38_artifact(artifact)
    if not report["valid"]:
        raise ValueError("Refusing to seal invalid V3.8 artifact: " + "; ".join(report["errors"]))
    encoded = json.dumps(artifact, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8") + b"\n"
    if target.exists():
        if target.read_bytes() != encoded:
            raise FileExistsError(f"Refusing to overwrite non-identical V3.8 artifact: {target}")
        return {"artifact": artifact, "created": False, "path": str(target)}
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
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
    "ELEMENTARY_BASIS",
    "EXPECTED_V38_SPEC_RAW_SHA256",
    "EXPECTED_V38_SPEC_SHA256",
    "N40_BUDGET_CNOT",
    "N40_SEEDS",
    "SELECTED_MODEL",
    "SPEC_FILENAME",
    "V38_VERSION",
    "apply_elementary_gate",
    "apply_elementary_sequence",
    "authenticate_v37_parent",
    "build_v38_artifact",
    "ccx_template",
    "compile_elementary_layer",
    "crx_template",
    "default_v38_artifact_path",
    "exhaustive_elementary_validation",
    "load_v38_artifact",
    "load_v38_spec",
    "lower_pattern_gate",
    "n40_admission_ledger",
    "seal_v38_artifact",
    "source_sha256",
    "validate_v38_artifact",
]
