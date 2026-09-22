# Quantum Research Lab V3.3 — Exact Feasible-Subspace Mixer Contract

## Executive decision

V3.3 closes the algorithmic gap left intentionally open by V3.2: the seven
exact dyadic BANDS constraints are now preserved by a named, ordered mixer
construction. The result is deliberately narrower than “QPU ready”.

- Feasible-subspace invariance relative to the frozen V3.2 predicate: **PASS**.
- Cached and transient guard cleanup: **PASS**.
- Ring topology as an exploration mixer: **REJECTED** because the authenticated
  seed-5501 witness is isolated.
- Complete-swap witness local reachability: **PASS, local evidence only**.
- Complete feasible-graph connectivity / ergodicity: **INDETERMINATE**.
- Controlled-XY native synthesis and backend routing: **NOT RUN**.
- Hardware execution: **BLOCKED; zero jobs**.
- Optimization performance and quantum advantage: **NOT TESTED / NOT CLAIMED**.

This separation is the core institutional property of the release. A green
invariance result cannot promote connectivity, engineering readiness or
performance.

## Immutable lineage

V3.3 is additive. It does not modify the V3.1 logical oracle, the V3.2 gate
compiler, their specifications or their sealed artifacts.

| Object | Identity |
|---|---|
| V3.1 raw parent | `7b39a20ec9200b16996ec25edd660ba7bf26bfb2b454ed44dd1a333513afd50e` |
| V3.1 dyadic oracle | `D9D109D117E1795CFFEF` |
| V3.2 raw compiler artifact | `616cc12808465916dfcfcde6c8e2c9feed1be4b294ad034f29cb7cb36704031b` |
| V3.2 semantic artifact | `5e6cc7e53f15921f7cbd22ef66f04878b37d54372e04b5bf49f5bb4854050fcd` |
| V3.2 validation manifest | `bde0dc2e90a355821c8678d2df8ac743820c0a4d2e83701aeeeaab3e1d8e9b91` |
| V3.3 preregistered spec | `5119490433952D6A4A61` / `5119490433952d6a4a6151a2890b647479460e3cda4283bf1bc541243d1a8e3e` |
| V3.3 algorithm source | `309a262415ba5f9017c8185c1a3b98fabbbd57c6a2ec5559eec904df44d02ec8` |
| V3.3 validation source | `dba6549d4831f0b5cffeca9dbd4cc741751136df0535abb52ef1b5f7f6547393` |
| V3.3 deployed-chain verifier source | `3f23095e4619127760fde37c7d811f841618e86a4ca27e993518bf31f58d46be` |
| V3.3 semantic artifact | `5ecd1fd5e3f093934220691e20139eff5c12757c2cf70bbfe6f89c2bc26b958a` |
| V3.3 raw artifact file | `af04ddd8986d59cc18ba33f756b24ade93ef005ff0b0df14d88d4c52d537b565` |
| V3.3 validation manifest | `7461299442dda626986ac448c1e7ed4cbb20bdd5a4d4c27fc60a7d96deb9285e` |
| V3.3 resource manifest | `437d9370d0a7b37aac30094b8ebf4c5db97d84abd7cfc633267a22b52eadf8a6` |

The V3.3 specification discloses that exploratory degree counts were observed
before the canonical rerun. The canonical evaluation is therefore not
described as blind confirmatory evidence.

## Algorithmic object

For seed `s`, let `f_s(x)` be the frozen V3.2 exact-K BANDS predicate on

`D_K = {x in {0,1}^40 : popcount(x)=10}`.

Let `S_e` swap bits `i,j` for edge `e=(i,j)`. The controlled XY rotation uses

`XY_e = (X_i X_j + Y_i Y_j)/2`

and rotates only the `|01>` / `|10>` pair. One canonical mixer layer is an
ordered product of partial mixers; it is not represented as an exact
exponential of an unordered sum of noncommuting terms.

The full alternating contract is:

1. prepare the authenticated feasible computational-basis witness;
2. apply the frozen diagonal Phase-II economic objective separator;
3. apply the ordered guarded mixer layer;
4. repeat for a declared depth and parameter sequence.

The diagonal cost separator preserves computational-basis support. The mixer
proof below therefore gives feasibility invariance to the whole alternating
contract, but says nothing about convergence or solution quality.

