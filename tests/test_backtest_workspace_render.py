from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest


pytestmark = pytest.mark.filterwarnings(
    "ignore:is_sparse is deprecated:DeprecationWarning"
)


_APP = r"""
import numpy as np
import pandas as pd
from backtest_lab import render_backtest_lab_mode

index = pd.bdate_range("2024-01-02", periods=180)
cycle = np.sin(np.linspace(0.0, 12.0, len(index)))
returns = 0.0004 + 0.006 * cycle
close = 100.0 * np.cumprod(1.0 + returns)
prices = pd.DataFrame(
    {
        "Open": close * 0.999,
        "High": close * 1.004,
        "Low": close * 0.996,
        "Close": close,
        "Volume": 4_000_000.0,
    },
    index=index,
)
prices.attrs.update(
    price_basis="adjusted_total_return",
    periods_per_year=252,
    interval_label="1d",
    data_source="deterministic_render_test",
)
render_backtest_lab_mode("NVDA", prices)
"""


def test_explicit_run_renders_the_complete_workspace_without_ui_errors() -> None:
    app = AppTest.from_string(_APP, default_timeout=120).run()
    assert not app.exception
    assert [button.label for button in app.button] == ["Lancer le backtest"]
    assert any("Configuration prête" in item.value for item in app.markdown)
    assert not app.tabs

    run_button = next(
        button for button in app.button if button.label == "Lancer le backtest"
    )
    app = run_button.click().run(timeout=120)

    assert not app.exception
    labels = [tab.label for tab in app.tabs]
    assert labels[:5] == [
        "Synthèse",
        "Résultats",
        "Transactions",
        "Validation",
        "Stress & capacité",
    ]
    assert labels[5:10] == [
        "Scénarios extrêmes",
        "Liquidité & capacité",
        "Exécution réaliste",
        "Marge & événements",
        "Causes & actions",
    ]
    assert labels[10] == "Preuves"
    assert labels[11:15] == ["Données", "Exécution", "Statistiques", "Gouvernance"]
    assert labels[15] == "Moteur universel"
    assert any(
        "Spirale de liquidité (liquidity trap) calculée" in item.value
        for item in app.success
    )
    automation_messages = [*app.success, *app.warning, *app.error]
    assert any("Automatisation moteur" in item.value for item in automation_messages)
    assert any(
        "Stress de marge désactivé" in item.value for item in app.info
    )
    assert any("Dernier run exécuté" in item.value for item in app.markdown)


def test_draft_change_keeps_the_last_executed_run_and_marks_it_dirty() -> None:
    app = AppTest.from_string(_APP, default_timeout=120).run()
    app = (
        next(button for button in app.button if button.label == "Lancer le backtest")
        .click()
        .run(timeout=120)
    )
    short_toggle = next(
        toggle for toggle in app.toggle if toggle.label == "Autoriser short"
    )
    app = short_toggle.set_value(True).run(timeout=120)

    assert not app.exception
    assert any("Modifications non exécutées" in item.value for item in app.markdown)
    assert any("dernier run exécuté" in item.value.lower() for item in app.warning)
    labels = [tab.label for tab in app.tabs]
    assert labels[:5] == [
        "Synthèse",
        "Résultats",
        "Transactions",
        "Validation",
        "Stress & capacité",
    ]
    assert labels[10] == "Preuves"
    assert labels[15] == "Moteur universel"
