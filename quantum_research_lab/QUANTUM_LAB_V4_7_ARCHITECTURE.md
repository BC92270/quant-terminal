# Quantum Lab V4.7 — Pinned Dated Properties and Fault-Excluded Routing

## Institutional decision boundary

V4.7 is an append-only `RESEARCH_ONLY` successor to the authenticated V4.6
full-stream routing experiment. It is designed to answer three bounded
questions over the exact eight V4.6 streams:

1. what dated FakeMarrakesh native properties imply under one explicitly
   frozen, offline duration/error model;
2. whether the V4.6 BasicSwap routes use any native CZ tuple whose bundled
   historical `gate_error` is equal to one; and
3. whether one preregistered fault-excluded routing candidate is feasible and
   Pareto-safe relative to the exact V4.6 baseline within that model.

V4.7 does **not** establish current calibration, availability, pulse-level
schedule feasibility, circuit fidelity, success probability, solution quality,
economic utility or quantum advantage. The source is a dated properties file
bundled in a pinned fake-provider wheel, not a live provider export.
`hardware_executable=false` remains mandatory. Provider discovery, credential
access, network calls, backend runs, simulator jobs and QPU jobs remain zero.

This document describes the frozen architecture and decision rules. A result
is valid only if a separately sealed V4.7 artifact passes its named validators;
the design itself is not evidence that those checks or scientific gates pass.

## Authenticated lineage

Before evaluating any V4.7 result, the optimizer is required to authenticate:

1. the raw and semantic V4.6 freeze contract;
2. the complete 249-path V4.6 frozen inventory and 247 immutable predecessor
   paths;
3. the exact V4.6 sealed artifact, its eight ordered stream commitments and its
   route/native/layout roots;
4. the V4.4 FakeMarrakesh structural snapshot and its original wheel/property
   provenance;
5. the raw dated properties bytes, normalized property oracle, fault-excluded
   ordered-path oracle and duration/error model contract; and
6. the result-blind V4.7 specification whose result state is
   `NOT_EVALUATED`.

Only the successor-mutable human and integration surfaces identified by the
lineage contract may supersede their V4.6 bytes. Every other parent path must
remain byte-identical. Any missing file, raw-hash mismatch, semantic self-hash
mismatch, duplicate JSON key, non-finite number, symlinked evidence path or
mixed release state is a fail-closed condition.

## Chronology and disclosure

The dated properties were necessarily inspected while the normalization and
fault-exclusion machinery was built. In particular, unit-error CZ tuples were
visible before the V4.7 specification was sealed. Their presence and all
property-derived observations are therefore disclosed as exploratory input
facts, not confirmatory discoveries.

The following elements were nevertheless fixed before the eight-seed result:

- the exact V4.6 baseline reconstruction obligation;
- the sole routing candidate and its initial-layout rule;
- the ordered-path objective and tie-break sequence;
- the integer-`dt` duration model;
- the decimal error-mass definition and its non-fidelity interpretation;
- the missing/invalid/unit-error fail-closed policies;
- the inherited resource gates;
- the all-eight-seed Pareto rule;
- the optimistic architecture lower-bound screen; and
- the decision tree and next falsifiable gate.

The candidate path oracle was built before the result, and the sealed
specification records `result_state_at_seal=NOT_EVALUATED`. A later artifact
must retain this chronology rather than recasting the experiment as fully
confirmatory.

## Historical property provenance

The reference builder consumes exactly one caller-supplied archive:

- file: `qiskit_ibm_runtime-0.49.0-py3-none-any.whl`;
- wheel SHA-256:
  `b29b4a0a5e013b6e6fd6556158fd34a05e2930dea870c60edef738b834977f2b`;
- member:
  `qiskit_ibm_runtime/fake_provider/backends/marrakesh/props_marrakesh.json`;
- raw property size: 565,487 bytes;
- raw property SHA-256:
  `d49d7ae07deb95947ea10e5b9b9c5cbab6df21f98610543817f35ade2b1aece6`.

The builder does not import Qiskit, import a provider SDK, contact a provider,
read credentials or submit a job. It also authenticates the V4.4 structural
snapshot that first committed this provenance.

The bundled record identifies `ibm_marrakesh` backend version `1.0.7` and a
global last-update timestamp of `2025-02-26T14:52:45-05:00`. Individual
property timestamps range from 2024-10-28 through 2025-02-26; the global date
is not treated as a strict cutoff for every field. None of these dates make the
snapshot current hardware evidence.

## Strict normalization and coverage

The normalized oracle retains every required native tuple for the frozen basis
`cz`, `id`, `rz`, `sx`, `x`:

- 352 directed CZ tuples;
- 156 tuples for each one-qubit gate;
- 976 native tuples total;
- exact `gate_error` and `gate_length` provenance for each tuple;
- duration converted to an exact integer number of 4 ns ticks; and
- T1, T2 and readout fields for all 156 qubits, for context only.

The 1,952 required native property values must be complete. V4.7 performs no
imputation, interpolation or reverse-edge fallback. A missing, duplicate,
out-of-range, non-finite or non-integral-duration value blocks evaluation.
Readout properties are reported but are not applied because the V4.6 route IR
contains no measurements.

The raw dated input contains 26 directed CZ tuples with reported
`gate_error=1`, corresponding to 13 undirected connections. Requiring both
directions of an undirected routing edge to be present, valid and strictly
below one produces components of sizes 153, 1, 1 and 1. Qubits 24, 102 and 113
are isolated. The largest healthy component has eight spare positions over the
maximum V4.6 logical width of 145.

These are properties-file observations, not measured failure rates from a V4.7
hardware experiment.

## Exact V4.6 baseline reconstruction

For each admitted seed, V4.7 regenerates every authenticated V4.6 input
instruction and replays the exact frozen V4.6 BasicSwap ordered-path oracle.
The identity initial layout maps logical qubit `i` to physical qubit `i`.

Before any comparison is accepted, the replay must reproduce the parent:

- complete input-stream manifest;
- ordered route-IR commitment;
- native-ledger commitment;
- final logical-to-physical layout; and
- exact input counts and stage ordering.

Failure to reproduce any baseline commitment aborts the V4.7 experiment. The
dated-property ledgers are added during replay; they do not modify the parent
route, macro or layout semantics.

## Fault-excluded candidate

The sole candidate is
`FAULT_EXCLUDED_SHORTEST_HOP_RELIABILITY_TIEBREAK_V1`.

It uses only the 153-qubit component remaining after the bidirectional
unit-error edge screen. Logical qubit order is mapped to the ascending prefix
of that component, making the non-trivial omission of isolated physical
qubits deterministic. The oracle commits all 23,256 ordered paths between
distinct component qubits. Its maximum shortest-path length is 43 hops.

For each ordered source/destination pair, path selection is lexicographically
ordered by:

1. minimum hop count;
2. minimum reported native gate-error mass for the route macro;
3. minimum nominal duration in integer ticks; and
4. the full physical path tuple.

The cost of an inserted SWAP is the three-CZ/six-SX V4.6 macro. The terminal
adjacent CX cost is one CZ plus two target SX gates. The candidate is a static
per-pair shortest-path tie-breaker: it has no lookahead, global layout search,
commutation pass, cancellation pass or global optimality claim. A locally
preferred path can still yield an inferior final layout or global schedule;
that possibility is measured, not hidden.

## Frozen duration model

Every baseline and candidate stream is replayed with 156 integer clocks, one
per physical qubit. Native gates use the exact dated duration attached to their
ordered qargs:

- a one-qubit operation starts at that qubit's current clock and advances it
  by its duration;
- a two-qubit CZ starts at the maximum of its endpoint clocks and advances both
  clocks to the same end time;
- RZ contributes its recorded zero duration;
- the CX and SWAP macros are scheduled in their exact frozen V4.6 order; and
- the maximum final physical clock is reported as the modeled makespan.

This produces a deterministic
`properties_conditioned_asap_duration_estimate` in 4 ns ticks. It is not a
pulse schedule or observed wall-clock runtime. The model excludes control
electronics, crosstalk, concurrent-drive restrictions beyond shared qubits,
dynamical decoupling, queue time, job overhead and calibration drift.

## Frozen error model

The normative diagnostic is

```text
reported_gate_error_mass =
    sum(exact_occurrence_count(gate, ordered_qargs) * reported_gate_error)
```

It is accumulated with 50-decimal precision and committed globally, by native
gate, by physical tuple and by workload stage. Occurrences with reported error
greater than or equal to one are counted separately. Missing or invalid tuples
block the calculation.

This additive mass is a deterministic screen over reported fields. It is **not**
circuit fidelity, success probability, an expected failure count, logical
error rate or solution quality. A product-style `sum(count*log10(1-p))` may be
reported as a non-normative diagnostic only when every used `p` is below one;
it has no acceptance role and is undefined when a unit-error tuple is used.

## Research feasibility and Pareto gates

The candidate research-feasibility gate requires, for every seed:

- exact parent input manifest;
- bijective final layout;
- zero ISA violations;
- zero coupling violations;
- zero missing property occurrences;
- zero unit-error gate occurrences;
- no more than 250,000,000 native CZ gates;
- no more than 250,000,000 structural ASAP layers; and
- native-CZ expansion no greater than 100 times the V4.5 CX input count.

These inherited ceilings are software/resource screens, not hardware
acceptance thresholds.

