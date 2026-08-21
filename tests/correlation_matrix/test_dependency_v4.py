import numpy as np
import pandas as pd

from correlation_matrix_section.dependency_intelligence.config import DependencyConfig
from correlation_matrix_section.dependency_intelligence.engine import DependencyIntelligence
from correlation_matrix_section.dependency_intelligence.force_model import fit_force_model
from correlation_matrix_section.dependency_intelligence.inputs import collect_force_inputs
from correlation_matrix_section.dependency_intelligence.spaces import base_currency_return
from correlation_matrix_section.dependency_intelligence.structural import lead_lag_table, jump_dependency


def _synthetic(seed=7, n=520):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range('2024-01-01', periods=n)
    mkt = rng.normal(0, .01, n)
    rates = rng.normal(0, .008, n)
    flow = rng.normal(0, .006, n)
    eps1 = rng.normal(0, .009, n)
    eps2 = rng.normal(0, .010, n)
    a = .8*mkt - .25*rates + .2*flow + eps1
    b = .65*mkt + .15*rates + .35*flow + .25*eps1 + eps2
    changes = pd.DataFrame({'A':a,'B':b,'SPY':mkt,'TLT':rates}, index=idx)
    force = pd.DataFrame({'FlowShock':flow}, index=idx)
    analysis = {
        'dependency_force_series': force,
        'dependency_force_metadata': {
            'FlowShock': {'force':'FlowShock','mechanism':'Endogenous Market','family':'Flows','input_kind':'shock'}
        }
    }
    return changes, analysis


def test_force_covariance_reconstruction_and_shapley_bridge():
    changes, analysis = _synthetic()
    inputs = collect_force_inputs(changes, analysis)
    fm = fit_force_model('A','B',changes,inputs.series,inputs.metadata,DependencyConfig(min_pair_obs=80,max_factors=6))
    assert fm.status == 'ok'
    assert abs(fm.reconstruction_error) < 1e-10
    assert len(fm.group_attribution) >= 2
    assert abs(fm.group_attribution['Systematic covariance contribution'].sum() - fm.systematic_cov) < 1e-10
    # Shapley mechanisms + residual must reconcile to raw correlation.
    total = fm.shapley_bridge['Correlation contribution'].sum()
    assert abs(total - fm.raw_corr) < 1e-8


def test_fx_base_currency_log_identity():
    idx = pd.bdate_range('2025-01-01', periods=120)
    local = pd.Series(np.linspace(-.01,.01,120), index=idx, name='EU')
    fxret = pd.Series(np.linspace(.001,-.001,120), index=idx)
    fxlevel = np.exp(fxret.fillna(0).cumsum())
    changes = pd.DataFrame({'EU':local}, index=idx)
    analysis = {
        'dependency_asset_metadata': {'EU':{'currency':'EUR'}},
        'dependency_base_currency':'USD',
        'dependency_fx_to_base': {'EUR':fxlevel},
    }
    inputs = collect_force_inputs(changes, analysis)
    out, status = base_currency_return(local,'EU',inputs)
    expected = local + np.log(fxlevel).diff()
    common = pd.concat([out,expected],axis=1).dropna()
    assert status.startswith('EUR->USD')
    assert np.max(np.abs(common.iloc[:,0]-common.iloc[:,1])) < 1e-12


def test_lead_lag_detects_primary_leads_peer():
    rng=np.random.default_rng(2)
    n=400
    idx=pd.bdate_range('2024-01-01',periods=n)
    a=pd.Series(rng.normal(size=n),index=idx)
    b=a.shift(2)+pd.Series(rng.normal(scale=.15,size=n),index=idx)
    ch=pd.DataFrame({'A':a,'B':b})
    tab=lead_lag_table('A','B',ch,max_lag=5,min_obs=80).dropna()
    best=tab.loc[tab['Abs correlation'].idxmax()]
    assert int(best['Lag days']) == 2
    assert best['Correlation'] > .9


def test_legacy_jump_alias_detects_common_extremes():
    rng=np.random.default_rng(3)
    n=500
    idx=pd.bdate_range('2024-01-01',periods=n)
    a=rng.normal(scale=.01,size=n); b=rng.normal(scale=.01,size=n)
    for k in [50,120,250,330,440]:
        a[k]+=0.12; b[k]+=0.10
    ch=pd.DataFrame({'A':a,'B':b},index=idx)
    out=jump_dependency('A','B',ch,z_threshold=3,min_obs=80)
    co=int(out.loc[out['Metric']=='Co-extreme observations','Value'].iloc[0])
    assert co >= 4


def test_full_dependency_engine_runs_with_default_proxies():
    changes, analysis=_synthetic()
    analysis['dependency_data_hub_mode'] = 'injected-only'
    dep=DependencyIntelligence(DependencyConfig(min_pair_obs=80,max_factors=6)).analyse_pair('A','B',changes,analysis)
    assert dep.status=='ok'
    assert dep.force_model.status=='ok'
    assert not dep.coverage.empty
    assert not dep.spaces.empty
    assert dep.summary['factors_used'] >= 2
