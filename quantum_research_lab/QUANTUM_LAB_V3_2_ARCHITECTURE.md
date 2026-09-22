# Quantum Research Lab V3.2 — Proof-Carrying Reversible Compiler

## Executive position

V3.2 converts the sealed V3.1 exact-dyadic BANDS predicate into deterministic,
provider-neutral reversible gate IR. It is an institutional research artifact:
every result is tied to an immutable parent, a preregistered compiler spec, a
compiler-source digest, exact range certificates, basis-state controls, a
resource ledger, and an independent reproducibility pass.

V3.2 is **not** a QPU-ready release. It authorises no hardware execution and
makes no quantum-speedup or quantum-advantage claim.

## Immutable provenance chain

1. Phase-II protocol: `8E5EF191FAE97A75`.
2. Phase-II execution specification: `40D3225B0AFC86BC01DD`.
3. Phase-III preparation specification: `CDC693C22A3838B0B3C1`.
4. V3.1 dyadic specification: `9A6F664368F4AC592281`.
5. V3.1 dyadic oracle: `D9D109D117E1795CFFEF`.
6. Exact parent file SHA-256:
   `7b39a20ec9200b16996ec25edd660ba7bf26bfb2b454ed44dd1a333513afd50e`.
7. V3.2 compiler specification: `EDAD55227D611B528845` /
   `edad55227d611b52884529fe2da4f8f458e80c36367589a3499bdf075060f3aa`.

`phase3_artifact_guard.py` recomputes the V3.1 legacy oracle hash, all eight
certificate hashes, all resource envelopes, seed order, parent identifiers and
the 126/126 parameter-identity totals. A stored status string never suffices.

## Two non-interchangeable oracle contracts

### EXACT_K_SUBSPACE

- Contract domain: `D_K = {x : popcount(x)=10}`.
- Compiled predicates: four group bands and three exact dyadic factor bands.
- Cardinality is an input-domain assumption, normally supplied by state
  preparation and a number-preserving XY mixer.
- Maximum certified factor accumulator width: 68 signed bits.

### FULL_BINARY

- Contract domain: every `x` in `{0,1}^40`.
- Compiled predicates: cardinality plus the same seven BANDS constraints.
- This is the complete strict Phase-II feasibility predicate.
- The full subset-sum prefix envelope requires 69 signed bits for seed 6607.

The extra full-binary bit is a scientific result, not an implementation detail:
using the 68-bit exact-K envelope outside `D_K` would create an unproved overflow
assumption.

## Canonical reversible construction

Registers are contiguous, global, zero-based and little-endian:

1. caller-owned data;
2. caller-owned output target;
3. sequentially reused accumulator;
4. two comparator flags;
5. one flag per constraint;
6. one aggregate conjunction flag.

For every constraint the compiler performs:

1. controlled exact integer additions into the shared accumulator;
2. inclusive lower and upper comparisons;
3. a Toffoli into the constraint flag;
4. reverse comparator uncomputation;
5. reverse arithmetic uncomputation.

The constraint flags are conjoined, the caller target is flipped, and the
entire computation is reversed. The contract is therefore:

`U_f |x>|y>|0_work> = |x>|y XOR f(x)>|0_work>`.

## Gate and arithmetic semantics

- Abstract gate set: `X`, `CX`, `CCX`, `MCX`.
- Negative-control polarity is explicit in each gate record.
- Signed values use exact two's complement.
- Controlled constant addition uses descending controlled increments for every
  set bit of the modulo-`2^w` constant.
- Comparators use disjoint lexicographic highest-differing-bit terms plus
  equality; signed order uses virtual sign-bit inversion.
- Abstract MCX uses a declared clean-ancilla v-chain accounting rule. A named
  backend/native-basis lowering is deliberately deferred.

## Validation ladder

- **A — Arithmetic:** exhaustive increments, signed constants, inclusive
  signed/unsigned comparators and inverse restoration for widths 1–5.
