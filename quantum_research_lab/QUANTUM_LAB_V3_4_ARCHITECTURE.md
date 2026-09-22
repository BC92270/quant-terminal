# Quantum Lab V3.4 — Optimized Oracle and Elementary Guarded Mixer

## Release position

V3.4 is an additive, research-only successor to the frozen V3.3 feasible-subspace
contract. It advances two previously open engineering gates without altering the
frozen financial instance, dyadic coefficients, exact-K domain, seven hard
constraints, mixer topology decision, or hardware claim boundary:

1. it replaces the two-live-flag inclusive-band comparator with a one-flag exact
   disjoint-violation identity; and
2. it lowers the abstract doubly-controlled XY primitive to a deterministic
   provider-neutral schedule over CCX, CX, RY and Clifford RZ gates.

The result is not called backend-native. Named-backend transpilation, coupling-map
routing, calibration, noise, pulse execution and QPU jobs remain absent.

## Lineage and change control

The V3.4 evidence artifact is buildable only while all 15 files in the V3.3 freeze
are byte-exact and the V3.3 13-gate release chain plus five-gate freeze verifier
pass. After that artifact is sealed, only `quantum_research_lab/ui.py` is declared
as a successor surface. The V3.4 freeze binds the replacement UI bytes and every
new V3.4 source, specification, test, artifact and verifier. All other V3.3 frozen
files remain byte-exact.

## Exact interval-flag optimization

For an integer accumulator `v` and inclusive interval `L <= U`, V3.4 uses

```text
inside(v) = 1 XOR [v <= L - 1] XOR [v >= U + 1].
```

The two violation predicates are disjoint. Toggling one clean target by the three
terms therefore computes the exact inclusive-band bit without materializing
separate greater-or-equal and less-or-equal flags or applying their conjunction.
The same network is self-inverse and is reused during uncomputation.

Consequences for each exact-K oracle:

- two logical comparator qubits are removed;
- comparator networks fall from 56 to 28 for the seven-constraint oracle;
- accumulator arithmetic, range proofs, signed two's-complement ordering and
  frozen predicate semantics remain unchanged;
- gate count, depth and the selected 7T-CCX subtotal must be strictly lower for
  every one of the eight preregistered N=40 seeds.

## Elementary C2-XY lowering

Let `a=f(x)` be the cached current-state feasibility bit and
`b=f(S_ij x)` the transient neighbor feasibility bit. With clean scratch bits
`t` and `g`, one mixer edge is lowered in chronological order as:

```text
CX(i,j)
CCX(a,b,t)
CCX(t,j,g)
RZ_i(+pi/2)
CX(g,i)
RY_i(-beta)
CX(g,i)
RY_i(+beta)
RZ_i(-pi/2)
CCX(t,j,g)
CCX(a,b,t)
CX(i,j)
```

The outer CNOTs map odd data parity to the `j=1` control sector. The clean AND
ladder converts `(a,b,j)` into a single control. The middle six gates implement
`CRX(2 beta)` exactly. Reversing the AND ladder returns both scratch bits to zero.

Per edge, the exact provider-neutral inventory is 4 CCX, 4 CX, 2 continuous RY
and 2 Clifford `RZ(±pi/2)` gates. Under the selected accounting convention of
7 T/T-dagger, 6 CX and 2 H per CCX, the subtotal becomes 28 T/T-dagger, 28 CX,
8 H, two continuous RY and two Clifford RZ gates. Approximation of the continuous
rotations into a discrete fault-tolerant set is deliberately `NOT_ESTIMATED`.

The two scratch bits are borrowed from the oracle work register after clean
uncomputation, so this lowering adds zero qubits to the sequential-reuse envelope.

## Validation ladder

The seal requires all nine independent gates:

1. V3.3 13/13 release and 5/5 freeze authentication;
2. V3.4 specification self-hash;
3. exhaustive interval truth tables for signed and unsigned widths 1 through 6;
4. N=40 differential equivalence on all eight seeds;
5. real frozen-constraint boundary tests;
6. elementary C2-XY matrix equivalence and scratch cleanup;
7. resource reduction and deterministic reproduction;
8. retention of the V3.3 negative connectivity result; and
9. hardware and advantage fail-closed boundaries.

The interval test covers 610,104 basis cases. The N=40 differential layer checks
all 2,400 nontrivial authenticated-witness swaps and 48 full gate-stream cases
covering target inputs 0 and 1, feasible and infeasible states, data preservation,
and complete ancilla cleanup. The elementary mixer test covers all 16 clean
logical basis inputs at six preregistered angles (96 cases).

The sealed JSON artifact is the authoritative source for per-seed hashes, exact
resource maxima, numerical errors and validation manifests.

## Sealed outcome

The canonical V3.4 artifact passed all nine gates with these release identities:

- semantic artifact SHA-256: `2753b81527bf470b8528550d4de491b968e114e4d59541fd16aeca2d995c9210`;
- validation manifest SHA-256: `cfbe1b9c55002b9386d3e5b2b59373b0689532deffe3c8de41736a7b10213b45`;
- resource manifest SHA-256: `c08112f636b2d3d7af167224338eb78ad59ef99effda8a4c43e1a1dda5e3632f`;
- elementary schedule SHA-256: `9231aceff98277a4e3d3e85cc9d520b2d5a61d434250e5fdeaa1c1333aa046bc`.

The complete-swap maxima are 118 logical qubits under sequential reuse,
668,278,258 provider-neutral gates, serial-depth upper bound 628,414,456,
149,405,532,710 CNOTs under the selected CCX cost model, and a subtotal of
174,280,328,040 T/T-dagger gates before continuous-rotation synthesis. There
are 1,560 continuous RY rotations per complete ordered layer.

Every seed improves over its V3.3 complete-layer ledger even after replacing
the one-placeholder-per-edge mixer cost by the full 12-gate schedule. The
provider-neutral reduction ranges from 534,996 to 728,684 gates; the selected
T subtotal reduction ranges from 172,494,812 to 272,803,328. These reductions
are material but do not reverse the NISQ-practicality rejection.

## Institutional claim ledger

| Claim | V3.4 decision | Evidence boundary |
|---|---|---|
| Optimized oracle equals frozen V3.2 predicate | PASS | Exact-K, eight N=40 seeds, structural proof plus differential/gate tests |
| Comparator/qubit/resource reduction | PASS if seal exists | Exact provider-neutral IR and selected CCX accounting model |
| Elementary C2-XY identity | PASS if seal exists | Exact continuous-rotation matrix, clean scratch |
| Backend-native circuit | NOT RUN | No target instruction set or named backend |
| Complete feasible-graph connectivity | INDETERMINATE | V3.3 local witness study only |
| Ring topology | REJECTED | Authenticated seed-5501 isolated witness retained |
| Optimization performance | NOT TESTED | No variational optimization or sampling study |
| Hardware execution | BLOCKED — ZERO JOBS | No submission path enabled |
| Quantum advantage | NOT CLAIMED | No accepted hardware/runtime evidence |

## Next falsifiable gate

V3.5 should not start by submitting circuits. It should first select a named,
versioned backend target and freeze:

- SDK and transpiler versions;
- target instruction set, coupling map and calibration timestamp;
- controlled-rotation approximation tolerance and synthesis method;
- routing seeds and optimization level;
- routed width/depth/2Q count acceptance budgets;
- a noise-aware rejection rule; and
- an explicit zero-job transpilation-only phase before any execution protocol.

If the routed resource envelope violates the preregistered budget, the backend
candidate is rejected and that negative result is retained. A different encoding
or mixer requires a new specification and untouched confirmatory evaluation.
