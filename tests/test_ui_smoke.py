from __future__ import annotations

import contextlib
import importlib
import pathlib
import sys
import types

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class _SessionState(dict):
    pass


class _Block:
    def __init__(self, st):
        self._st = st

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def __getattr__(self, name):
        return getattr(self._st, name)


class _FakeStreamlit(types.ModuleType):
    def __init__(self):
        super().__init__("streamlit")
        self.session_state = _SessionState()

    def subheader(self, *a, **k): pass
    def caption(self, *a, **k): pass
    def markdown(self, *a, **k): pass
    def dataframe(self, *a, **k): pass
    def plotly_chart(self, *a, **k): pass
    def warning(self, *a, **k): pass
    def info(self, *a, **k): pass
    def error(self, *a, **k): pass
    def success(self, *a, **k): pass
    def metric(self, *a, **k): pass
    def json(self, *a, **k): pass

    def form(self, *a, **k): return _Block(self)
    def expander(self, *a, **k): return _Block(self)
    def spinner(self, *a, **k): return _Block(self)
    def columns(self, spec, *a, **k):
        n = spec if isinstance(spec, int) else len(spec)
        return [_Block(self) for _ in range(n)]
    def tabs(self, names): return [_Block(self) for _ in names]

    def selectbox(self, label, options, index=0, **kwargs): return list(options)[index]
    def number_input(self, label, value=0, **kwargs): return value
    def form_submit_button(self, label, *a, **k):
        return str(label) == "Run long-history calibration & eligibility simulation"
    def segmented_control(self, label, options, default=None, **kwargs):
        return default if default is not None else list(options)[0]
    def toggle(self, label, value=False, **kwargs): return value
    def checkbox(self, label, value=False, **kwargs): return value
    def multiselect(self, label, options, default=None, **kwargs): return list(default or [])
    def download_button(self, *a, **k): return False


def _prices(seed=11, n=320):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2025-01-02", periods=n)
    returns = rng.normal(0.0003, 0.018, n)
    close = 100 * np.exp(np.cumsum(returns))
    spread = np.maximum(close * 0.004, 0.2)
    return pd.DataFrame({
        "date": dates,
        "open": close,
        "high": close + spread,
        "low": np.maximum(0.01, close - spread),
        "close": close,
        "volume": 1_000_000,
    })


def test_streamlit_renderer_smoke(monkeypatch):
    fake = _FakeStreamlit()
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    for name in list(sys.modules):
        if name.startswith("monte_carlo.ui"):
            del sys.modules[name]
    app = importlib.import_module("monte_carlo.ui.app")
    monkeypatch.setattr(
        app,
        "fetch_long_history",
        lambda **kwargs: (
            _prices(seed=99, n=900),
            {"provider": "test", "period": "10y", "status": "LIVE_FETCH", "ok": True, "warnings": [], "selected_rows": 900},
        ),
    )
    app.render_monte_carlo_advanced_lab("SMOKE", _prices(), analysis={})
    assert any(key.startswith("mc_v221c_result_SMOKE") for key in fake.session_state)


def test_uncertainty_interval_formatter_handles_float64_columns(monkeypatch):
    fake = _FakeStreamlit()
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    for name in list(sys.modules):
        if name.startswith("monte_carlo.ui"):
            del sys.modules[name]

    views = importlib.import_module("monte_carlo.ui.views")
    source = pd.DataFrame(
        [
            {"Metric": "Expected return", "Unit": "rate", "CI low": 0.0091, "Median": 0.0123, "CI high": 0.0187},
            {"Metric": "Barrier delta", "Unit": "pp", "CI low": -1.2, "Median": 0.5, "CI high": 2.4},
            {"Metric": "Shape", "Unit": "number", "CI low": 0.08, "Median": 0.11, "CI high": 0.19},
        ]
    )
    assert str(source["CI low"].dtype) == "float64"

    formatted = views._format_uncertainty_interval_table(source)

    assert formatted.loc[0, "CI low"] == "+0.91%"
    assert formatted.loc[1, "Median"] == "+0.50 pp"
    assert formatted.loc[2, "CI high"] == "0.1900"
    assert str(source["CI low"].dtype) == "float64"
    assert source.loc[0, "CI low"] == 0.0091


