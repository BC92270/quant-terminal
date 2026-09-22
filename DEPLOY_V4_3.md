# Quantum Lab V4.3 · Institutional Deployment Runbook

## Release boundary

V4.3 is a transactional, append-only overlay for one exact V4.2 target. The
installer accepts only:

1. the authenticated V4.2 predecessor, including all 175 paths immutable to a
   successor and the exact V4.2 `README.md` / `ui.py` surface pair; or
2. the exact complete V4.3 release, which returns an authenticated no-op.

A mixed, partial, drifted, symlinked or unknown target fails closed. The
installer does not install packages, access the network, inspect credentials,
discover a provider, select a backend, transpile a circuit or submit a QPU job.

**Never unzip or copy the institutional archive over the live target.** That
bypasses predecessor authentication, ordered commit and rollback. Extract the
archive into its own clean directory and invoke the installer from there.

## Exact overlay inventory

The V4.2-to-V4.3 transition contains exactly these 18 paths:

1. `FREEZE_CONTRACT_V4_3.json`
2. `DEPLOY_V4_3.md`
3. `app_v43_offline_harness.py`
4. `install_quantum_lab_v43.py`
5. `outputs/quantum_phase3/v43_reversible_circuit/SEALED_V4_3_REVERSIBLE_CIRCUIT_ARTIFACT.json`
6. `quantum_research_lab/PHASE_III_V4_3_REVERSIBLE_CIRCUIT_MATERIALIZATION_SPEC_V1.json`
7. `quantum_research_lab/QUANTUM_LAB_V4_3_ARCHITECTURE.md`
8. `quantum_research_lab/phase3_v43_reversible_circuit_ir.py`
9. `quantum_research_lab/phase3_v43_reversible_simulator.cpp`
10. `quantum_research_lab/phase3_v43_validation.py`
11. `quantum_research_lab/phase3_v43_ui.py`
12. `quantum_research_lab/test_phase3_v43.py`
13. `quantum_research_lab/test_phase3_v43_release.py`
14. `quantum_research_lab/verify_freeze_contract_v43.py`
15. `quantum_research_lab/verify_phase3_v43.py`
16. `quantum_research_lab/verify_phase3_v43_ui.py`
17. `quantum_research_lab/README.md`
18. `quantum_research_lab/ui.py`

Supporting evidence and verification paths are committed first. The
human-readable README is penultimate and the executable `ui.py` integration
surface is strictly last.

## 1. Prepare a clean source

Work from the extracted V4.3 release root, not from the live checkout. Use the
same Python interpreter for preflight, apply and verification.

```bash
cd /path/to/clean/Quantum_Lab_V4_3_Release
python3 --version
```

Do not edit, rename or regenerate any release file after extraction. A changed
source snapshot must fail the source identity gate.

## 2. Read-only preflight

```bash
python3 install_quantum_lab_v43.py \
  --source . \
  --target /workspaces/quant-terminal \
  --preflight
```

Preflight is read-only. It must authenticate:

- the V4.3 freeze contract and exact release inventory;
- every source overlay byte;
- the V4.2 freeze and sealed V4.2 artifact identities;
- all 175 V4.2 paths immutable to V4.3;
- the exact V4.2 predecessor surface pair or exact V4.3 no-op state;
- safe, distinct, non-nested source and target roots; and
- regular, non-symlink release and destination paths.

Do not proceed if the target is reported as mixed, partial or unknown. Restore
an independently authenticated V4.2 target first.

## 3. Transactional apply

```bash
python3 install_quantum_lab_v43.py \
  --source . \
  --target /workspaces/quant-terminal \
  --apply
```

The installer must acquire its owned lock before target-sensitive checks. It
builds a private complete candidate from the authenticated V4.2 target plus
the exact V4.3 overlay, sanitizes the Python validation environment, validates
the candidate, and then re-hashes source, stage and target under the same lock.

