# Quantum Lab V4.1 deployment contract

V4.1 is an additive, fail-closed successor to the exact V4.0 institutional
release. It executes the preregistered augmented-connectivity and resource
experiment for the frozen `N=40, K=10, BANDS` family. The complete V4.0
one-swap forest is preserved, all `58,725` registered incident two-swap
candidates are audited, and three deterministic exact bridges certify a
connected subgraph on all eight seeds.

Connectivity success is not production admission. The preregistered R1 and R2
compiler candidates reach respectively `15,256,056` and `15,663,936`
selected-model CNOT against the immutable `2,500,000` ceiling. Both remain
rejected; backend transpilation and hardware execution remain blocked.

## Exact V4.0 to V4.1 transition

The only accepted target states are:

1. the exact V4.0 predecessor, including its 145 frozen-file commitments, its
   freeze file, all 143 immutable predecessor paths, and the exact V4.0
   README/UI surface pair; or
2. the exact complete V4.1 overlay, in which case reapplication is an
   authenticated `NO_OP` and no target byte is rewritten.

The parent freeze is authenticated by both identities:

```text
V4.0 freeze raw-file SHA-256  748829b2153611ffba0751ea5da9d0785ca44ce4f12a02546436d4a1e79a94b4
V4.0 freeze semantic SHA-256  c6d380e5541182b6cc2096c3d2a6de6f129cb92c80288a43dae6f924314cff1e
```

Mixed V4.0/V4.1 surfaces, changed immutable bytes, partial overlays, unknown
third states, duplicate or non-finite JSON, absolute or traversing paths,
symlinked/non-regular release paths, source/target aliasing, nested roots and
broad filesystem or home-directory roots fail closed.

## Exact 18-file overlay

The ordered transition inventory contains exactly these paths:

1. `FREEZE_CONTRACT_V4_1.json`
2. `DEPLOY_V4_1.md`
3. `app_v41_offline_harness.py`
4. `install_quantum_lab_v41.py`
5. `outputs/quantum_phase3/v41_certified_bridge/SEALED_V4_1_CERTIFIED_BRIDGE_COMPILER_ARTIFACT.json`
6. `quantum_research_lab/PHASE_III_V4_1_CERTIFIED_BRIDGE_COMPILER_SPEC_V1.json`
7. `quantum_research_lab/QUANTUM_LAB_V4_1_ARCHITECTURE.md`
8. `quantum_research_lab/phase3_v41_bridge_engine.cpp`
9. `quantum_research_lab/phase3_v41_certified_bridge_compiler.py`
10. `quantum_research_lab/phase3_v41_ui.py`
11. `quantum_research_lab/phase3_v41_validation.py`
12. `quantum_research_lab/test_phase3_v41.py`
13. `quantum_research_lab/test_phase3_v41_release.py`
14. `quantum_research_lab/verify_freeze_contract_v41.py`
15. `quantum_research_lab/verify_phase3_v41.py`
16. `quantum_research_lab/verify_phase3_v41_ui.py`
17. `quantum_research_lab/README.md`
18. `quantum_research_lab/ui.py`

Supporting evidence and verification paths are committed first. The
human-readable `README.md` surface is penultimate and the executable `ui.py`
integration surface is strictly last.

## Preflight and apply

Run from a clean extraction of the V4.1 institutional release:

```bash
python3 install_quantum_lab_v41.py --source . --target /workspaces/quant-terminal
python3 install_quantum_lab_v41.py --source . --target /workspaces/quant-terminal --apply
```

Use the same Python interpreter for preflight, apply and every verifier. The
installer does not install dependencies or silently fall back to another
runtime. Missing Python packages or a missing C++ compiler fail the validation
gate; they do not authorize weaker checks.

## Transaction, lock, staging and rollback

An apply invocation must:

1. acquire `.quantum-lab-v41-install.lock` atomically with a unique ownership
   token; a pre-existing or replaced lock fails closed and is never removed by
   a non-owner;
2. authenticate the complete source inventory and classify the target as the
   exact V4.0 predecessor or exact V4.1 successor;
3. return a verified `NO_OP` for an exact V4.1 target;
4. construct a private, self-contained V4.1 staging candidate from exact
   inherited V4.0 bytes plus the exact 18-file source overlay;
5. re-hash the source snapshot, candidate and target immediately before any
   target mutation, closing source/target drift during staging;
6. execute the complete mandatory validation ladder against the staging
   candidate;
7. capture every target preimage—existence, regular-file type, mode and
   SHA-256—in a timestamped `.quantum-lab-v41-backup-*` directory;
8. atomically commit the ordered overlay, with `README.md` penultimate and
   `ui.py` last; and
9. authenticate and revalidate the installed V4.1 state.

Any commit or post-install failure restores captured preimages in reverse
order, removes only destinations proven to have been newly created by this
invocation, and reauthenticates the exact V4.0 predecessor. A changed backup,
unsafe destination or incomplete predecessor restoration makes rollback fail
closed and is reported explicitly. The private stage is removed only by its
owner; the backup remains available for audit. The installer releases only
the lock whose ownership token it still controls.