def test_options_risk_neutral_renderer_with_existing_result(monkeypatch):
    fake = _FakeStreamlit()
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    for name in list(sys.modules):
        if name.startswith("monte_carlo.ui"):
            del sys.modules[name]

    from monte_carlo.options_risk_neutral import black_scholes_price, build_options_risk_neutral_lab
    views = importlib.import_module("monte_carlo.ui.views")

    spot = 100.0
    rows = []
    for strike in np.arange(60.0, 141.0, 5.0):
        for option_type in ("call", "put"):
            price = black_scholes_price(spot, strike, 30.0 / 365.0, 0.04, 0.01, 0.25, option_type)
            rows.append(
                {
                    "strike": strike,
                    "option_type": option_type,
                    "bid": max(0.001, price - 0.03),
                    "ask": price + 0.03,
                    "last_price": price,
                    "open_interest": 500,
                    "volume": 50,
                    "implied_volatility": 0.25,
                    "expiration": "2026-09-04",
                    "valuation_date": "2026-08-05",
                }
            )
    rng = np.random.default_rng(8)
    path_returns = rng.normal(0.0002, 0.018, size=(800, 30))
    paths = np.concatenate([np.full((800, 1), spot), spot * np.exp(np.cumsum(path_returns, axis=1))], axis=1)
    lab = {"ticker": "OPTUI", "base": {"current_price": spot}, "paths_by_horizon": {30: paths}}
    result = build_options_risk_neutral_lab(
        lab,
        pd.DataFrame(rows),
        expiration="2026-09-04",
        risk_free_rate=0.04,
        dividend_yield=0.01,
        valuation_date="2026-08-05",
    )
    assert result["ok"]
    fake.session_state["mc_v251_options_result_OPTUI"] = result
    views._render_options_risk_neutral(lab, 30)


def test_options_surface_renderer_with_existing_result(monkeypatch):
    fake = _FakeStreamlit()
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    for name in list(sys.modules):
        if name.startswith("monte_carlo.ui"):
            del sys.modules[name]

    from monte_carlo.options_risk_neutral import black_scholes_price
    from monte_carlo.options_surface import build_multi_expiry_surface
    views = importlib.import_module("monte_carlo.ui.views")

    spot = 100.0
    chains = {}
    for expiration, dte, shift in (("2026-08-19", 14, 0.00), ("2026-09-04", 30, 0.01), ("2026-10-04", 60, 0.015)):
        rows = []
        for strike in np.arange(70.0, 131.0, 2.5):
            k = np.log(strike / (spot * np.exp((0.04 - 0.01) * dte / 365.0)))
            iv = 0.24 + shift + 0.10 * k * k - 0.06 * k
            for option_type in ("call", "put"):
                price = black_scholes_price(spot, strike, dte / 365.0, 0.04, 0.01, iv, option_type)
                rows.append(
                    {
                        "strike": strike,
                        "option_type": option_type,
                        "bid": max(0.001, price - 0.02),
                        "ask": price + 0.02,
                        "last_price": price,
                        "open_interest": 500,
                        "volume": 50,
                        "implied_volatility": iv,
                        "expiration": expiration,
                        "valuation_date": "2026-08-05",
                    }
                )
        chains[expiration] = pd.DataFrame(rows)
    lab = {"ticker": "SURFUI", "base": {"current_price": spot}, "paths_by_horizon": {}}
    result = build_multi_expiry_surface(
        lab,
        chains,
        list(chains),
        risk_free_rate=0.04,
        dividend_yield=0.01,
        contract_style="European",
        valuation_date="2026-08-05",
    )
    assert result["ok"]
    fake.session_state["mc_v254_surface_result_SURFUI"] = result
    views._render_options_volatility_surface(lab, 30)


class _StrictFormBlock(_Block):
    def __init__(self, st, form_key):
        super().__init__(st)
        self._form_key = str(form_key)

    def __enter__(self):
        self._st._form_stack.append(self._form_key)
        self._st._form_submits[self._form_key] = 0
        return self

    def __exit__(self, exc_type, exc, tb):
        current = self._st._form_stack.pop()
        assert current == self._form_key
        if exc_type is None:
            assert self._st._form_submits[self._form_key] >= 1, f"Form {self._form_key} has no submit button"
        return False


