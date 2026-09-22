# Quantum Lab V3.9 deployment contract

V3.9 is an additive, fail-closed successor to the exact V3.8 institutional
release. It evaluates a preregistered scalable reversible-IR and selected-model
resource lane for the eight frozen `N=40, K=10, BANDS` seeds. Its decision is
derived from the sealed evidence and is not assumed by this deployment layer.

Regardless of the derived resource result, complete feasible-graph
connectivity remains `INDETERMINATE`, production admission remains blocked by
connectivity and backend gates, `hardware_executable=false`, provider calls and
QPU jobs remain zero, and quantum advantage is not claimed.

## Exact predecessor and successor states

The installer accepts only:

1. the exact V3.8 freeze, all 112 immutable V3.8 frozen paths, and the exact
   V3.8 README/UI pair; or
2. the exact complete V3.9 overlay, in which case reapplication is a verified
   `NO_OP`.

The V3.8 parent identity is fixed by its raw and canonical semantic freeze
hashes, 114-path count, path fingerprint, and README/UI hashes. Mixed surface
pairs, unknown third states, changed predecessor bytes, partial V3.9 paths,
duplicate or non-finite JSON, symlinked paths, path traversal, broad roots and
nested source/target roots fail closed.

## Preflight and apply

Run from an extracted V3.9 institutional release:

```bash
python3 install_quantum_lab_v39.py --source . --target /workspaces/quant-terminal
python3 install_quantum_lab_v39.py --source . --target /workspaces/quant-terminal --apply
```

Use the same Python interpreter for preflight, apply and verification. The
installer records that interpreter in every validation command; missing
runtime dependencies therefore fail closed instead of silently selecting a
different environment.

On apply, the installer:

1. acquires `.quantum-lab-v39-install.lock` atomically with an ownership token;
2. authenticates the source and the V3.8/V3.9 target state;
3. constructs a private, self-contained 130-file V3.9 candidate from exact
   inherited target bytes and exact source-overlay bytes;
4. re-hashes the entire candidate and re-checks the source and target;
5. runs the mandatory validation ladder on the candidate before target
   mutation;
6. captures each target preimage, including existence, mode and SHA-256, into
   a timestamped `.quantum-lab-v39-backup-*` directory;
7. commits the 17-file overlay atomically, with
   `quantum_research_lab/README.md` penultimate and
   `quantum_research_lab/ui.py` last; and
8. authenticates and validates the installed V3.9 state.

Any commit or post-install failure restores the captured preimages in reverse
order and reauthenticates the exact predecessor. A lock that the current
installer did not create is never removed. The private candidate is removed
only by its owning invocation; the backup remains available for audit.

## Mandatory verification ladder

Normal installation executes these gates against both the private candidate
and the installed target. Scientific validation is exercised by the V3.9 unit
suite and independently by the release-chain verifier; the validation module
is not treated as a CLI until it exposes an explicit process exit contract.

```bash
python3 -m unittest quantum_research_lab.test_phase3_v39
python3 -m unittest quantum_research_lab.test_phase3_v39_release
python3 -m quantum_research_lab.verify_phase3_v39 .
python3 -m quantum_research_lab.verify_freeze_contract_v39 . --contract FREEZE_CONTRACT_V3_9.json
python3 -m quantum_research_lab.verify_phase3_v39_ui app_v39_offline_harness.py --timeout 180
python3 -m unittest quantum_research_lab.test_phase3_gate_compiler quantum_research_lab.test_phase3_algorithmic_contract quantum_research_lab.test_phase3_v34 quantum_research_lab.test_phase3_v35 quantum_research_lab.test_phase3_v36 quantum_research_lab.test_phase3_v37 quantum_research_lab.test_phase3_v38
```

The Streamlit route remains `?workspace=quantum-research`. Its exact 12-tab
contract is unchanged, and the V3.9 panel is additive after V3.8. Provider,
credential, transpilation, protocol-sealing and hardware controls remain
disabled for the authenticated BANDS lane.

## Freeze and package closure

`FREEZE_CONTRACT_V3_9.json` contains 129 raw-file commitments and a canonical
self-hash. The institutional archive contains those 129 files plus the freeze
itself, for 130 entries. The deployment overlay contains exactly the 17 ordered
transition paths used by the installer.

Expected deliverables:

- `Quantum_Lab_V3_9_Institutional_Release.zip`
- `Quantum_Lab_V3_9_Deployment_Overlay.zip`
- `QUANTUM_LAB_V3_9_RELEASE_MANIFEST.json`
- `QUANTUM_LAB_V3_9_VALIDATION_EVIDENCE.json`
- `QUANTUM_LAB_V3_9_RELEASE_REPORT.md`
- `QUANTUM_LAB_V3_9_PACKAGE_SHA256.txt`

Archive validation must require exact inventories, CRC success, no duplicate,
absolute or traversal entry, and byte equality with the freeze commitments.
SHA-256 manifests provide integrity only. Unless a detached signature anchored
outside the archive is supplied, the package classification is explicitly
`UNSIGNED_SHA256_INTEGRITY_ONLY` and must not be described as cryptographically
authenticated provenance.

## Scientific decision boundary

The release accepts only a decision derived from the frozen evidence:

- `N40_REVERSIBLE_IR_PASSED_RESOURCE_SCREEN_PASSED`;
- `N40_REVERSIBLE_IR_PASSED_RESOURCE_SCREEN_REJECTED`; or
- `N40_REVERSIBLE_IR_VALIDATION_FAILED`.

A passed 2,500,000-CNOT internal resource gate is not a proof of global
feasible-graph connectivity, named-backend routability, calibrated fidelity,
optimization performance or quantum advantage. V3.9 remains `RESEARCH_ONLY`
and provider-free.
