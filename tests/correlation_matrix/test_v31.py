from __future__ import annotations

import numpy as np
import pandas as pd

from correlation_matrix_section.correlation_intelligence_v3.breaks import dependency_break_detector
from correlation_matrix_section.correlation_intelligence_v3.connectedness import frequency_connectedness_from_changes, partial_network_stability
from correlation_matrix_section.correlation_intelligence_v3.covariance_lab import covariance_estimate, covariance_model_validation
from correlation_matrix_section.correlation_intelligence_v3.forward_corr import forward_correlation_diagnostics
from correlation_matrix_section.correlation_intelligence_v3.portfolio import portfolio_eigen_risk, structured_correlation_stress_scenarios
from correlation_matrix_section.correlation_intelligence_v3.synchronization import apply_alignment_lags, hayashi_yoshida_covariance
from correlation_matrix_section.correlation_intelligence_v3.tail_surface import pair_tail_surface


def synthetic_returns(n=720, p=6, seed=31):
    rng=np.random.default_rng(seed)
    factor=rng.normal(0,0.012,n)
    x=np.column_stack([0.5*factor+rng.normal(0,0.009+0.001*i,n) for i in range(p)])
    return pd.DataFrame(x,index=pd.bdate_range('2023-01-02',periods=n),columns=[f'A{i}' for i in range(p)])


def test_covariance_models_psd_and_validation():
    r=synthetic_returns()
    for model in ['Ledoit-Wolf','OAS','EWMA','POET-style','Factor-GLasso','RMT spectral']:
        f=covariance_estimate(r,model,days=252,min_obs=126)
        assert not f.covariance.empty
        assert np.linalg.eigvalsh(f.covariance.to_numpy()).min()>0
    tab,meta=covariance_model_validation(r,('Ledoit-Wolf','OAS','EWMA','POET-style','RMT spectral'),252,5,126,10)
    assert meta['status']=='ok' and meta['champion'] in set(tab['Model'])
    assert np.isfinite(pd.to_numeric(tab['QLIKE'])).all()


def test_break_detector_finds_large_regime_shift():
    rng=np.random.default_rng(4); n=520
    a=rng.normal(size=n)*.01
    b=np.empty(n); c=np.empty(n)
    b[:260]=.1*a[:260]+rng.normal(size=260)*.01
    c[:260]=-.1*a[:260]+rng.normal(size=260)*.01
    b[260:]=.9*a[260:]+rng.normal(size=n-260)*.004
    c[260:]=.8*a[260:]+rng.normal(size=n-260)*.004
    r=pd.DataFrame({'A':a,'B':b,'C':c},index=pd.bdate_range('2024-01-02',periods=n))
    curve,links,meta=dependency_break_detector(r,'A',days=520,side_window=60,step=5,bootstrap_samples=80,seed=7)
    assert meta['status']=='ok' and meta['matrix_shift']>0.25
    assert abs(meta['break_date']-r.index[260]).days<100
    assert not links.empty


def test_frequency_connectedness_and_network_stability():
    r=synthetic_returns(p=5)
    bands,directional,meta=frequency_connectedness_from_changes(r,list(r.columns),days=504,min_obs=120)
    assert meta['status']=='ok' and not bands.empty and not directional.empty
    assert bands['Within-band connectedness'].between(0,100).all()
    assert (bands['Absolute TCI contribution']>=0).all()
    assert abs(float(bands['Absolute TCI contribution'].sum())-float(meta['spectral_total_TCI'])) < 0.25
    stable,smeta=partial_network_stability(r,list(r.columns),days=252,bootstrap_samples=30,threshold=.08,selection_threshold=.5)
    assert smeta['status']=='ok' and not stable.empty
    assert stable['Selection frequency'].between(0,1).all()


def test_portfolio_eigen_risk_and_structured_stress():
    r=synthetic_returns(p=4)
    w={'A0':.4,'A1':.3,'A2':.2,'A3':.1}
    eig,meta=portfolio_eigen_risk(r,w,252)
    assert meta['status']=='ok'
    assert abs(float(eig['Risk share'].sum())-1)<1e-6
    stress=structured_correlation_stress_scenarios(r,w,252,{c:'Peer Equity' for c in r.columns})
    assert len(stress)>=5
    assert stress.iloc[0]['Scenario']=='Current correlation'
    assert np.isfinite(stress['Annualized vol']).all()


def test_tail_surface_multiple_quantiles():
    r=synthetic_returns(p=2)
    surf=pair_tail_surface(r,'A0','A1',days=504)
    assert {'q5 lower','q10 lower','q25 lower','q75 upper','q90 upper','q95 upper'}<=set(surf['Quantile'])
    assert surf['Co-exceedance'].between(0,1).all()


def test_synchronization_lag_and_hayashi_yoshida():
    idx=pd.date_range('2026-01-01',periods=6,freq='h')
    r=pd.DataFrame({'A':range(6),'B':range(10,16)},index=idx,dtype=float)
    aligned=apply_alignment_lags(r,{'B':1})
    assert np.isnan(aligned['B'].iloc[0]) and aligned['B'].iloc[1]==10
    a=pd.Series([0,.1,.2,.1],index=idx[[0,1,3,5]])
    b=pd.Series([0,.2,.1,.3],index=idx[[0,2,4,5]])
    assert hayashi_yoshida_covariance(a,b) is not None


def test_forward_term_structure_and_skew():
    r=synthetic_returns(p=3).rename(columns={'A0':'A','A1':'B','A2':'C'})
    analysis={
        'correlation_implied_corr':.55,
        'correlation_implied_horizon_days':63,
        'correlation_implied_term_structure':{21:.48,63:.55,126:.58},
        'correlation_implied_skew':{'Put OTM':.62,'ATM':.55,'Call OTM':.50},
    }
    meta,_=forward_correlation_diagnostics(analysis,r,63)
    assert meta['status']=='ok' and meta['term_slope']>.05
    assert meta['put_skew_vs_atm']>0 and meta['call_skew_vs_atm']<0
