# Quantum Lab V4.2 · Deployment Runbook

## Release boundary

V4.2 is an append-only overlay for an exact V4.1 target. The installer accepts
only two target states: authenticated V4.1 or the exact installed V4.2 no-op
state. Mixed, partial, symlinked or unknown states are rejected.

The overlay does not install packages, access the network, inspect credentials,
discover providers, transpile circuits or submit QPU jobs.

## Preflight

From the extracted V4.2 release root:

```bash
python install_quantum_lab_v42.py --source . --target /workspaces/quant-terminal --preflight
```

Preflight authenticates:

- the V4.2 freeze self-hash and 177-file inventory;
- all 159 immutable V4.1 paths in the target;
- the exact V4.1 freeze identity;
- every source overlay byte;
- the target README/UI successor pair; and
- absence of partial or unsafe overlay destinations.

## Apply

```bash
python install_quantum_lab_v42.py --source . --target /workspaces/quant-terminal --apply
```

The installer acquires an owned lock, records preimage hashes, stages a complete
candidate release, runs identity validation, re-hashes the source immediately
before commit, copies supporting files first, README penultimate and `ui.py`
last, then executes the configured post-install checks. A failure restores the
authenticated preimages and removes newly created files.

## Idempotence

Reapplying the exact overlay is a verified no-op:

```bash
python install_quantum_lab_v42.py --source . --target /workspaces/quant-terminal --apply
```

Expected status: `NO_OP_ALREADY_EXACT_V4_2`.

## Verification

Identity-only release audit:

```bash
python -m quantum_research_lab.verify_phase3_v42 /workspaces/quant-terminal --identity-only
```

Deep scientific replay:

```bash
python -m quantum_research_lab.verify_phase3_v42 /workspaces/quant-terminal
```

Freeze audit:

```bash
python -m quantum_research_lab.verify_freeze_contract_v42 /workspaces/quant-terminal
```

Positive-rerun UI contract:

```bash
python -m quantum_research_lab.verify_phase3_v42_ui /workspaces/quant-terminal/app_v42_offline_harness.py --timeout 600
```

## Live application

Restart the existing Streamlit process using the repository's established
command, then open:

`?workspace=quantum-research`

Required live markers include:

- `data-qv42-auth="pass"`;
- `data-qv42-support="CONNECTED"`;
- `data-qv42-resource="PASSED"`;
- `data-qv42-production="RESEARCH_ADMITTED"`;
- `data-qv42-circuit="NOT_RUN_NEXT_GATE"`;
- `data-qv42-hardware="false"`;
- `data-qv42-provider-calls="0"`; and
- `data-qv42-jobs="0"`.

The visible PASS is limited to joint promise support and the selected-model
resource gate. Circuit materialization, backend transpilation and hardware
execution must remain visibly unrun/blocked.

## Rollback

Automatic rollback occurs on any post-commit verification failure. The lock is
released only by its owning token. Manual recovery must use the installer's
reported backup directory and verify every recorded preimage hash before
restoration; never replace the workspace wholesale.
