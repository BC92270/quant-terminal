# Quantum Lab V4.0 deployment contract

V4.0 is an additive, fail-closed successor to the exact V3.9 institutional
release. It closes the question that V3.9 left `INDETERMINATE` by certifying
the complete one-out/one-in feasible graph for all eight frozen
`N=40, K=10, BANDS` seeds. The result is a counterexample, not a promotion:
six seeds are connected, seeds `2207` and `7703` are disconnected, and three
exact feasible portfolios are isolated.

The V3.9 selected-model rejection remains unchanged at `781,332,180` CNOT
against a `2,500,000` ceiling. V4.1's successor resource architecture is only
preregistered; its CNOT result is `NOT_EVALUATED` and its budget margin is
`NOT_COMPUTED`.

## Exact V3.9 to V4.0 transition

The only accepted target states are:

1. the exact V3.9 predecessor, including its 129 frozen-file commitments, its
   freeze file, the 127 immutable predecessor paths and the exact V3.9
   README/UI surface pair; or
2. the exact complete V4.0 overlay, in which case reapplication is an
   authenticated `NO_OP` and no target byte is rewritten.

The parent freeze is authenticated by both identities:

```text
V3.9 freeze raw-file SHA-256  e44295aaab7689be7090ff6022a67e2e7d96cc40fcdaedf0328aa50294880c59
V3.9 freeze semantic SHA-256  510790b4682e09376feb226b9d0b8b0046477ea456abf0a38e0cadb2410300ac
```

Mixed V3.9/V4.0 surfaces, changed immutable bytes, partial overlays, unknown
third states, duplicate or non-finite JSON, absolute or traversing paths,
symlinked/non-regular release paths, source/target aliasing, nested roots and
broad filesystem or home-directory roots fail closed.

## Exact 18-file overlay

The ordered transition inventory contains exactly these 18 paths:

1. `FREEZE_CONTRACT_V4_0.json`
2. `DEPLOY_V4_0.md`
3. `app_v40_offline_harness.py`
4. `install_quantum_lab_v40.py`
5. `outputs/quantum_phase3/v40_connectivity/SEALED_V4_0_GLOBAL_CONNECTIVITY_ARTIFACT.json`
6. `quantum_research_lab/PHASE_III_V4_0_GLOBAL_CONNECTIVITY_SPEC_V1.json`
7. `quantum_research_lab/QUANTUM_LAB_V4_0_ARCHITECTURE.md`
8. `quantum_research_lab/phase3_v40_connectivity_engine.cpp`
9. `quantum_research_lab/phase3_v40_global_connectivity.py`
10. `quantum_research_lab/phase3_v40_ui.py`
11. `quantum_research_lab/phase3_v40_validation.py`
12. `quantum_research_lab/test_phase3_v40.py`
13. `quantum_research_lab/test_phase3_v40_release.py`
14. `quantum_research_lab/verify_freeze_contract_v40.py`
15. `quantum_research_lab/verify_phase3_v40.py`
16. `quantum_research_lab/verify_phase3_v40_ui.py`
17. `quantum_research_lab/README.md`
18. `quantum_research_lab/ui.py`

Supporting evidence and verification paths are committed first. The
human-readable `README.md` surface is penultimate and the executable `ui.py`
integration surface is strictly last.

## Preflight and apply

Run from a clean extraction of the V4.0 institutional release:

```bash
python3 install_quantum_lab_v40.py --source . --target /workspaces/quant-terminal
python3 install_quantum_lab_v40.py --source . --target /workspaces/quant-terminal --apply
```

Use the same Python interpreter for preflight, apply and every verifier. The
installer does not install dependencies or silently fall back to another
runtime. A missing required Python package or C++ compiler is a failed gate,
not permission to weaken validation.

## Transaction, lock, staging and rollback

An apply invocation must:

1. acquire `.quantum-lab-v40-install.lock` atomically with a unique ownership
   token; a pre-existing or replaced lock fails closed and is never removed by
   a non-owner;
2. authenticate the complete source inventory and classify the target as the
   exact V3.9 predecessor or exact V4.0 successor;
3. return a verified `NO_OP` for an exact V4.0 target;
4. construct a private, self-contained V4.0 staging candidate from exact
   inherited V3.9 bytes plus the exact 18-file source overlay;
5. re-hash the source snapshot, candidate and target immediately before any
   target mutation, closing source/target drift during staging;
6. execute the complete mandatory validation ladder against the staging
   candidate;
7. capture every target preimage—existence, regular-file type, mode and
   SHA-256—in a timestamped `.quantum-lab-v40-backup-*` directory;
