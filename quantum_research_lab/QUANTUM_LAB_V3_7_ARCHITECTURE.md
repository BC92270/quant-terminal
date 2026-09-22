# Quantum Lab V3.7 — Proof-Carrying Reversible Incremental Exposure

## Release position

V3.7 is an additive, provider-free `RESEARCH_ONLY` successor to the sealed
V3.6 structural diagnosis. V3.6 proved that topology-only work cannot repair
the frozen V3.4 representation: even its cheapest mandatory oracle
compute/uncompute pair costs `184,191,414` selected-model CNOT, while the
internal research screen is `2,500,000`. It therefore left one exact lane at a
precise falsifiable boundary:

`BLOCKED_PENDING_REVERSIBLE_COMPILER`.

V3.7 closes that boundary only on a registered small instance. It implements a
coherent state-augmented swap, compiles it to a deterministic logical gate IR,
checks every computational-basis column, proves the reverse schedule, and
publishes an honest logical resource ledger. The resulting decision is:

`SMALL_INSTANCE_REVERSIBLE_PROTOTYPE_PASSED`.

The production decision remains independently closed:

`N40_REWRITE_ADMISSION_BLOCKED`.

This separation is the central result of the release. A valid small reversible
construction is evidence that the proposed mechanism is coherent; it is not
evidence that the seven-constraint N=40 compiler is small, elementary,
backend-native or useful for optimization.

## Immutable predecessor

The scientific builder authenticates the exact V3.6 artifact before creating
any V3.7 result:

- semantic SHA-256:
  `52b9b98a36bf8f6d661b42cdc63f3cc0f6476c207f273a171dcc0516c4c0a54d`;
- raw-file SHA-256:
  `147e81ebb891f61ec47dd9b46ab0adfc6a7a73e2e21f5b91e42d99b25de7c26c`;
- predecessor gate:
  `CLEAN_REVERSIBLE_INCREMENTAL_EXPOSURE_COMPILER`; and
- predecessor lane state:
  `BLOCKED_PENDING_REVERSIBLE_COMPILER`.

The release installer and independent verifier additionally authenticate the
raw and semantic V3.6 freeze, its exact 57-path inventory and all 55 immutable
paths outside the authorized README/UI successor pair. Old verifiers and
scientific artifacts remain byte-identical.

## Registered prototype fixture

The fixture is synthetic by construction and is never represented as an N=40
sample or performance benchmark.

| Contract | Value |
|---|---|
| Fixture | `V37_SYNTHETIC_EXACT_K_N4_K2_V1` |
| Classification | `SYNTHETIC_COMPILER_FIXTURE · PROTOTYPE_ONLY` |
| Portfolio width | N=4 |
| Cardinality | K=2 |
| Candidate swap edges | 6 complete variable pairs |
| Exposure rows | 2 |
| Cache encoding | 3-bit unsigned + 3-bit two's complement |
| Total data width | 10 qubits |
| Ancilla / scratch | 0 / 0 |
| Full computational domain | 1,024 basis states |

The two cached rows are:

1. `EXPOSURE_U`: coefficients `[0, 1, 2, 3]`, inclusive band `[1, 4]`,
   unsigned width 3;
2. `EXPOSURE_S`: coefficients `[-1, 0, 1, 2]`, inclusive band `[0, 2]`,
   two's-complement width 3.

There are six exact-K portfolios. Four are feasible and form a connected
four-node exchange graph; two are rejected by the registered bands. The
initial-state contract permits support only on exact-K feasible portfolios
whose cache registers equal a full integer recomputation.

## Exact incremental identity

For a swap of variables `i` and `j`, each exposure cache follows

```text
A_r(S_ij x) = A_r(x) + (x_j - x_i)(c_ri - c_rj).
```

V3.7 evaluates this identity on all `6 × 6 = 36` portfolio-edge cases and both
constraint rows, giving 72 exact integer comparisons. For each case it also
compares the prospective feasibility predicate with an independent full
recomputation and checks that the exchange preserves exact K.

These arithmetic checks decide which endpoints may be paired. They are not
used as a substitute for the unitary proof.

