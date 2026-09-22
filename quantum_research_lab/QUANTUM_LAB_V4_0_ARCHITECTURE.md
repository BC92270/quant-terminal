# Quantum Lab V4.0 · Exact Global Feasible-Graph Connectivity

## Institutional decision

Quantum Lab V4.0 closes the connectivity question deliberately left
`INDETERMINATE` by V3.9 for the eight frozen `N=40, K=10, BANDS` instances.
It enumerates the complete feasible state universe with exact integer
arithmetic, constructs every feasible one-out/one-in adjacency through
nine-element cores, and replays the complete computation with a structurally
different meet-in-the-middle partition.

The resulting decision is:

```text
V40_GLOBAL_CONNECTIVITY_COUNTEREXAMPLE_RESOURCE_REDESIGN_PREREGISTERED
```

Six seeds have one connected component. Seeds `2207` and `7703` are
disconnected. Together they contain three exactly feasible isolated vertices.
Because the evaluated graph already contains **all** feasible one-out/one-in
swaps, no reordering or sparse selection of that same move family can repair
those disconnections.

| Gate | Exact result | Boundary |
|---|---:|---|
| Frozen seeds completed | 8 / 8 | Both registered structural replays completed |
| Feasible vertices | 21,655,776 | Complete exact state universe across the eight seeds |
| Undirected feasible edges | 337,710,603 | Every Hamming-distance-two feasible pair |
| Nine-core incidences | 216,557,760 | Exact `10V` identity |
| Distinct nine-cores | 91,534,251 | Deterministic core index |
| Connected seeds | 6 / 8 | `1103, 3301, 4409, 5501, 6607, 8807` |
| Disconnected seeds | 2 / 8 | `2207, 7703` |
| Isolated components | 3 | One for `2207`, two for `7703` |
| Global all-seed gate | REJECTED | Counterexamples, not missing evidence |
| V3.9 resource architecture | REJECTED · preserved | 781,332,180 CNOT > 2,500,000 |
| V4.1 resource redesign | PREREGISTERED · NOT EVALUATED | No CNOT or budget-margin result exists |
| Backend / hardware | NOT RUN / BLOCKED | Zero provider calls and zero QPU jobs |

This is a counterexample to complete connectivity of the frozen one-swap
feasible graph. It is not a claim that constrained quantum optimization, a
larger move family, or quantum computing in general is impossible.

## Exact graph definition

For each frozen seed `s`, let the vertex set be

```text
V_s = {x in {0,1}^40 :
       popcount(x) = 10,
       every one of the four authenticated group bands is satisfied, and
       every one of the three authenticated exact-dyadic factor bands is satisfied}.
```

The seven coherent caches used by the V3.9 circuit are deterministic functions
of `x`. They are not additional graph coordinates and do not create duplicate
vertices.

For distinct `x,y in V_s`, the undirected edge relation is

```text
{x,y} in E_s  iff  popcount(x XOR y) = 2.
```

Equivalently, one selected asset is removed and one unselected asset is added.
The graph includes every such feasible move: it is not restricted by a device
topology, a heuristic edge sample, a sparse asset graph, or the static V3.9
row-overlap screen. Group and factor feasibility are evaluated with signed
128-bit integer arithmetic; no floating-point decision enters enumeration or
adjacency.

## Completeness theorem

The exact engine is `EXHAUSTIVE_GROUP_MITM_PLUS_NINE_CORE_DSU_V1`. Its
completeness rests on two finite combinatorial identities.

### Complete vertex enumeration

The four authenticated ten-asset groups form a disjoint partition of all
forty assets. For each group, the engine enumerates every local subset whose
cardinality lies inside that group's band. It then enumerates every four-way
product whose cardinalities sum to ten. Every group-valid exact-`K` portfolio
has one and only one such decomposition. Applying all three exact-dyadic factor
filters to that complete product therefore emits every member of `V_s`
exactly once and emits no nonmember.

The authenticated feasible witness for each seed must occur in the resulting
sorted vertex list. The list is committed as 40-bit masks encoded in unsigned
64-bit big-endian words.

### Complete edge and component construction

For a ten-element vertex `S` and each selected element `i in S`, define its
nine-core

```text
C_i(S) = S \ {i}.
```

Each vertex has exactly ten distinct nine-cores. Hence a complete vertex set of
size `V` must generate exactly

```text
10V
```

core incidences. Across V4.0, the observed value is
`216,557,760 = 10 x 21,655,776`.

For two distinct ten-subsets `S` and `T`:

```text
popcount(S XOR T) = 2
    iff
S and T contain one common nine-subset.
```

