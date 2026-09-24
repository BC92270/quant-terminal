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
| V4.9 | Active development | `quantum_research_lab/v49/` | Offline pre-hardware admission; fail closed |

V4.9 adds a compact package, a versioned release directory and a sealed output
directory. It does not rename, move or rewrite any V3.1-V4.8 path.

## Working locations

- Product and scientific code: `quantum_research_lab/v49/`
- Sealed evidence: `outputs/quantum_phase3/v49_pre_hardware_admission/`
- Release engineering: `release/quantum_v49/`
- Historical lineage: expand this file in the VS Code Explorer

## Hard boundary

Until every V4.9 admission gate passes, the section remains `RESEARCH_ONLY`,
`hardware_executable=false`, provider credentials are not read, provider and
network calls remain zero, and no simulator, backend or QPU job is submitted.