8. atomically commit the ordered overlay, with `README.md` penultimate and
   `ui.py` last; and
9. authenticate and revalidate the installed V4.0 state.

Any commit or post-install failure restores captured preimages in reverse
order, removes only destinations proven to have been newly created by this
invocation, and reauthenticates the exact V3.9 predecessor. A changed backup,
unsafe destination or incomplete predecessor restoration makes rollback fail
closed and is reported explicitly. The private stage is removed only by its
owner; the backup remains available for audit. The installer releases only
the lock whose ownership token it still controls.

Preflight is read-only. `NO_OP` is reserved for byte-exact V4.0 reapplication;
it is never used to excuse an incomplete, mixed or drifted target.

## Mandatory validation ladder

The candidate and installed target must pass the scientific, release-chain,
freeze, UI and inherited-regression gates with non-zero process status on any
failure:

```bash
python3 -m unittest quantum_research_lab.test_phase3_v40
python3 -m unittest quantum_research_lab.test_phase3_v40_release
python3 -m quantum_research_lab.verify_phase3_v40 .
python3 -m quantum_research_lab.verify_freeze_contract_v40 . --contract FREEZE_CONTRACT_V4_0.json
python3 -m quantum_research_lab.verify_phase3_v40_ui app_v40_offline_harness.py --timeout 180
python3 -m unittest quantum_research_lab.test_phase3_gate_compiler quantum_research_lab.test_phase3_algorithmic_contract quantum_research_lab.test_phase3_v34 quantum_research_lab.test_phase3_v35 quantum_research_lab.test_phase3_v36 quantum_research_lab.test_phase3_v37 quantum_research_lab.test_phase3_v38 quantum_research_lab.test_phase3_v39
```

Scientific verification authenticates the V3.9-to-V3.1 chain, the frozen
V4.0 spec, C++ engine source and sealed artifact; checks both structural
replays; proves the nine-core/Hamming-distance-two identity on exhaustive
bounded universes; and verifies the exact all-seed ledger:

```text
feasible vertices       21,655,776
undirected graph edges  337,710,603
nine-core incidences    216,557,760 = 10 × vertices
connected seeds         6 / 8
disconnected seeds      2207, 7703
isolated portfolios     3
direct neighbor audits  900 / 900 rejected
```

Deployment validation authenticates the already completed full-size dual
replay; it does not silently rerun the 21.7-million-vertex confirmatory study
from the Streamlit session. Recomputing or overwriting the sealed artifact is
outside the deployment path.

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

The initial and positive-rerun AppTest snapshots must reproduce this order.
The four entries after `QMC / RISK` are its nested views; together with the
eight principal tabs they form the exact 12-tab visible contract. V4.0 is an
additive panel inside `PHASE III / QPU`, after the preserved V3.4–V3.9 lineage.

The positive-rerun UI verifier requires zero Streamlit exceptions, exact
8-row connectivity, 3-row counterexample and 2-row V4.1-candidate ledgers,
the four authenticated downloads, all scientific override/recompute controls
disabled, all credential/backend controls disabled, stale provider state
cleared, and provider/transpile/seal spies at zero on every run. HTTP 200 by
itself is not UI acceptance.

## Scientific and execution boundary

V4.0's admissible decision is:

```text
global connectivity   GLOBAL_FEASIBLE_GRAPH_DISCONNECTED_COUNTEREXAMPLE
overall               V40_GLOBAL_CONNECTIVITY_COUNTEREXAMPLE_RESOURCE_REDESIGN_PREREGISTERED
production admission  REJECTED_CONNECTIVITY_AND_V39_RESOURCE_ARCHITECTURE
V4.1 resources        RESOURCE_ARCHITECTURE_PREREGISTERED_NOT_EVALUATED
next gate             AUGMENTED_1_2_EXCHANGE_GRAPH_CONNECTIVITY_OR_COUNTEREXAMPLE
```

The deployment is provider-free. Provider SDK import is false, credentials are
not read, provider calls are `0`, backend transpilation is `NOT_RUN`, QPU
submission is disabled, QPU jobs are `0`, and `hardware_executable=false`.
Optimization performance is `NOT_TESTED` and quantum advantage is
`NOT_CLAIMED`. The three isolated vertices refute connectivity of the frozen
one-swap graph only; they do not refute augmented mixers or quantum computing
in general.

SHA-256 commitments provide release integrity, not an external signature.
Without a detached signature anchored outside the package, provenance remains
`UNSIGNED_SHA256_INTEGRITY_ONLY`.
