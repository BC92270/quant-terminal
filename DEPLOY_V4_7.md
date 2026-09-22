# Quantum Lab V4.7 — transactional deployment

V4.7 is an append-only `RESEARCH_ONLY` overlay for an exact authenticated V4.6
target. It adds the pinned dated-properties evidence, strict normalized oracle,
fault-excluded routing candidate, dual full-stream replay, independent
verification and institutional evidence UI. It does not authorize provider
discovery, credential access, network activity, simulator work or QPU
execution; `hardware_executable=false` remains mandatory.

This guide deliberately does not duplicate a final freeze hash, overlay count
or validation-check count before those values have been generated and
verified. The authoritative deployment identities are
`FREEZE_CONTRACT_V4_7.json` and the machine-readable outputs of the V4.7
verifiers. A source without those final authenticated identities is not a
deployable V4.7 release.

## Required release contents

An institutional release must contain, at minimum:

- `FREEZE_CONTRACT_V4_7.json`;
- `install_quantum_lab_v47.py` and `build_quantum_lab_v47_release.py`;
- this deployment guide and the V4.7 architecture document;
- the raw and normalized dated-property evidence;
- the fault-excluded ordered-path oracle and frozen model/specification;
- the V4.7 optimizer, independent checker, validation and UI modules;
- release, scientific, freeze and UI-authentication tests/verifiers;
- the sealed V4.7 artifact and validation sidecars;
- the offline V4.7 harness; and
- the successor versions of `quantum_research_lab/README.md` and
  `quantum_research_lab/ui.py`.

The overlay inventory and write order must be taken from the freeze contract,
not reconstructed from this prose.

## Accepted source and target states

The installer must accept only:

1. a source whose V4.7 freeze self-hash, frozen inventory, ordered overlay and
   every transition byte authenticate exactly against the trusted, out-of-band
   25-path raw source-tree SHA-256 emitted by the release manifest; and
2. a target whose exact V4.6 freeze and all immutable V4.6 predecessor paths
   authenticate, with successor-mutable surfaces either both at V4.6 or both
   at exact V4.7.

Mixed, partial, unknown, third-state, symlinked, duplicate-key,
path-traversal, ancestor/descendant source-target and broad filesystem-root
states must be rejected. A target already at exact V4.7 is an explicit,
validated no-op; it must not be rewritten.

Before deployment, record the final release evidence below from the generated
freeze and verifier output:

```text
V4.7 freeze semantic SHA-256:      SEE GENERATED FREEZE (NOT SELF-EMBEDDED)
V4.7 freeze raw-file SHA-256:      SEE GENERATED FREEZE (NOT SELF-EMBEDDED)
V4.7 frozen path count:            272
V4.7 frozen-path fingerprint:      ae031bfffbb63989a382fb03aef942481c1a1d685ff0b574217bfb8e4fb037aa
V4.7 ordered overlay path count:   25
V4.7 ordered overlay SHA-256:      fd79355920e5ea82da07a67de5c46623cab7b28ae6d1b34f830c372e66adc7c9
V4.7 25-path raw source-tree SHA:   SEE AUTHENTICATED RELEASE MANIFEST
V4.7 artifact semantic SHA-256:    fa1b8a2be1471080134f34ada7ba8cff488c87077a4e5f271fd29828f1fffbaf
V4.7 artifact raw-file SHA-256:    ddb8dae96c1d5fe1040f92731c995315e04232da645fed0b2d34cf7575a06185
Scientific validation checks:      96 / 96
Independent checker obligations:  51 / 51
Scientific unit tests:             26 / 26
UI authentication gates:          21 / 21
Streamlit positive-rerun checks:   42 / 42
Release-chain checks:              20 / 20
Release-hardening tests:           FINAL BUILDER GATE · 29 / 29 REQUIRED
Freeze checks:                     POST-GENERATION VERIFIER · 24 / 24 REQUIRED
```

The freeze cannot embed its own final raw or semantic hash without creating a
self-reference. Read those two identities from the generated contract and
release manifest, then confirm them with the 24-check freeze verifier. Every
numeric result above was emitted and independently rechecked before this guide
was frozen; the explicitly marked builder/freeze gates are verified only after
freeze generation.

## Environment and operational boundary

Deployment requires a local Python 3 environment capable of running the
standard-library validators and the existing application dependencies. The
runtime overlay must not install Qiskit, import a provider SDK, request a token
or contact the network.

The pinned `qiskit-ibm-runtime` wheel is a provenance input for optional
reference rebuilding; it is not required to render or validate an already
sealed release. The shipped raw and normalized evidence must be sufficient for
offline operation.

