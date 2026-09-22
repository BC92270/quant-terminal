# Quantum Lab V4.1 · Certified Bridges and Proof-Carrying Resources

## Institutional decision

Quantum Lab V4.1 resolves the falsifiable successor gate registered by V4.0
for the frozen `N=40, K=10, BANDS` family. It authenticates the complete V4.0
one-swap component forest, exhausts every registered two-out/two-in candidate
incident to each of the three V4.0 singleton components, and adds only the
deterministically selected exact-feasible bridges needed by the registered
Kruskal rule.

The resulting augmented-connectivity decision is:

```text
AUGMENTED_1_2_EXCHANGE_GRAPH_CONNECTED_ALL_SEEDS_BY_CERTIFIED_SUBGRAPH
```

Connectivity is repaired for all eight seeds with three selected bridges. The
resource screen remains independently rejected:

```text
overall               V41_AUGMENTED_CONNECTIVITY_CERTIFIED_RESOURCE_SCREEN_REJECTED
resource architecture REJECTED_SELECTED_MODEL_CNOT_BUDGET
production admission  REJECTED_RESOURCE_BUDGET_HARDWARE_NOT_AUTHORIZED
next gate              SPARSE_CONNECTED_GENERATOR_COMPILER_OR_STRONGER_EXACT_ARITHMETIC_REDUCTION
```

| Gate | Exact result | Institutional boundary |
|---|---:|---|
| Frozen seeds | 8 / 8 | No seed averaging |
| V4.0 components before bridges | 11 | Authenticated, not regenerated |
| Incident two-swap candidates audited | 58,725 | `3 x C(10,2) x C(30,2)` |
| Exact-feasible incident candidates | 787 | Complete registered incident universe |
| Selected bridges | 3 | Deterministic Kruskal order |
| Components after bridges | 8 | One component per seed |
| Certified spanning-subgraph edges | 337,710,606 | 337,710,603 V4.0 edges plus 3 bridges |
| Complete augmented edge count | NOT ENUMERATED | Not required for the connectivity certificate |
| R1 maximum | 15,256,056 CNOT | Rejected by connectivity and budget across the family |
| R2 maximum | 15,663,936 CNOT | Registered primary candidate |
| R2 minimum budget margin | -13,163,936 CNOT | Ceiling remains 2,500,000 |
| Maximum R2 logical qubits | 311 | Selected abstract decomposition model only |
| Backend transpilation | NOT RUN | Provider-neutral research phase |
| Hardware | NOT EXECUTABLE | Zero provider calls and zero QPU jobs |

V4.1 proves connectivity of the full one-plus-two-swap graph by exhibiting a
connected certified spanning subgraph. It does not enumerate or claim the
number of every possible two-swap edge. It also does not establish backend
feasibility, physical depth, error tolerance, runtime advantage, investment
performance, or quantum advantage.

## Frozen lineage

The accepted computation begins with the exact V4.0 release and authenticates:

- the V4.0 specification, engine, Python source and sealed artifact;
- the raw and semantic identities of `FREEZE_CONTRACT_V4_0.json`;
- its 145-path inventory and path fingerprint;
- all 143 immutable V4.0 paths, excluding only the explicitly supersedable
  `quantum_research_lab/README.md` and `quantum_research_lab/ui.py` surfaces;
- the inherited V3.9 through V3.1 chain and dyadic oracle lineage.

No V4.0 scientific artifact is regenerated or rewritten. The V4.0 graph
result remains a valid counterexample for the all-one-swap move family. V4.1
adds a larger registered move family and does not relabel the parent result.

## Chronology and confirmatory boundary

Before the V4.1 protocol was sealed, an unsealed engineering audit observed
that the three isolated V4.0 portfolios had respectively `267`, `260`, and
`260` exact-feasible incident two-swap candidates. These observations are
disclosed as exploratory signals, not encoded as expected confirmatory output.

