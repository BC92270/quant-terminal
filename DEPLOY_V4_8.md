# Quantum Lab V4.8 · Institutional Release and Codespace Deployment

V4.8 is an append-only successor to the exact V4.7 release. It deploys an
exact controlled-adder architecture reduction, a strict authentic-snapshot
registry and a six-tab institutional evidence console. It does not authorize
provider discovery, credentials, simulator/backend execution or QPU work.

## Scientific result carried by the release

- Exact logical streams materialized: `8 / 8`.
- Frozen BasicSwap routes materialized: `8 / 8`.
- Exact equivalence cases: `28,240 / 28,240`.
- Aggregate CX: `19,251,104 → 6,474,096`.
- Aggregate routed CZ: `119,029,964 → 59,565,732`.
- Authentic snapshot epochs: `1 / 3`; multi-snapshot robustness is not
  evaluable.
- Optimistic duration and reported-error necessary screens: fail on `8 / 8`.
- Classification: `RESEARCH_ONLY`.
- `hardware_executable=false`.

The exact production decision is
`RESEARCH_ONLY_HARDWARE_EXECUTION_REJECTED`.

## Immutable release contract

| Contract item | Exact value |
|---|---|
| V4.7 institutional archive raw SHA-256 | `9724710ada013508e0b6af156841313532d3e09d889ae2120ca9e68598d1e9f4` |
| V4.7 freeze raw SHA-256 | `89dfc8f614955d4fe1c92cfd286ab04f4022d9eb69e566edf46a65e84aa81a3a` |
| V4.7 freeze semantic SHA-256 | `3f870a5ff89368d2000a58533fba395b0d077cc377cdc830fdc4b362f6465858` |
| V4.7 frozen paths | `272` |
| V4.7 immutable predecessor paths | `270` |
| V4.8 frozen paths | `295` |
| V4.8 frozen-path fingerprint | `99616a4c8a47f955f124265d4b316e81d8feba4b8ed808dee0d31540a5f446d2` |
| Ordered V4.8 overlay paths | `25` |
| Overlay order SHA-256 | `157ea72c59d642eda2bd48f50dd5c413e67d4ab9164638f0cc733022a3e0d843` |
| V4.8 artifact raw SHA-256 | `f6fcce00b9ce95cd9e30eeb938e243c308b5408255dc98556e8be45a36691f76` |
| V4.8 artifact semantic SHA-256 | `6df8440320e38e0bb73674f3ceb0f4bc179385d0d344c9521fa35f197504c55f` |
| Independent checks | `65 / 65` |
| Scientific validation | `96 / 96` |
| Scientific unit tests | `26 / 26` |
| Release-chain checks | `20 / 20` |
| Freeze checks | `24 / 24` |
| UI authentication | `24 / 24` |
| Streamlit positive-rerun checks | `42 / 42` |
| Release-hardening tests | `29 / 29` required |

The builder emits the final archive SHA-256 values and the ordered 25-path raw
source-tree identity into `QUANTUM_LAB_V4_8_RELEASE_MANIFEST.json` and
`QUANTUM_LAB_V4_8_PACKAGE_SHA256.txt`. Treat that manifest as the trusted
out-of-band source for deployment pins; never derive the expected installer
pin from the source tree being installed.

## Build and verify locally

Use the project Python environment containing Streamlit, NumPy, pandas and
Plotly. From the V4.8 source root:

```bash
python -m quantum_research_lab.test_phase3_v48

python -m quantum_research_lab.verify_phase3_v48 \
  --root . \
  --deep \
  --expected-artifact-raw-sha256 f6fcce00b9ce95cd9e30eeb938e243c308b5408255dc98556e8be45a36691f76 \
  --expected-artifact-sha256 6df8440320e38e0bb73674f3ceb0f4bc179385d0d344c9521fa35f197504c55f

python -m quantum_research_lab.verify_phase3_v48_ui \
  app_v48_offline_harness.py \
  --timeout 600

python build_quantum_lab_v48_release.py \
  --root . \
  --output-dir ../../outputs \
  --validation-report outputs/quantum_phase3/v48_multi_snapshot_architecture/SEALED_V4_8_VALIDATION_REPORT.json
```

The build is valid only when it:

1. authenticates the exact V4.7 freeze and all 270 immutable predecessor
   bytes;
2. validates the sealed clean-process replay report;
3. passes the 96 scientific, 20 release-chain, 42 UI and 24 freeze checks;
4. passes 26 scientific and 29 release-hardening tests;
5. builds both archives twice with identical SHA-256;
6. rejects duplicate, traversal and symlink ZIP entries; and
7. verifies CRC and exact member-byte equality.

Expected outputs:

- `Quantum_Lab_V4_8_Institutional_Release.zip` — 296 members: the 295 frozen
  files plus raw `FREEZE_CONTRACT_V4_8.json`;
- `Quantum_Lab_V4_8_Deployment_Overlay.zip` — 25 ordered transition files;
- `QUANTUM_LAB_V4_8_RELEASE_MANIFEST.json`;
- `QUANTUM_LAB_V4_8_PACKAGE_SHA256.txt`; and
- `QUANTUM_LAB_V4_8_RELEASE_REPORT.md`.

## Independent post-build verification

