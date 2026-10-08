"""Offline Streamlit harness for the Company Intelligence M&A workbench."""
from __future__ import annotations

import pandas as pd

from company_intelligence.mna_workbench import render_mna_workbench


peer_table = pd.DataFrame(
    [
        {"Symbol": symbol, "Company": f"Peer {symbol}", "Peer Type": "Peer", "EV/Sales": sales, "EV/EBITDA": ebitda, "P/E TTM": pe}
        for symbol, sales, ebitda, pe in (
            ("AAA", 5.0, 12.0, 25.0),
            ("BBB", 6.0, 14.0, 28.0),
            ("CCC", 7.0, 16.0, 31.0),
            ("DDD", 8.0, 18.0, 34.0),
        )
    ]
)

analysis = {
    "latest_price": 100.0,
    "company_analysis": {
        "profile": {
            "name": "Test Corporation",
            "symbol": "TST",
            "sector": "Technology",
            "industry": "Software",
            "country": "United States",
            "currency": "USD",
            "market_cap": 100_000_000_000.0,
            "enterprise_value": 105_000_000_000.0,
            "summary": "Synthetic issuer used only for deterministic interface validation.",
        },
        "growth": {
            "revenue_ttm": 20_000_000_000.0,
            "latest_net_income": 3_000_000_000.0,
            "latest_free_cash_flow": 3_500_000_000.0,
            "revenue_growth_yoy": 0.15,
        },
        "profitability": {"ebitda": 5_000_000_000.0, "ebitda_margin": 0.25, "operating_margin": 0.20},
        "valuation": {
            "market_cap": 100_000_000_000.0,
            "enterprise_value": 105_000_000_000.0,
            "trailing_pe": 33.3,
            "forward_pe": 28.0,
            "ev_to_revenue": 5.25,
            "ev_to_ebitda": 21.0,
        },
        "balance": {
            "total_cash": 10_000_000_000.0,
            "total_debt": 15_000_000_000.0,
            "free_cash_flow": 3_500_000_000.0,
            "fcf_margin": 0.175,
        },
        "analysts": {"current_price": 100.0},
        "forward": {},
        "sentiment": {},
        "raw_data": {
            "info": {"currentPrice": 100.0, "sharesOutstanding": 1_000_000_000.0, "bookValue": 20.0, "ebit": 4_000_000_000.0},
            "financials": pd.DataFrame(),
            "balance_sheet": pd.DataFrame(),
            "cashflow": pd.DataFrame(),
        },
        "institutional": {
            "peer_intelligence": {"table": peer_table, "summary": pd.DataFrame()},
            "what_changed": {
                "table": pd.DataFrame(
                    [{"Class": "Operating", "Dimension": "Growth", "Window": "TTM", "Direction": "Positive", "Materiality": 80, "Signal": "Growth", "Detail": "Improved", "Confidence": 90, "Source": "Fixture"}]
                ),
                "summary": {"bias": "Positive", "material": 1, "structural_risks": 0, "confidence": 90},
            },
            "relationships": {"summary": {}},
            "overlay": {"score": 75, "coverage": 90},
        },
    },
}

render_mna_workbench("TST", analysis)
