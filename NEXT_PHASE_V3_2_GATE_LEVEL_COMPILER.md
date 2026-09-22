# V3.2 — Reversible Gate-Level BANDS Compiler

## Purpose

V3.2 must compile the **sealed exact dyadic BANDS logical IR** into an explicit reversible quantum circuit while preserving the Phase-II hard-constraint semantics and the clean-ancilla contract.

This is a compiler phase, **not** a QPU execution phase.

## Hard prerequisite

Do not start V3.2 until the live V3.1 application has sealed the dyadic logical oracle and produced a valid immutable artifact.

The sealed logical oracle must remain:

- exact dyadic / binary64 semantics;
- `N=40 · BANDS`;
- all 8 sealed seeds;
- 4 group-count bands;
- 3 factor-exposure bands;
- max accumulator width observed = 68 bits;
- clean ancillas required;
- `hardware_executable=false` before compiler seal.

## Recommended new files

```text
quantum_research_lab/
  phase3_gate_compiler.py
  PHASE_III_GATE_COMPILER_SPEC_V1.json
  phase3_circuit_validation.py        # optional split if compiler becomes large
```

Do not put this implementation into `engine.py`.

## Compiler contract

The compiler must map the V3.1 reversible schedule to gates with no semantic relaxation:

1. exact-K witness-feasible computational basis initialization;
2. group-count registers;
3. exact controlled additions for selected bits;
4. lower/upper integer comparisons;
5. factor signed accumulators using exact dyadic integer constants;
6. lower/upper signed comparisons;
7. four group flags + three factor flags;
8. aggregate feasibility flag;
9. caller-visible feasibility control;
10. full reverse uncomputation to clean all work ancillas.

## Register semantics

Codex must define and freeze:

- qubit indexing convention;
- little-endian vs big-endian order;
- signed representation: use one explicit convention, preferably two's complement;
- overflow rules: overflow must be impossible by construction from certified accumulator bounds;
- constant encoding for positive and negative dyadic integers;
- comparator convention (`>= L`, `<= U` inclusive);
- temporary/carry ancilla lifecycle;
- exact reset/uncompute requirement.

Every choice must be written into `PHASE_III_GATE_COMPILER_SPEC_V1.json` before any hardware result is observed.

## Arithmetic primitives

At minimum implement and test reusable primitives:

```python
controlled_add_signed_constant(...)
reversible_unsigned_increment(...)
reversible_compare_ge_constant(...)
reversible_compare_le_constant(...)
aggregate_flags_and(...)
uncompute_aggregate_flags(...)
```

Prefer exact reversible arithmetic with auditable resource counts. The initial implementation should favor correctness and resource transparency over clever opaque optimizations.

## Group-count oracle

For each group `g`:

```text
|x> |0_count> |0_flags>
    -> controlled count selected x_i
    -> compare count >= L_g
    -> compare count <= U_g
    -> set group flag
    -> uncompute comparisons
    -> uncompute count
```

The final group flag may remain until the global feasibility flag has been formed, then must be uncomputed after use.

## Factor-exposure oracle

For each factor `f`:

```text
A_f(x) = Σ B_if x_i
```

where `B_if` are the exact V3.1 dyadic integers and the bounds are `L_f_int`, `U_f_int`.

Required sequence:

```text
|x>|0_acc>
 -> controlled add B_1 if x_1=1
 -> ...
 -> controlled add B_40 if x_40=1
 -> signed compare A_f >= L_f_int
 -> signed compare A_f <= U_f_int
 -> factor flag
 -> uncompute comparisons
 -> reverse all controlled adds
 -> |0_acc>
```

No coefficient rounding is allowed.

## Algorithmic enforcement issue — must not be skipped

A feasibility oracle alone does **not** automatically make QAOA a hard-constrained optimizer.

The current XY mixer preserves exact cardinality but does not necessarily preserve group-count and factor-exposure bands. V3.2/V3.3 must therefore explicitly choose and audit how the oracle is used.

Candidate paths to study:

1. **Feasible-subspace / Grover mixer**
   - prepare or reflect about a feasible-state superposition;
   - use the exact feasibility oracle as a subroutine;
   - potentially expensive but clean hard-constraint semantics.

