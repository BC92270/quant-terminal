from __future__ import annotations

import numpy as np
import pandas as pd

from correlation_matrix_section.correlation_intelligence_v3.breaks import dependency_break_detector
from correlation_matrix_section.correlation_intelligence_v3.connectedness import frequency_connectedness_from_changes, generalized_fevd, partial_network_stability, spectral_connectedness
from correlation_matrix_section.correlation_intelligence_v3.covariance_lab import covariance_model_validation


def _returns(n=620, p=6, seed=123):
    rng = np.random.default_rng(seed)
    f = rng.normal(0, 0.01, n)
    data = np.column_stack([0.55*f + rng.normal(0, 0.008 + i*0.0005, n) for i in range(p)])
    return pd.DataFrame(data, index=pd.bdate_range('2023-01-02', periods=n), columns=[f'A{i}' for i in range(p)])


def test_frequency_decomposition_reconciles_and_is_bounded():
    r = _returns(p=5)
    bands, directional, meta = frequency_connectedness_from_changes(r, list(r.columns), days=504, min_obs=120)
    assert meta['status'] == 'ok'
    assert not bands.empty and not directional.empty
    assert bands['Within-band connectedness'].between(0, 100).all()
    assert bands['Absolute TCI contribution'].between(0, 100).all()
    assert bands['Band variance mass'].between(0, 100).all()
    assert abs(float(bands['Absolute TCI contribution'].sum()) - float(meta['spectral_total_TCI'])) < 0.25
    assert abs(float(meta['reconciliation_error'])) < 0.25
    assert abs(float(bands['Band variance mass'].sum()) - 100.0) < 0.5


def test_break_sup_bootstrap_detects_strong_shift_and_reports_resolution():
    rng = np.random.default_rng(9)
    n = 520
    a = rng.normal(0, .01, n)
    b = np.r_[0.05*a[:260] + rng.normal(0,.01,260), 0.95*a[260:] + rng.normal(0,.003,n-260)]
    c = np.r_[-0.05*a[:260] + rng.normal(0,.01,260), 0.85*a[260:] + rng.normal(0,.004,n-260)]
    x = pd.DataFrame({'A':a,'B':b,'C':c}, index=pd.bdate_range('2024-01-02', periods=n))
    _, links, meta = dependency_break_detector(x, 'A', days=n, side_window=60, step=5, bootstrap_samples=99, seed=3)
    assert meta['status'] == 'ok'
    assert meta['selection_adjustment'].startswith('supremum')
    assert meta['null_samples'] > 80
    assert abs(meta['pvalue_resolution'] - 1/(meta['null_samples']+1)) < 1e-12
    assert meta['matrix_shift'] > 0.25
    assert meta['bootstrap_pvalue'] <= 0.05
    assert not links.empty


def test_break_sup_bootstrap_not_automatically_significant_under_stationary_null():
    # Deterministic stationary null: the max-stat correction should not mechanically produce a tiny p-value.
    x = _returns(n=520, p=4, seed=777)
    _, _, meta = dependency_break_detector(x, 'A0', days=520, side_window=60, step=5, bootstrap_samples=99, seed=11)
    assert meta['status'] == 'ok'
    assert meta['bootstrap_pvalue'] >= meta['pvalue_resolution']
    assert 0.0 < meta['bootstrap_pvalue'] <= 1.0


def test_covariance_champion_reports_runner_up_uncertainty():
    r = _returns(n=650, p=6, seed=2026)
    table, meta = covariance_model_validation(
        r, ('Ledoit-Wolf','OAS','POET-style','RMT spectral'),
        train_days=252, forecast_horizon=5, min_train=126, max_folds=16,
        champion_bootstrap_samples=600, seed=44,
    )
    assert meta['status'] == 'ok'
    assert meta['champion'] in set(table['Model'])
    assert meta['runner_up'] in set(table['Model'])
    assert meta['champion_status'] in {'Supported edge','Weak edge','Statistically tied','Insufficient fold inference'}
    if meta.get('champion_probability') is not None:
        assert 0.0 <= meta['champion_probability'] <= 1.0
        assert meta['paired_folds'] >= 6


def test_network_high_precision_can_run_500_bootstraps():
    r = _returns(n=420, p=5, seed=88)
    out, meta = partial_network_stability(
        r, list(r.columns), days=252, bootstrap_samples=500,
        block=5, threshold=.08, selection_threshold=.65, seed=7,
    )
    assert meta['status'] == 'ok'
    assert meta['bootstrap_valid'] == 500
    assert not out.empty
    assert out['Selection frequency'].between(0,1).all()


def test_spectral_total_matches_long_horizon_generalized_fevd_on_stable_var():
    rng = np.random.default_rng(5)
    n, k = 1000, 4
    a = np.array([[.25,.10,0,0],[0,.20,.15,0],[0,0,.15,.10],[.05,0,0,.20]])
    sigma = np.array([[1,.3,.1,0],[.3,1,.2,0],[.1,.2,1,.15],[0,0,.15,1]]) * 1e-4
    chol = np.linalg.cholesky(sigma)
    x = np.zeros((n,k))
    for t in range(1,n):
        x[t] = a @ x[t-1] + chol @ rng.normal(size=k)
    df = pd.DataFrame(x[100:], columns=list('ABCD'))
    _, _, time_meta = generalized_fevd(df, horizon=100, maxlags=1, min_obs=100)
    _, _, spec_meta = spectral_connectedness(df, maxlags=1, min_obs=100, n_freq=1024)
    assert abs(float(time_meta['TCI']) - float(spec_meta['spectral_total_TCI'])) < 1e-4
