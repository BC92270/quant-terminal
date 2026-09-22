# Quantum Lab V4.6 — transactional deployment

V4.6 is an append-only `RESEARCH_ONLY` overlay for an exact V4.5 target. It
adds the authenticated full-stream FakeMarrakesh routing result, its frozen
reference contracts, independent validation and institutional evidence UI.
It does not authorize provider discovery, credential access, simulator work or
QPU execution; `hardware_executable=false` remains mandatory.

## Accepted source and target states

The installer accepts only:

1. a source whose V4.6 freeze self-hash, 249-path inventory, ordered 22-path
   overlay and every transition byte authenticate exactly; and
2. a target whose exact V4.5 freeze and all 227 immutable predecessor paths
   authenticate, with README/UI either both at V4.5 or both at exact V4.6.

Mixed, partial, third-state, symlinked, duplicate or path-traversal states are
rejected. An exact V4.6 reapply is an explicit no-op.

## Preflight

From an extracted deployment overlay or the institutional source tree:

```bash
python3 install_quantum_lab_v46.py \
  --source /absolute/path/to/v46-source \
  --target /workspaces/quant-terminal
```

Preflight authenticates both roots and builds a complete temporary candidate
from the exact V4.5 target plus the authenticated V4.6 overlay. The independent
57-check scientific validator must pass inside that candidate before commit is
allowed.

## Apply

```bash
python3 install_quantum_lab_v46.py \
  --source /absolute/path/to/v46-source \
  --target /workspaces/quant-terminal \
  --apply
```

The installer acquires an owned-token lock, snapshots exact preimages, rehashes
the source immediately before and after commit, writes supporting evidence
first, updates `quantum_research_lab/README.md` penultimate and integrates
`quantum_research_lab/ui.py` last. Any error rolls committed paths back in
reverse order from hash-checked preimages. Backups and a deployment manifest
remain under `.quantum-lab-v46-backups/` for audit and recovery.

## Post-deployment verification

```bash
python3 -m quantum_research_lab.phase3_v46_validation \
  --root /workspaces/quant-terminal

python3 -m quantum_research_lab.verify_phase3_v46 \
  --root /workspaces/quant-terminal

python3 -m quantum_research_lab.verify_freeze_contract_v46 \
  --root /workspaces/quant-terminal

python3 -m unittest quantum_research_lab.test_phase3_v46 -v
```

The live route remains:

```text
?workspace=quantum-research
```

The expected authenticated release state is V4.6 with 57/57 scientific
validation checks, 36/36 standard-library checker obligations, 30/30 UI
authentication gates, 18/18 scientific unit tests, 38/38 release-chain checks
and 20/20 freeze checks. These counts prove only their named software and
evidence contracts—not current hardware readiness, calibration quality,
execution success, performance, utility or quantum advantage.

## Optional deterministic replay

The full replay consumes roughly 48.6 million input instructions and can take
substantial CPU time. It is not required for each page load or idempotent
deployment because its byte-exact result is already sealed. To repeat it in a
clean process:

```bash
fresh_dir="$(mktemp -d /tmp/quantum-v46-replay.XXXXXX)"
env -i PATH="$PATH" PYTHONPATH=/workspaces/quant-terminal \
  python3 -m quantum_research_lab.phase3_v46_full_stream_routing \
  --root /workspaces/quant-terminal \
  --output "$fresh_dir/replay.json"
```

Expected replay identities:

- raw SHA-256: `24a55be0ea90242318642b3db7fd00997a71bd8ce896a73e7118f12e65ce6694`
- semantic SHA-256: `cbf478af42b35502d4788f70aa96df836145d8e34dadf0c14f2426c241323832`

This replay is deterministic offline structural-compilation evidence only.
