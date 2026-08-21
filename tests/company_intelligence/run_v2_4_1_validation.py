from __future__ import annotations
import ast, os, sys, types, tempfile
from pathlib import Path
import pandas as pd
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

# Streamlit stub
st=types.ModuleType('streamlit')
def cache_data(*args,**kwargs):
    def deco(fn): return fn
    return deco
st.cache_data=cache_data; st.cache_resource=cache_data; st.secrets={}; st.session_state={}
def dummy(*a,**k): return None
st.__getattr__=lambda name: dummy
sys.modules['streamlit']=st

# yfinance stub
class DummyTicker:
    def __init__(self,symbol):
        self.symbol=symbol; self.info={}; self.major_holders=pd.DataFrame(); self.institutional_holders=pd.DataFrame(); self.mutualfund_holders=pd.DataFrame(); self.insider_transactions=pd.DataFrame(); self.insider_purchases=pd.DataFrame(); self.insider_roster_holders=pd.DataFrame()
        self.quarterly_financials=pd.DataFrame(); self.quarterly_cashflow=pd.DataFrame(); self.quarterly_balance_sheet=pd.DataFrame(); self.financials=pd.DataFrame(); self.cashflow=pd.DataFrame(); self.balance_sheet=pd.DataFrame()
yf=types.ModuleType('yfinance'); yf.Ticker=DummyTicker; yf.download=lambda *a,**k: pd.DataFrame(); sys.modules['yfinance']=yf

from company_intelligence import institutional_data as d
from company_intelligence import institutional_v2 as v2
from company_intelligence.institutional_metrics import calculate_roic, calculate_roic_audit, calculate_data_confidence, calculate_institutional_overlay
import company_intelligence.earnings as earnings

# 1) Segment persistence/seed fallback restores the last-known-good NVDA segment view even
# when the provider is unavailable.
orig_key=d.get_fmp_api_key
d.get_fmp_api_key=lambda: None
seg=d.load_fmp_segments('NVDA', {'raw_data': {'fmp': {}}})
d.get_fmp_api_key=orig_key
assert not seg['product'].empty, 'product seed missing'
assert not seg['geographic'].empty, 'geo seed missing'
assert 'Data Center' in set(seg['product']['Segment'])
assert 'UNITED STATES' in set(seg['geographic']['Segment'])
prod_summary=d._segment_summary(seg['product'])
geo_summary=d._segment_summary(seg['geographic'])
assert 0.88 < prod_summary['top_share'] < 0.91, prod_summary['top_share']
assert 0.68 < geo_summary['top_share'] < 0.71, geo_summary['top_share']
assert 20 < prod_summary['diversification_score'] < 30
assert 55 < geo_summary['diversification_score'] < 65
assert 'seed' in str(seg['metadata'].get('snapshot_type','')).lower() or 'snapshot' in str(seg['metadata'].get('product_source','')).lower()

# Persisted cache can be written/read under a configurable project cache directory.
with tempfile.TemporaryDirectory() as td:
    os.environ['COMPANY_INTELLIGENCE_CACHE_DIR']=td
    d._save_segment_snapshot('TEST', seg['product'].head(2), seg['geographic'].head(2), 'unit test')
    p,g,m=d._load_segment_snapshot('TEST')
    assert not p.empty and not g.empty and m.get('source_type')=='last_known_good'
os.environ.pop('COMPANY_INTELLIGENCE_CACHE_DIR',None)

# 2) One canonical ROIC formula is reused across TTM peer and capital allocation paths.
quarters=pd.date_range('2024-03-31', periods=8, freq='QE')[::-1]
rev=[55,54,54,52.94,30,30,30,30]
gp=[41,40,39,40.06,18,18,18,18]
op=[34,33,32,31.39,8,8,8,8]
pretax=[35,34,33,32,9,9,9,9]
tax=[5,5,5,5,2,2,2,2]
qfin=pd.DataFrame({q:[rev[i],gp[i],op[i],pretax[i],tax[i]] for i,q in enumerate(quarters)}, index=['Total Revenue','Gross Profit','Operating Income','Pretax Income','Tax Provision'])
fcf=[25,24,24,23.68,8,8,8,8]
qcf=pd.DataFrame({q:[fcf[i]] for i,q in enumerate(quarters)}, index=['Free Cash Flow'])
# Current and four-quarters-prior invested-capital inputs are intentionally distinct.
qbs=pd.DataFrame({q:[20+(i%2),160-2*i,30+i] for i,q in enumerate(quarters)}, index=['Total Debt','Stockholders Equity','Cash And Cash Equivalents'])

class MetricTicker(DummyTicker):
    def __init__(self,symbol):
        super().__init__(symbol)
        self.info={'marketCap':5.42e12,'longName':'NVIDIA','sector':'Technology','industry':'Semiconductors','trailingPE':34,'forwardPE':17,'enterpriseToRevenue':21,'enterpriseToEbitda':32}
        self.quarterly_financials=qfin; self.quarterly_cashflow=qcf; self.quarterly_balance_sheet=qbs
v2.yf.Ticker=MetricTicker
orig_fmp=v2._fmp_json; v2._fmp_json=lambda *a,**k: []
snap=v2._company_snapshot('NVDA')
assert snap['ROIC'] is not None and snap['ROIC']>0

