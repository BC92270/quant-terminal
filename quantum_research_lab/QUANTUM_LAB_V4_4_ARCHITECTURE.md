# Quantum Lab V4.4 · Named Offline Backend, Zero-Job Routing Gate

## Institutional decision

V4.4 executes the exact next gate registered by the authenticated V4.3
release: bind the provider-neutral circuit manifests to one explicit backend
target and test transpilation/routing without submitting a job.

The result is scientifically useful and deliberately negative:

- named structural target: **FakeMarrakesh**, pinned offline;
- target capacity: **156 physical qubits**;
- frozen V4.3 logical widths: **327–339 qubits**;
- full-workload capacity decisions: **8 / 8 rejected**;
- worst capacity deficit: **−183 qubits**;
- persistent register floor: **160 qubits**, already **4 over capacity** before
  arithmetic scratch or control flags;
- full-workload circuit reconstruction, transpilation, routing, scheduling,
  routed depth and native-gate counts: **not run after the mandatory capacity
  rejection**;
- five bounded Qiskit canaries: **pass twice with identical canonical hashes**;
- mandatory 157-qubit canary: **rejected by the transpiler**;
- provider calls, credential reads, network calls and QPU jobs: **0**; and
- hardware execution, calibration-conditioned fidelity, optimization
  performance and quantum advantage: **false / not tested / not tested / not
  claimed**.

The exact overall decision is
`V44_FAKE_MARRAKESH_CAPACITY_REJECTED_CANARY_PIPELINE_VALIDATED_ZERO_JOB`.
Production admission is
`REJECTED_RESEARCH_ARCHITECTURE_REQUIRES_PROOF_CARRYING_WIDTH_REDUCTION`.

This is not a failed software run. It is a successful falsification of the
current width architecture against one preregistered 156-qubit compilation
target.

## Exact predecessor and chronology

V4.4 authenticates the raw and semantic identities of the V4.3 freeze and
sealed artifact. It re-hashes exactly the **191** V4.3 paths immutable to a
successor; only `quantum_research_lab/README.md` and
`quantum_research_lab/ui.py` are successor-mutable.

The V4.4 protocol was sealed as `NOT_EVALUATED` before the confirmatory runner
produced its capacity and canary results. The target width, coupling graph,
basis, pass-manager settings, seed, canary set, success criteria and negative
control were frozen inputs. V4.4 does not regenerate, weaken or rewrite V4.3.

## What “FakeMarrakesh” means here

The target is a structural projection of files bundled in
`qiskit-ibm-runtime==0.49.0`, authenticated by raw SHA-256:

- `conf_marrakesh.json`:
  `5a9a7c14a0187a9ec8109e4e396f96f73cbb1e0c263a6d9d5912a9691ee24e5d`;
- `props_marrakesh.json`:
  `d49d7ae07deb95947ea10e5b9b9c5cbab6df21f98610543817f35ade2b1aece6`;
- `fake_marrakesh.py`:
  `cd8b9099bc275248c4b8e6166ffe8856a5eab65b49b22d4bd1ad8eb34d141c29`;
  and
- runtime source wheel:
  `b29b4a0a5e013b6e6fd6556158fd34a05e2930dea870c60edef738b834977f2b`.

The projection retains only structural compilation fields:

```text
target qubits              156
basis                      CZ · ID · RZ · SX · X
directed coupling edges    352
undirected couplers        176
maximum graph degree       3
processor metadata         Heron revision 2
target dt                  4 ns
```

The bundled properties file is pinned for provenance but is not used for the
capacity decision or the canary compilation. Its timestamp is historical
metadata, not proof of current calibration. The release never instantiates a
provider service and never claims that a real backend with this name is
available, accessible or currently configured this way.

IBM documents fake backends as simulated system snapshots useful for testing
transpilation and noisy simulation. V4.4 uses only the former structural role.
It does not run a noisy simulator.

## Capacity gate before expensive work

The acceptance protocol gives capacity precheck strict precedence over circuit
reconstruction and full transpilation. For each seed:

```text
capacity deficit = backend capacity − V4.3 logical allocation
```

| Seed | V4.3 logical qubits | Target | Deficit | Full transpilation | Full routing |
|---:|---:|---:|---:|---|---|
| 1103 | 330 | 156 | −174 | NOT_RUN_CAPACITY_PRECHECK_REJECTED | NOT_RUN_CAPACITY_PRECHECK_REJECTED |
| 2207 | 331 | 156 | −175 | NOT_RUN_CAPACITY_PRECHECK_REJECTED | NOT_RUN_CAPACITY_PRECHECK_REJECTED |
| 3301 | 327 | 156 | −171 | NOT_RUN_CAPACITY_PRECHECK_REJECTED | NOT_RUN_CAPACITY_PRECHECK_REJECTED |
| 4409 | 328 | 156 | −172 | NOT_RUN_CAPACITY_PRECHECK_REJECTED | NOT_RUN_CAPACITY_PRECHECK_REJECTED |
| 5501 | 329 | 156 | −173 | NOT_RUN_CAPACITY_PRECHECK_REJECTED | NOT_RUN_CAPACITY_PRECHECK_REJECTED |
| 6607 | 331 | 156 | −175 | NOT_RUN_CAPACITY_PRECHECK_REJECTED | NOT_RUN_CAPACITY_PRECHECK_REJECTED |
| 7703 | 339 | 156 | −183 | NOT_RUN_CAPACITY_PRECHECK_REJECTED | NOT_RUN_CAPACITY_PRECHECK_REJECTED |
| 8807 | 334 | 156 | −178 | NOT_RUN_CAPACITY_PRECHECK_REJECTED | NOT_RUN_CAPACITY_PRECHECK_REJECTED |

