# Quantum Research & Computation Lab V2.7.1 · Phase II

V2.7.1 is a governance-only correction to V2.7. It does **not** reopen any frozen research engine.

## Correction
- Corrected the sealed Regime Evidence Snapshot ID from the malformed 9-character digest `QREG-20260821-8B1479CA5` to the deterministic V2.6.1 provenance ID `QREG-20260821-8B14479CA5`.
- Added strict validation requiring every sealed Evidence Snapshot digest to contain exactly 10 hexadecimal characters.
- Regenerated the Regime Protocol SHA and global Phase-II Manifest SHA.
- The preregistered QUBO hardness suite is explicitly marked eligible to attempt its sealed promotion gate because it is immediately executable; this does **not** mean the gate has passed.
- Global promotion-ready counts are forced to zero whenever the 4/4 source-snapshot lock is not satisfied.

## Frozen source laboratory
- Regime / Density: V2.2.1
- QMC / Risk: V2.3.2
- QUBO / Ising: V2.4.1
- Quantum Information / Tensor Networks: V2.5.1
- Evidence / Governance: V2.6.1

`engine.py`, `evidence.py`, `data.py`, `app.py` and `asset_class_router.py` remain byte-for-byte unchanged from V2.7. Frozen Mission Control / Regime / QMC / QUBO / Quantum Information / Benchmark UI functions remain source-identical.

## Corrected Phase-II seal
- Source snapshot matches: **4 / 4** under the frozen default specification.
- Regime source evidence: `QREG-20260821-8B14479CA5`
- Regime protocol SHA: `E53918E5FE6D2E2A`
- Manifest SHA: `AA06BE666EBFE379C82B`

## Readiness under the frozen cutoff
1. **REGIME_OOS_EXTENSION** — WAITING · NEW DATA.
2. **TT_OOS_STRUCTURAL_TRANSFER** — WAITING · NEW DATA.
3. **QUBO_HARD_INSTANCE_SUITE** — ARMED · SEALED SUITE; eligible to execute the preregistered hardness gate.
4. **QMC_QPU_READINESS** — BLOCKED unless the real QPU environment is available.

The serialized preregistration remains `PHASE_II_PREREGISTRATION_V1.json`; V2.7.1 corrects its source identity and therefore legitimately changes its manifest hash before any confirmatory Phase-II result has been executed.

---

# Quantum Research & Computation Lab V2.8.1 · Phase II Resume-Safe Parent Lock

V2.8.1 preserves the V2.8 confirmatory execution layer and fixes the Phase-II parent lock: live post-cutoff data is now counted as new evidence instead of mutating the frozen parent snapshot identity. The V2.7.1 preregistration manifest, QUBO execution specification, 120-instance plan, thresholds, seeds, sizes and frozen research engines remain unchanged.

## QUBO Phase-II execution contract
- Protocol SHA: `8E5EF191FAE97A75`
- Source evidence: `QQUBO-20260821-861D4D08E8`
- Phase-II manifest SHA: `AA06BE666EBFE379C82B`
- Execution specification SHA: `40D3225B0AFC86BC01DD`
- Canonical plan: 120 instances = 5 sizes × 3 constraint regimes × 8 sealed seeds.
- Canonical ordering: N ascending → BASE / PAIRWISE / BANDS → sealed seed order.
- Completed canonical instances cannot be rerun or replaced.
- A finalized confirmatory run cannot be reinitialized under the same protocol.

## Deterministic instance regimes
- `BASE`: exact-cardinality equal-weight portfolio selection.
- `PAIRWISE`: exact cardinality plus deterministic witness-safe pairwise exclusion constraints.
- `BANDS`: exact cardinality plus four group-count bands and three continuous factor-exposure bands.
- All three regimes for a fixed `(N, seed)` share the same economic QUBO objective; only the hard constraint structure changes.

## Sealed solver budgets
- MILP time limit: 75 seconds per instance.
- MILP relative-gap target: 1e-9.
- Simulated Annealing: 8 restarts × 64 sweeps.
- Local Search: 16 restarts, 64 max passes, 128 candidate swaps per pass.
- Every result is checkpointed immediately after its canonical instance.

## Confirmatory gate
For one fixed `(N, regime)` family across all eight sealed seeds, the gate opens only if:
1. MILP median runtime ≥ 10 s **or** MILP p95 runtime ≥ 60 s; and
2. at least 25% of that family has the best fixed-budget heuristic gap > 0.5%.

The gate is evaluated only after all 120 canonical rows exist. Technical failures produce an `INDETERMINATE` result rather than seed replacement.

## Execution artifacts
A finalized run writes deterministic manifests, JSONL checkpoints, CSV results, family summaries, final outcome, SHA-256 checksums, and an immutable ZIP artifact under `outputs/quantum_phase2/qhardness/`.

The UI launches a resumable background worker so long MILP instances do not block the Streamlit session. A resume is allowed only when the environment, executor source, protocol SHA, plan SHA, and execution-spec SHA all still match the initialized run.

---

# Quantum Research & Computation Lab V2.9 · Phase III QPU Preparation

V2.9 does **not** submit a quantum-hardware job. It adds an eighth `PHASE III / QPU` tab that inherits the immutable Phase-II QUBO artifact and separates three distinct questions:

1. Did Phase II actually finalize `120/120` and pass the preregistered classical-hardness gate?
2. Can a gate-passing family be represented on a QPU without changing the economic objective or silently weakening its hard constraints?
3. Does a named hardware backend have enough capacity and acceptable routed depth for an engineering probe?

## Frozen parent
The following remain unchanged from V2.8.1:
- `app.py`
- `asset_class_router.py`
- `engine.py`
- `evidence.py`
- `experiments.py`
- `phase2_qhardness.py`
- `data.py`
- `PHASE_II_PREREGISTRATION_V1.json`
- `QUBO_PHASEII_EXECUTION_SPEC_V1.json`

Frozen UI functions for Mission Control, Regime, QMC, QUBO, Quantum Information, Benchmark Protocol and Phase II are source-identical to V2.8.1.

## New module
`phase3_qpu.py` provides:
- immutable Phase-II final-artifact gate inheritance;
- extraction of completed gate-passing `(N, regime)` families;
- deterministic minimum-resource candidate recommendation: smallest `N`, then `BASE < PAIRWISE < BANDS`;
- equal-objective encoding audit across all eight sealed seeds;
- explicit `BANDS` encoding block until a reversible feasibility oracle or audited fixed-point/slack construction is sealed;
- abstract BANDS resource envelopes at 8/12/16 fixed-point bits;
- Qiskit / IBM Quantum Compute / Aer / Amazon Braket SDK inventory;
- session-only IBM credential path and backend discovery when `qiskit-ibm-runtime` is installed;
- backend snapshot and raw-qubit capacity audit;
- Qiskit topology/depth transpilation probe for `BASE` / `PAIRWISE` only;
- Phase-III hardware-contract draft and one-way protocol seal;
- zero QPU job submission in V2.9.

## Preparation seal
Preparation Spec SHA: `CDC693C22A3838B0B3C1`

A Phase-III hardware protocol cannot be sealed until:
- the Phase-II QUBO run is finalized `120/120` with integrity OK;
- the final outcome is `HARDNESS GATE · PASSED`;
- the selected family is a completed gate-passing family;
- all eight Phase-II seeds remain in scope;
- a named backend calibration snapshot exists;
- the selected regime has an executable equal-objective encoding;
- raw backend capacity passes.

## Constraint honesty
`BASE` and `PAIRWISE` have hardware blueprint paths based on a witness-feasible computational basis state and a number-preserving XY ring mixer. `PAIRWISE` still requires a penalty audit before a final hardware protocol is scientifically acceptable.

`BANDS` is deliberately **not** declared executable. Its group-count and real-valued factor-exposure bands were hard constraints in Phase II. V2.9 refuses to replace them with an arbitrary penalty merely to make a circuit run. It reports only reversible-oracle resource envelopes until that encoding problem is solved explicitly.

---

# Quantum Research & Computation Lab V3.0 · Exact Reversible BANDS Oracle

V3.0 does not reopen Phase II and does not submit hardware jobs. It removes the next methodological blocker exposed by V2.9: a classically hard `BANDS` family cannot be compared to a QPU until the real-valued hard constraints are represented without changing the feasible set.

## New module
`phase3_bands_oracle.py` adds:
- sealed fixed-point ladder `8 -> 12 -> 16` bits;
- deterministic signed round-half-away-from-zero quantization;
- seed-level real-vs-integer witness consistency checks;
- MILP extremum proofs over the complete binary exact-K/group-band domain;
- explicit false-positive search: integer oracle accepts / Phase-II real constraints reject;
- explicit false-negative search: Phase-II real constraints accept / integer oracle rejects;
- checkpointed background proof worker;
- early rejection of a precision after one certified counterexample;
- hard `INDETERMINATE` stop if a proof MILP is not certified;
- family promotion only after all eight sealed seeds pass exactly;
- deterministic reversible logical schedule `compute -> compare -> flag -> uncompute`;
- signed accumulator-width and qubit-resource envelopes per seed;
- one-way exact logical-oracle seal with an Oracle Blueprint SHA.

## Fidelity rule
A fixed-point precision is promoted only if every sealed seed has:
1. the original Phase-II witness feasible in both real and integer representations;
2. zero false-positive feasibility witnesses;
3. zero false-negative feasibility witnesses; and
4. every required proof MILP certified.

The minimum passing precision in the sealed `8 -> 12 -> 16` ladder is selected. If a lower precision has an uncertified proof, the ladder stops instead of skipping upward.