class _StrictFakeStreamlit(_FakeStreamlit):
    def __init__(self):
        super().__init__()
        self._widget_keys = set()
        self._form_stack = []
        self._form_submits = {}

    def _register(self, key):
        if key is None:
            return
        key = str(key)
        assert key not in self._widget_keys, f"Duplicate Streamlit key: {key}"
        self._widget_keys.add(key)

    def form(self, *a, **k):
        key = k.get("key") or (a[0] if a else None)
        self._register(key)
        return _StrictFormBlock(self, key)

    def selectbox(self, label, options, index=0, **kwargs):
        self._register(kwargs.get("key"))
        return list(options)[index]

    def number_input(self, label, value=0, **kwargs):
        self._register(kwargs.get("key"))
        return value

    def checkbox(self, label, value=False, **kwargs):
        self._register(kwargs.get("key"))
        return value

    def file_uploader(self, label, **kwargs):
        self._register(kwargs.get("key"))
        return None

    def form_submit_button(self, label, *a, **kwargs):
        self._register(kwargs.get("key"))
        assert self._form_stack, "Submit button rendered outside a form"
        self._form_submits[self._form_stack[-1]] += 1
        return False


def test_options_forms_have_unique_keys_and_submit_buttons(monkeypatch):
    fake = _StrictFakeStreamlit()
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    for name in list(sys.modules):
        if name.startswith("monte_carlo.ui"):
            del sys.modules[name]

    views = importlib.import_module("monte_carlo.ui.views")
    lab = {"ticker": "KEYCHECK", "base": {"current_price": 100.0}, "paths_by_horizon": {}}

    # Streamlit evaluates every tab body during a rerun. Rendering both forms in
    # the same pass must therefore neither reuse widget keys nor omit a submit.
    views._render_options_risk_neutral(lab, 30)
    views._render_options_volatility_surface(lab, 30)

    assert "mc_v251_options_ttl_KEYCHECK" in fake._widget_keys
    assert "mc_v254_surface_ttl_KEYCHECK" in fake._widget_keys
    assert fake._form_submits["mc_v251_options_form_KEYCHECK"] == 1
    assert fake._form_submits["mc_v254_surface_form_KEYCHECK"] == 1


def test_package_version_change_invalidates_cached_results(monkeypatch):
    fake = _FakeStreamlit()
    fake.session_state.update(
        {
            "mc_runtime_signature_STALE": "OLD|VERSION",
            "mc_v221c_result_STALE": {"engine_version": "OLD"},
            "mc_v221c_config_STALE": {"seed": 1},
            "mc_v251_options_result_STALE": {"version": "OLD"},
            "mc_v252_surface_result_STALE": {"version": "OLD"},
            "mc_v254_surface_result_STALE": {"version": "OLD"},
            "mc_v255_calibration_dataset_result_STALE": {"version": "OLD"},
            "mc_v260_heston_result_STALE": {"version": "OLD"},
            "mc_v260a_heston_result_STALE": {"version": "OLD"},
            "mc_v261_heston_sim_result_STALE": {"version": "OLD"},
            "mc_v261a_heston_sim_result_STALE": {"version": "OLD"},
            "unrelated_key": 7,
        }
    )
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    for name in list(sys.modules):
        if name.startswith("monte_carlo.ui"):
            del sys.modules[name]
    app = importlib.import_module("monte_carlo.ui.app")
    app._invalidate_versioned_session_state("STALE")
    assert "mc_v221c_result_STALE" not in fake.session_state
    assert "mc_v251_options_result_STALE" not in fake.session_state
    assert "mc_v252_surface_result_STALE" not in fake.session_state
    assert "mc_v254_surface_result_STALE" not in fake.session_state
    assert "mc_v255_calibration_dataset_result_STALE" not in fake.session_state
    assert "mc_v260_heston_result_STALE" not in fake.session_state
    assert "mc_v260a_heston_result_STALE" not in fake.session_state
    assert "mc_v261_heston_sim_result_STALE" not in fake.session_state
    assert "mc_v261a_heston_sim_result_STALE" not in fake.session_state
    assert fake.session_state["unrelated_key"] == 7
    assert fake.session_state["mc_runtime_signature_STALE"].endswith("MC-RISK-ENGINE-2.8.1A")