## Canonical cached dual-guard construction

The institutional reference profile is `DUAL_GUARD_CACHED`.

1. At layer entry, compute `a = f(x)` once with `U_f`.
2. For edge `e`, compute `b = f(S_e x)` with `U_(f o S_e)`.
3. Apply `C2-XY_e(beta_e)` only if `a=b=1`.
4. Uncompute `b` with the same neighbor oracle.
5. Repeat steps 2–4 for every ordered edge while retaining `a`.
6. Uncompute `a` with `U_f` at layer exit.

`U_(f o S_e)` is obtained by a bijective relabelling of data wires in the
provider-neutral V3.2 oracle. It preserves abstract gate counts and dependency
depth. No physical SWAP belongs to the canonical logical IR. Whether routing
can realize that relabelling efficiently is intentionally deferred.

### Inductive invariant and cleanup proof

At each edge boundary:

- every V3.2 work register is clean;
- the transient neighbor flag `b` is clean;
- the retained flag satisfies `a=f(x)` on every basis branch.

If `a=0`, the controlled rotation is disabled, so the branch is unchanged and
`a=f(x)=0` remains true. If `a=1`, a transition is enabled only when
`b=f(S_e x)=1`; both endpoints are therefore feasible. On the rotated branch
`S_e x`, evaluating the neighbor predicate again gives
`f(S_e S_e x)=f(x)=1`, so `b` uncomputes. The unchanged component likewise
uncomputes with `f(S_e x)=1`. Thus the invariant holds after every edge. At
layer exit `U_f` clears `a` because it still equals the predicate of every
current branch.

| `f(x)` | `f(Sx)` | Different bits | C2-XY active | Dual-guard result |
|---:|---:|---:|---:|---|
| 0 | 0 | 1 | No | State frozen; both guards clean |
| 0 | 1 | 1 | No | State frozen by `a`; both guards clean |
| 1 | 0 | 1 | No | Neighbor rejected by `b`; both guards clean |
| 1 | 1 | 1 | Yes | Rotation stays between feasible endpoints; both guards clean |
| 0 or 1 | same | 0 | No | XY annihilates `00/11`; guards clean |

The research-only `FEASIBLE_SUPPORT_OPTIMIZED` profile removes `a` and uses two
oracle calls per edge. It is clean only when the input support is already
entirely feasible. V3.3 retains an explicit dirty-ancilla counterexample
outside that precondition, so this profile cannot silently replace the
institutional reference.

## Validation ladder

All eight canonical V3.3 gates passed:

1. `A_PARENT_CHAIN`: revalidated V3.1 and the complete 12-gate V3.2 release
   chain, including live compiler source/spec identities.
2. `B_SPEC_SELF_HASH`: recomputed the preregistered specification digest.
3. `C_GUARD_SYMBOLIC`: enumerated 20 Boolean/orientation cases for both guard
   profiles and retained the optimized profile’s out-of-contract failure.
4. `D_SMALL_N_EXHAUSTIVE_UNITARY`: tested 1,800 edge actions for an N=6,
   K=3 constrained predicate; full-layer Gram and norm errors were at most
   `2.220446049250313e-16`.
5. `E_N40_WITNESS_GRAPH`: tested all 300 nontrivial one-swap candidates for
   each of eight authenticated witnesses using both direct predicate evaluation
   and an independent exact-integer delta method.
6. `F_RESOURCE_REPRODUCIBILITY`: two independent resource passes produced the
   same manifest.
7. `G_NEGATIVE_RESULTS_RETAINED`: ring rejection and global-connectivity
   indeterminacy are first-class results, not hidden failures.
8. `H_HARDWARE_FAIL_CLOSED`: synthesis, transpilation and QPU states remain
   `NOT_RUN` / false.

The independent deployed-chain verifier adds 13 release controls, including
live byte-for-byte authentication of the algorithm, validation and verifier
sources. Missing parents return a negative report instead of crashing.

### N=40 graph evidence

