# Quantum Lab V4.2 · Indexed Coined-Walk Compiler

## Institutional decision

V4.2 is the append-only successor to the authenticated V4.1 release. It
resolves the registered architecture gate without rewriting the parent:

- joint promise support: **CONNECTED · 8 / 8 frozen seeds**;
- selected-model resource screen: **PASS · 8 / 8 frozen seeds**;
- worst complete-step numerator: **1,135,430 CNOT**;
- immutable budget: **2,500,000 CNOT**;
- minimum margin: **+1,364,570 CNOT**;
- research admission: **PROVIDER-NEUTRAL GENERATOR ADMITTED**; and
- circuit / backend / hardware: **NOT RUN / NOT RUN / FALSE**.

This is not hardware readiness and not an optimization or advantage claim.

## Why V4.1 could not be incrementally optimized

V4.1 evaluates each pair position with its own exact arithmetic path. Its R2
maximum is `15,663,936` CNOT. Exploratory V4.2 probes, disclosed before the
confirmatory artifact, found that a deterministic connected forest still used
hundreds of distinct global pair labels per seed (`375` to `490`), while six
seeded Hamiltonian label cycles left seed 3301 fragmented. Static label pruning
therefore did not approach the unchanged ceiling.

V4.2 changes the representation: pair identity becomes quantum address data,
so the expensive arithmetic is shared across the address family.

## Registered system

The data register contains 40 qubits at exact Hamming weight 10. Two persistent
40-qubit registers, `REMOVE_ADDRESS` and `ADD_ADDRESS`, each have Hamming weight
one. Their joint registered basis has `1,600` ordered address states.

One complete generator step contains:

1. a 40-edge cyclic excitation-preserving XY ring on `REMOVE_ADDRESS`;
2. the same ring on `ADD_ADDRESS`;
3. addressed reads of the two data bits;
4. construction of the addressed target portfolio;
5. one exact seven-band target-feasibility toggle;
6. an accepted addressed exchange;
7. symmetric target reconstruction and predicate clearing; and
8. the V4.1 data-only bridges in their authenticated order.

No pair position is removed after observing any result.

## Promise-subspace SELECT

On feasible data × one-hot coin inputs, SELECT is a disjoint union of exact
transpositions and identities:

- equal addresses are self loops;
- equal addressed bits are self loops;
- infeasible proposed targets are self loops; and
- opposite addressed bits with a feasible target are exchanged.

The target-feasible flag is retained through an accepted move. After the data
exchange, the two addressed-bit flags are updated, the move flag is cleared,
and the reverse target is reconstructed. Its feasibility is the original
feasible endpoint, so the predicate toggles cleanly to zero. Addressed-bit,
difference, move, target and arithmetic work registers return clean on the
registered promise subspace.

Off-promise behavior is not certified.

## Connectivity theorem

Each one-hot cyclic coin ring is connected. Their Cartesian product connects
all ordered address pairs for any fixed data state. At a fixed address pair,
SELECT exposes exactly the corresponding feasible one-swap edge. The three
authenticated V4.1 bridge transpositions act on data independently of coin.
Because the V4.1 augmented data graph is connected for every seed, the joint
promise graph is connected for every seed.

The exact ledger contains:

- `34,649,241,600` joint promise vertices;
- `69,973,909,206` registered joint support edges;
- all `780 / 780` pair positions; and
- all three authenticated V4.1 bridges.

## Independent small-domain control

The provider-free C++17 engine and an independent Python implementation exhaust
all nonempty feasible predicates on all exact-K domains for `2 ≤ N ≤ 5`.
They verify SELECT closure, involution, target-cleanup symmetry and equality of
data versus joint component counts. Complete exact-K domains through `N=8`
and Hamming-four bridge transpositions through `N=8` provide additional
controls.

Both implementations produce the same stable counts: `264,328` SELECT cases,
`264,328` cleanup cases, `2,218` arbitrary supports, `28` complete joint-domain
cases and `8,826` bridge cases, all with zero failures.

## Selected-model resource ledger

The frozen model uses:

- controlled constant add: `68w - 102` CNOT;
- ripple comparator: `16w - 9` CNOT;
- two-control X: `6` CNOT;
- `c`-control X for `c ≥ 3`: `6(2c - 3)` CNOT; and
- a data-only Hamming-four bridge at width 40: `3,600` CNOT.

The SELECT scaffold contains `562` CCX-equivalent operations and `326` direct
CNOT, including both coin rings, for `3,698` selected-model CNOT. One complete
step calls the full target-feasibility oracle twice. No cancellation between
registered macros is credited.

| Seed | Complete-step CNOT | Margin | Logical qubits | Bridges |
|---:|---:|---:|---:|---:|
| 1103 | 1,084,198 | +1,415,802 | 322 | 0 |
| 2207 | 1,087,798 | +1,412,202 | 323 | 1 |
| 3301 | 1,062,182 | +1,437,818 | 319 | 0 |
| 4409 | 1,062,182 | +1,437,818 | 320 | 0 |
| 5501 | 1,062,182 | +1,437,818 | 321 | 0 |
| 6607 | 1,084,198 | +1,415,802 | 323 | 0 |
| 7703 | 1,135,430 | +1,364,570 | 331 | 2 |
| 8807 | 1,106,214 | +1,393,786 | 326 | 0 |

The qubit figure is a logical allocation under sequential recycled workspace,
not a named-device capacity result.

## Evidence and validation

The sealed artifact authenticates the V4.1 specification, engine, compiler,
artifact, freeze contract and all 159 immutable V4.1 paths. Its portable C++
control contract excludes compiler and executable identities while retaining
the exact source hash, compile flags, clean-diagnostics requirement and stable
outputs. This allows byte-identical scientific JSON on macOS and Linux.

The release applies three non-substitutable layers:

- 16 artifact reconstruction checks;
- 35 independent scientific-validation checks; and
- 30 two-rerun Streamlit UI checks.

Nested boundary, selector, support and resource mutations are rejected even if
the top-level artifact hash is recomputed.

## Claim boundary

V4.2 establishes only exact promise-support structure and one provider-neutral
selected-model resource ledger. It does not establish:

- full-binary or off-promise cleanup;
- a materialized elementary circuit;
- independent reversible simulation of that circuit;
- native gate counts, topology mapping or routed depth;
- calibration, noise, error mitigation or runtime;
- optimization quality or economic utility;
- QPU execution; or
- quantum advantage.

The next falsifiable gate is
`INDEPENDENT_REVERSIBLE_SIMULATION_AND_BACKEND_AGNOSTIC_CIRCUIT_MATERIALIZATION`.

## Sources and context

The sealed specification registers Hadfield et al. on alternating-operator
mixers, Fuchs et al. on constrained mixers, Cuccaro et al. on ripple-carry
arithmetic and Barenco et al. on multi-controlled/two-level decompositions.
Those works provide design context; none substitutes for the frozen V4.2
evidence.
