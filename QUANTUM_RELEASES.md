# Quantum Lab release index

This file is the single Explorer entry point for the immutable Quantum Lab
lineage. VS Code nests the historical deployment guides, freeze contracts,
offline harnesses, builders and installers beneath this document. The files
remain at their original paths because their names and bytes participate in
published SHA-256 contracts.

## Active line

| Release | Status | Surface | Decision |
|---|---|---|---|
| V4.8 | Published and frozen | `quantum_research_lab/` | `RESEARCH_ONLY_HARDWARE_EXECUTION_REJECTED` |
| V4.9 | Published and frozen | `quantum_research_lab/v49/` | `V49_NOT_EVALUABLE_INSUFFICIENT_AUTHENTIC_EPOCHS` |
| V5.0 | Published and frozen | `quantum_research_lab/v50/` | `V50_AUTHENTIC_EPOCH_GATE_PASSED_ARCHITECTURE_NO_GO` |

V5.0 adds a compact package, a versioned release directory and a sealed output
directory. It does not rename, move or rewrite any V3.1-V4.9 scientific path.

## Working locations

- Product and scientific code: `quantum_research_lab/v50/`
- Pinned raw evidence: `quantum_research_lab/v50/evidence/raw/`
- Sealed evidence: `outputs/quantum_phase3/v50_hardware_evidence_control/`
- Release engineering: `release/quantum_v50/`
- Historical lineage: expand this file in the VS Code Explorer

## Hard boundary

V5.0 closes the historical epoch-count gap with four byte-pinned snapshots, but
the unchanged architecture fails all 32 strict necessary-screen cells. The
section remains `RESEARCH_ONLY`, `hardware_executable=false`, the snapshots are
not current hardware evidence, provider credentials are not read, provider and
network calls remain zero, and no simulator, backend or QPU job is submitted.