Before the first target mutation it records file existence, mode and SHA-256
preimages in a timestamped backup with a hashed preimage manifest. Commit uses
only the already validated stage. Each destination is rechecked before atomic
replacement; the README is committed penultimate and `ui.py` last.

No validation-skip or post-check bypass is an institutional deployment path.
Missing Python dependencies or a missing C++17 compiler are failures, not
permission to weaken the ladder.

## 4. Expected exact no-op

Reapply the same release after a successful installation:

```bash
python3 install_quantum_lab_v43.py \
  --source . \
  --target /workspaces/quant-terminal \
  --apply
```

Expected status:

```text
NO_OP_ALREADY_EXACT_V4_3
```

The no-op is allowed only after byte-exact V4.3 authentication. It must not
rewrite any target byte or excuse an incomplete overlay.

## 5. Independent verification

Run identity and freeze checks first:

```bash
cd /workspaces/quant-terminal
python3 -m quantum_research_lab.verify_phase3_v43 . --identity-only
python3 -m quantum_research_lab.verify_freeze_contract_v43 . \
  --contract FREEZE_CONTRACT_V4_3.json
```

Run the full independent scientific validation:

```bash
python3 -m quantum_research_lab.verify_phase3_v43 .
```

The accepted V4.3 report contains exactly `31 / 31` checks, the independent
C++17 counts (`107,520` arithmetic cases, `64` promise SELECT cases and `64`
roundtrips), eight authenticated stream manifests, and the required
`OFF_PROMISE_CLEANUP_REJECTED_WITH_WITNESS` negative control.

Run the positive-rerun Streamlit contract:

```bash
python3 -m quantum_research_lab.verify_phase3_v43_ui \
  /workspaces/quant-terminal/app_v43_offline_harness.py \
  --timeout 600
```

Finally run the V4.3 unit, release and inherited-regression suites configured
by the release. An identity-only result must remain labelled identity-only; it
cannot be reported as a fresh deep scientific replay.

## 6. Live application audit

Restart the existing Streamlit process with the repository's established
command, then open:

```text
?workspace=quantum-research
```

The V4.3 panel must render after the complete preserved V3.4–V4.2 lineage. The
live audit must confirm, at minimum:

- authenticated V4.3 evidence and all eight seed rows;
- `21,925,902` elementary instructions;
- maximum `1,158,046` CX and minimum margin `+1,341,954`;
- maximum logical allocation `339`;
- stream-manifest root beginning `9405dc3659aa`;
- register-map root beginning `315e7a7d8742`;
- independent validation `31 / 31`;
- promise cleanup accepted only inside its registered scope;
- off-promise cleanup visibly rejected with its witness;
- `RESEARCH_ONLY`, provider calls `0`, QPU jobs `0`;
- backend transpilation visibly `NOT_RUN`; and
- hardware false, performance not tested and advantage not claimed.

HTTP 200, a visible panel or a top-level PASS alone is not acceptance. Inspect
the final positive-rerun snapshot and the browser-visible boundary markers.

## Rollback and recovery

Any commit or post-install failure triggers reverse-order rollback of only the
paths touched by that invocation. The installer must reject rollback if a
destination or backup preimage changed unexpectedly; it must never overwrite
an external mutation merely to force restoration. Successful rollback ends by
reauthenticating the exact V4.2 predecessor.

The backup and hashed preimage manifest remain available for audit. Manual
recovery may use only the backup directory reported by that installer run,
after authenticating every recorded preimage and target condition. Never
restore the workspace wholesale, never delete an unknown lock, and never use
the institutional archive itself as a rollback payload.

## Scientific boundary after deployment

Deployment does not broaden the sealed claim. V4.3 remains provider-neutral
`RESEARCH_ONLY` circuit materialization. No provider SDK was imported, no
credentials were read, no backend was selected, no transpilation was run, no
QPU job was submitted, and `hardware_executable=false`. The next gate is the
separately governed
`NAMED_BACKEND_ZERO_JOB_TRANSPILATION_AND_ROUTING_PROTOCOL`.

