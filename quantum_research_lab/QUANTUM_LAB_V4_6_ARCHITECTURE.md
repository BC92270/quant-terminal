# Quantum Lab V4.6 — Full-Stream FakeMarrakesh Routing

## Institutional decision boundary

V4.6 is an append-only `RESEARCH_ONLY` successor to the authenticated V4.5
width redesign. It answers one narrow question: can every instruction in all
eight admitted V4.5 streams be reconstructed, translated into the frozen
FakeMarrakesh ISA and routed over its 156-qubit coupling graph under the
resource limits preregistered in V4.5?

It does **not** answer whether a current IBM system is available, calibrated,
accurate enough, fast enough, economically useful or capable of quantum
advantage. `hardware_executable` remains `false`; provider discovery,
credentials, network calls, backend runs, simulator jobs and QPU jobs remain
zero.

## Authenticated lineage

The compiler first authenticates:

1. the raw and semantic V4.5 freeze contract;
2. the exact V4.5 sealed artifact and scientific decision;
3. all 227 V4.5 paths immutable to a successor;
4. the V4.4 FakeMarrakesh structural snapshot;
5. the V4.6 Qiskit 2.5.2 path oracle and native translation contract;
6. the result-blind V4.6 specification.

Only `quantum_research_lab/README.md` and `quantum_research_lab/ui.py` may
supersede their V4.5 bytes. Every other parent path is byte-authenticated before
the V4.6 result is evaluated.

## Chronology and preregistration

The decisive V4.6 thresholds were already sealed in the V4.5 protocol before
any V4.6 pilot:

- routed native CZ per seed: at most 250,000,000;
- ASAP structural depth per seed: at most 250,000,000 layers;
- routed CZ / V4.5 CX expansion: at most 100×;
- ISA violations: exactly zero;
- coupling violations: exactly zero;
- routing method: `basic`;
- translation method: `translator`;
- transpiler seed: 4505.

One seed-1103 implementation pilot occurred before the V4.6 specification was
sealed. It is disclosed, is not confirmatory evidence, and changed none of the
V4.5 thresholds or V4.6 acceptance rules. The confirmatory eight-seed result
was `NOT_EVALUATED` when the V4.6 protocol was sealed.

## Why a compact exact IR is required

The V4.5 workloads contain roughly six million elementary instructions per
seed. Sparse routing can expand these into tens of millions of native
instructions. Materializing a Python object for every native gate would add a
large memory failure mode without adding scientific information.

V4.6 therefore uses a streaming, proof-carrying representation:

- every V4.5 elementary instruction is regenerated in canonical order;
- every instruction creates exactly one canonical route record;
- every route record fixes the logical operands, physical operands before the
  gate, exact ordered path, exact angle and inserted SWAP count;
- route records are committed globally, by 8,192-record chunk and by stage;
- every native macro has a frozen exact expansion and global phase;
- native counts and ASAP structural depth are updated exactly during the pass;
- the complete final logical-to-physical and physical-to-logical permutations
  are sealed.

This is a fully reconstructible circuit IR, not a statistical summary. It is
also not a monolithic `QuantumCircuit`, a pulse schedule or a QPU payload.

## Frozen BasicSwap route oracle

The reference builder imports only Qiskit 2.5.2 and reconstructs the V4.4
`Target`. With socket connections denied, it records all 24,180 ordered
shortest paths returned by `CouplingMap.shortest_undirected_path` for distinct
physical-qubit pairs. Ordered paths are retained because tied shortest-path
choices need not be symmetric under source/destination reversal.

For each nonadjacent CX, the confirmatory compiler:

1. reads the exact ordered path for the current physical operands;
2. inserts a SWAP on each path edge except the last;
3. updates both layout permutations after every SWAP;
4. emits the now-adjacent logical CX;
5. retains the final permutation as the required output interpretation.

This follows Qiskit's documented BasicSwap model of inserting shortest-path
SWAPs in front of a nonlocal two-qubit operation. The frozen oracle removes
runtime dependency and tie-breaking drift from the confirmatory compiler.

## Native macro contract

The target basis is `cz`, `id`, `rz`, `sx`, `x`. Nine bounded Qiskit 2.5.2
canaries freeze the translation behavior used by the streaming compiler.

- `X` → `x`.
- `H` → `rz(π/2)`, `sx`, `rz(π/2)`; phase `π/4`.
- `T` / `T†` → `rz(±π/4)`; phase `±π/8` modulo `2π`.
- `RY(θ)` → `rz(0)`, `sx`, `rz(π+θ)`, `sx`, `rz(3π)`; phase `3π/2`.
- `RZ(θ)` → `rz(θ)`.
- adjacent `CX` → native `H` on target, `cz`, native `H` on target; phase
  `π/2`.
- inserted `SWAP` → three repetitions of parallel `sx` on both endpoints then
  `cz`; phase `3π/2`.

Equivalence is exact up to the explicitly accumulated global phase. The
standard-library checker independently recomputes the entire native count
algebra from the authenticated V4.5 input counts and the routed SWAP count.

## Depth semantics

`asap_structural_depth` is an exact greedy layer count over the native macro
expansion. It respects one- and two-qubit resource conflicts, but uses no gate
duration, pulse constraint, dynamical decoupling, calibration error or
concurrency exclusion beyond shared qubits. It must not be interpreted as
nanoseconds, wall-clock execution time or calibrated schedule feasibility.

## Independent verification

`phase3_v46_independent_checker.py` uses the Python standard library only and
does not import the V4.6 compiler. It checks the complete identity chain,
nested self-hashes, exact parent stream manifests, route chunk completeness,
stage totals, distance-minus-one SWAP identity, native count algebra, final
layout bijections, every inherited resource threshold, aggregate recomputation
and the zero-provider/zero-job governance boundary.

The sealed artifact must additionally reproduce byte-for-byte in a clean
process. Stable replay is evidence of deterministic offline compilation only;
it is not independent evidence of physics or performance.

## Reference sources

- [IBM Quantum — Transpilation defaults and configuration](https://quantum.cloud.ibm.com/docs/en/guides/defaults-and-configuration-options)
- [IBM Quantum — Represent quantum computers for the transpiler](https://quantum.cloud.ibm.com/docs/en/guides/represent-quantum-computers)
- [IBM Quantum — BasisTranslator](https://quantum.cloud.ibm.com/docs/en/api/qiskit/2.3/qiskit.transpiler.passes.BasisTranslator)
- [Qiskit source — BasicSwap](https://github.com/Qiskit/qiskit/blob/main/qiskit/transpiler/passes/routing/basic_swap.py)

## Next falsifiable gate

Even if V4.6 passes its structural and inherited resource gates, production
admission remains rejected. The next admissible experiment is a separately
preregistered, pinned-dated-properties duration/error and optimization
feasibility study over the authenticated V4.6 routed streams. No provider or
QPU activity is implicitly authorized by that roadmap.
