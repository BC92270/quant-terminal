# Quantum Lab V4.5 · Institutional Deployment Runbook

## Release boundary

V4.5 is an append-only, transactional successor to the exact V4.4 release.
It admits eight proof-carrying logical streams to the next offline backend gate;
it does not claim that those streams were reconstructed, transpiled, routed or
executed on hardware.

The installer accepts only:

1. the authenticated V4.4 predecessor, including all 209
   successor-immutable files and its exact `README.md` / `ui.py` pair; or
2. the complete byte-exact V4.5 state, which returns an authenticated no-op.

A partial, mixed, drifted, symlinked or unknown state fails closed. The
installer imports no provider SDK, reads no credentials, performs no network
request, reconstructs no workload, routes no circuit and submits no job.

Never extract the institutional archive over a live target. Extract the
deployment overlay into a separate clean directory and invoke its installer.

## Sealed scientific result

- Decision: `V45_PROOF_CARRYING_WIDTH_REDUCTION_PASSED_EXACT_PROMISE_PARITY`.
- Frozen logical widths: `135, 137, 133, 135, 137, 137, 145, 139`.
- Capacity target: `156` logical qubits; minimum margin: `11`.
- Materialized streams within the legacy budget: `8 / 8`.
- Worst provider-neutral stream: `2,499,790 CX`; remaining margin: `210 CX`.
- Artifact semantic SHA-256:
  `9ab980071cc247cdbc70e8f964ccfbb09c48997d1d14cc26148c39518facda45`.
- Artifact raw SHA-256:
  `f28f2975b83d38e32b285cac8c2b7506a07f6341739f3153bde01d42e1219257`.
- Register-liveness certificate semantic SHA-256:
  `93f119c6493fac2eb0e7d281db1842482201cd7a680cf8ca93b9fdcc69a53102`.

The exact registered promise is feasible `N=40, K=10` data plus two valid
binary addresses in `0..39`. Addresses `40..63` and other off-promise states
are outside the acceptance claim. The inherited negative cleanup witness is
retained.

## Exact ordered overlay

The V4.4-to-V4.5 transition contains exactly 20 files, in commit order:

1. `FREEZE_CONTRACT_V4_5.json`
2. `DEPLOY_V4_5.md`
3. `app_v45_offline_harness.py`
4. `install_quantum_lab_v45.py`
5. `build_quantum_lab_v45_release.py`
6. `outputs/quantum_phase3/v45_width_reduction/SEALED_V4_5_PROOF_CARRYING_WIDTH_REDUCTION_ARTIFACT.json`
7. `quantum_research_lab/PHASE_III_V4_5_PROOF_CARRYING_WIDTH_REDUCTION_SPEC_V1.json`
8. `quantum_research_lab/PHASE_III_V4_5_REGISTER_LIVENESS_CERTIFICATE_V1.json`
9. `quantum_research_lab/QUANTUM_LAB_V4_5_ARCHITECTURE.md`
10. `quantum_research_lab/phase3_v45_proof_carrying_width_reduction.py`
11. `quantum_research_lab/phase3_v45_width_proof_checker.py`
12. `quantum_research_lab/phase3_v45_validation.py`
13. `quantum_research_lab/phase3_v45_ui.py`
14. `quantum_research_lab/test_phase3_v45.py`
15. `quantum_research_lab/test_phase3_v45_release.py`
16. `quantum_research_lab/verify_freeze_contract_v45.py`
17. `quantum_research_lab/verify_phase3_v45.py`
18. `quantum_research_lab/verify_phase3_v45_ui.py`
19. `quantum_research_lab/README.md`
20. `quantum_research_lab/ui.py`

The README is committed penultimate and the executable integration surface is
committed last. The ordered-list SHA-256 is
`d1c59d3e9a83675d67cb62f6b20aa9ca3fa3494a1376fadf8aa8e0a873d8073f`.

## 1. Prepare a clean overlay source

```bash
mkdir -p /tmp/quantum-lab-v45-overlay
cd /tmp/quantum-lab-v45-overlay
unzip /path/to/Quantum_Lab_V4_5_Deployment_Overlay.zip
```

The source and target must be distinct and non-nested. Do not edit, rename or
regenerate a release file after extraction.

## 2. Read-only preflight

```bash
python3 install_quantum_lab_v45.py \
  --source /tmp/quantum-lab-v45-overlay \
  --target /workspaces/quant-terminal \
  --preflight
```

Preflight must authenticate:

