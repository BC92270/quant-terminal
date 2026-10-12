from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest


pytestmark = pytest.mark.filterwarnings(
    "ignore:is_sparse is deprecated:DeprecationWarning"
)


_APP = r'''
from types import SimpleNamespace
import numpy as np
import pandas as pd
from backtest_institutional.universal_workspace import render_universal_workspace

index = pd.bdate_range("2024-01-02", periods=140, tz="UTC")
close = 100.0 * np.cumprod(1.0 + 0.0004 + 0.006 * np.sin(np.linspace(0, 12, len(index))))
bars = pd.DataFrame(
    {
        "Open": close * 0.999,
        "High": close * 1.005,
        "Low": close * 0.995,
        "Close": close,
        "Volume": 2_000_000.0,
    },
    index=index,
)
bars.attrs.update(currency="USD", price_basis="raw")
render_universal_workspace(
    ticker="NVDA",
    bars=bars,
    cfg=SimpleNamespace(currency="USD", periods_per_year=252),
)
'''


def test_native_run_renders_authoritative_ledger_and_fail_closed_gate() -> None:
    app = AppTest.from_string(_APP, default_timeout=120).run()
    assert not app.exception
    run = next(
        button
        for button in app.button
        if button.label == "Exécuter dans le ledger universel"
    )
    app = run.click().run(timeout=120)
    assert not app.exception
    assert any(metric.label == "Capital final" for metric in app.metric)
    assert any("HOLD — DATA REQUIRED" in item.value for item in app.markdown)
    assert any("Universal event ledger" in item.value for item in app.markdown)


def test_python_mode_never_displays_native_result_as_code_execution() -> None:
    app = AppTest.from_string(_APP, default_timeout=120).run()
    app = next(
        button
        for button in app.button
        if button.label == "Exécuter dans le ledger universel"
    ).click().run(timeout=120)
    mode = next(radio for radio in app.radio if radio.label == "Point d’entrée")
    app = mode.set_value("Stratégie Python").run(timeout=120)

    assert not app.exception
    assert any("SANDBOX REQUIRED" in item.value for item in app.warning)
    assert any(metric.label == "Politique statique" for metric in app.metric)
    assert not any(metric.label == "Capital final" for metric in app.metric)
    assert any("n’a pas été exécuté" in item.value for item in app.info)
