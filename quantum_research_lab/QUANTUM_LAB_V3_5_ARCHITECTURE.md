# Quantum Lab V3.5 — Zero-Job Named-Backend Admission

## Release position

V3.5 is an additive, `RESEARCH_ONLY` successor to the frozen V3.4 optimized
oracle and elementary guarded mixer. Its purpose is not to make the V3.4
circuit look executable. Its purpose is to make the first backend decision
falsifiable, reproducible and cheap enough to occur before credentials,
provider access, transpilation work or QPU time are consumed.

The implemented V3.5 system is therefore a **zero-job negative-result
machine**. It authenticates the frozen V3.4 parent, applies a documented IBM
per-circuit two-qubit-gate model screen, and can audit an independently exported
backend snapshot and candidate manifest against preregistered gates. It does
not discover a backend, import provider credentials, call a provider API,
transpile a circuit, execute a pulse schedule or submit a job.

The current result is negative and useful:

- the frozen V3.4 selected two-qubit accounting count fails the IBM
  pre-transpilation screen by almost four and a half orders of magnitude;
- no authenticated backend snapshot or routed candidate is needed to reach
  that result;
- the deeper backend-native gates remain implemented but `NOT_RUN` or
  `BLOCKED`, rather than being filled with synthetic evidence; and
- hardware execution remains `BLOCKED · ZERO JOBS`, with quantum advantage
  `NOT_CLAIMED`.

## Decisive provider screen

The V3.5 specification freezes the following comparison:

| Quantity | Frozen value | Evidence meaning |
|---|---:|---|
| V3.4 selected 2Q count | `149,405,532,710` | Provider-neutral selected 7T-CCX cost-model result |
| IBM maximum | `5,000,000` two-qubit gates per circuit | Documented provider circuit limit |
| Count / limit | `29,881.106542x` | Deterministic admission ratio, not a runtime or fidelity estimate |
| Admission result | `REJECTED_MODEL_SCREEN` | `PRETRANSPILATION_MODEL_SCREEN`; retain as a negative result |

The provider source is IBM Quantum's [Job limits](https://quantum.cloud.ibm.com/docs/en/guides/job-limits)
page. It was checked on **2026-09-05**. The page documents a maximum of five
million two-qubit gates per circuit but reports no publication date on the
page; V3.5 therefore records
`source_document_publication_utc = NOT_REPORTED_ON_PAGE` and never substitutes
the retrieval date for a publication date.

The numerator must be interpreted narrowly. `149,405,532,710` is the frozen
V3.4 subtotal obtained after expanding the provider-neutral CCX model into a
selected CNOT accounting convention. It is **not** the output of an IBM
backend `Target`, an ISA circuit, a coupling-map routing pass, a calibration-
aware transpiler or a pulse compiler, and it is not asserted to be a lower
bound on such an output. V3.5 uses it as an early, like-labelled model screen.
The rejection does not establish physical
runtime, success probability or hardware fidelity.

## Evidence taxonomy

V3.5 treats the following concepts as independent evidence axes.

### Named backend is not hardware evidence

A backend name is an identifier. It does not prove that the backend exists at
evaluation time, is a physical QPU, is operational, has enough qubits, exposes
the recorded instruction set, or was used. Offline identity admission also
requires provider ID, backend version, explicit `is_simulator = false`,
operational state, qubit capacity, basis inventory, coupling map and provenance.
Even a passing identity gate remains an offline documentary result, not a
hardware result. IBM's [QPU information](https://quantum.cloud.ibm.com/docs/en/guides/qpu-information)
guide is the primary reference for backend configuration, properties and
status information.

### Snapshot is not live state

A snapshot is an exported record captured at a stated time. It is accepted
only if its canonical payload digest matches both its embedded digest and a
SHA-256 value pinned out of band by the caller. An embedded digest alone is
self-asserted and insufficient. V3.5 does not silently upgrade
`PROVIDER_EXPORT` or `AUDITED_ARCHIVE` evidence into `LIVE` evidence.

Three timestamps remain separate:

1. `calibration.captured_at_utc` — when the calibration values were observed;
2. `provenance.exported_at_utc` — when the evidence record was exported; and
3. `evaluated_at_utc` — when V3.5 evaluated the frozen inputs.

