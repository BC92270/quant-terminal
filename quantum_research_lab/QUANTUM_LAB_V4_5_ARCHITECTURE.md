# Quantum Lab V4.5 — Proof-carrying width reduction

## Institutional status

V4.5 is an append-only, `RESEARCH_ONLY` successor to the exact V4.4 release. It addresses one and only one rejected gate: the V4.3 circuit family requires 327–339 logical wires while the frozen offline `FakeMarrakesh` structural target exposes 156 qubits. V4.5 changes the reversible compiler architecture before any target transpilation.

An admitted V4.5 result proves neither QPU execution nor current hardware compatibility. It only admits a width-reduced, provider-neutral circuit manifest to the next offline reconstruction/translation/routing gate. Provider calls, credential reads, network calls and submitted jobs remain exactly zero; `hardware_executable=false`; calibration-aware fidelity, runtime performance and quantum advantage remain untested or unclaimed.

## Immutable ancestry

The compiler authenticates the exact V4.4 freeze before producing evidence:

- semantic freeze: `e17aa8ce04c97416f7f0565f2eda4f16b739c5c921fb58ee25752a546ffe95b3`;
- raw freeze file: `f7b4507410aee41e409b3a0a1ce36ba1adff38299dc8a2d424e13885598ada13`;
- frozen inventory: 211 paths, including 209 paths immutable to V4.5;
- V4.4 artifact: semantic `de1ba4194a0f7220b1cfcb0c61f8faed3f187c0e9c7712775cba53fa79ed98bb`, raw `3b6824965fa7b2829981d6d35eec5413a24f7340719613e7cd2e8512d6285488`.

The operation against which parity is checked remains the exact V4.3 elementary-circuit artifact. No V4.3 or V4.4 byte is rewritten.

## Why transpilation cannot solve the width rejection

Qiskit's current built-in layout pipeline maps the virtual wires in an already-built circuit to physical wires and can expand the circuit with target ancillas. Its documentation explicitly notes that built-in pipelines do not currently shorten virtual-qubit lifetimes. Consequently, topology placement cannot turn a 339-wire input into a 156-wire input. Width must be reduced by the reversible compiler before a `QuantumCircuit` is reconstructed.

References:

