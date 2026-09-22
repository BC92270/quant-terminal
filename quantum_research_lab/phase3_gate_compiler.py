"""Proof-carrying reversible gate compiler for the V3.1 dyadic oracle.

This reference compiler deliberately favours a small, inspectable gate
vocabulary and deterministic output over circuit optimisation.  It lowers the
sealed integer BANDS predicate to a provider-neutral bit-flip oracle

    |x>|y>|0> -> |x>|y xor f(x)>|0>

using X, CX, CCX and abstract MCX gates.  MCX decomposition is specified and
accounted for, but backend-native transpilation remains outside the V3.2 claim.

There are two explicit semantic domains:

* ``EXACT_K_SUBSPACE`` assumes state preparation supplies popcount(x)=K and
  compiles the seven group/factor constraints;
* ``FULL_BINARY`` also compiles cardinality, so it implements the complete
  strict predicate on all 2**N computational-basis inputs.

No function in this module submits work to a QPU or claims hardware readiness.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence


COMPILER_VERSION = "PHASE III · PROOF-CARRYING REVERSIBLE GATE COMPILER · V1"
SPEC_FILENAME = "PHASE_III_GATE_COMPILER_SPEC_V1.json"
DOMAIN_EXACT_K = "EXACT_K_SUBSPACE"
DOMAIN_FULL_BINARY = "FULL_BINARY"
SUPPORTED_DOMAINS = (DOMAIN_EXACT_K, DOMAIN_FULL_BINARY)
ABSTRACT_GATE_SET = ("X", "CX", "CCX", "MCX")


def canonical_json_bytes(payload: Any) -> bytes:
    """Return strict, deterministic UTF-8 JSON bytes."""

    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def canonical_json_sha256(payload: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _without(payload: Mapping[str, Any], fields: Iterable[str]) -> dict[str, Any]:
    excluded = set(fields)
    return {key: value for key, value in payload.items() if key not in excluded}


def load_compiler_spec(path: str | Path | None = None) -> dict[str, Any]:
    """Load the preregistered compiler spec and verify its self hashes."""

    spec_path = Path(path) if path is not None else Path(__file__).with_name(SPEC_FILENAME)
    payload = json.loads(spec_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Gate compiler specification must be a JSON object.")
    content = _without(
        payload, {"gate_compiler_spec_sha", "gate_compiler_spec_sha256"}
    )
    full_hash = canonical_json_sha256(content)
    short_hash = full_hash[:20].upper()
    if payload.get("gate_compiler_spec_sha256") != full_hash:
        raise ValueError("Gate compiler specification SHA-256 mismatch.")
    if payload.get("gate_compiler_spec_sha") != short_hash:
        raise ValueError("Gate compiler specification short SHA mismatch.")
    if payload.get("claim_boundary", {}).get("hardware_executable") is not False:
        raise ValueError("Compiler specification violates the hardware claim boundary.")
    return payload


def compiler_source_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class Gate:
    """One deterministic provider-neutral reversible gate record."""

    kind: str
    target: int
    controls: tuple[int, ...] = ()
    control_values: tuple[int, ...] = ()
    stage: str = ""
    label: str = ""

    def __post_init__(self) -> None:
        if self.kind not in ABSTRACT_GATE_SET:
            raise ValueError(f"Unsupported gate kind: {self.kind}")
        if type(self.target) is not int or self.target < 0:
            raise ValueError("Gate target must be a non-negative integer.")
        if len(self.controls) != len(self.control_values):
            raise ValueError("Control indices and polarities must have equal length.")
        if len(set(self.controls)) != len(self.controls):
            raise ValueError("A gate cannot repeat a control qubit.")
        if self.target in self.controls:
            raise ValueError("A target qubit cannot also be a control.")
        if any(type(index) is not int or index < 0 for index in self.controls):
            raise ValueError("Control indices must be non-negative integers.")
        if any(value not in (0, 1) for value in self.control_values):
            raise ValueError("Control polarities must be zero or one.")
        expected_kind = {0: "X", 1: "CX", 2: "CCX"}.get(
            len(self.controls), "MCX"
        )
        if self.kind != expected_kind:
            raise ValueError(
                f"Gate kind {self.kind} is inconsistent with "
                f"{len(self.controls)} controls; expected {expected_kind}."
            )

    def as_dict(self) -> dict[str, Any]:
        return {
            "control_values": list(self.control_values),
            "controls": list(self.controls),
            "kind": self.kind,
            "label": self.label,
            "stage": self.stage,
            "target": self.target,
        }

    def canonical_bytes(self) -> bytes:
        """Fast exact equivalent of ``canonical_json_bytes(as_dict())``."""

        controls = ",".join(str(value) for value in self.controls)
        polarities = ",".join(str(value) for value in self.control_values)
        kind = json.dumps(self.kind, ensure_ascii=False)
        label = json.dumps(self.label, ensure_ascii=False)
        stage = json.dumps(self.stage, ensure_ascii=False)
        return (
            "{\"control_values\":["
            + polarities
            + "],\"controls\":["
            + controls
            + "],\"kind\":"
            + kind
            + ",\"label\":"
            + label
            + ",\"stage\":"
            + stage
            + ",\"target\":"
            + str(self.target)
            + "}"
        ).encode("utf-8")


def make_gate(
    target: int,
    controls: Sequence[int] = (),
    control_values: Sequence[int] | None = None,
    *,
    stage: str = "",
    label: str = "",
) -> Gate:
    controls_tuple = tuple(int(value) for value in controls)
    values_tuple = (
        tuple(1 for _ in controls_tuple)
        if control_values is None
        else tuple(int(value) for value in control_values)
    )
    kind = {0: "X", 1: "CX", 2: "CCX"}.get(len(controls_tuple), "MCX")
    return Gate(
        kind=kind,
        target=int(target),
        controls=controls_tuple,
        control_values=values_tuple,
        stage=str(stage),
        label=str(label),
    )


@dataclass(frozen=True, slots=True)
class Register:
    name: str
    start: int
    size: int
    role: str
    signed: bool = False

    def __post_init__(self) -> None:
        if not self.name or type(self.start) is not int or type(self.size) is not int:
            raise ValueError("Register name, start and size must be explicit.")
        if self.start < 0 or self.size < 1:
            raise ValueError("Register bounds must be positive.")

    @property
    def bits(self) -> tuple[int, ...]:
        return tuple(range(self.start, self.start + self.size))

    def as_dict(self) -> dict[str, Any]:
        return {
            "endianness": "LITTLE_ENDIAN",
            "name": self.name,
            "role": self.role,
            "signed": bool(self.signed),
            "size": self.size,
            "start": self.start,
            "stop_exclusive": self.start + self.size,
        }


@dataclass(frozen=True, slots=True)
class ConstraintIR:
    kind: str
    name: str
    data_indices: tuple[int, ...]
    coefficients: tuple[int, ...]
    lower: int
    upper: int
    width: int
    signed: bool
    range_certificate: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.kind not in {"CARDINALITY", "GROUP", "FACTOR"}:
            raise ValueError(f"Unsupported constraint kind: {self.kind}")
        if len(self.data_indices) != len(self.coefficients):
            raise ValueError("Constraint indices and coefficients must align.")
        if len(set(self.data_indices)) != len(self.data_indices):
            raise ValueError("Constraint data indices must be unique.")
        if self.lower > self.upper:
            raise ValueError("Constraint lower bound exceeds upper bound.")
        if self.width < 1:
            raise ValueError("Constraint width must be positive.")

    def as_dict(self) -> dict[str, Any]:
        return {
            "coefficients": list(self.coefficients),
            "data_indices": list(self.data_indices),
            "kind": self.kind,
            "lower": self.lower,
            "name": self.name,
            "range_certificate": dict(self.range_certificate),
            "signed": self.signed,
            "upper": self.upper,
            "width": self.width,
        }


@dataclass(frozen=True, slots=True)
class CircuitIR:
    seed: int
    instance_id: str
    n: int
    k: int
    domain_mode: str
    parent_dyadic_oracle_sha: str
    parent_artifact_file_sha256: str
    compiler_spec_sha256: str
    registers: tuple[Register, ...]
    constraints: tuple[ConstraintIR, ...]

    def __post_init__(self) -> None:
        if self.domain_mode not in SUPPORTED_DOMAINS:
            raise ValueError(f"Unsupported oracle domain: {self.domain_mode}")
        if self.n < 1 or not 0 <= self.k <= self.n:
            raise ValueError("Invalid N/K pair.")
        cursor = 0
        for register in self.registers:
            if register.start != cursor:
                raise ValueError("Registers must be contiguous and canonically ordered.")
            cursor += register.size
        if len(self.constraints) not in (7, 8):
            # Synthetic validation circuits may use a different count, so only
            # enforce non-emptiness here; the N=40 family validator enforces 7/8.
            if not self.constraints:
                raise ValueError("At least one constraint is required.")

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
        return _oracle_gate_stream(self)

    def header_payload(self) -> dict[str, Any]:
        return {
            "compiler_spec_sha256": self.compiler_spec_sha256,
            "compiler_version": COMPILER_VERSION,
            "constraints": [constraint.as_dict() for constraint in self.constraints],
            "domain_mode": self.domain_mode,
            "endianness": "LITTLE_ENDIAN",
            "gate_set": list(ABSTRACT_GATE_SET),
            "instance_id": self.instance_id,
            "k": self.k,
            "n": self.n,
            "parent_artifact_file_sha256": self.parent_artifact_file_sha256,
            "parent_dyadic_oracle_sha": self.parent_dyadic_oracle_sha,
            "registers": [register.as_dict() for register in self.registers],
            "seed": self.seed,
            "unitary": "|x>|y>|0> -> |x>|y XOR f(x)>|0>",
        }


def _signed_width(lower: int, upper: int) -> int:
    width = 2
    while lower < -(1 << (width - 1)) or upper > (1 << (width - 1)) - 1:
        width += 1
    return width


def _unsigned_width(upper: int) -> int:
    if upper < 0:
        raise ValueError("Unsigned width cannot contain a negative maximum.")
    return max(1, int(upper).bit_length())


def _exact_k_prefix_range(coefficients: Sequence[int], n: int, k: int) -> dict[str, Any]:
    """Prove prefix accumulator bounds for inputs extendable to popcount K."""

    if len(coefficients) != n:
        raise ValueError("Exact-K range proof requires one coefficient per data qubit.")
    global_min = 0
    global_max = 0
    worst_min_prefix = 0
    worst_max_prefix = 0
    for prefix_size in range(1, n + 1):
        prefix = sorted(int(value) for value in coefficients[:prefix_size])
        min_selected = max(0, k - (n - prefix_size))
        max_selected = min(k, prefix_size)
        local_mins = [sum(prefix[:count]) for count in range(min_selected, max_selected + 1)]
        local_maxs = [
            sum(prefix[prefix_size - count :]) if count else 0
            for count in range(min_selected, max_selected + 1)
        ]
        local_min = min(local_mins)
        local_max = max(local_maxs)
        if local_min < global_min:
            global_min = local_min
            worst_min_prefix = prefix_size
        if local_max > global_max:
            global_max = local_max
            worst_max_prefix = prefix_size
    return {
        "domain_assumption": f"popcount(x)={k}",
        "max_prefix_sum": int(global_max),
        "min_prefix_sum": int(global_min),
        "proof_method": "EXACT_K_EXTENDABLE_PREFIX_ENUMERATION",
        "worst_max_prefix_size": worst_max_prefix,
        "worst_min_prefix_size": worst_min_prefix,
    }


def _full_binary_prefix_range(coefficients: Sequence[int]) -> dict[str, Any]:
    global_min = 0
    global_max = 0
    running_min = 0
    running_max = 0
    worst_min_prefix = 0
    worst_max_prefix = 0
    for prefix_size, coefficient in enumerate(coefficients, start=1):
        running_min += min(0, int(coefficient))
        running_max += max(0, int(coefficient))
        if running_min < global_min:
            global_min = running_min
            worst_min_prefix = prefix_size
        if running_max > global_max:
            global_max = running_max
            worst_max_prefix = prefix_size
    return {
        "domain_assumption": "x in {0,1}^N",
        "max_prefix_sum": int(global_max),
        "min_prefix_sum": int(global_min),
        "proof_method": "FULL_BINARY_PREFIX_SIGN_ENVELOPE",
        "worst_max_prefix_size": worst_max_prefix,
        "worst_min_prefix_size": worst_min_prefix,
    }


def factor_range_certificate(
    coefficients: Sequence[int],
    lower: int,
    upper: int,
    *,
    n: int,
    k: int,
    domain_mode: str,
) -> dict[str, Any]:
    """Return a fail-closed signed-width proof for one factor accumulator."""

    if domain_mode == DOMAIN_EXACT_K:
        proof = _exact_k_prefix_range(coefficients, n, k)
    elif domain_mode == DOMAIN_FULL_BINARY:
        proof = _full_binary_prefix_range(coefficients)
    else:
        raise ValueError(f"Unsupported oracle domain: {domain_mode}")
    required_min = min(0, int(lower), int(upper), int(proof["min_prefix_sum"]))
    required_max = max(0, int(lower), int(upper), int(proof["max_prefix_sum"]))
    width = _signed_width(required_min, required_max)
    signed_min = -(1 << (width - 1))
    signed_max = (1 << (width - 1)) - 1
    return {
        **proof,
        "certified": bool(signed_min <= required_min <= required_max <= signed_max),
        "required_max": required_max,
        "required_min": required_min,
        "signed_max": signed_max,
        "signed_min": signed_min,
        "width": width,
    }


def _count_range_certificate(size: int, lower: int, upper: int) -> dict[str, Any]:
    required_max = max(int(size), int(lower), int(upper), 0)
    width = _unsigned_width(required_max)
    return {
        "certified": bool(0 <= lower <= upper <= (1 << width) - 1 and size <= (1 << width) - 1),
        "domain_assumption": "binary count",
        "max_prefix_sum": int(size),
        "min_prefix_sum": 0,
        "proof_method": "MONOTONE_UNIT_COEFFICIENT_COUNT",
        "required_max": required_max,
        "required_min": 0,
        "unsigned_max": (1 << width) - 1,
        "width": width,
    }


def constraints_from_certificate(
    certificate: Mapping[str, Any], domain_mode: str
) -> tuple[ConstraintIR, ...]:
    """Build auditable constraint IR from one authenticated parent certificate."""

    if domain_mode not in SUPPORTED_DOMAINS:
        raise ValueError(f"Unsupported oracle domain: {domain_mode}")
    n = int(certificate["N"])
    k = int(certificate["K"])
    constraints: list[ConstraintIR] = []
    if domain_mode == DOMAIN_FULL_BINARY:
        cardinality_range = _count_range_certificate(n, k, k)
        constraints.append(
            ConstraintIR(
                kind="CARDINALITY",
                name="CARDINALITY_K",
                data_indices=tuple(range(n)),
                coefficients=tuple(1 for _ in range(n)),
                lower=k,
                upper=k,
                width=int(cardinality_range["width"]),
                signed=False,
                range_certificate=cardinality_range,
            )
        )

    groups = certificate.get("group_bands")
    factors = certificate.get("factor_bands")
    if not isinstance(groups, list) or not isinstance(factors, list):
        raise ValueError("Parent certificate is missing group/factor bands.")
    for group in groups:
        indices = tuple(int(value) for value in group["indices"])
        proof = _count_range_certificate(
            len(indices), int(group["lower"]), int(group["upper"])
        )
        width = int(proof["width"])
        if width != int(group["counter_bits"]):
            raise ValueError(f"Frozen counter width mismatch for {group['name']}.")
        constraints.append(
            ConstraintIR(
                kind="GROUP",
                name=str(group["name"]),
                data_indices=indices,
                coefficients=tuple(1 for _ in indices),
                lower=int(group["lower"]),
                upper=int(group["upper"]),
                width=width,
                signed=False,
                range_certificate=proof,
            )
        )

    for factor in factors:
        coefficients = tuple(int(value) for value in factor["coefficients_int"])
        if len(coefficients) != n:
            raise ValueError(f"Frozen coefficient count mismatch for {factor['name']}.")
        proof = factor_range_certificate(
            coefficients,
            int(factor["lower_int"]),
            int(factor["upper_int"]),
            n=n,
            k=k,
            domain_mode=domain_mode,
        )
        if not proof["certified"]:
            raise ValueError(f"Accumulator range proof failed for {factor['name']}.")
        if domain_mode == DOMAIN_EXACT_K and int(proof["width"]) != int(
            factor["accumulator_signed_bits"]
        ):
            raise ValueError(f"Frozen exact-K width mismatch for {factor['name']}.")
        constraints.append(
            ConstraintIR(
                kind="FACTOR",
                name=str(factor["name"]),
                data_indices=tuple(range(n)),
                coefficients=coefficients,
                lower=int(factor["lower_int"]),
                upper=int(factor["upper_int"]),
                width=int(proof["width"]),
                signed=True,
                range_certificate=proof,
            )
        )
    expected = 7 if domain_mode == DOMAIN_EXACT_K else 8
    if len(constraints) != expected:
        raise ValueError(f"Expected {expected} constraints, received {len(constraints)}.")
    return tuple(constraints)


def _allocate_registers(n: int, constraints: Sequence[ConstraintIR]) -> tuple[Register, ...]:
    work_width = max(constraint.width for constraint in constraints)
    cursor = 0
    registers: list[Register] = []

    def add(name: str, size: int, role: str, signed: bool = False) -> None:
        nonlocal cursor
        registers.append(Register(name, cursor, size, role, signed))
        cursor += size

    add("data", n, "CALLER_OWNED_INPUT")
    add("target", 1, "CALLER_OWNED_OUTPUT")
    add("work", work_width, "SEQUENTIALLY_REUSED_ACCUMULATOR", True)
    add("compare_ge", 1, "CLEAN_COMPARATOR_FLAG")
    add("compare_le", 1, "CLEAN_COMPARATOR_FLAG")
    add("constraint_flags", len(constraints), "CLEAN_CONSTRAINT_FLAGS")
    add("aggregate", 1, "CLEAN_CONJUNCTION_FLAG")
    return tuple(registers)


def compile_seed_circuit(
    certificate: Mapping[str, Any],
    domain_mode: str,
    *,
    parent_dyadic_oracle_sha: str,
    parent_artifact_file_sha256: str,
    compiler_spec: Mapping[str, Any] | None = None,
) -> CircuitIR:
    """Compile one authenticated seed certificate to deterministic circuit IR."""

    spec = dict(compiler_spec) if compiler_spec is not None else load_compiler_spec()
    constraints = constraints_from_certificate(certificate, domain_mode)
    registers = _allocate_registers(int(certificate["N"]), constraints)
    return CircuitIR(
        seed=int(certificate["seed"]),
        instance_id=str(certificate["instance_id"]),
        n=int(certificate["N"]),
        k=int(certificate["K"]),
        domain_mode=domain_mode,
        parent_dyadic_oracle_sha=str(parent_dyadic_oracle_sha),
        parent_artifact_file_sha256=str(parent_artifact_file_sha256),
        compiler_spec_sha256=str(spec["gate_compiler_spec_sha256"]),
        registers=registers,
        constraints=constraints,
    )


def reversible_increment(
    control: int,
    register_bits: Sequence[int],
    *,
    inverse: bool = False,
    stage: str = "ARITHMETIC",
    label: str = "INCREMENT",
) -> Iterator[Gate]:
    """Controlled increment/decrement of a little-endian register modulo 2**w."""

    bits = tuple(int(value) for value in register_bits)
    if not bits:
        return
    forward = [
        make_gate(
            bits[index],
            (int(control),) + bits[:index],
            stage=stage,
            label=label,
        )
        for index in range(len(bits) - 1, -1, -1)
    ]
    yield from (reversed(forward) if inverse else forward)


def controlled_add_constant(
    control: int,
    register_bits: Sequence[int],
    constant: int,
    *,
    inverse: bool = False,
    stage: str = "ARITHMETIC",
    label: str = "ADD_CONSTANT",
) -> Iterator[Gate]:
    """Controlled exact two's-complement constant addition modulo 2**w."""

    bits = tuple(int(value) for value in register_bits)
    if not bits:
        raise ValueError("Addition register cannot be empty.")
    encoded = int(constant) & ((1 << len(bits)) - 1)
    set_positions = [index for index in range(len(bits) - 1, -1, -1) if (encoded >> index) & 1]
    if inverse:
        set_positions = list(reversed(set_positions))
    for position in set_positions:
        yield from reversible_increment(
            control,
            bits[position:],
            inverse=inverse,
            stage=stage,
            label=f"{label}@2^{position}",
        )


