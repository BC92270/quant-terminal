# Quantum Lab V3.9 · Scalable N40 Reversible IR & Resource Screen

## Institutional decision

V3.9 authenticates the immutable V3.8 → V3.1 lineage, compiles all eight
frozen `N=40, K=10, BANDS` instances to one deterministic provider-neutral
reversible macro IR, and evaluates the selected-model CNOT gate that V3.8 had
left `NOT_EVALUATED`.

| Gate | Result | Exact boundary |
|---|---|---|
| Parent chain | PASS | V3.8 artifact/spec/source/freeze and V3.1 dyadic artifact pinned by raw and semantic identity |
| Scalable reversible IR | PASS · 8/8 | exact-K feasible support with coherent exact caches |
| Ordered layer | PASS · 6,240/6,240 | 780 lexicographic positions per seed; identity records retained |
| Elementary selected-model ledger | PASS · 8/8 | V3.8 clean-ladder/6-CX-CCX/2-CX-CRX model |
| 2,500,000 CNOT gate | REJECTED | maximum complete-layer count = 781,332,180 |
| Complete feasible-graph connectivity | INDETERMINATE | no exhaustive graph proof or counterexample |
| Backend / hardware | NOT RUN / BLOCKED | zero provider calls and zero jobs |

The overall decision is
`N40_REVERSIBLE_IR_PASSED_RESOURCE_SCREEN_REJECTED`. It rejects this frozen
architecture, not reversible arithmetic or constrained quantum optimization in
general.

## Declared semantic domain

For every seed, the coherent input support is

```text
popcount(x) = 10
A_r = sum_k c[r,k] x_k for all seven exact integer rows r
L_r <= A_r <= U_r for all r
scratch = |0...0>
```

The four group rows use 4-bit unsigned caches. The three factor rows use the
60–68-bit signed-complement widths authenticated in the exact dyadic V3.1
certificate. Cache registers are caller-owned correlated data: they change
with the portfolio. Only temporary difference, comparator, flag, aggregate and
decomposition placements must return to zero.

The allowed positive statement is
`FEASIBLE_SUPPORT_COHERENT_EQUIVALENCE_PROVEN_BY_CONSTRUCTION`.
`FULL_BINARY_OPERATOR_EQUIVALENCE` is not claimed.

## Canonical edge construction

For each edge `e=(i,j)`, `i<j`, define the orientation `o=x_i` on the
different-bit subspace and compute `d=x_i XOR x_j` into clean scratch. For row
`r`, let

```text
delta_r = c[r,i] - c[r,j].
```

The two portfolio endpoints carry caches that differ by exactly `delta_r`.
V3.9 chooses a canonical endpoint `q_r in {0,1}` independently per row. The
choice minimizes the exact frozen-model normalization CNOT count, then the 1Q
count, with `q_r=1` as the final deterministic tie-break. This rule is sealed
before the eight ledgers are evaluated.

The cache transformation is

```text
B_r = A_o + (q_r - o) delta_r.
```

Operationally:

- `q_r=0`: add `-delta_r` under `d=1 AND x_i=1`;
- `q_r=1`: add `+delta_r` under `d=1 AND x_i=0`.

The explicit `d` control is mandatory. A negative `x_i` control alone would
corrupt equal-bit states `00/11`.

After canonicalization, define `s_r=1-2q_r`. Both endpoints satisfy row `r`
exactly when

```text
B_r in [ max(L_r, L_r - s_r delta_r),
         min(U_r, U_r - s_r delta_r) ].
```

The aggregate guard is `d AND` all nontrivial row intervals. Rows with
`delta_r=0` need no guard because the endpoint value is unchanged. A bound is
removed only if the exact conditional reachable range proves it identically
true.

## Exact-K conditional range certificate

For canonical orientation `q_r`, one of `i,j` is selected and the other is not.
The remaining selection has size `K-1=9` among 38 coefficients. Consequently
the exact reachable endpoints are

```text
selected canonical coefficient
+ sum of the 9 smallest / largest coefficients among the other 38.
```

This is a proof over the complete exact-K domain, not a sample. A position is
statically dead only when at least one row has an empty intersection between
this reachable interval and its symmetric feasible interval. Dead positions
remain in the ordered layer as hashed `CERTIFIED_IDENTITY_POSITION` records.

## Reversible schedule and uncompute order