## Important hardware boundary
A sealed V3.0 BANDS oracle is a **logical reversible oracle specification**, not yet a compiled backend circuit. The Phase-III hardware protocol remains blocked until a gate-level compiler/transpilation path for this exact oracle is itself sealed and audited.

Oracle Spec SHA: `62854F1D7076BA742775`

---

# Quantum Research & Computation Lab V3.1 · Exact Dyadic BANDS Oracle

V3.1 preserves the finalized Phase-II hardness result and the complete V3.0 falsification record: the preregistered 8/12/16-bit approximate fixed-point ladder produced certified feasibility counterexamples and therefore cannot be promoted. V3.1 does **not** extend that ladder post hoc. Instead it canonicalizes the frozen Phase-II IEEE-754 binary64 BANDS coefficients and hard bounds exactly as dyadic rational numbers.

## Exact binary64 → dyadic mapping
Every finite Python/NumPy `float64` is represented exactly by `value.as_integer_ratio() = n / 2^e`. For each factor band, V3.1 selects a common power-of-two denominator and lifts all 40 coefficients plus the lower/upper hard bounds to signed integers **without rounding**. The mapping is verified coefficient-by-coefficient by exact `Fraction` equality and binary64 reconstruction.

Across the sealed `N=40 · BANDS` family:
- 8 / 8 seed certificates pass.
- 126 / 126 exact parameter identities pass per seed (40 coefficients + 2 bounds across each of 3 factor bands).
- Maximum per-factor common dyadic denominator exponent: 63.
- Maximum signed factor-accumulator width: 68 bits.
- Maximum sequential-reuse logical-qubit envelope: 151.
- Maximum parallel-register envelope: 336.
- Integer comparisons per oracle evaluation: 14.

## Semantic contract
The dyadic oracle represents the **strict hard-band mathematical problem used by the authoritative Phase-II MILP**. The existing `1e-8` tolerance in the Phase-II heuristic/post-processing feasibility validator is retained as a separate numerical convention and is not widened into the hardware hard-band oracle.

## Governance
- V3.0 `8 / 12 / 16` approximate fixed-point failures remain immutable evidence and are not overwritten.
- The exact dyadic logical oracle may be sealed only when the complete V3.0 falsification record is present.
- A logical oracle seal still sets `hardware_executable = false`.
- Gate-level compilation, topology/routing validation, backend calibration snapshotting, and any QPU execution remain separate future gates.
- V3.1 submits zero quantum jobs.

---

# Quantum Research & Computation Lab V3.2 · Proof-Carrying Gate Compiler

V3.2 consumes the exact live V3.1 seal as an immutable parent and emits a
deterministic, provider-neutral reversible gate stream. The compiler reference
implementation prioritizes correctness, reproducibility and auditability over
optimisation. Its abstract gate set is `X / CX / CCX / MCX`; negative controls,
register ordering, endianness and inclusive comparator semantics are explicit
in every identity contract.

## Fail-closed parent trust

`phase3_artifact_guard.py` does not trust stored status fields. It authenticates
the exact parent bytes, recomputes the legacy V3.1 oracle SHA and every seed
certificate SHA, checks the complete 8-seed order, recalculates the 126/126
parameter identities and reconstructs the frozen resource summary. Any mismatch
blocks compilation.

Parent file SHA-256:
`7b39a20ec9200b16996ec25edd660ba7bf26bfb2b454ed44dd1a333513afd50e`.

## Explicit semantic variants

- `EXACT_K_SUBSPACE` compiles four group bands and three factor bands on the
  declared `popcount(x)=10` domain. Its maximum factor accumulator is 68 signed
  bits and its maximum logical circuit width is 119 qubits.
- `FULL_BINARY` additionally compiles cardinality and implements the complete
  strict predicate for all `2^40` inputs. Its range proof requires 69 signed
  factor bits for seed 6607 and reaches 121 logical qubits.

The full-binary extra bit is retained as an auditable result. The implementation
never reuses an exact-K width outside its proof domain.

## Validation and sealing

`phase3_circuit_validation.py` runs five gates before a write-once seal:

1. exhaustive arithmetic and inclusive-comparator controls through width five;
2. all eight authoritative N=40 witnesses from the hash-locked Phase-II
   generator;
3. exhaustive small-N exact-K and full-binary oracle equivalence for both caller
   target values;
4. deterministic N=40 witness, infeasible-swap and off-cardinality controls with
   data preservation and clean ancillas;
5. an independent second compilation reproducing all gate IR hashes and
   resource ledgers.

The UI exposes the parent chain, both domain variants, per-seed circuit hashes,
four resource levels, validation gates, downloadable spec/artifact, and a
background compiler worker. An identical existing seal is preserved; a
different or invalid seal is never overwritten.

Canonical V3.2 seal (2026-09-04):

- artifact semantic SHA-256:
  `5e6cc7e53f15921f7cbd22ef66f04878b37d54372e04b5bf49f5bb4854050fcd`;
- artifact raw-file SHA-256:
  `616cc12808465916dfcfcde6c8e2c9feed1be4b294ad034f29cb7cb36704031b`;
- validation manifest SHA-256:
  `bde0dc2e90a355821c8678d2df8ac743820c0a4d2e83701aeeeaab3e1d8e9b91`;
- 16/16 circuit ledgers reproduced over two complete family passes;
- maximum exact-K envelope: 119 logical qubits, 428,273 abstract gates;
- maximum full-binary envelope: 121 logical qubits, 438,939 abstract gates.

The resource values are provider-neutral reference-compiler estimates. They
are not native-basis, routed, calibrated or physically executable counts.

Compiler Spec SHA: `EDAD55227D611B528845`  
Compiler Spec SHA-256:
`edad55227d611b52884529fe2da4f8f458e80c36367589a3499bdf075060f3aa`

## Hardware boundary

The sealed V3.2 artifact still has `hardware_executable = false` and
`qpu_submission_enabled = false`. Backend-native transpilation, frozen
calibration provenance, error-budget falsification and an algorithmic contract
for all seven BANDS constraints are required before a hardware protocol may be
sealed. The current XY mixer preserves cardinality only. No speedup or advantage
claim follows from classical hardness, exact oracle fidelity or gate-level IR.

See `QUANTUM_LAB_V3_2_ARCHITECTURE.md` for the complete design and roadmap.

---

# Quantum Research & Computation Lab V3.3 · Exact Feasible-Subspace Mixer

V3.3 consumes the immutable V3.2 exact-K oracle and seals an ordered guarded
XY mixer that preserves all seven BANDS constraints. The canonical
`DUAL_GUARD_CACHED` profile computes `a=f(x)` once per layer, evaluates the
candidate neighbor `b=f(S_e x)` for each swap edge by logical wire relabelling,
rotates only when `a=b=1`, uncomputes `b`, and clears `a` after the layer.

The formal invariant is exact relative to the frozen V3.2 predicate. It is not
an optimization-performance result and does not imply that the feasible graph
is connected.

## Canonical evidence

- V3.3 spec: `5119490433952D6A4A61` /
  `5119490433952d6a4a6151a2890b647479460e3cda4283bf1bc541243d1a8e3e`.
- Semantic artifact:
  `5ecd1fd5e3f093934220691e20139eff5c12757c2cf70bbfe6f89c2bc26b958a`.
- Validation manifest:
  `7461299442dda626986ac448c1e7ed4cbb20bdd5a4d4c27fc60a7d96deb9285e`.
- Resource manifest:
  `437d9370d0a7b37aac30094b8ebf4c5db97d84abd7cfc633267a22b52eadf8a6`.
- The seal authenticates the live algorithm, validation and deployed-chain
  verifier sources; the independent release verifier passes 13 / 13 controls.
- Eight of eight independent validation gates pass.
- N=6: 1,800 exhaustive edge actions and full-layer unitary Gram checks pass.
- N=40: all 2,400 nontrivial witness swaps are evaluated by direct predicate
  and exact-integer delta arithmetic with identical results.

## Topology and resource decisions

The ring topology is rejected: seed 5501 is feasible but has ring degree zero.
The complete topology gives every authenticated witness 31–65 feasible
one-swap neighbors and 302–1,204 states reachable within two hops. This is
positive local evidence only; global connectivity remains `INDETERMINATE`.

The canonical complete layer uses 780 ordered edges and 1,562 oracle calls. Its
maximum provider-neutral ledger reaches 120 logical qubits, 668,963,206
operations, depth 628,708,904 and an oracle-only T subtotal of 174,490,676,360.
The native cost of the controlled-XY primitives is not yet included. The named
reference construction is therefore not NISQ-practical.

V3.3 keeps `hardware_executable=false` and submits zero jobs. Native C2-XY/MCX
synthesis, routing, frozen calibration and error-budget work move explicitly to
V3.4; the prior tentative backend milestone is not represented as completed.

See `QUANTUM_LAB_V3_3_ARCHITECTURE.md` for the proof, truth table, complete
resource interpretation, graph evidence, chronology and reproduction commands.

---

# Quantum Research & Computation Lab V3.4 · Optimized Native-Lowering Contract

V3.4 preserves the frozen V3.3 exact-feasible-subspace semantics while reducing
the oracle resource envelope and lowering the guarded `C2-XY` primitive to an
elementary provider-neutral schedule. Across the eight preregistered N=40
instances, the optimized oracle remains differentially equivalent to the frozen
V3.2 predicate and the controlled-rotation matrix tests retain clean scratch.

The canonical complete-scan ledger contains 780 edges, 1,562 oracle calls,
at most 118 sequentially reused logical qubits, 1,560 continuous rotations and
`149,405,532,710` CNOTs under the selected 7T-CCX accounting convention. These
are model values—not a named-backend transpilation, routed ISA circuit, pulse
schedule, calibrated fidelity estimate or hardware observation. V3.4 therefore
keeps execution disabled and submits zero jobs.