That common core is unique. Thus two feasible vertices are adjacent exactly
when they meet in one nine-core bucket. The engine inserts every incidence in
a deterministic core index and unions all vertices in a bucket with a
disjoint-set union structure. If a core has already appeared `m` times, its
next occurrence contributes exactly `m` new undirected edges; this counts the
clique induced by the core without materializing a quadratic adjacency list.

The DSU forest invariant is checked per seed:

```text
successful_unions + component_count = feasible_vertex_count.
```

It holds for all eight seeds. Summed over the family, there are `21,655,765`
successful unions and eleven connected components, exactly
`21,655,776 - 11`.

The nine-core equivalence was also exhaustively checked against explicit
Hamming-distance-two adjacency on bounded induced graphs before accepting the
`N=40` certificate.

## Dual structural replay

The confirmatory protocol requires two complete executions for every seed:

| Replay | MITM group split | First factor filter |
|---|---|---:|
| Primary | `[0,1] | [2,3]` | `FACTOR_1` |
| Structural replay | `[0,2] | [1,3]` | `FACTOR_2` |

The two executions take different enumeration paths and may inspect different
numbers of intermediate interval candidates. They must nevertheless reproduce
the same stable evidence: sorted feasible-set hash, vertex count, edge count,
nine-core index hash, union forest hash, component assignment hash, component
representatives and sizes, invariants, and authenticated witness.

All stable fields match for all eight seeds. Runtime and intermediate candidate
counts are diagnostics and are intentionally excluded from replay equality.
This is a deterministic structural replay plus an exact completeness argument;
it is not described as hardware replication or as an independently signed
external proof.

## Complete seed ledger

| Seed | Feasible vertices | Exact edges | Components | Component sizes | Decision |
|---:|---:|---:|---:|---|---|
| 1103 | 5,050,560 | 77,090,945 | 1 | 5,050,560 | CONNECTED |
| 2207 | 3,981,553 | 67,310,169 | 2 | 3,981,552 + 1 | DISCONNECTED |
| 3301 | 623,921 | 7,996,488 | 1 | 623,921 | CONNECTED |
| 4409 | 4,268,642 | 62,193,081 | 1 | 4,268,642 | CONNECTED |
| 5501 | 165,775 | 1,842,395 | 1 | 165,775 | CONNECTED |
| 6607 | 2,559,471 | 41,412,247 | 1 | 2,559,471 | CONNECTED |
| 7703 | 3,053,396 | 50,780,143 | 3 | 3,053,394 + 1 + 1 | DISCONNECTED |
| 8807 | 1,952,458 | 29,085,135 | 1 | 1,952,458 | CONNECTED |
| **Total** | **21,655,776** | **337,710,603** | **11** | — | **6 connected / 2 disconnected** |

The institutional all-seed gate passes only if every seed has exactly one
component under both complete replays. Six connected instances cannot offset
two counterexamples.

## Exact isolated counterexamples

Each isolated representative is first verified against the seven original
integer constraints. A separate direct audit then generates all
`K(N-K) = 10 x 30 = 300` possible one-out/one-in neighbors and records the
first constraint that rejects each neighbor. All 900 candidate neighbors of
the three representatives are infeasible.

### Seed 2207 · one isolated feasible vertex

```text
mask       = 08b4208484
indices    = [2, 7, 10, 15, 21, 26, 28, 29, 31, 35]
components = 3,981,552 + 1
neighbors  = 0 feasible / 300 audited
```

Its exact constraint values are:

| GROUP_1 | GROUP_2 | GROUP_3 | GROUP_4 | FACTOR_1 | FACTOR_2 | FACTOR_3 |
|---:|---:|---:|---:|---:|---:|---:|
| 2 | 4 | 2 | 2 | 45,401,068,155,318,150 | 23,060,240,033,275,816 | 53,966,679,905,698,000 |

The deterministic first-failure ledger assigns the 300 rejected neighbors as
`104 / 41 / 23 / 44 / 24 / 32 / 32` for
`FACTOR_1 / FACTOR_2 / FACTOR_3 / GROUP_1 / GROUP_2 / GROUP_3 / GROUP_4`.

```text
counterexample SHA-256 = b500e0ce920176aa347bc51468833469e8a632576c3ef82a79e020ddf956bfd8
neighbor ledger SHA-256 = 6790c04c33b8aa3bc17f8149039a65dcb6e420f84b01397a28a9b77f0526c73a
```

### Seed 7703 · two isolated feasible vertices

First isolated vertex:

```text
mask      = a8180000ec
indices   = [2, 3, 5, 6, 7, 27, 28, 35, 37, 39]
neighbors = 0 feasible / 300 audited
```

