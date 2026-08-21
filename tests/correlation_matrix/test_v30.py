import numpy as np
import pandas as pd

from correlation_matrix_section.correlation_intelligence_v3.config import CorrelationConfig
from correlation_matrix_section.correlation_intelligence_v3.connectedness import connectedness_from_changes, partial_network_edges
from correlation_matrix_section.correlation_intelligence_v3.engine import CorrelationEngine
from correlation_matrix_section.correlation_intelligence_v3.forward_corr import implied_average_correlation, forward_correlation_diagnostics
from correlation_matrix_section.correlation_intelligence_v3.portfolio import (
    correlation_shock_scenarios,
    incremental_asset_impact,
    portfolio_risk_decomposition,
)
from correlation_matrix_section.correlation_intelligence_v3.tail import adaptive_tail_metrics, bootstrap_tail_uncertainty


def synthetic_levels(n=650, seed=123):
    rng = np.random.default_rng(seed)
    m = rng.normal(0, 0.010, n)
    sec = 0.65*m + rng.normal(0, 0.007, n)
    rates = -0.18*m + rng.normal(0, 0.005, n)
    ret = {
        'AAA': 0.85*m + 0.65*sec + rng.normal(0,0.008,n),
        'BBB': 0.55*m + 0.50*sec + rng.normal(0,0.009,n),
        'CCC': 0.35*m + 0.25*sec + rng.normal(0,0.011,n),
        'DDD': 0.15*m + rng.normal(0,0.012,n),
        'SPY': m,
        'SMH': sec,
        'TLT': rates,
        'GLD': -0.05*m + rng.normal(0,0.008,n),
    }
    idx = pd.bdate_range('2023-01-02', periods=n)
    return pd.DataFrame({k:100*np.exp(np.cumsum(v)) for k,v in ret.items()}, index=idx)


def changes():
    lv = synthetic_levels()
    return np.log(lv/lv.shift(1))


def test_adaptive_tail_uses_longer_horizon_and_bootstrap_runs():
    ch = changes()
    m = adaptive_tail_metrics('AAA','BBB',ch,90,'Adaptive',0.10,30,756)
    assert m['Tail horizon days'] >= 250
    assert m['Lower tail obs'] >= 20
    boot = bootstrap_tail_uncertainty('AAA','BBB',ch,m['Tail horizon days'],0.10,80,5,42)
    assert boot['status'] == 'ok'
    assert boot['coex_samples'] >= 30


def test_directional_connectedness_matrix_is_row_normalized_and_has_tci():
    ch = changes()
    mat, table, meta = connectedness_from_changes(ch, ['AAA','BBB','CCC','DDD'], 252, 10, 2, 100)
    assert meta['status'] == 'ok'
    assert not mat.empty and not table.empty
    assert np.allclose(mat.sum(axis=1).values, 100.0, atol=1e-6)
    assert 0 <= meta['TCI'] <= 100
    assert 'NET transmitter' in table.columns


def test_partial_network_and_portfolio_layer():
    ch = changes()
    pc = ch[['AAA','BBB','CCC','DDD']].tail(252).corr()
    edges, central = partial_network_edges(pc, threshold=0.10)
    assert not central.empty

    w = {'AAA':0.35,'BBB':0.25,'TLT':0.20,'GLD':0.20}
    table, meta = portfolio_risk_decomposition(ch,w,252,{'AAA':'Equity','BBB':'Equity','TLT':'Rates','GLD':'Commodity'})
    assert meta['status'] == 'ok'
    assert meta['diversification_ratio'] > 0
    assert 'Risk contribution %' in table.columns
    shocks = correlation_shock_scenarios(ch,w,252,(0.1,0.2))
    assert len(shocks) == 3
    assert shocks.iloc[-1]['Annualized vol'] >= shocks.iloc[0]['Annualized vol']
    inc = incremental_asset_impact(ch,w,['CCC','SPY','SMH'],252,0.05)
    assert not inc.empty
    assert 'Δ CVaR95' in inc.columns


def test_implied_correlation_identity_and_engine_forward_hook():
    calc = implied_average_correlation(
        0.20,
        {'AAA':0.5,'BBB':0.5},
        {'AAA':0.25,'BBB':0.25},
    )
    assert calc['status'] == 'ok'
    assert -1 <= calc['implied_corr_clipped'] <= 1

    lv = synthetic_levels()
    analysis = {
        'correlation_prices': lv,
        'correlation_data_source': 'synthetic',
        'correlation_tail_mode': 'Adaptive',
        'portfolio_weights': {'AAA':0.4,'BBB':0.3,'TLT':0.15,'GLD':0.15},
        'correlation_implied_inputs': {
            'index_iv':0.20,
            'weights':{'AAA':0.5,'BBB':0.5},
            'component_ivs':{'AAA':0.25,'BBB':0.25},
            'horizon_days':63,
            'source':'synthetic options',
        },
    }
    b = CorrelationEngine(CorrelationConfig(connectedness_max_assets=5)).analyse('AAA',list(lv.columns),None,90,'2y',analysis)
    assert b.summary['status'] == 'ok'
    assert b.summary['tail_horizon'] >= 250
    assert b.connectedness_meta['status'] == 'ok'
    assert not b.portfolio_shock_table.empty
    assert b.forward_corr_meta['status'] == 'ok'
    assert b.summary['forward_implied_corr'] is not None


def test_connectedness_direction_identifies_known_transmitter():
    rng = np.random.default_rng(77)
    n = 900
    a = np.zeros(n); b = np.zeros(n); c = np.zeros(n)
    for t in range(1, n):
        a[t] = 0.2*a[t-1] + rng.normal(0,1)
        b[t] = 0.7*a[t-1] + 0.1*b[t-1] + rng.normal(0,0.6)
        c[t] = 0.5*b[t-1] + 0.1*c[t-1] + rng.normal(0,0.8)
    ch = pd.DataFrame({'A':a,'B':b,'C':c})
    mat, table, meta = connectedness_from_changes(ch, ['A','B','C'], 800, 10, 3, 100)
    assert meta['status'] == 'ok'
    assert table.iloc[0]['Asset'] == 'A'
    assert table.iloc[0]['NET transmitter'] > 0