def _order_key_bits(value: int, width: int, signed: bool) -> list[int]:
    encoded = int(value) & ((1 << width) - 1)
    result = [(encoded >> index) & 1 for index in range(width)]
    if signed:
        result[width - 1] ^= 1
    return result


def _actual_control_value(key_value: int, index: int, width: int, signed: bool) -> int:
    return int(key_value) ^ int(bool(signed and index == width - 1))


def compare_inclusive(
    register_bits: Sequence[int],
    constant: int,
    target: int,
    *,
    relation: str,
    signed: bool,
    inverse: bool = False,
    stage: str = "COMPARATOR",
    label: str = "COMPARE",
) -> Iterator[Gate]:
    """Toggle target iff the register is >= or <= an inclusive constant.

    Disjoint highest-differing-bit terms plus equality ensure at most one MCX
    fires for any input.  Signed order uses virtual sign-bit inversion, so no
    mutation of the accumulator register is needed.
    """

    bits = tuple(int(value) for value in register_bits)
    width = len(bits)
    if width < 1:
        raise ValueError("Comparator register cannot be empty.")
    if relation not in {"GE", "LE"}:
        raise ValueError("Comparator relation must be GE or LE.")
    minimum = -(1 << (width - 1)) if signed else 0
    maximum = (1 << (width - 1)) - 1 if signed else (1 << width) - 1
    if relation == "GE" and constant <= minimum:
        yield make_gate(target, stage=stage, label=f"{label}:ALWAYS_TRUE")
        return
    if relation == "GE" and constant > maximum:
        return
    if relation == "LE" and constant >= maximum:
        yield make_gate(target, stage=stage, label=f"{label}:ALWAYS_TRUE")
        return
    if relation == "LE" and constant < minimum:
        return

    key = _order_key_bits(int(constant), width, signed)
    terms: list[Gate] = []
    # A greater-than term exists where the constant key bit is zero; a
    # less-than term exists where it is one.  Higher key bits must match.
    differing_constant = 0 if relation == "GE" else 1
    differing_input = 1 if relation == "GE" else 0
    for index in range(width - 1, -1, -1):
        if key[index] != differing_constant:
            continue
        control_indices = [bits[index]] + [bits[higher] for higher in range(index + 1, width)]
        control_values = [
            _actual_control_value(differing_input, index, width, signed)
        ] + [
            _actual_control_value(key[higher], higher, width, signed)
            for higher in range(index + 1, width)
        ]
        terms.append(
            make_gate(
                target,
                control_indices,
                control_values,
                stage=stage,
                label=f"{label}:{relation}:DIFF@{index}",
            )
        )
    equality_values = [
        _actual_control_value(key[index], index, width, signed)
        for index in range(width)
    ]
    terms.append(
        make_gate(
            target,
            bits,
            equality_values,
            stage=stage,
            label=f"{label}:{relation}:EQUALITY",
        )
    )
    yield from (reversed(terms) if inverse else terms)