The specification freezes candidate enumeration, canonical ledgers, replay
fields, bridge ordering, component membership, compression proofs, resource
numerator, decomposition costs, budget, and all decision branches. Two
amendments are disclosed in the specification:

1. correction of truncated SHA-256 constants in the independent C++ engine,
   before any confirmatory evidence was accepted; and
2. completion of the already registered ripple/comparator decomposition model,
   before the first V4.1 resource ledger.

Neither amendment changes the candidate family, connectivity rule, budget, or
post-observation selection policy.

## Complete incident bridge audit

For each authenticated singleton source `S`, the registered universe contains
every target obtained by removing two selected indices and adding two
unselected indices:

```text
C(10,2) x C(30,2) = 19,575 candidates per source.
```

The three sources therefore require exactly `58,725` classifications. Every
candidate is evaluated against the original four group bands and three exact
dyadic factor bands with signed exact integer arithmetic.

Three independent methods must agree on the canonical record sequence:

1. Python exact delta updates in canonical removed/addition order;
2. Python full-mask recomputation using a reversed generation order followed
   by canonical sorting; and
3. an independent C++ `int128` full two-swap audit.

The sealed rows carry complete feasible inventories plus commitments to the
full feasible/infeasible classification ledger. Agreement is required for the
audit universe, audited count, ledger hash, feasible count, feasible records,
seed, and source mask. A digest without record equality is insufficient.

## Connectivity certificate

Each V4.0 disconnected seed contains exactly one non-singleton component plus
one or two singleton components. A feasible target distinct from every
singleton representative therefore belongs to the authenticated non-singleton
component.

Candidate bridges are normalized and sorted by:

```text
(component representative pair,
 endpoint-mask pair,
 removed-index pair,
 added-index pair).
```

A deterministic DSU/Kruskal replay accepts a bridge only when its endpoints
currently lie in different authenticated V4.0 components. Selection stops
when the seed is connected or the complete registered candidate inventory is
exhausted.

The proof object is the union of:

- all `337,710,603` exact one-swap edges authenticated by V4.0; and
- the three selected exact-feasible Hamming-distance-four bridges.

That `337,710,606`-edge subgraph is connected on every seed. Because it is a
subgraph of the full one-plus-two-swap graph, the supergraph is connected as
well. No assertion about its complete edge count is needed.

## Exact compression certificates

V4.1 evaluates all three factor predicates for all eight seeds, producing 24
factor certificates. For a factor row with original integer coefficients
`a_i`, a candidate shift `s` uses:

```text
b_i = round_half_even(a_i / 2^s)
lower' = ceil(lower / 2^s)
upper' = floor(upper / 2^s).
```

For every shift, two meet-in-the-middle partitions independently compute:

- the exact minimum distance of any complete-domain sum to either threshold;
- the exact maximum residual
  `abs(sum_i (a_i - 2^s b_i) x_i)`; and
- canonical witnesses for both extrema.

For `s > 0`, acceptance requires a strict residual bound smaller than the
minimum threshold distance. V4.1 then performs an explicit original-versus-
compressed classification replay over the complete group-valid exact-`K`
domain. The largest shift satisfying every condition is selected. Shift zero
remains the exact identity case.

The two MITM partitions, factor hashes, seed hashes, parent-certificate links,
selected shifts, interval rounding and full-domain parity results must all
match. Compression is therefore a proof-carrying exact predicate rewrite, not
a floating-point approximation claim.

## Guarded-slack compiler

The architecture identifier is:

```text
EXACT_COMPRESSED_UNSIGNED_SLACK_LINEAR_ARITHMETIC_WITH_CERTIFIED_BRIDGES_V1
```

For a compressed constraint with sum `B`, bounds `[l,u]`, and
`G=max(i,j)|b_i-b_j|`, the coherent cache stores:

```text
Z = (B - l) + G.
```

