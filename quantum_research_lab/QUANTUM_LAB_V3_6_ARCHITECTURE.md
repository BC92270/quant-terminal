# Quantum Lab V3.6 — Structural Cost Attribution & Algorithmic Rewrite Gate

## Release position

V3.6 is an additive `RESEARCH_ONLY` successor to the sealed V3.5 zero-job
backend-admission result. V3.5 established that the selected V3.4 accounting
model cannot enter the provider workflow. V3.6 determines which mechanism
causes that rejection and which classes of research can, or cannot, remove it.

The release is deliberately provider-free. It does not install Qiskit, select
a backend, read credentials, call a provider, transpile, route or submit a job.
Its output is an authenticated architecture decision:

`ARCHITECTURE_REWRITE_REQUIRED · TOPOLOGY_ONLY REJECTED`

This is a result about the frozen V3.4 construction and selected 7T-CCX CNOT
accounting model. It is not a lower bound for every quantum algorithm and not
an impossibility proof for portfolio optimization.

## Immutable parent chain

V3.6 consumes, without rewriting:

- V3.4 semantic artifact SHA-256
  `2753b81527bf470b8528550d4de491b968e114e4d59541fd16aeca2d995c9210`;
- V3.4 raw artifact SHA-256
  `4e15aba6c83dcec0ff3e22652df03c624f635956d10b769514cfbd78cdaed7fd`;
- V3.5 semantic artifact SHA-256
  `7e217693093dca453ab478c003fe2303e3f6fa21e2a8f36d5bcadef9c58508da`;
- V3.5 raw artifact SHA-256
  `94e8741cf2d1564a513917aeb83f5cbca4ce75821a3a8517cefbad48bbfb0ef4`;
- V3.5 semantic freeze SHA-256
  `efda21e201cd9ecc7b4fab7544c4c024a96b925dc39f977c17331a5278c994d2`;
- V3.5 raw freeze SHA-256
  `8d0a5ca3f37cf4c7a755537d55eb7b2a202bb72603527ec9f4f8fb7d1ba21f52`.

V3.5's provider-limit observation remains historical evidence with its own
retrieval timestamp. V3.6 inherits it; it does not relabel the observation as a
new live provider measurement.

## Exact structural attribution

The frozen canonical V3.4 layer uses a complete swap scan with:

- `E = 780` controlled-XY edges;
- `2E + 2 = 1,562` optimized-oracle calls;
- `28` selected-model CNOTs per elementary mixer edge; and
- `780 × 28 = 21,840` selected-model mixer CNOTs in total.

For every authenticated seed, the V3.4 ledger satisfies exactly:

```text
layer_cnot = 1,562 × oracle_cnot_per_call + 780 × 28
```

| Seed | Oracle CNOT / call | Complete-layer CNOT | Oracle share |
|---:|---:|---:|---:|
| 1103 | 92,113,403 | 143,881,157,326 | 99.99998482% |
| 2207 | 94,092,865 | 146,973,076,970 | 99.99998514% |
| 3301 | 94,836,617 | 148,134,817,594 | 99.99998526% |
| 4409 | 92,681,391 | 144,768,354,582 | 99.99998491% |
| 5501 | 95,650,135 | 149,405,532,710 | 99.99998538% |
| 6607 | 92,095,707 | 143,853,516,174 | 99.99998482% |
| 7703 | 95,619,337 | 149,357,426,234 | 99.99998538% |
| 8807 | 92,971,589 | 145,221,643,858 | 99.99998496% |

The arithmetic has no fitted parameter. Each per-call value is recovered by
subtracting the sealed mixer contribution and dividing by the exact sealed
oracle-call count; the remainder must be zero for all eight seeds.

## Structural rejection

The inherited IBM screen is five million two-qubit gates per circuit. The
cheapest single frozen V3.4 oracle call is `92,095,707` selected-model CNOTs,
or `18.4191414×` that external limit. The cached feasible-guard architecture
requires at least an initial compute and final uncompute even if all mixer
edges are removed; the cheapest frozen pair is therefore `184,191,414`, or
`36.8382828×` the external limit.

V3.6 also freezes a stricter internal research admission target of `2,500,000`
selected-model CNOTs. This is a provider-neutral engineering budget, not a
provider-native limit. Against that target:

