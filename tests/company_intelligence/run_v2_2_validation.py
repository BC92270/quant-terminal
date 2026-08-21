from __future__ import annotations
import sys, types
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
yf=types.ModuleType('yfinance')
class DummyTicker:
    def __init__(self,symbol):
        self.symbol=symbol; self.info={}; self.major_holders=pd.DataFrame(); self.institutional_holders=pd.DataFrame(); self.mutualfund_holders=pd.DataFrame(); self.insider_transactions=pd.DataFrame(); self.insider_purchases=pd.DataFrame(); self.insider_roster_holders=pd.DataFrame()
yf.Ticker=DummyTicker; yf.download=lambda *a,**k: pd.DataFrame(); sys.modules['yfinance']=yf

from company_intelligence import institutional_data as d
from company_intelligence import institutional_v2 as v2
import company_intelligence.earnings as earnings

# Segment normalization: flat mapping + nested list
flat=[{'symbol':'NVDA','date':'2026-01-25','fiscalYear':2026,'period':'FY','reportedCurrency':'USD','data':{'Data Center':193.74e9,'Gaming':16.04e9}}]
f=d.normalize_segment_payload(flat,'Product')
assert len(f)==2 and abs(f['Share'].sum()-1)<1e-9
nested=[{'symbol':'NVDA','date':'2026-01-25','fiscalYear':2026,'period':'FY','data':[{'segment':'US','revenue':149.62e9},{'segment':'Taiwan','revenue':42.34e9}]}]
g=d.normalize_segment_payload(nested,'Geography')
assert len(g)==2 and abs(g['Share'].sum()-1)<1e-9

# SEC: geographic 41% must not become customer concentration
filing='''
ITEM 1A
Risk Factors
For fiscal year 2025, sales to one direct customer represented 22% of total revenue.
Revenue from sales to customers headquartered outside the United States accounted for 41% of revenue.
We depend on a limited number of foundries to manufacture our semiconductor wafers.
ITEM 1B
Other
ITEM 7
Management Discussion
For fiscal year 2024, sales to one direct customer represented 13% of total revenue.
ITEM 7A
Other
ITEM 8
Financial Statements
For fiscal year 2025, sales to one direct customer represented 12% of total revenue.
ITEM 9
Other
'''
rels=d.extract_relationship_disclosures(filing)
assert not rels.empty
assert not ((pd.to_numeric(rels['Disclosed %'],errors='coerce').fillna(-1)-.41).abs()<1e-12).any(), rels
rs=d._relationship_summary(rels)
assert abs(rs['max_customer_concentration']-.22)<1e-12, rs
assert 60 <= rs['customer_risk_score'] <= 85, rs

# Governance yfinance fallback
co={'raw_data':{'info':{'currency':'USD','companyOfficers':[{'name':'Jane CFO','title':'Chief Financial Officer','totalPay':1_000_000,'yearBorn':1970}]}}}
ex=d.normalize_yfinance_executives(co)
assert not ex.empty and ex.iloc[0]['name']=='Jane CFO'

# Ownership: mixed managers excluded from active proxy
holders=pd.DataFrame([
 {'Holder':'BlackRock Inc.','pctHeld':.08,'pctChange':-.01},
 {'Holder':'Vanguard Capital Management LLC','pctHeld':.07,'pctChange':1.0},
 {'Holder':'Active Alpha Partners','pctHeld':.03,'pctChange':.12},
 {'Holder':'Long Only Capital','pctHeld':.02,'pctChange':.06},
])
own=v2.build_ownership_intelligence({'institutional_holders':holders,'mutualfund_holders':pd.DataFrame()},pd.DataFrame())
assert own['summary']['weighted_position_change_proxy'] is not None
assert own['summary']['active_position_change_proxy'] is not None
assert abs(own['summary']['active_position_change_proxy']-own['summary']['weighted_position_change_proxy'])>1e-3

# Capital allocation: Core Financials Yahoo fallback works with FMP unavailable
cf=pd.DataFrame({
 pd.Timestamp('2025-01-31'):[100,90,-10,-8,-2,5],
 pd.Timestamp('2024-01-31'):[80,70,-8,-5,-1,4],
}, index=['Operating Cash Flow','Free Cash Flow','Capital Expenditure','Repurchase Of Capital Stock','Cash Dividends Paid','Stock Based Compensation'])
company={'raw_data':{'info':{'marketCap':1000},'fmp':{'cashflow_annual':[],'key_metrics_annual':[]},'cashflow':cf}}
orig=v2._fmp_json; v2._fmp_json=lambda *a,**k: []
cap=v2.load_capital_allocation_intelligence('TEST',company)
v2._fmp_json=orig
assert not cap['history'].empty, cap
assert cap['summary']['net_buyback'] is not None
assert cap['summary']['source']=='Yahoo cash-flow fallback'

# Peer universe survives unavailable FMP peer/screener endpoints via curated taxonomy
orig_snap,orig_screen=v2._company_snapshot,v2._screener_candidates
def snap(sym):
    base={'Symbol':sym,'Company':sym,'Sector':'Technology','Industry':'Semiconductors','Market Cap':1000,'Revenue Growth':.2,'Gross Margin':.5,'Operating Margin':.3,'FCF Margin':.2,'ROIC':.2,'FCF Yield':.03,'P/E TTM':30,'Forward P/E':25,'EV/Sales':8,'EV/EBITDA':20,'Source':'test'}
    if sym=='NVDA': base.update({'Market Cap':5000,'Revenue Growth':.8,'Gross Margin':.7,'Operating Margin':.6,'ROIC':.5,'P/E TTM':40,'Forward P/E':30})
    return base
v2._company_snapshot=snap; v2._screener_candidates=lambda *a,**k: pd.DataFrame()
peer=v2.load_peer_intelligence('NVDA',())
v2._company_snapshot, v2._screener_candidates=orig_snap,orig_screen
assert not peer['table'].empty and len(peer['table'])>=5, peer
assert 'AMD' in set(peer['table']['Symbol'])

# What Changed: structural risk excluded from directional balance
company={
 'institutional':{
  'ownership_v2':{'summary':{'weighted_position_change_proxy':.30,'breadth':.10},'score_basis':'test'},
  'insider_v2':{'score':10,'summary':{'buyers_90d':0,'sellers_90d':3}},
  'relationships':{'summary':{'max_customer_concentration':.22,'customer_confidence':95,'single_source_count':0}},
  'sec':{'filings':pd.DataFrame()},
 },
 'sentiment':{'global_sentiment':'Plutôt positif','raw_score':4}
}
wc=v2.build_what_changed(company)
assert wc['summary']['structural_risks']==1
assert 'Customer concentration' not in set(wc['table'].query("Class == 'Directional Change'")['Dimension'])
assert wc['table'].query("Dimension == 'Customer concentration'").iloc[0]['Class']=='Structural State'

# Core regression remains fixed
assert earnings.score_market_feeling({'raw_score':2,'news_count':3})==62

print('PASS_V2_2')