- the V4.5 freeze self-hash, 229-file inventory and exact path fingerprint;
- every one of the 20 source payloads;
- the exact raw and semantic V4.4 freeze;
- all 209 successor-immutable V4.4 target files;
- the complete V4.4 predecessor surface or complete V4.5 no-op state;
- contained regular non-symlink paths; and
- distinct, non-broad source and target roots.

Do not proceed unless `valid` is true and `successor_state` is exactly `V4.4`.

## 3. Transactional apply

```bash
python3 install_quantum_lab_v45.py \
  --source /tmp/quantum-lab-v45-overlay \
  --target /workspaces/quant-terminal \
  --apply
```

The installer acquires an owned lock, creates a private complete candidate,
authenticates its 229 frozen files and runs the staged validation ladder before
the first live mutation. It then re-hashes source and stage, records each
destination preimage and mode, writes self-hashed preimage and install-intent
manifests, and commits exactly 20 paths atomically in registered order.

Every live destination is checked against its locked preimage immediately
before replacement. Installed bytes are re-hashed before post-install tests.
No skip, bypass or force-overwrite mode exists.

Expected status:

```text
APPLIED_AND_VERIFIED
```

## 4. Exact no-op reapply

Run the same apply command again. Expected status:

```text
NO_OP_ALREADY_EXACT_V4_5
```

The no-op is permitted only after the full V4.5 state and every overlay byte
authenticate. It performs no target write.

## 5. Independent installed verification

```bash
cd /workspaces/quant-terminal
python3 -m quantum_research_lab.verify_phase3_v45 . --identity-only
python3 -m quantum_research_lab.verify_freeze_contract_v45 .
python3 -m unittest quantum_research_lab.test_phase3_v45
python3 -m quantum_research_lab.verify_phase3_v45_ui \
  /workspaces/quant-terminal/app_v45_offline_harness.py --timeout 600
```

The expected ladder is:

- release chain: `36 / 36`;
- immutable freeze: `18 / 18` over 229 files;
- scientific validation: frozen `51 / 51` commitment;
- scientific unit tests: `20 / 20`;
- Streamlit UI authentication: `28 / 28`, with two exception-free positive
  snapshots, 12 application tabs, 10 V4.5 downloads and 12 disabled V4.5
  governance controls;
- historical scientific tests: `161 / 161`;
- release hardening: `28 / 28`.

Identity-only verification authenticates the frozen 51-check scientific
commitment; it is not a fresh materialization. A fresh deterministic replay is
explicit and remains provider-free:

```bash
python3 -m quantum_research_lab.verify_phase3_v45 . --rebuild
```

Do not install or upgrade provider packages merely to validate this release.

## 6. Live application audit

Restart the existing Streamlit process and open
`?workspace=quantum-research`. In `PHASE III / QPU`, verify that V4.5 appears
after the preserved V3.4–V4.4 lineage and that the authenticated panel shows:

- all eight V4.3 and V4.5 widths;
- explicit register allocation and liveness ledgers;
- exact promise-subspace trace evidence;
- eight CNOT-budget passes and the worst-case margin;
- full reconstruction, transpilation and routing as `NOT_RUN_IN_V4_5`;
- provider SDK false, credential reads 0, provider/network calls 0 and jobs 0;
- hardware execution false, performance not tested and advantage not claimed;
- all sensitive controls disabled; and
- the exact next gate
  `PINNED_FAKEMARRAKESH_FULL_RECONSTRUCTION_TRANSLATION_AND_ROUTING_OF_WIDTH_ADMITTED_V4_5_STREAMS`.

HTTP 200 or a visible panel alone is not acceptance. Inspect the positive
final rerun, machine-readable boundary hooks, tables and disabled controls.

## Rollback

Any commit or post-install failure triggers reverse-order rollback only for
paths written by that invocation. Restoration requires exact recorded
installed states and authenticated preimages. If an external mutation appears,
the installer refuses to overwrite it and reports rollback incomplete.

The timestamped backup, `PREIMAGE_MANIFEST.json` and `INSTALL_INTENT.json`
remain for audit. Never delete an unknown installer lock or restore an entire
workspace to repair one failed overlay.

## Scientific boundary after deployment

Deployment does not broaden the V4.5 result. FakeMarrakesh remains a pinned
offline structural target inherited for capacity only. Full V4.5 reconstruction,
translation, layout and routing were not run; native CZ counts and routed
depth are not measured; current calibration and optimization performance are
not tested; hardware executability is false; provider SDK imports, credential
reads, provider calls, network calls and QPU jobs are zero; quantum advantage
is not claimed; classification remains `RESEARCH_ONLY`.