See `QUANTUM_LAB_V3_4_ARCHITECTURE.md` and `FREEZE_CONTRACT_V3_4.json` for the
full validation ladder, immutable lineage and exact byte inventory.

---

# Quantum Research & Computation Lab V3.5 · Zero-Job Backend Admission

V3.5 turns the first provider-admission failure into a sealed institutional
result. It authenticates the exact V3.4 parent and compares the frozen selected
CCX/CNOT accounting result with IBM Quantum's documented maximum of 5,000,000
two-qubit gates per circuit. The ratio is `29,881.106542x`, so the current
representation is `REJECTED_MODEL_SCREEN` before credentials, provider access,
transpilation or QPU time are consumed.

The comparison has a deliberately narrow meaning:

- `149,405,532,710` is a provider-neutral selected-model CNOT count, not a
  backend-native result and not a lower bound;
- no real backend snapshot, `Target`, coupling-map route or calibration bundle
  is included in the scientific artifact;
- the optional snapshot/candidate auditor requires a caller-supplied
  out-of-band SHA-256 pin and retains `PASS`, `REJECTED`, `BLOCKED` and
  `NOT_RUN` as distinct states;
- synthetic fixtures validate decision logic only and are excluded from the
  sealed scientific artifact; and
- credentials remain unread, network/provider calls remain zero, submission is
  disabled, QPU jobs remain zero and quantum advantage remains unclaimed.

The live Codespace inspection used for this release found Python 3.12.1 and no
installed `qiskit`, `qiskit_ibm_runtime`, `qiskit_aer` or `rustworkx` package.
Backend-native reproduction is consequently `NOT_RUN · QISKIT ABSENT`; the
release does not install an unpinned SDK to manufacture a transpilation result.

See `QUANTUM_LAB_V3_5_ARCHITECTURE.md`,
`PHASE_III_BACKEND_ADMISSION_SPEC_V1.json` and `FREEZE_CONTRACT_V3_5.json` for
the evidence taxonomy, preregistered gates, negative-result seal and V3.6
algorithmic-reduction roadmap.

---

# Quantum Research & Computation Lab V3.6 · Structural Cost Attribution & Rewrite Gate

V3.6 moves upstream from provider admission and attacks the failed numerator
without weakening the evidence standard. It authenticates the V3.4/V3.5
lineage and reconstructs all eight frozen complete-layer ledgers exactly as

`total CNOT = 1,562 × oracle CNOT per call + 780 × 28`.

The oracle contributes more than `99.9999848%` of the selected-model CNOT cost.
The cheapest authenticated oracle costs `92,095,707` CNOT per call, so even the
mandatory compute/uncompute pair reaches `184,191,414` CNOT—`73.6765656x` the
provider-neutral V3.6 research budget of `2,500,000`. Deleting mixer edges while
preserving the exact ordered V3.4 operator is therefore unavailable, and edge
pruning changes semantics. `TOPOLOGY_ONLY` is rejected as a sufficient remedy
inside the frozen architecture; no global algorithmic lower bound is claimed.

The incremental-exposure lane verifies the exact classical swap-delta identity
for `43,680 / 43,680` constraint-row cases across all eight witnesses. This is
useful design evidence, but it is not yet a coherent quantum implementation.
Promotion remains `BLOCKED_PENDING_REVERSIBLE_COMPILER` until a gate-level
reversible IR, coherent cache-update proof, clean-ancilla proof, full
differential mixer action and selected-model resource ledger all exist.

V3.6 is `RESEARCH_ONLY` and provider-free: it imports no provider SDK, reads no
credentials, makes zero provider calls, performs no backend transpilation and
submits zero QPU jobs. It does not claim hardware executability, optimization
performance, global impossibility or quantum advantage.

See `QUANTUM_LAB_V3_6_ARCHITECTURE.md`,
`PHASE_III_V3_6_ALGORITHMIC_REDUCTION_SPEC_V1.json` and
`FREEZE_CONTRACT_V3_6.json` for the proof scope, semantic lane taxonomy,
release controls and exact frozen inventory.

---

# Quantum Research & Computation Lab V3.7 · Proof-Carrying Reversible Prototype

V3.7 implements the narrow experiment preregistered by V3.6: a coherent
incremental-exposure swap on a sealed synthetic `N=4, K=2` instance. The
portfolio register and two exact integer cache registers are coupled as one
two-level basis transition, then compiled through a deterministic Gray-path
schedule of `PATTERN_MCX` and `PATTERN_MCRX` logical primitives.

The registered ten-qubit domain is exhausted rather than sampled. Validation
covers 18,432 edge/beta basis columns, 3,072 complete-layer columns and
3,145,728 Gram entries, alongside 36 portfolio-edge and 72 constraint-row
differential cases. The reverse Gray path restores every addressed
intermediate state; the construction allocates zero ancilla and zero scratch
qubits. The complete logical ledger contains 36 pattern-MCX and four
pattern-MCRX operations across four coherent endpoint pairs.

The resulting scientific state is deliberately split:

- `SMALL_INSTANCE_REVERSIBLE_PROTOTYPE_PASSED`;
- `N40_REWRITE_ADMISSION_BLOCKED`;
- elementary one-/two-qubit decomposition `NOT IMPLEMENTED`;
- selected-model CNOT `NOT ESTIMATED`;
- N=40 projection `NOT RUN`; and
- the 2.5M selected-model budget gate `NOT EVALUATED`.

The positive prototype result therefore does not supersede the V3.6
structural rejection and is not a production successor-equivalence result.
Seven-constraint N=40 reversible arithmetic, full eight-seed equivalence,
elementary decomposition, a comparable resource ledger and the internal
budget screen are still required before backend-native work can be admitted.

V3.7 remains `RESEARCH_ONLY` and provider-free. It imports no provider SDK,
reads no credential, makes zero provider calls, performs no backend
transpilation, submits zero QPU jobs and keeps `hardware_executable=false`.
Optimization performance, global impossibility and quantum advantage are not
claimed.

The release also repairs a packaging-closure gap additively. Twenty-seven
historical runtime/support paths that were present in the working project but
omitted from the prior institutional ZIP are captured as a
`V3.7_LEGACY_SUPPORT_SNAPSHOT`. No V3.6 bytes or historical freeze claims are
rewritten.

See `QUANTUM_LAB_V3_7_ARCHITECTURE.md`,
`PHASE_III_V3_7_REVERSIBLE_PROTOTYPE_SPEC_V1.json` and
`FREEZE_CONTRACT_V3_7.json` for the exact fixture, proof obligations, resource
boundary, release controls and 99-path package closure.

---

# Quantum Research & Computation Lab V3.8 · Elementary Decomposition & N=40 Admission

V3.8 authenticates the complete V3.7 lineage and lowers every one of its 40
signed-pattern logical primitives to the preregistered provider-neutral basis
`X/H/T/TDG/RY/RZ/CX`. The model is frozen before evaluation: clean AND
ladders, an exact six-CX Toffoli, and an exact two-CX controlled-RX. No
post-observation template or topology switching is permitted.

On the registered synthetic `N=4, K=2` operator, the exact selected-model
ledger is 5,920 one-qubit gates, 3,632 CNOT, serial CNOT depth 3,632, eight
clean auxiliaries at peak and 18 total logical qubits. All 49,152 primitive
basis/beta cases pass, with maximum action and norm residuals below `1e-12`
and zero auxiliary cleanup failures. This is an elementary refinement of the
authenticated V3.7 operator, not an N=40 projection.

The production gate remains deliberately separate. All eight frozen
`N=40, K=10, BANDS` seed contracts and their seven-constraint classical delta
evidence authenticate, but 0/8 seeds have a scalable reversible V3.8 IR,
elementary lowering, coherent cleanup, ordered-layer connectivity or a
selected-model CNOT ledger. Consequently:

- overall: `ELEMENTARY_PROTOTYPE_PASSED_N40_ADMISSION_BLOCKED`;
- N=40 admission: `BLOCKED_INCOMPLETE_REVERSIBLE_IR`;
- N=40 selected-model CNOT: `NOT_ESTIMATED`; and
- internal 2,500,000-CNOT gate: `NOT_EVALUATED`.

The frozen V3.4/V3.6 cost rejection remains authentic historical evidence for
that architecture and is not relabeled as a V3.8 numerator or a global lower
bound. V3.8 remains `RESEARCH_ONLY`, imports no provider SDK, reads no
credential, makes zero provider calls, performs no backend transpilation,
submits zero QPU jobs and keeps `hardware_executable=false`. Optimization
performance and quantum advantage are not claimed.

See `QUANTUM_LAB_V3_8_ARCHITECTURE.md` and
`PHASE_III_V3_8_ELEMENTARY_ADMISSION_SPEC_V1.json` for the exact templates,
counting convention, exhaustive proof, admission matrix and successor gate.

---

# Quantum Research & Computation Lab V3.9 · Scalable N40 Reversible IR

V3.9 closes the exact evidence gap left open by V3.8 without promoting the
project to hardware. Each of the eight frozen `N=40, K=10, BANDS` seeds now
has a deterministic proof-carrying reversible macro IR over all 780 canonical
swap positions. The construction updates the seven exact integer cache
registers coherently, uses symmetric endpoint-feasibility intervals, lowers
every macro under the decomposition model frozen by V3.8, and preserves every
position in lexicographic order as either a live rotation or a certified
identity.

The proof inventory is complete:

- 6,240 / 6,240 ordered edge-seed positions;
- 43,680 / 43,680 constraint-row cases;
- 4,220 live reversible pair rotations;
- 2,020 statically dead positions with exact empty-overlap certificates;
- 28,320 structurally nonzero row-edge deltas;
- 19,094 nonzero row-edge deltas among live rotations; and
- eight deterministic seed/layer hashes with independent replay.

