# Quantum Lab V4.4 · Institutional Deployment Runbook

## Release boundary

V4.4 is an append-only, transactional overlay for one exact V4.3 target. The
installer accepts only:

1. the authenticated V4.3 predecessor, including all 191 successor-immutable
   paths and the exact V4.3 `README.md` / `ui.py` surface pair; or
2. the complete byte-exact V4.4 state, which returns an authenticated no-op.

A partial, mixed, drifted, symlinked or unknown state fails closed. The
installer imports no provider SDK, reads no credentials, performs no network
request, rebuilds no canary, runs no full-workload transpilation and submits no
job. Candidate and post-install checks authenticate the already sealed V4.4
evidence with the environment available in the target.

Do not copy or extract the institutional archive over a live target. Extract
the deployment overlay into a distinct clean directory and invoke its
installer.

## Exact ordered overlay

The V4.3-to-V4.4 transition contains exactly 20 files:

1. `FREEZE_CONTRACT_V4_4.json`
2. `DEPLOY_V4_4.md`
3. `app_v44_offline_harness.py`
4. `install_quantum_lab_v44.py`
5. `build_quantum_lab_v44_release.py`
6. `outputs/quantum_phase3/v44_named_backend/SEALED_V4_4_NAMED_BACKEND_ZERO_JOB_ARTIFACT.json`
7. `quantum_research_lab/PHASE_III_V4_4_NAMED_BACKEND_ZERO_JOB_ROUTING_SPEC_V1.json`
8. `quantum_research_lab/PHASE_III_V4_4_FROZEN_BACKEND_SNAPSHOT_V1.json`
9. `quantum_research_lab/PHASE_III_V4_4_TOOLCHAIN_MANIFEST_V1.json`
10. `quantum_research_lab/QUANTUM_LAB_V4_4_ARCHITECTURE.md`
11. `quantum_research_lab/phase3_v44_named_backend_routing.py`
12. `quantum_research_lab/phase3_v44_validation.py`
13. `quantum_research_lab/phase3_v44_ui.py`
14. `quantum_research_lab/test_phase3_v44.py`
15. `quantum_research_lab/test_phase3_v44_release.py`
16. `quantum_research_lab/verify_freeze_contract_v44.py`
17. `quantum_research_lab/verify_phase3_v44.py`
18. `quantum_research_lab/verify_phase3_v44_ui.py`
19. `quantum_research_lab/README.md`
20. `quantum_research_lab/ui.py`

The human-readable README is committed penultimate; the executable integration
surface is committed last.

## 1. Prepare a clean overlay source

```bash
mkdir -p /tmp/quantum-lab-v44-overlay
cd /tmp/quantum-lab-v44-overlay
unzip /path/to/Quantum_Lab_V4_4_Deployment_Overlay.zip
```

The source and target must be distinct and non-nested. Do not edit, rename or
regenerate a release file after extraction.

## 2. Read-only preflight

```bash
python3 install_quantum_lab_v44.py \
  --source /tmp/quantum-lab-v44-overlay \
  --target /workspaces/quant-terminal \
  --preflight
```

Preflight must authenticate:

- the V4.4 freeze self-hash, 211-file inventory and path fingerprint;
- every one of the 20 source payloads;
- the exact raw and semantic V4.3 freeze;
- all 191 successor-immutable V4.3 target files;
- the exact V4.3 surface pair or exact complete V4.4 no-op state;
- safe regular non-symlink paths; and
- distinct non-broad source and target roots.

Do not proceed unless `valid` is true and the target state is exactly `V4.3`.

## 3. Transactional apply

```bash
python3 install_quantum_lab_v44.py \
  --source /tmp/quantum-lab-v44-overlay \
  --target /workspaces/quant-terminal \
  --apply
```

The installer acquires an owned lock before target-sensitive checks, creates a
private complete candidate, verifies its frozen identity and runs the staged
validation ladder before the first live mutation. It then re-hashes the source
and stage, records every destination preimage and file mode, writes self-hashed
preimage and install-intent manifests, and commits 20 files atomically in the
registered order.