| GROUP_1 | GROUP_2 | GROUP_3 | GROUP_4 | FACTOR_1 | FACTOR_2 | FACTOR_3 |
|---:|---:|---:|---:|---:|---:|---:|
| 2 | 3 | 3 | 2 | 106,803,483,539,945,820 | 168,451,523,978,620,500 | 170,799,108,844,557,630 |

Its first-failure counts are `137 / 69 / 15 / 44 / 35 / 0 / 0` in the same
factor-then-group order.

```text
counterexample SHA-256 = ad12133a43812f9f0467753b66f319e546173a3adab01f9e91bebefbe01fef82
neighbor ledger SHA-256 = 36c438c153de4a900b98b2acf6f036bfc3b3332db57fae81ab2653407dc72c8d
```

Second isolated vertex:

```text
mask      = e2008a4082
indices   = [1, 7, 14, 17, 19, 23, 33, 37, 38, 39]
neighbors = 0 feasible / 300 audited
```

| GROUP_1 | GROUP_2 | GROUP_3 | GROUP_4 | FACTOR_1 | FACTOR_2 | FACTOR_3 |
|---:|---:|---:|---:|---:|---:|---:|
| 2 | 1 | 4 | 3 | 68,944,212,616,707,330 | 169,310,210,011,548,740 | 144,875,885,154,342,200 |

Its first-failure counts are `116 / 61 / 12 / 44 / 21 / 18 / 28`.

```text
counterexample SHA-256 = 20ad5996f62e63406902a13ab5b2cee398083cbd245a1b48b8a5ae9f582a9499
neighbor ledger SHA-256 = 7f6bb1c0153a7d1252ab1c5f49ee5f2b34afac32b4e9e12018a6818923b900d1
```

The three singleton components are sufficient counterexamples on their own;
the complete enumeration and DSU certificate additionally establish the
component structure of every other feasible vertex.

## V3.9 resource result remains frozen

V4.0 does not alter, reinterpret, average, or replace the V3.9 resource
numerator:

```text
selected model maximum = 781,332,180 CNOT
registered ceiling     =   2,500,000 CNOT
minimum margin         = -778,832,180 CNOT
decision               = REJECTED_SELECTED_MODEL_CNOT_BUDGET
```

That result rejects the exact V3.9 clean-ancilla arithmetic architecture. The
new V4.0 connectivity counterexample independently rejects its all-one-swap
global connectivity assumption for two seeds. Neither result establishes a
global lower bound for every possible mixer or reversible compiler.

## V4.1 preregistration · no resource result yet

V4.0 records, but does not execute, the successor architecture
`EXACT_COMPRESSED_UNSIGNED_SLACK_LINEAR_ARITHMETIC_WITH_CERTIFIED_BRIDGES_V1`.
The registration occurred after the V3.9 rejection and after disclosure of
the exploratory V4.0 signal, but before any V4.1 resource ledger.

Two candidates must be published without silent winner selection:

1. `R1_LINEAR_SLACK_ALL_ONE_SWAP` retains every feasible Hamming-distance-two
   swap. Its complete-connectivity correctness gate cannot pass on the frozen
   family because of the V4.0 counterexamples; no V4.1 CNOT ledger has been
   evaluated.
2. `R2_LINEAR_SLACK_ONE_SWAP_PLUS_TWO_SWAP_BRIDGES` may add exact-feasible
   Hamming-distance-four moves. The registered bridge rule selects the
   lexicographically earliest component bridges under deterministic Kruskal
   ordering and then requires complete connectivity recertification.

The preregistered resource design also requires exact threshold-margin
certificates before any power-of-two coefficient compression, original versus
compressed predicate parity over the complete exact-`K` group-valid universe,
unsigned slack caches `S=A-L`, measurement-free ripple arithmetic,
forward/inverse equivalence, clean scratch, coherent pair action, and an
independent selected-model resource replay.

The elementary decomposition model must be fixed in V4.1 before the first
ledger. Coherent cache preparation is reported separately and remains outside
the one-complete-layer numerator. At V4.0 closure:

```text
V4.1 status        = RESOURCE_ARCHITECTURE_PREREGISTERED_NOT_EVALUATED
CNOT               = NOT_EVALUATED
budget margin      = NOT_COMPUTED
projected cost     = PROHIBITED
hardware readiness = NOT ESTABLISHED
```

## Evidence chronology

1. V3.9 authenticated the eight-seed reversible IR, rejected its selected
   resource model, and left global connectivity indeterminate.