The positive statement is deliberately bounded:

`FEASIBLE_SUPPORT_COHERENT_EQUIVALENCE_PROVEN_BY_CONSTRUCTION`.

It applies to exact-K states whose seven caller-owned cache registers equal
their exact integer functions and whose starting portfolio satisfies every
hard band. Reversible composition establishes global unitarity of the emitted
IR. `FULL_BINARY_OPERATOR_EQUIVALENCE` is not claimed, and an ordered
780-position layer is not evidence of complete feasible-graph connectivity.
Full-binary operator equivalence and complete feasible-graph connectivity are not claimed.

The exact selected-model resource screen rejects this architecture. Per-seed
complete-layer counts range from `722,438,876` to `781,332,180` CNOT; the
maximum exceeds the preregistered `2,500,000` gate by `778,832,180`. The
decision is therefore:

- reversible IR: `N40_REVERSIBLE_IR_PASSED`;
- resource screen: `REJECTED_SELECTED_MODEL_CNOT_BUDGET`;
- overall: `N40_REVERSIBLE_IR_PASSED_RESOURCE_SCREEN_REJECTED`;
- production: `BLOCKED_GLOBAL_CONNECTIVITY_AND_BACKEND`; and
- complete global connectivity: `INDETERMINATE`.

This is an architecture-specific negative result, not a lower bound over other
adders, encodings, factorizations or mixer constructions. V3.9 remains
`RESEARCH_ONLY`, imports no provider SDK, reads no credential, makes zero
provider calls, performs no backend transpilation, submits zero QPU jobs and
keeps `hardware_executable=false`. Optimization performance, global
impossibility and quantum advantage are not claimed.

The next falsifiable gate is
`GLOBAL_FEASIBLE_GRAPH_CONNECTIVITY_OR_COUNTEREXAMPLE`; because the resource
screen already fails, any redesigned resource model must be preregistered as a
new architecture rather than silently substituted into V3.9.

See `QUANTUM_LAB_V3_9_ARCHITECTURE.md` and
`PHASE_III_V3_9_SCALABLE_REVERSIBLE_IR_SPEC_V1.json` for the exact canonical
cache transformation, proof boundary, counting convention and release chain.

---

# Quantum Research & Computation Lab V4.0 · Exact Global Connectivity Counterexample

V4.0 answers the complete feasible-graph question that V3.9 deliberately left
`INDETERMINATE`. For each of the eight frozen `N=40, K=10, BANDS` seeds, the
vertex set contains every portfolio satisfying the four group bands and three
exact-dyadic factor bands. Two vertices are adjacent exactly when their Hamming
distance is two: one selected asset is removed and one unselected asset is
added. This is the full feasible one-out/one-in graph, not a topology sample or
a bounded local search.

The exact group-product meet-in-the-middle enumerator and nine-core DSU certify:

- `21,655,776` feasible vertices;
- `337,710,603` unique undirected feasible edges;
- `216,557,760` nine-core incidences, exactly `10 × 21,655,776`;
- `91,534,251` distinct nine-cores and `21,655,765` successful unions;
- six connected seeds: `1103, 3301, 4409, 5501, 6607, 8807`; and
- two disconnected seeds: `2207` with component sizes `3,981,552 + 1`, and
  `7703` with component sizes `3,053,394 + 1 + 1`.

All eight seeds completed both registered structural replays: group split
`[0,1] | [2,3]` with `FACTOR_1` first, and group split `[0,2] | [1,3]` with
`FACTOR_2` first. Every stable enumeration, core-index, component and witness
field matches. The three singleton components are exact feasible portfolios;
all `300` possible one-swap neighbors of each were checked directly, giving
`900 / 900` rejected neighbors and zero feasible neighbors. The all-seed
decision is therefore
`GLOBAL_FEASIBLE_GRAPH_DISCONNECTED_COUNTEREXAMPLE`, not missing evidence.
No subgraph of the same one-swap edge universe can restore connectivity.

V4.0 does not revise the V3.9 resource result. The frozen maximum remains
`781,332,180` CNOT against the `2,500,000` selected-model ceiling, with margin
`-778,832,180`; that architecture remains
`REJECTED_SELECTED_MODEL_CNOT_BUDGET`. The successor
`EXACT_COMPRESSED_UNSIGNED_SLACK_LINEAR_ARITHMETIC_WITH_CERTIFIED_BRIDGES_V1`
is preregistered for V4.1 with both the one-swap candidate and a deterministic
one-plus-two-swap bridge candidate. It is `NOT_EVALUATED`: CNOT is
`NOT_EVALUATED`, budget margin is `NOT_COMPUTED`, and expected or projected
cost claims are prohibited. The next falsifiable gate is
`AUGMENTED_1_2_EXCHANGE_GRAPH_CONNECTIVITY_OR_COUNTEREXAMPLE`.

The counterexample rejects global ergodicity of this frozen one-swap graph; it
does not establish impossibility for augmented mixers, optimization
performance or quantum computing generally. V4.0 remains `RESEARCH_ONLY` and
provider-free: no provider SDK is imported, no credential is read, provider
calls and QPU jobs remain zero, backend transpilation is `NOT_RUN`, submission
is disabled, `hardware_executable=false`, and quantum advantage is
`NOT_CLAIMED`.

See [`QUANTUM_LAB_V4_0_ARCHITECTURE.md`](QUANTUM_LAB_V4_0_ARCHITECTURE.md),
`PHASE_III_V4_0_GLOBAL_CONNECTIVITY_SPEC_V1.json`, and the sealed connectivity
artifact for the graph definition, completeness theorem, seed ledger,
counterexamples, chronology and V4.1 preregistration boundary.

---

# Quantum Research & Computation Lab V4.1 · Certified Bridges & Proof-Carrying Resources

V4.1 executes the successor experiment preregistered by V4.0. It preserves the
complete authenticated one-swap forest and audits every two-out/two-in move
incident to the three isolated V4.0 portfolios. This is a narrow, exact
augmentation of the registered graph—not an unreported topology search and
not a claim that every augmented edge has been enumerated.

For each isolated source there are exactly `C(10,2) × C(30,2) = 19,575`
candidate targets. The resulting `58,725 / 58,725` candidates are classified
by three independent implementations:

- Python exact delta arithmetic in canonical candidate order;
- Python exact full recomputation in reversed enumeration order; and
- an independently compiled C++ `int128` full-recomputation engine.

All three ledgers match exactly. They identify `787` feasible incident
two-swap neighbors (`267 + 260 + 260`). Deterministic registered ordering then
selects three component bridges. Adding those three edges to all
`337,710,603` authenticated V4.0 one-swap edges yields a connected certified
spanning subgraph with `337,710,606` edges and one connected component for
each of the eight frozen seeds. The scientific decision is
`AUGMENTED_1_2_EXCHANGE_GRAPH_CONNECTED_ALL_SEEDS_BY_CERTIFIED_SUBGRAPH`.

The number `337,710,606` is the size of that certified connected subgraph. The
complete augmented one-plus-two-swap edge count is
`NOT_ENUMERATED_NOT_REQUIRED_FOR_CONNECTIVITY_CERTIFICATE`; V4.1 makes no
claim about that larger count.

V4.1 also evaluates the preregistered
`EXACT_COMPRESSED_UNSIGNED_SLACK_LINEAR_ARITHMETIC_WITH_CERTIFIED_BRIDGES_V1`
compiler. Its coefficient compression is accepted only where dual exact
meet-in-the-middle certificates prove complete-domain predicate parity. The
guarded unsigned-slack arithmetic, compute/rotate/uncompute paths, clean
decomposition ancillas, one-qubit gates, abstract operations and selected
`X/H/T/TDG/RY/RZ/CX` counts are all published per seed. Coherent cache
preparation is reported in a separate ledger and excluded from the registered
mixer-layer numerator; it is neither hidden nor credited against that
endpoint.

Both preregistered resource candidates are published and rejected:

- R1, `R1_LINEAR_SLACK_ALL_ONE_SWAP`, reaches a maximum of `15,256,056`
  selected-model CNOT;
- R2, `R2_LINEAR_SLACK_ONE_SWAP_PLUS_TWO_SWAP_BRIDGES`, reaches a maximum of
  `15,663,936` selected-model CNOT; and
- the frozen primary R2 endpoint therefore misses the `2,500,000` ceiling by
  `13,163,936` CNOT, with a minimum margin of `-13,163,936`.

The maximum R2 logical allocation, including registered clean decomposition
ancillas, is `311` qubits. These counts are exact under the selected frozen
decomposition model, not cross-model lower bounds and not backend-native
transpilation results. Post-observation switching between R1 and R2 is
prohibited. Connectivity success cannot substitute for resource admission.

The combined release decision is
`V41_AUGMENTED_CONNECTIVITY_CERTIFIED_RESOURCE_SCREEN_REJECTED`; production
admission remains `REJECTED_RESOURCE_BUDGET_HARDWARE_NOT_AUTHORIZED`. The next
falsifiable gate is
`SPARSE_CONNECTED_GENERATOR_COMPILER_OR_STRONGER_EXACT_ARITHMETIC_REDUCTION`.

V4.1 remains `RESEARCH_ONLY` and provider-free. It imports no provider SDK,
reads no credentials, performs no provider discovery or backend
transpilation, makes zero provider calls, submits zero QPU jobs and keeps
`hardware_executable=false`. Optimization performance and quantum advantage
are `NOT_CLAIMED`.