## Coherent state augmentation

A valid embedded basis state is

```text
|x, A_U(x), A_S(x)>.
```

For a feasible exchange, the compiled block couples the complete source and
target addresses:

```text
|x, A(x)>  <->  |S_ij x, A(S_ij x)>.
```

At angle `β`, the intended two-level action is

```text
|a> -> cos(β)|a> - i sin(β)|b>
|b> -> -i sin(β)|a> + cos(β)|b>.
```

The portfolio and cache therefore move on the same coherent branch. No
orientation flag is measured, discarded or left entangled with the result.
Every inconsistent-cache address and every address outside an explicitly
compiled endpoint pair is assigned identity action.

The six candidate variable edges produce four coherent endpoint pairs. The
other candidate swaps are deliberately inactive because one or both endpoints
violate the registered support contract.

## Deterministic Gray-path compiler

For endpoint bit strings `a` and `b`, the compiler constructs a deterministic
Gray path

```text
g_0=a, g_1, ..., g_d=b
```

where adjacent addresses differ in exactly one bit. Each adjacent
transposition is a `PATTERN_MCX`: the target is the differing bit and every
other bit is a declared positive or negative control. A central
`PATTERN_MCRX(2β)` acts on the final adjacent pair. The preceding MCX sequence
is then reversed exactly.

Writing the Gray-path permutation as `P`, the complete block is

```text
U_ab(β) = P† · MCRX(2β) · P.
```

Conjugation moves the addressed rotation to the required endpoints and returns
every intermediate address. Because each pattern gate specifies all nine
non-target bits, its addressed action is unambiguous on the full ten-qubit
domain.

## Cleanup and unitarity proof

The prototype allocates no ancilla and no scratch register. Cleanup is
nevertheless tested rather than inferred:

- the compiled action is compared with an independently constructed ideal
  two-level action for every basis column;
- the compiled adjoint is applied and must restore every input column;
- every off-target column must remain identity;
- every output column must retain unit norm;
- the complete ordered six-edge layer is compared with an independent
  reference composition; and
- the complete 1,024 by 1,024 Gram matrix must equal identity within the frozen
  `1e-12` numeric tolerance.

The canonical beta set is `0`, `0.2718281828459045` and
`0.7853981633974483`. Across the edge-level audit this produces 18,432 checked
columns. The complete-layer audit adds 3,072 checked columns and 3,145,728 Gram
entries. The four endpoint pairs are also replayed under every beta, for 12
explicit pair-angle checks.

The proof is numerical for the declared floating trigonometric evaluation and
exhaustive for the complete registered discrete domain. It is not a symbolic
proof for arbitrary precision or arbitrary widths.

## Honest logical resource ledger

The canonical complete edge scan contains:

| Resource | Exact V3.7 logical-IR value |
|---|---:|
| Candidate edges | 6 |
| Coherent two-level pairs | 4 |
| `PATTERN_MCX` | 36 |
| `PATTERN_MCRX` | 4 |
| Total logical operations | 40 |
| Conservative serialized logical depth | 40 |
| Maximum controls per primitive | 9 |
| Ancilla qubits | 0 |
| Scratch qubits | 0 |

The full-width pattern-controlled operations are logical primitives, not a
native or elementary basis. V3.7 deliberately reports:

```text
ELEMENTARY BASIS DECOMPOSITION · NOT IMPLEMENTED
SELECTED-MODEL CNOT · NOT ESTIMATED
N40 PROJECTION · NOT RUN
2.5M BUDGET GATE · NOT EVALUATED
```

No V3.4 resource reduction is booked from the small-instance logical count.

## Semantic admission decision

The release carries two independent gates.

### Passed

- exact registered fixture and register encoding;
- exact-K preservation;
- integer incremental cache identity;
- prospective predicate equivalence;
- coherent two-level portfolio/cache action;
- reverse Gray-path cleanup with zero allocated scratch;
- full-domain action, adjoint, norm and Gram checks;
- complete-layer reference equivalence;
- deterministic IR replay; and
- exact logical-primitive ledger.

