# Quantum Lab V4.3 · Backend-Agnostic Reversible Circuit Materialization

## Institutional decision

V4.3 is the append-only successor to the authenticated V4.2 release. It
executes the exact next gate registered by V4.2: materialize one complete
provider-neutral elementary circuit stream for every frozen `N=40, K=10,
BANDS` seed and test its finite reversible controls independently.

The accepted result is deliberately narrow:

- full deterministic elementary streams: **8 / 8 frozen seeds**;
- elementary instructions across the eight streams: **21,925,902**;
- worst materialized count: **1,158,046 CX**;
- immutable budget: **2,500,000 CX**;
- minimum budget margin: **+1,341,954 CX**;
- maximum logical allocation with registered workspace reuse: **339 qubits**;
- independent V4.3 validation: **31 / 31 checks**;
- provider-neutral research circuit IR: **ADMITTED**; and
- backend transpilation / QPU jobs / hardware execution: **NOT RUN / 0 /
  FALSE**.

The exact overall decision is
`V43_BACKEND_AGNOSTIC_CIRCUIT_MATERIALIZED_PROMISE_SIMULATION_PASSED`.
Production admission remains
`PROVIDER_NEUTRAL_RESEARCH_CIRCUIT_IR_ADMITTED_BACKEND_AND_HARDWARE_NOT_AUTHORIZED`.
This is neither a named-backend result nor evidence of performance, economic
utility or quantum advantage.

## Exact predecessor and chronology

The V4.3 compiler authenticates the V4.2 artifact, V4.2 specification and
V4.2 freeze contract by registered raw and semantic SHA-256 identities. It
also authenticates exactly the 175 V4.2 paths that are immutable to a
successor. Only the human-readable `quantum_research_lab/README.md` and the
integration surface `quantum_research_lab/ui.py` remain successor-mutable.

The V4.3 protocol was sealed with result state `NOT_EVALUATED`. Its disclosed
exploratory inputs were the accepted V4.2 resource ledger, algebraic checks of
the selected Cuccaro templates and the V4.2 off-promise cleanup
counterexample. Angles, decompositions, width policy, budget, witnesses and
decision branches are therefore part of the frozen confirmatory contract.
Changing one requires a newly disclosed specification version.

V4.3 does not regenerate or rewrite V4.2. In particular, the accepted V4.2
CNOT-screen decision and all frozen predecessor bytes remain unchanged.

## Provider-neutral circuit IR

Each seed materializes one complete V4.2 generator step into the frozen
elementary basis:

```text
X · H · T · TDG · RY · RZ · CX
```

Every parameterized rotation is represented as an exact signed reduced
rational multiple of π. The frozen angles are:

- coin `XX+YY`: `theta = π/2`, `beta = 0`;
- certified two-level bridge: `theta = π/2`.

The canonical instruction record binds the instruction index, stage, opcode,
ordered qubit identifiers and exact angle. A `SHA-256` digest is computed over
the ordered instruction bytes. The artifact records per-stage manifests,
ordered chunks of at most `8,192` instructions, their sizes and hashes, the
complete stream hash, gate counts and register allocation. It intentionally
does not store eight multi-million-line circuit side files.

The roots binding all eight results are:

```text
ordered stream-manifest root  9405dc3659aa7a86fad4437f3a29bd654d87bae0a221e4d169b4f1f5af43bbeb
register-map root             315e7a7d8742ab5a4456e0ea26be8c94b098050d60bc1ad9dd874900c4b0218e
```

These are deterministic research-manifest commitments. They are not external
signatures, provider circuit identifiers or evidence that a backend accepts
the circuit.

## Materialized complete step

The stream retains the V4.2 operation order:

1. a 40-edge excitation-preserving `XX+YY` ring on `REMOVE_COIN`;
2. the same ring on `ADD_COIN`;
3. addressed reads and construction of the proposed target portfolio;
4. an exact seven-row target-feasibility toggle;
5. the accepted addressed exchange on the promise subspace;
6. reverse target reconstruction and predicate cleanup; and
7. the authenticated V4.1 data bridges, in their frozen order.

The selected exact decompositions are:

- CCX: a six-CX, nine-one-qubit Clifford+T template;
- MCX with `c >= 3` controls: a clean `2c-3` CCX ladder;
- controlled constant addition: an outer-controlled Cuccaro modulo adder with
  constant load/unload and a clean carry;
- comparator: high-bit carry compute/copy/uncompute, with exact `GE` and `LE`
  wrappers;
- interval: XOR of the nested predicates `GE(lower)` and `GE(upper+1)`;
- coin edge: a two-CX `XX+YY` template expanded into the frozen basis; and
- data bridge: a Gray-path two-level `RY` construction with clean ladder
  uncomputation.

The stream is a materialized logical circuit, not a backend-native circuit.
No macro cancellation is credited across the frozen operation boundaries.

## Register map and liveness

Every seed receives a deterministic, explicit register map in this order:

```text
DATA[40]
REMOVE_COIN[40]
ADD_COIN[40]
TARGET[40]
SUM_0 ... SUM_6[materialized guarded widths]
CONSTANT[max guarded width]
CARRY[1]
ADDRESSED[2]
ROW_FLAGS[7]
CONTROL_FLAGS[5]
```

