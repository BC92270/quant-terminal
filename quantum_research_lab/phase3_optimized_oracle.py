"""V3.4 exact oracle optimization with a proof-carrying interval flag.

The frozen V3.2 compiler remains immutable.  This additive compiler replaces
two live comparator flags and their compute/uncompute networks with the exact
integer identity

    1[L <= v <= U] = 1 XOR 1[v <= L-1] XOR 1[v >= U+1]

whose two violation predicates are disjoint when L <= U.  Arithmetic,
endianness, signed ordering and the seven frozen constraints are unchanged.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

from .phase3_gate_compiler import (
    ABSTRACT_GATE_SET,
    DOMAIN_EXACT_K,
    DOMAIN_FULL_BINARY,
    SUPPORTED_DOMAINS,
    ConstraintIR,
    Gate,
    Register,
    canonical_json_bytes,
    canonical_json_sha256,
    compare_inclusive,
    constraints_from_certificate,
    controlled_add_constant,
    make_gate,
)


OPTIMIZER_VERSION = "PHASE III · EXACT DISJOINT-VIOLATION ORACLE · V1"
SPEC_FILENAME = "PHASE_III_OPTIMIZED_NATIVE_SPEC_V1.json"


def _without(payload: Mapping[str, Any], fields: Iterable[str]) -> dict[str, Any]:
    excluded = set(fields)
    return {key: value for key, value in payload.items() if key not in excluded}


def load_v34_spec(path: str | Path | None = None) -> dict[str, Any]:
    spec_path = Path(path) if path is not None else Path(__file__).with_name(SPEC_FILENAME)
    payload = json.loads(spec_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("V3.4 specification must be a JSON object.")
    core = _without(payload, ("v34_spec_sha", "v34_spec_sha256"))
    full_hash = canonical_json_sha256(core)
    if payload.get("v34_spec_sha256") != full_hash:
        raise ValueError("V3.4 specification SHA-256 mismatch.")
    if payload.get("v34_spec_sha") != full_hash[:20].upper():
        raise ValueError("V3.4 specification short SHA mismatch.")
    boundary = payload.get("claim_boundary") or {}
    if boundary.get("hardware_executable") is not False:
        raise ValueError("V3.4 specification violates the hardware boundary.")
    if boundary.get("qpu_submission_enabled") is not False:
        raise ValueError("V3.4 specification enables QPU submission.")
    return payload


def optimizer_source_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class OptimizedCircuitIR:
    seed: int
    instance_id: str
    n: int
    k: int
    domain_mode: str
    parent_v31_raw_file_sha256: str
    parent_v32_artifact_sha256: str
    parent_v33_artifact_sha256: str
    parent_v33_freeze_sha256: str
    optimizer_spec_sha256: str
    registers: tuple[Register, ...]
    constraints: tuple[ConstraintIR, ...]

    def __post_init__(self) -> None:
        if self.domain_mode not in SUPPORTED_DOMAINS:
            raise ValueError(f"Unsupported oracle domain: {self.domain_mode}")
        cursor = 0
        for register in self.registers:
            if register.start != cursor:
                raise ValueError("Optimized registers must be contiguous.")
            cursor += register.size
        if not self.constraints:
            raise ValueError("At least one frozen constraint is required.")

    def register(self, name: str) -> Register:
        for register in self.registers:
            if register.name == name:
                return register
        raise KeyError(name)

    @property
    def logical_qubits(self) -> int:
        final = self.registers[-1]
        return final.start + final.size

    def iter_gates(self) -> Iterator[Gate]:
        return _optimized_oracle_gate_stream(self)

    def header_payload(self) -> dict[str, Any]:
        return {
            "constraints": [constraint.as_dict() for constraint in self.constraints],
            "domain_mode": self.domain_mode,
            "endianness": "LITTLE_ENDIAN",
            "gate_set": list(ABSTRACT_GATE_SET),
            "instance_id": self.instance_id,
            "interval_flag_identity": (
                "inside = 1 XOR [value <= lower-1] XOR [value >= upper+1]"
            ),
            "k": self.k,
            "n": self.n,
            "optimizer_spec_sha256": self.optimizer_spec_sha256,
            "optimizer_version": OPTIMIZER_VERSION,
            "parent_v31_raw_file_sha256": self.parent_v31_raw_file_sha256,
            "parent_v32_artifact_sha256": self.parent_v32_artifact_sha256,
            "parent_v33_artifact_sha256": self.parent_v33_artifact_sha256,
            "parent_v33_freeze_sha256": self.parent_v33_freeze_sha256,
            "registers": [register.as_dict() for register in self.registers],
            "seed": self.seed,
            "unitary": "|x>|y>|0> -> |x>|y XOR f(x)>|0>",
        }


def _allocate_optimized_registers(
    n: int, constraints: Sequence[ConstraintIR]
) -> tuple[Register, ...]:
    work_width = max(constraint.width for constraint in constraints)
    cursor = 0
    registers: list[Register] = []

    def add(name: str, size: int, role: str, signed: bool = False) -> None:
        nonlocal cursor
        registers.append(Register(name, cursor, size, role, signed))
        cursor += size

    add("data", n, "CALLER_OWNED_INPUT")
    add("target", 1, "CALLER_OWNED_OUTPUT")
    add("work", work_width, "SEQUENTIALLY_REUSED_ACCUMULATOR_AND_MIXER_SCRATCH", True)
    add("constraint_flags", len(constraints), "CLEAN_CONSTRAINT_FLAGS")
    add("aggregate", 1, "CLEAN_CONJUNCTION_FLAG")
    return tuple(registers)


def compile_optimized_seed(
    certificate: Mapping[str, Any],
    domain_mode: str,
    *,
    parent_v31_raw_file_sha256: str,
    parent_v32_artifact_sha256: str,
    parent_v33_artifact_sha256: str,
    parent_v33_freeze_sha256: str,
    spec: Mapping[str, Any] | None = None,
) -> OptimizedCircuitIR:
    v34_spec = dict(spec) if spec is not None else load_v34_spec()
    constraints = constraints_from_certificate(certificate, domain_mode)
    registers = _allocate_optimized_registers(int(certificate["N"]), constraints)
    return OptimizedCircuitIR(
        seed=int(certificate["seed"]),
        instance_id=str(certificate["instance_id"]),
        n=int(certificate["N"]),
        k=int(certificate["K"]),
        domain_mode=domain_mode,
        parent_v31_raw_file_sha256=str(parent_v31_raw_file_sha256),
        parent_v32_artifact_sha256=str(parent_v32_artifact_sha256),
        parent_v33_artifact_sha256=str(parent_v33_artifact_sha256),
        parent_v33_freeze_sha256=str(parent_v33_freeze_sha256),
        optimizer_spec_sha256=str(v34_spec["v34_spec_sha256"]),
        registers=registers,
        constraints=constraints,
    )


def optimized_interval_flag(
    register_bits: Sequence[int],
    lower: int,
    upper: int,
    target: int,
    *,
    signed: bool,
    stage: str = "INTERVAL_FLAG",
    label: str = "DISJOINT_VIOLATIONS",
) -> Iterator[Gate]:
    """Toggle target iff the encoded integer lies in the inclusive interval."""

    if int(lower) > int(upper):
        raise ValueError("Inclusive interval lower bound exceeds upper bound.")
    yield make_gate(target, stage=stage, label=f"{label}:BIAS_ONE")
    yield from compare_inclusive(
        register_bits,
        int(lower) - 1,
        target,
        relation="LE",
        signed=bool(signed),
        stage=stage,
        label=f"{label}:BELOW_LOWER",
    )
    yield from compare_inclusive(
        register_bits,
        int(upper) + 1,
        target,
        relation="GE",
        signed=bool(signed),
        stage=stage,
        label=f"{label}:ABOVE_UPPER",
    )


def _optimized_constraint_gate_stream(
    circuit: OptimizedCircuitIR,
    constraint_index: int,
    *,
    stage_prefix: str,
) -> Iterator[Gate]:
    constraint = circuit.constraints[constraint_index]
    data = circuit.register("data").bits
    work = circuit.register("work").bits[: constraint.width]
    flag = circuit.register("constraint_flags").bits[constraint_index]
    prefix = f"{stage_prefix}:{constraint_index:02d}:{constraint.name}"
    additions = [
        (data[data_index], coefficient)
        for data_index, coefficient in zip(
            constraint.data_indices, constraint.coefficients
        )
        if coefficient
    ]
    for ordinal, (control, coefficient) in enumerate(additions):
        yield from controlled_add_constant(
            control,
            work,
            coefficient,
            stage=f"{prefix}:ACCUMULATE",
            label=f"TERM_{ordinal:03d}",
        )
    yield from optimized_interval_flag(
        work,
        constraint.lower,
        constraint.upper,
        flag,
        signed=constraint.signed,
        stage=f"{prefix}:INTERVAL",
    )
    for reverse_ordinal, (control, coefficient) in enumerate(reversed(additions)):
        yield from controlled_add_constant(
            control,
            work,
            coefficient,
            inverse=True,
            stage=f"{prefix}:UNCOMPUTE_ACCUMULATOR",
            label=f"TERM_{len(additions) - reverse_ordinal - 1:03d}",
        )


def _optimized_oracle_gate_stream(circuit: OptimizedCircuitIR) -> Iterator[Gate]:
    flags = circuit.register("constraint_flags").bits
    aggregate = circuit.register("aggregate").bits[0]
    target = circuit.register("target").bits[0]
    for index in range(len(circuit.constraints)):
        yield from _optimized_constraint_gate_stream(
            circuit, index, stage_prefix="COMPUTE"
        )
    yield make_gate(
        aggregate,
        flags,
        stage="AGGREGATE",
        label="ALL_CONSTRAINTS_TRUE",
    )
    yield make_gate(
        target,
        (aggregate,),
        stage="ORACLE_OUTPUT",
        label="BIT_FLIP_TARGET",
    )
    yield make_gate(
        aggregate,
        flags,
        stage="UNCOMPUTE_AGGREGATE",
        label="ALL_CONSTRAINTS_TRUE",
    )
    for index in range(len(circuit.constraints) - 1, -1, -1):
        yield from _optimized_constraint_gate_stream(
            circuit, index, stage_prefix="UNCOMPUTE"
        )


def optimized_gate_ir_sha256(circuit: OptimizedCircuitIR) -> str:
    digest = hashlib.sha256()
    digest.update(canonical_json_bytes({"header": circuit.header_payload()}))
    digest.update(b"\n")
    for gate in circuit.iter_gates():
        digest.update(gate.canonical_bytes())
        digest.update(b"\n")
    return digest.hexdigest()


def optimized_classical_predicate(
    bits: Sequence[int], circuit: OptimizedCircuitIR
) -> bool:
    if len(bits) != circuit.n or any(int(value) not in (0, 1) for value in bits):
        raise ValueError("Classical input must contain exactly N binary values.")
    if circuit.domain_mode == DOMAIN_EXACT_K and sum(int(value) for value in bits) != circuit.k:
        raise ValueError("EXACT_K_SUBSPACE predicate called outside its declared domain.")
    return all(
        constraint.lower
        <= sum(
            int(coefficient) * int(bits[index])
            for index, coefficient in zip(
                constraint.data_indices, constraint.coefficients
            )
        )
        <= constraint.upper
        for constraint in circuit.constraints
    )


def simulate_optimized_basis_state(
    circuit: OptimizedCircuitIR,
    bits: Sequence[int],
    *,
    target: int = 0,
) -> dict[str, Any]:
    if len(bits) != circuit.n or any(int(value) not in (0, 1) for value in bits):
        raise ValueError("Simulation input must contain exactly N binary values.")
    if int(target) not in (0, 1):
        raise ValueError("Target must be zero or one.")
    state = [0] * circuit.logical_qubits
    data_register = circuit.register("data")
    target_index = circuit.register("target").bits[0]
    for index, value in enumerate(bits):
        state[data_register.start + index] = int(value)
    state[target_index] = int(target)
    for gate in circuit.iter_gates():
        if all(
            state[index] == expected
            for index, expected in zip(gate.controls, gate.control_values)
        ):
            state[gate.target] ^= 1
    data_after = state[data_register.start : data_register.start + data_register.size]
    ancilla_indices = [
        index
        for register in circuit.registers
        if register.name not in {"data", "target"}
        for index in register.bits
    ]
    return {
        "ancilla_clean": all(state[index] == 0 for index in ancilla_indices),
        "data_after": data_after,
        "data_preserved": data_after == [int(value) for value in bits],
        "target_after": state[target_index],
        "target_before": int(target),
        "target_toggled": state[target_index] ^ int(target),
    }


def analyze_optimized_circuit(
    circuit: OptimizedCircuitIR,
    *,
    initial_basis_states: Sequence[int] | None = None,
) -> dict[str, Any]:
    """Hash/count the gate stream and optionally simulate integer basis states.

    The optional batch is evaluated in the same authoritative traversal used
    for the digest and resource ledger.  This avoids materialising hundreds of
    thousands of gate records or performing a redundant full-stream pass.
    """

    abstract_counts = {kind: 0 for kind in ABSTRACT_GATE_SET}
    decomposed_x = 0
    decomposed_cx = 0
    decomposed_ccx = 0
    clean_mcx_ancillas = 0
    t_depth_serial_upper = 0
    total_gates = 0
    output_gate_position: int | None = None
    last_layer = [0] * circuit.logical_qubits
    abstract_depth = 0
    digest = hashlib.sha256()
    digest.update(canonical_json_bytes({"header": circuit.header_payload()}))
    digest.update(b"\n")
    simulated_states = (
        [int(value) for value in initial_basis_states]
        if initial_basis_states is not None
        else None
    )
    state_limit = 1 << circuit.logical_qubits
    if simulated_states is not None and any(
        state < 0 or state >= state_limit for state in simulated_states
    ):
        raise ValueError("Initial basis state lies outside the circuit register width.")

    for gate in circuit.iter_gates():
        total_gates += 1
        if gate.stage == "ORACLE_OUTPUT":
            output_gate_position = total_gates
        abstract_counts[gate.kind] += 1
        digest.update(gate.canonical_bytes())
        digest.update(b"\n")
        if simulated_states is not None:
            control_mask = 0
            expected_mask = 0
            for control, value in zip(gate.controls, gate.control_values):
                bit = 1 << control
                control_mask |= bit
                if value:
                    expected_mask |= bit
            target_mask = 1 << gate.target
            for state_index, state in enumerate(simulated_states):
                if state & control_mask == expected_mask:
                    simulated_states[state_index] = state ^ target_mask
        involved = gate.controls + (gate.target,)
        layer = 1 + max(last_layer[index] for index in involved)
        for index in involved:
            last_layer[index] = layer
        abstract_depth = max(abstract_depth, layer)

        negative_controls = sum(value == 0 for value in gate.control_values)
        decomposed_x += 2 * negative_controls
        controls = len(gate.controls)
        if controls == 0:
            decomposed_x += 1
        elif controls == 1:
            decomposed_cx += 1
        elif controls == 2:
            decomposed_ccx += 1
            t_depth_serial_upper += 3
        else:
            ccx_for_gate = 2 * controls - 3
            decomposed_ccx += ccx_for_gate
            clean_mcx_ancillas = max(clean_mcx_ancillas, controls - 2)
            t_depth_serial_upper += 3 * ccx_for_gate

    base_adds = sum(
        sum(1 for coefficient in constraint.coefficients if coefficient)
        for constraint in circuit.constraints
    )
    uncompute_gates = (
        total_gates - output_gate_position if output_gate_position is not None else 0
    )
    forward_gates = (
        output_gate_position - 1 if output_gate_position is not None else total_gates
    )
    work_qubits = circuit.register("work").size
    flag_qubits = circuit.register("constraint_flags").size
    logical_ancillas = work_qubits + flag_qubits + 1
    report = {
        "claim_boundary": {
            "hardware_executable": False,
            "qpu_submission_enabled": False,
            "status": "OPTIMIZED PROVIDER-NEUTRAL GATE IR · NOT BACKEND TRANSPILED",
        },
        "domain_mode": circuit.domain_mode,
        "gate_ir_sha256": digest.hexdigest(),
        "instance_id": circuit.instance_id,
        "levels": {
            "FAULT_TOLERANT_ESTIMATE": {
                "basis": "CLEAN_ANCILLA_MCX_V_CHAIN_AND_7T_CCX_UPPER_BOUND",
                "clean_mcx_decomposition_ancillas": clean_mcx_ancillas,
                "decomposed_ccx": decomposed_ccx,
                "decomposed_cnot": decomposed_cx + 6 * decomposed_ccx,
                "decomposed_x": decomposed_x,
                "logical_qubits_with_decomposition_ancillas": (
                    circuit.logical_qubits + clean_mcx_ancillas
                ),
                "t_count": 7 * decomposed_ccx,
                "t_depth_upper_bound": t_depth_serial_upper,
            },
            "GATE_LEVEL_ABSTRACT": {
                **abstract_counts,
                "abstract_depth": abstract_depth,
                "critical_path_depth": abstract_depth,
                "gate_count": total_gates,
                "negative_control_lowering": "PAIRED_X_AROUND_POSITIVE_CONTROL_NETWORK",
            },
            "LOGICAL_IR": {
                "aggregate_qubits": 1,
                "caller_target_qubits": 1,
                "comparator_network_count": 4 * len(circuit.constraints),
                "constraint_flag_qubits": flag_qubits,
                "controlled_add_count": 4 * base_adds,
                "controlled_add_count_forward_predicate": base_adds,
                "data_qubits": circuit.n,
                "logical_qubits_total": circuit.logical_qubits,
                "max_simultaneously_live_ancillas": logical_ancillas,
                "range_certified_widths": {
                    constraint.name: constraint.width
                    for constraint in circuit.constraints
                },
                "removed_comparator_flag_qubits_vs_v32": 2,
                "uncomputation_gate_count": uncompute_gates,
                "uncomputation_overhead": (
                    float(uncompute_gates / forward_gates) if forward_gates else 0.0
                ),
                "work_qubits": work_qubits,
            },
            "TRANSPILED_BACKEND_SPECIFIC": {
                "backend": None,
                "status": "NOT_RUN",
            },
        },
        "optimizer_spec_sha256": circuit.optimizer_spec_sha256,
        "optimizer_version": OPTIMIZER_VERSION,
        "seed": circuit.seed,
    }
    if simulated_states is not None:
        report["simulated_basis_states_after"] = simulated_states
    return report


def optimized_circuit_manifest(circuit: OptimizedCircuitIR) -> dict[str, Any]:
    ledger = analyze_optimized_circuit(circuit)
    return {
        "circuit_header": circuit.header_payload(),
        "gate_ir_sha256": ledger["gate_ir_sha256"],
        "resource_ledger": ledger,
    }


__all__ = [
    "OPTIMIZER_VERSION",
    "OptimizedCircuitIR",
    "analyze_optimized_circuit",
    "compile_optimized_seed",
    "load_v34_spec",
    "optimized_circuit_manifest",
    "optimized_classical_predicate",
    "optimized_gate_ir_sha256",
    "optimized_interval_flag",
    "optimizer_source_sha256",
    "simulate_optimized_basis_state",
]