### Still blocked

- authenticated seven-constraint N=40 register contract;
- scalable reversible arithmetic and cache-update schedule;
- exhaustive/differential equivalence on all eight frozen N=40 seeds;
- elementary one- and two-qubit decomposition;
- comparable selected-model CNOT and depth ledger;
- the `≤2,500,000` admission screen on every seed;
- production feasible-graph and ordered-layer evidence;
- named-backend target, routing, calibration and error budget; and
- any QPU execution or optimization comparison.

The next falsifiable gate is
`ELEMENTARY_BASIS_DECOMPOSITION_AND_N40_RESOURCE_LEDGER`.

## Claim boundary

V3.7 is provider-free. The scientific path imports no provider SDK, reads no
credential, makes no provider call, performs no backend transpilation and
submits zero QPU jobs. `hardware_executable` and `qpu_submission_enabled`
remain false. Optimization performance is not tested; global impossibility and
quantum advantage are not claimed.

The positive word `PASSED` applies only to the registered N=4, K=2 compiler
fixture. It must never be rendered as N=40 admission, backend readiness,
hardware fidelity or portfolio-performance evidence.

## Institutional surface

The V3.7 panel is inserted after the immutable V3.6 diagnosis and before all
legacy/future provider controls. It exposes:

- the authenticated prototype seal and fixture identity;
- a fail-closed proof matrix;
- exhaustive differential and coherent-transition ledgers;
- register widths and logical resources;
- complete-layer action/round-trip/Gram residuals;
- a side-by-side prototype-to-production gap; and
- disabled N=40, backend and hardware actions.

No top-level or nested tab is added. The historical Streamlit contract remains
12 tabs: eight principal tabs plus the four nested QMC views.

## Additive package-closure repair

An extraction audit found that the earlier V3.6 institutional ZIP omitted
legacy runtime/support files required by its own imported verifier chain,
including `phase3_circuit_validation.py` and `FREEZE_CONTRACT_V3_4.json`.
V3.7 does not rewrite the V3.6 archive or retroactively alter its freeze. It
captures the 27 missing files as a new
`V3.7_LEGACY_SUPPORT_SNAPSHOT`, records their raw hashes, and ships a cleanly
extractable institutional package.

The V3.7 freeze therefore contains 99 exact paths:

- the 57-path V3.6 frozen inventory, with only the authorized README/UI pair
  advanced to V3.7;
- the immutable V3.6 freeze itself;
- 27 newly captured legacy support paths; and
- 14 new V3.7 paths.

This is an additive closure repair, not a claim that the omitted files were
retroactively part of the V3.6 freeze.

## Release transaction

Deployment remains fail-closed:

```text
LOCK
  -> AUTHENTICATE EXACT V3.6
  -> VALIDATE SUPPORT CLOSURE
  -> STAGE + REHASH
  -> RECHECK SOURCE
  -> BACK UP HASHED PREIMAGES
  -> ATOMIC REPLACE (README PENULTIMATE, UI LAST)
  -> UNIT + SCIENCE + RELEASE + FREEZE + APPTEST
  -> VERIFIED ROLLBACK ON ANY FAILURE
```

Only exact V3.6 and exact V3.7 successor pairs are accepted. Mixed README/UI,
third successors, duplicate JSON keys, non-finite constants, traversal,
symlinks, non-regular files, incomplete inventories and concurrent locks are
rejected. Exact V3.7 reapplication is a no-op.

## Reproduction

From the release root:

```bash
python -m unittest quantum_research_lab.test_phase3_v37 -v
python -m quantum_research_lab.phase3_v37_validation
python -m quantum_research_lab.verify_phase3_v37 .
python -m quantum_research_lab.verify_freeze_contract_v37 \
  . --contract FREEZE_CONTRACT_V3_7.json
python -m quantum_research_lab.verify_phase3_v37_ui \
  app_v37_offline_harness.py --timeout 180
```

Passing these commands proves deterministic implementation, release integrity
and UI wiring for the declared V3.7 scope. It does not prove user acceptance,
hardware behavior, optimization quality or quantum advantage.
