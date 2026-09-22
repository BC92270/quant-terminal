# Quantum Lab V3.8 deployment contract

V3.8 is an additive, fail-closed successor to the exact V3.7 release. It seals
an elementary one-/two-qubit decomposition for the registered synthetic
`N=4, K=2` operator and separately records that N=40 admission remains blocked.
It performs no provider call, backend transpilation, credential read or QPU job.

## Required predecessor

The installer accepts only:

1. the exact V3.7 freeze, all 97 immutable V3.7 frozen files, and the exact
   V3.7 README/UI successor pair; or
2. the exact complete V3.8 overlay, in which case reapplication is a no-op.

Mixed README/UI states, an unknown successor, changed predecessor bytes,
symlinks, partial V3.8 destinations and active install locks fail closed.

## Preflight and apply

From the extracted release directory:

```bash
python3 install_quantum_lab_v38.py --source . --target /workspaces/quant-terminal
python3 install_quantum_lab_v38.py --source . --target /workspaces/quant-terminal --apply
```

The V3.8 transition is staged and committed transactionally. Existing target
bytes are copied to a timestamped `.quantum-lab-v38-backup-*` directory with a
preimage manifest. `quantum_research_lab/README.md` is committed penultimate and
`quantum_research_lab/ui.py` last. Any failed post-install gate restores and
reauthenticates every preimage. Exact reapplication is a verified no-op.

## Mandatory verification

The installer runs:

```bash
python3 -m unittest quantum_research_lab.test_phase3_v38
python3 -m unittest quantum_research_lab.test_phase3_v38_release
python3 -m quantum_research_lab.phase3_v38_validation
python3 -m quantum_research_lab.verify_phase3_v38 .
python3 -m quantum_research_lab.verify_freeze_contract_v38 . --contract FREEZE_CONTRACT_V3_8.json
python3 -m quantum_research_lab.verify_phase3_v38_ui app_v38_offline_harness.py --timeout 180
python3 -m unittest quantum_research_lab.test_phase3_gate_compiler quantum_research_lab.test_phase3_algorithmic_contract quantum_research_lab.test_phase3_v34 quantum_research_lab.test_phase3_v35 quantum_research_lab.test_phase3_v36 quantum_research_lab.test_phase3_v37
```

The Streamlit route remains `?workspace=quantum-research`; the exact 12-tab
contract is unchanged. The V3.8 panel is additive, immediately after V3.7.

## Scientific stop condition

The bounded decision is
`ELEMENTARY_PROTOTYPE_PASSED_N40_ADMISSION_BLOCKED`. Prototype cost is 3,632
CNOT only under the frozen N=4 selected model. N=40 selected-model CNOT remains
`NOT_ESTIMATED`, the 2.5M gate is `NOT_EVALUATED`, production admission is
`BLOCKED_INCOMPLETE_REVERSIBLE_IR`, `hardware_executable=false`, provider calls
and QPU jobs are zero, and quantum advantage is `NOT_CLAIMED`.
