# Quantum Lab V5.0 · deployment runbook

V5.0 is an additive successor to the authenticated V4.9 release. Historical
V3.1–V4.9 scientific and release paths are never moved. Only the three declared
successor surfaces — `QUANTUM_RELEASES.md`, `quantum_research_lab/README.md`,
and `quantum_research_lab/ui.py` — may replace their V4.9 bytes.

## Build from an exact V4.9 checkout

```bash
python -m quantum_research_lab.v50.engine.validation --root .
python release/quantum_v50/build.py --root .
python -m unittest discover -s quantum_research_lab/v50/tests -t . -v
python release/quantum_v50/build.py --root .
```

The deterministic overlay and manifest are written under
`release/quantum_v50/dist/`, keeping the repository root uncluttered.

## Install into a Codespace target

```bash
python release/quantum_v50/install.py \
  --source-root /path/to/authenticated-v50-source \
  --target-root /workspaces/quant-terminal
```

The installer authenticates the exact V4.9 freeze and artifact and then re-hashes
all 317 parent paths that V5.0 does not explicitly supersede. A missing,
symlinked or drifted immutable parent path aborts before any write. The three
allowed successor paths and all 34 transition paths are exact allowlists; path
traversal, mixed states and unknown target bytes are rejected. The installer
stages every file, backs up overwritten successor surfaces, writes atomically,
and rolls back on failure. It never deletes or resets unrelated target files.
Re-running the identical overlay is idempotent.

Two staged V5.0 candidates are recognized for exact in-place migration only:

- raw `7f14c39d5a981c364d6e0d9eab8913f3bdea5a6f6e7d3f0d4bb523b4aee9e39c`
  and semantic
  `7ea4daa73211daf6724f0a378363ad728bd79bfb6b83258ecef19fc2bf34b743`;
- raw `c95b5442f6fcb560ccf3b7af91d47d8d23c69afe283666ea17d2b58da927e4a6`
  and semantic
  `fa8acb511824cac448bec6a42b6c8b4b98f52571bec2a9b13f5fea7f595af6b5`.

Before writing, every existing transition file is re-hashed against its
authenticated candidate contract. Any other candidate, local drift, or mixed
state fails closed.

## Required post-install checks

```bash
python release/quantum_v50/build.py --root .
python -m py_compile quantum_research_lab/v50/engine/*.py \
  quantum_research_lab/v50/ui.py quantum_research_lab/ui.py
python -m unittest discover -s quantum_research_lab/v50/tests -t . -v
python -m quantum_research_lab.v50.engine.provider_gate --root . --status
```

Open `?workspace=quantum-research`, select `PHASE III / QPU`, and verify the
V5.0 surface shows `4 / 3` authentic historical epochs, `32 cells`, strict
cross-snapshot target `≤467 CX`, decision
`V50_AUTHENTIC_EPOCH_GATE_PASSED_ARCHITECTURE_NO_GO`, provider discovery
denied, V5 execution closed, `RESEARCH_ONLY`, and zero jobs.

## Non-claims

V5.0 does not treat bundled fake-provider snapshots as current hardware
evidence, perform live-provider discovery, read credentials, connect to a
provider service, execute a simulator/backend/QPU job, or claim fidelity,
runtime, hardware readiness, utility, or quantum advantage.