Use explicit absolute roots. Never target `/`, a home directory, the release
source itself or a parent/child of the source. For the live Codespace described
by this project, the expected target is:

```text
/workspaces/quant-terminal
```

## Preflight

From an extracted deployment overlay or authenticated institutional source
tree, first obtain `source_tree_raw_sha256` from an independently authenticated
copy of `QUANTUM_LAB_V4_7_RELEASE_MANIFEST.json`. Never calculate the expected
pin from the source tree you are about to install. Then run the installer
without `--apply`:

Before extraction, also compare the downloaded overlay archive SHA-256 with
`archives.overlay.sha256` in that same authenticated manifest. The release
archive builder rejects duplicate names, absolute/traversal paths and symlinks;
an unverified third-party extraction result is not an admitted source.

```bash
python3 install_quantum_lab_v47.py \
  --source /absolute/path/to/v47-source \
  --target /workspaces/quant-terminal \
  --expected-source-tree-raw-sha256 <TRUSTED_64_HEX_SOURCE_TREE_PIN>
```

Preflight must be read-only with respect to the target. It authenticates both
roots, rejects unsafe paths/states and builds a complete temporary candidate
from the exact target plus authenticated overlay. The final V4.7 scientific
validator must pass inside that candidate before commit is permitted. Before
executing source-controlled validation code, the installer authenticates the
external 25-path raw-tree pin, rejects forbidden provider/network/dynamic-code
imports in the executed validation modules, and supplies a scrubbed allowlist
environment with no inherited credentials or arbitrary secrets.

For a sparse 25-file overlay source, every predecessor digest committed by the
V4.7 freeze is resolved against and re-hashed from the exact target V4.6. For a
full institutional source, the same inventory can be authenticated entirely
from the source tree. Neither mode permits a missing or substituted predecessor
byte.

A successful preflight demonstrates only that the named source, predecessor,
candidate and software/evidence checks passed. It is not evidence of current
hardware readiness or scientific acceptance beyond those checks.

## Apply

Only after a clean preflight, apply the exact same source:

```bash
python3 install_quantum_lab_v47.py \
  --source /absolute/path/to/v47-source \
  --target /workspaces/quant-terminal \
  --expected-source-tree-raw-sha256 <SAME_TRUSTED_64_HEX_SOURCE_TREE_PIN> \
  --apply
```

The transactional installer is expected to:

1. acquire an owned-token V4.7 lock and reject residual predecessor locks;
2. snapshot and hash exact preimages of every path it may supersede;
3. reauthenticate the externally pinned raw source tree immediately before
   commit;
4. write machine evidence and implementation files before human surfaces;
5. update `quantum_research_lab/README.md` penultimate;
6. update `quantum_research_lab/ui.py` last;
7. reauthenticate the committed target as exact V4.7; and
8. retain a deployment manifest and exact backups under the V4.7 backup
   directory.

Any exception during commit must trigger reverse-order rollback from
hash-checked preimages. An installer report is successful only when it states
`valid=true`, the target state is exact V4.7 and rollback errors are absent.

Do not manually copy a subset of overlay files. A partially updated evidence
surface can display decisions that the integration surface has not
authenticated.

## Post-deployment verification

Run every named verifier from the deployed target:

```bash
cd /workspaces/quant-terminal

python3 -m quantum_research_lab.phase3_v47_validation \
  --root /workspaces/quant-terminal

python3 -m quantum_research_lab.verify_phase3_v47 \
  --root /workspaces/quant-terminal

python3 -m quantum_research_lab.verify_freeze_contract_v47 \
  --root /workspaces/quant-terminal

python3 -m unittest quantum_research_lab.test_phase3_v47 -v

QUANTUM_LAB_V46_ARCHIVE=/absolute/path/to/Quantum_Lab_V4_6_Institutional_Release.zip \
  python3 -m unittest quantum_research_lab.test_phase3_v47_release -v
```

The 29-test release-hardening suite deliberately reconstructs pristine V4.6
targets to exercise every commit position and rollback phase. Its fixture must
therefore be the exact authenticated V4.6 institutional archive; the explicit
environment variable makes that dependency portable without embedding or
silently downloading a predecessor package. A missing or different fixture is
a failed hardening run, not a reason to skip those tests. The accepted fixture
raw SHA-256 is
`bb21a0ee147734b0d4fa3585c96740fd7fcb2a57a966dade9db6f43aec9390ba`.
The final control also extracts the exact 25-file sparse deployment inventory,
authenticates all predecessor bytes against the target V4.6, performs the real
96-check candidate validation, applies the overlay, and proves the next apply
is an authenticated no-op.

