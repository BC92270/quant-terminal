# Quantum Lab V3.4 — safe Codespace deployment

The V3.4 release is an additive overlay for a byte-authentic V3.3 checkout. The
installer does not submit a QPU job and does not touch credentials.

## 1. Extract the overlay

Extract the archive at any temporary path in the Codespace. Do not merge files
manually before preflight.

## 2. Run the read-only preflight

```bash
python install_quantum_lab_v34.py --target /workspaces/quant-terminal
```

Preflight requires the exact V3.1, V3.2 and V3.3 sealed parent artifacts and
accepts `ui.py` only if it is either the frozen V3.3 byte sequence or this exact
V3.4 successor. Any unrelated drift blocks installation.

## 3. Apply transactionally

```bash
python install_quantum_lab_v34.py \
  --target /workspaces/quant-terminal \
  --apply
```

The installer:

1. revalidates every source overlay file against `FREEZE_CONTRACT_V3_4.json`;
2. creates a timestamped backup inside the target checkout;
3. replaces the 15 declared files atomically;
4. runs both the independent 18-gate V3.4 release verifier and the 6-gate
   release-freeze verifier; and
5. rolls back every applied file if verification fails.

The successful JSON output reports the backup directory and complete verifier
stdout. Keep that backup until the Streamlit acceptance test passes.

## 4. Validate the deployed UI

From `/workspaces/quant-terminal`:

```bash
python -m quantum_research_lab.verify_phase3_v34_ui app.py --timeout 180
python -m quantum_research_lab.verify_freeze_contract_v34 . \
  --contract FREEZE_CONTRACT_V3_4.json
```

The UI acceptance target is 17/17 checks, zero exceptions and the unchanged
12-tab contract. The freeze target is 6/6 checks across 29 exact files. If market
data initialization is asynchronous, rerun AppTest after bootstrap and require
the positive final V3.4 state.

## Claim boundary after deployment

Deployment exposes a sealed provider-neutral elementary schedule. It does not
make that schedule backend-native. Named-backend transpilation, routing,
calibration, discrete synthesis of continuous RY angles, noise acceptance,
optimization performance, hardware execution and quantum advantage remain
blocked or unclaimed.
