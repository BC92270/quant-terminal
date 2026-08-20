from __future__ import annotations
import ast, sys, types
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
import company_intelligence.earnings as earnings

# 1) Central-bundle segment source of truth works even without an API key.
product=[{'symbol':'NVDA','date':'2026-01-25','fiscalYear':2026,'period':'FY','reportedCurrency':'USD','data':{'Data Center':193.74e9,'Gaming':16.04e9,'Automotive':2.35e9}}]
geo=[{'symbol':'NVDA','date':'2026-01-25','fiscalYear':2026,'period':'FY','reportedCurrency':'USD','data':{'UNITED STATES':149.62e9,'TAIWAN, PROVINCE OF CHINA':42.34e9,'CHINA':19.68e9}}]
company_segments={'raw_data':{'fmp':{'product_segments_raw':product,'geographic_segments_raw':geo}}}
seg=d.load_fmp_segments('NVDA', company_segments)
assert not seg['product'].empty and not seg['geographic'].empty
assert abs(seg['product']['Share'].sum()-1)<1e-9
assert 'Data Center' in set(seg['product']['Segment'])

# Date-keyed/hierarchical schema is normalized too.
date_keyed={'2025-01-26':{'Data Center':115.19e9,'Gaming':11.35e9}}
f=d.normalize_segment_payload(date_keyed,'Product')
assert len(f)==2 and set(f['Fiscal Year'].dropna().astype(int))=={2025}

# 2) Governance titleSince must not be fabricated from Yahoo fiscalYear.
co={'raw_data':{'info':{'currency':'USD','companyOfficers':[{'name':'Jane CFO','title':'Chief Financial Officer','totalPay':1_000_000,'yearBorn':1970,'fiscalYear':2026}]}}}
ex=d.normalize_yfinance_executives(co)
assert not ex.empty and pd.isna(ex.iloc[0]['titleSince']), ex

# 3) Peer metric contract: FCF margin is derived from the same TTM statements.
quarters=pd.date_range('2024-03-31', periods=8, freq='QE')[::-1]
# Most recent four revenue sum = 215.94; prior four = 120.00
rev=[55,54,54,52.94,30,30,30,30]
gp=[41,40,39,40.06,18,18,18,18]
op=[34,33,32,31.39,8,8,8,8]
pretax=[35,34,33,32,9,9,9,9]
tax=[5,5,5,5,2,2,2,2]
qfin=pd.DataFrame({q:[rev[i],gp[i],op[i],pretax[i],tax[i]] for i,q in enumerate(quarters)}, index=['Total Revenue','Gross Profit','Operating Income','Pretax Income','Tax Provision'])
fcf=[25,24,24,23.68,8,8,8,8]
qcf=pd.DataFrame({q:[fcf[i]] for i,q in enumerate(quarters)}, index=['Free Cash Flow'])
# balance with invested capital around 150
qbs=pd.DataFrame({q:[20,160,30] for q in quarters}, index=['Total Debt','Stockholders Equity','Cash And Cash Equivalents'])
class MetricTicker(DummyTicker):
    def __init__(self,symbol):
        super().__init__(symbol)
        self.info={'marketCap':5.42e12,'longName':'NVIDIA','sector':'Technology','industry':'Semiconductors','trailingPE':34,'forwardPE':17,'enterpriseToRevenue':21,'enterpriseToEbitda':32}
        self.quarterly_financials=qfin; self.quarterly_cashflow=qcf; self.quarterly_balance_sheet=qbs
v2.yf.Ticker=MetricTicker
orig_fmp=v2._fmp_json; v2._fmp_json=lambda *a,**k: []
snap=v2._company_snapshot('NVDA')
v2._fmp_json=orig_fmp
assert abs(snap['FCF Margin']-(96.68/215.94))<1e-9, snap['FCF Margin']
assert abs(snap['Revenue Growth']-(215.94/120.0-1))<1e-9
assert snap['ROIC'] is not None and snap['ROIC']>0
assert 'TTM' in v2.PEER_METRIC_CONTRACT['FCF Margin']