On feasible support, `G <= Z <= G + (u-l)`. A one-swap delta lies in
`[-G,G]`; consequently the normalized intermediate lies in
`[0, 2G + (u-l)]`. The registered width represents this interval exactly and
prevents modular wraparound.

Every one of the 780 lexicographic asset-pair positions is retained as either
a live guarded pair action or a certified identity position. No sampled edge
removal is admitted. Forward updates, bound flags, aggregate controls, the
rotation, inverse flag computation and denormalization return reusable scratch
clean under the selected abstract model.

R2 appends the selected bridges in registered Kruskal order. Each bridge is a
two-level rotation on the full data-plus-cache joint register using a canonical
differing-bit Gray path. Its selected-model CNOT formula is independently
replayed from joint width and joint endpoint Hamming distance.

## Resource numerator and independent replay

The resource numerator is one complete ordered mixer layer. Coherent cache
preparation is mandatory, reported separately, and excluded from that
numerator exactly as preregistered. No cancellation is assumed between macros
or positions.

The selected abstract decomposition model is:

```text
CONTROLLED_CUCCARO_RIPPLE_CLEAN_LADDER_6CX_CCX_CRX2CX_V1
```

The ledger publishes both registered candidates without post-observation
switching:

- `R1_LINEAR_SLACK_ALL_ONE_SWAP`;
- `R2_LINEAR_SLACK_ONE_SWAP_PLUS_TWO_SWAP_BRIDGES`.

Every seed contains a generated IR ledger and a separately constructed closed-
formula replay. The validation layer cross-links compression certificates,
guarded registers, parent certificates, one-swap macro terms, bridge IR,
connectivity decisions, cache preparation, candidate margins and aggregate
decisions.

The maximum R2 numerator is `15,663,936` CNOT, versus the unchanged
`2,500,000` ceiling. Its minimum margin is `-13,163,936`, so R2 is rejected
despite passing connectivity. The `97.99%` reduction relative to V3.9's
`781,332,180` maximum is an arithmetic resource-ledger comparison inside the
selected model; it is not a hardware speedup or quantum-advantage claim.

## Validation stack

The release requires all of the following:

- 16/16 artifact reconstruction checks;
- 28/28 independent scientific validation checks;
- exact raw and semantic identities for the specification and artifact;
- exact engine and Python-source identities;
- parent V4.0 authentication and 143 immutable paths;
- complete dual-Python bridge replay and C++ method attestation;
- exact compression, connectivity and resource reconstruction;
- nested tamper rejection;
- provider-import AST screening;
- positive-rerun Streamlit acceptance with fail-fast provider, transpilation
  and seal spies;
- transactional deployment, rollback and exact-reapply tests.

Hash commitments establish integrity inside the release. They are not an
external signature. Provenance therefore remains
`UNSIGNED_SHA256_INTEGRITY_ONLY` unless a detached signature is anchored
outside the package.

## Claim and execution boundary

The admissible release state remains:

```text
research classification    RESEARCH_ONLY
provider SDK imported      false
provider credentials read  false
provider calls             0
backend transpilation      NOT_RUN
QPU submission enabled     false
QPU jobs submitted         0
hardware executable        false
optimization performance   NOT_TESTED
quantum advantage          NOT_CLAIMED
```

No UI control, credential, provider discovery, backend choice, transpilation
result, manual relabel, or post-observation candidate switch may override the
resource rejection or manufacture hardware readiness.

## Research context

The frozen specification records the following context sources:

- Cuccaro et al., *A new quantum ripple-carry addition circuit* (2004), for
  measurement-free ripple arithmetic;
- Barenco et al., *Elementary gates for quantum computation* (1995), for
  multi-controlled and two-level decomposition context; and
- Hadfield et al., *From the Quantum Approximate Optimization Algorithm to a
  Quantum Alternating Operator Ansatz* (2019), for constraint-preserving
  partial-mixer context.

These references motivate the registered abstract construction. They do not
substitute for backend-native compilation, device calibration, physical-error
analysis, or hardware execution.