- IBM Quantum, [Transpiler](https://quantum.cloud.ibm.com/docs/en/api/qiskit/transpiler).
- Mathias Soeken et al., [Reversible circuit compilation with space constraints](https://arxiv.org/abs/1510.00377).
- Anouk Paradis et al., [Reqomp: Space-constrained Uncomputation for Quantum Circuits](https://doi.org/10.22331/q-2024-02-19-1258).
- Charles H. Bennett, [Logical Reversibility of Computation](https://doi.org/10.1147/rd.176.0525).

## Encoded interface and exact parity domain

V4.3 represents each of the two 40-state coin addresses as a 40-qubit one-hot register. V4.5 compiles the logical interface directly with a six-qubit, little-endian binary address:

`|e_i>_one-hot  ↦  |i>_binary`, for `i ∈ {0,…,39}`.

This is an exact isometry between the promised 40-dimensional logical coin spaces. It is not a claimed unitary circuit that compresses an arbitrary already-existing 40-qubit register to six qubits. V4.5 requires binary initialization at the compiled interface. Addresses 40–63 are outside the admitted parity promise and are retained as explicit negative scope; they are never silently projected, measured, reset or discarded.

The ordered ring applies exactly the same 40 two-level rotations in the same order to each valid logical coin space. Each binary two-level operation is materialized through a deterministic Gray path, a pattern-controlled exact rotation on the final edge, and the inverse Gray path. Invalid address basis states are not used as intermediate Gray states.

## Register ledger

For a seed whose maximum materialized row width is `w`, V4.5 allocates:

| Register | Width | Lifetime / role |
|---|---:|---|
| `DATA` | 40 | Persistent portfolio basis |
| `REMOVE_ADDR` | 6 | Persistent valid binary coin address |
| `ADD_ADDR` | 6 | Persistent valid binary coin address |
| `SUM_WORK` | `w` | One shared guarded-sum bank, cleared after every row phase |
| `CONSTANT` | `w` | Constant synthesis, MCX ladder and post-SELECT bridge workspace |
| `CARRY` | 1 | Clean Cuccaro carry |
| `ADDRESSED` | 2 | Addressed data flags |
| `ROW_FLAGS` | 7 | Seven exact interval predicates |
| `CONTROL_FLAGS` | 5 | Difference, feasible, move, streamed target, adder ladder |

The exact static formula is `67 + 2w`. Across the eight frozen seeds, `w` is between 33 and 39, giving 133–145 logical wires. The worst case therefore retains an 11-qubit structural margin under 156.

## Streamed target, shared sum and Bennett schedule

The 40-qubit V4.3 `TARGET` bank is removed. For index `i`, one clean control wire is computed as:

`t_i = DATA_i XOR (difference AND REMOVE_ADDR=i) XOR (difference AND ADD_ADDR=i)`.

It controls the same frozen constant-add primitive, then is immediately uncomputed. The independent checker exhausts the local Boolean identity for every data bit, difference bit and all 64×64 binary address pairs.

The address-equality toggles inside this immediate compute/use/uncompute envelope use a three-CX relative-phase Toffoli ladder. If `B` denotes the resulting monomial equality computation and `A` the controlled adder, the emitted block is exactly `B† A B`: `A` preserves every input and the streamed control, so the basis-dependent phases of `B` cancel with its exact adjoint. This optimization is confined to that certified envelope; ordinary exact MCX ladders remain in every context where such cancellation is not established. It keeps the predeclared 2,500,000-CNOT bound falsifiable rather than relaxing it after observing the result.

The seven simultaneous V4.3 sum banks are replaced by `SUM_WORK`. For each row the compiler:

1. computes the guarded sum from streamed target bits;
2. toggles the row predicate;
3. reverses all additions and clears the sum;
4. proceeds to the next row.

After the seven-row AND is copied into the feasibility flag, rows are recomputed in reverse order to erase their predicate flags, then their sums are erased again. This is Bennett compute–use–uncompute: the reduction in space deliberately purchases more gates. No `reset`, measurement or loss of dependencies is allowed.

## SELECT parity and bridge reuse

Binary equality-controlled reads replace one-hot reads. On the valid address subspace, equality controls are algebraically identical to the corresponding one-hot bit. The update therefore preserves the exact V4.3 promised SELECT trace: addressed flags, difference, target feasibility, move bit, conditional swap and reverse cleanup.

The V4.3 off-promise cleanup witness remains a mandatory rejection witness. V4.5 does not reinterpret it as a globally clean oracle.

After SELECT has restored all scratch to zero, the certified Hamming-distance-four data bridges reuse the first 37 clean wires drawn from `SUM_WORK || CONSTANT`. The allocation certificate proves this reuse occurs only after SELECT cleanup and does not overlap any data control or bridge target.

## Proof-carrying evidence

The sealed result contains:

- exact parent, specification, source and artifact identities;
- a contiguous per-seed register map;
- an ordered liveness trace and cleanup obligations;
- a register-map root, liveness root and deterministic stream-manifest root;
- exact elementary and CNOT counts;
- local exhaustive target-identity evidence;
- valid-subspace coin and selector parity evidence;
- the retained V4.3 off-promise witness;
- two clean-process reproducibility roots;
- a separate standard-library checker result that does not import the generator.

Tests are evidence for the implementation, not a substitute for the construction proof. The admitted claim is limited to the frozen promise and compiler contract.

## Predeclared gates

V4.5 is accepted only if every seed is at most 156 qubits, the static design ceiling is at most 145, and materialized CNOT count remains at most 2,500,000 per seed. A negative outcome remains a valid result.

If V4.5 passes, the next independent gate is frozen now: reconstruct each width-admitted stream, translate with the pinned V4.4 offline target, and route with `translator/basic`, seed 4505, zero ISA violations, zero coupling violations, at most 100× native-CZ expansion, and at most 250,000,000 native CZ gates and routed depth per seed. That gate is explicitly not executed or claimed by V4.5.

The IBM fake-provider documentation states that fake backends are snapshots and do not represent the latest real-system behavior. A later offline routing pass would still not establish current calibration, execution success, fidelity, latency, economic utility or advantage: [IBM Quantum fake provider](https://quantum.cloud.ibm.com/docs/en/api/qiskit-ibm-runtime/fake-provider).