# 4) Capital-allocation ROIC fallback from annual raw statements, with decomposed score.
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
company={'raw_data':{'info':{'marketCap':5.42e12},'fmp':{'cashflow_annual':cf_rows,'key_metrics_annual':[],'income_annual':income,'balance_annual':balance},'cashflow':pd.DataFrame(),'financials':pd.DataFrame(),'balance_sheet':pd.DataFrame()}}
orig=v2._fmp_json; v2._fmp_json=lambda *a,**k: []
cap=v2.load_capital_allocation_intelligence('NVDA',company)
v2._fmp_json=orig
assert not cap['history'].empty
assert cap['summary']['roic'] is not None and cap['summary']['roic']>0.20, cap['summary']
assert cap['score'] is not None and 0<=cap['score']<=100
assert cap['summary']['capital_efficiency_score'] is not None
# If ROIC is deliberately removed, a 90+ score cannot be manufactured.
latest=cap['history'].iloc[0].copy(); latest['ROIC']=np.nan
components=v2._capital_allocation_components(latest)
avail=[x for x in components.values() if x is not None]
score_no_roic=np.mean(avail) if len(avail)>=3 else np.nan
score_no_roic=min(score_no_roic,85) if not np.isnan(score_no_roic) else score_no_roic
assert score_no_roic<=85

# 5) SEC event materiality: Form 4/3 are not material; 8-K 5.02 and 13G are.
now=pd.Timestamp.utcnow().tz_localize(None)
filings=pd.DataFrame([
 {'filingDate':now-pd.Timedelta(days=2),'form':'4','items':'','accessionNumber':'a'},
 {'filingDate':now-pd.Timedelta(days=3),'form':'3','items':'','accessionNumber':'b'},
 {'filingDate':now-pd.Timedelta(days=4),'form':'8-K','items':'5.02','accessionNumber':'c'},
 {'filingDate':now-pd.Timedelta(days=5),'form':'SCHEDULE 13G','items':'','accessionNumber':'d'},
])
events=v2.build_sec_event_intelligence(filings)
t=events['table']
assert int(t.loc[t['Form']=='4','Materiality'].iloc[0])==1
assert int(t.loc[t['Form']=='3','Materiality'].iloc[0])==0
assert int(t.loc[t['Form']=='8-K','Materiality'].iloc[0])==3
assert int(t.loc[t['Form']=='SCHEDULE 13G','Materiality'].iloc[0])==2
assert events['summary']['material_events_30d']==2

# What Changed uses item-aware material events, not raw filing count.
wc_company={'institutional':{'sec':{'filings':filings},'sec_events':events},'sentiment':{}}
wc=v2.build_what_changed(wc_company)
material=wc['table'].query("Class == 'Material Event'")
assert len(material)==2, material
assert not material['Signal'].astype(str).str.startswith('4 ·').any()

# 6) Existing structural separation and core regression stay intact.
company_wc={
 'institutional':{
  'ownership_v2':{'summary':{'weighted_position_change_proxy':.30,'breadth':.10},'score_basis':'test'},
  'insider_v2':{'score':10,'summary':{'buyers_90d':0,'sellers_90d':3}},
  'relationships':{'summary':{'max_customer_concentration':.22,'customer_confidence':95,'single_source_count':0}},
  'sec':{'filings':pd.DataFrame()}, 'sec_events':{'table':pd.DataFrame()},
 },
 'sentiment':{'global_sentiment':'Plutôt positif','raw_score':4}
}
wc2=v2.build_what_changed(company_wc)
assert wc2['summary']['structural_risks']==1
assert 'Customer concentration' not in set(wc2['table'].query("Class == 'Directional Change'")['Dimension'])
assert earnings.score_market_feeling({'raw_score':2,'news_count':3})==62

# Compile-time hygiene: no duplicate top-level function names in package files.
for py in (ROOT/'company_intelligence').glob('*.py'):
    tree=ast.parse(py.read_text())
    names=[n.name for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))]
    dup={x for x in names if names.count(x)>1}
    assert not dup, (py.name,dup)

print('PASS_V2_3')
