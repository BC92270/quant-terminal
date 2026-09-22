# Quantum Lab V3.8 — Elementary Decomposition & N=40 Admission

## Decision

`ELEMENTARY_PROTOTYPE_PASSED_N40_ADMISSION_BLOCKED`

V3.8 closes the elementary-basis gap for the authenticated V3.7 synthetic
`N=4, K=2` operator. It does not close the production `N=40` compiler gap.

The bounded positive result is:

- all 40 V3.7 signed-pattern logical primitives are deterministically lowered;
- the provider-neutral elementary basis is `X, H, T, TDG, RY, RZ, CX`;
- the selected model emits exactly 5,920 one-qubit gates and 3,632 CNOT;
- peak clean-ancilla allocation is 8, for 18 logical qubits in total;
- 49,152 full-domain primitive/beta cases pass;
- maximum action residual is approximately `4.05e-15`;
- maximum norm residual is approximately `8.00e-15`;
- all allocated auxiliaries return to `|0>` in every checked case.

The production result is:

- 8/8 frozen `N=40, K=10, BANDS` seed identities authenticate;
- 8/8 parent rows carry seven-constraint classical delta equivalence;
- 0/8 seeds have a V3.8 scalable reversible arithmetic/cache-update IR;
- 0/8 have elementary lowering, coherent cleanup, ordered-layer connectivity,
  or a selected-model CNOT ledger;
- therefore the internal 2,500,000-CNOT gate is `NOT_EVALUATED` and N=40
  admission is `BLOCKED_INCOMPLETE_REVERSIBLE_IR`.

No missing N=40 numerator is replaced by a prototype projection or by the
historical V3.4 cost. The frozen V3.4/V3.6 rejection remains visible, authentic,
and explicitly non-comparable to the V3.8 selected model.

## Frozen decomposition model

The preregistered model is
`CLEAN_ANCILLA_TOFFOLI_LADDER_6CX_CCX_CRX2CX_V1`.

For a positive-control `MCX` with `m >= 3` controls, V3.8 computes the AND of
the first `m-1` controls into `m-2` clean auxiliaries, applies one Toffoli to
the target, then reverses the compute ladder. This uses `2m-3` exact Toffolis.

For a positive-control `MCRX` with `m >= 2` controls, it computes the AND of all
controls into `m-1` clean auxiliaries, applies one controlled-RX, then reverses
the ladder. This uses `2(m-1)` exact Toffolis plus one controlled-RX.

Signed zero-controls are normalized with Pauli-X immediately before and after
each logical primitive. No cross-primitive cancellation is booked. The CNOT
depth convention is the conservative serial emission order, so selected-model
CNOT depth equals the selected-model CNOT count. Connectivity is an abstract
all-to-all logical model, not a device topology.

### Exact templates

The Toffoli template uses 6 CX and 9 one-qubit Clifford+T gates. It is checked
against the exact CCX action on all eight basis columns.

The controlled-RX template uses 2 CX and four one-qubit rotations:

`RZ(pi/2) · RY(theta/2) · CX · RY(-theta/2) · CX · RZ(-pi/2)`

It is checked on all four basis columns at all three registered beta values.
The wider AND ladders are then checked as complete signed-pattern blocks.

This construction is consistent with the universal one-qubit-plus-XOR gate
framework and generalized controlled-gate decompositions developed by Barenco
et al., *Elementary gates for quantum computation*, Physical Review A 52,
3457 (1995), DOI `10.1103/PhysRevA.52.3457`.

## Why the composition proof is exhaustive

The V3.8 verifier checks each of the 36 `PATTERN_MCX` occurrences on all 1,024
data-register basis states and each of the four `PATTERN_MCRX` occurrences on
all 1,024 states at three beta values. Each check compares the complete
elementary block to the corresponding authenticated V3.7 logical primitive and
also inspects every output basis address for non-zero auxiliary bits.

Because every block is equal on a complete computational basis and returns its
auxiliaries to the same clean state, equality is preserved by ordered
composition. V3.7's independently authenticated exhaustive complete-layer
action, adjoint, norm, support, connectivity, and full Gram proofs remain the
logical reference. V3.8 adds an exact elementary refinement; it does not rewrite
or weaken that predecessor evidence.

## Resource attribution

| Component | Occurrences | CNOT per occurrence | Selected-model subtotal |
|---|---:|---:|---:|
| Signed `PATTERN_MCX` | 36 | 90 | 3,240 |
| Signed `PATTERN_MCRX` | 4 | 98 | 392 |
| **Complete ordered layer** | **40** | — | **3,632** |

The corresponding one-qubit totals are 468 X, 1,208 H, 2,416 T, 1,812 TDG,
8 RY, and 8 RZ, for 5,920 one-qubit gates. These are exact counts for the frozen
emission model, not minimality claims.

## N=40 admission matrix

Production admission requires every item below on every frozen seed:

1. authenticated V3.7/V3.6 lineage;
2. authenticated seven-constraint register contract;
3. scalable reversible arithmetic and cache-update IR;
4. elementary lowering;
5. full coherent equivalence and clean uncompute;
6. ordered-layer connectivity evidence;
7. selected-model CNOT ledger;
8. maximum CNOT no greater than 2,500,000;
9. no post-observation model or topology switching.

V3.8 passes items 1 and 2 and preserves the classical delta audit. It does not
pass items 3–8. Under the preregistered missing-evidence policy this is a block,
not a favorable estimate and not a global impossibility claim.

## Claim boundary

V3.8 is `RESEARCH_ONLY` and provider-free. It imports no provider SDK, reads no
credential, makes zero provider calls, runs no named-backend transpilation,
enables no QPU submission, and submits zero QPU jobs. `hardware_executable` is
false. Optimization performance and quantum advantage are not claimed.

## Next falsifiable gate

`SCALABLE_N40_REVERSIBLE_ARITHMETIC_IR_AND_EIGHT_SEED_EQUIVALENCE`

The successor must construct, rather than project, the seven-constraint N=40
register update on all eight frozen seeds. Only then can the same frozen
elementary model produce a comparable N=40 CNOT numerator for the 2.5M gate.