The negative decision does not depend on V4.3 scratch estimates alone. Four
persistent 40-qubit registers are simultaneously part of the current circuit
contract:

```text
DATA[40] + REMOVE_COIN[40] + ADD_COIN[40] + TARGET[40] = 160 qubits
```

That floor exceeds the target before `SUM_*`, `CONSTANT`, `CARRY`, addressed
flags, row flags or control flags are allocated. A topology-only pass cannot
repair this. The architecture must change while preserving the V4.3 operation
on its exact promise subspace.

Rejected full-workload metrics are represented by the literal value
`NOT_RUN_CAPACITY_PRECHECK_REJECTED`. They are never rendered as zero. A zero
depth or zero native-gate count would be misleading because no such full
compilation exists.

## Pinned zero-job canary toolchain

The confirmatory runner uses Qiskit core **2.5.2** with:

```text
optimization_level = 0
layout_method       = trivial
routing_method      = basic
translation_method  = translator
seed_transpiler     = 4404
scheduling_method   = NOT_RUN
```

The target is constructed locally from the frozen width, basis, coupling graph
and `dt`. No `qiskit_ibm_runtime` module is imported by the runner. Network
connection attempts are actively denied during compilation.

The bounded suite contains:

1. a three-qubit non-native ISA translation;
2. a five-qubit reversible `CCX`/multi-control-X arithmetic motif;
3. one literal 40-qubit V4.3 `XX+YY` coin ring;
4. both 40-qubit coin rings without data, target or scratch registers;
5. an exact 156-qubit capacity-boundary circuit; and
6. a mandatory 157-qubit over-capacity rejection.

Every accepted output is canonicalized as an ordered stream of target
operation, physical qubits and 17-digit numeric parameters. The evidence also
binds output operation counts, depth, size, global phase, used physical
qubits, ISA membership and every two-qubit coupling edge. Two clean processes
produce the same bundle SHA-256:

```text
b744a2bd1364d531c65d89e24dd7f78ef8170e12cbf13affd3e28a0a1191a0f0
```

The ordered canary-result root is:

```text
3348aedbe468e14e979dd50f943dd004c0640c1271d446d7ef8c8378c0ac8cc6
```

Canary success proves that the pinned local translation/routing mechanics
operate for those small circuits. It cannot be extrapolated to the rejected
327–339-qubit workloads, to hardware fidelity, or to optimization quality.

## Security and governance boundary

The confirmatory source contains no provider-service import. Sensitive
provider environment variables are removed from child-process environments,
and socket connections are blocked during each canary run. The release records:

```text
provider SDK imported       false
provider credentials read   false
credential reads            0
provider calls              0
network calls               0
backend run calls           0
local simulator jobs        0
QPU jobs                    0
QPU submission enabled      false
hardware executable         false
```

The UI is evidence-only. Rebuild, target mutation, capacity override,
full-workload transpilation, provider access, calibration extrapolation, QPU
submission, performance claims and advantage claims are all disabled controls.

## Integrity versus scientific proof

Canonical SHA-256 hashes provide deterministic integrity and lineage. They are
not external signatures. The artifact is independently checked for:

- specification, snapshot, toolchain, source and parent cross-links;
- capacity-row and aggregate self-hashes;
- independent recomputation from the authenticated V4.3 artifact;
- canary-row, bundle and double-replay hashes;
- target ISA and coupling compliance;
- literal not-run full-workload metrics;
- zero-provider/zero-job boundaries; and
- exact decision and next-gate strings.

The institutional archive and transactional installer add packaging and
deployment assurance. Neither turns the offline snapshot into live hardware
evidence.

## Next falsifiable gate

The next gate is:

`PROOF_CARRYING_WIDTH_REDUCTION_TO_156_QUBITS_OR_LOWER_WITH_EXACT_PROMISE_PARITY`

A successor must exhibit an explicit register/liveness plan at or below 156
qubits and prove exact parity with the V4.3 promise-subspace operation. It must
retain the V4.3 off-promise negative witness and preregister new resource and
routing bounds. Plausible research directions include in-place target updates,
sequential or recomputed coin addressing, pebbling/recomputation of arithmetic
scratch, and constraint streaming. None is accepted until it supplies the
required reversible equivalence and cleanup evidence.

V4.4 remains `RESEARCH_ONLY`. It does not authorize provider discovery,
credential access, hardware execution, economic deployment or a quantum
advantage claim.