cf_rows=[
 {'calendarYear':2026,'date':'2026-01-31','operatingCashFlow':102.72e9,'freeCashFlow':96.68e9,'commonStockRepurchased':-40.09e9,'dividendsPaid':-0.974e9,'stockBasedCompensation':6.39e9,'capitalExpenditure':-6.04e9,'debtRepayment':0},
 {'calendarYear':2025,'date':'2025-01-31','operatingCashFlow':64.09e9,'freeCashFlow':60.85e9,'commonStockRepurchased':-33.71e9,'dividendsPaid':-0.834e9,'stockBasedCompensation':4.74e9,'capitalExpenditure':-3.24e9,'debtRepayment':-1.25e9},
]
income=[
 {'calendarYear':2026,'operatingIncome':130.39e9,'incomeBeforeTax':132e9,'incomeTaxExpense':18e9},
 {'calendarYear':2025,'operatingIncome':81e9,'incomeBeforeTax':82e9,'incomeTaxExpense':12e9},
]
balance=[
 {'calendarYear':2026,'totalDebt':11.04e9,'totalStockholdersEquity':157.29e9,'cashAndCashEquivalents':10.61e9},
 {'calendarYear':2025,'totalDebt':10e9,'totalStockholdersEquity':79e9,'cashAndCashEquivalents':8e9},
]
company={'raw_data':{
 'info':{'marketCap':5.42e12},
 'quarterly_financials':qfin,'quarterly_cashflow':qcf,'quarterly_balance_sheet':qbs,
 'fmp':{'cashflow_annual':cf_rows,'key_metrics_annual':[],'income_annual':income,'balance_annual':balance,'income_quarterly':[],'balance_quarterly':[]},
 'cashflow':pd.DataFrame(),'financials':pd.DataFrame(),'balance_sheet':pd.DataFrame()
}}
cap=v2.load_capital_allocation_intelligence('NVDA',company)
v2._fmp_json=orig_fmp
assert abs(cap['summary']['roic']-snap['ROIC'])<1e-12, (cap['summary']['roic'],snap['ROIC'])
assert cap['summary']['roic_basis'].startswith('TTM canonical')
assert 'FY ROIC' in cap['history'].columns and cap['summary']['fy_roic'] is not None

# 3) Unified confidence penalizes missing capital-allocation fields; no 100/100 with N/As.
assert 0 < cap['confidence'] < 90, cap['confidence']
assert cap['confidence_detail']['coverage'] < 100
assert set(['coverage','source_quality','freshness','cross_validation','score']).issubset(cap['confidence_detail'])
manual_conf=calculate_data_confidence({'a':True,'b':False,'c':True},source_quality=.7,freshness=.8,cross_validation=.5)
assert 0 < manual_conf['score'] < 100 and manual_conf['coverage']<100

# 4) Overlay is separate/transparent and never mutates the core score.
overlay=calculate_institutional_overlay(
    ownership_score=56, insider_score=10, product_diversification=24,
    geographic_diversification=59, customer_risk=77, supplier_risk=22,
)
assert overlay['score'] is not None and overlay['coverage']==100
assert len(overlay['components'])==6
controller=(ROOT/'company_intelligence'/'controller.py').read_text()
assert 'Core Fundamental Score' in controller and 'Institutional Overlay' in controller
assert 'not blended' in controller

# 5) Canonical generic ROIC sanity check.
r=calculate_roic(
    operating_income=100,pretax_income=100,tax_expense=20,
    current_debt=20,current_equity=100,current_cash=10,
    prior_debt=20,prior_equity=90,prior_cash=10,
)
# IC current=110, prior=100, avg=105; NOPAT=80.
assert abs(r-(80/105))<1e-12

# 6) Existing core regression stays intact.
assert earnings.score_market_feeling({'raw_score':2,'news_count':3})==62

# Compile-time hygiene: no duplicate top-level function names in package files.
for py in (ROOT/'company_intelligence').glob('*.py'):
    tree=ast.parse(py.read_text())
    names=[n.name for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))]
    dup={x for x in names if names.count(x)>1}
    assert not dup, (py.name,dup)

# 7) Final-polish semantics / auditability.
ui=(ROOT/'company_intelligence'/'institutional_ui.py').read_text()
controller=(ROOT/'company_intelligence'/'controller.py').read_text()
assert 'Dimension Coverage' in controller and 'Institutional Coverage' not in controller
assert 'Relative Attractiveness Percentile' in ui
assert '_fmt_pp' in ui and 'taxonomy_changed' in ui and 'N/M' in ui
assert 'ROIC audit bridge — target' in ui

# Presentation helper keeps analytical percentile numeric internally while renaming only display semantics.
from company_intelligence.institutional_ui import _fmt_pp, _format_peer_summary_display
assert _fmt_pp(0.0145)=='+1.45 pp'
bridge=pd.DataFrame([{'Metric':'Forward P/E','Target':17.37,'Peer Median':26.69,'Target Percentile':80.0,'Premium / Discount':-0.3491,'Higher Is Better':False}])
display_bridge=_format_peer_summary_display(bridge)
assert 'Relative Attractiveness Percentile' in display_bridge.columns and 'Target Percentile' not in display_bridge.columns
assert display_bridge.iloc[0]['Relative Attractiveness Percentile']=='80/100'
assert bridge.iloc[0]['Target Percentile']==80.0

# ROIC audit is exactly the canonical ROIC, not a second formula.
audit=calculate_roic_audit(operating_income=100,pretax_income=100,tax_expense=20,current_debt=20,current_equity=100,current_cash=10,prior_debt=20,prior_equity=90,prior_cash=10)
assert abs(audit['roic']-r)<1e-12
assert abs(audit['tax_rate']-0.20)<1e-12
assert audit['nopat']==80
assert abs(audit['average_invested_capital']-105)<1e-12

# Target peer snapshot carries the private audit bridge without leaking it into public tables.
assert isinstance(snap.get('_ROIC Audit'),dict) and abs(snap['_ROIC Audit']['roic']-snap['ROIC'])<1e-12

print('PASS_V2_4_1')