If supplied as a dedicated module in the final overlay, also run the V4.7 UI
authentication verifier and the offline harness according to their `--help`
output. Record the exact passed/total counts from the commands; do not rely on
provisional counts in a document or earlier release.

The live route remains:

```text
?workspace=quantum-research
```

Refresh the Streamlit page after the process observes the changed files. If
the server does not hot-reload, restart only the application process through
the existing Codespace workflow; do not alter release evidence to force a
rerun.

## Live evidence acceptance

The deployed interface must, at minimum:

- identify V4.7 and `RESEARCH_ONLY` unambiguously;
- retain `hardware_executable=false` and zero provider/job claims;
- distinguish the historical bundled properties from current calibration;
- show the exact property timestamp range and source provenance;
- separate V4.6 baseline, V4.7 candidate, Pareto and architecture decisions;
- label modeled duration as an offline integer-`dt` estimate;
- label reported error mass as descriptive and not circuit fidelity;
- expose all eight seed rows and their evidence identities; and
- fail closed rather than render a scientific decision when authentication
  fails.

Browser rendering is additional evidence only. A visible panel cannot replace
artifact, freeze, scientific, release-chain or UI-authentication checks.

## Optional deterministic artifact replay

The V4.7 optimizer regenerates every admitted input instruction twice—once for
the exact V4.6 baseline and once for the fault-excluded candidate. The replay
therefore processes substantially more work than V4.6 and may require
considerable CPU time. It is not required on every page load or idempotent
deployment because the byte-exact result is sealed.

To replay in a clean output directory without mutating the frozen artifact:

```bash
fresh_dir="$(mktemp -d /tmp/quantum-v47-replay.XXXXXX)"

env -i PATH="$PATH" PYTHONPATH=/workspaces/quant-terminal PYTHONHASHSEED=0 \
  python3 -m quantum_research_lab.phase3_v47_dated_properties_optimizer \
  --root /workspaces/quant-terminal \
  --output "$fresh_dir/replay.json"
```

Compare both values emitted by the final sealed release:

```text
Expected replay raw SHA-256:       ddb8dae96c1d5fe1040f92731c995315e04232da645fed0b2d34cf7575a06185
Expected replay semantic SHA-256:  fa1b8a2be1471080134f34ada7ba8cff488c87077a4e5f271fd29828f1fffbaf
```

A mismatch is a failed replay even if high-level metrics look similar. A match
proves deterministic offline software reproduction only.

## Optional reference-oracle reproduction

Reference rebuilding must occur in a disposable copy, never in the installed
or frozen release tree. Supply the exact pinned wheel locally and preserve the
original builder timestamp so byte identities remain comparable:

```bash
python3 -m quantum_research_lab.phase3_v47_reference_builder \
  --wheel /absolute/path/to/qiskit_ibm_runtime-0.49.0-py3-none-any.whl \
  --root /absolute/path/to/disposable-v47-source \
  --created-utc 2026-09-20T19:30:00Z
```

The builder must reject any wheel other than SHA-256
`b29b4a0a5e013b6e6fd6556158fd34a05e2930dea870c60edef738b834977f2b`.
The extracted raw property bytes must be exactly 565,487 bytes with SHA-256
`d49d7ae07deb95947ea10e5b9b9c5cbab6df21f98610543817f35ade2b1aece6`.
Then compare normalized and path-oracle raw and semantic hashes with the sealed
V4.7 specification.

Reference reproduction performs no provider or hardware activity and must not
be described as a fresh calibration pull.

## Backup, rollback and recovery

Automatic rollback is part of the installer transaction. On a reported apply
failure:

1. preserve the complete installer output;
2. preserve the owned backup directory and deployment manifest;
3. confirm whether the report says `rolled_back=true` and whether
   `rollback_errors` is empty;
4. run the V4.6 freeze verifier against the target; and
5. do not retry until the source/target mismatch or residual lock has been
   understood.

There is no authorization in this guide for ad hoc deletion of locks, backups
or evidence. A residual lock may represent an interrupted transaction and must
be investigated before a new apply.

## Release acceptance record

Before declaring the Codespace deployed, retain together:

- source and target roots;
- package/overlay archive hash;
- installer preflight JSON;
- installer apply JSON and backup manifest;
- exact post-deployment verifier outputs;
- sealed artifact and freeze identities;
- idempotent second-preflight or second-apply no-op evidence; and
- live route audit results, including any Streamlit exception or browser error.

Even a complete acceptance record proves only the named V4.7 software,
lineage, evidence and model-scoped checks. Production admission remains
`OFFLINE_HISTORICAL_PROPERTIES_ONLY_HARDWARE_EXECUTION_REJECTED` unless a
future, separately authorized protocol changes that boundary.