Freshness is computed from the calibration capture time, never from export or
evaluation time. A timestamp more than 300 seconds in the future is invalid;
a calibration age over 24 hours is rejected. IBM documents the distinct role
and lifecycle of calibration work in [Calibration jobs](https://quantum.cloud.ibm.com/docs/en/guides/calibration-jobs).

### Target-native, ISA-valid and pulse-native are not synonyms

- **Target-transpiled** means a recorded transpiler run declares the named
  backend, SDK/transpiler versions, optimization level, routing seed, target
  basis and used coupling edges, and the emitted candidate is consistent with
  the frozen snapshot. Qiskit's [transpiler API](https://quantum.cloud.ibm.com/docs/en/api/qiskit/2.2/transpiler)
  and [TranspileLayout](https://quantum.cloud.ibm.com/docs/en/api/qiskit/2.2/qiskit.transpiler.TranspileLayout)
  document the compilation and layout concepts used by this boundary.
- **ISA-valid** means the submitted circuit conforms to the backend's supported
  instructions and topology for the relevant target. A provider-neutral gate
  list, or even a circuit containing familiar IBM gate names, does not prove
  ISA validity. IBM's [fractional-gates guide](https://quantum.cloud.ibm.com/docs/en/guides/fractional-gates)
  further shows why instruction availability and execution mode must be
  recorded rather than inferred.
- **Pulse-native** would require an explicit pulse-level representation and
  applicable calibration evidence. V3.5 has no pulse schedule and makes no
  pulse-native claim. Passing a target-basis check would still not establish
  pulse implementation, pulse calibration quality or hardware execution.

Continuous-rotation treatment is another independent boundary. V3.4 contains
1,560 continuous `RY` rotations. V3.5 separates a `NISQ_TARGET_ISA` lane, where
`approximation_degree = 1.0` and no fault-tolerant T-count is inferred, from a
`FAULT_TOLERANT_CLIFFORD_T` lane that is not IBM-QPU-native. For the latter,
the preregistered spectral-norm budget is `1e-3` in aggregate and at most
`1e-3 / 1560 = 6.41025641025641e-7` per occurrence; the achieved errors must be
measured rather than inferred from a requested epsilon. Qiskit's
[synthesis API](https://quantum.cloud.ibm.com/docs/en/api/qiskit/synthesis) and
[SynthesizeRZRotations pass](https://quantum.cloud.ibm.com/docs/en/api/qiskit/2.4/qiskit.transpiler.passes.SynthesizeRZRotations)
are relevant implementation references; the Ross-Selinger
[ancilla-free rotation synthesis paper](https://arxiv.org/abs/1403.2975) is a
primary algorithmic reference. None of these references is evidence that
synthesis was run in V3.5.

## Live environment boundary

The live Codespace inventory observed on 2026-09-05 is:

| Component | Observed state |
|---|---|
| Python | `3.12.1` |
| `qiskit` | absent |
| `qiskit_ibm_runtime` | absent |
| `qiskit_aer` | absent |
| `rustworkx` | absent |

Consequently, local backend-native transpilation reproduction is
`NOT_RUN · QISKIT ABSENT`. This is not treated as a failed import to hide and
not treated as permission to install a different, unpinned toolchain. Before a
future reproduction, the environment must freeze package versions against the
official [Qiskit release notes](https://quantum.cloud.ibm.com/docs/en/api/qiskit/release-notes/2.5)
and [Qiskit IBM Runtime release notes](https://quantum.cloud.ibm.com/docs/en/api/qiskit-ibm-runtime/release-notes),
then bind serialized inputs and outputs to hashes. Qiskit's
[QPY documentation](https://quantum.cloud.ibm.com/docs/en/api/qiskit/qpy) is
the relevant primary reference for version-aware circuit serialization; QPY
serialization alone does not authenticate provenance or prove reproducibility.

## Implemented offline admission architecture

`phase3_backend_admission.py` is a dependency-light auditor. It accepts two
objects produced elsewhere:

1. a backend/calibration snapshot whose payload hash is pinned independently;
2. a candidate manifest describing an already completed transpilation and
   rotation-synthesis result.

It then emits a self-hashed V3.5 artifact. The artifact records runtime
inventory and claim boundaries, and cannot authorize submission even when all
offline gates pass.

The preregistered gates are:

| Gate | Implemented decision rule |
|---|---|
| V3.4 parent binding | Verify raw and semantic V3.4 artifact/freeze identities, resource/validation/schedule manifests, passing parent validation and zero-job boundaries |
| Parent provider 2Q gate model screen | Reject the frozen selected-model representation before transpilation when `149,405,532,710 > 5,000,000`; retain ratio and source metadata |
| Snapshot authentication | Require canonical SHA-256 to match embedded, duplicate and independently supplied commitments |
| Backend identity and provenance | Require allowed provider/evidence class, named versioned non-simulator operational backend with `status_msg = active`, width, basis, coupling and source record |
| Calibration freshness | Require explicit calibration identity (nullable), snapshot/properties/per-metric timestamps, capture-to-export ≤900 s, age ≤24 h and future skew ≤300 s |
| Candidate parent binding | Bind candidate and transpiler input independently to the frozen V3.4 semantic hash |
| Transpilation metadata | Require backend match, SDK/transpiler versions, optimization level, routing seed, target basis and coupling-valid used edges |
| Logical and routed width | Require 118 logical qubits; reject a backend or routed result that cannot contain them |
| Connected capacity | Require one non-faulty coupling-map component containing at least 118 qubits |
| Routed depth | Require routed depth at or below `1,000,000` |
| Routed 2Q count | Require routed two-qubit count at or below `2,000,000`, stricter than the provider ceiling |
| Route calibration | Require 100% used-edge coverage, maximum 2Q error at or below 0.03 and nearest-rank p95 at or below 0.015 |
| Rotation evidence | Require a declared lane, all 1,560 rotations, maximum error ≤`6.41025641025641e-7` and aggregate error ≤`1e-3` |
| Noise-aware proxy | Require `routed_2q_count × log(1 - p95_error) >= log(0.99)`; governance screen only |
| Zero-job boundary | Credentials not read, provider session not opened, network calls zero, submission disabled, jobs zero, hardware executable false, advantage not claimed |

The noise calculation is explicitly a conservative independent-error screening
proxy. It is not a circuit-fidelity model, not an experiment and not evidence
of useful output quality.

Gate states have fixed meanings:

- `PASS` — the supplied offline field passes its preregistered screen;
- `REJECTED` — trustworthy evidence violates a preregistered budget;
- `BLOCKED` — evidence is absent, malformed, unauthenticated or internally
  inconsistent; and
- `NOT_RUN` — the measurement or transformation needed for the gate was not
  performed.

V3.5 retains each gate independently. The IBM pre-transpilation rejection is
therefore visible even when no snapshot/candidate was supplied. If and only if
the V3.4 parent is authenticated, that independent result controls the overall
state as `REJECTED_MODEL_SCREEN`, with downstream absence recorded separately
as `BLOCKED_OR_NOT_RUN`. An invalid V3.4 parent instead controls as
`INVALID_EVIDENCE_CHAIN`. Only a complete all-pass bundle with a passing model
screen could report `PASS · ZERO-JOB OFFLINE ADMISSION ONLY`.

## Why the confirmatory backend protocol is deferred

The V3.4 representation fails the external provider circuit limit before a
named-backend candidate is constructed. Running the full confirmatory protocol
now would not rescue that representation and could create misleading
precision around an already inadmissible circuit. V3.5 therefore does not:

- select a convenient backend after seeing routing outcomes;
- fabricate a fake-backend snapshot and label it hardware;
- install an unpinned SDK merely to obtain a transpiler count;
- refresh calibration after inspecting which edges the route uses;
- tune rotation tolerance, optimization level or routing seed post hoc;
- split one logical algorithm into multiple circuits without specifying the
  changed execution semantics and inter-circuit classical work; or
- submit a small demonstration circuit and generalize it to the frozen V3.4
  workload.

The full protocol is preserved as an unopened confirmatory stage. After an
algorithmic successor passes the provider-neutral screen, a new immutable
contract must freeze, before inspection of results:

1. exact algorithmic parent and circuit serialization hashes;
2. backend name, provider ID, backend version and hardware/simulator class;
3. snapshot source record, independent digest, capture/export timestamps and
   maximum accepted age;
4. SDK, runtime and transpiler versions;
5. target basis/ISA mode, coupling map and any fractional-gate configuration;
6. optimization level, layout/routing methods and a fixed seed set;
7. rotation-synthesis method, basis, tolerance and per-angle error evidence;
8. routed width, depth, two-qubit count and provider-limit budgets;
9. route-specific calibration coverage, maximum/p95 error and noise proxy;
10. untouched confirmatory candidates and negative-result retention; and
11. a separate human authorization gate for any credential access or QPU job.

Passing that protocol would establish only a reproducible offline admission.
It would not establish optimization performance, solution quality, sampling
advantage, runtime advantage, economic value or production readiness.

## Institutional claim ledger

| Claim | V3.5 decision | Evidence boundary |
|---|---|---|
| Frozen V3.4 parent integrity | Auditable / required | Exact raw, semantic and manifest identities |
| IBM 5M 2Q per-circuit screen | `REJECTED_MODEL_SCREEN` | IBM page retrieved 2026-09-05T09:50:26Z; page publication date not reported |
| Rejection multiple | `29,881.106542x` | Arithmetic on frozen selected-model numerator and documented limit |
| Named backend selected | `NOT_RUN` | No authenticated backend snapshot supplied |
| Live backend state | `NOT_RUN` | Offline-only architecture; zero provider calls |
| Qiskit transpilation | `NOT_RUN · QISKIT ABSENT` | Live environment inventory, not an inferred candidate result |
| Target/ISA validity | `NOT_RUN` | No transpiled circuit, target or routed manifest |
| Pulse-native execution | `NOT_RUN` | No pulse representation or execution evidence |
| Calibration/noise acceptance | `NOT_RUN` | No route-specific authenticated calibration bundle |
| Hardware execution | `BLOCKED · ZERO JOBS` | Submission code absent/disabled; credentials prohibited |
| Quantum advantage | `NOT_CLAIMED` | No accepted hardware, runtime or solution-quality evidence |

## V3.6 — algorithmic reduction roadmap

V3.6 must attack the numerator before it attacks the transpiler. A routing or
calibration campaign cannot be justified while the selected V3.4 accounting
model exceeds the provider limit by `29,881.106542x`, and installing Qiskit does
not change that frozen provider-neutral model result. This numerator is not a
backend-native count or a lower bound. The next research program is therefore
an algorithmic reduction ladder:

### 1. Freeze semantic choices

Define whether the successor preserves the exact V3.4 objective, exact-K
domain and seven hard constraints. Any relaxation, decomposition, surrogate or
hybrid method must receive a new problem statement and cannot inherit V3.4
equivalence labels.

### 2. Decompose cost by mechanism

Attribute logical qubits, depth, CCX/CX count and continuous rotations to
arithmetic, each constraint comparator, feasibility caching, edge guards,
mixer topology and full-layer repetition. Report exact formulae and measured
N-scaling on preregistered instances; avoid optimizing only a visually dominant
term.

### 3. Evaluate reduction families independently

Candidate families include reversible-arithmetic redesign, comparator sharing,
constraint-specific encodings, sparse or adaptive feasible-neighbor graphs,
block-coordinate/exchange decompositions, classical presolve, symmetry
reduction and rigorously specified hybrid decomposition. Each family must
preserve ancilla cleanup and predicate semantics or state the semantic change
explicitly.

### 4. Require differential equivalence and connectivity evidence

Every exact successor must reproduce the frozen predicate and mixer action on
the validation ladder. A cheaper topology must be tested for feasible-graph
connectivity; V3.3's isolated-witness ring rejection remains binding and cannot
be erased by lower gate counts.

### 5. Preregister a provider-neutral admission margin

Before backend inspection, freeze an acceptance budget below the five-million
ceiling, a seed/instance set and untouched confirmation cases. Count the same
gate class on both sides. The selected CCX-accounting total may remain a
screening proxy, but it must never be relabeled as a routed native count.

### 6. Open backend work only after reduction passes

Only a provider-neutral successor that clears the frozen screen proceeds to a
pinned Qiskit environment, authenticated named-backend snapshot, target/ISA
transpilation, routing, rotation synthesis and route-calibration gates. Failure
at any layer remains a publishable negative result.

### 7. Keep execution as a separate decision

Even a complete offline pass leaves provider authentication, QPU submission
and hardware execution disabled. A later execution protocol requires explicit
authorization, a job/shot budget, controls, stopping rules, append-only job
receipts and acceptance criteria defined before results are observed.

## Source register

The external technical references below were checked on 2026-09-05. They define
interfaces, provider limits and methods; they do not attest that V3.5 executed
those interfaces or methods.

- IBM Quantum, [Job limits](https://quantum.cloud.ibm.com/docs/en/guides/job-limits)
- IBM Quantum, [QPU information](https://quantum.cloud.ibm.com/docs/en/guides/qpu-information)
- IBM Quantum, [Calibration jobs](https://quantum.cloud.ibm.com/docs/en/guides/calibration-jobs)
- IBM Quantum, [Fractional gates](https://quantum.cloud.ibm.com/docs/en/guides/fractional-gates)
- Qiskit, [Transpiler API](https://quantum.cloud.ibm.com/docs/en/api/qiskit/2.2/transpiler)
- Qiskit, [TranspileLayout API](https://quantum.cloud.ibm.com/docs/en/api/qiskit/2.2/qiskit.transpiler.TranspileLayout)
- Qiskit, [Synthesis API](https://quantum.cloud.ibm.com/docs/en/api/qiskit/synthesis)
- Qiskit, [SynthesizeRZRotations](https://quantum.cloud.ibm.com/docs/en/api/qiskit/2.4/qiskit.transpiler.passes.SynthesizeRZRotations)
- Qiskit, [QPY serialization](https://quantum.cloud.ibm.com/docs/en/api/qiskit/qpy)
- Qiskit, [release notes 2.5](https://quantum.cloud.ibm.com/docs/en/api/qiskit/release-notes/2.5)
- Qiskit IBM Runtime, [release notes](https://quantum.cloud.ibm.com/docs/en/api/qiskit-ibm-runtime/release-notes)
- Ross and Selinger, [Optimal ancilla-free Clifford+T approximation of z-rotations](https://arxiv.org/abs/1403.2975)