- the worst complete layer requires a `59,762.213084×` reduction;
- the cheapest single frozen oracle requires `36.8382828×`; and
- the cheapest compute/uncompute pair requires `73.6765656×`.

Therefore edge pruning, sparse topology selection, guard-cache removal or
mixer micro-optimization **cannot be sufficient** while the frozen oracle
implementation remains. This is a mathematical rejection inside the frozen
resource formula. It says nothing about a rewritten oracle or a different
algorithm.

## Reduction portfolio and evidence classes

V3.6 keeps candidate lanes independent.

| Candidate lane | V3.6 state | Reason |
|---|---|---|
| `TOPOLOGY_ONLY` | `REJECTED_STRUCTURAL_FLOOR` | A mandatory frozen oracle pair already exceeds both budgets before any edge cost |
| `GUARD_CACHE_ONLY` | `REJECTED_INSUFFICIENT` | Removing the `+2` calls does not change the per-edge full-oracle bottleneck |
| `INCREMENTAL_EXPOSURE_GUARD` | `RESEARCH_CANDIDATE · BLOCKED_GATE_IR` | Exact classical swap deltas are plausible, but no reversible coherent update, clean-uncompute proof or sealed resource ledger exists |
| `FACTORIZED_CONSTRAINT_ORACLE` | `RESEARCH_CANDIDATE · BLOCKED_EQUIVALENCE` | Must reproduce all seven frozen constraints and binary64/dyadic semantics before resource claims |
| `BLOCK_COORDINATE_HYBRID` | `CHANGED_SEMANTICS · NEW_PROTOCOL_REQUIRED` | Local subproblems plus a classical outer loop are not the frozen end-to-end algorithm |
| `CLASSICAL_PRESOLVE_SYMMETRY` | `CONDITIONAL · NOT_MEASURED` | Instance-specific reduction requires point-in-time inputs, frozen rules and retained excluded-variable certificates |
| `PENALTY_RELAXATION` | `PROHIBITED_AS_SUCCESSOR_EQUIVALENCE` | A penalized or approximate feasible set cannot inherit exact V3.4 equivalence |

`RESEARCH_CANDIDATE` is not a passing circuit. `CHANGED_SEMANTICS` is not a
failure if pursued under a new protocol, but it cannot be compared as an exact
successor without an explicit bridge experiment.

## Incremental-exposure frontier

The leading exact research lane is a state-augmented mixer that would retain
the seven exact constraint accumulators and update them by swap deltas. A
classically correct relation

```text
exposure_k(S_ij x) = exposure_k(x) + (x_i - x_j) × (a_kj - a_ki)
```

does not by itself define the required quantum operation. A passing successor
must implement a unitary that keeps the portfolio and accumulator registers
coherent on both branches of every XY rotation, proves all scratch cleanup,
and reproduces the frozen predicate. Applying a classical update after an XY
rotation and discarding an orientation bit is forbidden because it can leak
which-path information.

No cost reduction is booked until the complete reversible schedule exists.

## Preregistered successor gates

A future algorithmic candidate may clear the V3.6 rewrite gate only if every
gate below passes on the same sealed artifact:

1. exact V3.4 and V3.5 parent identities;
2. explicit semantic class: `EXACT_SUCCESSOR` or `CHANGED_SEMANTICS`;
3. exact predicate equivalence for all seven hard constraints where claimed;
4. exact-K preservation and a declared initial-state contract;
5. reversible accumulator/update identity on exhaustive small-width cases;
6. clean ancillas after every ordered layer;
7. connectivity evidence independent of local witness degree;
8. deterministic provider-neutral gate IR and resource ledger;
9. selected-model CNOT maximum `≤ 2,500,000` on all eight frozen seeds;
10. no post-observation candidate switching or hidden fallback;
11. negative-result retention; and
12. zero network calls, zero credentials and zero QPU jobs.

Passing these gates would open only the V3.5 confirmatory backend-audit lane.
It would not authorize provider access or hardware execution.

## V3.6 artifact contract

`SEALED_V3_6_ALGORITHMIC_REDUCTION_ARTIFACT.json` must contain:

- raw and semantic parent commitments;
- the exact eight-row cost decomposition;
- integer divisibility/reconstruction evidence;
- the internal provider-neutral research-budget comparison; the external IBM
  limit remains authenticated in the immutable V3.5 parent rather than copied
  into the V3.6 scientific payload;