See [`QUANTUM_LAB_V4_1_ARCHITECTURE.md`](QUANTUM_LAB_V4_1_ARCHITECTURE.md),
`PHASE_III_V4_1_CERTIFIED_BRIDGE_COMPILER_SPEC_V1.json`, and the sealed V4.1
artifact for the exact candidate universe, bridge-selection contract,
compression certificates, resource formulas, chronology and non-substitutable
admission gates.

---

# Quantum Research & Computation Lab V4.2 · Indexed Coined-Walk Compiler

V4.2 executes the exact architectural rewrite demanded by the V4.1 negative
resource result. It does not delete exchange labels or reinterpret the V4.1
connectivity certificate. Two persistent 40-qubit one-hot coin registers
address the removed and added assets, allowing one target construction and one
seven-band exact-feasibility oracle to be shared across all `780` pair
positions. Both cyclic coin rings preserve Hamming weight one and connect all
`40 × 40 = 1,600` ordered address states.

The registered SELECT is certified only on the exact promise subspace:
feasible `N=40, K=10` data states times two one-hot coin registers. An
independent C++ engine and an independent Python implementation agree on:

- `2,218` nonempty arbitrary feasible supports through `N=5`;
- `264,328` SELECT and cleanup cases with zero failures;
- `2,218` data-versus-joint component comparisons with zero failures;
- `28` complete exact-K joint graphs through `N=8`, all connected; and
- `8,826` Hamming-distance-four bridge involution controls.

The support ledger retains every V4.1 one-swap edge and the exact three V4.1
bridges. Across the eight frozen seeds it describes `34,649,241,600` joint
promise vertices and `69,973,909,206` registered support edges. This is a
structural support certificate, not an enumerated statevector or performance
experiment.

Under the unchanged
`CONTROLLED_CUCCARO_RIPPLE_CLEAN_LADDER_6CX_CCX_CRX2CX_V1` model, one complete
coined-walk generator step includes two exact target-feasibility oracle calls,
the complete address/target/data SELECT scaffold, both 40-edge coin rings and
every authenticated bridge. All eight seeds pass the immutable `2,500,000`
CNOT ceiling. Counts range from `1,062,182` to `1,135,430`; the worst-case
margin is `+1,364,570`, and the maximum recycled-workspace logical-qubit bound
is `331`. Relative to the V4.1 R2 maximum, the selected-model maximum is reduced
by `92.75%`.

The combined decision is
`V42_INDEXED_COINED_WALK_CONNECTED_RESOURCE_SCREEN_PASSED`, with
`PROVIDER_NEUTRAL_RESEARCH_GENERATOR_ADMITTED_HARDWARE_NOT_AUTHORIZED`.
Admission stops there. Circuit materialization, independent reversible
simulation, backend-native lowering, routing, calibration, noise, runtime,
optimization performance and quantum advantage have not been established.
The next falsifiable gate is
`INDEPENDENT_REVERSIBLE_SIMULATION_AND_BACKEND_AGNOSTIC_CIRCUIT_MATERIALIZATION`.

V4.2 remains `RESEARCH_ONLY`: provider SDK imports, credential reads, provider
calls and QPU jobs are zero; backend transpilation is `NOT_RUN`;
`hardware_executable=false`; quantum advantage is `NOT_CLAIMED`.

See [`QUANTUM_LAB_V4_2_ARCHITECTURE.md`](QUANTUM_LAB_V4_2_ARCHITECTURE.md),
`PHASE_III_V4_2_COINED_WALK_COMPILER_SPEC_V1.json`, and the sealed V4.2
artifact for the exact promise, chronology, formulas, per-seed ledgers and
claim boundary.

---

# Quantum Research & Computation Lab V4.3 · Materialized Reversible Circuit IR

V4.3 executes the next falsifiable gate named by V4.2. Every complete N=40
coined-walk generator step is expanded into a deterministic elementary stream
over the explicit provider-neutral basis `X/H/T/TDG/RY/RZ/CX`. The release
materializes all eight frozen seeds—not a representative seed, extrapolated
formula, or backend transpilation—and commits ordered 8,192-instruction chunk
hashes, per-stage hashes, complete gate histograms, register maps and one root
for each evidence family in the single sealed artifact.

The complete inventory contains `21,925,902` elementary instructions. The
maximum seed materializes `1,158,046` CX against the unchanged `2,500,000`
budget, leaving a minimum margin of `+1,341,954`. The maximum explicitly
allocated recycled-workspace bound is `339` logical qubits. The ordered stream
root is
`9405dc3659aa7a86fad4437f3a29bd654d87bae0a221e4d169b4f1f5af43bbeb`;
the register-map root is
`315e7a7d8742ab5a4456e0ea26be8c94b098050d60bc1ad9dd874900c4b0218e`.

The materializer closes two inherited nomenclature/design gaps without
rewriting V4.2:

- `H` is now explicit in the elementary basis because the exact 6-CX Toffoli
  template uses it; the omission in the V4.2 basis list is disclosed, while
  every V4.2 byte and its CNOT decision remain immutable.
- The four group sum banks are zero-extended from width 3 to the width-5
  minimum required by the materialized Cuccaro sequence. This adds `22,784`
  CX per complete step while preserving the exact predicate.
- Exact interval membership is implemented as the XOR of two nested `GE`
  predicates. This removes the two unnecessary row-CCX terms costed in V4.2,
  subtracting `168` CX per step. The net materialization delta is therefore
  `+22,616` CX for every seed.

The separately compiled C++17 simulator exhausts `107,520` arithmetic cases,
`64` promise-space SELECT cases and `64` involutive round trips. Exact
statevector controls independently verify the 6-CX Toffoli, the 2-CX
`XX+YY` coin template and the Gray-path two-level bridge construction up to
global phase. All eight authenticated N=40 representatives also supply a
positive feasible exchange-and-cleanup witness.

Acceptance is strictly promise-scoped. A mandatory `N=2, K=1` negative
control starts from infeasible `10`, targets the only feasible state `01`, and
leaves the retained feasibility flag equal to one on reverse cleanup. V4.3
therefore publishes
`OFF_PROMISE_CLEANUP_REJECTED_WITH_WITNESS`; it does not claim clean operation
on the full binary Hilbert space.

The combined research decision is
`V43_BACKEND_AGNOSTIC_CIRCUIT_MATERIALIZED_PROMISE_SIMULATION_PASSED`, with
`PROVIDER_NEUTRAL_RESEARCH_CIRCUIT_IR_ADMITTED_BACKEND_AND_HARDWARE_NOT_AUTHORIZED`.
The next gate is
`NAMED_BACKEND_ZERO_JOB_TRANSPILATION_AND_ROUTING_PROTOCOL`.

V4.3 remains `RESEARCH_ONLY`. No provider SDK is imported, no credential is
read, no named backend is selected, backend transpilation is `NOT_RUN`,
provider calls and QPU jobs are zero, `hardware_executable=false`,
optimization performance is `NOT_TESTED`, and quantum advantage is
`NOT_CLAIMED`.

See [`QUANTUM_LAB_V4_3_ARCHITECTURE.md`](QUANTUM_LAB_V4_3_ARCHITECTURE.md),
`PHASE_III_V4_3_REVERSIBLE_CIRCUIT_MATERIALIZATION_SPEC_V1.json`, and the
sealed V4.3 artifact for the exact register/liveness contract, angles,
instruction canonicalization, chunk manifests, per-seed ledgers, independent
controls and evidence boundary.

---

# Quantum Research & Computation Lab V4.4 · Named Offline Backend / Zero-Job Routing

V4.4 executes the exact named-backend zero-job gate registered by V4.3. It
authenticates the complete V4.3 release, pins one offline FakeMarrakesh
structural target from `qiskit-ibm-runtime==0.49.0`, and freezes Qiskit core
`2.5.2` transpiler settings before evaluating the workload.

The target exposes `156` physical qubits, the basis `CZ/ID/RZ/SX/X`, and `352`
directed coupling edges. This is a fake-backend snapshot for local compilation
tests—not a live-provider query, current calibration record, backend
availability statement or hardware certificate. The bundled properties file
is pinned for provenance but excluded from the capacity and canary decisions.

The mandatory capacity precheck rejects all eight V4.3 workloads:

- frozen logical widths: `330, 331, 327, 328, 329, 331, 339, 334`;
- deficits relative to 156: `−174, −175, −171, −172, −173, −175, −183, −178`;
- rejected seeds: `8 / 8`;
- worst deficit: `−183` qubits; and
- persistent `DATA + REMOVE_COIN + ADD_COIN + TARGET` floor: `160` qubits,
  already `4` above the target before arithmetic scratch and flags.

The protocol therefore does not reconstruct or transpile any full workload.
Full native-gate counts, routed depth, routing and scheduling are all recorded
as `NOT_RUN_CAPACITY_PRECHECK_REJECTED`, never as synthetic zeroes.

A bounded zero-job suite separately validates the pinned compilation mechanics:

1. three-qubit non-native ISA translation;
2. five-qubit reversible `CCX`/multi-control-X arithmetic motif;
3. one literal 40-qubit V4.3 coin ring;
4. both 40-qubit coin rings without data, target or scratch; and
5. the exact 156-qubit capacity boundary.

All five outputs pass the frozen ISA and coupling audit in two clean processes
with identical canonical bundle SHA-256
`b744a2bd1364d531c65d89e24dd7f78ef8170e12cbf13affd3e28a0a1191a0f0`.
The mandatory 157-qubit negative canary is rejected with `TranspilerError`.
Canary success is not extrapolated to the rejected 327–339-qubit workload.

The combined decision is
`V44_FAKE_MARRAKESH_CAPACITY_REJECTED_CANARY_PIPELINE_VALIDATED_ZERO_JOB`.
Production admission is
`REJECTED_RESEARCH_ARCHITECTURE_REQUIRES_PROOF_CARRYING_WIDTH_REDUCTION`.
The next falsifiable gate is
`PROOF_CARRYING_WIDTH_REDUCTION_TO_156_QUBITS_OR_LOWER_WITH_EXACT_PROMISE_PARITY`.