- **B — Seed controls:** all eight N=40 authoritative witnesses regenerated
  only after the frozen Phase-II generator source hash matches.
- **C — Small-N exhaustive:** both target values, every allowed exact-K input,
  every full-binary input, negative coefficients, inclusive boundaries, input
  preservation and clean ancillas.
- **D — N40 controls:** witness-accept, deterministic exact-K reject and
  off-cardinality full-binary reject controls for all eight seeds.
- **E — Reproducibility:** an independent second compilation must reproduce all
  gate-stream hashes and resource ledgers exactly.

The compiler seal is write-once. An existing non-identical or invalid artifact
is never overwritten.

## Canonical V3.2 seal (2026-09-04)

- Compiler artifact semantic SHA-256:
  `5e6cc7e53f15921f7cbd22ef66f04878b37d54372e04b5bf49f5bb4854050fcd`.
- Compiler artifact raw-file SHA-256:
  `616cc12808465916dfcfcde6c8e2c9feed1be4b294ad034f29cb7cb36704031b`.
- Validation-manifest SHA-256:
  `bde0dc2e90a355821c8678d2df8ac743820c0a4d2e83701aeeeaab3e1d8e9b91`.
- Freeze-contract semantic SHA-256:
  `875cb29ddd26ad9c50eebc8eab2f0f1758220e26683d7ad45475db9e1d2f61f2`.
- Canonical family: 8 seeds × 2 semantic domains = 16 circuit ledgers.
- Maximum `EXACT_K_SUBSPACE` envelope: 119 logical qubits, 428,273
  abstract gates, depth 402,502 and a 111,709,780 T-count upper estimate.
- Maximum `FULL_BINARY` envelope: 121 logical qubits, 438,939 abstract
  gates, depth 413,016 and a 115,676,610 T-count upper estimate.

These are deterministic reference-compiler estimates, not routed backend
counts. The raw-file hash includes the artifact creation timestamp; the
semantic hash deliberately excludes it and is the stable scientific identity.

## Four resource levels

1. `LOGICAL_IR`: registers, widths, controlled additions, comparators and
   uncomputation.
2. `GATE_LEVEL_ABSTRACT`: exact X/CX/CCX/MCX counts and dependency depth.
3. `TRANSPILED_BACKEND_SPECIFIC`: explicitly `NOT_RUN` in V3.2.
4. `FAULT_TOLERANT_ESTIMATE`: clean-MCX v-chain CCX/CNOT/T upper estimates,
   separated from the logical width.

These levels must never be collapsed into one ambiguous “qubit count”.

## Remaining blockers and opportunity frontier

1. Reduce the reference arithmetic depth and T-count without changing gate
   semantics or parent identity.
2. Preregister a named provider, backend snapshot, native basis, routing
   policy, optimisation level and transpiler version.
3. Prove or redesign the algorithmic enforcement path. The current XY mixer
   preserves cardinality, not all seven BANDS constraints.
4. Add noisy simulation and error-budget falsification before any QPU run.
5. Seal a hardware protocol first; execute later under a separate, explicit
   authority gate.
6. Compare against strong classical baselines under matched wall-clock,
   energy-budget and solution-quality definitions before discussing advantage.

## Operations

Fast local regression:

```bash
python -m unittest quantum_research_lab.test_phase3_gate_compiler -v
```

Full two-pass canonical seal:

```bash
python -m quantum_research_lab.phase3_circuit_validation \
  outputs/quantum_phase3/dyadic_bands_oracle/N40_BANDS/SEALED_EXACT_DYADIC_BANDS_ORACLE.json \
  --output outputs/quantum_phase3/gate_compiler/SEALED_GATE_COMPILER_ARTIFACT.json
```

The Streamlit Phase-III tab exposes the same workflow through a resumable
background worker and displays the sealed artifact only after fail-closed
integrity checks pass.
