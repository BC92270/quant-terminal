import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from market_psychology.walk_forward import (
    _classify_holdout_replication,
    _build_mechanism_evidence_matrix,
    classify_alarm_predictive_evidence,
    classify_memory_predictive_status,
)


def test_strict_holdout_replication_requires_precision_not_just_same_sign():
    directional = _classify_holdout_replication(
        "ROBUST OOS", 0.29, 0.21, 0.34, -0.29, 0.64
    )
    assert directional == "DIRECTIONALLY CONFIRMED"

    replicated = _classify_holdout_replication(
        "ROBUST OOS", 0.29, 0.18, 0.04, 0.02, 0.31
    )
    assert replicated == "STATISTICALLY REPLICATED"


def test_opposite_sign_only_fails_when_holdout_is_informative():
    inconclusive = _classify_holdout_replication(
        "ROBUST OOS", 0.25, -0.08, 0.55, -0.31, 0.16
    )
    assert inconclusive == "INCONCLUSIVE"

    failed = _classify_holdout_replication(
        "ROBUST OOS", 0.25, -0.16, 0.03, -0.29, -0.02
    )
    assert failed == "FAILED REPLICATION"


def test_mechanism_evidence_matrix_marks_low_coverage_not_applicable():
    dev = pd.DataFrame([
        {"Mechanism":"Fear","Target":"Future vol","Horizon":"5D","Development evidence":"ROBUST OOS"},
        {"Mechanism":"Fear","Target":"Future vol","Horizon":"20D","Development evidence":"ROBUST OOS"},
        {"Mechanism":"Herding","Target":"Future vol","Horizon":"5D","Development evidence":"ROBUST OOS"},
    ])
    conf = pd.DataFrame([
        {"Mechanism":"Fear","Target":"Future vol","Horizon":"5D","Replication":"STATISTICALLY REPLICATED"},
        {"Mechanism":"Fear","Target":"Future vol","Horizon":"20D","Replication":"DIRECTIONALLY CONFIRMED"},
        {"Mechanism":"Herding","Target":"Future vol","Horizon":"5D","Replication":"STATISTICALLY REPLICATED"},
    ])
    coverage = pd.DataFrame([
        {"Mechanism":"Fear","Coverage":0.97},
        {"Mechanism":"Herding","Coverage":0.19},
    ])
    matrix, detail = _build_mechanism_evidence_matrix(dev, conf, coverage)
    fear = matrix[matrix["Mechanism"] == "Fear"].iloc[0]
    herding = matrix[matrix["Mechanism"] == "Herding"].iloc[0]
    assert fear["Future vol"] == "HIGH"
    assert herding["Future vol"] == "N/A"
    assert not detail.empty


def test_alarm_evidence_returns_none_when_no_fdr_survivor():
    frame = pd.DataFrame([
        {"Partition":"WALK_FORWARD","Alarm":"ATTENTION SHOCK","Horizon":"5D","Target":"Return","Event - baseline":0.01,"Bootstrap CI low":-0.01,"Bootstrap CI high":0.03,"Bootstrap p":0.5,"FDR q":0.9},
        {"Partition":"HOLDOUT","Alarm":"ATTENTION SHOCK","Horizon":"5D","Target":"Return","Event - baseline":0.02,"Bootstrap CI low":-0.01,"Bootstrap CI high":0.04,"Bootstrap p":0.4,"FDR q":np.nan},
    ])
    out = classify_alarm_predictive_evidence(frame)
    assert out.iloc[0]["Predictive validation"] == "NONE"
    assert out.iloc[0]["Operational role"] == "MONITORING / STATE ALERT"


def test_memory_role_stays_contextual_and_direction_only_does_not_promote_prediction():
    summary = pd.DataFrame([
        {"Partition":"WALK_FORWARD","Horizon":"60D","Return IC":-0.35,"Return p":0.001,"Vol IC":-0.20,"Vol p":0.04,"Tail IC":-0.46,"Tail p":0.001},
        {"Partition":"HOLDOUT","Horizon":"60D","Return IC":-0.001,"Return p":0.99,"Vol IC":-0.03,"Vol p":0.85,"Tail IC":-0.20,"Tail p":0.22},
    ])
    family = pd.DataFrame([
        {"Horizon":"60D","Metric":"Return","p":0.001,"q":0.003},
        {"Horizon":"60D","Metric":"Vol","p":0.04,"q":0.06},
        {"Horizon":"60D","Metric":"Tail","p":0.001,"q":0.003},
    ])
    out = classify_memory_predictive_status(summary, family)
    assert out["role"] == "CONTEXTUAL / DESCRIPTIVE"
    assert out["predictive_status"] == "NOT REPLICATED"
    assert out["development_fdr_survivors"] == 3
    assert out["holdout_statistical_replications"] == 0