V4.4 remains `RESEARCH_ONLY`. The confirmatory runner imports no provider SDK,
reads no credentials, makes zero provider calls and zero network calls, and
submits zero simulator or QPU jobs. `hardware_executable=false`; calibration-
aware fidelity and optimization performance are `NOT_TESTED`; quantum
advantage is `NOT_CLAIMED`.

See [`QUANTUM_LAB_V4_4_ARCHITECTURE.md`](QUANTUM_LAB_V4_4_ARCHITECTURE.md),
`PHASE_III_V4_4_NAMED_BACKEND_ZERO_JOB_ROUTING_SPEC_V1.json`,
`PHASE_III_V4_4_FROZEN_BACKEND_SNAPSHOT_V1.json`,
`PHASE_III_V4_4_TOOLCHAIN_MANIFEST_V1.json`, and the sealed V4.4 artifact for
the exact chronology, hashes, capacity rows, canary outputs and claim boundary.

---

# Quantum Research & Computation Lab V4.5 · Proof-Carrying Width Reduction

V4.5 is an append-only, `RESEARCH_ONLY` successor to the exact V4.4 release.
It addresses the single structural gate that V4.4 rejected: the authenticated
V4.3 circuit family required `327–339` logical wires while the pinned offline
FakeMarrakesh structural target exposes `156` qubits. V4.5 changes the
reversible compiler architecture before any full target transpilation.

## Immutable parent and result-blind chronology

The compiler authenticates the exact V4.4 freeze and its 209-path immutable
successor inventory before emitting evidence. No V4.3 or V4.4 byte is rewritten.
The V4.5 protocol was sealed with `result_state_at_seal=NOT_EVALUATED`; its
acceptance and negative-result branches were therefore fixed before the result.

V4.5 compiles each promised 40-state one-hot coin interface to a six-qubit
little-endian binary address, streams the former 40-qubit target bank one bit
at a time, and replaces seven simultaneous guarded-sum banks with one shared
bank under an explicit Bennett compute–use–uncompute schedule. For arithmetic
width `w`, the certified allocation is exactly:

`DATA40 + REMOVE_ADDR6 + ADD_ADDR6 + SUM_WORK(w) + CONSTANT(w) + CARRY1 + ADDRESSED2 + ROW_FLAGS7 + CONTROL_FLAGS5 = 67 + 2w`.

The exact width ledger is:

| Seed | V4.3 width | V4.5 width | Margin to 156 |
|---:|---:|---:|---:|
| 1103 | 330 | 135 | +21 |
| 2207 | 331 | 137 | +19 |
| 3301 | 327 | 133 | +23 |
| 4409 | 328 | 135 | +21 |
| 5501 | 329 | 137 | +19 |
| 6607 | 331 | 137 | +19 |
| 7703 | 339 | 145 | +11 |
| 8807 | 334 | 139 | +17 |

All eight streams fit the preregistered `156`-qubit logical-capacity gate. The
maximum is `145`, retaining an `11`-qubit structural margin. All eight
provider-neutral materialized streams also remain within the unchanged
`2,500,000`-CX ceiling; the worst is seed `7703` at `2,499,790 CX`, with only
`+210` remaining. This narrow margin is retained literally rather than rounded
or relaxed.

## Exact promise parity, liveness and negative scope

The admitted coin map is the logical isometry
`|e_i> one-hot → |i> binary` for `i ∈ {0,…,39}`. Every authenticated feasible
component representative exhausts all `40 × 40 = 1,600` valid remove/add
address pairs and preserves the exact V4.3 SELECT trace. Binary addresses
`40–63` and arbitrary off-promise ancestors remain outside the equivalence
claim. The mandatory V4.3 off-promise cleanup witness remains rejected; V4.5
does not reinterpret it as a globally clean oracle.

The register/liveness certificate proves contiguous non-overlapping maps,
ordered phase-local borrowing, explicit inverse computation and clean exit for
all reusable workspace. `reset`, measurement, discard and dependency loss are
forbidden and absent. The certificate semantic identity is
`93f119c6493fac2eb0e7d281db1842482201cd7a680cf8ca93b9fdcc69a53102`.

A three-CX relative-phase Toffoli ladder is used only inside the certified
`B† A B` streamed-target envelope, where the compute phases cancel under the
exact adjoint. Ordinary exact multi-control ladders remain everywhere else.
This confined optimization preserves the falsifiability of the fixed CX gate.

## Institutional UI and governance

The V4.5 evidence surface authenticates the sealed artifact, specification,
source, independent checker, liveness certificate and exact V4.4 parent before
disclosing any V4.5 outcome. If any identity or the exact 28-check contract
fails, width, parity and CX results are masked fail-closed. The authenticated
surface provides seven evidence ledgers, ten downloads, nineteen
machine-readable provenance hooks and twelve permanently disabled governance
controls. The historical V4.4 rejection remains visible and unchanged.

The exact combined decision is
`V45_PROOF_CARRYING_WIDTH_REDUCTION_PASSED_EXACT_PROMISE_PARITY`.
Production admission remains
`WIDTH_PROOF_ADMITTED_TO_NEXT_OFFLINE_GATE_ONLY_HARDWARE_EXECUTION_REJECTED`.

## Hard boundary and next gate

V4.5 does **not** reconstruct, transpile or route these full streams on
FakeMarrakesh. Full circuit reconstruction, transpilation and routing are all
`NOT_RUN_IN_V4_5`; native CZ count and routed depth are not measured; current
calibration, fidelity, runtime and optimization performance are `NOT_TESTED`.
The compiler and evidence UI import no provider SDK, read zero credentials,
make zero provider and network calls, and submit zero simulator or QPU jobs.
`hardware_executable=false`; quantum advantage is `NOT_CLAIMED`.

The exact next falsifiable gate is
`PINNED_FAKEMARRAKESH_FULL_RECONSTRUCTION_TRANSLATION_AND_ROUTING_OF_WIDTH_ADMITTED_V4_5_STREAMS`.
That separately preregistered successor must reconstruct every admitted stream,
translate and route it against the pinned offline target, and enforce its native
CZ, routed-depth, ISA and coupling limits. It was not executed by V4.5. Even a
future offline routing pass would not establish current hardware availability,
calibration quality, execution success, runtime, economic utility or advantage.

See [`QUANTUM_LAB_V4_5_ARCHITECTURE.md`](QUANTUM_LAB_V4_5_ARCHITECTURE.md),
`PHASE_III_V4_5_PROOF_CARRYING_WIDTH_REDUCTION_SPEC_V1.json`,
`PHASE_III_V4_5_REGISTER_LIVENESS_CERTIFICATE_V1.json`, the independent width
checker, validation suite and sealed V4.5 artifact for the exact construction,
hashes, per-seed streams, cleanup proofs and claim boundary.

---

# Quantum Research & Computation Lab V4.6 · Full-Stream FakeMarrakesh Routing

V4.6 executes the exact offline successor gate registered by V4.5. It
authenticates the V4.5 freeze contract, its proof-carrying width result and all
`227` predecessor paths immutable to a successor before reconstructing every
instruction of the eight admitted streams. Only this README and the integrated
UI are permitted successor surfaces; no earlier scientific evidence is
rewritten.

## Frozen protocol and reference mechanics

The decisive limits were already sealed in V4.5 before V4.6 exploration:
`250,000,000` native CZ per seed, `250,000,000` ASAP structural layers per
seed, at most `100×` native-CZ expansion over the V4.5 CX count, and exactly
zero ISA or coupling violations. Routing is pinned to `basic`, translation to
`translator`, and the transpiler seed to `4505`.

One seed-1103 implementation pilot preceded the V4.6 specification. It is
explicitly non-confirmatory and changed none of those inherited thresholds or
acceptance branches. The confirmatory eight-seed result was still
`NOT_EVALUATED` when the V4.6 protocol was sealed.

An isolated Qiskit `2.5.2` reference builder, with socket connections denied,
freezes all `24,180` ordered shortest paths over the `156`-qubit offline
FakeMarrakesh coupling graph and nine bounded native-translation canaries. The
confirmatory compiler then imports neither Qiskit nor a provider client. It
regenerates the exact V4.5 stream, inserts the BasicSwap path operations,
updates the complete logical/physical permutation, expands the frozen native
macros and commits every route globally, per 8,192-record chunk and per stage.

This is a compact, exactly reconstructible circuit IR. It is not a monolithic
`QuantumCircuit`, pulse schedule, submitted job or hardware payload.

## Confirmatory eight-stream result

All eight authenticated streams pass the structural and inherited resource
gates:

| Seed | Logical qubits | Input instructions | Inserted SWAP | Native CZ | Native instructions | ASAP structural depth |
|---:|---:|---:|---:|---:|---:|---:|
| 1103 | 135 | 6,077,566 | 4,144,702 | 14,839,144 | 59,482,464 | 23,878,539 |
| 2207 | 137 | 6,086,776 | 4,169,221 | 14,916,301 | 59,736,353 | 23,925,669 |
| 3301 | 133 | 5,969,118 | 4,072,600 | 14,579,062 | 58,434,154 | 23,449,597 |
| 4409 | 135 | 5,969,230 | 4,067,511 | 14,563,795 | 58,388,465 | 23,416,448 |
| 5501 | 137 | 5,969,310 | 4,080,645 | 14,603,197 | 58,506,751 | 23,436,098 |
| 6607 | 137 | 6,077,382 | 4,149,075 | 14,852,263 | 59,521,637 | 23,876,346 |
| 7703 | 145 | 6,312,490 | 4,342,669 | 15,527,797 | 62,128,995 | 24,893,376 |
| 8807 | 139 | 6,185,342 | 4,233,197 | 15,148,405 | 60,677,639 | 24,375,938 |

