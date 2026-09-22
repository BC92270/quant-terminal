# Quantum Lab V3.5 — safe Codespace deployment

V3.5 is an additive, transactional overlay for the exact V3.4 Codespace
release. It installs a sealed zero-job backend-admission result and the related
institutional UI. It does not install Qiskit, read credentials, contact a
provider, transpile a circuit or submit a QPU job.

## 1. Extract outside the live checkout

Extract `Quantum_Lab_V3_5_Deployment_Overlay.zip` under a temporary directory.
Do not merge files manually before preflight.

## 2. Verify the archive identity

Compare the archive SHA-256 with the release manifest before extraction:

```bash
sha256sum Quantum_Lab_V3_5_Deployment_Overlay.zip
```

## 3. Run the read-only preflight

```bash
python install_quantum_lab_v35.py --target /workspaces/quant-terminal
```

Preflight authenticates the V3.4 freeze and scientific artifact, checks all 29
V3.4 frozen paths, and accepts the central README/UI only in one of two exact
states: frozen V3.4 or sealed V3.5. The other 27 V3.4 files must remain
byte-exact. It also validates every overlay source against the V3.5 freeze.

## 4. Apply transactionally

```bash
python install_quantum_lab_v35.py \
  --target /workspaces/quant-terminal \
  --apply
```

The installer:

1. creates a timestamped backup inside the target checkout;
2. replaces only the 15 declared overlay files through atomic `os.replace`;
3. runs the 14-test V3.5 core suite;
4. runs the independent 23-gate V3.5 release-chain verifier;
5. runs the eight-gate V3.5 release-freeze verifier; and
6. restores every changed path if any post-install verifier fails.

Keep the reported backup directory until the UI acceptance step is complete.

## 5. Validate the deployed UI

From `/workspaces/quant-terminal`, with the same Python environment used by the
running Streamlit service:

```bash
python -m quantum_research_lab.verify_phase3_v35_ui app.py \
  --timeout 180 \
  --evidence-mode NONE \
  --backend-class UNKNOWN \
  --circuit-stage PROVIDER_NEUTRAL

python -m quantum_research_lab.verify_phase3_v35 .

python -m quantum_research_lab.verify_freeze_contract_v35 . \
  --contract FREEZE_CONTRACT_V3_5.json
```

The acceptance targets are 19/19 UI checks, zero Streamlit exceptions, the
unchanged 12-tab contract, 23/23 release checks and 8/8 freeze checks. If the
app is still bootstrapping, rerun AppTest and require the positive final state;
absence of an exception alone is not acceptance.

## 6. Confirm the service, then inspect the route

```bash
curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8501/
```

Open `?workspace=quantum-research`, select `PHASE III / QPU`, and confirm the
V3.5 control room reports:

- `EVIDENCE MODE · NONE`;
- `BACKEND CLASS · UNKNOWN`;
- `CIRCUIT STAGE · PROVIDER_NEUTRAL`;
- `PRE-TRANSPILE PROVIDER LIMIT · REJECTED`;
- `ADMISSION VETO · ACTIVE`; and
- `QPU EXECUTION · ZERO JOBS`.

## Claim boundary after deployment

The installed artifact authenticates a model-admission negative result:
`149,405,532,710` selected-model CNOTs versus IBM's documented `5,000,000`
two-qubit-gate limit per circuit, or `29,881.106542x`. The numerator is not a
backend-native count or a lower bound. There is no real backend snapshot,
target transpilation, routing result, calibration-conditioned fidelity result,
hardware execution or quantum-advantage claim in V3.5.
