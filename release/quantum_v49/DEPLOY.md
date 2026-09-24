# Quantum Lab V4.9 · deployment runbook

V4.9 is an additive successor to the authenticated V4.8 release. Historical
V3.1–V4.8 paths are never moved. Only the two declared successor surfaces,
`quantum_research_lab/README.md` and `quantum_research_lab/ui.py`, may replace
their V4.8 bytes.

## Build from a clean V4.8 checkout

```bash
python -m quantum_research_lab.v49.engine.evaluator --root .
python -m quantum_research_lab.v49.engine.validation --root .
python -m unittest discover -s quantum_research_lab/v49/tests -t . -v
python release/quantum_v49/build.py --root .
```

The deterministic overlay and manifest are written under
`release/quantum_v49/dist/`, keeping the repository root uncluttered.

## Install into a Codespace target

```bash
python release/quantum_v49/install.py \
  --source-root /path/to/authenticated-v49-source \
  --target-root /workspaces/quant-terminal
```

The installer authenticates the V4.8 freeze and artifact, rejects mixed
successor states, stages every file, backs up overwritten surfaces and rolls
back on failure. Re-running an identical overlay is idempotent.

## Required post-install checks

```bash
python -m py_compile quantum_research_lab/v49/engine/*.py \
  quantum_research_lab/v49/ui.py quantum_research_lab/ui.py
python -m unittest discover -s quantum_research_lab/v49/tests -t . -v
python -m streamlit run app.py --server.port 8501 --server.address 0.0.0.0
```

Open `?workspace=quantum-research`, select `PHASE III / QPU`, and verify the
V4.9 terminal dossier shows `1 / 3` authentic epochs, a required maximum of
`963` direct CX, provider discovery `DENIED`, V5 `CLOSED`,
`RESEARCH_ONLY`, and zero jobs.

## Non-claims

V4.9 does not perform current-provider discovery, read credentials, connect to
a network service, execute a simulator/backend/QPU job, or claim hardware
readiness, fidelity, utility or quantum advantage.