The complete result covers `48,647,214` input instructions, `33,259,620`
inserted SWAP operations, `119,029,964` native CZ operations and
`476,876,458` reconstructible native instructions. The worst stream uses
`145 / 156` logical qubits, `15,527,797` CZ and `24,893,376` structural
layers. Every final layout is a sealed bijection; all ISA and coupling
violation counts are zero. A clean-process replay reproduces the sealed
artifact byte-for-byte.

The exact combined decision is
`V46_FAKEMARRAKESH_FULL_STREAM_ROUTING_PASSED_STRUCTURAL_AND_PREREGISTERED_RESOURCE_GATES`.
Production admission remains
`OFFLINE_STRUCTURAL_COMPILATION_ONLY_HARDWARE_EXECUTION_REJECTED`.

## Hard evidence boundary and next gate

V4.6 remains `RESEARCH_ONLY`. The target is a pinned, dated offline fake
backend snapshot and is not current hardware evidence. Structural depth uses
gate layers, not calibrated duration. Calibration-aware fidelity, runtime,
error feasibility and optimization performance are `NOT_TESTED`; provider SDK
imports, credential reads, provider/network/backend calls, local simulator
jobs and QPU jobs are all zero. `hardware_executable=false`; quantum advantage
is `NOT_CLAIMED`.

The next falsifiable gate is
`PINNED_DATED_PROPERTIES_DURATION_ERROR_AND_OPTIMIZATION_FEASIBILITY_OF_V46_ROUTED_STREAMS`.
It requires a separately preregistered study and grants no implicit authority
to discover a provider or submit hardware work.

See [`QUANTUM_LAB_V4_6_ARCHITECTURE.md`](QUANTUM_LAB_V4_6_ARCHITECTURE.md),
`PHASE_III_V4_6_FULL_STREAM_FAKEMARRAKESH_ROUTING_SPEC_V1.json`, the frozen
path oracle and translation contract, the standard-library checker, validation
suite and sealed V4.6 artifact for exact hashes, route commitments and claim
boundaries.

---

# Quantum Research & Computation Lab V4.7 · Dated Properties Stress Screen

V4.7 executes the exact next gate registered by V4.6. It authenticates the
complete V4.6 freeze, all `247` immutable predecessor files, the eight ordered
route/native/layout commitments and one pinned historical FakeMarrakesh
properties file before evaluating any result. The experiment is offline and
append-only; only this README and the integrated UI supersede predecessor
surfaces.

## Historical evidence and frozen model

The raw properties are the exact
`props_marrakesh.json` bytes bundled in
`qiskit-ibm-runtime==0.49.0`:

- raw size: `565,487` bytes;
- raw SHA-256:
  `d49d7ae07deb95947ea10e5b9b9c5cbab6df21f98610543817f35ade2b1aece6`;
- backend record: `ibm_marrakesh` version `1.0.7`;
- global date: `2025-02-26T14:52:45-05:00`; and
- embedded field range: 2024-10-28 through 2025-02-26.

The global timestamp is not asserted as a cutoff for every property. This is a
dated fake-provider snapshot, never current calibration or hardware evidence.

Strict normalization retains all `976` native tuples—`352` directed CZ tuples
and `156` tuples for each of `id`, `rz`, `sx` and `x`—with all `1,952`
required duration/error fields. There is no imputation and no reverse-edge
fallback. The raw file exposes `26` directed / `13` undirected CZ tuples with
reported `gate_error=1`. Removing them produces components of sizes
`153, 1, 1, 1`; qubits `24`, `102` and `113` are isolated, leaving an
eight-qubit margin over the maximum logical width `145`.

The duration diagnostic is an exact integer-`dt` per-qubit ASAP replay with
`dt=4 ns`. The error diagnostic is the exact decimal sum
`Σ occurrence_count × reported_gate_error`. Modeled makespan is not a pulse
schedule or wall-clock runtime; reported-error mass is not circuit fidelity,
success probability, expected failures, logical error or solution quality.

## Exact baseline and single preregistered candidate

Every input instruction is streamed once into two independent routing states:

1. `V4_6_EXACT_BASIC_SWAP_BASELINE`, which must reproduce every V4.6 stream,
   route, native, manifest and final-layout commitment exactly; and
2. `FAULT_EXCLUDED_SHORTEST_HOP_RELIABILITY_TIEBREAK_V1`, the sole
   preregistered candidate.

The candidate maps logical order onto the ascending prefix of the 153-qubit
healthy component and uses minimum hops, then minimum reported error mass,
then minimum integer duration, then lexicographic path. It has no lookahead,
global layout search or global-optimality claim.

All eight exact baseline commitments reproduce. All eight candidate rows pass
the frozen research-feasibility gate with zero ISA, coupling, missing-property
and unit-error occurrences. The route/cost ledger is:

| Seed | Width | Baseline SWAP | Candidate SWAP | Baseline CZ | Candidate CZ | Baseline ticks | Candidate ticks |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1103 | 135 | 4,144,702 | 4,794,333 | 14,839,144 | 16,788,037 | 236,387,704 | 257,656,102 |
| 2207 | 137 | 4,169,221 | 4,957,735 | 14,916,301 | 17,281,843 | 236,971,819 | 262,568,530 |
| 3301 | 133 | 4,072,600 | 4,727,475 | 14,579,062 | 16,543,687 | 232,197,030 | 251,458,802 |
| 4409 | 135 | 4,067,511 | 4,730,300 | 14,563,795 | 16,552,162 | 231,845,571 | 254,898,592 |
| 5501 | 137 | 4,080,645 | 4,811,702 | 14,603,197 | 16,796,368 | 232,117,393 | 254,815,121 |
| 6607 | 137 | 4,149,075 | 4,890,808 | 14,852,263 | 17,077,462 | 236,360,494 | 263,677,826 |
| 7703 | 145 | 4,342,669 | 5,064,271 | 15,527,797 | 17,692,603 | 246,471,109 | 274,995,541 |
| 8807 | 139 | 4,233,197 | 5,047,609 | 15,148,405 | 17,591,641 | 241,313,112 | 271,482,591 |

Across all eight streams, the baseline retains its exact V4.6 totals of
`33,259,620` SWAP, `119,029,964` CZ and `476,876,458` native instructions.
The candidate uses `39,024,233` SWAP, `136,323,803` CZ and `528,757,975`
native instructions. Its maximum structural depth is `26,858,925`; its maximum
modeled makespan is `274,995,541` ticks. These remain software-model costs, not
hardware runtime.

## Dated error screen and Pareto result

| Seed | Baseline unit-error uses | Candidate unit-error uses | Baseline reported-error mass | Candidate reported-error mass | Pareto-safe |
|---:|---:|---:|---:|---:|:---:|
| 1103 | 697,333 | 0 | 795561.02943504188668074289 | 86829.40777656678431324590 | No |
| 2207 | 760,448 | 0 | 858304.53106308783708010426 | 86144.04233156570251251180 | No |
| 3301 | 710,343 | 0 | 805228.15929800536725895747 | 85533.54813833759214551522 | No |
| 4409 | 671,694 | 0 | 766501.40832646773446763720 | 84204.70841897854388059858 | No |
| 5501 | 762,350 | 0 | 860032.44189977830317530631 | 84141.19843006236119562837 | No |
| 6607 | 723,690 | 0 | 824390.83560544412486681001 | 87370.67116115422453853494 | No |
| 7703 | 874,040 | 0 | 976891.62454186701306026378 | 90679.07139081027353572958 | No |
| 8807 | 774,705 | 0 | 876397.24240492877206601761 | 91173.32727818479321918669 | No |

The baseline totals `5,974,603` occurrences on tuples whose dated reported
error is one, versus `0` for the candidate. Descriptive error mass falls from
exactly `6763307.27257462103865583953` to
`696075.97492566027534095108`. The candidate nevertheless increases native CZ
and modeled makespan on every seed, so a Pareto-safe replacement is **not**
demonstrated. This negative result is retained rather than optimized away.

## Architecture-level necessary-condition rejection

The preregistered optimistic lower bound removes every SWAP and one-qubit gate,
assigns every direct CX the globally best reported CZ error and duration, and
assumes 78-way disjoint CZ parallelism. Even that impossible-to-beat bound has
reported-error mass between `2447.0041764902838817308` and
`2590.5624070300740640860`, while its duration is `3.849337×` to `4.075163×`
the maximum dated T2. Both optimistic screens fail for all eight seeds.

The exact combined decision is
`V47_HISTORICAL_PROPERTIES_STRESS_SCREEN_REJECTS_FIXED_V46_ARCHITECTURE_NO_CURRENT_HARDWARE_INFERENCE`.
The candidate decision is
`V47_FAULT_EXCLUDED_RESEARCH_ROUTING_FEASIBLE_UNDER_HISTORICAL_PROPERTIES`;
the Pareto decision is
`PARETO_SAFE_REPLACEMENT_NOT_DEMONSTRATED`.

## Authentication, UI and release boundary

The sealed artifact is `9,370,376` bytes with raw SHA-256
`ddb8dae96c1d5fe1040f92731c995315e04232da645fed0b2d34cf7575a06185`
and semantic SHA-256
`fa1b8a2be1471080134f34ada7ba8cff488c87077a4e5f271fd29828f1fffbaf`.
It passes `51/51` standard-library independent checks, `96/96` scientific
validation checks, `20/20` release-chain checks and `26/26` scientific unit
tests. The institutional Streamlit surface passes `21/21` authentication gates
and `42/42` positive-rerun checks while preserving the twelve outer tabs and
adding six V4.7 evidence tabs. All six evidence downloads are raw-hash-gated;
all ten governance actions remain disabled.