def test_calibration_dataset_renderer_with_existing_result(monkeypatch):
    fake = _FakeStreamlit()
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    for name in list(sys.modules):
        if name.startswith("monte_carlo.ui"):
            del sys.modules[name]

    from monte_carlo.options_risk_neutral import black_scholes_price
    from monte_carlo.options_surface import build_multi_expiry_surface
    from monte_carlo.calibration_dataset import build_calibration_dataset
    views = importlib.import_module("monte_carlo.ui.views")

    spot = 100.0
    chains = {}
    for expiration, dte, shift in (
        ("2026-08-21", 16, 0.00),
        ("2026-09-04", 30, 0.07),
        ("2026-10-16", 72, 0.01),
        ("2026-11-20", 107, 0.015),
        ("2027-01-15", 163, 0.018),
    ):
        rows = []
        for strike in np.arange(65.0, 136.0, 2.5):
            k = np.log(strike / (spot * np.exp((0.04 - 0.01) * dte / 365.0)))
            iv = 0.24 + shift + 0.10 * k * k - 0.06 * k
            for option_type in ("call", "put"):
                price = black_scholes_price(spot, strike, dte / 365.0, 0.04, 0.01, iv, option_type)
                rows.append({
                    "strike": strike,
                    "option_type": option_type,
                    "bid": max(0.001, price - 0.02),
                    "ask": price + 0.02,
                    "last_price": price,
                    "open_interest": 500,
                    "volume": 50,
                    "implied_volatility": iv,
                    "expiration": expiration,
                    "valuation_date": "2026-08-05",
                })
        chains[expiration] = pd.DataFrame(rows)
    lab = {"ticker": "DATAUI", "base": {"current_price": spot}, "paths_by_horizon": {}}
    surface = build_multi_expiry_surface(
        lab,
        chains,
        list(chains),
        risk_free_rate=0.04,
        dividend_yield=0.01,
        contract_style="European",
        valuation_date="2026-08-05",
    )
    assert surface["ok"]
    dataset = build_calibration_dataset(surface)
    assert dataset["training_points"] > 0
    fake.session_state["mc_v254_surface_result_DATAUI"] = surface
    fake.session_state["mc_v255_calibration_dataset_result_DATAUI"] = dataset
    views._render_calibration_dataset_governance(lab, 30)


def test_all_options_dataset_forms_have_unique_keys_and_submit_buttons(monkeypatch):
    fake = _StrictFakeStreamlit()
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    for name in list(sys.modules):
        if name.startswith("monte_carlo.ui"):
            del sys.modules[name]
    views = importlib.import_module("monte_carlo.ui.views")
    lab = {"ticker": "KEYDATA", "base": {"current_price": 100.0}, "paths_by_horizon": {}}

    views._render_options_risk_neutral(lab, 30)
    views._render_options_volatility_surface(lab, 30)
    views._render_calibration_dataset_governance(lab, 30)

    assert "mc_v255_dataset_event_policy_KEYDATA" in fake._widget_keys
    assert "mc_v255_dataset_submit_KEYDATA" in fake._widget_keys
    assert fake._form_submits["mc_v255_dataset_form_KEYDATA"] == 1


def test_heston_q_simulation_renderer_with_existing_result(monkeypatch):
    fake = _FakeStreamlit()
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    for name in list(sys.modules):
        if name.startswith("monte_carlo.ui"):
            del sys.modules[name]

    from monte_carlo.heston_calibration import HestonParameters, heston_call_prices
    from monte_carlo.heston_simulation import build_heston_q_simulation
    from monte_carlo.options_risk_neutral import implied_volatility
    views = importlib.import_module("monte_carlo.ui.views")

    spot, r, q = 100.0, 0.03, 0.01
    params = HestonParameters(1.8, 0.045, 0.55, -0.65, 0.05)
    rows = []
    for expiration, dte in (("2026-09-04", 30), ("2026-11-20", 107)):
        t = dte / 365.0
        strikes = np.asarray([85.0, 95.0, 100.0, 105.0, 115.0])
        calls = heston_call_prices(spot, strikes, t, r, q, params, quadrature_nodes=64)
        for index, (strike, call_price) in enumerate(zip(strikes, calls)):
            option_type = "put" if strike < spot else "call"
            price = call_price - spot * np.exp(-q * t) + strike * np.exp(-r * t) if option_type == "put" else call_price
            iv = implied_volatility(float(price), spot, float(strike), t, r, q, option_type)
            rows.append({
                "sample_role": "HOLDOUT" if index == 1 else "TRAIN",
                "expiration": expiration,
                "dte": dte,
                "time_to_expiry": t,
                "strike": float(strike),
                "option_type": option_type,
                "effective_q": q,
                "target_price": float(price),
                "heston_price": float(price),
                "target_iv": float(iv),
                "heston_iv": float(iv),
                "log_moneyness": float(np.log(strike / (spot * np.exp((r - q) * t)))),
                "moneyness_bucket": "ATM",
            })
    calibration = {
        "ok": True,
        "status": "PASS",
        "configuration_signature": "UI-CAL",
        "spot": spot,
        "risk_free_rate": r,
        "parameters": params.__dict__,
        "fit_table": pd.DataFrame(rows),
        "local_error_summary": {"worst_cell_mean_abs_iv_error": 0.0},
    }
    result = build_heston_q_simulation(calibration, paths=600, steps_per_year=182, convergence_check=False, sample_paths=2)
    lab = {"ticker": "HSIMUI", "base": {"current_price": spot}, "paths_by_horizon": {}}
    fake.session_state["mc_v260a_heston_result_HSIMUI"] = calibration
    fake.session_state["mc_v261_heston_sim_result_HSIMUI"] = result
    views._render_heston_q_simulation(lab, 30)


