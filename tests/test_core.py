import numpy as np
import pandas as pd

from correlation_matrix_section.correlation_intelligence_v3.config import CorrelationConfig
from correlation_matrix_section.correlation_intelligence_v3.engine import CorrelationEngine
from correlation_matrix_section.correlation_intelligence_v3.estimators import correlation_matrix
from correlation_matrix_section.correlation_intelligence_v3.tail import empirical_tail_metrics, fit_copulas
from correlation_matrix_section.correlation_intelligence_v3.structure import rmt_diagnostics


def synthetic_prices(n=420, seed=7):
    rng=np.random.default_rng(seed)
    market=rng.normal(0,0.012,n)
    sector=0.6*market+rng.normal(0,0.009,n)
    ret={
        "AAA":0.9*market+0.7*sector+rng.normal(0,0.010,n),
        "BBB":0.7*market+0.5*sector+rng.normal(0,0.011,n),
        "CCC":-0.15*market+rng.normal(0,0.013,n),
        "SPY":market,
        "SMH":sector,
        "TLT":-0.25*market+rng.normal(0,0.006,n),
    }
    idx=pd.bdate_range("2025-01-01",periods=n)
    return pd.DataFrame({k:100*np.exp(np.cumsum(v)) for k,v in ret.items()},index=idx)


def test_engine_with_supplied_data():
    prices=synthetic_prices()
    eng=CorrelationEngine(CorrelationConfig(bootstrap_samples=50))
    b=eng.analyse("AAA",list(prices.columns),None,180,"2y",{"correlation_prices":prices,"correlation_data_source":"synthetic"})
    assert b.summary["status"]=="ok"
    assert not b.corr_shrunk.empty
    assert not b.corr_partial.empty
    assert not b.ranking.empty
    assert b.data_source=="synthetic"


def test_shrunk_matrix_psd():
    prices=synthetic_prices()
    changes=np.log(prices/prices.shift(1))
    c=correlation_matrix(changes,180,"Ledoit-Wolf",40)
    vals=np.linalg.eigvalsh(c.values)
    assert vals.min()>-1e-8


def test_tail_has_uncertainty():
    prices=synthetic_prices()
    changes=np.log(prices/prices.shift(1))
    m=empirical_tail_metrics("AAA","BBB",changes,252,0.10)
    assert "Lower CI low" in m and "Lower CI high" in m
    assert m["Lower tail obs"]>0


def test_rmt_and_copula_run():
    prices=synthetic_prices()
    changes=np.log(prices/prices.shift(1))
    s,e,l,c=rmt_diagnostics(changes,252,40)
    assert s["status"]=="ok"
    assert not e.empty and not c.empty
    fits=fit_copulas("AAA","BBB",changes,252)
    assert not fits.empty
    assert "AIC" in fits.columns