A second clean process, launched with an empty environment and
`PYTHONHASHSEED=0`, reproduced the artifact byte-for-byte; its raw and semantic
SHA-256 are identical to the sealed values above.

V4.7 remains `RESEARCH_ONLY`. The optimizer, checker, validation and UI import
no provider client, read no credentials, make zero provider/network/backend
calls, and submit zero local-simulator or QPU jobs. `hardware_executable=false`;
current calibration, pulse scheduling, circuit fidelity, utility and quantum
advantage are not claimed. Production admission is
`OFFLINE_HISTORICAL_PROPERTIES_ONLY_HARDWARE_EXECUTION_REJECTED`.

The next falsifiable gate is
`MULTI_SNAPSHOT_ROBUSTNESS_AND_ARCHITECTURE_LEVEL_CZ_REDUCTION_BEFORE_ANY_CURRENT_PROVIDER_DISCOVERY`.
It requires a separately sealed protocol and does not authorize live provider
discovery or execution.

See [`QUANTUM_LAB_V4_7_ARCHITECTURE.md`](QUANTUM_LAB_V4_7_ARCHITECTURE.md),
`PHASE_III_V4_7_PINNED_DATED_PROPERTIES_OPTIMIZATION_SPEC_V1.json`, the raw and
normalized dated-property evidence, the fault-excluded path oracle, duration /
error model, independent checker, sealed validation report and final freeze for
the exact chronology, hashes, ledgers and deployment contract.

---

# Quantum Research & Computation Lab V4.8 · Exact Architecture Reduction and Snapshot Governance

V4.8 executes the falsifiable successor gate left by V4.7 without contacting a
provider. It authenticates the complete V4.7 lineage, preregisters one exact
adder substitution, materializes eight full logical streams, and replays the
unchanged frozen V4.6 BasicSwap path oracle. In parallel, it inventories every
authenticated local properties input and refuses to manufacture a
multi-snapshot claim from duplicate files or synthetic perturbations.

## Exact controlled-adder redesign

Only the controlled constant-adder primitive changes. The V4.5 logical layout,
binary coin rings, streamed Bennett SELECT structure, certified bridges,
initial layout and V4.6 routing oracle remain fixed.

The candidate loads each set bit of a clean constant register with a CX from
the external control, executes the exact uncontrolled Cuccaro constant adder,
then unloads the register. The translated per-add cost changes from
`68w − 102` CX to `17w − 25 + 2·popcount(c mod 2^w)` CX.

An optimizer-independent gate-level simulator checks exhaustive widths `5` and
`6`, plus `2,000` deterministic cases for each of widths
`7, 8, 16, 31, 33, 34, 35, 36, 39`. All `28,240 / 28,240` cases preserve the
exact controlled modular sum and clean constant/carry exit. This proves the
specified basis permutation under the registered construction; it is not a
hardware-fidelity statement.

## Full-stream resource result

All eight candidate streams are materially emitted and routed with zero ISA or
coupling violations:

| Seed | Width | Parent CX | V4.8 CX | Parent routed CZ | V4.8 routed CZ | V4.8 depth |
|---:|---:|---:|---:|---:|---:|---:|
| 1103 | 135 | 2,405,038 | 808,014 | 14,839,144 | 7,418,727 | 7,348,857 |
| 2207 | 137 | 2,408,638 | 811,478 | 14,916,301 | 7,418,714 | 7,370,423 |
| 3301 | 133 | 2,361,262 | 795,990 | 14,579,062 | 7,327,440 | 7,247,341 |
| 4409 | 135 | 2,361,262 | 796,174 | 14,563,795 | 7,241,677 | 7,231,760 |
| 5501 | 137 | 2,361,262 | 796,158 | 14,603,197 | 7,328,538 | 7,252,504 |
| 6607 | 137 | 2,405,038 | 807,950 | 14,852,263 | 7,420,451 | 7,345,974 |
| 7703 | 145 | 2,499,790 | 838,686 | 15,527,797 | 7,811,853 | 7,632,359 |
| 8807 | 139 | 2,448,814 | 819,646 | 15,148,405 | 7,598,332 | 7,468,370 |

Aggregate logical CX falls from `19,251,104` to `6,474,096`, a reduction of
`12,777,008` (approximately `66.37%`). Frozen-BasicSwap CZ falls from
`119,029,964` to `59,565,732`, a reduction of `59,464,232` (approximately
`49.96%`). Structural depth is a gate-layer diagnostic, not calibrated
duration or wall-clock runtime.

## Multi-snapshot admission remains not evaluable

The authenticated local lineage contains one distinct properties epoch: the
dated `2025-02-26` FakeMarrakesh development snapshot already used in V4.7.
Copies in another directory, archive members and normalized representations
share the same identity and count once. Synthetic jitter, bootstrap samples,
resampling or metadata-only changes never count as authentic snapshots.

The sealed protocol requires at least three same-family epochs with distinct
raw identities, normalized property-vector identities and timestamps. Every
snapshot × seed cell must pass; averaging cannot rescue a failure. Observation
is therefore `1 / 3`, and the exact decision is
`MULTI_SNAPSHOT_ROBUSTNESS_NOT_EVALUABLE_INSUFFICIENT_DISTINCT_AUTHENTIC_SNAPSHOT_IDENTITIES`.

## Historical necessary-condition frontier

V4.8 reuses the V4.7 deliberately optimistic lower bounds: zero SWAP, zero
one-qubit cost, the globally best historical CZ error/duration and ideal
78-way CZ parallelism. Despite the large architecture reduction, every seed
still fails both necessary screens. Candidate CX remains `795,990–838,686`,
above the historical idealized duration ceiling `613,392` and far above the
strict additive-error ceiling `964`.

These screens are necessary, not sufficient. Additive reported-error mass is
not fidelity, success probability, expected failures or logical error.

## Sealed identities and independent evidence

The V4.8 artifact raw SHA-256 is
`f6fcce00b9ce95cd9e30eeb938e243c308b5408255dc98556e8be45a36691f76`;
its semantic SHA-256 is
`6df8440320e38e0bb73674f3ceb0f4bc179385d0d344c9521fa35f197504c55f`.
The optimizer source is pinned by
`0bef3609b7c535b13cd25254a8c322f7d1c207b4111549e5b86bd5ff2e9ea0e9`
and its standard-library independent checker by
`1435e1c4efb61c30e884e87132ec39f30f1206c96332e3802c19dd0a42269f3c`.

The artifact passes `65/65` optimizer-independent checks, `96/96` scientific
validation checks, `20/20` release-chain checks and `26/26` scientific unit
tests. An empty-environment replay with `PYTHONHASHSEED=0` reproduces the
artifact byte-for-byte. The institutional UI contract requires `24/24`
authentication gates, six raw-hash-gated evidence downloads, ten disabled
governance actions and `42/42` positive-rerun checks before release.

## Decision and hard boundary

The combined decision is
`V48_EXACT_ARCHITECTURE_CX_AND_BASICSWAP_CZ_REDUCTION_DEMONSTRATED_MULTI_SNAPSHOT_ROBUSTNESS_NOT_EVALUABLE_HARDWARE_REJECTED`.
Production admission remains
`RESEARCH_ONLY_HARDWARE_EXECUTION_REJECTED`.

Provider SDK imports, credential reads, provider/network/backend calls, local
simulator submissions and QPU jobs remain zero. `hardware_executable=false`;
the dated snapshot is not current hardware evidence, and no current
calibration, pulse schedule, calibrated fidelity, utility or quantum advantage
is claimed.

The next falsifiable gate is
`ACQUIRE_TWO_ADDITIONAL_AUTHENTIC_OFFLINE_SNAPSHOT_EPOCHS_AND_REDUCE_DIRECT_CX_BELOW_BOTH_HISTORICAL_NECESSARY_THRESHOLDS_BEFORE_ANY_CURRENT_PROVIDER_DISCOVERY`.

See [`QUANTUM_LAB_V4_8_ARCHITECTURE.md`](QUANTUM_LAB_V4_8_ARCHITECTURE.md),
the multi-snapshot/CZ-reduction specification, snapshot catalog, normalized
cohort, architecture oracle, robustness cost model, independent checker,
sealed artifact and validation report for the exact protocol and identities.

---

# Phase III V4.9 · Terminal Offline Admission Dossier

V4.9 is the final offline decision phase of the V4 lineage. It authenticates
the exact V4.8 parent, preserves every frozen predecessor path and evaluates
two independent prerequisites before any current-provider discovery:

1. at least three authentic same-family snapshot epochs with distinct raw,
   normalized-property and source-time identities; and
2. an exact architecture that passes every seed × snapshot capacity, routing,
   ISA, coupling, property, duration and strict error-screen gate.

The current cohort is `1 / 3`. The frozen V4.8 reference architecture remains
at `795,990–838,686` direct CX against a strict admissible maximum of `963`.
The sealed current decision is therefore
`V49_NOT_EVALUABLE_INSUFFICIENT_AUTHENTIC_EPOCHS`; provider discovery is
denied and V5 entry is closed.

V4.9 is compact by construction:

- protocol, engine, snapshot intake and tests live in [`v49/`](v49/);
- sealed evidence lives in
  `outputs/quantum_phase3/v49_pre_hardware_admission/`; and
- release engineering lives in `release/quantum_v49/`.

No provider SDK is imported, no credential is read and no provider, network,
backend, simulator or QPU job is called. `hardware_executable=false`; no
hardware readiness, fidelity, utility or quantum advantage is claimed.