Preflight is read-only. `NO_OP` is reserved for byte-exact V4.1 reapplication;
it is never used to excuse an incomplete, mixed or drifted target.

## Mandatory validation ladder

The candidate and installed target must pass unit, release, deep scientific,
freeze, UI and inherited-regression gates with non-zero process status on any
failure:

```bash
python3 -m unittest quantum_research_lab.test_phase3_v41
python3 -m unittest quantum_research_lab.test_phase3_v41_release
python3 -m quantum_research_lab.verify_phase3_v41 .
python3 -m quantum_research_lab.verify_freeze_contract_v41 . --contract FREEZE_CONTRACT_V4_1.json
python3 -m quantum_research_lab.verify_phase3_v41_ui app_v41_offline_harness.py --timeout 600
python3 -m unittest quantum_research_lab.test_phase3_gate_compiler quantum_research_lab.test_phase3_algorithmic_contract quantum_research_lab.test_phase3_v34 quantum_research_lab.test_phase3_v35 quantum_research_lab.test_phase3_v36 quantum_research_lab.test_phase3_v37 quantum_research_lab.test_phase3_v38 quantum_research_lab.test_phase3_v39 quantum_research_lab.test_phase3_v40
```

The release-chain command is the single authoritative deep replay in this
ladder. It performs all 28 scientific checks, including the complete
independent artifact rebuild. Unit, release and freeze checks authenticate the
same pinned evidence without redundantly launching the multi-minute replay.
An identity-only invocation is always labelled
`deep_scientific_replay=false`; it cannot be reported as a fresh deep replay.

Scientific verification authenticates the V4.0-to-V3.1 chain, the frozen V4.1
specification, C++ engine source, Python compiler and sealed artifact; checks
the three independent incident-bridge methods; rebuilds compression,
connectivity, resources and decisions; and verifies the exact all-seed ledger:

```text
incident two-swap candidates  58,725 / 58,725
exact-feasible candidates     787
selected bridges              3
certified-subgraph edges      337,710,606
connected seeds               8 / 8
R1 maximum                    15,256,056 CNOT · REJECTED
R2 maximum                    15,663,936 CNOT · REJECTED
R2 minimum margin            -13,163,936 CNOT
maximum R2 logical qubits     311
```

The complete augmented one-plus-two-swap edge count is not enumerated and is
not needed for the connected-subgraph certificate. The displayed
`337,710,606` count is the complete authenticated V4.0 forest plus the three
selected bridges, not the full augmented edge set.

## Live route and exact 12-tab contract

The live route remains:

```text
?workspace=quantum-research
```

The user-visible tab contract is exactly:

1. `MISSION CONTROL`
2. `REGIME / DENSITY`
3. `QMC / RISK`
4. `PRICING & CONVERGENCE`
5. `TAIL RISK / EXPOSURE`
6. `QAE RESOURCE INTELLIGENCE`
7. `ADVANTAGE FRONTIER`
8. `QUBO / ISING`
9. `QUANTUM INFORMATION`
10. `BENCHMARK PROTOCOL`
11. `PHASE II / OOS`
12. `PHASE III / QPU`

The first and positive-rerun AppTest snapshots must reproduce this order. The
four entries after `QMC / RISK` are its nested views; together with the eight
principal tabs they form the exact 12-tab visible contract. V4.1 is an
additive panel inside `PHASE III / QPU`, after the preserved V3.4–V4.0 lineage.

The positive-rerun UI verifier requires 31/31 controls, zero Streamlit
exceptions, exact bridge-audit/selected-bridge/connectivity/resource/
compression ledgers with row counts `3/3/8/8/24`, five authenticated
downloads, all scientific override/recompute controls disabled, all
credential/backend controls disabled, stale provider state cleared, and
provider/transpile/seal spies at zero on both runs. HTTP 200 alone is not UI
acceptance.

## Scientific and execution boundary

V4.1's admissible decision is:

```text
augmented connectivity  AUGMENTED_1_2_EXCHANGE_GRAPH_CONNECTED_ALL_SEEDS_BY_CERTIFIED_SUBGRAPH
resource architecture   REJECTED_SELECTED_MODEL_CNOT_BUDGET
overall                 V41_AUGMENTED_CONNECTIVITY_CERTIFIED_RESOURCE_SCREEN_REJECTED
production admission    REJECTED_RESOURCE_BUDGET_HARDWARE_NOT_AUTHORIZED
next gate               SPARSE_CONNECTED_GENERATOR_COMPILER_OR_STRONGER_EXACT_ARITHMETIC_REDUCTION
```

The deployment is provider-free. Provider SDK import is false, credentials are
not read, provider calls are `0`, backend transpilation is `NOT_RUN`, QPU
submission is disabled, QPU jobs are `0`, and `hardware_executable=false`.
Optimization performance is `NOT_TESTED` and quantum advantage is
`NOT_CLAIMED`. The connected-subgraph certificate establishes connectivity
for the frozen augmented move family only; it is not evidence of resource,
backend, hardware, optimization-performance or advantage admission.

SHA-256 commitments provide release integrity, not an external signature.
Without a detached signature anchored outside the package, provenance remains
`UNSIGNED_SHA256_INTEGRITY_ONLY`.