A Pareto-safe replacement is demonstrated only if, on **all eight** seeds, the
candidate has:

- strictly lower reported gate-error mass;
- modeled makespan no greater than the exact V4.6 baseline; and
- native CZ count no greater than the exact V4.6 baseline.

Passing feasibility does not imply Pareto dominance. Passing both remains a
model-scoped research result and does not authorize hardware execution.

## Architecture-level necessary-condition screen

For each seed, V4.7 also computes a deliberately impossible-to-beat optimistic
lower bound using only the directly translated CX count:

- every SWAP and every one-qubit gate is removed;
- every remaining CX receives the minimum CZ error in the entire dated
  snapshot;
- every remaining CX receives the minimum CZ duration;
- 78 disjoint CZ gates are assumed to execute in parallel; and
- the resulting duration is compared with the maximum dated T2 while the
  resulting additive error mass is compared with the exclusive limit one.

This is a necessary-condition stress screen, not a sufficient hardware model.
If all eight seeds fail both optimistic screens, the exact preregistered
fixed-architecture decision is
`FIXED_V46_ARCHITECTURE_REJECTED_BY_PREREGISTERED_HISTORICAL_PROPERTIES_STRESS_SCREEN`;
the corresponding combined result is
`V47_HISTORICAL_PROPERTIES_STRESS_SCREEN_REJECTS_FIXED_V46_ARCHITECTURE_NO_CURRENT_HARDWARE_INFERENCE`.
That model-scoped rejection requires an architecture-level redesign before the
next gate. It is restricted to this workload family, these direct-CX counts,
this dated property oracle and this screen. It is not a theorem of quantum
impossibility and does not characterize a current backend.

## Sealed evidence architecture

The result artifact is required to contain, for each seed and for both routes:

- exact reconstructed input and route commitments;
- native, physical-property, stage-property, timing and error ledgers;
- final layout and resource-gate decision;
- self-hashes for every material nested record;
- baseline/candidate deltas and the per-seed Pareto decision; and
- the architecture lower-bound inputs, outputs and decision.

Aggregate evidence commits the ordered eight-seed root, baseline identity,
candidate feasibility, Pareto status, modeled makespan extrema and unit-error
occurrence totals. The top-level claim boundary must preserve zero provider,
network, credential, simulator and QPU activity.

The independent checker must use the Python standard library only and must not
import the V4.7 optimizer. It must recompute property coverage, nested hashes,
native occurrence/error algebra, timing identities, route/layout invariants,
baseline V4.6 commitments, resource gates, comparisons, aggregate decisions
and the governance boundary. Clean-process byte-exact replay is an additional
determinism check; it is not independent physical evidence.

The deployment trust bootstrap is deliberately external to the self-hashed
freeze. The release manifest publishes a SHA-256 over the ordered 25 raw
transition files, including the raw freeze bytes. Preflight and apply require
that trusted value explicitly and recheck it before and after commit work. A
self-consistent but independently unpinned overlay is therefore not admitted.
Candidate validation runs only after that check, with a scrubbed environment
and a static offline boundary over every executed validation module.

At the time this architecture document was authored, final artifact, freeze,
release and validation identities were intentionally not asserted. Their sole
authoritative values are the subsequently generated sealed artifact,
`FREEZE_CONTRACT_V4_7.json` and validator outputs.

## Reference sources

- [IBM Quantum — fake-provider backend snapshots](https://quantum.cloud.ibm.com/docs/en/api/qiskit/1.3/providers_fake_provider)
- [IBM Quantum — BackendProperties model](https://eu-de.quantum.cloud.ibm.com/docs/en/api/qiskit-ibm-runtime/models-backend-properties)
- [Qiskit — Target and InstructionProperties](https://qiskit.qotlabs.org/docs/api/qiskit/qiskit.transpiler.Target)
- [IBM Quantum — Transpilation defaults and configuration](https://quantum.cloud.ibm.com/docs/en/guides/defaults-and-configuration-options)
- [IBM Quantum — Represent quantum computers for the transpiler](https://quantum.cloud.ibm.com/docs/en/guides/represent-quantum-computers)
- [Qiskit source — BasicSwap](https://github.com/Qiskit/qiskit/blob/main/qiskit/transpiler/passes/routing/basic_swap.py)

## Next falsifiable gate

Whatever the V4.7 model-scoped outcome, production admission remains rejected.
The preregistered next gate is
`MULTI_SNAPSHOT_ROBUSTNESS_AND_ARCHITECTURE_LEVEL_CZ_REDUCTION_BEFORE_ANY_CURRENT_PROVIDER_DISCOVERY`.
It requires a separately sealed protocol. It does not implicitly authorize
live provider discovery, credential use, simulator execution or QPU work.
