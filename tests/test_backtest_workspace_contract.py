from __future__ import annotations

from types import SimpleNamespace
import re

import numpy as np
import pandas as pd

from backtest_institutional.workspace import (
    authoritative_snapshot,
    decision_view,
    gate_cards,
    public_label,
)


def test_public_labels_hide_implementation_versions() -> None:
    labels = [
        public_label("Institutional Backtest V7"),
        public_label("Walk-Forward / OOS Validation V2"),
        public_label("Benchmark Relative V3.5b · execution"),
        public_label("Signal Safety v2.6"),
    ]
    assert labels == [
        "Institutional Backtest",
        "Walk-Forward / OOS Validation",
        "Benchmark Relative · execution",
        "Signal Safety",
    ]
    assert not any(re.search(r"\b[Vv]\d", label) for label in labels)


def test_machine_decision_maps_to_one_stable_public_verdict() -> None:
    assert decision_view("RESEARCH APPROVED")["label"] == "APPROUVÉ POUR RECHERCHE"
    assert decision_view("CONDITIONAL REVIEW")["label"] == "REVUE CONDITIONNELLE"
    assert decision_view("REJECT / REDESIGN")["label"] == "À RECONCEVOIR"
    assert decision_view("HOLD — DATA REQUIRED")["label"] == "PREUVES REQUISES"


def test_gate_cards_preserve_state_but_sanitize_public_names() -> None:
    cards = gate_cards(
        {
            "checks": [
                {"gate": "Execution V7", "state": "PASS", "detail": "causal fills"},
                {"gate": "OOS V2", "state": "UNAVAILABLE", "detail": "DATA REQUIRED"},
            ]
        }
    )
    assert cards == [
        {
            "label": "Execution",
            "state": "PASS",
            "detail": "causal fills",
            "tone": "pass",
        },
        {
            "label": "OOS",
            "state": "UNAVAILABLE",
            "detail": "DATA REQUIRED",
            "tone": "hold",
        },
    ]


def test_gate_cards_translate_known_institutional_controls() -> None:
    cards = gate_cards(
        {
            "checks": [
                {
                    "gate": "Canonical event ledger",
                    "state": "PASS",
                    "detail": "complete",
                }
            ]
        }
    )
    assert cards[0]["label"] == "Ledger d’exécution canonique"


def test_authoritative_snapshot_prefers_the_executed_ledger() -> None:
    index = pd.bdate_range("2024-01-02", periods=4)
    executed = pd.DataFrame(
        {
            "nav": [100.0, 102.0, 99.0, 105.0],
            "return": [0.0, 0.02, -3.0 / 102.0, 6.0 / 99.0],
        },
        index=index,
    )
    misleading_legacy = pd.DataFrame(
        {
            "equity": [100.0, 500.0, 2_000.0, 9_000.0],
            "strategy_return": [0.0, 4.0, 3.0, 3.5],
        },
        index=index,
    )
    institutional = SimpleNamespace(execution=SimpleNamespace(daily=executed))

    snapshot = authoritative_snapshot(institutional, misleading_legacy, 252)
    assert snapshot["source"] == "ledger exécuté"
    np.testing.assert_allclose(snapshot["nav"], executed["nav"])
    np.testing.assert_allclose(snapshot["total_return"], 0.05)
    np.testing.assert_allclose(snapshot["max_drawdown"], 99.0 / 102.0 - 1.0)