| Seed | Ring degree | Complete degree | Reachable in at most 2 complete swaps |
|---:|---:|---:|---:|
| 1103 | 4 | 65 | 1,204 |
| 2207 | 3 | 53 | 969 |
| 3301 | 2 | 50 | 746 |
| 4409 | 2 | 55 | 941 |
| 5501 | **0** | 31 | 302 |
| 6607 | 7 | 59 | 1,047 |
| 7703 | 3 | 61 | 1,151 |
| 8807 | 4 | 55 | 790 |

Forward and reverse edge traversal produced identical exact two-hop state sets
for every seed. These are component-size lower bounds, not total feasible-set
counts. The ring failure is conclusive for the named witness; the complete
topology evidence remains local.

## Resource falsification

For `E` ordered edges, the cached dual-guard layer uses:

- `2E+2` frozen V3.2 oracle invocations;
- `E` algorithmic `C2-XY` primitives;
- one additional retained guard qubit beyond the V3.2 exact-K oracle width;
- zero physical SWAPs in the canonical provider-neutral wire model.

| Topology | Edges | Oracle calls | Logical qubits max | Provider-neutral gates max | Provider-neutral depth max | Oracle-path T subtotal max |
|---|---:|---:|---:|---:|---:|---:|
| Ring control | 40 | 82 | 120 | 35,118,426 | 33,005,204 | 9,160,201,960 |
| Complete canonical | 780 | 1,562 | 120 | 668,963,206 | 628,708,904 | 174,490,676,360 |

The gate and depth columns count each `C2-XY` as one algorithmic IR primitive.
Its native discrete synthesis cost is not estimated. The T column is only the
sum of frozen-oracle upper estimates; it is not a complete mixer upper bound.
An explicit `SWAP-U_f-SWAP` fallback would add twelve CX per edge, reaching
668,972,566 known operations for the complete layer before C2-XY synthesis.

The complete reference layer is therefore rejected as NISQ-practical in its
current form. This is a resource falsification of the named construction, not
an impossibility theorem for arithmetic optimization, alternative encodings,
logical-X mixers, block decompositions or future fault-tolerant systems.

## Literature alignment

The contract follows the feasible-subspace and ordered-partial-mixer design
principles of Hadfield et al.,
[arXiv:1709.03489](https://arxiv.org/abs/1709.03489), and the explicit
subspace/decomposition focus of Fuchs et al.,
[arXiv:2203.06095](https://arxiv.org/abs/2203.06095). These references motivate
the architecture; they do not validate this project’s implementation or its
N=40 graph.

## Roadmap change control

The V3.2 specification had tentatively named backend-native lowering as V3.3.
That work is now explicitly moved to V3.4. The reason is scientific ordering:
routing a circuit before proving that its algorithm preserves all seven hard
constraints would validate the wrong object. V3.3 does not claim that the old
backend milestone was completed.

V3.4 may begin only with:

1. a frozen native decomposition and precision target for `C2-XY`;
2. arithmetic/oracle optimization with semantic equivalence proofs;
3. a named backend and timestamped calibration snapshot;
4. complete routed resource and error-budget rejection criteria;
5. continued `hardware_executable=false` until every independent gate passes.

## Reproduction

```bash
python -m quantum_research_lab.phase3_algorithmic_validation \
  SEALED_EXACT_DYADIC_BANDS_ORACLE.json \
  outputs/quantum_phase3/gate_compiler/SEALED_GATE_COMPILER_ARTIFACT.json \
  --output outputs/quantum_phase3/algorithmic_contract/SEALED_FEASIBLE_SUBSPACE_MIXER_ARTIFACT.json

python -m quantum_research_lab.verify_phase3_v33 \
  SEALED_EXACT_DYADIC_BANDS_ORACLE.json \
  outputs/quantum_phase3/gate_compiler/SEALED_GATE_COMPILER_ARTIFACT.json \
  outputs/quantum_phase3/algorithmic_contract/SEALED_FEASIBLE_SUBSPACE_MIXER_ARTIFACT.json

python -m unittest \
  quantum_research_lab.test_phase3_gate_compiler \
  quantum_research_lab.test_phase3_algorithmic_contract -v

python -m quantum_research_lab.verify_phase3_v33_ui app.py --timeout 90

python -m quantum_research_lab.verify_freeze_contract_v33 . \
  --contract FREEZE_CONTRACT_V3_3.json
```
