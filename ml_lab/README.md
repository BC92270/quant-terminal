# Institutional ML & Deep Learning Lab

This package contains the complete ML/DL research surface used by the Streamlit
application. The repository root keeps a single integration point:

    from ml_lab.research_lab import render_ml_research_lab_v1

## Structure

- research_lab.py — Streamlit router, labels and research workbench.
- institutional_engine.py — leakage, drift, promotion and registry controls.
- institutional_ui.py — readiness, governance, literature and monitoring views.
- modeling_engine.py — purged champion–challenger ML validation.
- deep_learning_lab.py — sequence experiment orchestration and exports.
- sequence_engine.py — executable sklearn full-window neural challengers.
- neural_backends.py — lazy PyTorch LSTM, GRU and causal Conv1D backends.
- requirements.txt — package-specific ML/DL runtimes.

## Launch

From the repository root:

    python -m pip install -r requirements.txt
    python -m streamlit run app.py --server.port 8501 --server.headless true

Then select **ML Research Lab** in the application. The advanced workbench and
Deep Learning Lab remain lazy-loaded so application startup does not import
PyTorch or TensorFlow.

## Neural runtimes

The model zoo exposes:

- full-window sklearn Sequence MLP, deep ensemble and temporal ensemble;
- PyTorch LSTM, GRU and causal Conv1D;
- TensorFlow MLP, LSTM, GRU and causal Conv1D;
- simple Dummy, Logistic and tree baselines under identical purged folds.

Neural models are challengers, not privileged champions. Promotion remains
blocked unless OOS performance, calibration, drift, costs and sample-size gates
all pass.

## Validation

    pytest -q tests/ml_lab
    pytest -q

The tests cover causal feature quarantine, purged splits, OOS uniqueness,
calibration, conformal abstention and executable neural backends.