2. **Quantum Alternating Operator Ansatz with constraint-aware mixer**
   - design moves that preserve all BANDS constraints;
   - difficult for real-valued factor bands;
   - potentially more efficient if a valid move graph can be constructed.

3. **Oracle-assisted projected/rejection dynamics**
   - use exact feasibility marking in an algorithm whose mathematical objective remains optimization over the feasible set;
   - must be formalized before hardware protocol seal.

4. **Provably sufficient exact penalty**
   - only admissible if a formal bound proves strict separation of every infeasible state from every feasible state and the benchmark semantics are explicitly redefined before hardware execution;
   - do not reuse arbitrary V2.4-style penalties.

Do **not** silently use a normal X mixer plus a convenient penalty.

## Validation ladder for V3.2

### Level A — arithmetic primitive tests

For small register widths, exhaustively test every basis state against classical integer arithmetic.

### Level B — seed-level oracle tests

For each of the 8 N=40 BANDS seeds:

- verify the circuit's feasibility flag on all available authoritative witness states;
- construct adversarial boundary states from the V3.0 counterexamples where possible;
- verify group/factor flag decomposition;
- verify every work register returns to zero after uncompute.

### Level C — small-N exhaustive compiler proof

Generate reduced BANDS instances at small N where all `2^N` states can be checked. Compare:

```text
classical strict BANDS feasibility
== exact dyadic integer feasibility
== simulated gate-level oracle output
```

Require zero mismatches.

### Level D — N=40 implementation controls

For the real candidate family:

- use deterministic test vectors;
- include witness-feasible states;
- include known near-boundary / V3.0 mismatch states;
- include randomized exact-K states as implementation controls only;
- never call sampling a proof of fidelity.

## Required resource accounting

V3.2 must report at least:

- logical qubits total;
- data qubits;
- work/ancilla qubits;
- maximum simultaneously live ancillas;
- controlled-add count;
- comparator count;
- X / CX / CCX counts before decomposition;
- Toffoli count;
- CNOT / two-qubit count after decomposition;
- T-count and T-depth for a fault-tolerant decomposition path;
- total depth;
- critical-path depth;
- uncomputation overhead;
- cost per group constraint;
- cost per factor constraint;
- cost per full feasibility-oracle call.

Resource reports must be separated into:

```text
LOGICAL IR
GATE-LEVEL ABSTRACT
TRANSPILED BACKEND-SPECIFIC
FAULT-TOLERANT ESTIMATE
```

Do not mix these categories.

## Compiler seal

Add a new immutable seal only after the above validations pass:

```text
PHASE_III_GATE_COMPILER_SPEC_V1.json
GATE_COMPILER_SPEC_SHA
SEALED_GATE_COMPILER_ARTIFACT.json
GATE_COMPILER_ARTIFACT_SHA
```

The seal should contain:

- parent dyadic oracle SHA;
- compiler source SHA;
- arithmetic convention;
- register layout;
- resource counts;
- validation summary;
- canonical test vectors and hashes;
- exact circuit-construction version;
- `hardware_executable=false` until backend-specific routing/capacity tests pass.

## After V3.2

### V3.3 — Backend Compilation & Routing Audit

- install optional Qiskit / runtime stack outside the frozen scientific core;
- discover named backends;
- snapshot backend calibration metadata;
- transpile the sealed compiler output;
- report routed depth, two-qubit gates, SWAP overhead, backend qubit usage, connectivity bottlenecks;
- reject backend if circuit cannot be represented faithfully or capacity is insufficient.

### V3.4 — Phase-III Hardware Protocol Seal

Only once:

- Phase II passed;
- exact dyadic oracle sealed;
- gate-level compiler sealed;
- algorithmic hard-constraint enforcement formally specified;
- named backend snapshot passes;
- routing/depth/resource criteria pass.

Then create a preregistered hardware protocol. Still do not claim advantage before execution.

### V3.5 — Hardware Execution

Run the sealed equal-objective benchmark across all 8 seeds, predeclared depth schedule, shots, and repeats. Record queue time separately from device/compute time. Preserve failed hardware runs according to the preregistration.
