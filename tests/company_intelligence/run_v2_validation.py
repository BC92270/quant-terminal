"""Offline validation harness for Company Intelligence V2.

The execution environment used to build the artifact does not ship Streamlit/yfinance,
so minimal stubs are injected. The tests exercise pure analytics and provider normalizers
with synthetic payloads; no internet calls are made.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# ---- Streamlit stub ---------------------------------------------------------
st = types.ModuleType("streamlit")

def cache_data(*args, **kwargs):
    def deco(fn):
        return fn
    return deco

st.cache_data = cache_data
st.cache_resource = cache_data
st.secrets = {}
st.session_state = {}
st.spinner = lambda *a, **k: types.SimpleNamespace(__enter__=lambda self: None, __exit__=lambda self, *exc: False)
# UI attributes are looked up only when renderers run; keep permissive fallbacks.
def _dummy(*args, **kwargs):
    return None
st.__getattr__ = lambda name: _dummy
sys.modules["streamlit"] = st


# ---- yfinance stub ----------------------------------------------------------
yf = types.ModuleType("yfinance")
class DummyTicker:
    def __init__(self, symbol):
        self.symbol = symbol
        self.info = {}
        self.major_holders = pd.DataFrame()
        self.institutional_holders = pd.DataFrame()
        self.mutualfund_holders = pd.DataFrame()
        self.insider_transactions = pd.DataFrame()
        self.insider_purchases = pd.DataFrame()
        self.insider_roster_holders = pd.DataFrame()
yf.Ticker = DummyTicker
yf.download = lambda *a, **k: pd.DataFrame()
sys.modules["yfinance"] = yf


from company_intelligence.institutional_v2 import (  # noqa: E402
    build_ownership_intelligence,
    build_insider_intelligence,
    load_capital_allocation_intelligence,
    load_peer_intelligence,
    build_what_changed,
)
import company_intelligence.institutional_v2 as iv2  # noqa: E402
from company_intelligence.institutional_data import (  # noqa: E402
    normalize_segment_payload,
    extract_relationship_disclosures,
    _segment_summary,
)
import company_intelligence.earnings as earnings  # noqa: E402


# ---- Ownership V2 -----------------------------------------------------------
inst_holders = pd.DataFrame([
    {"Holder": "BlackRock Inc.", "pctHeld": 0.08, "pctChange": -0.01, "Shares": 100, "Value": 1000},
    {"Holder": "Vanguard Capital Management LLC", "pctHeld": 0.07, "pctChange": 0.04, "Shares": 90, "Value": 900},
    {"Holder": "Active Alpha Partners", "pctHeld": 0.03, "pctChange": 0.12, "Shares": 40, "Value": 400},
    {"Holder": "Long Only Capital", "pctHeld": 0.02, "pctChange": 0.06, "Shares": 30, "Value": 300},
])
funds = pd.DataFrame([
    {"Holder": "Vanguard 500 Index Fund", "pctHeld": 0.03, "pctChange": 0.01},
    {"Holder": "Growth Fund of America", "pctHeld": 0.02, "pctChange": -0.02},
])
own = build_ownership_intelligence({"institutional_holders": inst_holders, "mutualfund_holders": funds}, pd.DataFrame())
assert own["score"] is not None
assert own["summary"]["breadth"] > 0
assert own["summary"]["top10"] > 0
assert "Passive / Index" in set(own["funds"]["Holder Type"])


# ---- Insider V2: grants do NOT create a neutral score ----------------------
grants = pd.DataFrame([
    {"Text": "Stock Award(Grant) at price 0.00 per share.", "Insider": "Director A", "Position": "Director", "Shares": 1200, "Value": 0, "Start Date": "2026-07-01"},
    {"Text": "Stock Gift at price 0.00 per share.", "Insider": "Director B", "Position": "Director", "Shares": 500, "Value": 0, "Start Date": "2026-07-02"},
])
ins0 = build_insider_intelligence(pd.DataFrame(), grants)
assert ins0["score"] is None
assert ins0["summary"]["informative_count_90d"] == 0

fmp_tx = pd.DataFrame([
    {"transactionDate": "2026-07-15", "reportingName": "CEO A", "typeOfOwner": "Chief Executive Officer", "transactionType": "P-Purchase", "securitiesTransacted": 10000, "price": 100},
    {"transactionDate": "2026-07-20", "reportingName": "Director C", "typeOfOwner": "Director", "transactionType": "S-Sale", "securitiesTransacted": 1000, "price": 105},
])
ins1 = build_insider_intelligence(fmp_tx, grants)
assert ins1["score"] is not None and ins1["score"] > 50
assert set(ins1["transactions"]["Category"]).issuperset({"Open-market purchase", "Open-market sale", "Grant / award", "Gift"})


# ---- Segment taxonomy -------------------------------------------------------
segment_payload = [
    {"date": "2026-01-25", "fiscalYear": 2026, "period": "FY", "reportedCurrency": "USD", "data": {"Data Center": 90, "Gaming": 10}},
    {"date": "2025-01-25", "fiscalYear": 2025, "period": "FY", "reportedCurrency": "USD", "data": {"Data Center": 80, "Gaming": 15, "OEM": 5}},
]
seg = normalize_segment_payload(segment_payload, "Product")
seg_sum = _segment_summary(seg)
assert seg_sum["taxonomy_changed"] is True
assert "OEM" in seg_sum["removed_segments"]
assert abs(seg_sum["top_share"] - 0.90) < 1e-9


# ---- SEC relationship scanner: reject known false-positive pattern ---------
filing_text = """
ITEM 1. BUSINESS
We receive a significant amount of revenue from a limited number of customers.
For fiscal year 2026, sales to one direct customer represented 22% of total revenue.
Certain advanced components are obtained from a single source supplier and alternative sources may not be available.
Our investment portfolio contains industry sector concentration risks and a decline in securities values could hurt results.
ITEM 1A. RISK FACTORS
We depend on a limited number of foundries and manufacturing partners for production.
ITEM 1B. UNRESOLVED STAFF COMMENTS
ITEM 7. MANAGEMENT'S DISCUSSION AND ANALYSIS
Customer demand can vary between periods.
ITEM 7A. QUANTITATIVE AND QUALITATIVE DISCLOSURES
ITEM 8. FINANCIAL STATEMENTS
No additional concentration disclosure.
ITEM 9. CHANGES IN AND DISAGREEMENTS
"""
rels = extract_relationship_disclosures(filing_text)
assert rels["Risk Type"].astype(str).str.contains("Customer concentration").any()
assert rels["Risk Type"].astype(str).str.contains("Single-source").any()
assert not rels["Disclosure"].astype(str).str.contains("investment portfolio", case=False).any()
assert (pd.to_numeric(rels["Disclosed %"], errors="coerce") == 0.22).sum() == 1


# ---- Capital allocation loader with synthetic FMP payload ------------------
def fake_fmp(endpoint, params=None):
    if endpoint == "cash-flow-statement":
        return [
            {"date": "2026-01-31", "calendarYear": "2026", "freeCashFlow": 100, "operatingCashFlow": 120, "commonStockRepurchased": -20, "commonStockIssued": 2, "dividendsPaid": -3, "stockBasedCompensation": 10, "capitalExpenditure": -15, "debtRepayment": -5},
            {"date": "2025-01-31", "calendarYear": "2025", "freeCashFlow": 80, "operatingCashFlow": 95, "commonStockRepurchased": -10, "commonStockIssued": 3, "dividendsPaid": -2, "stockBasedCompensation": 12, "capitalExpenditure": -12, "debtRepayment": -2},
        ]
    if endpoint == "key-metrics":
        return [
            {"calendarYear": "2026", "marketCap": 1000, "returnOnInvestedCapital": 0.30},
            {"calendarYear": "2025", "marketCap": 800, "returnOnInvestedCapital": 0.25},
        ]
    if endpoint == "profile":
        return [{"symbol": "TEST", "marketCap": 1000}]
    return []
orig_fmp = iv2._fmp_json
iv2._fmp_json = fake_fmp
cap = load_capital_allocation_intelligence("TEST")
assert not cap["history"].empty
assert cap["score"] is not None and cap["score"] > 50
assert abs(cap["summary"]["shareholder_yield"] - 0.021) < 1e-9
iv2._fmp_json = orig_fmp


# ---- Peer engine with synthetic snapshots ----------------------------------
target_snap = {"Symbol": "NVDA", "Company": "NVIDIA", "Sector": "Technology", "Industry": "Semiconductors", "Market Cap": 5000, "Revenue Growth": 0.50, "Gross Margin": 0.70, "Operating Margin": 0.55, "FCF Margin": 0.40, "ROIC": 0.45, "FCF Yield": 0.025, "P/E TTM": 50, "Forward P/E": 30, "EV/Sales": 20, "EV/EBITDA": 35, "Source": "synthetic"}
peer_snaps = {
    "AMD": {"Symbol": "AMD", "Company": "AMD", "Sector": "Technology", "Industry": "Semiconductors", "Market Cap": 400, "Revenue Growth": 0.25, "Gross Margin": 0.52, "Operating Margin": 0.22, "FCF Margin": 0.18, "ROIC": 0.18, "FCF Yield": 0.02, "P/E TTM": 40, "Forward P/E": 28, "EV/Sales": 8, "EV/EBITDA": 25, "Source": "synthetic"},
    "AVGO": {"Symbol": "AVGO", "Company": "Broadcom", "Sector": "Technology", "Industry": "Semiconductors", "Market Cap": 2000, "Revenue Growth": 0.20, "Gross Margin": 0.75, "Operating Margin": 0.45, "FCF Margin": 0.35, "ROIC": 0.25, "FCF Yield": 0.03, "P/E TTM": 35, "Forward P/E": 25, "EV/Sales": 12, "EV/EBITDA": 22, "Source": "synthetic"},
    "AAPL": {"Symbol": "AAPL", "Company": "Apple", "Sector": "Technology", "Industry": "Consumer Electronics", "Market Cap": 4000, "Revenue Growth": 0.08, "Gross Margin": 0.46, "Operating Margin": 0.32, "FCF Margin": 0.25, "ROIC": 0.55, "FCF Yield": 0.03, "P/E TTM": 32, "Forward P/E": 29, "EV/Sales": 9, "EV/EBITDA": 24, "Source": "synthetic"},
}
orig_snap, orig_screen = iv2._company_snapshot, iv2._screener_candidates
iv2._company_snapshot = lambda s: target_snap if s == "NVDA" else peer_snaps[s]
iv2._screener_candidates = lambda sector, industry, limit=80: pd.DataFrame({"symbol": ["AMD", "AVGO", "AAPL"]})
peer = load_peer_intelligence("NVDA", ("AVGO", "AAPL"))
assert not peer["table"].empty
assert peer["table"].iloc[0]["Peer Type"] == "Target"
assert peer["table"].query("Symbol == 'AMD'").iloc[0]["Peer Type"] == "Direct / same industry"
assert peer["scores"]["relative_quality_percentile"] is not None
iv2._company_snapshot, iv2._screener_candidates = orig_snap, orig_screen


# ---- What Changed synthesis -------------------------------------------------
company = {
    "raw_data": {
        "alpha": {
            "earnings_estimates": {
                "estimates": [{
                    "date": "2027-01-31", "horizon": "fiscal year",
                    "eps_estimate_average": "10.5", "eps_estimate_average_30_days_ago": "10.0",
                    "revenue_estimate_average": "110", "revenue_estimate_average_30_days_ago": "100",
                }]
            }
        }
    },
    "sentiment": {"global_sentiment": "Plutôt positif", "raw_score": 3},
    "institutional": {
        "ownership_v2": own,
        "insider_v2": ins1,
        "product_summary": {"top_share_delta": 0.02, "taxonomy_changed": False},
        "geographic_summary": {"top_share_delta": 0.10, "taxonomy_changed": True},
        "relationships": {"summary": {"max_customer_concentration": 0.22}},
        "capital_allocation": cap,
        "sec": {"filings": pd.DataFrame([{"filingDate": pd.Timestamp.utcnow().tz_localize(None) - pd.Timedelta(days=5), "form": "8-K"}])},
        "peer_intelligence": peer,
    },
}
wc = build_what_changed(company)
assert not wc["table"].empty
assert "Estimate revisions" in set(wc["table"]["Dimension"])
geo_row = wc["table"].query("Dimension == 'Geographic concentration'").iloc[0]
assert geo_row["Direction"] == "Mixed"
assert wc["summary"]["confidence"] > 0


# ---- Core regression: NameError hotfix remains intact ----------------------
assert earnings.score_market_feeling({"raw_score": 2, "news_count": 3}) == 62
empty_bundle = {
    "info": {"symbol": "TEST"},
    "financials": pd.DataFrame(), "quarterly_financials": pd.DataFrame(),
    "balance_sheet": pd.DataFrame(), "quarterly_balance_sheet": pd.DataFrame(),
    "cashflow": pd.DataFrame(), "quarterly_cashflow": pd.DataFrame(),
    "recommendations": pd.DataFrame(), "earnings_dates": pd.DataFrame(),
    "news": [], "yf_news": [], "alpha": {}, "sec": {}, "finnhub": {},
    "fmp": {"earnings_calendar": [], "earnings_surprises": []},
}
orig_core_loader = earnings.get_company_intelligence_data
earnings.get_company_intelligence_data = lambda ticker: empty_bundle
core = earnings.analyze_company_intelligence("TEST", 100.0)
assert core["scores"]["sentiment_score"] == 50
assert "company_score" in core["scores"]
earnings.get_company_intelligence_data = orig_core_loader

print("PASS_V2")
