# Quantum Lab V3.7 deployment contract

V3.7 is an additive, fail-closed successor to the exact V3.6 release. It seals a
provider-free reversible incremental-exposure prototype on the registered
synthetic `N=4, K=2` fixture. It does **not** admit the production `N=40`
compiler, an elementary one-/two-qubit decomposition, a selected-model CNOT
ledger, backend transpilation, hardware execution, or quantum advantage.

## Required predecessor

The installer accepts only one of two authenticated target states:

1. the exact V3.6 successor pair plus the 55 immutable V3.6 frozen files, the
   exact V3.6 freeze, and the 27-file historical support closure; or
2. the exact complete V3.7 overlay, in which case reapplication is a no-op.

Mixed README/UI states, unknown successors, symlinks, partial V3.7 overlays,
changed predecessor bytes, and stale install locks fail closed. The support
closure is labelled `V3.7_LEGACY_SUPPORT_SNAPSHOT_NOT_RETROACTIVE_V3.6_FREEZE`:
it repairs package completeness without rewriting V3.6 history.

## Preflight and apply

From the extracted overlay directory:

```bash
python3 install_quantum_lab_v37.py --source . --target /workspaces/quant-terminal
python3 install_quantum_lab_v37.py --source . --target /workspaces/quant-terminal --apply
```

The 45-file overlay (27 authenticated support-closure files plus 18 V3.7
transition surfaces) is staged and committed transactionally. A support path
that is absent from the known V3.6 packaged state is restored; a support path
that exists with any other hash is rejected. Existing target
bytes are copied to a timestamped `.quantum-lab-v37-backup-*` directory with a
preimage manifest. `quantum_research_lab/README.md` is replaced penultimate and
`quantum_research_lab/ui.py` last. A failed post-install gate restores and
reauthenticates every preimage.

## Mandatory verification

The installer runs these gates before reporting success:

```bash
python3 -m unittest quantum_research_lab.test_phase3_v37
python3 -m unittest quantum_research_lab.test_phase3_v37_release
python3 -m quantum_research_lab.phase3_v37_validation
python3 -m quantum_research_lab.verify_phase3_v37 .
python3 -m quantum_research_lab.verify_freeze_contract_v37 . --contract FREEZE_CONTRACT_V3_7.json
python3 -m quantum_research_lab.verify_phase3_v37_ui app_v37_offline_harness.py --timeout 180
python3 -m unittest quantum_research_lab.test_phase3_gate_compiler quantum_research_lab.test_phase3_algorithmic_contract quantum_research_lab.test_phase3_v34 quantum_research_lab.test_phase3_v35 quantum_research_lab.test_phase3_v36
```

The Streamlit route remains `?workspace=quantum-research`. The offline harness
stubs only unrelated market/provider surfaces; the sealed V3.7 compiler fixture
remains scientific evidence inside its declared prototype boundary.

## Scientific stop condition

The positive decision is `SMALL_INSTANCE_REVERSIBLE_PROTOTYPE_PASSED`. The
production decision remains `N40_REWRITE_ADMISSION_BLOCKED`, selected-model CNOT
is `NOT_ESTIMATED`, `hardware_executable=false`, provider calls and QPU jobs are
zero, and quantum advantage is `NOT_CLAIMED`.