```bash
python -m quantum_research_lab.verify_freeze_contract_v48 --root .

python -m quantum_research_lab.verify_phase3_v48 \
  --root . \
  --deep \
  --expected-artifact-raw-sha256 f6fcce00b9ce95cd9e30eeb938e243c308b5408255dc98556e8be45a36691f76 \
  --expected-artifact-sha256 6df8440320e38e0bb73674f3ceb0f4bc179385d0d344c9521fa35f197504c55f

python -m unittest quantum_research_lab.test_phase3_v48
python -m unittest quantum_research_lab.test_phase3_v48_release
```

The reference bundle can be checked without rewriting it:

```bash
python -m quantum_research_lab.phase3_v48_reference_builder \
  --root . \
  --emit check
```

## Prepare a sparse deployment overlay

Extract the deployment archive into a new empty directory and verify it against
the release checksums:

```bash
mkdir -p /tmp/quantum-lab-v48-overlay
python - <<'PY'
from pathlib import Path
import zipfile

archive = Path("../../outputs/Quantum_Lab_V4_8_Deployment_Overlay.zip").resolve()
target = Path("/tmp/quantum-lab-v48-overlay").resolve()
with zipfile.ZipFile(archive) as payload:
    payload.extractall(target)
print(target)
PY
```

Before deployment, copy the `source_tree_raw_sha256` value from the
authenticated V4.8 release manifest into a shell variable. Do not calculate
the expected value from the extracted overlay.

```bash
V48_SOURCE_PIN='<manifest source_tree_raw_sha256>'
```

## Fail-closed preflight against the live Codespace

The only accepted target states are:

- exact V4.7 predecessor; or
- exact V4.8, which produces an idempotent no-op.

A mixed state, partial V4.8, unknown README/UI pair, altered immutable parent,
symlinked path, residual release lock or third state is rejected.

```bash
python /tmp/quantum-lab-v48-overlay/install_quantum_lab_v48.py \
  --source /tmp/quantum-lab-v48-overlay \
  --target /workspaces/quant-terminal \
  --expected-source-tree-raw-sha256 "$V48_SOURCE_PIN"
```

Required preflight result for a fresh promotion:

- `valid: true`;
- `state: V4.7`;
- `immutable_mismatches: []`;
- `partial_v48_paths: []`; and
- source raw identity equal to the trusted manifest pin.

## Transactional apply

```bash
python /tmp/quantum-lab-v48-overlay/install_quantum_lab_v48.py \
  --source /tmp/quantum-lab-v48-overlay \
  --target /workspaces/quant-terminal \
  --expected-source-tree-raw-sha256 "$V48_SOURCE_PIN" \
  --apply
```

The installer:

1. authenticates the raw 25-path source tree before importing release code;
2. statically rejects provider/network/environment-capable imports from the
   candidate verifier path;
3. constructs and validates a complete candidate tree in a scrubbed
   environment;
4. acquires an owned target lock;
5. rehashes source and predecessor under that lock;
6. stores hash-authenticated preimages;
7. commits evidence first, README penultimately and `ui.py` last;
8. authenticates the exact V4.8 target; and
9. rolls back to exact V4.7 on any failure.

A successful fresh apply reports `valid: true`, `applied: true`,
`rolled_back: false`, `state: V4.8` and a backup path.

## Mandatory idempotence pass

Run the identical apply command a second time. The required result is:

- `valid: true`;
- `applied: false`;
- `idempotent_no_op: true`; and
- `state: V4.8`.

Any other state is a deployment failure.

## Live verification and UI audit

From `/workspaces/quant-terminal`:

```bash
python -m quantum_research_lab.verify_freeze_contract_v48 --root .

python -m quantum_research_lab.verify_phase3_v48 \
  --root . \
  --deep \
  --expected-artifact-raw-sha256 f6fcce00b9ce95cd9e30eeb938e243c308b5408255dc98556e8be45a36691f76 \
  --expected-artifact-sha256 6df8440320e38e0bb73674f3ceb0f4bc179385d0d344c9521fa35f197504c55f

python -m quantum_research_lab.verify_phase3_v48_ui \
  app_v48_offline_harness.py \
  --timeout 600
```

Open `?workspace=quantum-research` and require:

- the original 12 outer tabs plus exactly six active V4.8 tabs;
- `SNAPSHOT REGISTRY`, `ROBUSTNESS`, `ARCHITECTURE / CZ`, `FRONTIER`,
  `PROVENANCE`, `GOVERNANCE`;
- visible `8 / 8` exact streams, `6,474,096` CX, `59,565,732` CZ,
  `28,240` equivalence cases and `1 / 3` authentic epochs;
- both optimistic necessary screens visibly failed;
- six raw-hash-gated JSON downloads;
- all ten governance controls disabled; and
- `RESEARCH_ONLY_HARDWARE_EXECUTION_REJECTED` with
  `hardware_executable=false`.

## Recovery

On an organic commit failure, inspect the installer JSON. A safe rollback has
`rolled_back: true` and `rollback_errors: []`. The backup directory contains
the exact preimages and its manifest. Do not manually mix files from V4.7 and
V4.8. If rollback authentication fails, stop the application, preserve the
target and backup as forensic evidence, and restore only from the exact
authenticated V4.7 institutional release.

## Non-claims

V4.8 is offline architecture and governance evidence. The dated snapshot is
not current calibration. Structural depth is not runtime. Additive error mass
is not fidelity. Resource reduction is not utility or advantage. Provider SDK
imports, credential reads, provider/network/backend calls, simulator jobs and
QPU jobs remain zero.