2. An unsealed engineering run of the exact nine-core engine exposed candidate
   isolated portfolios for seeds `2207` and `7703`. This exploratory signal was
   disclosed and was not accepted as confirmatory evidence.
3. The confirmatory protocol, engine identity, dual MITM partitions, equality
   fields, direct-neighbor audit, stop policy, and decision branches were
   sealed at `2026-09-10T20:00:00Z`.
4. Both complete registered replays then ran for all eight seeds. The protocol
   did not stop after the first counterexample.
5. Matching stable evidence and three direct 300-neighbor audits produced the
   sealed V4.0 counterexample decision.
6. The V4.1 redesign remains a preregistration only. Its arithmetic,
   decomposition, connectivity after bridges, CNOT numerator, and budget gate
   have not been evaluated.

This chronology prevents exploratory observations from being relabeled as
confirmatory results and prevents a future favorable resource number from
being inserted retrospectively into V4.0.

## Artifact identities

```text
V4.0 canonical spec SHA-256       3ab75513efc7014157ef74633ef5c4d9bd4f23b22390f341dbfd033cb8a9694e
V4.0 raw spec file SHA-256        c86e73ebc4e7852407972dfcab89000e68dbeac4e9d635093a31eadc835109e2
V4.0 engine raw SHA-256           16cdfffe8dde853f534349d0531f52c4026271f6f03de53ade77af4ec6726944
V4.0 Python source SHA-256        4ad9704cf4007a447195c6c9544ba38caa02316c32c1c0d7032b6a0cb6755afc
graph definition SHA-256          965a0e06fd64170c01466aefcbf488b1b0c3d0f84c94538deda1ce49c43bb614
counterexample bundle SHA-256     21c543be40fe0811b001c459391b2774ae431e554aea190a0aa08a0d8227d232
sealed artifact SHA-256           0fbbddcdf73dde6708814521cc3df741acb53c079e25b6c8829965de56778f01
```

The artifact is located at
`outputs/quantum_phase3/v40_connectivity/SEALED_V4_0_GLOBAL_CONNECTIVITY_ARTIFACT.json`.
Its hashes provide integrity commitments inside this release; they are not a
detached external signature.

## Scientific boundary

V4.0 is `RESEARCH_ONLY` and provider-free.

| Field | Frozen value |
|---|---|
| Provider SDK imported | `false` |
| Provider credentials read | `false` |
| Provider calls | `0` |
| Backend transpilation | `NOT_RUN` |
| QPU submission enabled | `false` |
| QPU jobs submitted | `0` |
| Hardware executable | `false` |
| Optimization performance | `NOT_TESTED` |
| Quantum advantage | `NOT_CLAIMED` |
| V4.1 resource redesign | `PREREGISTERED_NOT_EVALUATED` |

Exact classical enumeration and graph certification do not establish native
device routability, calibrated fidelity, state preparation, useful
optimization performance, or quantum advantage.

## Primary research context

These sources motivate the design space; none is treated as evidence for the
instance-specific V4.0 counts or as a substitute for the sealed computation.

- Hadfield et al., [*From the Quantum Approximate Optimization Algorithm to a
  Quantum Alternating Operator Ansatz*](https://arxiv.org/abs/1709.03489),
  provides the hard-constraint alternating-operator and feasible-subspace
  mixer context.
- Fuchs et al., [*Constrained mixers for the quantum approximate optimization
  algorithm*](https://arxiv.org/abs/2203.06095), develops constrained-subspace
  mixers and CX-cost-aware decompositions.
- Cuccaro et al., [*A new quantum ripple-carry addition
  circuit*](https://arxiv.org/abs/quant-ph/0410184), is the primary context for
  the future measurement-free linear-depth arithmetic lane. It is not an
  evaluated V4.0 circuit.
- Wołk, Capała and Rycerz, [*Design and Analysis of an Improved Constrained
  Hypercube Mixer in Quantum Approximate Optimization
  Algorithm*](https://arxiv.org/abs/2603.05187), motivates the preregistered
  precomputed-linear-function cache direction. It is a 2026 preprint and does
  not validate the V4.1 candidate or its unevaluated resource gate.

## Next falsifiable gate

```text
AUGMENTED_1_2_EXCHANGE_GRAPH_CONNECTIVITY_OR_COUNTEREXAMPLE
```

The next admissible positive claim requires exact Hamming-distance-four bridge
selection, complete recertification of the augmented graph on all eight frozen
seeds, a frozen measurement-free elementary decomposition, coherent cleanup,
and an independently replayed maximum CNOT ledger. Until those gates are
executed, V4.1 remains `NOT_EVALUATED` and every provider or hardware control
must remain closed.