def test_heston_q_simulation_form_has_unique_keys_and_submit_button(monkeypatch):
    fake = _StrictFakeStreamlit()
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    for name in list(sys.modules):
        if name.startswith("monte_carlo.ui"):
            del sys.modules[name]
    views = importlib.import_module("monte_carlo.ui.views")
    lab = {"ticker": "HSIMKEY", "base": {"current_price": 100.0}, "paths_by_horizon": {}}
    views._render_heston_q_simulation(lab, 30)
    assert "mc_v261a_heston_sim_paths_HSIMKEY" in fake._widget_keys
    assert "mc_v261a_heston_sim_submit_HSIMKEY" in fake._widget_keys
    assert fake._form_submits["mc_v261a_heston_sim_form_HSIMKEY"] == 1


def test_bates_q_simulation_renderer_with_existing_result(monkeypatch):
    fake = _FakeStreamlit()
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    for name in list(sys.modules):
        if name.startswith("monte_carlo.ui"):
            del sys.modules[name]
    views = importlib.import_module("monte_carlo.ui.views")

    ticker = "BATESUI"
    bates_calibration = {
        "ok": True,
        "status": "PASS",
        "champion_status": "BATES_CHAMPION",
        "configuration_signature": "BATES-CAL",
        "fit_table": pd.DataFrame([{"dte": 30, "strike": 100.0}]),
    }
    heston_calibration = {
        "ok": True,
        "status": "WARNING",
        "configuration_signature": "HESTON-CAL",
    }
    distribution = pd.DataFrame([
        {
            "dte": 30,
            "forward_bias_bps": 2.0,
            "forward_bias_z": 0.2,
            "probability_at_least_one_jump": 0.05,
            "mean_return": 0.01,
            "median_return": 0.0,
            "var_5": -0.2,
            "es_5": -0.25,
            "var_1": -0.3,
            "es_1": -0.35,
            "prob_below_spot": 0.48,
            "terminal_variance_zero_fraction": 0.0,
            "probability_two_or_more_jumps": 0.001,
        }
    ])
    result = {
        "ok": True,
        "status": "WARNING",
        "configuration_signature": "BATES-SIM",
        "bates_calibration_signature": "BATES-CAL",
        "heston_calibration_signature": "HESTON-CAL",
        "settings": {"paths": 10_000, "steps_per_year": 365, "scheme": "Andersen QE-M"},
        "parameters": {"jump_intensity": 0.6, "jump_mean": -0.09, "jump_volatility": 0.2},
        "jump_compensator": -0.067,
        "martingale_method": "Andersen analytic QE-M + exact jump compensator",
        "distribution_summary": distribution,
        "pricing_summary": {"price_rmse": 0.1, "iv_rmse": 0.005, "confidence_coverage": 0.95},
        "time_convergence_diagnostic": {"status": "INCONCLUSIVE_MC_NOISE", "reason": "test"},
        "path_convergence_diagnostic": {"status": "PRECISION_CONVERGED", "reason": "test"},
        "path_quantiles": pd.DataFrame(),
        "jump_diagnostics": pd.DataFrame(),
        "terminal_spot_samples": pd.DataFrame({"30": [90.0, 100.0, 110.0]}),
        "heston_terminal_samples": pd.DataFrame({"30": [92.0, 100.0, 108.0]}),
        "diffusion_only_terminal_samples": pd.DataFrame({"30": [91.0, 100.0, 109.0]}),
        "pricing_validation": pd.DataFrame(),
        "heston_bates_comparison": pd.DataFrame(),
        "jump_count_summary": pd.DataFrame(),
        "jump_attribution": pd.DataFrame(),
        "maturity_validation": pd.DataFrame(),
        "moneyness_validation": pd.DataFrame(),
        "time_convergence": pd.DataFrame(),
        "path_convergence": pd.DataFrame(),
        "governance": {},
        "carry_nodes": pd.DataFrame(),
        "variance_diagnostics": pd.DataFrame(),
        "warnings": [],
        "blockers": [],
    }
    fake.session_state[f"mc_v270a_bates_result_{ticker}"] = bates_calibration
    fake.session_state[f"mc_v260a_heston_result_{ticker}"] = heston_calibration
    fake.session_state[f"mc_v271_bates_sim_result_{ticker}"] = result
    views._render_bates_q_simulation({"ticker": ticker}, 30)