`TARGET[0:37]` is reused for the bridge ladder only after SELECT and both
feasibility-oracle passes are clean. `CONSTANT[0:5]` is reused for the
seven-control AND only after comparator constants are clean. The clean-exit
contract covers `TARGET`, every sum bank, constant scratch, carry, addressed
flags, row flags and control flags. The largest observed allocation is 339
logical qubits; it is a static logical-liveness result, not capacity approval
for any device.

## Append-only corrections to the V4.2 model

V4.3 exposes three corrections required by literal elementary
materialization. None changes V4.2 bytes or rewrites its accepted screen.

First, V4.2 listed an elementary basis that omitted `H`, although its inherited
exact six-CX CCX decomposition uses `H`. V4.3 explicitly includes `H`. This is
an append-only nomenclature correction; the V4.2 CNOT decision remains the
historical result it was.

Second, the selected Cuccaro materialization requires arithmetic width at
least five. The four group banks costed at width three by V4.2 are exactly
zero-extended to width five. The interval predicate is preserved, the logical
allocation increases by eight qubits, and the complete-step ledger gains
`22,784 CX` for every seed.

Third, V4.2 conservatively costed two extra CCX operations per row to combine
lower and upper comparisons. Because `GE(upper+1)` is nested inside
`GE(lower)`, the exact interval bit is their XOR. The materialized circuit
therefore needs no combining CCX pair and removes `168 CX` per complete step.

The reconciled delta is exact:

```text
width lift                         +22,784 CX
exact nested-GE XOR correction        -168 CX
net V4.3 delta versus V4.2         +22,616 CX
```

Consequently, the V4.2 worst case `1,135,430` becomes the V4.3 materialized
worst case `1,158,046`, leaving `1,341,954` CX below the unchanged budget.

## Eight-seed evidence ledger

| Seed | Elementary instructions | CX | Budget margin | Logical qubits | Bridges |
|---:|---:|---:|---:|---:|---:|
| 1103 | 2,737,326 | 1,106,814 | +1,393,186 | 330 | 0 |
| 2207 | 2,746,616 | 1,110,414 | +1,389,586 | 331 | 1 |
| 3301 | 2,682,810 | 1,084,798 | +1,415,202 | 327 | 0 |
| 4409 | 2,682,822 | 1,084,798 | +1,415,202 | 328 | 0 |
| 5501 | 2,682,878 | 1,084,798 | +1,415,202 | 329 | 0 |
| 6607 | 2,737,190 | 1,106,814 | +1,393,186 | 331 | 0 |
| 7703 | 2,864,786 | 1,158,046 | +1,341,954 | 339 | 2 |
| 8807 | 2,791,474 | 1,128,830 | +1,371,170 | 334 | 0 |

All eight preregistered CNOT replays, qubit replays, stream manifests and
real-`N=40` promise witnesses pass.

## Independent validation

The Python validation layer authenticates the specification, source,
simulator, parent and sealed artifact, then checks all stream and register
roots without trusting their aggregate labels. It also evaluates matrix-level
unitary equivalence of the CCX, coin and bridge templates up to the registered
global-phase convention.

The separately implemented, dependency-free C++17 simulator performs:

- `107,520` exhaustive arithmetic cases;
- `64` promise-subspace SELECT cases;
- `64` SELECT roundtrips;
- `12` gate-count contracts; and
- the mandatory off-promise negative control.

The eight authenticated real-`N=40` witnesses start with feasible data and
one-hot remove/add coins. They accept a feasible one-swap move and return all
registered selector work to zero. This verifies the registered promise cases;
it is not a full-state quantum simulation of a 339-qubit circuit.

## Mandatory off-promise rejection

V4.3 does not generalize cleanup beyond the registered feasible-start promise.
The frozen counterexample is:

```text
N=2, K=1
feasible set  {01}
start         10  (infeasible)
remove bit    1
add bit       0
target        01  (feasible)
```

The forward selector accepts the move, but the reverse target is the original
infeasible state. The retained feasibility flag therefore remains `1` instead
of clearing. Both implementations must report
`OFF_PROMISE_CLEANUP_REJECTED_WITH_WITNESS`; accepting global cleanup would
fail the protocol.

## Claim boundary and next gate

V4.3 establishes only a deterministic provider-neutral logical circuit IR,
its exact selected-template ledger and finite controls inside the registered
promise. It does not establish:

- full-binary or arbitrary off-promise cleanup;
- state-vector or tensor-network simulation of the complete 339-qubit state;
- native-gate counts, routed depth, topology feasibility or scheduler output;
- calibration-aware fidelity, noise, error mitigation or runtime;
- optimization performance, portfolio quality or economic utility;
- provider access, QPU execution or hardware readiness; or
- quantum advantage.

The sealed boundary is `RESEARCH_ONLY`: provider SDK imports and credential
reads are false, provider calls and submitted QPU jobs are zero, named backend
selection is false, backend transpilation is `NOT_RUN`,
`hardware_executable=false`, optimization performance is `NOT_TESTED`, and
quantum advantage is `NOT_CLAIMED`.

The next falsifiable gate is
`NAMED_BACKEND_ZERO_JOB_TRANSPILATION_AND_ROUTING_PROTOCOL`. It must remain a
zero-job protocol unless a later, separately authorized release changes that
boundary.

