# Quantum Lab V3.6 · Codespace deployment runbook

## Scope

This overlay is additive over an exact V3.5 target. It preserves all historical
scientific artefacts and routes, replaces only the authorized README/UI
successor pair, and adds the provider-free V3.6 structural-reduction chain.
It does not install a provider SDK, read credentials, open a provider session,
transpile a named-backend circuit or submit a QPU job.

## Transaction

From the extracted V3.6 overlay root:

```bash
python install_quantum_lab_v36.py --target /workspaces/quant-terminal
python install_quantum_lab_v36.py --target /workspaces/quant-terminal --apply
```

The first command is a non-mutating preflight. The apply command:

1. acquires `.quantum-lab-v36-install.lock`;
2. authenticates the exact raw and semantic V3.5 freeze plus its 41-path
   inventory;
3. accepts only a coherent V3.5 or exact V3.6 README/UI state;
4. rejects duplicate JSON keys, path traversal, symlinks and non-regular files;
5. stages and re-hashes all 18 source files;
6. writes a timestamped backup with a hash-and-mode preimage manifest;
7. atomically replaces each file, with `quantum_research_lab/ui.py` last;
8. runs unit, negative release, release-chain, freeze and positive-rerun
   Streamlit checks; and
9. restores and re-hashes every preimage, then reruns V3.5 release/freeze
   verification, if any post-install control fails.

An exact V3.6 reapplication is an idempotent no-op. A stale lock is never
silently broken; its provenance must be investigated first.

## Independent acceptance

```bash
python -m unittest quantum_research_lab.test_phase3_v36 -v
python -m unittest quantum_research_lab.test_phase3_v36_release -v
python -m quantum_research_lab.phase3_v36_validation
python -m quantum_research_lab.verify_phase3_v36 /workspaces/quant-terminal
python -m quantum_research_lab.verify_freeze_contract_v36 \
  /workspaces/quant-terminal \
  --contract /workspaces/quant-terminal/FREEZE_CONTRACT_V3_6.json
python -m quantum_research_lab.verify_phase3_v36_ui \
  /workspaces/quant-terminal/app_v36_offline_harness.py --timeout 180
```

Acceptance additionally requires the live Streamlit DOM at
`?workspace=quantum-research` to expose the Phase III V3.6 control room,
`ARCHITECTURE_REWRITE_REQUIRED`, the topology-only rejection, the incremental
compiler block and the zero-job claim boundary. HTTP 200 alone is insufficient.

## Rollback evidence

The timestamped `.quantum-lab-v36-backup-*` directory is retained after a
successful install. It contains `PREIMAGE_MANIFEST.json`, prior bytes for every
overwritten path, file modes and a semantic manifest hash. Do not delete the
backup until the live UI and process working directory have been verified.

## Scientific boundary

The V3.6 result is structural and scoped to the frozen V3.4 selected 7T-CCX
accounting model. The 184,191,414-CNOT compute/uncompute pair is not a
backend-native or global lower bound. The 43,680-row incremental delta result
is classical evidence only; a clean reversible compiler remains absent.
