"""Pure synthetic tests for the new institutional normalizers.
Run inside the project environment with: python tests/test_institutional_normalizers.py
"""
from company_intelligence.institutional_data import (
    normalize_segment_payload,
    extract_relationship_disclosures,
)

sample = [
    {
        "symbol": "X",
        "date": "2025-12-31",
        "fiscalYear": 2025,
        "period": "FY",
        "reportedCurrency": "USD",
        "data": {"Cloud": 70, "Hardware": 30},
    },
    {
        "symbol": "X",
        "date": "2024-12-31",
        "fiscalYear": 2024,
        "period": "FY",
        "reportedCurrency": "USD",
        "data": {"Cloud": 50, "Hardware": 25},
    },
]

df = normalize_segment_payload(sample, "Product")
assert len(df) == 4
latest = df[df["Fiscal Year"] == 2025]
assert abs(latest["Share"].sum() - 1.0) < 1e-9
cloud = df[(df["Segment"] == "Cloud") & (df["Fiscal Year"] == 2025)].iloc[0]
assert abs(cloud["Growth"] - 0.40) < 1e-9

text = (
    "One customer accounted for 23% of our total revenue during fiscal 2025. "
    "Certain components are obtained from a single source supplier and alternative sources may not be available."
)
relationships = extract_relationship_disclosures(text)
assert relationships["Risk Type"].astype(str).str.contains("Customer concentration").any()
assert relationships["Risk Type"].astype(str).str.contains("Single-source").any()

print("PASS")