Every live position follows this fixed order:

```text
compute d
→ normalize every nonzero-delta cache
→ compute exact interval flags and aggregate guard
→ CNOT Gray conjugation
→ aggregate-controlled RX(2 beta)
→ inverse CNOT Gray conjugation
→ uncompute aggregate, flags and comparators while caches remain normalized
→ denormalize caches using the new x_i orientation
→ clear d from the restored portfolio pair
```

The guard must be uncomputed before denormalization. Reversing those two steps
would make the inverse comparator read a different cache value and invalidate
cleanup.

## Elementary accounting

The selected model is inherited without switching from V3.8:

- `CCX_CLIFFORD_T_6CX_V1`: 6 CX and 9 one-qubit gates;
- clean-ancilla `m`-control ladder: `2m-3` CCX for `m>=3`;
- negative controls: paired X wrappers around each abstract gate;
- controlled `RX`: 2 CX and 4 one-qubit gates;
- abstract all-to-all logical connectivity; and
- no cancellation between macros or edge positions.

A length-`l` increment controlled by the two-pattern condition has controls
`2..l+1`. Under the selected ladder this is exactly `l²` Toffoli equivalents,
or `6l²` CNOT. The implementation uses this closed form and independently
replays every seed from its canonical macro records. Backend routing can only
increase or transform this provider-neutral count and is not run after the
screen rejects.

## Frozen results

| Seed | Cache widths G1/G2/G3/G4/F1/F2/F3 | Dead | Live | Selected-model CNOT | Margin vs 2.5M |
|---:|---|---:|---:|---:|---:|
| 1103 | 4/4/4/4/61/64/63 | 273 | 507 | 725,326,700 | -722,826,700 |
| 2207 | 4/4/4/4/60/62/63 | 229 | 551 | 781,332,180 | -778,832,180 |
| 3301 | 4/4/4/4/63/61/61 | 266 | 514 | 722,838,840 | -720,338,840 |
| 4409 | 4/4/4/4/63/64/62 | 270 | 510 | 722,438,876 | -719,938,876 |
| 5501 | 4/4/4/4/65/64/62 | 245 | 535 | 774,993,824 | -772,493,824 |
| 6607 | 4/4/4/4/64/68/64 | 254 | 526 | 767,893,060 | -765,393,060 |
| 7703 | 4/4/4/4/63/61/61 | 234 | 546 | 775,257,268 | -772,757,268 |
| 8807 | 4/4/4/4/62/62/64 | 249 | 531 | 760,588,844 | -758,088,844 |

The width envelope is 241–252 data-plus-cache qubits and 314–330 logical
qubits when reusable scratch and the selected clean-decomposition ancilla peak
are included. These are logical-model quantities, not native device widths.

## Validation ladder

The release requires all of the following:

1. raw, semantic and nested V3.8 → V3.1 authentication;
2. exhaustive two-pattern controlled addition for widths 1–6, both canonical
   orientations, forward and inverse;
3. exhaustive signed and unsigned inclusive comparators for widths 1–6;
4. exhaustive small-width cache canonicalization/inverse;
5. exhaustive symmetric-interval identity over a bounded integer grid;
6. controlled-RX two-level action on all basis columns for three registered
   beta controls;
7. exact eight-seed cache widths and seed order;
8. all 6,240 positions, 43,680 row cases and dead/live certificates;
9. unique edge hashes and an ordered hash chain per seed;
10. a second independent compilation of all eight seed objects;
11. maximum—not mean—resource admission;
12. explicit retention of connectivity, provider, hardware and advantage
    boundaries; and
13. nested tamper, missing-seed, duplicate-seed, order and budget-decision
    rejection tests.

## Research context

The construction is consistent with the hard-constraint alternating-operator
design context of Hadfield et al. and the elementary multi-control context of
Barenco et al. Cuccaro ripple-carry arithmetic is retained as a preregistered
successor research direction, not retroactively substituted for the V3.9
selected adder.

## Next falsifiable gates

The unchanged logical next gate is
`GLOBAL_FEASIBLE_GRAPH_CONNECTIVITY_OR_COUNTEREXAMPLE`. Because the selected
resource screen already rejects, any attempt to reduce cost must first seal a
new arithmetic/decomposition architecture and its comparison contract. No
V3.9 observation may be used to switch its registered model post hoc.