Every live destination is rechecked against its locked preimage immediately
before replacement. Installed bytes are re-hashed before post-install tests.
No `--skip`, validation bypass or force-overwrite mode exists.

Expected status:

```text
APPLIED_AND_VERIFIED
```

## 4. Exact no-op reapply

Run the same apply command again. Expected status:

```text
NO_OP_ALREADY_EXACT_V4_4
```

The no-op is permitted only after the full V4.4 surface and all overlay bytes
authenticate. It performs no target write.

## 5. Independent installed verification

```bash
cd /workspaces/quant-terminal
python3 -m quantum_research_lab.verify_phase3_v44 . --identity-only
python3 -m quantum_research_lab.verify_freeze_contract_v44 .
python3 -m unittest quantum_research_lab.test_phase3_v44
python3 -m quantum_research_lab.verify_phase3_v44_ui \
  /workspaces/quant-terminal/app_v44_offline_harness.py --timeout 600
```

Identity-only verification authenticates the frozen 37-check scientific
commitment; it does not claim a fresh Qiskit replay. The UI harness must finish
with 26/26 checks, two exception-free snapshots, 12 tabs, 8 V4.4 evidence
tables, 12 metric cards, 12 disabled governance controls and 10 downloads.

The live Codespace does not need Qiskit to display or authenticate V4.4. A new
toolchain replay is a separate scientific operation and must use the exact
manifested Qiskit 2.5.2 environment:

```bash
python3 -m quantum_research_lab.phase3_v44_named_backend_routing \
  --root /workspaces/quant-terminal --canary-json
```

Do not install or upgrade packages in the production Codespace merely to turn
an identity deployment check into a fresh scientific replay.

## 6. Live application audit

Restart the existing Streamlit process with the repository's established
command and open `?workspace=quantum-research`. Verify the `PHASE III / QPU`
tab after the preserved V3.4–V4.3 lineage.

The live surface must show:

- `fake_marrakesh` as a pinned offline target, not a live provider;
- `156` target qubits and `352` directed coupling edges;
- all eight logical widths and exact negative deficits;
- `8 / 8 REJECTED` before full transpilation;
- the 160-qubit persistent floor and `−4` structural deficit;
- five canaries passing target ISA and coupling checks;
- two identical clean-process canary bundle hashes;
- the 157-qubit negative canary rejected;
- full transpilation, routing, native counts and depth visibly `NOT_RUN`;
- provider SDK false, credentials false, provider/network calls 0, QPU jobs 0;
- hardware false, calibration and performance not tested, advantage not claimed;
- all sensitive controls disabled; and
- the exact proof-carrying width-reduction next gate.

HTTP 200 or a visible panel alone is not acceptance. Inspect the positive final
rerun, machine-readable boundary hooks, visible tables and disabled controls.

## Rollback

Any commit or post-install failure triggers reverse-order rollback only for
paths written by that invocation. Restoration requires the exact recorded
installed state and authenticated preimages. If an external mutation appears,
the installer refuses to overwrite it and reports rollback incomplete.

The timestamped backup, `PREIMAGE_MANIFEST.json` and `INSTALL_INTENT.json`
remain for audit. Never delete an unknown installer lock, restore the entire
workspace, or use the institutional archive as an overwrite payload.

## Scientific boundary after deployment

Deployment does not broaden the result. V4.4 is
`V44_FAKE_MARRAKESH_CAPACITY_REJECTED_CANARY_PIPELINE_VALIDATED_ZERO_JOB`.
FakeMarrakesh is an offline structural snapshot. Full workload transpilation
and routing were not run after the capacity rejection; calibration-aware
fidelity and optimization performance were not tested; hardware execution is
false; credential reads, provider calls, network calls and QPU jobs are zero;
quantum advantage is not claimed.