def _constraint_gate_stream(
    circuit: CircuitIR, constraint_index: int, *, stage_prefix: str
) -> Iterator[Gate]:
    constraint = circuit.constraints[constraint_index]
    data = circuit.register("data").bits
    work = circuit.register("work").bits[: constraint.width]
    ge = circuit.register("compare_ge").bits[0]
    le = circuit.register("compare_le").bits[0]
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
    yield from compare_inclusive(
        work,
        constraint.lower,
        ge,
        relation="GE",
        signed=constraint.signed,
        stage=f"{prefix}:COMPARE",
        label="LOWER_BOUND",
    )
    yield from compare_inclusive(
        work,
        constraint.upper,
        le,
        relation="LE",
        signed=constraint.signed,
        stage=f"{prefix}:COMPARE",
        label="UPPER_BOUND",
    )
    yield make_gate(
        flag,
        (ge, le),
        stage=f"{prefix}:FLAG",
        label="INCLUSIVE_BAND_AND",
    )
    yield from compare_inclusive(
        work,
        constraint.upper,
        le,
        relation="LE",
        signed=constraint.signed,
        inverse=True,
        stage=f"{prefix}:UNCOMPUTE_COMPARE",
        label="UPPER_BOUND",
    )
    yield from compare_inclusive(
        work,
        constraint.lower,
        ge,
        relation="GE",
        signed=constraint.signed,
        inverse=True,
        stage=f"{prefix}:UNCOMPUTE_COMPARE",
        label="LOWER_BOUND",
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


def _oracle_gate_stream(circuit: CircuitIR) -> Iterator[Gate]:
    flags = circuit.register("constraint_flags").bits
    aggregate = circuit.register("aggregate").bits[0]
    target = circuit.register("target").bits[0]
    for index in range(len(circuit.constraints)):
        yield from _constraint_gate_stream(circuit, index, stage_prefix="COMPUTE")
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
        yield from _constraint_gate_stream(circuit, index, stage_prefix="UNCOMPUTE")


def gate_ir_sha256(circuit: CircuitIR) -> str:
    """Stream a deterministic hash without materialising the full circuit."""

    digest = hashlib.sha256()
    digest.update(canonical_json_bytes({"header": circuit.header_payload()}))
    digest.update(b"\n")
    for gate in circuit.iter_gates():
        digest.update(canonical_json_bytes(gate.as_dict()))
        digest.update(b"\n")
    return digest.hexdigest()


def classical_constraint_value(bits: Sequence[int], constraint: ConstraintIR) -> int:
    return sum(
        int(coefficient) * int(bits[index])
        for index, coefficient in zip(
            constraint.data_indices, constraint.coefficients
        )
    )


def classical_predicate(bits: Sequence[int], circuit: CircuitIR) -> bool:
    if len(bits) != circuit.n or any(int(value) not in (0, 1) for value in bits):
        raise ValueError("Classical input must contain exactly N binary values.")
    if circuit.domain_mode == DOMAIN_EXACT_K and sum(int(value) for value in bits) != circuit.k:
        raise ValueError("EXACT_K_SUBSPACE predicate called outside its declared domain.")
    return all(
        constraint.lower
        <= classical_constraint_value(bits, constraint)
        <= constraint.upper
        for constraint in circuit.constraints
    )


def simulate_basis_state(
    circuit: CircuitIR,
    bits: Sequence[int],
    *,
    target: int = 0,
) -> dict[str, Any]:
    """Execute abstract gates on one computational-basis state."""

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


def analyze_circuit(circuit: CircuitIR) -> dict[str, Any]:
    """Stream an institutional multi-level resource and provenance ledger."""

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

    for gate in circuit.iter_gates():
        total_gates += 1
        if gate.stage == "ORACLE_OUTPUT":
            output_gate_position = total_gates
        abstract_counts[gate.kind] += 1
        digest.update(canonical_json_bytes(gate.as_dict()))
        digest.update(b"\n")
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

    decomposed_cnot = decomposed_cx + 6 * decomposed_ccx
    t_count = 7 * decomposed_ccx
    base_adds = sum(
        sum(1 for coefficient in constraint.coefficients if coefficient)
        for constraint in circuit.constraints
    )
    controlled_add_count = 4 * base_adds
    comparator_count = 8 * len(circuit.constraints)
    uncompute_gates = (
        total_gates - output_gate_position if output_gate_position is not None else 0
    )
    forward_gates = (
        output_gate_position - 1 if output_gate_position is not None else total_gates
    )
    work_qubits = circuit.register("work").size
    flag_qubits = circuit.register("constraint_flags").size
    logical_ancillas = work_qubits + 2 + flag_qubits + 1
    range_widths = {
        constraint.name: constraint.width for constraint in circuit.constraints
    }

    return {
        "claim_boundary": {
            "hardware_executable": False,
            "qpu_submission_enabled": False,
            "status": "PROVIDER_NEUTRAL_GATE_IR · NOT BACKEND TRANSPILED",
        },
        "domain_mode": circuit.domain_mode,
        "gate_ir_sha256": digest.hexdigest(),
        "instance_id": circuit.instance_id,
        "levels": {
            "FAULT_TOLERANT_ESTIMATE": {
                "basis": "CLEAN_ANCILLA_MCX_V_CHAIN_AND_7T_CCX_UPPER_BOUND",
                "clean_mcx_decomposition_ancillas": clean_mcx_ancillas,
                "decomposed_ccx": decomposed_ccx,
                "decomposed_cnot": decomposed_cnot,
                "decomposed_x": decomposed_x,
                "logical_qubits_with_decomposition_ancillas": (
                    circuit.logical_qubits + clean_mcx_ancillas
                ),
                "t_count": t_count,
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
                "comparator_count": comparator_count,
                "constraint_flag_qubits": flag_qubits,
                "controlled_add_count": controlled_add_count,
                "controlled_add_count_forward_predicate": base_adds,
                "data_qubits": circuit.n,
                "logical_qubits_total": circuit.logical_qubits,
                "max_simultaneously_live_ancillas": logical_ancillas,
                "range_certified_widths": range_widths,
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
        "parent_artifact_file_sha256": circuit.parent_artifact_file_sha256,
        "parent_dyadic_oracle_sha": circuit.parent_dyadic_oracle_sha,
        "seed": circuit.seed,
    }


def circuit_manifest(circuit: CircuitIR) -> dict[str, Any]:
    """Return a compact deterministic description suitable for sealed artifacts."""

    ledger = analyze_circuit(circuit)
    return {
        "circuit_header": circuit.header_payload(),
        "gate_ir_sha256": ledger["gate_ir_sha256"],
        "resource_ledger": ledger,
    }


__all__ = [
    "ABSTRACT_GATE_SET",
    "COMPILER_VERSION",
    "CircuitIR",
    "ConstraintIR",
    "DOMAIN_EXACT_K",
    "DOMAIN_FULL_BINARY",
    "Gate",
    "Register",
    "SUPPORTED_DOMAINS",
    "analyze_circuit",
    "canonical_json_bytes",
    "canonical_json_sha256",
    "circuit_manifest",
    "classical_constraint_value",
    "classical_predicate",
    "compile_seed_circuit",
    "compiler_source_sha256",
    "constraints_from_certificate",
    "controlled_add_constant",
    "factor_range_certificate",
    "gate_ir_sha256",
    "load_compiler_spec",
    "make_gate",
    "compare_inclusive",
    "reversible_increment",
    "simulate_basis_state",
]