- independent candidate-lane states and reasons;
- a decision of `ARCHITECTURE_REWRITE_REQUIRED` unless an exact compiled
  successor actually clears every preregistered gate;
- deterministic validation and resource-manifest hashes; and
- immutable `RESEARCH_ONLY`, `qpu_jobs_submitted = 0`,
  `hardware_executable = false`, `quantum_advantage = NOT_CLAIMED` fields.

Synthetic fixtures may test rejection paths, but they must be labelled
`TEST_ONLY` and excluded from the scientific artifact.

## Institutional control-room surface

The V3.6 UI should make the bottleneck legible without implying progress that
has not occurred:

- a cost-concentration waterfall separating oracle and mixer contributions;
- per-seed exact reconstruction and compression ratios;
- the adjacent authenticated V3.5 external-limit panel, kept visually and
  semantically distinct from the V3.6 internal research budget;
- a candidate portfolio with semantic class and gate state;
- a critical-path panel for the incremental-exposure candidate;
- independent admission, hardware-claim and execution vetoes; and
- downloadable sealed artifact and specification.

Zeros remain `NOT_RECORDED` unless an artifact establishes otherwise.

## Validation ladder

The V3.6 release verifier must independently establish:

- V3.5 freeze and release chain are exact before successor transition;
- 39 immutable V3.5 frozen files remain byte-exact;
- only `quantum_research_lab/README.md` and `quantum_research_lab/ui.py` are
  authorized V3.5-to-V3.6 successor transitions;
- all eight cost identities reconstruct exactly with zero remainder;
- extrema, percentages and budget ratios are recomputed rather than trusted;
- topology-only and guard-cache-only decisions fail closed;
- uncompiled research lanes cannot emit reduced gate counts;
- semantic-change lanes cannot inherit exact-successor labels;
- artifact and manifests are deterministic and self-authenticating;
- UI acceptance preserves the historical 12-tab contract; and
- credential, provider and execution boundaries remain zero-job.

## Release-chain hardening

V3.6 does not treat predecessor verifier output as a trust anchor. The
independent V3.6 verifier must first match the raw V3.5 freeze digest above,
then require its exact 41-path inventory. It must verify the 39 immutable files
byte for byte and accept README/UI only as one of two explicit states: sealed
V3.5 or sealed V3.6. A different successor is rejected even if an older
verifier would have labelled the path merely “superseded”.

All JSON control files are parsed with duplicate-key rejection. Every relative
path is resolved under the declared release root before it is read. Core
scientific functions are not trusted to verify their own source commitments;
the release verifier carries independent hashing and arithmetic reconstruction.

The installer cannot make a multi-file filesystem transaction truly atomic,
so it uses an install lock, stages and authenticates every source, writes new
dependencies before the integration surface, and replaces `ui.py` last. Its
backup contains a preimage hash manifest. A rollback is reported successful
only after every preimage hash is reproduced and the applicable predecessor
release/freeze verification passes. A boolean “no exception during copy” is
not accepted as rollback evidence.

AppTest acceptance scopes V3.6 markers, the disabled backend/QPU controls and
the exact 12-tab contract. Live acceptance additionally requires the V3.6 DOM
markers on `?workspace=quantum-research`; HTTP 200 alone is insufficient.

## Next admissible frontier

V3.7 should not be named-backend transpilation. It should attempt one narrow,
proof-carrying reversible prototype of the incremental-exposure relation on a
small exact-K instance, including a two-level coherent update, scratch cleanup,
differential predicate checks and an honest gate ledger. Scaling claims remain
blocked until that prototype is exact and reproducible.

## Source register

- IBM Quantum, [Job limits](https://quantum.cloud.ibm.com/docs/en/guides/job-limits)
- Hadfield et al., [From the Quantum Approximate Optimization Algorithm to a Quantum Alternating Operator Ansatz](https://arxiv.org/abs/1709.03489)
- Fuchs et al., [Constraint Preserving Mixers for the Quantum Approximate Optimization Algorithm](https://arxiv.org/abs/2203.06095)

These sources define external limits or motivate constrained mixers. They do
not validate the V3.6 implementation; all V3.6 decisions are recomputed from
the authenticated local artifact chain.