def test_heston_bates_comparison_formatter_uses_explicit_units(monkeypatch):
    fake = _FakeStreamlit()
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    for name in list(sys.modules):
        if name.startswith("monte_carlo.ui"):
            del sys.modules[name]
    views = importlib.import_module("monte_carlo.ui.views")
    source = pd.DataFrame(
        [
            {
                "dte": 29,
                "bates_terminal_mean": 220.0161,
                "bates_mean_return": 0.0042,
                "bates_es_5": -0.2485,
                "bates_skewness": 0.2174,
                "bates_excess_kurtosis": 5.6236,
                "heston_forward": 220.42,
                "delta_skewness": -0.11,
            }
        ]
    )
    formatted = views._format_heston_bates_comparison_table(source)
    assert formatted.loc[0, "bates_terminal_mean"] == "220.02"
    assert formatted.loc[0, "bates_mean_return"] == "0.42%"
    assert formatted.loc[0, "bates_es_5"] == "-24.85%"
    assert formatted.loc[0, "bates_skewness"] == "0.2174"
    assert formatted.loc[0, "bates_excess_kurtosis"] == "5.6236"
    assert formatted.loc[0, "heston_forward"] == "220.42"
    assert formatted.loc[0, "delta_skewness"] == "-0.1100"
    assert source.loc[0, "bates_terminal_mean"] == 220.0161


def test_bates_role_labels_do_not_promote_research_output(monkeypatch):
    fake = _FakeStreamlit()
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    for name in list(sys.modules):
        if name.startswith("monte_carlo.ui"):
            del sys.modules[name]
    views = importlib.import_module("monte_carlo.ui.views")
    labels = views._bates_role_labels("BATES_RESEARCH_ONLY")
    assert labels["noun"] == "Bates research challenger"
    assert "champion" not in labels["comparison_title"].lower()


def test_bates_terminal_chart_uses_dynamic_source_role():
    from monte_carlo.ui.charts import _plot_bates_terminal_comparison

    result = {
        "bates_champion_status": "BATES_RESEARCH_ONLY",
        "terminal_spot_samples": pd.DataFrame({"30": [90.0, 100.0, 110.0]}),
        "heston_terminal_samples": pd.DataFrame({"30": [92.0, 100.0, 108.0]}),
        "diffusion_only_terminal_samples": pd.DataFrame({"30": [91.0, 100.0, 109.0]}),
    }
    figure = _plot_bates_terminal_comparison(result, 30)
    assert figure.data[0].name == "Bates research challenger"


def test_model_risk_download_grid_has_slot_for_model_card(monkeypatch):
    """Regression: eight download buttons require eight Streamlit columns."""
    import inspect

    fake = _FakeStreamlit()
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    for name in list(sys.modules):
        if name.startswith("monte_carlo.ui"):
            del sys.modules[name]

    views = importlib.import_module("monte_carlo.ui.views")
    source = inspect.getsource(views._render_model_risk_numerical_governance)

    assert "downloads = st.columns(8)" in source
    assert 'downloads[7].download_button("Download model card JSON"' in source
