"""Validation-only V3.5 AppTest harness.

The real Phase-III UI and sealed artifacts are retained. Unrelated market labs
are replaced with explicit offline fixtures so UI acceptance cannot trigger
network activity. These fixtures are never scientific or backend evidence.
"""

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from quantum_research_lab import ui


ROOT = Path(__file__).resolve().parent
DYADIC = json.loads((ROOT / "SEALED_EXACT_DYADIC_BANDS_ORACLE.json").read_text())


ui._load_regime_cached = lambda ticker: (pd.DataFrame(), "OFFLINE_TEST_FIXTURE")
ui._mission_control = lambda *args, **kwargs: None
ui._regime_lab = lambda *args, **kwargs: None
ui._qmc_lab = lambda *args, **kwargs: st.tabs(
    [
        "PRICING & CONVERGENCE",
        "TAIL RISK / EXPOSURE",
        "QAE RESOURCE INTELLIGENCE",
        "ADVANTAGE FRONTIER",
    ]
)
ui._portfolio_lab = lambda *args, **kwargs: (None, None)
ui._information_lab = lambda *args, **kwargs: None
ui._benchmarks = lambda *args, **kwargs: None
ui._phase2_program = lambda *args, **kwargs: None
ui.qpu_phase2_gate = lambda: {
    "ready": True,
    "state": "HARDNESS GATE PASSED · OFFLINE UI FIXTURE",
    "reason": "Offline V3.5 UI fixture; excluded from scientific evidence.",
    "status": {"summary": {"completed": 120}},
    "eligible_families": pd.DataFrame(
        [
            {
                "N": 40,
                "Regime": "BANDS",
                "MILP median s": 10.0,
                "MILP p95 s": 20.0,
                "Heuristic hard fraction": 1.0,
                "Family gate": True,
                "Complete family": True,
                "Optimality certified fraction": 1.0,
            }
        ]
    ),
    "recommended_family": {"N": 40, "Regime": "BANDS"},
}
ui.qpu_family_encoding_audit = lambda *args, **kwargs: {
    "encoding_status": "BLOCKED · OFFLINE HISTORICAL BASELINE",
    "encoding_exactness": "Historical baseline; successor evidence rendered below.",
    "initial_state": "Dicke(N=40,K=10)",
    "mixer": "Guarded XY",
    "logical_qubits_min": 40,
    "economic_quadratic_terms": 780,
    "pairwise_exclusions": 0,
    "group_bands": 4,
    "factor_bands": 3,
    "logical_2q_interactions_p1_pretranspile": 780,
    "constraint_resource_envelopes": [],
    "hardware_executable": False,
}
ui.qpu_family_seed_audits = lambda *args, **kwargs: pd.DataFrame(
    [{"Seed": seed, "Encoding status": "OFFLINE FIXTURE"} for seed in DYADIC["family"]["seeds"]]
)
ui.bands_family_audit_summary = lambda *args, **kwargs: {
    "status": "FAMILY FIDELITY FAIL · FROZEN",
    "completed": 8,
    "exact": False,
    "table": pd.DataFrame(),
}
ui.bands_load_sealed_oracle = lambda *args, **kwargs: None
ui.bands_oracle_worker_status = lambda *args, **kwargs: {
    "status": "FROZEN",
    "selected_bits": None,
    "sealed": False,
}
ui.default_dyadic_root = lambda: ROOT
ui.family_dyadic_summary = lambda *args, **kwargs: {
    "status": "EXACT DYADIC FAMILY · OFFLINE FIXTURE",
    "exact": True,
    "completed": 8,
    "table": pd.DataFrame([{"Seeds": "8/8", "Exact": True}]),
    "resource_summary": DYADIC["resource_summary"],
}
ui.load_sealed_dyadic_oracle = lambda *args, **kwargs: DYADIC
ui.sealed_dyadic_oracle_path = lambda *args, **kwargs: ROOT / "SEALED_EXACT_DYADIC_BANDS_ORACLE.json"
ui.promote_dyadic_encoding = lambda encoding, artifact: dict(encoding)
ui.qpu_sdk_inventory = lambda: pd.DataFrame([{"SDK": "OFFLINE FIXTURE", "Status": "NOT USED"}])
ui.qpu_runtime_fingerprint = lambda: {"python": "fixture", "platform": "offline", "machine": "test"}
ui.qpu_backend_capacity = lambda *args, **kwargs: {
    "backend_qubits": 0,
    "capacity_ok": False,
    "reason": "No backend in offline UI fixture.",
    "required_logical_qubits_min": 40,
    "status": "WAITING",
}
ui.qpu_protocol_draft = lambda *args, **kwargs: {
    "status": "DRAFT · OFFLINE FIXTURE",
    "hardware_executable": False,
}


ui.render_quantum_research_lab(ticker="SPY", price_data=pd.DataFrame())
